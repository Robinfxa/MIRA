"""Application-owned immutable evidence; semantic observations never issue permits."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Literal

from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext
from mira.domain.models import AudioProgress, AudioStatus, Effect, EffectKind
from mira.domain.transitions import MAX_AUDIO_SECONDS

INPUT_QUESTION_SET = "mira-input-v1"
INPUT_PREDICATES = ("speech_restriction", "capture_restriction", "display_request")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def evidence_digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(asdict(value))).hexdigest()


@dataclass(frozen=True, slots=True)
class ReliableUserInput:
    event_id: str
    text: str = field(repr=False)
    source: Literal["text", "asr_final"] = "text"


@dataclass(frozen=True, slots=True)
class PresentationFact:
    effect: Effect = field(repr=False)
    status: Literal["presented", "partial", "unknown"]
    observed_text: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ControlledReferent:
    referent_id: str
    description: str = field(repr=False)
    presentation_effect_id: str


@dataclass(frozen=True, slots=True)
class DirectiveFact:
    directive_id: str
    raw_text: str = field(repr=False)
    source_ref: str
    scope: Literal["turn", "session"] = "turn"
    interpretation: Literal["authoritative", "observed", "unknown"] = "authoritative"


@dataclass(frozen=True, slots=True)
class AuthorPolicy:
    policy_revision: str
    character_revision: str
    capability_revision: str
    character_facts: tuple[str, ...]
    allowed_controls: tuple[EffectProposal, ...] = ()
    constraints: tuple[DirectiveFact, ...] = ()


@dataclass(frozen=True, slots=True)
class DecisionSnapshot:
    snapshot_id: str
    event_watermark: int
    activity_seq: int
    input_epoch: int
    input_revision: int
    generation_id: str
    context: GenerationContext = field(repr=False)
    reliable_inputs: tuple[ReliableUserInput, ...] = field(repr=False)
    author_policy: AuthorPolicy
    presentation_facts: tuple[PresentationFact, ...] = field(default=(), repr=False)
    referents: tuple[ControlledReferent, ...] = ()
    effective_constraints: tuple[DirectiveFact, ...] = ()
    response_obligations: tuple[DirectiveFact, ...] = ()
    local_stop: bool = False


class SemanticValue(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class InputDecisionStatus(StrEnum):
    OBSERVED = "observed"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class PredicateObservation:
    predicate: str
    value: SemanticValue
    probability: float | None = None


@dataclass(frozen=True, slots=True)
class ChoiceProbability:
    option: str
    probability: float


@dataclass(frozen=True, slots=True)
class ReferentObservation:
    status: Literal["resolved", "none", "ambiguous", "unknown"] = "unknown"
    referent_id: str | None = None
    probabilities: tuple[ChoiceProbability, ...] = ()
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class InputDecisionObservation:
    snapshot_id: str
    snapshot_digest: str
    status: InputDecisionStatus
    reason_code: str
    predicates: tuple[PredicateObservation, ...] = ()
    referent: ReferentObservation = ReferentObservation()
    question_set_revision: str = INPUT_QUESTION_SET
    calibration_ref: str | None = None
    request_digest: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    unresolved_items: tuple[str, ...] = field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class ResponseContract:
    contract_id: str
    contract_digest: str
    basis_snapshot_digest: str
    context_digest: str
    candidate_digest: str
    policy_revision: str
    effective_constraints: tuple[str, ...] = field(repr=False)
    response_obligations: tuple[str, ...] = field(repr=False)
    character_facts: tuple[str, ...]
    allowed_controls: tuple[EffectProposal, ...]
    scope: Literal["stage", "seal"]
    snapshot: DecisionSnapshot = field(repr=False)
    input_observation: InputDecisionObservation = field(repr=False)
    unresolved_items: tuple[str, ...] = ()


def mira26_author_policy() -> AuthorPolicy:
    return AuthorPolicy("mira26-author-v1", "mira26-v1", "mira26-controls-v1", (
        "MIRA是原创虚构角色，26岁，成年摄影师。",
        "当前虚构场景是雨夜的窗边咖啡馆；不代表用户的真实位置或天气。",
        "角色动作是受控视觉表现，不证明实际拍摄、读取用户影像或完成任何未回执的行为。",
    ), tuple(EffectProposal(EffectKind.POSE, value) for value in (
        "camera_ready", "camera_lowered", "look_at_rain", "face_calm", "face_warm",
        "face_curious", "face_reflective")) + tuple(
            EffectProposal(EffectKind.SCENE, value) for value in ("cafe", "rain_window", "cafe_warm")))


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}")


def _identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _text(value: object, maximum: int = 4096) -> bool:
    if type(value) is not str or not 0 < len(value) <= maximum or not value.strip():
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def _tuple(value: object, maximum: int) -> bool:
    return type(value) is tuple and len(value) <= maximum


def _effect(value: object, *, compiled: bool) -> bool:
    expected = Effect if compiled else EffectProposal
    if type(value) is not expected or type(value.kind) is not EffectKind or not _text(value.value):
        return False
    return not compiled or (_identifier(value.id) and _text(value.digest, 160)
        and type(value.output_epoch) is int and value.output_epoch >= 0
        and type(value.activity_seq) is int and value.activity_seq >= 0)


def _directives(value: object) -> bool:
    return (_tuple(value, 24) and all(type(item) is DirectiveFact
        and _identifier(item.directive_id) and _text(item.raw_text) and _identifier(item.source_ref)
        and item.scope in ("turn", "session")
        and item.interpretation in ("authoritative", "observed", "unknown") for item in value)
        and len({item.directive_id for item in value}) == len(value))


def valid_snapshot(snapshot: object) -> bool:
    """Validate the immutable admission boundary, never infer or repair missing facts."""
    if type(snapshot) is not DecisionSnapshot:
        return False
    s, c, policy = snapshot, snapshot.context, snapshot.author_policy
    if (not all(_identifier(value) for value in (s.snapshot_id, s.generation_id))
            or any(type(value) is not int or value < 0 for value in (
                s.event_watermark, s.activity_seq, s.input_epoch, s.input_revision))
            or type(s.local_stop) is not bool or type(c) is not GenerationContext
            or not _text(c.user_text) or not _tuple(c.user_inputs, 32) or not c.user_inputs
            or not all(_text(item) for item in c.user_inputs)
            or type(c.output_epoch) is not int or c.output_epoch < 0
            or not _tuple(s.reliable_inputs, 32) or not s.reliable_inputs
            or not all(type(item) is ReliableUserInput and _identifier(item.event_id)
                       and _text(item.text) and item.source in ("text", "asr_final")
                       for item in s.reliable_inputs)
            or tuple(item.text for item in s.reliable_inputs) != c.user_inputs
            or s.reliable_inputs[-1].text != c.user_text
            or len({item.event_id for item in s.reliable_inputs}) != len(s.reliable_inputs)):
        return False
    if (type(policy) is not AuthorPolicy
            or not all(_identifier(value) for value in (policy.policy_revision,
                policy.character_revision, policy.capability_revision))
            or not _tuple(policy.character_facts, 32) or not policy.character_facts
            or not all(_text(value) for value in policy.character_facts)
            or not _tuple(policy.allowed_controls, 32)
            or not all(_effect(item, compiled=False)
                       and item.kind in (EffectKind.POSE, EffectKind.SCENE)
                       for item in policy.allowed_controls)
            or len(set(policy.allowed_controls)) != len(policy.allowed_controls)
            or not all(_directives(value) for value in (
                s.effective_constraints, s.response_obligations, policy.constraints))):
        return False
    if (not all(_tuple(value, 64) and all(_effect(item, compiled=True) for item in value)
                for value in (c.presented_effects, c.accepted_prefix))
            or not _tuple(s.presentation_facts, 64)
            or not all(type(item) is PresentationFact and _effect(item.effect, compiled=True)
                and item.status in ("presented", "partial", "unknown")
                # This runtime has no alignment source. Samples cannot establish words.
                and item.observed_text is None for item in s.presentation_facts)):
        return False
    facts = {item.effect.id: item for item in s.presentation_facts}
    if (len(facts) != len(s.presentation_facts)
            or len({item.id for item in c.accepted_prefix}) != len(c.accepted_prefix)
            or any(item.output_epoch != c.output_epoch or item.activity_seq != s.activity_seq
                   for item in c.accepted_prefix)
            or any(item.id in facts and facts[item.id].effect != item for item in c.accepted_prefix)
            or tuple(item.effect for item in s.presentation_facts if item.status == "presented")
            != c.presented_effects or not _tuple(c.audio_progress, 4096)):
        return False
    latest_audio = {}
    for progress in c.audio_progress:
        if (type(progress) is not AudioProgress or type(progress.status) is not AudioStatus
                or any(type(value) is not int or value < 0 for value in (
                    progress.output_epoch, progress.activity_seq, progress.presentation_seq,
                    progress.sample_rate_hz, progress.rendered_samples))
                or not 8000 <= progress.sample_rate_hz <= 48000
                or progress.rendered_samples > progress.sample_rate_hz * MAX_AUDIO_SECONDS
                or (progress.status in (AudioStatus.RENDERED, AudioStatus.COMPLETED)
                    and progress.rendered_samples == 0)
                or progress.presentation_seq == 0 or not _identifier(progress.effect_id)
                or progress.effect_id not in facts):
            return False
        fact = facts[progress.effect_id]
        if (fact.effect.kind != EffectKind.SPEECH
                or (progress.digest, progress.output_epoch, progress.activity_seq)
                != (fact.effect.digest, fact.effect.output_epoch, fact.effect.activity_seq)):
            return False
        previous = latest_audio.get(progress.effect_id)
        if previous is not None and (previous.status != AudioStatus.RENDERED
                or progress.presentation_seq <= previous.presentation_seq
                or progress.rendered_samples < previous.rendered_samples
                or progress.sample_rate_hz != previous.sample_rate_hz):
            return False
        latest_audio[progress.effect_id] = progress
    for effect_id, progress in latest_audio.items():
        expected = ("presented" if progress.status == AudioStatus.COMPLETED else
                    "partial" if progress.rendered_samples > 0 else "unknown")
        if facts[effect_id].status != expected:
            return False
    if any(item.effect.kind == EffectKind.SPEECH and item.effect.id not in latest_audio
           for item in s.presentation_facts):
        return False
    if (not _tuple(s.referents, 16)
            or not all(type(item) is ControlledReferent and _identifier(item.referent_id)
                and item.referent_id not in ("none", "ambiguous") and _text(item.description, 512)
                and _identifier(item.presentation_effect_id)
                and item.presentation_effect_id in facts for item in s.referents)
            or len({item.referent_id for item in s.referents}) != len(s.referents)):
        return False
    return True


def _usable_observation(snapshot: DecisionSnapshot, observation: object) -> bool:
    if (type(observation) is not InputDecisionObservation
            or observation.status != InputDecisionStatus.OBSERVED
            or observation.snapshot_id != snapshot.snapshot_id
            or observation.snapshot_digest != evidence_digest(snapshot)
            or observation.question_set_revision != INPUT_QUESTION_SET
            or not _identifier(observation.calibration_ref)
            or not _text(observation.model, 160)
            or observation.unresolved_items != () or not _tuple(observation.predicates, 3)
            or len(observation.predicates) != 3):
        return False
    for item in observation.predicates:
        if (type(item) is not PredicateObservation or item.predicate not in INPUT_PREDICATES
                or type(item.value) is not SemanticValue
                or type(item.probability) not in (float, int) or not math.isfinite(item.probability)
                or not 0 <= item.probability <= 1
                or not (item.value == SemanticValue.YES and item.probability >= 0.99
                        or item.value == SemanticValue.NO and item.probability <= 0.01)):
            return False
    if {item.predicate for item in observation.predicates} != set(INPUT_PREDICATES):
        return False
    referent = observation.referent
    if (type(referent) is not ReferentObservation or referent.status not in ("none", "resolved")
            or not _tuple(referent.probabilities, 18)
            or not all(type(item) is ChoiceProbability and _identifier(item.option)
                       and type(item.probability) in (int, float)
                       and math.isfinite(item.probability) and 0 <= item.probability <= 1
                       for item in referent.probabilities)):
        return False
    probabilities = {item.option: item.probability for item in referent.probabilities}
    expected_options = {"none", "ambiguous"} | {item.referent_id for item in snapshot.referents}
    selected = referent.referent_id if referent.status == "resolved" else "none"
    if not _identifier(selected):
        return False
    if (set(probabilities) != expected_options or len(probabilities) != len(referent.probabilities)
            or (referent.status == "none" and referent.referent_id is not None)
            or selected not in probabilities or probabilities[selected] < 0.99
            or not math.isclose(sum(probabilities.values()), 1, abs_tol=0.00001)
            or type(referent.confidence) not in (int, float)
            or not math.isfinite(referent.confidence) or not 0.985 <= referent.confidence <= 1):
        return False
    count = len(probabilities)
    if not math.isclose(referent.confidence,
                        (probabilities[selected] - 1 / count) / (1 - 1 / count), abs_tol=0.0001):
        return False
    if referent.status == "resolved":
        controlled = next(item for item in snapshot.referents if item.referent_id == selected)
        if not any(item.effect.id == controlled.presentation_effect_id and item.status == "presented"
                   for item in snapshot.presentation_facts):
            return False
    return not (next(item.value for item in observation.predicates
                     if item.predicate == "display_request") == SemanticValue.YES
                and referent.status != "resolved")


class ResponseContractProducer:
    def produce(self, context: GenerationContext, candidate: CandidateRange, *,
                snapshot: DecisionSnapshot, observation: InputDecisionObservation | None,
                scope: Literal["stage", "seal"] = "stage") -> ResponseContract | None:
        """Compose trusted facts only. No inference, state change, permits or hidden fallback.

        The owner must recheck current revisions before and after external work. A new
        observation cannot remove an existing directive. Unsupported raw requirements
        remain obligations for full semantic output review, never a guessed permission.
        """
        if (not valid_snapshot(snapshot) or snapshot.local_stop or snapshot.context != context
                or not _usable_observation(snapshot, observation) or scope not in ("stage", "seal")
                or type(candidate) is not CandidateRange or not _identifier(candidate.fixture_id)
                or not _tuple(candidate.effects, 8) or not candidate.effects
                or not all(_effect(item, compiled=False) for item in candidate.effects)):
            return None
        assert observation is not None
        policy = snapshot.author_policy
        directives = policy.constraints + snapshot.effective_constraints + snapshot.response_obligations
        if any(item.interpretation == "unknown" for item in directives):
            return None
        values = {item.predicate: item.value for item in observation.predicates}
        for effect in candidate.effects:
            if (effect.kind == EffectKind.MEDIA
                    or effect.kind == EffectKind.SPEECH and values["speech_restriction"] == SemanticValue.YES
                    or effect.kind in (EffectKind.POSE, EffectKind.SCENE)
                    and effect not in policy.allowed_controls):
                return None
        constraints = tuple(item.raw_text for item in policy.constraints + snapshot.effective_constraints)
        if any(values[name] == SemanticValue.YES for name in ("speech_restriction", "capture_restriction")):
            constraints += (context.user_text,)
        obligations = tuple(item.raw_text for item in snapshot.response_obligations)
        if context.user_text not in obligations:
            obligations += (context.user_text,)
        if len(constraints) > 32 or len(obligations) > 32:
            return None
        binding = {
            "snapshot": asdict(snapshot), "observation": asdict(observation),
            "candidate": asdict(candidate), "effective_constraints": constraints,
            "response_obligations": obligations, "scope": scope,
        }
        digest = hashlib.sha256(canonical_bytes(binding)).hexdigest()
        return ResponseContract(
            "response-" + digest, digest, evidence_digest(snapshot), evidence_digest(context),
            evidence_digest(candidate), policy.policy_revision, constraints, obligations,
            policy.character_facts, policy.allowed_controls, scope, snapshot, observation,
        )
