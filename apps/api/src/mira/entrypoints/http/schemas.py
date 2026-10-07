"""Wire v0.1.0-foundation; deliberately NOT the full voice-v0.2 protocol.

Canonical public schemas live here. Generated OpenAPI/TypeScript are read-only.
"""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mira.domain.models import AudioStatus, EffectKind, Phase

WIRE_VERSION = "0.1.0-foundation"
DiagnosticId = Annotated[str, Field(pattern=r"^h_[0-9a-f]{32}$", min_length=34, max_length=34)]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OperatorPairRequest(WireModel):
    code: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[\x21-\x7e]+$")]


class OperatorPairStatus(WireModel):
    required: bool
    paired: bool
    revoked: bool


ManagementEntryId = Annotated[str, Field(
    min_length=1, max_length=128, pattern=r"^[^\s\x00-\x1f\x7f]+$"
)]
ManagementOperationId = UUID


class MemoryManagementStatusView(WireModel):
    enabled: bool
    revision: Annotated[int, Field(strict=True, ge=0)] | None


class MemoryManagementEntryView(WireModel):
    entry_id: ManagementEntryId
    text: Annotated[str, Field(min_length=1, max_length=16384)]
    kind: Literal["episodic", "boundary"]
    source: Literal["user_statement"] = "user_statement"
    source_version: Annotated[int, Field(strict=True, ge=1)]
    recorded_at: Annotated[str, Field(min_length=20, max_length=64)]
    active: bool
    forget_event_id: ManagementEntryId | None
    forgotten_at: Annotated[str, Field(min_length=20, max_length=64)] | None


class MemoryManagementPageView(WireModel):
    revision: Annotated[int, Field(strict=True, ge=0)]
    entries: Annotated[list[MemoryManagementEntryView], Field(max_length=20)]
    next_cursor: Annotated[str, Field(max_length=64)] | None


class MemoryManagementOperationRequest(WireModel):
    operation_id: ManagementOperationId
    expected_revision: Annotated[int, Field(strict=True, ge=0)]
    operation: Literal["record", "correct", "forget", "restore"]
    confirmed: Literal[True]
    text: Annotated[str, Field(min_length=1, max_length=4096, pattern=r"\S")] | None = None
    kind: Literal["episodic", "boundary"] | None = None
    entry_id: ManagementEntryId | None = None
    forget_event_id: ManagementEntryId | None = None

    @field_validator("confirmed", mode="before")
    @classmethod
    def strict_confirmation(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("operation confirmation must be the boolean true")
        return value

    @model_validator(mode="after")
    def exact_operation_fields(self):
        if self.confirmed is not True:
            raise ValueError("operation confirmation must be true")
        if self.operation == "record":
            valid = (self.text is not None and self.kind is not None
                     and self.entry_id is None and self.forget_event_id is None)
        elif self.operation == "correct":
            valid = (self.text is not None and self.kind is None
                     and self.entry_id is not None and self.forget_event_id is None)
        elif self.operation == "forget":
            valid = (self.text is None and self.kind is None
                     and self.entry_id is not None and self.forget_event_id is None)
        else:
            valid = (self.text is None and self.kind is None
                     and self.entry_id is None and self.forget_event_id is not None)
        if not valid:
            raise ValueError("operation fields do not match the selected memory action")
        return self


class MemoryManagementOperationView(WireModel):
    status: Literal["committed"] = "committed"
    operation_id: str
    revision: Annotated[int, Field(strict=True, ge=0)]
    entry_id: ManagementEntryId | None = None
    event_id: ManagementEntryId | None = None
    replayed: bool = False


class MemoryManagementErrorView(WireModel):
    code: str
    message: str
    request_id: str
    current_revision: Annotated[int, Field(strict=True, ge=0)] | None = None


class CreateSessionRequest(WireModel):
    client_instance_id: UUID


class ChapterChoiceRequest(WireModel):
    choice: Literal['accept', 'decline']
    offer_id: Annotated[str, Field(min_length=1, max_length=128,
        pattern=r'^[^\s\x00-\x1f\x7f]+$')]
    offer_effect_id: UUID
    offer_effect_digest: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class InputRequest(WireModel):
    request_id: UUID
    activity_seq: Annotated[int, Field(strict=True, ge=1)]
    presentation_cutoff: Annotated[int, Field(strict=True, ge=0)]
    text: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]
    source_audio_stream_id: UUID | None = None
    listening_utterance_id: UUID | None = None
    relation: Literal["independent", "continuation", "new_topic"] = "independent"
    continuation_of_request_id: UUID | None = None
    continuation_of_output_epoch: Annotated[int, Field(strict=True, ge=1)] | None = None
    chapter_choice: ChapterChoiceRequest | None = None

    @model_validator(mode="after")
    def exact_continuation_identity(self):
        has_request = self.continuation_of_request_id is not None
        has_epoch = self.continuation_of_output_epoch is not None
        if ((self.relation == "continuation" and not (has_request and has_epoch))
                or (self.relation != "continuation" and (has_request or has_epoch))):
            raise ValueError("input relation does not match its continuation identity")
        return self

    @model_validator(mode="after")
    def one_audio_source(self):
        if self.source_audio_stream_id is not None and self.listening_utterance_id is not None:
            raise ValueError("input cannot cite two audio sources")
        return self

    @model_validator(mode='after')
    def explicit_chapter_choice(self):
        if self.chapter_choice is None:
            return self
        if (self.relation != 'independent' or self.source_audio_stream_id is not None
                or self.listening_utterance_id is not None):
            raise ValueError('chapter choices are explicit local button inputs')
        expected = '我收下这张照片' if self.chapter_choice.choice == 'accept' else '暂时不收照片'
        if self.text != expected:
            raise ValueError('chapter choice text does not match its explicit choice')
        return self


