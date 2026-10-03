"""Wire v0.1.0-foundation; deliberately NOT the full voice-v0.2 protocol.

Canonical public schemas live here. Generated OpenAPI/TypeScript are read-only.
"""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from mira.domain.models import AudioStatus, EffectKind, Phase

WIRE_VERSION = "0.1.0-foundation"
DiagnosticId = Annotated[str, Field(pattern=r"^h_[0-9a-f]{32}$", min_length=34, max_length=34)]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateSessionRequest(WireModel):
    client_instance_id: UUID


class InputRequest(WireModel):
    request_id: UUID
    activity_seq: Annotated[int, Field(strict=True, ge=1)]
    presentation_cutoff: Annotated[int, Field(strict=True, ge=0)]
    text: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]


class StopRequest(WireModel):
    activity_seq: Annotated[int, Field(strict=True, ge=1)]
    presentation_cutoff: Annotated[int, Field(strict=True, ge=0)]


class ReceiptRequest(WireModel):
    effect_id: UUID
    digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    output_epoch: Annotated[int, Field(strict=True, ge=1)]
    activity_seq: Annotated[int, Field(strict=True, ge=1)]
    presentation_seq: Annotated[int, Field(strict=True, ge=1)]


class AudioProgressRequest(ReceiptRequest):
    sample_rate_hz: Annotated[int, Field(strict=True, ge=8000, le=48000)]
    rendered_samples: Annotated[int, Field(strict=True, ge=0, le=48000 * 300)]
    status: AudioStatus


class AudioProgressView(WireModel):
    effect_id: str
    digest: str
    output_epoch: int
    activity_seq: int
    presentation_seq: int
    sample_rate_hz: int
    rendered_samples: int
    status: AudioStatus


class EffectView(WireModel):
    id: str
    kind: EffectKind
    value: str
    digest: str
    output_epoch: int
    activity_seq: int
    cue_id: str | None = None
    cue_speech_id: str | None = None


class SessionView(WireModel):
    schema_version: Literal["0.1.0-foundation"] = WIRE_VERSION
    session_id: str
    client_instance_id: str
    revision: int
    activity_seq: int
    input_epoch: int
    output_epoch: int
    permit_revision: int
    phase: Phase
    request_id: str | None
    sealed: bool
    active_grants: list[EffectView]
    presented_effects: list[EffectView]
    audio_progress: list[AudioProgressView]
    last_error: str | None
    last_error_diagnostic_id: DiagnosticId | None = None


class CreateSessionResponse(WireModel):
    session: SessionView
    session_token: str


class AuditEventView(WireModel):
    sequence: int
    kind: str
    state_revision: int
    output_epoch: int
    occurred_at: str


class HealthResponse(WireModel):
    status: Literal["ok"] = "ok"
    mode: Literal["mock", "replay", "rehearsal", "injected"] = "mock"
    schema_version: str = WIRE_VERSION
    live_llm: bool | None = False
    live_audio: bool | None = False
    live_images: bool = False


class ErrorResponse(WireModel):
    code: str
    message: str
    request_id: str


class DiagnosticsStatusResponse(WireModel):
    available: bool
    recording_active: bool
    notice: str
    dropped_events: int
    dropped_recordings: int
    io_failures: int
    pending_records: int


class VoiceCapabilities(WireModel):
    generation_mode: Literal["mock", "replay", "rehearsal", "injected"]
    speech_enabled: bool
    microphone_enabled: bool
    speech_sample_rate_hz: Literal[24000] = 24000
    microphone_sample_rate_hz: Literal[16000] = 16000
    qualification: Literal["injected_unverified", "unavailable", "offline_fixture"]


class SpeechStreamRequest(WireModel):
    digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    output_epoch: Annotated[int, Field(strict=True, ge=1)]
    activity_seq: Annotated[int, Field(strict=True, ge=1)]


class SpeechOriginView(WireModel):
    effect_id: str
    digest: str
    output_epoch: int
    activity_seq: int
    stream_id: str


class SpeechAudioFrame(SpeechOriginView):
    type: Literal["audio"] = "audio"
    sequence: int
    first_sample: int
    sample_rate_hz: Literal[24000] = 24000
    pcm_base64: str


class SpeechCompleteFrame(SpeechOriginView):
    type: Literal["complete"] = "complete"
    total_samples: int


class SpeechErrorFrame(SpeechOriginView):
    type: Literal["error"] = "error"
    code: str
    diagnostic_id: DiagnosticId | None = None


class MicrophoneStart(WireModel):
    type: Literal["start"]
    session_token: Annotated[str, Field(min_length=1, max_length=128, repr=False)]
    stream_id: UUID
    activity_seq: Annotated[int, Field(strict=True, ge=0)]
    input_epoch: Annotated[int, Field(strict=True, ge=0)]
    sample_rate_hz: Literal[16000]


class MicrophoneAudio(WireModel):
    type: Literal["audio"]
    sequence: Annotated[int, Field(strict=True, ge=1, le=6100)]
    first_sample: Annotated[int, Field(strict=True, ge=0, le=16000 * 60)]
    pcm_base64: Annotated[str, Field(min_length=4, max_length=16000)]


class MicrophoneControl(WireModel):
    type: Literal["finish", "cancel"]


class MicrophoneReady(WireModel):
    type: Literal["ready"] = "ready"
    stream_id: str
    activity_seq: int
    input_epoch: int


class MicrophoneTranscript(WireModel):
    type: Literal["transcript"] = "transcript"
    stream_id: str
    revision: int
    text: str
    is_final: bool


class MicrophoneComplete(WireModel):
    type: Literal["complete"] = "complete"
    stream_id: str
    revision: int
    text: str
    had_final: bool


class MicrophoneError(WireModel):
    type: Literal["error"] = "error"
    code: str
    diagnostic_id: DiagnosticId | None = None


# WebSocket/NDJSON models are exported with the HTTP schemas; no hand-written TS copy.
MEDIA_WIRE_MODELS = (SpeechAudioFrame, SpeechCompleteFrame, SpeechErrorFrame,
                     MicrophoneStart, MicrophoneAudio, MicrophoneControl, MicrophoneReady,
                     MicrophoneTranscript, MicrophoneComplete, MicrophoneError)
