"""Authenticated, one-stream-per-lease continuous listening WebSocket."""
import asyncio
import base64
from dataclasses import replace
import binascii
import json
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from mira.application.continuous_listening import ListeningEvent, ListeningLease
from mira.application.diagnostic_events import request_correlation
from mira.domain.errors import DomainError
from mira.entrypoints.http.schemas import (
    ContinuousListeningAudio, ContinuousListeningEndpointPending,
    ContinuousListeningReady, ContinuousListeningStart, ContinuousListeningStop,
    ContinuousListeningStopped, ContinuousListeningTranscript,
    ContinuousListeningCommit, ContinuousListeningCommitReady,
    ContinuousListeningCommitRejected,
    ContinuousListeningUtteranceReady, ContinuousListeningUtteranceRevision,
    ContinuousListeningRecognitionStatus,
    ContinuousListeningClientEndpoint, ContinuousListeningCancelEndpoint, ContinuousListeningEndpointStatus,
    ContinuousListeningHold, ContinuousListeningHeld, ContinuousListeningHoldRejected,
)

router = APIRouter()


def _no_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


async def _message(websocket: WebSocket, *, timeout: float = 10) -> dict:
    async with asyncio.timeout(timeout):
        raw = await websocket.receive()
    if raw["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(raw.get("code", 1000))
    text = raw.get("text")
    if not isinstance(text, str) or len(text) > 20_000:
        raise DomainError("invalid_input", "Expected a bounded JSON listening message.")
    try:
        value = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except (ValueError, RecursionError):
        raise DomainError("invalid_input", "Invalid listening message.") from None
    if not isinstance(value, dict):
        raise DomainError("invalid_input", "Invalid listening message.")
    return value


def _origin_host_allowed(websocket: WebSocket) -> bool:
    container = websocket.app.state.container
    allowed_origins = getattr(websocket.app.state, "http_allowed_origins", container.settings.http.allowed_origins)
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if not isinstance(origin, str) or not isinstance(host, str):
        return False
    if origin not in allowed_origins:
        return False
    try:
        expected_host = urlsplit(origin).netloc
    except ValueError:
        return False
    allowed_hosts = {urlsplit(value).netloc for value in allowed_origins}
    # TestClient's host is accepted only for offline ASGI tests, not configured deployments.
    if host.lower() == "testserver":
        return container.settings.environment == "test" and origin.startswith("http://")
    return host.lower() == expected_host.lower() and host.lower() in {item.lower() for item in allowed_hosts}


def _usage_budget(websocket: WebSocket) -> tuple[int | None, int | None]:
    container = websocket.app.state.container
    budget = getattr(container, "stt_request_budget", None)
    if budget is None:
        return None, None
    snapshot = budget.snapshot()
    declaration = getattr(websocket.app.state, "usage_declaration", None)
    declared_limit = getattr(declaration, "stt_requests", None)
    if (declaration is not None and getattr(declaration, "stt_max_stream_seconds", None) is not None
            and declared_limit != snapshot.limit):
        raise DomainError("unavailable", "STT request declaration does not match its shared budget.")
    current = getattr(websocket.app.state, "usage_snapshot", None)
    if declaration is not None and current is not None:
        try:
            websocket.app.state.usage_snapshot = replace(current, stt_requests_used=snapshot.used)
        except (TypeError, ValueError):
            # A malformed optional telemetry snapshot never weakens the actual request counter.
            pass
    return snapshot.used, snapshot.remaining


def _wire_event(event: ListeningEvent):
    if event.type == "endpoint_status":
        return ContinuousListeningEndpointStatus(lease_id=UUID(event.lease_id),
            endpoint_id=UUID(event.endpoint_id), source_end_sample=event.source_end_sample,
            state=event.endpoint_state)
    if event.type == "recognition_status":
        return ContinuousListeningRecognitionStatus(lease_id=UUID(event.lease_id),
            stream_index=event.stream_index, state=event.recognition_state,
            stt_requests_used=event.stt_requests_used,
            stt_requests_remaining=event.stt_requests_remaining)
    if event.type == "utterance_ready":
        return ContinuousListeningUtteranceReady(lease_id=UUID(event.lease_id),
            utterance_id=UUID(event.utterance_id), revision=event.revision, text=event.text,
            begin_offset_samples=event.begin_offset_samples,
            end_offset_samples=event.end_offset_samples, final_offset_samples=event.final_offset_samples,
            endpoint_basis=event.endpoint_basis, source_end_sample=event.source_end_sample,
            client_endpoint_id=UUID(event.client_endpoint_id) if event.client_endpoint_id else None)
    if event.type == "utterance_revision":
        return ContinuousListeningUtteranceRevision(lease_id=UUID(event.lease_id),
            utterance_id=UUID(event.utterance_id), commit_id=UUID(event.commit_id),
            revision=event.revision, text=event.text, submission_state=event.submission_state)
    if event.type == "transcript":
        return ContinuousListeningTranscript(lease_id=UUID(event.lease_id), revision=event.revision,
            text=event.text or "", is_final=bool(event.is_final),
            committed_commit_id=UUID(event.commit_id) if event.commit_id else None,
            committed_utterance_id=UUID(event.utterance_id) if event.utterance_id else None)
    if event.type == "endpoint_pending":
        reason = event.reason if event.reason in {"missing_result_offset", "unmatched_activity_end"} else "missing_result_offset"
        return ContinuousListeningEndpointPending(lease_id=UUID(event.lease_id),
            revision=event.revision, text=event.text or "", reason=reason,
            can_submit_manually=True)
    if event.type == "stopped":
        allowed = {"user_stop", "permission_lost", "replaced", "max_duration", "max_samples",
            "queue_limit", "revision_limit", "utterance_limit", "provider_stream_ended",
            "unavailable", "invalid_input", "invalid_response", "session_closed", "disconnect",
            "output_limit", "session_capacity", "microphone_unavailable", "input_limit", "invalid_audio",
            "timeout", "unauthenticated", "permission_denied", "quota_exhausted", "media_cancelled",
            "incomplete_stream", "blocked", "response_limit", "service_budget_exhausted"}
        reason = event.reason if event.reason in allowed else "unavailable"
        return ContinuousListeningStopped(lease_id=UUID(event.lease_id), reason=reason,
                                          diagnostic_id=event.diagnostic_id)
    raise DomainError("invalid_response", "Invalid listening event.")


@router.websocket("/api/v1/sessions/{session_id}/continuous-listening")
async def continuous_listening(websocket: WebSocket, session_id: str) -> None:
    """Begin one authorized stream only after a session-scoped start frame is validated."""
    if not _origin_host_allowed(websocket) or websocket.query_params or len(session_id) > 64:
        await websocket.close(code=1008)
        return
    try:
        parsed_session_id = str(UUID(session_id))
    except ValueError:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    correlation = request_correlation.set(str(uuid4()))
    container = websocket.app.state.container
    registry = container.listening_leases
    lease: ListeningLease | None = None
    receive_task: asyncio.Task | None = None
    event_task: asyncio.Task | None = None
    close_reason = "disconnect"
    try:
        try:
            start = ContinuousListeningStart.model_validate(await _message(websocket, timeout=5))
        except (DomainError, ValidationError, TimeoutError):
            await websocket.close(code=1008)
            return
        # Token is in the first frame, never URL/query/logs. Authentication and capability
        # checks happen before the recognition task can open a provider stream.
        try:
            container.sessions.get(parsed_session_id, start.session_token)
        except DomainError:
            await websocket.close(code=1008)
            return
        backend = container.continuous_speech_recognition
        if backend is None or registry.limits.max_seconds == 0:
            await websocket.send_text(ContinuousListeningStopped(
                lease_id=start.lease_id, reason="microphone_unavailable").model_dump_json())
            await websocket.close(code=1008)
            return
        try:
            stt_used, stt_remaining = _usage_budget(websocket)
            if stt_remaining == 0:
                await websocket.send_text(ContinuousListeningStopped(
                    lease_id=start.lease_id, reason="service_budget_exhausted" if registry.limits.max_seconds is None else "input_limit").model_dump_json())
                await websocket.close(code=1008)
                return
            natural_mode = start.mode == "natural" and getattr(backend, "endpoint_mode", None) == "google_vad_offsets"
            lease = await registry.start(parsed_session_id, str(start.lease_id), natural_mode=natural_mode,
                client_endpointing=natural_mode and start.client_endpointing)
        except DomainError as error:
            reason = "session_capacity" if error.code == "session_capacity" else "invalid_input"
            await websocket.send_text(ContinuousListeningStopped(
                lease_id=start.lease_id, reason=reason).model_dump_json())
            await websocket.close(code=1008)
            return

        limits = registry.limits
        effective_seconds = limits.max_seconds
        backend_seconds = getattr(backend, "max_stream_seconds", None)
        declaration = getattr(websocket.app.state, "usage_declaration", None)
        declared_seconds = getattr(declaration, "stt_max_stream_seconds", None)
        caps = [value for value in (backend_seconds, declared_seconds)
                if type(value) in (int, float) and value > 0]
        if caps:
            lease.recognition_stream_seconds = min(290.0, float(min(caps)))
            # Per-RPC duration is independent of the optional total microphone lease.
            # Natural recognition renews bounded streams without shortening that lease.
        if effective_seconds is not None and effective_seconds < 1:
            await registry.stop_lease(lease, "microphone_unavailable")
            await websocket.send_text(ContinuousListeningStopped(
                lease_id=start.lease_id, reason="microphone_unavailable").model_dump_json())
            return
        effective_samples = (None if effective_seconds is None else min(limits.max_samples, effective_seconds * 16_000))
        if effective_seconds is not None:
            lease.constrain_audio_limits(max_seconds=effective_seconds, max_samples=effective_samples)
        endpoint_mode = "google_vad_offsets_manual_commit" if getattr(
            backend, "endpoint_mode", None) == "google_vad_offsets" else "unavailable_manual"
        if natural_mode:
            endpoint_mode = "google_vad_offsets_natural"
        await websocket.send_text(ContinuousListeningReady(
            lease_id=start.lease_id,
            max_seconds=effective_seconds,
            max_samples=effective_samples,
            max_utterances=limits.max_utterances,
            max_streams_per_session=limits.max_streams_per_session,
            max_total_streams=limits.max_total_streams,
            session_lease_starts_used=registry.lease_starts_for_session(parsed_session_id),
            total_lease_starts_used=registry.total_lease_starts,
            stt_requests_used=stt_used,
            stt_requests_remaining=stt_remaining,
            endpoint_mode=endpoint_mode,
            manual_commit_required=not natural_mode,
            client_endpoint_supported=natural_mode and start.client_endpointing,
            client_silence_ms=limits.client_silence_ms,
            natural_grace_ms=int(limits.natural_grace_seconds * 1000) if natural_mode else 0,
            drain_timeout_ms=int(limits.drain_timeout_seconds * 1000),
            max_recognition_streams=limits.max_recognition_streams if (natural_mode or effective_seconds is None) else 1,
        ).model_dump_json())
        lease._recognition_task = asyncio.create_task(lease.recognize(backend,
            is_current=registry.is_current, register_utterance=registry.register_utterance,
            request_budget=getattr(container, "stt_request_budget", None)))
        loop = asyncio.get_running_loop()
        deadline = None if effective_seconds is None else loop.time() + effective_seconds
        last_transcript_revision = 0
        last_correction_revisions: dict[str, int] = {}
        while True:
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0 and lease.active:
                close_reason = "max_duration"
                await registry.stop_lease(lease, close_reason)
                continue
            # A server event must not cancel an in-flight receive: its transport
            # may already have removed a client audio/control frame from the queue.
            if receive_task is None:
                receive_task = asyncio.create_task(_message(websocket))
            if event_task is None:
                event_task = asyncio.create_task(lease.events.get())
            done, _pending = await asyncio.wait((receive_task, event_task), timeout=None if remaining is None else max(0.1, remaining),
                                               return_when=asyncio.FIRST_COMPLETED)
            completed_receive, completed_event = receive_task, event_task
            done.update(task for task in (receive_task, event_task) if task.done())
            if receive_task in done:
                receive_task = None
            if event_task in done:
                event_task = None
            if not done:
                close_reason = "max_duration"
                await registry.stop_lease(lease, close_reason)
                continue
            if completed_receive in done:
                # Disconnect and explicit Stop take precedence when recognition and
                # incoming control become ready together. Do not publish a retained
                # terminal preview before consuming an already-received cancellation.
                raw = completed_receive.result()
                if raw.get("type") == "stop":
                    try:
                        control = ContinuousListeningStop.model_validate(raw)
                        if str(control.lease_id) != lease.lease_id:
                            raise DomainError("stale_stream", "Stop belongs to another listening lease.")
                        close_reason = control.reason
                    except (ValidationError, DomainError):
                        close_reason = "invalid_input"
                    await registry.stop_lease(lease, close_reason)
                    await websocket.send_text(ContinuousListeningStopped(
                        lease_id=UUID(lease.lease_id), reason=close_reason,
                        diagnostic_id=lease.diagnostic_id).model_dump_json())
                    break
            if completed_event in done:
                event = completed_event.result()
                if event.type != "stopped" and not registry.is_current(lease):
                    event = None
                elif event.type == "utterance_ready" and lease.natural_candidate() != event:
                    # A newer BEGIN/interim/final can invalidate an enqueued candidate.
                    # Still consume a simultaneously received control below.
                    event = None
                if event is not None:
                    _usage_budget(websocket)
                    if event.type == "stopped":
                        for preview in lease.terminal_previews:
                            delivered_revision = (last_correction_revisions.get(preview.utterance_id, 0)
                                if preview.type == "utterance_revision" else last_transcript_revision)
                            if preview.revision <= delivered_revision:
                                continue
                            # Completion may clear the queue before its writer runs. Preserve
                            # only the last already-observed preview, with unchanged finality.
                            # Explicit cancellation clears this snapshot even after EOF.
                            await websocket.send_text(_wire_event(preview).model_dump_json())
                            if preview.type == "utterance_revision":
                                last_correction_revisions[preview.utterance_id] = preview.revision
                            else:
                                last_transcript_revision = preview.revision
                    await websocket.send_text(_wire_event(event).model_dump_json())
                    if event.type == "transcript":
                        last_transcript_revision = event.revision
                    elif event.type == "utterance_revision":
                        last_correction_revisions[event.utterance_id] = event.revision
                        for old in tuple(last_correction_revisions)[:-64]:
                            last_correction_revisions.pop(old)
                    if event.type == "stopped":
                        close_reason = event.reason or close_reason
                        break
            if completed_receive in done:
                try:
                    if raw.get("type") == "audio":
                        chunk = ContinuousListeningAudio.model_validate(raw)
                        if str(chunk.lease_id) != lease.lease_id:
                            raise DomainError("stale_stream", "Audio belongs to another listening lease.")
                        try:
                            pcm = base64.b64decode(chunk.pcm_base64, validate=True)
                        except (ValueError, binascii.Error):
                            raise DomainError("invalid_audio", "Invalid PCM encoding.") from None
                        try:
                            lease.audio.push(lease_id=lease.lease_id, sequence=chunk.sequence,
                                first_sample=chunk.first_sample, pcm=pcm)
                            _usage_budget(websocket)
                        except DomainError as error:
                            close_reason = "max_samples" if error.code == "input_limit" and (
                                effective_samples is not None and lease.audio.samples + len(pcm) // 2 > effective_samples) else (
                                    "queue_limit" if "queue" in str(error).lower() else error.code)
                            await registry.stop_lease(lease, close_reason)
                    elif raw.get("type") == "client_endpoint":
                        control = ContinuousListeningClientEndpoint.model_validate(raw)
                        if str(control.lease_id) != lease.lease_id:
                            raise DomainError("stale_stream", "Endpoint belongs to another listening lease.")
                        await lease.request_client_endpoint(endpoint_id=str(control.endpoint_id),
                                                            source_end_sample=control.source_end_sample)
                    elif raw.get("type") == "cancel_endpoint":
                        control = ContinuousListeningCancelEndpoint.model_validate(raw)
                        if str(control.lease_id) != lease.lease_id:
                            raise DomainError("stale_stream", "Endpoint belongs to another listening lease.")
                        await lease.cancel_client_endpoint(endpoint_id=str(control.endpoint_id))
                    elif raw.get("type") == "hold":
                        control = ContinuousListeningHold.model_validate(raw)
                        if str(control.lease_id) != lease.lease_id:
                            raise DomainError("stale_stream", "Hold belongs to another listening lease.")
                        try:
                            held = await lease.hold_candidate(utterance_id=str(control.utterance_id),
                                                              revision=control.revision)
                            await websocket.send_text(ContinuousListeningHeld(
                                lease_id=UUID(held.lease_id), utterance_id=UUID(held.utterance_id),
                                revision=held.revision, text=held.text).model_dump_json())
                            lease.release_held_candidate(held)
                        except DomainError as error:
                            reasons = {"transcript_stale": "stale_revision",
                                "media_cancelled": "lease_revoked", "request_conflict": "identity_conflict",
                                "session_capacity": "request_limit"}
                            await websocket.send_text(ContinuousListeningHoldRejected(
                                lease_id=UUID(lease.lease_id), utterance_id=control.utterance_id,
                                revision=control.revision, current_revision=lease.revision,
                                reason=reasons.get(error.code, "lease_revoked")).model_dump_json())
                            if error.code == "session_capacity":
                                close_reason = "utterance_limit"
                                await registry.stop_lease(lease, close_reason)
                    elif raw.get("type") == "commit":
                        control = ContinuousListeningCommit.model_validate(raw)
                        if str(control.lease_id) != lease.lease_id:
                            raise DomainError("stale_stream", "Commit belongs to another listening lease.")
                        try:
                            result = await lease.manual_commit(commit_id=str(control.commit_id),
                                revision=control.revision, registry=registry,
                                utterance_id=str(control.utterance_id) if control.utterance_id else None)
                            delivered = await registry.mark_delivered(parsed_session_id,
                                lease.lease_id, result.commit_id)
                            if not delivered:
                                raise DomainError("media_cancelled", "Listening commit was revoked.")
                            await websocket.send_text(ContinuousListeningCommitReady(
                                lease_id=UUID(result.lease_id), commit_id=UUID(result.commit_id),
                                segment_seq=result.segment_seq, revision=result.revision,
                                text=result.text,
                                utterance_id=UUID(result.utterance_id) if result.utterance_id else None).model_dump_json())
                        except DomainError as error:
                            reasons = {"transcript_stale": "stale_revision",
                                       "transcript_empty": "no_final_text",
                                       "session_capacity": "request_limit",
                                       "busy": "pending_capacity",
                                       "media_cancelled": "lease_revoked",
                                       "request_conflict": "identity_conflict"}
                            await websocket.send_text(ContinuousListeningCommitRejected(
                                lease_id=UUID(lease.lease_id), commit_id=control.commit_id,
                                reason=reasons.get(error.code, "lease_revoked"),
                                current_revision=lease.revision).model_dump_json())
                            if error.code == "session_capacity":
                                close_reason = "utterance_limit"
                                await registry.stop_lease(lease, close_reason)
                    else:
                        raise DomainError("invalid_input", "Unsupported listening control message.")
                except (ValidationError, DomainError):
                    close_reason = "invalid_input"
                    await registry.stop_lease(lease, close_reason)
    except WebSocketDisconnect:
        close_reason = "disconnect"
    except asyncio.CancelledError:
        close_reason = "session_closed"
        raise
    except Exception:
        close_reason = "unavailable"
    finally:
        for task in (receive_task, event_task):
            if task is not None and not task.done():
                task.cancel()
        if receive_task is not None or event_task is not None:
            await asyncio.gather(*(task for task in (receive_task, event_task) if task is not None),
                                 return_exceptions=True)
        if lease is not None:
            if lease.active:
                await registry.stop_lease(lease, close_reason)
            if lease._recognition_task is not None:
                await asyncio.wait({lease._recognition_task}, timeout=.25)
        try:
            await websocket.close(code=1000)
        except Exception:
            pass
        request_correlation.reset(correlation)