class StopRequest(WireModel):
    scope: Literal["all", "reply"] = "all"
    activity_seq: Annotated[int, Field(strict=True, ge=1)]
    presentation_cutoff: Annotated[int, Field(strict=True, ge=0)]


class ResponsePreferenceRequest(WireModel):
    muted: Annotated[bool, Field(strict=True)]
    expected_revision: Annotated[int, Field(strict=True, ge=0)]


class PhotoDismissRequest(WireModel):
    target: Literal["display", "fixed_photo", "image_job", "all_photos"] = "display"
    expected_photo_effect_id: UUID | None = None
    expected_image_request_id: UUID | None = None
    request_id: UUID
    expected_revision: Annotated[int, Field(strict=True, ge=0)]
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


class CaptionChunkView(WireModel):
    group_id: str
    index: int
    start: int
    end: int
    total: int
    source_sha256: str


class EffectView(WireModel):
    id: str
    kind: EffectKind
    value: str
    digest: str
    output_epoch: int
    activity_seq: int
    cue_id: str | None = None
    cue_speech_id: str | None = None
    caption_chunk: CaptionChunkView | None = None


class StoryImageView(WireModel):
    capability: Literal['unavailable','bounded_fiction'] = 'unavailable'
    state: Literal['unavailable','idle','held','pending','generating','reviewing','qualified','presented','failed','cancelled'] = 'unavailable'
    request_id: str | None = None
    scene_id: str | None = None
    resource_id: str | None = None
    content_digest: str | None = None
    failure_code: Literal['unavailable','ineligible','budget','generation','review','timeout','cancelled'] | None = None
    completion_state: Literal['unavailable','pending','context_consumed','requested','granted','presented','failed','cancelled'] = 'unavailable'
    completion_effect_id: UUID | None = None
    completion_speech_effect_id: UUID | None = None
    completion_available: bool = False


class StoryImageCompletionRequest(WireModel):
    request_id: UUID
    parent_request_id: UUID
    output_epoch: Annotated[int, Field(strict=True, ge=1)]
    activity_seq: Annotated[int, Field(strict=True, ge=1)]
    presented_effect_id: UUID | None = None


class StoryImageResourceRequest(WireModel):
    effect_id: UUID
    digest: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    output_epoch: Annotated[int, Field(strict=True, ge=0)]
    activity_seq: Annotated[int, Field(strict=True, ge=0)]
    content_digest: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class FixedPhotoView(WireModel):
    state: Literal['idle','pending','held','granted','preparing','receipt_pending','presented','failed','cancelled','dismissed'] = 'idle'
    reason: Literal['unavailable','already_visible','dismissed','review_unknown','review_rejected','review_failed','optional_ineligible','preparation_failed','presentation_failed','receipt_unconfirmed','cancelled'] | None = None
    attempt_seq: Annotated[int, Field(strict=True, ge=0)] = 0
    output_epoch: Annotated[int, Field(strict=True, ge=0)] = 0
    activity_seq: Annotated[int, Field(strict=True, ge=0)] = 0
    effect_id: UUID | None = None


