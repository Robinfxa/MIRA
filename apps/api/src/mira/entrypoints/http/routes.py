from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from mira.bootstrap.container import Container
from mira.domain.models import AudioProgress, Receipt
from mira.entrypoints.http.mappers import session_view
from mira.entrypoints.http.schemas import (
    AudioProgressRequest, AuditEventView, CreateSessionRequest, CreateSessionResponse, ErrorResponse,
    DiagnosticsStatusResponse, HealthResponse, InputRequest, ReceiptRequest, SessionView, StopRequest,
    ResponsePreferenceRequest, PhotoDismissRequest, FixedPhotoProgressRequest, StoryImageCompletionRequest,
)

# Explicit descriptions keep exports independent of Python's HTTP status phrases.
router = APIRouter(prefix="/api/v1", responses={
    400: {"model": ErrorResponse, "description": "Bad Request"},
    404: {"model": ErrorResponse, "description": "Not Found"},
    422: {"model": ErrorResponse, "description": "Unprocessable Content"},
    409: {"model": ErrorResponse, "description": "Conflict"},
})
Token = Annotated[str, Header(alias="X-Mira-Session-Token")]


def container_from(request: Request) -> Container:
    return request.app.state.container


ContainerDependency = Annotated[Container, Depends(container_from)]


@router.get("/health", response_model=HealthResponse)
async def health(container: ContainerDependency) -> HealthResponse:
    # Keep the foundation health fixture-family contract; capabilities names replay.
    return HealthResponse(mode="mock" if container.generation_mode == "replay" else container.generation_mode,
                          live_llm=None if container.generation_mode == "injected" else False,
                          live_audio=False if container.generation_mode == "rehearsal" else None if (
                              container.speech_enabled or container.microphone_enabled) else False)


@router.get("/diagnostics-status", response_model=DiagnosticsStatusResponse)
async def diagnostics_status(container: ContainerDependency) -> DiagnosticsStatusResponse:
    try:
        state = container.diagnostics.status()
        return DiagnosticsStatusResponse(available=state.available,
            recording_active=state.recording_active, notice=state.notice,
            dropped_events=state.dropped_events, dropped_recordings=state.dropped_recordings,
            io_failures=state.io_failures, pending_records=state.pending_records)
    except Exception:
        return DiagnosticsStatusResponse(available=False, recording_active=False,
            notice="诊断状态暂不可用，请勿输入秘密。", dropped_events=0,
            dropped_recordings=0, io_failures=1, pending_records=0)


@router.post("/sessions", response_model=CreateSessionResponse, status_code=201)
async def create_session(body: CreateSessionRequest, request: Request, container: ContainerDependency) -> CreateSessionResponse:
    devices = getattr(request.app.state, "device_sessions", None)
    if devices is None:
        actor, token = container.sessions.create(str(body.client_instance_id))
    else:
        actor, token = await devices.create(request.state.device_identity, str(body.client_instance_id),
                                           container, request.app.state.operator_pairing,
                                           media_allowed=getattr(request.state, "mira_voice_allowed", True))
    try:
        container.diagnostics.add_secret(token)
    except Exception:
        pass
    return CreateSessionResponse(session=session_view(await actor.snapshot()), session_token=token)


@router.get("/sessions/{session_id}", response_model=SessionView)
async def get_session(session_id: UUID, token: Token, container: ContainerDependency) -> SessionView:
    return session_view(await container.sessions.get(str(session_id), token).snapshot())


@router.post("/sessions/{session_id}/inputs", response_model=SessionView, status_code=202)
async def submit_input(session_id: UUID, body: InputRequest, token: Token,
                       container: ContainerDependency) -> SessionView:
    session_key = str(session_id)
    actor = container.sessions.get(session_key, token)
    from mira.domain.chapter_presentation import ChapterChoice
    chapter_choice = (ChapterChoice(**body.chapter_choice.model_dump(mode='json'))
                      if body.chapter_choice is not None else None)
    same_audio_input = (body.source_audio_stream_id is not None and
        container.reviewed_audio.consume_input_completion(
            session_key, str(body.source_audio_stream_id), str(body.request_id), body.text.strip()))
    listening_final = False
    if body.listening_utterance_id is not None:
        await container.listening_leases.validate_submission(
            session_key, str(body.listening_utterance_id), str(body.request_id), body.text.strip())
        listening_final = True
    state = await actor.submit(
        request_id=str(body.request_id), activity_seq=body.activity_seq,
        cutoff=body.presentation_cutoff, text=body.text.strip(),
        source="asr_final" if same_audio_input or listening_final else "text",
        relation=body.relation,
        continuation_of_request_id=(str(body.continuation_of_request_id)
                                    if body.continuation_of_request_id is not None else None),
        continuation_of_output_epoch=body.continuation_of_output_epoch,
        chapter_choice=chapter_choice,
    )
    if listening_final:
        await container.listening_leases.mark_accepted(
            session_key, str(body.listening_utterance_id), str(body.request_id), body.text.strip())
    # A matching ASR commit is the same microphone input. Other new text/input replaces the stage.
    if not same_audio_input:
        container.reviewed_audio.cancel_session(session_key)
    return session_view(state)


