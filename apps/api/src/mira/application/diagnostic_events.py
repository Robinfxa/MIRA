"""Transport-independent, payload-free operational diagnostic contracts."""
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import re
from time import monotonic

from mira.application.contracts import ReportedConfidenceWarning, SafeResponseValidation
from mira.application.generation_diagnostics import SafeGenerationDiagnostic
from mira.application.fixed_photo_diagnostics import SafeFixedPhotoDiagnostic
from mira.application.wardrobe_diagnostics import SafeWardrobeDiagnostic
from mira.application.optional_candidate_diagnostics import SafeOptionalCandidateDiagnostic
from mira.application.image_readiness import SafeImageReadinessDiagnostic
from mira.application.native_tool_diagnostics import SafeNativeToolDiagnostic


class DiagnosticStage(StrEnum):
    HTTP = "http"
    SESSION = "session"
    GENERATION = "generation"
    INPUT_REVIEW = "input_review"
    OUTPUT_REVIEW = "output_review"
    STT = "stt"
    STT_FIRST_REVISION = "stt_first_revision"
    STT_FIRST_FINAL_REVISION = "stt_first_final_revision"
    STT_STREAM_END = "stt_stream_end"
    TTS = "tts"
    MICROPHONE = "microphone"
    PLAYBACK = "playback"
    DIAGNOSTICS = "diagnostics"
    FIXED_PHOTO = "fixed_photo"
    WARDROBE = "wardrobe"
    IMAGE_READINESS = "image_readiness"
    NATIVE_TOOL = "native_tool"


class DiagnosticKind(StrEnum):
    STARTED = "started"
    FINISHED = "finished"
    STATE_CHANGED = "state_changed"
    MODE_CHANGED = "mode_changed"


