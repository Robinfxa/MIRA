"""Transport-independent, payload-free operational diagnostic contracts."""
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import re
from time import monotonic


class DiagnosticStage(StrEnum):
    HTTP = "http"
    SESSION = "session"
    GENERATION = "generation"
    INPUT_REVIEW = "input_review"
    OUTPUT_REVIEW = "output_review"
    STT = "stt"
    TTS = "tts"
    MICROPHONE = "microphone"
    PLAYBACK = "playback"
    DIAGNOSTICS = "diagnostics"


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
    INVALID_INPUT = "invalid_input"
    INVALID_RESPONSE = "invalid_response"
    INVALID_AUDIO = "invalid_audio"
    EMPTY_AUDIO = "empty_audio"
    LIMIT_REACHED = "limit_reached"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    DISCONNECTED = "disconnected"
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
        self.cancellation_reason: CancellationReason | None = None
        emit_safely(sink, DiagnosticEvent(stage, DiagnosticOutcome.STARTED, context,
                                         kind=DiagnosticKind.STARTED))

    def finish(self, outcome: DiagnosticOutcome, *, code: DiagnosticCode | None = None,
               reason: CancellationReason | None = None) -> None:
        if self._finished:
            return
        self._finished = True
        self.cancellation_reason = reason
        emit_safely(self.sink, DiagnosticEvent(self.stage, outcome, self.context,
            code=code, cancellation_reason=reason, duration_ms=(monotonic() - self._started) * 1000))


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
