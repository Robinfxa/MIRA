"""Authenticated bounded media data paths, separate from presentation receipts."""
import asyncio
import base64
import binascii
import json
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from mira.application.diagnostic_errors import classify_failure, public_error_code
from mira.application.diagnostic_events import (
    CancellationReason, DiagnosticCode, DiagnosticEvent, DiagnosticOutcome, DiagnosticStage,
    RecordingKind,
    diagnostic_context, emit_safely, failure_diagnostic_id, request_correlation,
)
from mira.application.ports.reviewed_audio import AudioCaptureHandle, AudioCaptureOwner
from mira.application.media_runtime import MediaOperation, MicrophoneBuffer
from mira.application.ports.media import TranscriptRevision
from mira.domain.errors import DomainError
from mira.entrypoints.http.routes import ContainerDependency, Token
from mira.entrypoints.http.schemas import (
    ErrorResponse, MicrophoneAudio, MicrophoneComplete, MicrophoneControl, MicrophoneError,
    MicrophoneReady, MicrophoneStart, MicrophoneTranscript, SpeechAudioFrame,
    SpeechCompleteFrame, SpeechErrorFrame, SpeechStreamRequest, VoiceCapabilities,
)

# Explicit descriptions keep exports independent of Python's HTTP status phrases.
router = APIRouter(prefix="/api/v1", responses={
    400: {"model": ErrorResponse, "description": "Bad Request"},
    404: {"model": ErrorResponse, "description": "Not Found"},
    409: {"model": ErrorResponse, "description": "Conflict"},
    422: {"model": ErrorResponse, "description": "Unprocessable Content"},
    503: {"model": ErrorResponse, "description": "Service Unavailable"},
})


@router.get("/voice-capabilities", response_model=VoiceCapabilities)
async def voice_capabilities(container: ContainerDependency) -> VoiceCapabilities:
    return VoiceCapabilities(generation_mode=container.generation_mode,
                             speech_enabled=container.speech_enabled,
                             microphone_enabled=container.microphone_enabled,
                             qualification="offline_fixture" if container.generation_mode == "rehearsal" else "injected_unverified" if (
                                 container.speech_enabled or container.microphone_enabled
                             ) else "unavailable")


@router.post("/sessions/{session_id}/speech/{effect_id}/stream",
             responses={200: {"content": {"application/x-ndjson": {"schema": {
                 "oneOf": [{"$ref": "#/components/schemas/" + name} for name in
                           ("SpeechAudioFrame", "SpeechCompleteFrame", "SpeechErrorFrame")]
             }}}}}, response_class=StreamingResponse)
