"""Application-owned immutable evidence; semantic observations never issue permits."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field, fields, is_dataclass, replace
from enum import StrEnum
from typing import Literal

from mira.application.contracts import (
    CandidateRange, EffectProposal, GenerationContext, ReportedConfidenceWarning,
    generation_context_data, candidate_data, effect_data,
)
from mira.application.memory_context import ContextPacket, valid_context_packet
from mira.application.choice_confidence import choice_confidence_consistent
from mira.application.choice_confidence import choice_probability_sum_compatible
from mira.application.choice_wire_policy import (
    CHOICE_WIRE_POLICY_LEGACY_STRICT, CHOICE_WIRE_POLICY_REPORTED_V2,
    is_supported_choice_wire_policy,
)
from mira.application.decision_policy import (
    DecisionPolicyRef, USER_DEVELOPMENT_0_6_V1, USER_DEVELOPMENT_0_6_V2,
)
from mira.domain.story_images import ImageIntent
from mira.domain.models import AudioProgress, AudioStatus, Effect, EffectKind
from mira.domain.transitions import MAX_AUDIO_SECONDS
from mira.domain.story import StoryContextProjection, valid_story_projection
from mira.application.character_controls import CHARACTER_POSES
from mira.application.authored_visual_events import event_available
from mira.domain.story import CapabilityState, ReadinessCatalog

INPUT_QUESTION_SET = "mira-input-v1"
INPUT_PREDICATES = ("speech_restriction", "capture_restriction", "display_request")
INPUT_QUESTION_SET_V2 = "mira-input-v2"
INPUT_QUESTION_SET_AUTHORED = "mira-input-authored-objects-v1"
INPUT_PREDICATES_V2 = INPUT_PREDICATES + ("referent_required",)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def decision_snapshot_data(snapshot: DecisionSnapshot, *, max_context_bytes: int = 48_000) -> dict[str, object]:
    """Canonical review projection with one explicit memory evidence field."""
    if type(snapshot) is not DecisionSnapshot:
        raise TypeError("decision_snapshot_invalid")
    data = asdict(snapshot)
    data["context"] = generation_context_data(snapshot.context, max_context_bytes=max_context_bytes)
    data['presentation_facts'] = tuple({**asdict(fact), 'effect': effect_data(fact.effect)}
                                       for fact in snapshot.presentation_facts)
    data['referents'] = tuple(referent_data(item) for item in snapshot.referents)
    if "conversation_history" in data["context"]:
        keep = {item["id"] for item in data["context"]["presented_effects"]}
        keep.update(item["effect_id"] for item in data["context"]["audio_progress"])
        keep.update(item.presentation_effect_id for item in snapshot.referents)
        all_facts = data["presentation_facts"]
        data["presentation_facts"] = tuple(item for item in all_facts if item["effect"]["id"] in keep)
        data["omitted_presentation_facts"] = len(all_facts) - len(data["presentation_facts"])
        # All reliable input text remains here for permission decisions. Omitting a
        # natural-language restriction is not permission to perform an action.
    return data


def _evidence_data(value: object) -> object:
    """Recursively preserve legacy dataclass JSON while projecting packets safely."""
    if type(value) is Effect:
        return effect_data(value)
    if type(value) is GenerationContext:
        return generation_context_data(value)
    if type(value) is CandidateRange:
        return candidate_data(value)
    if type(value) is ContextPacket:
        return value.as_dict()
    if type(value) is DecisionSnapshot:
        return decision_snapshot_data(value)
    if type(value) is ControlledReferent:
        return referent_data(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _evidence_data(getattr(value, item.name)) for item in fields(value)}
    if type(value) is tuple:
        return [_evidence_data(item) for item in value]
    if type(value) is list:
        return [_evidence_data(item) for item in value]
    if type(value) is dict:
        return {key: _evidence_data(item) for key, item in value.items()}
    return value


def evidence_digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(_evidence_data(value))).hexdigest()


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
    presentation_effect_id: str | None
    # A shipped authored object can be requested before its first presentation.
    # This field never claims exposure; legacy presented-only objects omit it.
    authored_capability_id: str | None = None


def referent_data(item: ControlledReferent) -> dict:
    data = asdict(item)
    if item.authored_capability_id is None:
        data.pop('authored_capability_id', None)
    return data


def authored_referent_ready(context: GenerationContext, item: ControlledReferent) -> bool:
    return (item.referent_id == 'authored.trip_photo'
        and item.authored_capability_id == 'mira.media.trip_photo'
        and item.presentation_effect_id is None
        and type(context.character_assets) is ReadinessCatalog
        and context.character_assets.state_for('mira.media.trip_photo') is CapabilityState.READY)


def referent_has_evidence(snapshot: DecisionSnapshot, item: ControlledReferent, *,
                         allow_authored: bool = False) -> bool:
    if item.authored_capability_id is not None:
        return allow_authored and authored_referent_ready(snapshot.context, item)
    return any(fact.effect.id == item.presentation_effect_id and fact.status == 'presented'
               for fact in snapshot.presentation_facts)


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
    decision_policy_ref: DecisionPolicyRef | None = None
    request_digest: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    unresolved_items: tuple[str, ...] = field(default=(), repr=False)
    choice_wire_policy_version: str = CHOICE_WIRE_POLICY_LEGACY_STRICT


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


def character_author_policy(projection: StoryContextProjection | None,
                            base: AuthorPolicy | None = None, *,
                            readiness: ReadinessCatalog | None = None) -> AuthorPolicy:
    """Use the same selected authored fiction for generation and semantic review.

    This declares fixed authored control names but grants no execution permission.
    Asset readiness, semantic review and presentation remain separate. Fiction, planned nodes and internal affect
    never establish physical action, user facts or actually presented expressions.
    """
    policy = base if base is not None else mira26_author_policy()
    if readiness is not None:
        additions = tuple(effect for effect in (
            EffectProposal(EffectKind.POSE, 'camera_raise'),
            EffectProposal(EffectKind.MEDIA, 'trip_photo')) if event_available(effect, readiness))
        if additions:
            policy = replace(policy, allowed_controls=tuple(dict.fromkeys((*policy.allowed_controls, *additions))),
                character_facts=(*policy.character_facts,
                    "camera_raise仅把手中相机举至胸前；trip_photo是以固定原创插画资产呈现的角色世界灯塔照片，非现实拍摄或用户照片。技术来源不必在普通角色对话中复述；核准往事可用第一人称谈，直接追问现实或来源时须据实区分。资产与话语均不证明已经显示，显示须有匹配回执。"))
    if projection is None:
        return policy
    if not valid_story_projection(projection):
        raise ValueError("character_story_invalid")
    facts = tuple(dict.fromkeys((*policy.character_facts,
        *(text for _identifier, text in projection.canon_text))))
    if len(facts) > 32 or any(not isinstance(text, str) or not text.strip()
                              or len(text) > 4096 for text in facts):
        raise ValueError("character_story_limit")
    from mira.domain.xiahe_chapter import CHAPTER_CAPABILITIES
    from mira.domain.xiahe_chapter import CHAPTER_ASSETS, CHAPTER_REVISION
    chapter_controls=tuple(EffectProposal(EffectKind.SCENE,value) for value in CHAPTER_CAPABILITIES
        if readiness is not None and readiness.state_for(CHAPTER_CAPABILITIES[value]).value == "ready"
        and readiness.get(CHAPTER_CAPABILITIES[value]).asset_revision == CHAPTER_REVISION
        and CHAPTER_ASSETS[value] in readiness.get(CHAPTER_CAPABILITIES[value]).verified_assets)
    controls=tuple(dict.fromkeys((*policy.allowed_controls,*chapter_controls,
        *(EffectProposal(EffectKind.POSE,value) for value in CHARACTER_POSES))))
    return replace(policy, policy_revision="mira-story-author-v1",
        character_revision="storycanon-" + hashlib.sha256(
            canonical_bytes(facts)).hexdigest()[:24], character_facts=facts,
        allowed_controls=controls,capability_revision="mira-character-controls-v1")


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
            or not _text(c.user_text, 8_192) or not _tuple(c.user_inputs, 1000) or not c.user_inputs
            or not all(_text(item, 8_192) for item in c.user_inputs)
            or (c.memory_packet is not None
                and not valid_context_packet(c.memory_packet, request_text=c.user_text))
            or (c.character_story is not None and not valid_story_projection(c.character_story))
            or type(c.output_epoch) is not int or c.output_epoch < 0
            or not _tuple(s.reliable_inputs, 1000) or not s.reliable_inputs
            or not all(type(item) is ReliableUserInput and _identifier(item.event_id)
                       and _text(item.text, 8_192) and item.source in ("text", "asr_final")
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
                       and (item.kind in (EffectKind.POSE, EffectKind.SCENE)
                            or item.kind is EffectKind.MEDIA and item.value == "trip_photo")
                       for item in policy.allowed_controls)
            or len(set(policy.allowed_controls)) != len(policy.allowed_controls)
            or not all(_directives(value) for value in (
                s.effective_constraints, s.response_obligations, policy.constraints))):
        return False
    if (not all(_tuple(value, 1000) and all(_effect(item, compiled=True) for item in value)
                for value in (c.presented_effects, c.accepted_prefix))
            or not _tuple(s.presentation_facts, 1000)
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
                and ((item.authored_capability_id is None
                      and _identifier(item.presentation_effect_id)
                      and item.presentation_effect_id in facts)
                     or authored_referent_ready(c, item)) for item in s.referents)
            or len({item.referent_id for item in s.referents}) != len(s.referents)):
        return False
    return True


def _usable_observation(snapshot: DecisionSnapshot, observation: object, *,
                        speech_only: bool = False) -> bool:
    """Validate original evidence; event contracts additionally need complete semantics.

    Speech consumes only its own NO predicate after the same wire checks. It never
    replaces unknown scores, resolves an object, or makes an event contract usable.
    """
    # A user-selected policy reference is provenance, not calibration. It is a
    # separate, allow-listed admission path with its own exact thresholds below.
    selected_development_policy = (
        {DecisionPolicyRef.USER_DEVELOPMENT_0_6_V1: USER_DEVELOPMENT_0_6_V1,
         DecisionPolicyRef.USER_DEVELOPMENT_0_6_V2: USER_DEVELOPMENT_0_6_V2}.get(
             observation.decision_policy_ref)
        if type(observation) is InputDecisionObservation
        and type(observation.decision_policy_ref) is DecisionPolicyRef else None
    )
    development_policy = selected_development_policy is not None
    calibration_admission = (type(observation) is InputDecisionObservation
        and observation.decision_policy_ref is None
        and _identifier(observation.calibration_ref))
    if type(observation) is not InputDecisionObservation:
        return False
    v2 = observation.question_set_revision in (INPUT_QUESTION_SET_V2, INPUT_QUESTION_SET_AUTHORED)
    allow_authored = observation.question_set_revision == INPUT_QUESTION_SET_AUTHORED
    predicates = INPUT_PREDICATES_V2 if v2 else INPUT_PREDICATES
    if (observation.question_set_revision not in (INPUT_QUESTION_SET, INPUT_QUESTION_SET_V2, INPUT_QUESTION_SET_AUTHORED)
            or not is_supported_choice_wire_policy(observation.choice_wire_policy_version)
            or (observation.status != InputDecisionStatus.OBSERVED
                and not (speech_only and observation.status == InputDecisionStatus.UNKNOWN
                         and observation.reason_code == "jev_input_semantic_unknown"))
            or observation.snapshot_id != snapshot.snapshot_id
            or observation.snapshot_digest != evidence_digest(snapshot)
            or not (development_policy and observation.calibration_ref is None
                    or calibration_admission)
            or not _text(observation.model, 160)
            or not _tuple(observation.unresolved_items, 1)
            or not _tuple(observation.predicates, len(predicates))
            or len(observation.predicates) != len(predicates)):
        return False
    for item in observation.predicates:
        yes_min = (selected_development_policy.noul_yes_probability_min
                   if selected_development_policy else 0.99)
        no_max = (selected_development_policy.noul_no_probability_max
                  if selected_development_policy else 0.01)
        if (type(item) is not PredicateObservation or item.predicate not in predicates
                or type(item.value) is not SemanticValue
                or type(item.probability) not in (float, int) or not math.isfinite(item.probability)
                or not 0 <= item.probability <= 1
                or not (item.value == SemanticValue.YES and item.probability >= yes_min
                        or item.value == SemanticValue.NO and item.probability <= no_max
                        or speech_only and item.predicate != "speech_restriction"
                        and item.value == SemanticValue.UNKNOWN
                        and no_max < item.probability < yes_min)):
            return False
    if {item.predicate for item in observation.predicates} != set(predicates):
        return False
    values = {item.predicate: item.value for item in observation.predicates}
    referent = observation.referent
    unresolved_referent = (type(referent) is ReferentObservation
                           and referent.status in ("ambiguous", "unknown"))
    if (type(referent) is not ReferentObservation
            or referent.status not in (("none", "resolved", "ambiguous", "unknown")
                                       if v2 or speech_only else ("none", "resolved"))
            or not _tuple(referent.probabilities, 18)
            or not all(type(item) is ChoiceProbability and _identifier(item.option)
                       and type(item.probability) in (int, float)
                       and math.isfinite(item.probability) and 0 <= item.probability <= 1
                       for item in referent.probabilities)):
        return False
    probabilities = {item.option: item.probability for item in referent.probabilities}
    expected_options = {"none", "ambiguous"} | {item.referent_id for item in snapshot.referents}
    selected = (referent.referent_id if referent.status == "resolved" else
                "none" if referent.status == "none" else
                "ambiguous" if referent.status == "ambiguous" else None)
    referent_probability_min = (selected_development_policy.referent_probability_min
                                if selected_development_policy else 0.99)
    referent_confidence_min = (selected_development_policy.referent_confidence_min
                               if selected_development_policy else 0.985)
    if selected is not None and not _identifier(selected):
        return False
    sum_is_valid = (choice_probability_sum_compatible(probabilities)
                    if observation.choice_wire_policy_version == CHOICE_WIRE_POLICY_REPORTED_V2
                    else math.isclose(sum(probabilities.values()), 1, abs_tol=0.00001))
    if (set(probabilities) != expected_options or len(probabilities) != len(referent.probabilities)
            or (referent.status == "none" and referent.referent_id is not None)
            or (referent.status in ("ambiguous", "unknown") and referent.referent_id is not None)
            or (referent.status == "resolved" and selected not in probabilities)
            or (selected is not None and (selected not in probabilities
                                          or probabilities[selected] < referent_probability_min
                                          or probabilities[selected] != max(probabilities.values())))
            or not sum_is_valid
            or type(referent.confidence) not in (int, float)
            or not math.isfinite(referent.confidence)
            or not 0 <= referent.confidence <= 1
            or (referent.status != "unknown"
                and referent.confidence < referent_confidence_min)):
        return False
    if (observation.choice_wire_policy_version == CHOICE_WIRE_POLICY_LEGACY_STRICT
            and not choice_confidence_consistent(probabilities, referent.confidence)):
        return False
    if speech_only:
        # Check that the semantic status still accurately describes the raw
        # evidence, without requiring unrelated event judgments to be complete.
        if (referent.status == "unknown"
                and max(probabilities.values()) >= referent_probability_min
                and referent.confidence >= referent_confidence_min):
            return False
        presented = referent.status == "none" or any(
            controlled.referent_id == selected
            and referent_has_evidence(snapshot, controlled, allow_authored=allow_authored)
            for controlled in snapshot.referents)
        nonblocking = (v2 and values["referent_required"] == SemanticValue.NO
                       and values["display_request"] == SemanticValue.NO)
        identity_complete = (
            (referent.status in ("none", "resolved") and presented)
            if not v2 else
            ((referent.status in ("none", "resolved") and presented) or unresolved_referent)
            if nonblocking else referent.status == "resolved" and presented
        )
        complete = all(value != SemanticValue.UNKNOWN for value in values.values()) and identity_complete
        if complete:
            expected_status = InputDecisionStatus.OBSERVED
            expected_unresolved = ("referent_identity",) if nonblocking and unresolved_referent else ()
            expected_reason = (
                "jev_input_user_development_0_6_" + selected_development_policy.reference.value.rsplit("-", 1)[-1]
                + "_observed" if selected_development_policy else "jev_input_observed")
        else:
            expected_status = InputDecisionStatus.UNKNOWN
            expected_unresolved = (snapshot.context.user_text,)
            expected_reason = "jev_input_semantic_unknown"
        return (values["speech_restriction"] == SemanticValue.NO
                and observation.status == expected_status
                and observation.reason_code == expected_reason
                and observation.unresolved_items == expected_unresolved)
    if referent.status == "resolved":
        controlled = next(item for item in snapshot.referents if item.referent_id == selected)
        if not referent_has_evidence(snapshot, controlled, allow_authored=allow_authored):
            return False
    display_request = values["display_request"]
    if (v2 and values["referent_required"] == SemanticValue.YES
            and referent.status != "resolved"):
        return False
    if unresolved_referent:
        if (not v2 or values["referent_required"] != SemanticValue.NO
                or display_request != SemanticValue.NO
                or observation.unresolved_items != ("referent_identity",)):
            return False
    elif observation.unresolved_items != ():
        return False
    return not (display_request == SemanticValue.YES and referent.status != "resolved")


def speech_permission_allowed(snapshot: object, candidate: object, observation: object) -> bool:
    """Validate speech evidence only; the Actor still owns current grants and voice IO.

    The input question asks about a *new* restriction. DirectiveFact has no typed
    speech applicability, so a NO cannot clear any retained author/user directive
    or obligation. Such raw evidence stays closed until explicitly resolved by its
    owner. This helper cannot admit controls, capture, media or story proposals.
    """
    if (not valid_snapshot(snapshot) or snapshot.local_stop
            or snapshot.author_policy.constraints or snapshot.effective_constraints
            or snapshot.response_obligations
            or type(candidate) is not CandidateRange or not _identifier(candidate.fixture_id)
            or not _tuple(candidate.effects, 8) or not candidate.effects
            or not all(_effect(item, compiled=False) and item.kind == EffectKind.SPEECH
                       for item in candidate.effects)
            or candidate.story_proposal_json is not None
            or candidate.affect_proposal_json is not None
            or type(observation) is not InputDecisionObservation
            or type(observation.status) is not InputDecisionStatus
            or not _text(observation.model, 160)
            or re.fullmatch(r"jev-\d+\.\d+\.\d+", observation.model) is None
            or any(type(value) is not int or not 0 <= value <= 64_000 for value in
                   (observation.input_tokens, observation.output_tokens))):
        return False
    try:
        candidate_data(candidate)
        binding = hashlib.sha256(canonical_bytes({
            "state": decision_snapshot_data(snapshot), "model": observation.model,
            "question_set": observation.question_set_revision,
        })).hexdigest()
        if observation.request_digest != binding:
            return False
        return _usable_observation(snapshot, observation, speech_only=True)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        return False


class ResponseContractProducer:
    def produce(self, context: GenerationContext, candidate: CandidateRange, *,
                snapshot: DecisionSnapshot, observation: InputDecisionObservation | None,
                scope: Literal["stage", "seal"] = "stage",
                optional_image_only: bool = False) -> ResponseContract | None:
        """Compose trusted facts only. No inference, state change, permits or hidden fallback.

        The owner must recheck current revisions before and after external work. A new
        observation cannot remove an existing directive. Unsupported raw requirements
        remain obligations for full semantic output review, never a guessed permission.
        """
        image_only = (optional_image_only is True and scope == "stage"
            and type(candidate) is CandidateRange and candidate.effects == ()
            and type(candidate.image_intent) is ImageIntent and type(context) is GenerationContext
            and valid_story_projection(context.character_story)
            and all(value is None for value in (candidate.story_proposal_json,candidate.affect_proposal_json,
                candidate.image_proposal_json,candidate.caption_chunk)))
        if (not valid_snapshot(snapshot) or snapshot.local_stop or snapshot.context != context
                or not _usable_observation(snapshot, observation) or scope not in ("stage", "seal")
                or type(candidate) is not CandidateRange or not _identifier(candidate.fixture_id)
                or not _tuple(candidate.effects, 8) or not candidate.effects and not image_only
                or not all(_effect(item, compiled=False) for item in candidate.effects)):
            return None
        if context.character_story is None and any(value is not None for value in (
                candidate.story_proposal_json, candidate.affect_proposal_json)):
            return None
        try:
            candidate_data(candidate)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return None
        assert observation is not None
        policy = snapshot.author_policy
        directives = policy.constraints + snapshot.effective_constraints + snapshot.response_obligations
        if any(item.interpretation == "unknown" for item in directives):
            return None
        values = {item.predicate: item.value for item in observation.predicates}
        for effect in candidate.effects:
            if (not event_available(effect, context.character_assets)
                    or effect.kind == EffectKind.SPEECH and values["speech_restriction"] == SemanticValue.YES
                    or effect.kind in (EffectKind.POSE, EffectKind.SCENE, EffectKind.MEDIA)
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
            "candidate": candidate_data(candidate), "effective_constraints": constraints,
            "response_obligations": obligations, "scope": scope,
        }
        digest = hashlib.sha256(canonical_bytes(binding)).hexdigest()
        return ResponseContract(
            "response-" + digest, digest, evidence_digest(snapshot), evidence_digest(context),
            evidence_digest(candidate), policy.policy_revision, constraints, obligations,
            policy.character_facts, policy.allowed_controls, scope, snapshot, observation,
            observation.unresolved_items,
        )
