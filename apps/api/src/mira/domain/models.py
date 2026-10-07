"""Immutable application facts. Standard library only; no transport or environment."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from mira.domain.fixed_photo import FixedPhotoStatus
from mira.domain.chapter_presentation import ChapterPresentation
from mira.domain.story_images import ImageReservation, StoryImageStatus, StoryImageFact, parse_generated_photo


class EffectKind(StrEnum):
    SUBTITLE = "subtitle"
    SPEECH = "speech"
    POSE = "pose"
    SCENE = "scene"
    MEDIA = "media"


class Phase(StrEnum):
    IDLE = "idle"
    THINKING = "thinking"
    READY = "ready"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class CaptionChunk:
    """Application-owned disjoint original-text range; offsets are Unicode code points."""
    group_id: str
    index: int
    start: int
    end: int
    total: int
    source_sha256: str


@dataclass(frozen=True, slots=True)
class Effect:
    id: str
    kind: EffectKind
    value: str
    digest: str
    output_epoch: int
    activity_seq: int
    # Assigned by the application compiler; never by model output.
    cue_id: str | None = None
    cue_speech_id: str | None = None
    caption_chunk: CaptionChunk | None = None


@dataclass(frozen=True, slots=True)
class Receipt:
    effect_id: str
    digest: str
    output_epoch: int
    activity_seq: int
    presentation_seq: int


class AudioStatus(StrEnum):
    RENDERED = "rendered"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AudioProgress:
    """Software-render evidence only, never physical hearing or word alignment."""
    effect_id: str
    digest: str
    output_epoch: int
    activity_seq: int
    presentation_seq: int
    sample_rate_hz: int
    rendered_samples: int
    status: AudioStatus


@dataclass(frozen=True, slots=True)
class Fence:
    output_epoch: int
    presentation_cutoff: int


@dataclass(frozen=True, slots=True)
class SessionState:
    session_id: str
    client_instance_id: str
    revision: int = 0
    activity_seq: int = 0
    input_epoch: int = 0
    output_epoch: int = 0
    permit_revision: int = 0
    phase: Phase = Phase.IDLE
    request_id: str | None = None
    sealed: bool = False
    active_grants: tuple[Effect, ...] = ()
    issued_effects: tuple[Effect, ...] = ()
    receipts: tuple[Receipt, ...] = ()
    audio_progress: tuple[AudioProgress, ...] = ()
    fences: tuple[Fence, ...] = ()
    last_presentation_cutoff: int = 0
    user_inputs: tuple[str, ...] = ()
    # Confirmed old presentation prefix and count omitted from recent RAM context.
    presentation_floor: int = 0
    retired_user_inputs: int = 0
    last_error: str | None = None
    image_reservations: tuple[ImageReservation, ...] = ()
    image_cancellation_generation: int = 0
    story_image: StoryImageStatus = StoryImageStatus()
    fixed_photo: FixedPhotoStatus = FixedPhotoStatus()
    story_image_facts: tuple[StoryImageFact, ...] = ()
    # Current authored-photo display is separate from immutable exposure receipts.
    photo_visible: bool = False
    photo_visibility_revision: int = 0
    photo_dismissed_through_activity: int = -1
    photo_dismissal_cutoff: int = 0
    image_dismissed_through_activity: int = -1
    image_dismissal_cutoff: int = 0
    # Diagnostic-only immutable failure fact; never current branch authority.
    last_error_diagnostic_id: str | None = None
    # App-owned user preference. Restoring voice applies only to a later input.
    response_muted: bool = False
    response_mode: Literal["voice", "text_only"] = "voice"
    response_preference_revision: int = 0
    # Derived from story state by Actor; never accepted from a client or persisted separately.
    chapter_projection: ChapterPresentation | None = None

    @property
    def presented_effects(self) -> tuple[Effect, ...]:
        ids = {r.effect_id for r in self.receipts} | {
            p.effect_id for p in self.audio_progress if p.status == AudioStatus.COMPLETED
        }
        presented = tuple(e for e in self.issued_effects if e.id in ids)
        # Preserve legacy issuance ordering and all non-photo positions. When a
        # generated photo participates, only this shared photo surface needs its
        # competing fixed/generated entries in actual presentation sequence.
        if not any(e.kind is EffectKind.MEDIA and parse_generated_photo(e.value)
                   for e in presented):
            return presented
        photo_ids = {e.id for e in presented if e.kind is EffectKind.MEDIA
                     and (e.value in ('trip_photo', 'trip_photo_placeholder')
                          or parse_generated_photo(e.value) is not None)}
        sequence = {receipt.effect_id: receipt.presentation_seq for receipt in self.receipts}
        photos = iter(sorted((e for e in presented if e.id in photo_ids),
                             key=lambda effect: sequence[effect.id]))
        return tuple(next(photos) if e.id in photo_ids else e for e in presented)