class FixedPhotoProgressRequest(WireModel):
    effect_id: UUID
    digest: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    output_epoch: Annotated[int, Field(strict=True, ge=0)]
    activity_seq: Annotated[int, Field(strict=True, ge=0)]
    outcome: Literal['preparing','preparation_failed','presentation_failed','receipt_pending']


class ChapterProjectionView(WireModel):
    schema_: Literal['mira.xiahe-chapter.v1'] = Field(alias='schema')
    source_hash: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    stage: Literal['stranger_cafe', 'recognized', 'old_friend_story', 'photo_promise',
                   'photo_previewed', 'gift_offered', 'gift_declined', 'completed']
    role_active: Annotated[bool, Field(strict=True)]
    role_name: Literal['夏禾'] | None
    active_gift_offer_id: Annotated[str, Field(min_length=1, max_length=128,
        pattern=r'^[^\s\x00-\x1f\x7f]+$')] | None
    gift_offer_effect_id: UUID | None
    gift_offer_effect_digest: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')] | None
    pending_transition: Literal['x.recognize', 'x.story', 'x.promise', 'x.preview',
        'x.gift_offer', 'x.gift_accept', 'x.gift_decline', 'x.exit'] | None
    completed: Annotated[bool, Field(strict=True)]
    revision: Annotated[int, Field(strict=True, ge=0)]
    suspended: Annotated[bool, Field(strict=True)]


class SessionView(WireModel):
    presentation_floor: Annotated[int, Field(strict=True, ge=0)] = 0
    retired_user_inputs: Annotated[int, Field(strict=True, ge=0)] = 0
    chapter_projection: ChapterProjectionView | None = None
    fixed_photo: FixedPhotoView = FixedPhotoView()
    story_image: StoryImageView = StoryImageView()
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
    photo_visible: bool = False
    photo_visibility_revision: int = 0
    last_error: str | None
    last_error_diagnostic_id: DiagnosticId | None = None
    response_muted: bool = False
    response_mode: Literal["voice", "text_only"] = "voice"
    response_preference_revision: Annotated[int, Field(strict=True, ge=0)] = 0


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


class ReviewedAudioRecordingRequest(WireModel):
    enabled: Annotated[bool, Field(strict=True)]
    consent: Annotated[bool, Field(strict=True)] = False


class ReviewedAudioStatusResponse(WireModel):
    scope: Literal["application"] = "application"
    recording_active: bool
    has_pending_audio: bool
    staged_bytes: Annotated[int, Field(ge=0)]
    max_audio_bytes: Annotated[int, Field(ge=2, le=512 * 1024)]
    expires_in_seconds: Annotated[float, Field(ge=0, le=60)]
    pending_stream_id: UUID | None = None
    pending_kind: Literal["audio_input", "audio_output"] | None = None
    input_completion_ready: bool
    notice: str
    scope_notice: str


class ReviewedAudioReviewResponse(WireModel):
    scope: Literal["application"] = "application"
    scope_notice: str
    review_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    kind: Literal["audio_input", "audio_output"]
    sample_rate_hz: Literal[16000, 24000, 48000]
    byte_count: Annotated[int, Field(strict=True, ge=2, le=512 * 1024)]
    expires_in_seconds: Annotated[float, Field(ge=0, le=60)]
    preview_path: str
    notice: str


class ReviewedAudioConfirmRequest(WireModel):
    reviewed_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    review: Literal["approved", "rejected", "uncertain"]
    persist_consent: Annotated[bool, Field(strict=True)]


class ReviewedAudioActionResponse(WireModel):
    scope: Literal["application"] = "application"
    scope_notice: str
    ok: bool
    code: str
    message: str
    recording_active: bool
    accepted_for_queue: bool = False


class VoiceCapabilities(WireModel):
    generation_mode: Literal["mock", "replay", "rehearsal", "injected"]
    speech_enabled: bool
    microphone_enabled: bool
    continuous_listening_enabled: bool = False
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


