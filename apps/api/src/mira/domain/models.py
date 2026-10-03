"""Immutable application facts. Standard library only; no transport or environment."""
from dataclasses import dataclass
from enum import StrEnum


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
    last_error: str | None = None
    # Diagnostic-only immutable failure fact; never current branch authority.
    last_error_diagnostic_id: str | None = None

    @property
    def presented_effects(self) -> tuple[Effect, ...]:
        ids = {r.effect_id for r in self.receipts} | {
            p.effect_id for p in self.audio_progress if p.status == AudioStatus.COMPLETED
        }
        return tuple(e for e in self.issued_effects if e.id in ids)