@router.post("/sessions/{session_id}/response-preference", response_model=SessionView)
async def set_response_preference(session_id: UUID, body: ResponsePreferenceRequest, token: Token,
                                  container: ContainerDependency) -> SessionView:
    actor = container.sessions.get(str(session_id), token)
    return session_view(await actor.set_response_preference(
        muted=body.muted, expected_revision=body.expected_revision))


@router.post("/sessions/{session_id}/stop", response_model=SessionView)
async def stop_session(session_id: UUID, body: StopRequest, token: Token,
                       container: ContainerDependency) -> SessionView:
    session_key = str(session_id)
    actor = container.sessions.get(session_key, token)
    if body.scope == "all":
        await container.listening_leases.stop_session(session_key, "user_stop")
    state = await actor.stop(
        activity_seq=body.activity_seq, cutoff=body.presentation_cutoff, scope=body.scope,
    )
    container.reviewed_audio.cancel_session(session_key)
    return session_view(state)


@router.post('/sessions/{session_id}/photo-dismissals', response_model=SessionView)
async def dismiss_photo(session_id: UUID, body: PhotoDismissRequest, token: Token,
                        container: ContainerDependency) -> SessionView:
    return session_view(await container.sessions.get(str(session_id), token).dismiss_photo(
        request_id=str(body.request_id), expected_revision=body.expected_revision,cutoff=body.presentation_cutoff,
        target=body.target,expected_photo_effect_id=str(body.expected_photo_effect_id) if body.expected_photo_effect_id else None,
        expected_image_request_id=str(body.expected_image_request_id) if body.expected_image_request_id else None))


@router.post('/sessions/{session_id}/fixed-photo-progress', response_model=SessionView)
async def fixed_photo_progress(session_id: UUID, body: FixedPhotoProgressRequest, token: Token,
                               container: ContainerDependency) -> SessionView:
    return session_view(await container.sessions.get(str(session_id), token).fixed_photo_progress(
        effect_id=str(body.effect_id), digest=body.digest, output_epoch=body.output_epoch,
        activity_seq=body.activity_seq, outcome=body.outcome))


@router.post("/sessions/{session_id}/receipts", response_model=SessionView)
async def record_receipt(session_id: UUID, body: ReceiptRequest, token: Token,
                         container: ContainerDependency) -> SessionView:
    receipt = Receipt(str(body.effect_id), body.digest, body.output_epoch, body.activity_seq,
                      body.presentation_seq)
    return session_view(await container.sessions.get(str(session_id), token).receipt(receipt))


@router.post("/sessions/{session_id}/audio-progress", response_model=SessionView)
async def record_audio_progress(session_id: UUID, body: AudioProgressRequest, token: Token,
                                container: ContainerDependency) -> SessionView:
    progress = AudioProgress(str(body.effect_id), body.digest, body.output_epoch,
                             body.activity_seq, body.presentation_seq, body.sample_rate_hz,
                             body.rendered_samples, body.status)
    return session_view(await container.sessions.get(str(session_id), token).audio_progress(progress))


@router.get("/sessions/{session_id}/events", response_model=list[AuditEventView])
async def events(session_id: UUID, token: Token, container: ContainerDependency) -> list[AuditEventView]:
    container.sessions.get(str(session_id), token)
    return [AuditEventView(**{k: v for k, v in asdict(e).items() if k != "session_id"})
            for e in container.journal.read(str(session_id))]


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: UUID, token: Token, request: Request, container: ContainerDependency) -> Response:
    session_key = str(session_id)
    devices = getattr(request.app.state, "device_sessions", None)
    if devices is not None:
        await devices.delete(request.state.device_identity, session_key, token, container)
        return Response(status_code=204)
    container.sessions.get(session_key, token)
    container.reviewed_audio.cancel_session(session_key)
    await container.listening_leases.close_session(session_key)
    await container.sessions.delete(session_key, token)
    return Response(status_code=204)


@router.post('/sessions/{session_id}/story-image-completions',response_model=SessionView,status_code=202)
async def story_image_completion(session_id: UUID,body: StoryImageCompletionRequest,token: Token,
                                 container: ContainerDependency) -> SessionView:
    return session_view(await container.sessions.get(str(session_id),token).complete_story_image(
        request_id=str(body.request_id),parent_request_id=str(body.parent_request_id),
        output_epoch=body.output_epoch,activity_seq=body.activity_seq,
        presented_effect_id=str(body.presented_effect_id) if body.presented_effect_id else None))
