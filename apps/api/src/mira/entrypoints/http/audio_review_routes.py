"""Private local exact-buffer review endpoints for development-only raw PCM."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field

from mira.application.diagnostic_events import ContentReview
from mira.application.ports.reviewed_audio import AudioCaptureStatus
from mira.entrypoints.http.routes import ContainerDependency, Token
from mira.entrypoints.http.schemas import (
    ErrorResponse, ReviewedAudioActionResponse, ReviewedAudioConfirmRequest,
    ReviewedAudioRecordingRequest, ReviewedAudioReviewResponse, ReviewedAudioStatusResponse,
)

router = APIRouter(prefix="/api/v1/sessions/{session_id}/reviewed-audio", responses={
    400: {"model": ErrorResponse, "description": "Bad Request"},
    404: {"model": ErrorResponse, "description": "Not Found"},
    409: {"model": ErrorResponse, "description": "Conflict"},
    422: {"model": ErrorResponse, "description": "Unprocessable Content"},
})
_APP_SCOPE_NOTICE = (
    "此开关作用于本机 MIRA 应用的所有已认证会话，不是单个会话开关。"
    "原始 PCM 仅在内存中等待逐段审核；不会自动检测所有口述秘密，也不会授权原始导出。"
)
_REVIEW_NOTICE = (
    "请审核播放的精确原始 PCM 缓冲区本身；摘要只绑定字节内容，不代表检测到或排除了所有口述秘密。"
    "确认后还需单独同意本机私密保存。"
)


def _status(value: AudioCaptureStatus) -> ReviewedAudioStatusResponse:
    return ReviewedAudioStatusResponse(
        recording_active=value.recording_active,
        has_pending_audio=value.has_pending_audio,
        staged_bytes=value.staged_bytes,
        max_audio_bytes=value.max_audio_bytes,
        expires_in_seconds=value.expires_in_seconds,
        pending_stream_id=value.pending_stream_id,
        pending_kind=value.pending_kind.value if value.pending_kind is not None else None,
        input_completion_ready=value.input_completion_ready,
        notice=value.notice,
        scope_notice=_APP_SCOPE_NOTICE,
    )


def _action(container, session_id: str, *, ok: bool, code: str, message: str,
            accepted_for_queue: bool = False, status_code: int = 200):
    status = container.reviewed_audio.status_for_session(session_id)
    payload = ReviewedAudioActionResponse(
        scope_notice=_APP_SCOPE_NOTICE,
        ok=ok,
        code=code,
        message=message,
        recording_active=status.recording_active,
        accepted_for_queue=accepted_for_queue,
    )
    return JSONResponse(payload.model_dump(mode="json"), status_code=status_code,
                        headers={"Cache-Control": "no-store"})


@router.get("", response_model=ReviewedAudioStatusResponse)
async def reviewed_audio_status(session_id: UUID, token: Token,
                                container: ContainerDependency) -> ReviewedAudioStatusResponse:
    container.sessions.get(str(session_id), token)
    status = container.reviewed_audio.status_for_session(str(session_id))
    return _status(status)


@router.post("/recording", response_model=ReviewedAudioActionResponse)
async def set_reviewed_audio_recording(session_id: UUID, body: ReviewedAudioRecordingRequest,
                                      request: Request, token: Token, container: ContainerDependency):
    container.sessions.get(str(session_id), token)
    if getattr(request.app.state, "device_sessions", None) is not None:
        return _action(container, str(session_id), ok=False,
            code="private_device_audio_recording_unavailable",
            message="双设备模式不开放应用级原始音频录制；正常语音和脱敏诊断仍可用。",
            status_code=409)
    result = container.reviewed_audio.set_recording(body.enabled, consent=body.consent)
    return _action(container, str(session_id), ok=result.ok, code=result.code,
                   message=result.message, status_code=200 if result.ok else 409)


@router.post("/streams/{stream_id}/review", response_model=ReviewedAudioReviewResponse)
async def request_reviewed_audio(session_id: UUID, stream_id: UUID, token: Token,
                                container: ContainerDependency):
    container.sessions.get(str(session_id), token)
    result = container.reviewed_audio.request_review_for_stream(str(session_id), str(stream_id))
    if not result.ok or result.ticket is None:
        not_found = result.code in {"audio_review_not_found", "stale_audio_handle", "review_expired"}
        return JSONResponse({"code": result.code, "message": result.message},
                            status_code=404 if not_found else 409,
                            headers={"Cache-Control": "no-store"})
    ticket = result.ticket
    status = container.reviewed_audio.status_for_session(str(session_id))
    if not status.has_pending_audio:
        return JSONResponse({"code": "audio_review_not_found",
                             "message": "此音频审核不存在、已过期或不属于当前会话。"},
                            status_code=404, headers={"Cache-Control": "no-store"})
    response = ReviewedAudioReviewResponse(
        scope_notice=_APP_SCOPE_NOTICE,
        review_id=ticket.review_id,
        digest=ticket.digest,
        kind=ticket.recording_kind.value,
        sample_rate_hz=ticket.sample_rate_hz,
        byte_count=status.staged_bytes,
        expires_in_seconds=status.expires_in_seconds,
        preview_path=(f"/api/v1/sessions/{session_id}/reviewed-audio/"
                      f"reviews/{ticket.review_id}/preview"),
        notice=_REVIEW_NOTICE,
    )
    return JSONResponse(response.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@router.get("/reviews/{review_id}/preview")
async def preview_reviewed_audio(session_id: UUID,
        review_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")], token: Token,
        container: ContainerDependency):
    container.sessions.get(str(session_id), token)
    found = container.reviewed_audio.preview_review(str(session_id), review_id)
    if found is None:
        return JSONResponse({"code": "audio_review_not_found",
            "message": "此音频审核不存在、已过期或不属于当前会话。"},
            status_code=404, headers={"Cache-Control": "no-store"})
    ticket, pcm = found
    return Response(pcm, media_type="application/octet-stream", headers={
        "Cache-Control": "no-store",
        "X-Mira-Audio-Format": "pcm16le-mono",
        "X-Mira-Sample-Rate-Hz": str(ticket.sample_rate_hz),
        "X-Mira-Recording-Kind": ticket.recording_kind.value,
        "X-Mira-Audio-Digest": ticket.digest,
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/reviews/{review_id}/confirm", response_model=ReviewedAudioActionResponse)
async def confirm_reviewed_audio(session_id: UUID,
        review_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")],
        body: ReviewedAudioConfirmRequest,
        token: Token, container: ContainerDependency):
    container.sessions.get(str(session_id), token)
    review = ContentReview(body.review)
    result = container.reviewed_audio.confirm_review(str(session_id), review_id,
        reviewed_digest=body.reviewed_digest, review=review,
        persist_consent=body.persist_consent)
    if result.code == "audio_review_not_found":
        return _action(container, str(session_id), ok=False, code=result.code,
                       message=result.message, status_code=404)
    return _action(container, str(session_id), ok=result.ok, code=result.code,
        message=result.message, accepted_for_queue=result.code == "queued_private_local",
        status_code=200 if result.ok else 409)