class ContinuousListeningStart(WireModel):
    type: Literal["start"]
    session_token: Annotated[str, Field(min_length=1, max_length=128, repr=False)]
    lease_id: UUID
    mode: Literal["manual", "natural"] = "manual"
    client_endpointing: bool = False


class ContinuousListeningAudio(WireModel):
    type: Literal["audio"]
    lease_id: UUID
    sequence: Annotated[int, Field(strict=True, ge=1)]
    first_sample: Annotated[int, Field(strict=True, ge=0)]
    pcm_base64: Annotated[str, Field(min_length=4, max_length=16_000)]


class ContinuousListeningStop(WireModel):
    type: Literal["stop"]
    lease_id: UUID
    reason: Literal["user_stop", "permission_lost"] = "user_stop"


class ContinuousListeningClientEndpoint(WireModel):
    type: Literal["client_endpoint"]
    lease_id: UUID
    endpoint_id: UUID
    source_end_sample: Annotated[int, Field(strict=True, ge=1)]


class ContinuousListeningCancelEndpoint(WireModel):
    type: Literal["cancel_endpoint"]
    lease_id: UUID
    endpoint_id: UUID


class ContinuousListeningEndpointStatus(WireModel):
    type: Literal["endpoint_status"] = "endpoint_status"
    lease_id: UUID
    endpoint_id: UUID
    source_end_sample: Annotated[int, Field(strict=True, ge=1)]
    state: Literal["queued", "draining", "cancelled", "completed"]


class ContinuousListeningReady(WireModel):
    type: Literal["ready"] = "ready"
    lease_id: UUID
    sample_rate_hz: Literal[16000] = 16000
    max_seconds: Annotated[int, Field(strict=True, ge=1, le=290)] | None
    max_samples: Annotated[int, Field(strict=True, ge=1, le=16_000 * 290)] | None
    max_utterances: Annotated[int, Field(strict=True, ge=1, le=32)] | None
    max_streams_per_session: Annotated[int, Field(strict=True, ge=1, le=16)] | None
    max_total_streams: Annotated[int, Field(strict=True, ge=1, le=100)] | None
    session_lease_starts_used: Annotated[int, Field(strict=True, ge=1)]
    total_lease_starts_used: Annotated[int, Field(strict=True, ge=1)]
    stt_requests_used: Annotated[int, Field(strict=True, ge=0)] | None = None
    stt_requests_remaining: Annotated[int, Field(strict=True, ge=0, le=100)] | None = None
    endpoint_mode: Literal["google_vad_offsets_manual_commit", "google_vad_offsets_natural", "unavailable_manual"]
    manual_commit_required: bool = True
    client_endpoint_supported: bool = False
    client_silence_ms: Annotated[int, Field(strict=True, ge=250, le=2_000)] = 700
    natural_grace_ms: Annotated[int, Field(strict=True, ge=0, le=2_000)] = 0
    drain_timeout_ms: Annotated[int, Field(strict=True, ge=100, le=5_000)] = 2_000
    max_recognition_streams: Annotated[int, Field(strict=True, ge=1, le=32)] | None = 1


class ContinuousListeningTranscript(WireModel):
    type: Literal["transcript"] = "transcript"
    lease_id: UUID
    revision: Annotated[int, Field(strict=True, ge=1)]
    text: Annotated[str, Field(max_length=2_000)]
    is_final: bool
    committed_commit_id: UUID | None = None
    committed_utterance_id: UUID | None = None


class ContinuousListeningCommit(WireModel):
    type: Literal["commit"]
    lease_id: UUID
    commit_id: UUID
    revision: Annotated[int, Field(strict=True, ge=1)]
    utterance_id: UUID | None = None


class ContinuousListeningHold(WireModel):
    type: Literal["hold"]
    lease_id: UUID
    utterance_id: UUID
    revision: Annotated[int, Field(strict=True, ge=1)]


class ContinuousListeningHeld(WireModel):
    type: Literal["utterance_held"] = "utterance_held"
    lease_id: UUID
    utterance_id: UUID
    revision: Annotated[int, Field(strict=True, ge=1)]
    text: Annotated[str, Field(min_length=1, max_length=2_000)]


class ContinuousListeningHoldRejected(WireModel):
    type: Literal["hold_rejected"] = "hold_rejected"
    lease_id: UUID
    utterance_id: UUID
    revision: Annotated[int, Field(strict=True, ge=1)]
    reason: Literal["stale_revision", "lease_revoked", "identity_conflict", "request_limit"]
    current_revision: Annotated[int, Field(strict=True, ge=0)]