class DiagnosticOutcome(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DROPPED = "dropped"


class CancellationReason(StrEnum):
    USER_STOP = "user_stop"
    DISCONNECT = "disconnect"
    SUPERSEDED = "superseded"
    SESSION_CLOSED = "session_closed"
    SHUTDOWN = "shutdown"
    PERMIT_REVOKED = "permit_revoked"
    UNKNOWN = "unknown"


class DiagnosticCode(StrEnum):
    UNAUTHENTICATED = "unauthenticated"
    PERMISSION_DENIED = "permission_denied"
    QUOTA_EXHAUSTED = "quota_exhausted"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    STORY_CHECKPOINT_PENDING = "story_checkpoint_pending"
    TRANSPORT_CONNECT = "transport_connect"
    TRANSPORT_PROXY = "transport_proxy"
    TRANSPORT_PROTOCOL = "transport_protocol"
    TRANSPORT_READ = "transport_read"
    TRANSPORT_WRITE = "transport_write"
    CODEX_STARTUP_READONLY_FILESYSTEM = "codex_startup_readonly_filesystem"
    INVALID_INPUT = "invalid_input"
    INVALID_RESPONSE = "invalid_response"
    INVALID_AUDIO = "invalid_audio"
    EMPTY_AUDIO = "empty_audio"
    LIMIT_REACHED = "limit_reached"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    DISCONNECTED = "disconnected"
    MEMORY_CONTEXT_STALE = "memory_context_stale"
    MEMORY_CONTEXT_OVERFLOW = "memory_context_overflow"
    MEMORY_TIMEOUT = "memory_timeout"
    MEMORY_UNAVAILABLE = "memory_unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DiagnosticContext:
    request_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    effect_id: str | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticEvent:
    stage: DiagnosticStage
    outcome: DiagnosticOutcome
    context: DiagnosticContext = DiagnosticContext()
    kind: DiagnosticKind = DiagnosticKind.FINISHED
    code: DiagnosticCode | None = None
    cancellation_reason: CancellationReason | None = None
    duration_ms: float | None = None
    http_status: int | None = None
    response_validation: SafeResponseValidation | None = None
    generation_diagnostic: SafeGenerationDiagnostic | None = None
    reported_confidence_warning: ReportedConfidenceWarning | None = None
    fixed_photo: SafeFixedPhotoDiagnostic | None = None
    wardrobe: SafeWardrobeDiagnostic | None = None
    optional_candidate_hold: SafeOptionalCandidateDiagnostic | None = None
    image_readiness: SafeImageReadinessDiagnostic | None = None
    native_tool: SafeNativeToolDiagnostic | None = None
    # No arbitrary provider name, message, URL, headers, metadata or body field.


class RecordingKind(StrEnum):
    DIALOGUE = "dialogue"
    MODEL_INPUT = "model_input"
    MODEL_OUTPUT = "model_output"
    AUDIO_INPUT = "audio_input"
    AUDIO_OUTPUT = "audio_output"


class ContentReview(StrEnum):
    APPROVED = "approved"
    REDACTED = "redacted"
    UNCERTAIN = "uncertain"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ReviewedRecording:
    """Caller attests this exact bounded buffer was reviewed, not merely its transcript.

    APPROVED/REDACTED is an explicit content-review boundary, never an automatic
    claim that a regex or ASR result can detect every secret. UNKNOWN is fail-closed.
    Raw SDK objects, HTTP envelopes and request headers are not accepted.
    """
    kind: RecordingKind
    context: DiagnosticContext = DiagnosticContext()
    review: ContentReview = ContentReview.UNCERTAIN
    text: str | None = field(default=None, repr=False)
    audio: bytes | None = field(default=None, repr=False)
    sample_rate_hz: int | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticStatus:
    available: bool = False
    recording_active: bool = False
    notice: str = ""
    accepted_events: int = 0
    written_events: int = 0
    dropped_events: int = 0
    accepted_recordings: int = 0
    written_recordings: int = 0
    dropped_recordings: int = 0
    io_failures: int = 0
    pending_records: int = 0


def emit_safely(sink, event: DiagnosticEvent) -> None:
    """A broken injected sink cannot alter an application transition."""
    if sink is not None:
        try:
            sink.emit(event)
        except Exception:
            pass


# A request-local correlation source, never a session state/authorization authority.
request_correlation: ContextVar[str | None] = ContextVar("mira_diagnostic_request", default=None)


def diagnostic_context(*, session_id: str | None = None, turn_id: str | None = None,
                       effect_id: str | None = None) -> DiagnosticContext:
    return DiagnosticContext(request_correlation.get(), session_id, turn_id, effect_id)


def correlation_hash(value: str) -> str:
    """The shared ordinary-log encoding, not a credential or authority token."""
    if type(value) is not str or not 1 <= len(value) <= 256:
        raise ValueError("invalid correlation")
    return "h_" + hashlib.sha256(value.encode()).hexdigest()[:32]


def safe_diagnostic_id(value) -> str | None:
    return value if type(value) is str and re.fullmatch(r"h_[0-9a-f]{32}", value) else None


def failure_diagnostic_id(context: DiagnosticContext) -> str | None:
    """Only actual request UUIDs get public locators; no origin means unavailable.

    HTTP/WS mint this ID before emitting events. Never substitute the active input
    command, poll request, exception body or an invented unlogged identifier.
    """
    value = context.request_id
    if type(value) is str and re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        return correlation_hash(value)
    return None


class DiagnosticSpan:
    """One operation's observed timing, without controlling that operation."""
    def __init__(self, sink, stage: DiagnosticStage, context: DiagnosticContext):
        self.sink, self.stage, self.context = sink, stage, context
        self._started = monotonic()
        self._finished = False
        self._observed_milestones: set[DiagnosticStage] = set()
        self.cancellation_reason: CancellationReason | None = None
        emit_safely(sink, DiagnosticEvent(stage, DiagnosticOutcome.STARTED, context,
                                         kind=DiagnosticKind.STARTED))

    def observe(self, stage: DiagnosticStage, outcome: DiagnosticOutcome = DiagnosticOutcome.SUCCEEDED) -> None:
        """Emit a fixed numeric milestone on the existing safe diagnostics sink."""
        if (self.stage != DiagnosticStage.STT
                or stage not in (DiagnosticStage.STT_FIRST_REVISION,
                                 DiagnosticStage.STT_FIRST_FINAL_REVISION,
                                 DiagnosticStage.STT_STREAM_END)
                or stage in self._observed_milestones
                or (self._finished and stage != DiagnosticStage.STT_STREAM_END)):
            return
        self._observed_milestones.add(stage)
        emit_safely(self.sink, DiagnosticEvent(stage, outcome, self.context,
            kind=DiagnosticKind.STATE_CHANGED,
            duration_ms=max(0.0, (monotonic() - self._started) * 1000)))

    def finish(self, outcome: DiagnosticOutcome, *, code: DiagnosticCode | None = None,
               reason: CancellationReason | None = None,
               response_validation: SafeResponseValidation | None = None,
               generation_diagnostic: SafeGenerationDiagnostic | None = None,
               reported_confidence_warning: ReportedConfidenceWarning | None = None) -> None:
        if self._finished:
            return
        self._finished = True
        self.cancellation_reason = reason
        emit_safely(self.sink, DiagnosticEvent(self.stage, outcome, self.context,
            code=code, cancellation_reason=reason, duration_ms=(monotonic() - self._started) * 1000,
            response_validation=response_validation,
            generation_diagnostic=generation_diagnostic,
            http_status=generation_diagnostic.http_status if generation_diagnostic else None,
            reported_confidence_warning=reported_confidence_warning))


def capture_text_safely(sink, kind: RecordingKind, text: str, context: DiagnosticContext) -> None:
    if sink is not None:
        try:
            sink.capture_text(kind, text, context)
        except Exception:
            pass


def capture_model_safely(sink, kind: RecordingKind, content, context: DiagnosticContext) -> None:
    # Avoid even buffering the logical model content when recording is off.
    if sink is not None:
        try:
            if not sink.status().recording_active:
                return
            import json
            from dataclasses import asdict
            sink.capture_text(kind, json.dumps(asdict(content), ensure_ascii=False), context)
        except Exception:
            pass
