"""Transport-independent inputs/outputs of generation and review adapters."""
from dataclasses import asdict, dataclass, field
from enum import StrEnum
import json
from typing import Literal

from mira.domain.fixed_photo import FixedPhotoStatus
from mira.domain.story_images import ImageIntent, StoryImageFact, parse_image_proposal_json
from mira.domain.models import AudioProgress, CaptionChunk, Effect, EffectKind
from mira.application.memory_context import ContextPacket
from mira.application.conversation_context import bound_conversation_data
from mira.application.conversation_archive import ConversationRecallPacket
from mira.application.interrupted_intent import RequestContext, request_context_data
from mira.application.character_memory import first_person_dialogue
from mira.application.optional_candidate_diagnostics import SafeOptionalCandidateDiagnostic
from mira.application.dialogue_topics import dialogue_topic_guidance, omit_optional_topics
from mira.domain.story import StoryContextProjection, ReadinessCatalog, valid_story_projection


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
    # Untrusted suggestions only; no effect/grant or state authority.
    story_proposal_json: str | None = field(default=None, repr=False)
    affect_proposal_json: str | None = field(default=None, repr=False)
    caption_chunk: CaptionChunk | None = None
    image_proposal_json: str | None = field(default=None, repr=False)
    image_intent: ImageIntent | None = field(default=None, repr=False)
    # Local diagnostic only; deliberately excluded from candidate_data and model/review inputs.
    optional_hold: SafeOptionalCandidateDiagnostic | None = field(default=None, repr=False)


def candidate_data(candidate: CandidateRange) -> dict[str, object]:
    """Preserve old wire when absent; expose bounded structured proposals as data."""
    if type(candidate) is not CandidateRange:
        raise ValueError("candidate_invalid")
    result = {"effects": tuple(asdict(effect) for effect in candidate.effects),
              "fixture_id": candidate.fixture_id}
    if candidate.caption_chunk is not None:
        result["caption_chunk"] = asdict(candidate.caption_chunk)
    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("candidate_proposal_duplicate")
            value[key] = item
        return value
    for name, raw in (("story_proposal", candidate.story_proposal_json),
                      ("affect_proposal", candidate.affect_proposal_json)):
        if raw is None:
            continue
        if type(raw) is not str or len(raw.encode("utf-8")) > 4096:
            raise ValueError("candidate_proposal_limit")
        def invalid_constant(_value):
            raise ValueError("candidate_proposal_nonfinite")
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
        if type(value) is not dict:
            raise ValueError("candidate_proposal_invalid")
        result[name] = value
    if candidate.image_proposal_json is not None:
        result['image_proposal'] = parse_image_proposal_json(candidate.image_proposal_json).as_dict()
    if candidate.image_intent is not None:
        if type(candidate.image_intent) is not ImageIntent: raise ValueError('image_intent_invalid')
        result['image_intent'] = asdict(candidate.image_intent)
    return result


@dataclass(frozen=True, slots=True)
class GenerationContext:
    user_text: str
    user_inputs: tuple[str, ...]
    presented_effects: tuple[Effect, ...]
    output_epoch: int
    accepted_prefix: tuple[Effect, ...] = ()
    # Partial software rendering is not a claim that the entire speech text was heard.
    audio_progress: tuple[AudioProgress, ...] = ()
    # Explicitly opt-in; not authority, and excluded from raw diagnostics.
    memory_packet: ContextPacket | None = field(default=None, repr=False)
    # Explicit application-owned fictional state, separate from personal memory.
    character_story: StoryContextProjection | None = field(default=None, repr=False)
    character_assets: ReadinessCatalog | None = field(default=None, repr=False)
    # Current bounded accepted request lineage, never a presentation/hearing receipt.
    request_context: RequestContext | None = field(default=None, repr=False)
    # An issued camera transition without a completion may have stopped mid-motion.
    visual_action_uncertain: bool = False
    # Authoritative app modality for this single generation request.
    # None is only for historical fixture contexts; live Actor requests always set it.
    response_mode: Literal["voice", "text_only"] | None = None
    photo_visible: bool = False
    photo_visibility_revision: int = 0
    # Operational read failure is explicit; no recalled text or stale packet survives.
    memory_recall_status: str | None = None
    conversation_recall: ConversationRecallPacket | None = field(default=None, repr=False)
    conversation_recall_status: str | None = None
    story_image_scenes: tuple[str, ...] = ()
    story_images: tuple[StoryImageFact, ...] = ()
    story_image_completions: tuple[StoryImageFact, ...] = ()
    story_image_completion_only: bool = False
    fixed_photo: FixedPhotoStatus = FixedPhotoStatus()
    retired_user_inputs: int = 0


