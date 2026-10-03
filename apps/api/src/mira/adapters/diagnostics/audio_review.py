"""Bounded transient staging for exact-buffer, human-reviewed development audio."""
from dataclasses import dataclass, replace
import hashlib
import hmac
import math
import threading
import time
import uuid

from mira.application.diagnostic_events import (
    ContentReview,
    DiagnosticContext,
    RecordingKind,
    ReviewedRecording,
)
from mira.application.ports.reviewed_audio import (
    AudioCaptureHandle, AudioCaptureOwner, AudioCaptureResult, AudioCaptureStatus,
    AudioReviewTicket,
)


_MAX_AUDIO_BYTES = 512 * 1024
_MAX_TTL_SECONDS = 60.0
_SUPPORTED_SAMPLE_RATES = frozenset((16000, 24000, 48000))


@dataclass(frozen=True, slots=True)
class AudioCaptureLimits:
    """Single-buffer memory and lifetime ceiling; downstream raw budgets stay authoritative."""

    max_audio_bytes: int = _MAX_AUDIO_BYTES
    ttl_seconds: float = 30.0

    def __post_init__(self):
        if (type(self.max_audio_bytes) is not int
                or not 2 <= self.max_audio_bytes <= _MAX_AUDIO_BYTES):
            raise ValueError("invalid audio staging budget")
        if (type(self.ttl_seconds) not in (int, float)
                or not math.isfinite(self.ttl_seconds)
                or not 1 <= self.ttl_seconds <= _MAX_TTL_SECONDS):
            raise ValueError("invalid audio staging lifetime")


class _RevocablePcmView:
    """Hold one review view that becomes empty when its stage is invalidated."""

    def __init__(self, pcm: bytearray):
        self._pcm: bytearray | None = pcm

    def view(self) -> memoryview:
        pcm = self._pcm
        return memoryview(pcm).toreadonly() if pcm is not None else memoryview(b"")

    def revoke(self) -> None:
        self._pcm = None


@dataclass(slots=True)
class _Pending:
    handle: AudioCaptureHandle
    owner: AudioCaptureOwner
    sample_rate_hz: int
    recording_kind: RecordingKind
    recording_generation: int
    expires_at: float
    pcm: bytearray
    phase: str = "staging"
    digest: str | None = None
    review_id: str | None = None
    ticket: AudioReviewTicket | None = None
    view: _RevocablePcmView | None = None
    timer: threading.Timer | None = None
    completion_digest: str | None = None
    completion_generation: int | None = None
    completion_request_id: str | None = None