async def speech_stream(session_id: UUID, effect_id: UUID, body: SpeechStreamRequest,
                        token: Token, container: ContainerDependency) -> StreamingResponse:
    actor = container.sessions.get(str(session_id), token)
    operation = await actor.open_speech(effect_id=str(effect_id), digest=body.digest,
                                       output_epoch=body.output_epoch, activity_seq=body.activity_seq)
    owner = AudioCaptureOwner(
        session_id=str(session_id),
        turn_id=str(operation.output_epoch),
        stream_id=str(effect_id),
        effect_id=str(effect_id),
        output_epoch=operation.output_epoch,
    )
    capture = container.reviewed_audio
    capture_result = capture.begin_scoped(owner, sample_rate_hz=24000,
                                          kind=RecordingKind.AUDIO_OUTPUT)
    capture_handle = capture_result.handle if capture_result.ok else None
    origin = dict(effect_id=str(effect_id), digest=body.digest, output_epoch=body.output_epoch,
                  activity_seq=body.activity_seq, stream_id=str(effect_id))
    stream_succeeded = False

    async def frames():
        nonlocal stream_succeeded
        cursor, sequence = 0, 0
        try:
            async for packet in operation.values():
                await actor.validate_media(operation)
                if capture_handle is not None:
                    # speech_packets has already checked the PCM16LE format, stream/effect identity,
                    # sample rate, continuity and chunk bound before the packet reaches this edge.
                    capture.append_scoped(owner, capture_handle, packet.pcm)
                cursor = packet.first_sample + len(packet.pcm) // 2
                sequence += 1
                yield SpeechAudioFrame(**origin, sequence=sequence, first_sample=packet.first_sample,
                    pcm_base64=base64.b64encode(packet.pcm).decode("ascii")).model_dump_json() + "\n"
            await actor.validate_media(operation)
            yield SpeechCompleteFrame(**origin, total_samples=cursor).model_dump_json() + "\n"
            # Set only after the complete frame has actually been sent by the streaming consumer.
            stream_succeeded = True
        except DomainError as error:
            if error.code != "media_cancelled":
                await actor.media_failed(operation, error.code)
            yield SpeechErrorFrame(**origin, code=public_error_code(error.code),
                                   diagnostic_id=operation.diagnostic_id).model_dump_json() + "\n"
        finally:
            if capture_handle is not None and not stream_succeeded:
                capture.cancel_session(str(session_id), stream_id=owner.stream_id)
            await actor.close_media(operation, CancellationReason.DISCONNECT)

    class OwnedStreamResponse(StreamingResponse):
        async def __call__(self, scope, receive, send):
            try:
                await super().__call__(scope, receive, send)
            finally:
                if capture_handle is not None and not stream_succeeded:
                    capture.cancel_session(str(session_id), stream_id=owner.stream_id)
                await actor.close_media(operation, CancellationReason.DISCONNECT)

    return OwnedStreamResponse(frames(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


async def _message(websocket: WebSocket, *, timeout: float = 10) -> dict:
    async with asyncio.timeout(timeout):
        message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    text = message.get("text")
    if not isinstance(text, str) or len(text) > 20000:
        raise DomainError("invalid_input", "Expected a bounded JSON media message.")
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        raise DomainError("invalid_input", "Invalid media message.") from None
    if not isinstance(value, dict):
        raise DomainError("invalid_input", "Invalid media message.")
    return value


async def _read_microphone(websocket: WebSocket, buffer: MicrophoneBuffer, actor,
                           operation: MediaOperation, capture, capture_owner: AudioCaptureOwner,
                           capture_handle: AudioCaptureHandle | None) -> None:
    while True:
        raw = await _message(websocket)
        await actor.validate_media(operation)
        if raw.get("type") == "audio":
            value = MicrophoneAudio.model_validate(raw)
            try:
                pcm = base64.b64decode(value.pcm_base64, validate=True)
            except (ValueError, binascii.Error):
                raise DomainError("invalid_audio", "Invalid PCM encoding.") from None
            buffer.push(sequence=value.sequence, first_sample=value.first_sample, pcm=pcm)
            if capture_handle is not None:
                # Only append after the live input boundary has validated and accepted this chunk.
                capture.append_scoped(capture_owner, capture_handle, pcm)
        else:
            control = MicrophoneControl.model_validate(raw)
            if control.type == "cancel":
                operation.cancel(CancellationReason.USER_STOP)
                raise DomainError("media_cancelled", "Microphone was cancelled.")
            if buffer.finished:
                raise DomainError("invalid_input", "Microphone input has already finished.")
            await buffer.finish()
            # Keep receiving disconnect/cancel while recognition drains.


async def _send_transcripts(websocket: WebSocket, buffer: MicrophoneBuffer, actor,
                            operation: MediaOperation, capture, capture_owner: AudioCaptureOwner,
                            capture_handle: AudioCaptureHandle | None) -> None:
    revision, final_text, had_final = 0, "", False
    async for value in operation.values():
        await actor.validate_media(operation)
        if (not isinstance(value, TranscriptRevision) or value.input_stream_id != buffer.stream_id
                or type(value.revision) is not int or value.revision <= revision
                or value.revision > 10000 or not isinstance(value.text, str)
                or len(value.text) > 2000 or type(value.is_final) is not bool):
            raise DomainError("invalid_response", "Invalid transcript revision.")
        revision = value.revision
        had_final = value.is_final and bool(value.text.strip())
        if value.is_final:
            final_text = value.text
        await websocket.send_text(MicrophoneTranscript(stream_id=buffer.stream_id,
            revision=revision, text=value.text, is_final=value.is_final).model_dump_json())
    await actor.validate_media(operation)
    if not buffer.finished:
        raise DomainError("incomplete_stream", "Recognition ended before microphone finish.")
    if had_final and capture_handle is not None:
        # The server binds this exact final transcript to the authenticated stream before telling
        # the client completion succeeded. A later input may preserve only this one-use pairing.
        capture.register_input_completion(capture_owner, capture_handle, final_text)
    await websocket.send_text(MicrophoneComplete(stream_id=buffer.stream_id, revision=revision,
        text=final_text if had_final else "", had_final=had_final).model_dump_json())


@router.websocket("/sessions/{session_id}/microphone")
async def microphone(websocket: WebSocket, session_id: str) -> None:
    container = websocket.app.state.container
    # Browser cookies are never authority. No token is accepted in a logged URL.
    if (websocket.headers.get("origin") not in container.settings.http.allowed_origins
            or websocket.query_params):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    context_token = request_correlation.set(str(uuid4()))
    close_reason = CancellationReason.UNKNOWN
    operation, buffer, actor = None, None, None
    capture_owner, capture_handle = None, None
    microphone_succeeded = False
    tasks: list[asyncio.Task] = []
    try:
        UUID(session_id)
        start = MicrophoneStart.model_validate(await _message(websocket, timeout=5))
        actor = container.sessions.get(session_id, start.session_token)
        buffer = MicrophoneBuffer(str(start.stream_id))
        operation = await actor.open_microphone(stream_id=buffer.stream_id,
            activity_seq=start.activity_seq, input_epoch=start.input_epoch, buffer=buffer)
        capture_owner = AudioCaptureOwner(
            session_id=session_id,
            turn_id=None,
            stream_id=buffer.stream_id,
            input_epoch=operation.input_epoch,
        )
        capture = container.reviewed_audio
        capture_result = capture.begin_scoped(capture_owner, sample_rate_hz=16000,
                                              kind=RecordingKind.AUDIO_INPUT)
        capture_handle = capture_result.handle if capture_result.ok else None
        await websocket.send_text(MicrophoneReady(stream_id=buffer.stream_id,
            activity_seq=start.activity_seq, input_epoch=start.input_epoch).model_dump_json())
        reader = asyncio.create_task(_read_microphone(websocket, buffer, actor, operation,
            capture, capture_owner, capture_handle))
        sender = asyncio.create_task(_send_transcripts(websocket, buffer, actor, operation,
            capture, capture_owner, capture_handle))
        tasks = [reader, sender]
        operation.own_consumers(*tasks)
        async with asyncio.timeout(75):
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            # Receiver remains alive through drain so close/cancel always tears down STT.
            # If both finish simultaneously, reject malformed/cancelled input first.
            if reader in done:
                try:
                    await reader
                except WebSocketDisconnect:
                    # The client normally closes immediately after receiving MicrophoneComplete.
                    # That completed stream remains reviewable; an earlier disconnect still cancels.
                    if not (sender.done() and not sender.cancelled()
                            and sender.exception() is None):
                        raise
            await sender
            microphone_succeeded = True
    except asyncio.CancelledError:
        close_reason = CancellationReason.DISCONNECT
        raise
    except WebSocketDisconnect:
        close_reason = CancellationReason.DISCONNECT
        emit_safely(container.diagnostics, DiagnosticEvent(DiagnosticStage.MICROPHONE,
            DiagnosticOutcome.CANCELLED, diagnostic_context(session_id=session_id),
            code=DiagnosticCode.DISCONNECTED, cancellation_reason=close_reason))
    except (DomainError, ValidationError, ValueError, TimeoutError) as error:
        code = public_error_code(error.code) if isinstance(error, DomainError) else (
            "timeout" if isinstance(error, TimeoutError) else "invalid_input")
        close_reason = CancellationReason.USER_STOP if code == "media_cancelled" else CancellationReason.UNKNOWN
        if operation is not None:
            operation.cancel(close_reason)
        emit_safely(container.diagnostics, DiagnosticEvent(DiagnosticStage.MICROPHONE,
            DiagnosticOutcome.CANCELLED if code == "media_cancelled" else DiagnosticOutcome.FAILED,
            diagnostic_context(session_id=session_id), code=classify_failure(error).code,
            cancellation_reason=close_reason if code == "media_cancelled" else None))
        try:
            await websocket.send_text(MicrophoneError(code=code, diagnostic_id=failure_diagnostic_id(
                diagnostic_context(session_id=session_id))).model_dump_json())
        except (WebSocketDisconnect, RuntimeError):
            pass
    finally:
        if buffer is not None:
            buffer.clear()
        request_correlation.reset(context_token)
        if operation is not None:
            # This call revokes and registers all owned cleanup synchronously;
            # repeated outer cancellation cannot skip either step.
            cleanup = actor.close_media(operation, close_reason)
            if capture_handle is not None and not microphone_succeeded:
                container.reviewed_audio.cancel_session(session_id, stream_id=buffer.stream_id)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await cleanup
        try:
            await websocket.close(code=1000)
        except (WebSocketDisconnect, RuntimeError):
            pass