class ContinuousListeningCommitReady(WireModel):
    type: Literal["commit_ready"] = "commit_ready"
    lease_id: UUID
    commit_id: UUID
    segment_seq: Annotated[int, Field(strict=True, ge=1)]
    revision: Annotated[int, Field(strict=True, ge=1)]
    text: Annotated[str, Field(min_length=1, max_length=2_000)]
    utterance_id: UUID | None = None


class ContinuousListeningUtteranceReady(WireModel):
    type: Literal["utterance_ready"] = "utterance_ready"
    lease_id: UUID
    utterance_id: UUID
    revision: Annotated[int, Field(strict=True, ge=1)]
    text: Annotated[str, Field(min_length=1, max_length=2_000)]
    begin_offset_samples: Annotated[int, Field(strict=True, ge=0)]
    end_offset_samples: Annotated[int, Field(strict=True, ge=0)]
    final_offset_samples: Annotated[int, Field(strict=True, ge=0)] | None
    endpoint_basis: Literal["offset_coverage", "vad_final_grace", "stream_finalized", "client_silence_finalized"] = "offset_coverage"
    client_endpoint_id: UUID | None = None
    source_end_sample: Annotated[int, Field(strict=True, ge=1)]

    @model_validator(mode="after")
    def valid_endpoint_evidence(self):
        if (self.endpoint_basis == "client_silence_finalized") != (self.client_endpoint_id is not None):
            raise ValueError("client endpoint identity must match its endpoint basis")
        if not self.begin_offset_samples <= self.end_offset_samples <= self.source_end_sample:
            raise ValueError("invalid natural endpoint audio range")
        final = self.final_offset_samples
        if self.endpoint_basis not in {"stream_finalized", "client_silence_finalized"} and final is None:
            raise ValueError("this endpoint basis requires a final audio offset")
        if final is not None and not self.begin_offset_samples <= final <= self.source_end_sample:
            raise ValueError("final offset is outside the utterance audio range")
        if self.endpoint_basis == "offset_coverage" and final < self.end_offset_samples:
            raise ValueError("final offset does not cover the activity end")
        return self


class ContinuousListeningRecognitionStatus(WireModel):
    type: Literal["recognition_status"] = "recognition_status"
    lease_id: UUID
    stream_index: Annotated[int, Field(strict=True, ge=1)]
    state: Literal["opening", "listening", "draining", "awaiting_commit", "completed", "limit"]
    stt_requests_used: Annotated[int, Field(strict=True, ge=0)] | None = None
    stt_requests_remaining: Annotated[int, Field(strict=True, ge=0, le=100)] | None = None


class ContinuousListeningUtteranceRevision(WireModel):
    type: Literal["utterance_revision"] = "utterance_revision"
    lease_id: UUID
    utterance_id: UUID
    commit_id: UUID
    revision: Annotated[int, Field(strict=True, ge=1)]
    text: Annotated[str, Field(min_length=1, max_length=2_000)]
    reason: Literal["late_result_after_submission"] = "late_result_after_submission"
    requires_review: Literal[True] = True
    submission_state: Literal["pending", "reserved", "accepted", "revoked", "unknown"]


class ContinuousListeningCommitRejected(WireModel):
    type: Literal["commit_rejected"] = "commit_rejected"
    lease_id: UUID
    commit_id: UUID
    reason: Literal["stale_revision", "no_final_text", "request_limit", "lease_revoked",
                    "identity_conflict", "pending_capacity"]
    current_revision: Annotated[int, Field(strict=True, ge=0)]


class ContinuousListeningEndpointPending(WireModel):
    type: Literal["endpoint_pending"] = "endpoint_pending"
    lease_id: UUID
    revision: Annotated[int, Field(strict=True, ge=1)]
    text: Annotated[str, Field(max_length=2_000)]
    reason: Literal["missing_result_offset", "unmatched_activity_end"]
    can_submit_manually: bool = True


