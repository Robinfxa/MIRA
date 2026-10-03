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
async def create_session(body: CreateSessionRequest, container: ContainerDependency) -> CreateSessionResponse:
    actor, token = container.sessions.create(str(body.client_instance_id))
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
    state = await container.sessions.get(str(session_id), token).submit(
        request_id=str(body.request_id), activity_seq=body.activity_seq,
        cutoff=body.presentation_cutoff, text=body.text.strip(),
    )
    return session_view(state)


@router.post("/sessions/{session_id}/stop", response_model=SessionView)
async def stop_session(session_id: UUID, body: StopRequest, token: Token,
                       container: ContainerDependency) -> SessionView:
    state = await container.sessions.get(str(session_id), token).stop(
        activity_seq=body.activity_seq, cutoff=body.presentation_cutoff,
    )
    return session_view(state)


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
async def delete_session(session_id: UUID, token: Token, container: ContainerDependency) -> Response:
    await container.sessions.delete(str(session_id), token)
    return Response(status_code=204)
