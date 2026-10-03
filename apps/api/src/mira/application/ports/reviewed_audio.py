"""Narrow application contract for exact-buffer development audio review."""
from dataclasses import dataclass, field
from typing import Protocol

from mira.application.diagnostic_events import ContentReview, RecordingKind


class RevocablePcmView(Protocol):
    def view(self) -> memoryview: ...


@dataclass(frozen=True, slots=True)
class AudioCaptureOwner:
    """Actual provenance for one media stream, with provisional turn/effect left unknown."""

    session_id: str = field(repr=False)
    turn_id: str | None = field(repr=False)
    stream_id: str = field(repr=False)
    effect_id: str | None = field(default=None, repr=False)
    input_epoch: int | None = None
    output_epoch: int | None = None

    def __post_init__(self):
        if (type(self.session_id) is not str or not 1 <= len(self.session_id) <= 256
                or type(self.stream_id) is not str or not 1 <= len(self.stream_id) <= 256):
            raise ValueError("invalid audio capture owner")
        if any(value is not None and (type(value) is not str or not 1 <= len(value) <= 256)
               for value in (self.turn_id, self.effect_id)):
            raise ValueError("invalid audio capture provenance")
        if any(value is not None and (type(value) is not int or value < 0)
               for value in (self.input_epoch, self.output_epoch)):
            raise ValueError("invalid audio capture epoch")
        if not any(value is not None for value in (
                self.turn_id, self.effect_id, self.input_epoch, self.output_epoch)):
            raise ValueError("audio capture owner has no turn, effect, or input/output epoch")


@dataclass(frozen=True, slots=True)
class AudioCaptureHandle:
    token: str = field(repr=False)
    generation: int


@dataclass(frozen=True, slots=True)
class AudioReviewTicket:
    """Exact review grant; invalidation makes its transient PCM view empty."""

    stage_token: str = field(repr=False)
    stage_generation: int
    recording_generation: int
    owner: AudioCaptureOwner = field(repr=False)
    recording_kind: RecordingKind
    sample_rate_hz: int
    digest: str
    review_id: str = field(repr=False)
    _pcm_view: RevocablePcmView = field(repr=False, compare=False)

    @property
    def pcm(self) -> memoryview:
        return self._pcm_view.view()


@dataclass(frozen=True, slots=True)
class AudioCaptureResult:
    code: str
    message: str
    ok: bool = False
    handle: AudioCaptureHandle | None = None
    ticket: AudioReviewTicket | None = None


@dataclass(frozen=True, slots=True)
class AudioCaptureStatus:
    recording_active: bool = False
    has_pending_audio: bool = False
    staged_bytes: int = 0
    max_audio_bytes: int = 512 * 1024
    recording_generation: int = 0
    expires_in_seconds: float = 0.0
    notice: str = "开发原始音频录制已关闭。"
    pending_stream_id: str | None = None
    pending_kind: RecordingKind | None = None
    input_completion_ready: bool = False


class ReviewedAudioCapturePort(Protocol):
    """One app-wide bounded coordinator; callers must authenticate and owner-scope API access."""

    def set_recording(self, enabled: bool, *, consent: bool = False) -> AudioCaptureResult: ...
    def begin_scoped(self, owner: AudioCaptureOwner, *, sample_rate_hz: int,
                     kind: RecordingKind = RecordingKind.AUDIO_INPUT) -> AudioCaptureResult: ...
    def append_scoped(self, owner: AudioCaptureOwner, handle: AudioCaptureHandle,
                      chunk: bytes) -> AudioCaptureResult: ...
    def status_for_session(self, session_id: str) -> AudioCaptureStatus: ...
    def register_input_completion(self, owner: AudioCaptureOwner, handle: AudioCaptureHandle,
                                  final_text: str) -> bool: ...
    def consume_input_completion(self, session_id: str, stream_id: str, request_id: str,
                                 text: str) -> bool: ...
    def request_review_for_stream(self, session_id: str, stream_id: str) -> AudioCaptureResult: ...
    def preview_review(self, session_id: str, review_id: str
                       ) -> tuple[AudioReviewTicket, bytes] | None: ...
    def confirm_review(self, session_id: str, review_id: str, *, reviewed_digest: str,
                       review: ContentReview, persist_consent: bool) -> AudioCaptureResult: ...
    def cancel_session(self, session_id: str, *, stream_id: str | None = None
                       ) -> AudioCaptureResult: ...
    def close(self) -> None: ...