class ContinuousListeningStopped(WireModel):
    type: Literal["stopped"] = "stopped"
    lease_id: UUID
    reason: Literal["user_stop", "permission_lost", "replaced", "max_duration",
                    "max_samples", "queue_limit", "revision_limit", "utterance_limit",
                    "provider_stream_ended", "unavailable", "invalid_input",
                    "invalid_response", "session_closed", "disconnect", "output_limit",
                    "session_capacity", "microphone_unavailable", "input_limit", "invalid_audio",
                    "timeout", "unauthenticated", "permission_denied", "quota_exhausted",
                    "media_cancelled", "incomplete_stream", "blocked", "response_limit",
                    "service_budget_exhausted"]
    diagnostic_id: DiagnosticId | None = None


# WebSocket/NDJSON models are exported with the HTTP schemas; no hand-written TS copy.
MEDIA_WIRE_MODELS = (SpeechAudioFrame, SpeechCompleteFrame, SpeechErrorFrame,
                     MicrophoneStart, MicrophoneAudio, MicrophoneControl, MicrophoneReady,
                     MicrophoneTranscript, MicrophoneComplete, MicrophoneError,
                     ContinuousListeningStart, ContinuousListeningAudio, ContinuousListeningStop,
                     ContinuousListeningReady, ContinuousListeningTranscript,
                     ContinuousListeningCommit, ContinuousListeningCommitReady,
                     ContinuousListeningHold, ContinuousListeningHeld, ContinuousListeningHoldRejected,
                     ContinuousListeningUtteranceReady, ContinuousListeningUtteranceRevision,
                     ContinuousListeningRecognitionStatus,
                     ContinuousListeningClientEndpoint, ContinuousListeningCancelEndpoint,
                     ContinuousListeningEndpointStatus,
                     ContinuousListeningCommitRejected, ContinuousListeningEndpointPending,
                     ContinuousListeningStopped)


ConversationSessionId = Annotated[str, Field(min_length=1, max_length=128, pattern=r'^[^\s\x00-\x20\x7f]+$')]


class ConversationStatusView(WireModel):
    enabled: bool
    persistence_status: Literal['disabled','enabled_no_committed_records','pending','saved',
        'unavailable','write_outcome_unknown','unavailable_or_write_outcome_unknown','rejected','revoked_existing_records_retained']
    management_enabled: bool = False
    recall_session_id: ConversationSessionId | None = None
    current_session_id: ConversationSessionId | None = None
    selection_locked: bool = False
    recipients: str = ''
    speech_enabled: bool = False
    recall_authorized: bool = False
    google_authorized: bool = False


class ConversationSessionsView(WireModel):
    revision: Annotated[int, Field(strict=True, ge=0)]
    sessions: Annotated[list[ConversationSessionId], Field(max_length=20)]
    next_cursor: Annotated[str, Field(max_length=64)] | None


class ConversationEntryView(WireModel):
    entry_id: ManagementEntryId
    source_version: Annotated[int, Field(strict=True, ge=1)]
    stage: Literal['accepted_input','corrected_input','presented_effect','audio_progress']
    active: bool
    text: Annotated[str, Field(min_length=1, max_length=8192)]
    output_epoch: Annotated[int, Field(strict=True, ge=1)]
    request_id: ConversationSessionId | None
    input_source: Literal['text','asr_final'] | None
    effect_kind: EffectKind | None
    rendered_samples: Annotated[int, Field(strict=True, ge=0)] | None
    sample_rate_hz: Annotated[int, Field(strict=True, ge=8000, le=48000)] | None
    audio_status: AudioStatus | None
    forget_event_id: ManagementEntryId | None


class ConversationPageView(WireModel):
    session_id: ConversationSessionId
    revision: Annotated[int, Field(strict=True, ge=0)]
    entries: Annotated[list[ConversationEntryView], Field(max_length=20)]
    next_cursor: Annotated[str, Field(max_length=64)] | None


class ConversationSelectionRequest(WireModel):
    session_id: ConversationSessionId | None
    authorize_selected_provider_and_jev: Annotated[bool, Field(strict=True)]
    authorize_google_derived_speech: Annotated[bool, Field(strict=True)] = False


class ConversationOperationRequest(MemoryManagementOperationRequest):
    operation: Literal['correct','forget','restore']
    session_id: ConversationSessionId


class ConversationRevokeRequest(WireModel):
    confirmed: Annotated[bool, Field(strict=True)]

    @field_validator('confirmed')
    @classmethod
    def must_confirm(cls,value):
        if value is not True:raise ValueError('confirmation_required')
        return value