def effect_data(effect: Effect) -> dict[str, object]:
    """Absent chunk metadata preserves the pre-chunking evidence wire exactly."""
    data = asdict(effect)
    if effect.caption_chunk is None:
        data.pop('caption_chunk', None)
    return data


def generation_context_data(context: GenerationContext, *, max_context_bytes: int | None = 48_000) -> dict[str, object]:
    """Canonical transport projection; absent memory preserves legacy wire bytes."""
    if type(context) is not GenerationContext:
        raise TypeError("generation_context_invalid")
    data = asdict(context)
    data.pop("fixed_photo", None)
    data.pop("retired_user_inputs", None)
    if context.retired_user_inputs:
        data["local_history_retention"] = {
            "omitted_user_inputs": context.retired_user_inputs,
            "scope": "recent_retained_exact_facts_only",
            "rule": "Earlier local inputs and presentation details may have expired; never claim complete recall or invent omitted facts.",
        }
    if not context.story_image_scenes: data.pop("story_image_scenes", None)
    if not context.story_images: data.pop("story_images", None)
    if not context.story_image_completions: data.pop("story_image_completions", None)
    if not context.story_image_completion_only: data.pop("story_image_completion_only", None)
    if context.response_mode is None:
        data.pop('response_mode', None)
    data['presented_effects'] = tuple(effect_data(effect) for effect in context.presented_effects)
    data['accepted_prefix'] = tuple(effect_data(effect) for effect in context.accepted_prefix)
    data.pop("memory_packet", None)
    data.pop("character_story", None)
    data.pop("character_assets", None)
    data.pop("request_context", None)
    data.pop("conversation_recall", None)
    # An unavailable read must not resurrect a leftover packet on either wire.
    # Normal Actor failure paths already clear it; this guards direct consumers.
    if context.conversation_recall is not None and context.conversation_recall_status != "unavailable":
        if type(context.conversation_recall) is not ConversationRecallPacket:
            raise ValueError("conversation_recall_invalid")
        data["conversation_recall"] = context.conversation_recall.as_dict()
    if context.conversation_recall_status is None:
        data.pop("conversation_recall_status", None)
    elif context.conversation_recall_status != "unavailable":
        raise ValueError("conversation_recall_status_invalid")
    if context.memory_recall_status is None:
        data.pop("memory_recall_status", None)
    elif context.memory_recall_status != "unavailable":
        raise ValueError("memory_recall_status_invalid")
    if context.request_context is not None:
        data["request_context"] = request_context_data(context.request_context,
            user_text=context.user_text, user_inputs=context.user_inputs, output_epoch=context.output_epoch)
    data.pop("photo_visible", None)
    data.pop("photo_visibility_revision", None)
    if (type(context.photo_visible) is not bool or type(context.photo_visibility_revision) is not int
            or context.photo_visibility_revision < 0):
        raise ValueError('photo_visibility_invalid')
    data.pop("visual_action_uncertain", None)
    if type(context.visual_action_uncertain) is not bool:
        raise ValueError("visual_action_uncertain_invalid")
    if context.memory_packet is not None and context.memory_recall_status != "unavailable":
        # Use the packet's explicit, scope-free trust projection, not dataclass
        # field reflection. `memory_evidence` is omitted for old contexts.
        data["memory_evidence"] = context.memory_packet.as_dict()
    if context.character_story is not None:
        if not valid_story_projection(context.character_story):
            raise ValueError("character_story_invalid")
        data["character_story"] = {
            "projection_id": context.character_story.projection_id,
            **json.loads(context.character_story.context_json),
        }
        data["first_person_dialogue"] = first_person_dialogue(
            user_inputs=context.user_inputs, presented_effects=context.presented_effects,
            story_projection=context.character_story, output_epoch=context.output_epoch,
            memory_evidence=data.get("memory_evidence"), memory_recall_status=context.memory_recall_status,
            conversation_recall=data.get("conversation_recall"),
            conversation_recall_status=context.conversation_recall_status)
        topics = dialogue_topic_guidance(story_projection=context.character_story,
            user_text=context.user_text, user_inputs=context.user_inputs,
            presented_effects=context.presented_effects)
        if topics is not None:
            data["first_person_dialogue"]["optional_topics"] = topics
    if context.character_assets is not None:
        if type(context.character_assets) is not ReadinessCatalog:
            raise ValueError('character_asset_catalog_invalid')
        data['character_assets']=asdict(context.character_assets)
    from mira.application.authored_visual_events import visual_context_projection
    if visual_projection := visual_context_projection(context):
        data['authored_visual_events'] = visual_projection
    # Optional writing resources must yield before the inherited history bound
    # considers omitting any ordinary source row. The original ledger is intact.
    if (max_context_bytes is not None and len(json.dumps(data, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"), allow_nan=False).encode('utf-8')) > max_context_bytes):
        omit_optional_topics(data)
    return data if max_context_bytes is None else bound_conversation_data(data, max_bytes=max_context_bytes)


class ReviewVerdict(StrEnum):
    ALLOW = "allow"
    REJECT = "reject"
    UNKNOWN = "unknown"


class ResponseValidationReason(StrEnum):
    """Closed parser categories suitable for local diagnostics."""

    ANSWER_COVERAGE = "answer_coverage"
    ANSWER_SHAPE = "answer_shape"
    BODY_SIZE = "body_size"
    CHOICE_NOT_MAXIMUM = "choice_not_maximum"
    DUPLICATE_KEY = "duplicate_key"
    INCONSISTENT_CONFIDENCE = "inconsistent_confidence"
    INVALID_UTF8 = "invalid_utf8"
    JSON_DECODE = "json_decode"
    MODEL_MISMATCH = "model_mismatch"
    NONFINITE_NUMBER = "nonfinite_number"
    NUMERIC_OVERFLOW = "numeric_overflow"
    PROBABILITIES = "probabilities"
    RESPONSE_SHAPE = "response_shape"
    UNKNOWN = "unknown"
    USAGE_SHAPE = "usage_shape"


class ResponseWireType(StrEnum):
    ARRAY = "array"
    BOOLEAN = "boolean"
    MISSING = "missing"
    NULL = "null"
    NUMBER = "number"
    OBJECT = "object"
    OTHER = "other"
    STRING = "string"


class ResponseChoice(StrEnum):
    ALLOW = "allow"
    REJECT = "reject"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SafeResponseAnswerFacts:
    """Per-known-question facts only; suffix and categorical values are allowlisted."""

    question_suffix: str
    answer_wire_type: ResponseWireType
    answer_reason: ResponseValidationReason | None
    choice: ResponseChoice | None
    answer_field_count: int | None
    unexpected_answer_field_count: int | None
    expected_probability_count: int
    probability_field_count: int | None
    unexpected_probability_field_count: int | None
    valid_probability_count: int
    confidence: float | None
    selected_probability: float | None
    maximum_probability: float | None
    probability_sum: float | None
    selected_is_maximum: bool | None
    confidence_consistent: bool | None
    # Set only for the v3 completed-claim NOUL applicability fact. Kept at the end
    # with a default so existing choice-only producers and serialized records survive.
    noul_probability: float | None = None
    # Emitted only under reported-confidence-v2; the raw mismatch remains observable.
    confidence_mismatch_warning: bool | None = None


@dataclass(frozen=True, slots=True)
class SafeResponseValidation:
    """Small allowlisted structure summary; never contains provider-owned strings."""

    parser_reason: ResponseValidationReason
    response_wire_type: ResponseWireType
    response_bytes: int | None
    response_sha256: str | None
    expected_answer_count: int | None
    answer_count: int | None
    missing_answer_count: int | None
    unexpected_answer_count: int | None
    invalid_answer_count: int | None
    invalid_probability_count: int | None
    nonfinite_numeric_count: int | None
    oversized_integer_count: int | None
    selected_probability_range: tuple[float, float] | None = None
    confidence_range: tuple[float, float] | None = None
    probability_sum_range: tuple[float, float] | None = None
    answer_facts: tuple[SafeResponseAnswerFacts, ...] = ()
    # Omitted by the serializer for legacy strict records.
    choice_wire_policy_version: str | None = None


@dataclass(frozen=True, slots=True)
class ReportedConfidenceWarning:
    """Bounded numeric provenance for an accepted v2 input referent mismatch."""

    choice_wire_policy_version: str
    maximum_probability: float
    confidence: float
    probability_sum: float


class CharacterSemanticValue(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CharacterSemanticEvidence:
    """Optional simple observations; UNKNOWN never becomes story or action consent."""
    context_digest: str
    candidate_digest: str
    relevance: CharacterSemanticValue = CharacterSemanticValue.UNKNOWN
    willingness: CharacterSemanticValue = CharacterSemanticValue.UNKNOWN
    refusal: CharacterSemanticValue = CharacterSemanticValue.UNKNOWN
    affect_supported: CharacterSemanticValue = CharacterSemanticValue.UNKNOWN
    specific_notice: CharacterSemanticValue = CharacterSemanticValue.UNKNOWN


@dataclass(frozen=True, slots=True)
class ReviewObservation:
    verdict: ReviewVerdict
    reason_code: str
    response_diagnostics: SafeResponseValidation | None = field(default=None, compare=False, repr=False)
    character_evidence: CharacterSemanticEvidence | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    sequence: int
    session_id: str
    kind: str
    state_revision: int
    output_epoch: int
    occurred_at: str
