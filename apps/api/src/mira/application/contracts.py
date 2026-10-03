"""Transport-independent inputs/outputs of generation and review adapters."""
from dataclasses import dataclass
from enum import StrEnum

from mira.domain.models import AudioProgress, Effect, EffectKind


def audio_context_progress(progress: tuple[AudioProgress, ...]) -> tuple[AudioProgress, ...]:
    """Project cumulative latest facts for model context, preserving the owner's ledger.

    Samples and status are copied verbatim: partial rendering never becomes completed
    or heard words. Full immutable effect identity prevents collapsing conflicting
    imported identities. Presentation sequence gives deterministic cross-effect order.
    Provider byte/effect bounds remain enforced; this is not unbounded history storage.
    """
    latest = {}
    for fact in progress:
        latest[(fact.effect_id, fact.digest, fact.output_epoch, fact.activity_seq)] = fact
    return tuple(sorted(latest.values(), key=lambda fact: fact.presentation_seq))


@dataclass(frozen=True, slots=True)
class EffectProposal:
    kind: EffectKind
    value: str


@dataclass(frozen=True, slots=True)
class CandidateRange:
    """A complete fixture range, never a raw token delta or provider progress log."""
    effects: tuple[EffectProposal, ...]
    fixture_id: str


@dataclass(frozen=True, slots=True)
class GenerationContext:
    user_text: str
    user_inputs: tuple[str, ...]
    presented_effects: tuple[Effect, ...]
    output_epoch: int
    accepted_prefix: tuple[Effect, ...] = ()
    # Partial software rendering is not a claim that the entire speech text was heard.
    audio_progress: tuple[AudioProgress, ...] = ()


class ReviewVerdict(StrEnum):
    ALLOW = "allow"
    REJECT = "reject"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ReviewObservation:
    verdict: ReviewVerdict
    reason_code: str


@dataclass(frozen=True, slots=True)
class AuditEvent:
    sequence: int
    session_id: str
    kind: str
    state_revision: int
    output_epoch: int
    occurred_at: str