class ReviewedAudioCapture:
    """One bounded in-memory candidate followed by exact review and explicit private save.

    The injected sink is the existing diagnostics recorder, not a new storage mechanism. This
    coordinator deliberately does not start microphone acquisition, inspect a transcript, or
    offer export. Its caller must make recording mode visible and route Stop/new-input/close here.
    """

    def __init__(self, diagnostics, *, limits: AudioCaptureLimits | None = None, clock=None):
        self.diagnostics = diagnostics
        self.limits = limits or AudioCaptureLimits()
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._closed = False
        self._recording = False
        self._recording_generation = 0
        self._stage_generation = 0
        self._pending: _Pending | None = None

    @staticmethod
    def _result(code: str, message: str, *, ok: bool = False,
                handle: AudioCaptureHandle | None = None,
                ticket: AudioReviewTicket | None = None) -> AudioCaptureResult:
        return AudioCaptureResult(code, message, ok, handle, ticket)

    def _now(self) -> float:
        value = self._clock()
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("invalid monotonic clock")
        return float(value)

    def _discard_locked(self) -> None:
        pending, self._pending = self._pending, None
        if pending is None:
            return
        if pending.timer is not None:
            pending.timer.cancel()
        # Clear the only coordinator-owned copy. A reviewer-held view, if any, sees zeros.
        if pending.pcm:
            pending.pcm[:] = b"\x00" * len(pending.pcm)
            if pending.view is None:
                pending.pcm.clear()
        if pending.view is not None:
            pending.view.revoke()

    def _expire_locked(self) -> bool:
        pending = self._pending
        if pending is not None and self._now() >= pending.expires_at:
            self._discard_locked()
            return True
        return False

    def _expire_timer(self, token: str, generation: int) -> None:
        with self._lock:
            pending = self._pending
            if (pending is not None and pending.handle.token == token
                    and pending.handle.generation == generation):
                # The timer can fire a moment early under scheduler jitter; leave the hard
                # deadline authoritative and schedule only the tiny remainder.
                remaining = pending.expires_at - self._now()
                if remaining <= 0:
                    self._discard_locked()
                else:
                    timer = threading.Timer(remaining, self._expire_timer,
                                            args=(token, generation))
                    timer.daemon = True
                    pending.timer = timer
                    timer.start()

    def _schedule_expiry_locked(self, pending: _Pending) -> None:
        timer = threading.Timer(self.limits.ttl_seconds, self._expire_timer,
                                args=(pending.handle.token, pending.handle.generation))
        timer.daemon = True
        pending.timer = timer
        timer.start()

    def set_recording(self, enabled: bool, *, consent: bool = False) -> AudioCaptureResult:
        if type(enabled) is not bool or type(consent) is not bool:
            return self._result("invalid_recording_choice", "无法确认开发录制设置。")
        if enabled and not consent:
            return self._result("consent_required", "开启开发原始音频录制前需要明确确认。")
        with self._lock:
            if self._closed:
                return self._result("closed", "音频审核已关闭。")
            # Any explicit mode transition invalidates all review state, including repeated on/off.
            self._recording_generation += 1
            self._discard_locked()
            self._recording = False
            try:
                accepted = self.diagnostics.set_recording(enabled, consent=consent)
            except Exception:
                accepted = False
            if accepted is not True:
                code = "recording_enable_failed" if enabled else "recording_disable_failed"
                message = ("本地诊断录制未确认开启，原始音频保持关闭。" if enabled else
                           "本地诊断录制未确认关闭，原始音频审核已阻止继续。")
                return self._result(code, message)
            self._recording = enabled
            if enabled:
                return self._result("recording_enabled",
                    "开发原始音频录制已开启；原音频仅暂存在内存，必须逐段审核原缓冲区并明确确认私密本机保存。不会自动检测所有口述秘密。",
                    ok=True)
            return self._result("recording_disabled", "开发原始音频录制已关闭。", ok=True)

    def begin(self, owner: AudioCaptureOwner, *, sample_rate_hz: int) -> AudioCaptureResult:
        return self.begin_recording(owner, sample_rate_hz=sample_rate_hz)

    def begin_recording(self, owner: AudioCaptureOwner, *, sample_rate_hz: int,
                        kind: RecordingKind = RecordingKind.AUDIO_INPUT) -> AudioCaptureResult:
        with self._lock:
            self._expire_locked()
            # New input always supersedes any older candidate, even if the new attempt is denied.
            self._discard_locked()
            self._stage_generation += 1
            if self._closed:
                return self._result("closed", "音频审核已关闭。")
            if not self._recording:
                return self._result("recording_disabled", "先明确开启开发原始音频录制。")
            if type(owner) is not AudioCaptureOwner:
                return self._result("invalid_owner", "当前音频缺少有效的会话、轮次或流身份。")
            try:
                AudioCaptureOwner(owner.session_id, owner.turn_id, owner.stream_id,
                                  owner.effect_id, owner.input_epoch, owner.output_epoch)
            except Exception:
                return self._result("invalid_owner", "当前音频缺少有效的会话、轮次或流身份。")
            if type(kind) is not RecordingKind or kind not in (
                    RecordingKind.AUDIO_INPUT, RecordingKind.AUDIO_OUTPUT):
                return self._result("invalid_recording_kind", "只允许审核原始音频输入或输出。")
            if type(sample_rate_hz) is not int or sample_rate_hz not in _SUPPORTED_SAMPLE_RATES:
                return self._result("invalid_sample_rate", "当前音频采样率不受支持。")
            try:
                now = self._now()
            except Exception:
                return self._result("clock_unavailable", "无法核验音频暂存期限，未保留音频。")
            handle = AudioCaptureHandle(uuid.uuid4().hex, self._stage_generation)
            pending = _Pending(handle, owner, sample_rate_hz, kind, self._recording_generation,
                               now + self.limits.ttl_seconds, bytearray())
            self._pending = pending
            self._schedule_expiry_locked(pending)
            return self._result("staging_started", "已开始有界内存暂存；尚未写入磁盘。",
                                ok=True, handle=handle)

    def begin_scoped(self, owner: AudioCaptureOwner, *, sample_rate_hz: int,
                     kind: RecordingKind = RecordingKind.AUDIO_INPUT) -> AudioCaptureResult:
        """Start a buffer for one authenticated session without displacing another session."""
        with self._lock:
            try:
                self._expire_locked()
            except Exception:
                self._discard_locked()
                return self._result("clock_unavailable", "无法核验音频暂存期限，未保留音频。")
            pending = self._pending
            if pending is not None and pending.owner.session_id != getattr(owner, "session_id", None):
                return self._result("audio_review_busy", "本会话的原始音频未暂存；已有缓冲仍受其会话保护。")
            return self.begin_recording(owner, sample_rate_hz=sample_rate_hz, kind=kind)

    def append_scoped(self, owner: AudioCaptureOwner, handle: AudioCaptureHandle,
                      chunk: bytes) -> AudioCaptureResult:
        with self._lock:
            pending = self._pending
            if pending is None or pending.owner != owner or pending.handle != handle:
                return self._result("stale_audio_handle", "这段音频已取消、过期或被更新输入取代。")
            return self.append(handle, chunk)

    def status_for_session(self, session_id: str) -> AudioCaptureStatus:
        """Keep app-wide recording visible while hiding another session's staged metadata."""
        with self._lock:
            try:
                self._expire_locked()
            except Exception:
                self._discard_locked()
                self._recording = False
            status = self.status()
            pending = self._pending
            if pending is not None and pending.owner.session_id == session_id:
                return replace(status, pending_stream_id=pending.owner.stream_id,
                               pending_kind=pending.recording_kind,
                               input_completion_ready=(
                                   pending.recording_kind is RecordingKind.AUDIO_INPUT
                                   and pending.completion_digest is not None
                                   and pending.completion_generation == pending.recording_generation
                                   and pending.completion_generation == self._recording_generation))
            notice = ("开发原始音频录制已开启；本模式适用于本机 MIRA 应用的所有会话。"
                      "当前会话没有待审核音频。不会自动检测所有口述秘密。"
                      if status.recording_active else "开发原始音频录制已关闭。")
            return replace(status, has_pending_audio=False, staged_bytes=0,
                           expires_in_seconds=0.0, notice=notice,
                           pending_stream_id=None, pending_kind=None,
                           input_completion_ready=False)

    def register_input_completion(self, owner: AudioCaptureOwner, handle: AudioCaptureHandle,
                                  final_text: str) -> bool:
        """Bind a validated server-completed final transcript to its exact pending input stage."""
        if (type(owner) is not AudioCaptureOwner or type(handle) is not AudioCaptureHandle
                or type(final_text) is not str or not final_text.strip() or len(final_text) > 2000):
            return False
        with self._lock:
            try:
                if self._expire_locked():
                    return False
            except Exception:
                self._discard_locked()
                return False
            pending = self._pending
            if (pending is None or pending.owner != owner or pending.handle != handle
                    or pending.recording_kind is not RecordingKind.AUDIO_INPUT
                    or pending.recording_generation != self._recording_generation
                    or not self._recording or self._closed):
                return False
            pending.completion_digest = hashlib.sha256(
                final_text.strip().encode("utf-8")).hexdigest()
            pending.completion_generation = pending.recording_generation
            pending.completion_request_id = None
            return True

    def consume_input_completion(self, session_id: str, stream_id: str, request_id: str,
                                 text: str) -> bool:
        """Accept only the one-use request for the exact server-final stream/transcript pair.

        Repeating the same request ID is idempotent; another request cannot reuse the association.
        """
        if (any(type(value) is not str or not 1 <= len(value) <= 256
                for value in (session_id, stream_id, request_id))
                or type(text) is not str or not 1 <= len(text) <= 2000):
            return False
        with self._lock:
            try:
                if self._expire_locked():
                    return False
            except Exception:
                self._discard_locked()
                return False
            pending = self._pending
            if (pending is None or pending.owner.session_id != session_id
                    or pending.owner.stream_id != stream_id
                    or pending.recording_kind is not RecordingKind.AUDIO_INPUT
                    or pending.completion_generation != pending.recording_generation
                    or pending.completion_generation != self._recording_generation
                    or pending.completion_digest is None or not self._recording or self._closed):
                return False
            digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
            if not hmac.compare_digest(digest, pending.completion_digest):
                return False
            if pending.completion_request_id is None:
                pending.completion_request_id = request_id
                return True
            return hmac.compare_digest(pending.completion_request_id, request_id)

    def request_review_for_stream(self, session_id: str, stream_id: str) -> AudioCaptureResult:
        with self._lock:
            pending = self._pending
            if (pending is None or pending.owner.session_id != session_id
                    or pending.owner.stream_id != stream_id):
                return self._result("audio_review_not_found", "此音频审核不存在、已过期或不属于当前会话。")
            result = self.request_review(pending.handle)
            if result.ticket is not None:
                pending.ticket = result.ticket
            return result

    def preview_review(self, session_id: str, review_id: str) -> tuple[AudioReviewTicket, bytes] | None:
        """Read the exact buffer only for the owning authenticated session."""
        with self._lock:
            try:
                if self._expire_locked():
                    return None
            except Exception:
                self._discard_locked()
                return None
            pending = self._pending
            ticket = pending.ticket if pending is not None else None
            if (pending is None or ticket is None or pending.owner.session_id != session_id
                    or pending.phase != "review" or ticket.review_id != review_id):
                return None
            pcm = bytes(ticket.pcm)
            if not pcm:
                return None
            return ticket, pcm

    def confirm_review(self, session_id: str, review_id: str, *, reviewed_digest: str,
                       review: ContentReview, persist_consent: bool) -> AudioCaptureResult:
        with self._lock:
            try:
                if self._expire_locked():
                    return self._result("audio_review_not_found", "此音频审核不存在、已过期或不属于当前会话。")
            except Exception:
                self._discard_locked()
                return self._result("clock_unavailable", "无法核验审核期限，暂存音频已清除。")
            pending = self._pending
            ticket = pending.ticket if pending is not None else None
            if (pending is None or ticket is None or pending.owner.session_id != session_id
                    or pending.phase != "review" or ticket.review_id != review_id):
                return self._result("audio_review_not_found", "此音频审核不存在、已过期或不属于当前会话。")
        return self.confirm_save(ticket, reviewed_digest=reviewed_digest,
                                 review=review, persist_consent=persist_consent)

    def cancel_session(self, session_id: str, *, stream_id: str | None = None) -> AudioCaptureResult:
        """Invalidate only this authenticated session's buffer, optionally for one media stream."""
        with self._lock:
            try:
                self._expire_locked()
            except Exception:
                self._discard_locked()
                return self._result("audio_cancelled", "待审核音频已清除，未写入磁盘。", ok=True)
            pending = self._pending
            if pending is None or pending.owner.session_id != session_id:
                return self._result("nothing_pending", "没有待审核的音频。", ok=True)
            if stream_id is not None and pending.owner.stream_id != stream_id:
                return self._result("stale_audio_handle", "这段音频已被取消或更新输入取代。")
            self._stage_generation += 1
            self._discard_locked()
            return self._result("audio_cancelled", "待审核音频已清除，未写入磁盘。", ok=True)

    def append(self, handle: AudioCaptureHandle, chunk: bytes) -> AudioCaptureResult:
        with self._lock:
            try:
                expired = self._expire_locked()
            except Exception:
                self._discard_locked()
                return self._result("clock_unavailable", "无法核验音频暂存期限，未保留音频。")
            if expired:
                return self._result("review_expired", "音频审核期限已过，暂存音频已清除。")
            pending = self._pending
            if pending is None or type(handle) is not AudioCaptureHandle or pending.handle != handle:
                return self._result("stale_audio_handle", "这段音频已取消、过期或被更新输入取代。")
            if self._closed or not self._recording:
                self._discard_locked()
                return self._result("recording_disabled", "录制已关闭，暂存音频已清除。")
            if self._recording_generation != pending.recording_generation:
                self._discard_locked()
                return self._result("stale_audio_handle", "录制状态已变化，暂存音频已清除。")
            if pending.phase != "staging":
                self._discard_locked()
                return self._result("review_already_requested", "审核缓冲区已封存，不能再修改。请重新开始。")
            if type(chunk) is not bytes:
                self._discard_locked()
                return self._result("invalid_audio_chunk", "音频分块格式无效，暂存内容已清除。")
            if not chunk:
                return self._result("empty_audio_chunk", "没有收到音频数据。")
            if len(pending.pcm) + len(chunk) > self.limits.max_audio_bytes:
                self._discard_locked()
                return self._result("audio_limit_reached", "音频超过暂存容量上限，内容已清除。")
            pending.pcm.extend(chunk)
            return self._result("audio_staged", "音频暂存在内存中，尚未写入磁盘。", ok=True,
                                handle=handle)

    def request_review(self, handle: AudioCaptureHandle) -> AudioCaptureResult:
        with self._lock:
            try:
                expired = self._expire_locked()
            except Exception:
                self._discard_locked()
                return self._result("clock_unavailable", "无法核验音频暂存期限，暂存音频已清除。")
            if expired:
                return self._result("review_expired", "音频审核期限已过，暂存音频已清除。")
            pending = self._pending
            if pending is None or type(handle) is not AudioCaptureHandle or pending.handle != handle:
                return self._result("stale_audio_handle", "这段音频已取消、过期或被更新输入取代。")
            if self._closed or not self._recording:
                self._discard_locked()
                return self._result("recording_disabled", "录制已关闭，暂存音频已清除。")
            if pending.phase != "staging":
                self._discard_locked()
                return self._result("review_already_requested", "审核申请已失效，请重新开始。")
            if not pending.pcm or len(pending.pcm) % 2:
                self._discard_locked()
                return self._result("invalid_pcm", "原始 PCM 缓冲区为空或帧不完整，内容已清除。")
            try:
                digest = hashlib.sha256(pending.pcm).hexdigest()
                review_id = uuid.uuid4().hex
                pending.view = _RevocablePcmView(pending.pcm)
                pending.digest = digest
                pending.review_id = review_id
                pending.phase = "review"
                ticket = AudioReviewTicket(
                    stage_token=pending.handle.token,
                    stage_generation=pending.handle.generation,
                    recording_generation=pending.recording_generation,
                    owner=pending.owner,
                    recording_kind=pending.recording_kind,
                    sample_rate_hz=pending.sample_rate_hz,
                    digest=digest,
                    review_id=review_id,
                    _pcm_view=pending.view,
                )
            except Exception:
                self._discard_locked()
                return self._result("review_unavailable", "无法准备精确缓冲区审核，暂存音频已清除。")
            return self._result("review_required",
                "请审核下方原始缓冲区本身。摘要只绑定字节内容，不代表检测到或排除了所有口述秘密。",
                ok=True, handle=handle, ticket=ticket)

    def confirm_save(self, ticket: AudioReviewTicket, *, reviewed_digest: str,
                     review: ContentReview, persist_consent: bool) -> AudioCaptureResult:
        record = None
        with self._lock:
            try:
                expired = self._expire_locked()
            except Exception:
                self._discard_locked()
                return self._result("clock_unavailable", "无法核验审核期限，暂存音频已清除。")
            if expired:
                return self._result("review_expired", "审核已过期，暂存音频已清除。")
            pending = self._pending
            if (pending is None or type(ticket) is not AudioReviewTicket
                    or pending.phase != "review"
                    or pending.handle.token != ticket.stage_token
                    or pending.handle.generation != ticket.stage_generation
                    or pending.recording_generation != ticket.recording_generation
                    or pending.recording_generation != self._recording_generation
                    or pending.owner != ticket.owner
                    or pending.recording_kind != ticket.recording_kind
                    or pending.sample_rate_hz != ticket.sample_rate_hz
                    or pending.digest != ticket.digest
                    or pending.review_id != ticket.review_id):
                return self._result("stale_review_ticket", "此审核已失效；请为当前音频重新审核。")
            if self._closed or not self._recording:
                self._discard_locked()
                return self._result("recording_disabled", "录制已关闭，审核音频已清除。")
            try:
                actual_digest = hashlib.sha256(pending.pcm).hexdigest()
            except Exception:
                self._discard_locked()
                return self._result("buffer_changed", "审核缓冲区无法复核，音频已清除。")
            if actual_digest != pending.digest:
                self._discard_locked()
                return self._result("buffer_changed", "审核后的音频字节发生变化，旧确认已撤销并清除。")
            if (type(reviewed_digest) is not str or len(reviewed_digest) != 64
                    or not hmac.compare_digest(reviewed_digest, pending.digest)):
                self._discard_locked()
                return self._result("digest_mismatch", "审核摘要与原始音频不一致，内容已清除。")
            # Every valid-ticket submit consumes the approval, even a denial or missing save consent.
            if type(persist_consent) is not bool or not persist_consent:
                self._discard_locked()
                return self._result("persist_consent_required", "需要单独确认将这段已审核音频保存在本机。")
            if type(review) is not ContentReview or review is not ContentReview.APPROVED:
                self._discard_locked()
                return self._result("review_not_approved", "只有针对原始缓冲区的明确安全审核可进入本机保存。")
            try:
                owner = ticket.owner
                context = DiagnosticContext(session_id=owner.session_id,
                    turn_id=owner.turn_id, effect_id=owner.effect_id)
                record = ReviewedRecording(
                    kind=ticket.recording_kind,
                    context=context,
                    review=ContentReview.APPROVED,
                    audio=bytes(pending.pcm),
                    sample_rate_hz=ticket.sample_rate_hz,
                )
            except Exception:
                self._discard_locked()
                return self._result("reviewed_audio_unavailable", "无法构造已审核录制，未保存音频。")
            self._discard_locked()
        try:
            accepted = self.diagnostics.capture(record)
        except Exception:
            accepted = False
        if accepted is True:
            return self._result("queued_private_local",
                "已进入本机私密诊断写入队列；这只表示队列已接收，落盘仍可能失败。", ok=True)
        return self._result("local_queue_rejected",
            "本机诊断队列未接受音频，未保存。请检查开发录制状态和容量后再开始新一段审核。")

    def cancel(self, handle: AudioCaptureHandle | None = None) -> AudioCaptureResult:
        with self._lock:
            try:
                self._expire_locked()
            except Exception:
                self._discard_locked()
            pending = self._pending
            if pending is None:
                return self._result("nothing_pending", "没有待审核的音频。", ok=True)
            if handle is not None and (type(handle) is not AudioCaptureHandle or
                                       pending.handle != handle):
                return self._result("stale_audio_handle", "这段音频已被取消或更新输入取代。")
            self._stage_generation += 1
            self._discard_locked()
            return self._result("audio_cancelled", "待审核音频已清除，未写入磁盘。", ok=True)

    def status(self) -> AudioCaptureStatus:
        with self._lock:
            try:
                self._expire_locked()
            except Exception:
                self._discard_locked()
                self._recording = False
            pending = self._pending
            remaining = max(0.0, pending.expires_at - self._now()) if pending else 0.0
            if self._recording:
                if pending is None:
                    notice = ("开发原始音频录制已开启；原音频只暂存在内存，须逐段审核原缓冲区并明确确认本机私密保存。"
                              "不会自动检测所有口述秘密。")
                else:
                    notice = "有一段原始音频等待审核；确认保存前不会写入磁盘，且审核会在短时限后自动失效。"
            else:
                notice = "开发原始音频录制已关闭。"
            return AudioCaptureStatus(
                recording_active=self._recording and not self._closed,
                has_pending_audio=pending is not None,
                staged_bytes=len(pending.pcm) if pending else 0,
                max_audio_bytes=self.limits.max_audio_bytes,
                recording_generation=self._recording_generation,
                expires_in_seconds=remaining,
                notice=notice,
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._recording_generation += 1
            self._stage_generation += 1
            self._discard_locked()
            self._recording = False
            self._closed = True
            try:
                self.diagnostics.set_recording(False, consent=False)
            except Exception:
                pass
