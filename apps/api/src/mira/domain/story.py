"""Typed, deterministic story/affect reducer for MIRA's bounded rain invitation.

The module is deliberately free of provider, HTTP, filesystem, and SQLite imports.
Raw dialogue is never an input to this reducer: callers provide fixed labels and
stable IDs from trusted application boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import json
from typing import Any

from mira.domain.story_memory import first_person_story_memory
from mira.domain.xiahe_chapter import (ChapterState, ChapterStage, ChapterInputAct, CHAPTER_SCENES, CHAPTER_SOURCE_HASH,
    CHAPTER_CAPABILITIES, chapter_projection, chapter_is_dormant, cancel_chapter, parse_input_act)


def _bounded_text(value: object, name: str, max_length: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > max_length or (not allow_empty and not value):
        raise ValueError(f"{name} must be a bounded string")
    return value


def _revision(value: object, name: str, *, allow_zero: bool = False) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1):
        raise ValueError(f"{name} must be an integer revision/epoch")
    return value


def _exact_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


class StoryNode(StrEnum):
    CAFE_CHAT = "cafe_chat"
    AWAIT_RAIN_CHOICE = "await_rain_choice"
    RAINCOAT_PENDING = "raincoat_pending"
    RAIN_VIEW = "rain_view"


class OfferStatus(StrEnum):
    NONE = "none"
    PROPOSED = "proposed"
    PRESENTED = "presented"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    UNKNOWN = "unknown"
    SUSPENDED = "suspended"
    CLOSED_CAPABILITY_UNAVAILABLE = "closed_capability_unavailable"


class Will(StrEnum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


class Relevance(StrEnum):
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"
    UNKNOWN = "unknown"


class ProposalSignal(StrEnum):
    OFFER_RAIN = "offer_rain"
    ACCEPT_RAINCOAT = "accept_raincoat"
    CHAT = "chat"
    LOOK_AT_RAIN = "look_at_rain"
    RECOGNIZE_XIAHE = "recognize_xiahe"
    RECALL_OLD_FRIEND = "recall_old_friend"
    RECALL_PHOTO_PROMISE = "recall_photo_promise"
    OFFER_PHOTO_GIFT = "offer_photo_gift"
    ACCEPT_PHOTO_GIFT = "accept_photo_gift"
    DECLINE_PHOTO_GIFT = "decline_photo_gift"
    EXIT_XIAHE_ROLE = "exit_xiahe_role"


class CapabilityState(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ReceiptKind(StrEnum):
    OFFER_PRESENTED = "complete_offer_cue_presentation"
    WARDROBE_COMPLETED = "trusted_current_wardrobe_completion"
    SCENE_COMPLETED = "trusted_current_scene_completion"


class ReceiptComponent(StrEnum):
    SUBTITLE = "subtitle"
    SPEECH = "speech"
    WARDROBE = "wardrobe"
    SCENE = "scene"


class EvidenceLabel(StrEnum):
    SOFTWARE = "software"
    CLIENT_REPORT = "client_report"
    FICTION = "fiction"


class Affect(StrEnum):
    NORMAL = "normal"
    GUARDED = "guarded"
    HAPPY = "happy"
    SHY = "shy"


class AffectSignal(StrEnum):
    PLEASANT_SHARED_ATTENTION = "pleasant_shared_attention"
    COMFORTABLE_HUMOR = "comfortable_humor"
    PERSONAL_ATTENTION = "personal_attention"
    BOUNDARY_PRESSURE = "boundary_pressure"
    REPAIR = "repair"
    NEUTRAL = "neutral"
    UNCERTAIN = "uncertain"


class ResultCode(StrEnum):
    PROPOSAL_STAGED = "proposal_staged"
    CHAT_HELD = "chat_held"
    CHOICE_NO = "choice_no"
    CHOICE_UNKNOWN = "choice_unknown"
    ASSET_UNKNOWN = "asset_unknown"
    ASSET_UNAVAILABLE = "asset_unavailable"
    RECEIPT_ACCEPTED = "receipt_accepted"
    DUPLICATE = "duplicate"
    STOPPED = "stopped"
    STALE = "stale"
    REJECTED = "rejected"


class Fallback(StrEnum):
    NONE = "none"
    CALM_CLARIFICATION = "calm_clarification"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    ORDINARY_CHAT = "ordinary_chat"


_CANON_RELEASE_OVERRIDES = {
    "canon.first_trip": "story.photo_detail",
    "canon.photo_promise": "story.waiting_reason",
    "canon.waiting": "story.waiting_reason",
    "canon.personal_stakes": "story.imperfect_print",
    "canon.star_clip": "story.star_clip",
    "canon.raincoat": "story.amber_raincoat",
}


@dataclass(frozen=True, slots=True)
class CanonEntry:
    entry_id: str
    status: str
    source_status: str
    text: str
    category: str
    source: str = "authored_backstory"
    author_created: bool = True
    approval_basis: str = "inherited_source"
    source_refs: tuple[str, ...] = ()
    source_version: int = 1
    disclosure_level: str = "public"
    release_event_id: str | None = None
    is_user_fact: bool = False
    is_shared_experience: bool = False
    first_person_text: str | None = None
    memory_temporal_type: str = "source_quote"

    def __post_init__(self) -> None:
        _bounded_text(self.entry_id, "canon entry ID", 128)
        _bounded_text(self.text, "canon text", 4000)
        _bounded_text(self.category, "canon category", 80)
        if self.first_person_text is not None:
            _bounded_text(self.first_person_text, "first-person canon", 4000)
        if self.memory_temporal_type not in {"source_quote", "character_identity", "authored_trait",
                "authored_past", "current_scene", "current_intention", "current_concern"}:
            raise ValueError("invalid first-person temporal type")
        _exact_bool(self.author_created, "author_created")
        _exact_bool(self.is_user_fact, "is_user_fact")
        _exact_bool(self.is_shared_experience, "is_shared_experience")
        _revision(self.source_version, "canon source revision")
        if len(self.source_refs) > 16 or any(not isinstance(ref, str) or not ref or len(ref) > 128 for ref in self.source_refs):
            raise ValueError("canon source refs must be bounded strings")
        if self.is_user_fact or self.is_shared_experience:
            raise ValueError("fiction canon cannot become a user fact or shared event")
        if self.status not in {"inherited_canonical", "current_brief_constraint", "approved_author_canon"}:
            raise ValueError("only explicitly selected canon/brief constraints may be projected")
        if not self.author_created or self.source != "authored_backstory":
            raise ValueError("projected canon must retain authored-fiction provenance")
        if self.status == "approved_author_canon" and (self.source_status != "author_draft"
                or self.approval_basis != "explicit_composition_selection"):
            raise ValueError("author-draft canon requires explicit composition approval provenance")
        if self.disclosure_level not in {"public", "private_until_invited"}:
            raise ValueError("canon disclosure level is not allowlisted")
        if self.release_event_id is not None:
            _bounded_text(self.release_event_id, "canon release event", 128)


def awaited_friend_claim_available(chapter: ChapterState, entries: tuple[CanonEntry, ...]) -> bool:
    """Only the selected, unchanged authored waiting fact resolves this fiction role.

    The digest binds canon.waiting v3 text plus first-person text, not user data.
    A canon edit needs an explicit review/update of this narrow role binding.
    """
    if (type(chapter) is not ChapterState or chapter.source_hash != CHAPTER_SOURCE_HASH
            or chapter.stage is not ChapterStage.STRANGER or chapter.role_active
            or chapter.suspended or chapter.pending is not None or chapter.milestones
            or type(entries) is not tuple or any(type(e) is not CanonEntry for e in entries)):
        return False
    waiting = tuple(e for e in entries if e.entry_id == 'canon.waiting')
    if len(waiting) != 1:
        return False
    entry = waiting[0]
    if (entry.status != 'approved_author_canon' or entry.source_status != 'author_draft'
            or entry.approval_basis != 'explicit_composition_selection'
            or entry.source != 'authored_backstory' or entry.author_created is not True
            or entry.source_version != 3 or entry.is_user_fact or entry.is_shared_experience):
        return False
    source = json.dumps({'text': entry.text, 'first_person_text': entry.first_person_text},
                        ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(source.encode()).hexdigest() == '87b8182b9f2d82ff60542bb7cfe532c33de6757b0de1011aec7c3d524fc967e7'


@dataclass(frozen=True, slots=True)
class CanonRevision:
    story_id: str
    revision: int
    entries: tuple[CanonEntry, ...]
    content_hash: str
    proposal_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _bounded_text(self.story_id, "canon story ID", 128)
        _revision(self.revision, "canon revision")
        if not _is_sha256(self.content_hash):
            raise ValueError("canon revision requires a content SHA-256")
        if not isinstance(self.entries, tuple) or not isinstance(self.proposal_ids, tuple):
            raise ValueError("canon rows must be immutable tuples")
        if self.revision < 1 or not self.story_id:
            raise ValueError("canon revision must be positive and story-bound")
        ids = [entry.entry_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("canon entry IDs must be unique")
        if any(entry.status == "author_draft" for entry in self.entries):
            raise ValueError("author draft proposals may not be promoted implicitly")


@dataclass(frozen=True, slots=True)
class StoryGraph:
    story_id: str
    graph_id: str
    revision: int
    nodes: tuple[StoryNode, ...]
    initial_node: StoryNode
    content_hash: str

    def __post_init__(self) -> None:
        _bounded_text(self.story_id, "graph story ID", 128)
        _bounded_text(self.graph_id, "graph ID", 128)
        _revision(self.revision, "graph revision")
        if not isinstance(self.nodes, tuple) or not isinstance(self.initial_node, StoryNode):
            raise ValueError("graph nodes must be an immutable typed tuple")
        required = tuple(StoryNode)
        if self.nodes != required or self.initial_node is not StoryNode.CAFE_CHAT:
            raise ValueError("the approved runtime graph must be the bounded four-node loop")
        if len(self.content_hash) != 64:
            raise ValueError("graph content hash must be SHA-256")


@dataclass(frozen=True, slots=True)
class StoryDefinition:
    graph: StoryGraph
    canon: CanonRevision

    def __post_init__(self) -> None:
        if not isinstance(self.graph, StoryGraph) or not isinstance(self.canon, CanonRevision):
            raise ValueError("story definition requires typed graph and canon revisions")
        if self.graph.story_id != self.canon.story_id:
            raise ValueError("graph and canon must name the same story")


def _canon_entry(item: dict[str, Any], seed_version: int) -> CanonEntry:
    source_status = _bounded_text(item.get("status"), "canon source status", 64)
    provenance = item.get("provenance")
    disclosure = item.get("disclosure")
    if not isinstance(provenance, dict) or not isinstance(disclosure, dict):
        raise ValueError("canon provenance and disclosure must be explicit objects")
    raw_refs = provenance.get("source_refs")
    if not isinstance(raw_refs, (list, tuple)) or len(raw_refs) > 16:
        raise ValueError("canon provenance source refs are malformed")
    source_refs = tuple(_bounded_text(x, "canon source ref", 128) for x in raw_refs)
    source_revision = _revision(provenance.get("source_version", seed_version), "canon source revision")
    release_event = disclosure.get("release_event_id") or _CANON_RELEASE_OVERRIDES.get(item["id"])
    if release_event is not None and release_event not in _CANON_RELEASE_OVERRIDES.values():
        raise ValueError("canon disclosure event is not an approved story-node event")
    status = "approved_author_canon" if source_status == "author_draft" else source_status
    return CanonEntry(
        entry_id=_bounded_text(item.get("id"), "canon entry ID", 128),
        status=status, source_status=source_status,
        text=_bounded_text(item.get("text"), "canon text", 4000),
        category=_bounded_text(item.get("category", "uncategorized"), "canon category", 80),
        source=_bounded_text(item.get("source"), "canon source", 80),
        author_created=_exact_bool(item.get("author_created"), "author_created"),
        approval_basis=("inherited_source" if source_status == "inherited_canonical"
                        else "explicit_composition_selection"),
        source_refs=source_refs, source_version=source_revision,
        disclosure_level=_bounded_text(disclosure.get("level"), "canon disclosure level", 64),
        release_event_id=release_event,
        is_user_fact=_exact_bool(item.get("is_user_fact"), "is_user_fact"),
        is_shared_experience=_exact_bool(item.get("is_shared_experience"), "is_shared_experience"),
        first_person_text=item.get("first_person_text"),
        memory_temporal_type=item.get("memory_temporal_type", "source_quote"),
    )


def definition_from_documents(graph_doc: dict[str, Any], seed_doc: dict[str, Any], *,
                              approved_canon_ids: tuple[str, ...] | None = None) -> StoryDefinition:
    """Create an immutable runtime definition from the authored JSON package.

    Author-created backstory with status ``author_draft`` remains a proposal by
    default. Composition may explicitly select exact draft IDs; the projection
    records its source status, revision, and authored-fiction provenance.
    """
    if not isinstance(graph_doc, dict) or not isinstance(seed_doc, dict):
        raise ValueError("story graph and seed must be JSON objects")
    if graph_doc.get("schema") != "mira.story-graph.v1":
        raise ValueError("unsupported story graph schema")
    if seed_doc.get("schema") != "mira.story-seed.v1":
        raise ValueError("unsupported story seed schema")
    if graph_doc.get("story_id") != seed_doc.get("story_id"):
        raise ValueError("graph and seed story IDs differ")
    graph_id = _bounded_text(graph_doc.get("graph_id"), "graph ID", 128)
    story_id = _bounded_text(graph_doc.get("story_id"), "story ID", 128)
    graph_revision = _revision(graph_doc.get("revision"), "graph revision")
    seed_version = _revision(seed_doc.get("version"), "seed version")
    raw_nodes = graph_doc.get("nodes", ())
    if not isinstance(raw_nodes, (list, tuple)) or len(raw_nodes) > 16:
        raise ValueError("graph node list is malformed or too large")
    nodes = tuple(StoryNode(_bounded_text(item.get("id"), "node ID", 64))
                  for item in raw_nodes if isinstance(item, dict))
    if len(nodes) != len(raw_nodes):
        raise ValueError("graph node rows must be objects")
    if len(nodes) != 4 or set(nodes) != set(StoryNode):
        raise ValueError("only the bounded four-node graph is approved by this runtime")
    canonical = json.dumps(graph_doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    graph = StoryGraph(
        story_id=story_id, graph_id=graph_id,
        revision=graph_revision, nodes=tuple(StoryNode),
        initial_node=StoryNode(_bounded_text(graph_doc["initial_node"], "initial node", 64)),
        content_hash=hashlib.sha256(canonical).hexdigest(),
    )
    raw_fiction = seed_doc.get("canonical_fiction", ())
    if not isinstance(raw_fiction, (list, tuple)) or len(raw_fiction) > 64:
        raise ValueError("canonical fiction list is malformed or too large")
    if any(not isinstance(item, dict) for item in raw_fiction):
        raise ValueError("canonical fiction rows must be objects")
    raw_entries = tuple(item for item in raw_fiction
                        if item.get("status") in {"inherited_canonical", "current_brief_constraint", "author_draft"})
    for item in raw_entries:
        _bounded_text(item.get("id"), "canon ID", 128)
        _bounded_text(item.get("status"), "canon source status", 64)
        _exact_bool(item.get("author_created"), "author_created")
        _exact_bool(item.get("is_user_fact"), "is_user_fact")
        _exact_bool(item.get("is_shared_experience"), "is_shared_experience")
        if item["is_user_fact"] or item["is_shared_experience"] or not item["author_created"]:
            raise ValueError("story canon source rows must be authored fiction, not user facts or shared events")
    eligible_ids = {item["id"] for item in raw_entries}
    if approved_canon_ids is None:
        selected_ids = {item["id"] for item in raw_entries if item.get("status") == "inherited_canonical"}
    else:
        if not isinstance(approved_canon_ids, tuple) or any(not isinstance(i, str) for i in approved_canon_ids):
            raise ValueError("canon selection must be a tuple of exact string IDs")
        selected_ids = set(approved_canon_ids)
        if len(selected_ids) != len(approved_canon_ids):
            raise ValueError("approved canon selection contains duplicate IDs")
        if not selected_ids.issubset(eligible_ids):
            raise ValueError("canon selection references a user fact, private item, or unknown entry")
    entries = tuple(_canon_entry(item, seed_version) for item in raw_entries if item["id"] in selected_ids)
    proposals = tuple(item["id"] for item in raw_entries
                      if item.get("status") == "author_draft" and item["id"] not in selected_ids)
    canon_view = [{
        "id": row.entry_id, "status": row.status, "source_status": row.source_status,
        "text": row.text, "category": row.category, "source": row.source,
        "author_created": row.author_created, "approval_basis": row.approval_basis,
        "source_refs": row.source_refs, "source_version": row.source_version,
        "disclosure_level": row.disclosure_level, "release_event_id": row.release_event_id,
        "first_person_text": row.first_person_text, "memory_temporal_type": row.memory_temporal_type,
    } for row in entries]
    canon_hash = hashlib.sha256(json.dumps({"story_id": story_id, "revision": seed_version,
        "entries": canon_view}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    canon = CanonRevision(story_id=story_id, revision=seed_version,
                          entries=entries, content_hash=canon_hash, proposal_ids=proposals)
    return StoryDefinition(graph=graph, canon=canon)


@dataclass(frozen=True, slots=True)
class PendingTransition:
    transition_id: str
    grant_id: str
    receipt_kind: ReceiptKind
    epoch: int
    input_id: str
    offer_id: str | None
    source_node: StoryNode
    admitted_node: StoryNode
    target_node: StoryNode
    capability_id: str | None = None
    capability_revision: str | None = None
    draft_cue_digest: str | None = None
    compiled_effect_id: str | None = None
    compiled_effect_digest: str | None = None
    receipt_requirement: ReceiptRequirement | None = None

    def __post_init__(self) -> None:
        _bounded_text(self.transition_id, "pending transition ID", 64)
        _bounded_text(self.grant_id, "pending grant ID", 128)
        _revision(self.epoch, "pending transition epoch", allow_zero=True)
        _bounded_text(self.input_id, "pending input ID", 128)
        if self.offer_id is not None:
            _bounded_text(self.offer_id, "pending offer ID", 96)
        if not all(isinstance(node, StoryNode) for node in (self.source_node, self.admitted_node, self.target_node)):
            raise ValueError("pending node values must be fixed graph labels")
        if self.capability_revision is not None:
            _bounded_text(self.capability_revision, "capability revision", 128)
        if self.draft_cue_digest is not None and not _is_sha256(self.draft_cue_digest):
            raise ValueError("pending cue digest must be SHA-256")
        if self.compiled_effect_id is not None:
            _bounded_text(self.compiled_effect_id, "compiled effect ID", 128)
        if self.compiled_effect_digest is not None and not _is_sha256(self.compiled_effect_digest):
            raise ValueError("compiled effect digest must be SHA-256")


@dataclass(frozen=True, slots=True)
class ReceiptRequirement:
    component: ReceiptComponent
    component_id: str
    component_digest: str
    cue_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.component, ReceiptComponent):
            raise ValueError("receipt component must be a fixed typed label")
        if not isinstance(self.component_id, str) or not self.component_id or len(self.component_id) > 128 or not _is_sha256(self.component_digest):
            raise ValueError("receipt component requires a bounded exact ID and SHA-256 digest")
        if self.cue_digest is not None and not _is_sha256(self.cue_digest):
            raise ValueError("cue digest must be SHA-256")


@dataclass(frozen=True, slots=True)
class EpisodeCandidate:
    candidate_id: str
    event_code: str
    receipt_id: str
    compiled_effect_id: str
    compiled_effect_digest: str
    component_id: str
    component_digest: str
    evidence: EvidenceLabel
    story_id: str
    graph_revision: int
    canon_revision: int
    character_state: tuple[tuple[str, str], ...]
    claim_boundary: tuple[str, ...] = (
        "software_character_state_only",
        "no_claim_of_physical_action",
        "no_claim_that_a_human_heard_or_understood",
        "not_user_fact_or_shared_experience",
    )
    status: str = "candidate_only"

    def __post_init__(self) -> None:
        for value, label, limit in ((self.candidate_id, "episode candidate ID", 160),
                                    (self.event_code, "episode event code", 96),
                                    (self.receipt_id, "episode receipt ID", 128),
                                    (self.compiled_effect_id, "episode compiled effect ID", 128),
                                    (self.component_id, "episode component ID", 128),
                                    (self.story_id, "episode story ID", 128)):
            _bounded_text(value, label, limit)
        if not _is_sha256(self.compiled_effect_digest) or not _is_sha256(self.component_digest):
            raise ValueError("episode must preserve compiled effect and receipt component digests")
        if not isinstance(self.evidence, EvidenceLabel):
            raise ValueError("episode evidence must be a fixed software/client/fiction label")
        _revision(self.graph_revision, "episode graph revision")
        _revision(self.canon_revision, "episode canon revision")
        if not isinstance(self.character_state, tuple) or len(self.character_state) > 8:
            raise ValueError("episode state facts must be bounded immutable pairs")
        if any(not isinstance(pair, tuple) or len(pair) != 2
               or any(not isinstance(value, str) or len(value) > 128 for value in pair)
               for pair in self.character_state):
            raise ValueError("episode facts must be bounded string pairs")
        if not isinstance(self.claim_boundary, tuple) or any(not isinstance(value, str) for value in self.claim_boundary):
            raise ValueError("episode claim boundary must be fixed immutable labels")
        if self.status != "candidate_only":
            raise ValueError("story episode persistence does not promote to user history")


@dataclass(frozen=True, slots=True)
class StoryState:
    scope_id: str
    story_id: str
    graph_id: str
    graph_revision: int
    canon_revision: int
    graph_hash: str
    canon_hash: str
    node: StoryNode = StoryNode.CAFE_CHAT
    epoch: int = 0
    revision: int = 0
    active_offer_id: str | None = None
    offer_status: OfferStatus = OfferStatus.NONE
    current_outfit: str = "black_jacket"
    relationship_delta: int = 0
    pending: PendingTransition | None = None
    clarification_used: bool = False
    last_input_ids: tuple[str, ...] = ()
    input_fence_id: str | None = None
    released_story_events: tuple[str, ...] = ()
    receipt_ids: tuple[str, ...] = ()
    episodes: tuple[EpisodeCandidate, ...] = ()
    reentry_label: str = "session_state_only"
    # Historical receipt-backed appearance, never automatic browser restoration.
    last_acknowledged_outfit: str | None = None
    last_acknowledged_accessory: str | None = None
    last_acknowledged_emotion: str | None = None
    active_offer_capability: str | None = None
    active_offer_cue: str | None = None
    chapter: ChapterState = ChapterState()

    def __post_init__(self) -> None:
        if type(self.chapter) is not ChapterState:
            raise ValueError("story chapter must have an explicit known schema")
        _bounded_text(self.scope_id, "story scope ID", 256)
        _bounded_text(self.story_id, "story ID", 128)
        _bounded_text(self.graph_id, "graph ID", 128)
        _revision(self.graph_revision, "graph revision")
        _revision(self.canon_revision, "canon revision")
        if not _is_sha256(self.graph_hash) or not _is_sha256(self.canon_hash):
            raise ValueError("story state must bind exact graph and canon content hashes")
        _revision(self.epoch, "story epoch", allow_zero=True)
        _revision(self.revision, "story state revision", allow_zero=True)
        if type(self.relationship_delta) is not int or self.relationship_delta != 0:
            raise ValueError("the bounded rain invitation has no relationship score changes")
        if not isinstance(self.node, StoryNode) or not isinstance(self.offer_status, OfferStatus):
            raise ValueError("story node/offer status must be fixed typed labels")
        if self.current_outfit not in {"black_jacket", "cream_inner_only", "amber_raincoat"}:
            raise ValueError("story outfit is not an approved fictional state")
        if self.last_acknowledged_outfit not in {None, "black_jacket", "cream_inner_only", "amber_raincoat"}:
            raise ValueError("acknowledged outfit is not an approved fictional state")
        if self.last_acknowledged_accessory not in {None, "camera_clip", "star_clip"}:
            raise ValueError("acknowledged accessory is not an approved fictional state")
        if self.last_acknowledged_emotion not in {None, "normal", "guarded", "happy", "shy"}:
            raise ValueError("acknowledged emotion is not an approved fictional state")
        if self.active_offer_capability not in {None, "mira.outfit.amber_raincoat", "cafe.scene.rain_window"}:
            raise ValueError("offer capability is not approved")
        if self.active_offer_cue is not None:
            _bounded_text(self.active_offer_cue, "offer cue", 500)
        if self.active_offer_id is not None:
            _bounded_text(self.active_offer_id, "offer ID", 96)
        if self.input_fence_id is not None:
            _bounded_text(self.input_fence_id, "input fence ID", 128)
        if not isinstance(self.last_input_ids, tuple) or len(self.last_input_ids) > 16 or len(set(self.last_input_ids)) != len(self.last_input_ids):
            raise ValueError("story input ID history must be a unique bounded tuple")
        if not isinstance(self.receipt_ids, tuple) or len(self.receipt_ids) > 64 or len(set(self.receipt_ids)) != len(self.receipt_ids):
            raise ValueError("receipt ID history must be a unique bounded tuple")
        if not isinstance(self.episodes, tuple) or len(self.episodes) > 32:
            raise ValueError("episode candidates must be a bounded immutable tuple")
        if any(not isinstance(episode, EpisodeCandidate) for episode in self.episodes):
            raise ValueError("story episodes must be qualified typed candidates")
        if not isinstance(self.released_story_events, tuple) or len(self.released_story_events) > 16:
            raise ValueError("released canon event IDs must be a bounded immutable tuple")
        if any(event not in _CANON_RELEASE_OVERRIDES.values() for event in self.released_story_events):
            raise ValueError("released canon event is not allowlisted")
        if type(self.clarification_used) is not bool:
            raise ValueError("clarification flag must be boolean")
        if self.pending is not None and (not isinstance(self.pending, PendingTransition)
                or self.pending.epoch != self.epoch):
            raise ValueError("pending transition must match current typed epoch")

    @classmethod
    def initial(cls, definition: StoryDefinition, scope_id: str, *, outfit: str = "black_jacket") -> StoryState:
        if not scope_id:
            raise ValueError("a server-bound nonempty scope is required")
        if outfit not in {"black_jacket", "cream_inner_only", "amber_raincoat"}:
            raise ValueError("unknown approved outfit state")
        return cls(scope_id=scope_id, story_id=definition.graph.story_id,
                   graph_id=definition.graph.graph_id, graph_revision=definition.graph.revision,
                   canon_revision=definition.canon.revision, graph_hash=definition.graph.content_hash,
                   canon_hash=definition.canon.content_hash, node=definition.graph.initial_node,
                   current_outfit=outfit)


@dataclass(frozen=True, slots=True)
class StoryProposal:
    """Bounded LLM proposal; the reducer, never this object, decides admission."""
    transition_id: str
    signal: ProposalSignal
    input_id: str
    epoch: int
    offer_id: str | None = None
    target_capabilities: tuple[str, ...] = ()
    draft_cue: str | None = None
    input_act: ChapterInputAct | None = None
    reopen_offer: bool = False

    def __post_init__(self) -> None:
        _exact_bool(self.reopen_offer, "proposal reopen")
        if self.input_act is not None and type(self.input_act) is not ChapterInputAct:
            raise ValueError("invalid typed chapter input act")
        if self.transition_id in CHAPTER_SCENES:
            expected_cap = CHAPTER_CAPABILITIES[CHAPTER_SCENES[self.transition_id]]
            if self.target_capabilities != (expected_cap,):
                raise ValueError("chapter proposal must name exactly its local presentation capability")
        elif self.transition_id.startswith("x.") and self.target_capabilities:
            raise ValueError("chapter cue cannot request other capabilities")
        if self.transition_id in {"x.story", "x.promise"} and not self.draft_cue:
            raise ValueError("chapter story beat must bind an exact subtitle cue")
        _bounded_text(self.transition_id, "proposal transition ID", 64)
        _bounded_text(self.input_id, "proposal input ID", 128)
        _revision(self.epoch, "proposal epoch", allow_zero=True)
        if not isinstance(self.signal, ProposalSignal):
            raise ValueError("proposal signal must be an allowlisted enum")
        expected = PROPOSAL_SIGNAL_BY_TRANSITION.get(self.transition_id)
        if expected is None or expected is not self.signal:
            raise ValueError("proposal transition/signal pair is not allowlisted")
        if not isinstance(self.target_capabilities, tuple) or len(self.target_capabilities) > 2 or len(set(self.target_capabilities)) != len(self.target_capabilities):
            raise ValueError("proposal capability list must be unique and bounded to two")
        if any(not isinstance(cap, str) or cap not in ALLOWED_CAPABILITY_IDS for cap in self.target_capabilities):
            raise ValueError("proposal capabilities must be allowlisted IDs")
        if self.draft_cue is not None and len(self.draft_cue) > 500:
            raise ValueError("proposal cue exceeds the fixed 500-character bound")
        if self.offer_id is not None:
            _bounded_text(self.offer_id, "proposal offer ID", 96)
        if self.draft_cue is not None:
            _bounded_text(self.draft_cue, "proposal cue", 500)
        if self.transition_id == "t.yes" and self.target_capabilities != ("mira.outfit.amber_raincoat",):
            raise ValueError("raincoat proposal must name exactly the approved outfit capability")
        if self.transition_id == "t.offer" and not self.draft_cue:
            raise ValueError("offer proposal must carry the exact bounded cue text to be reviewed")
        if self.transition_id == "t.window" and self.target_capabilities != ("cafe.scene.rain_window",):
            raise ValueError("window proposal must name exactly the approved scene capability")
        if self.transition_id == "t.offer" and self.target_capabilities not in {(), ("cafe.scene.rain_window",)}:
            raise ValueError("offer goal must be legacy wardrobe or the explicit window scene")
        if self.transition_id == "t.chat" and self.target_capabilities:
            raise ValueError("chat proposals cannot request effect capabilities")


PROPOSAL_SIGNAL_BY_TRANSITION = {
    "t.offer": ProposalSignal.OFFER_RAIN,
    "t.yes": ProposalSignal.ACCEPT_RAINCOAT,
    "t.window": ProposalSignal.LOOK_AT_RAIN,
    "t.chat": ProposalSignal.CHAT,
    "x.recognize": ProposalSignal.RECOGNIZE_XIAHE,
    "x.story": ProposalSignal.RECALL_OLD_FRIEND,
    "x.promise": ProposalSignal.RECALL_PHOTO_PROMISE,
    "x.gift_offer": ProposalSignal.OFFER_PHOTO_GIFT,
    "x.gift_accept": ProposalSignal.ACCEPT_PHOTO_GIFT,
    "x.gift_decline": ProposalSignal.DECLINE_PHOTO_GIFT,
    "x.exit": ProposalSignal.EXIT_XIAHE_ROLE,
}
ALLOWED_PROPOSAL_FIELDS = frozenset({
    "transition_id", "signal", "offer_id", "target_capabilities", "draft_cue", "input_act", "reopen_offer",
})
ALLOWED_CAPABILITY_IDS = frozenset({
    "mira.outfit.amber_raincoat", "mira.pose.look_at_rain", "cafe.scene.rain_window",
    *CHAPTER_CAPABILITIES.values(),
})


def parse_story_proposal(payload: object, *, input_id: str, epoch: int) -> StoryProposal:
    """Parse a bounded structured LLM proposal; raw text is never control input."""
    if not isinstance(payload, dict) or not payload:
        raise ValueError("story proposal must be a nonempty JSON object")
    if set(payload) - ALLOWED_PROPOSAL_FIELDS:
        raise ValueError("story proposal contains unknown fields")
    transition_id = payload.get("transition_id")
    signal_text = payload.get("signal")
    if not isinstance(transition_id, str) or not isinstance(signal_text, str):
        raise ValueError("proposal requires string transition_id and signal")
    try:
        signal = ProposalSignal(signal_text)
    except ValueError as exc:
        raise ValueError("proposal signal is not allowlisted") from exc
    offer_id = payload.get("offer_id")
    if offer_id is not None and (not isinstance(offer_id, str) or not offer_id or len(offer_id) > 96):
        raise ValueError("offer ID must be a bounded nonempty string")
    if transition_id in {"t.offer", "t.yes", "t.window", "x.gift_offer", "x.gift_accept", "x.gift_decline"} and offer_id is None:
        raise ValueError("offer and choice proposals require the exact offer ID")
    raw_caps = payload.get("target_capabilities", ())
    if not isinstance(raw_caps, (list, tuple)) or len(raw_caps) > 2 or any(not isinstance(c, str) for c in raw_caps):
        raise ValueError("target capability IDs must be a bounded string list")
    caps = tuple(raw_caps)
    if any(cap not in ALLOWED_CAPABILITY_IDS for cap in caps):
        raise ValueError("proposal contains a non-allowlisted capability")
    draft = payload.get("draft_cue")
    if draft is not None and (not isinstance(draft, str) or len(draft) > 500):
        raise ValueError("draft cue must be a string of at most 500 characters")
    return StoryProposal(transition_id, signal, input_id, epoch, offer_id, caps, draft,
        parse_input_act(payload.get("input_act")), payload.get("reopen_offer", False))


@dataclass(frozen=True, slots=True)
class JevEvidence:
    input_id: str
    epoch: int
    offer_id: str | None
    will: Will
    relevance: Relevance = Relevance.UNKNOWN
    refusal: bool = False

    def __post_init__(self) -> None:
        _bounded_text(self.input_id, "JEV input ID", 128)
        _revision(self.epoch, "JEV epoch", allow_zero=True)
        if self.offer_id is not None:
            _bounded_text(self.offer_id, "JEV offer ID", 96)
        if not isinstance(self.will, Will) or not isinstance(self.relevance, Relevance):
            raise ValueError("JEV output must use fixed will/relevance labels")
        _exact_bool(self.refusal, "JEV refusal")

    def normalized_will(self) -> Will:
        # Conflicting or malformed labels fail closed as UNKNOWN.
        if self.refusal and self.will is Will.YES:
            return Will.UNKNOWN
        if self.refusal:
            return Will.NO
        return self.will


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    capability_id: str
    state: CapabilityState
    asset_revision: str | None = None
    verified_assets: tuple[str, ...] = ()
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        _bounded_text(self.capability_id, "capability ID", 128)
        if not isinstance(self.state, CapabilityState):
            raise ValueError("capability state must be fixed typed label")
        if not isinstance(self.verified_assets, tuple) or len(self.verified_assets) > 32:
            raise ValueError("verified asset list must be bounded immutable tuple")
        if any(not isinstance(x, str) or not x or len(x) > 128 for x in self.verified_assets):
            raise ValueError("verified asset IDs must be bounded strings")
        if self.state is CapabilityState.READY and (not self.asset_revision or not self.verified_assets or not self.evidence_id):
            raise ValueError("READY requires a concrete revision, verified asset set, and readiness evidence")


@dataclass(frozen=True, slots=True)
class ReadinessCatalog:
    revision: str
    records: tuple[CapabilityRecord, ...] = ()

    def __post_init__(self) -> None:
        _bounded_text(self.revision, "readiness catalog revision", 128)
        if not isinstance(self.records, tuple) or len(self.records) > 64:
            raise ValueError("readiness records must be a bounded immutable tuple")
        ids = [item.capability_id for item in self.records]
        if not self.revision or len(ids) != len(set(ids)):
            raise ValueError("readiness catalog needs a revision and unique capability IDs")

    def get(self, capability_id: str) -> CapabilityRecord | None:
        return next((item for item in self.records if item.capability_id == capability_id), None)

    def state_for(self, capability_id: str) -> CapabilityState:
        record = self.get(capability_id)
        return record.state if record else CapabilityState.UNKNOWN


@dataclass(frozen=True, slots=True)
class PresentationReceipt:
    receipt_id: str
    scope_id: str
    story_id: str
    graph_revision: int
    canon_revision: int
    epoch: int
    grant_id: str
    transition_id: str
    kind: ReceiptKind
    evidence: EvidenceLabel
    outcome: str
    offer_id: str | None = None
    before_outfit: str | None = None
    after_outfit: str | None = None
    capability_revision: str | None = None
    compiled_effect_id: str | None = None
    compiled_effect_digest: str | None = None
    component: ReceiptComponent | None = None
    component_id: str | None = None
    component_digest: str | None = None
    cue_digest: str | None = None

    def __post_init__(self) -> None:
        _bounded_text(self.receipt_id, "receipt ID", 128)
        _bounded_text(self.scope_id, "receipt scope", 256)
        _bounded_text(self.story_id, "receipt story ID", 128)
        _revision(self.graph_revision, "receipt graph revision")
        _revision(self.canon_revision, "receipt canon revision")
        _revision(self.epoch, "receipt epoch", allow_zero=True)
        if not isinstance(self.kind, ReceiptKind) or not isinstance(self.evidence, EvidenceLabel):
            raise ValueError("receipt kind/evidence must be typed fixed labels")
        if not all((self.receipt_id, self.scope_id, self.grant_id, self.transition_id)):
            raise ValueError("receipt requires exact stable IDs")
        if self.outcome not in {"complete", "failed"}:
            raise ValueError("receipt outcome must be a fixed label")
        if (not self.compiled_effect_id or not _is_sha256(self.compiled_effect_digest)
                or not self.component or not self.component_id or not _is_sha256(self.component_digest)):
            raise ValueError("receipt requires exact compiled-effect and component identities/digests")
        if self.cue_digest is not None and not _is_sha256(self.cue_digest):
            raise ValueError("receipt cue digest must be SHA-256")


@dataclass(frozen=True, slots=True)
class NativeStoryEvidence:
    """Finite Luna tool intent, bound by application to the current reliable input.

    Not a JEV observation, confidence score or presentation receipt.
    """
    input_id: str
    epoch: int
    offer_id: str | None
    intent: str

    def __post_init__(self):
        _bounded_text(self.input_id,'native story input',128)
        _revision(self.epoch,'native story epoch',allow_zero=True)
        if self.offer_id is not None:_bounded_text(self.offer_id,'native offer',96)
        if self.intent not in {'offer','accept','decline','reopen'}:
            raise ValueError('invalid native story intent')

    def normalized_will(self):
        return Will.NO if self.intent=='decline' else Will.YES if self.intent=='accept' else Will.UNKNOWN


@dataclass(frozen=True, slots=True)
class StoryTurn:
    input_id: str
    epoch: int
    proposal: StoryProposal | None
    jev: JevEvidence | None
    readiness: ReadinessCatalog
    permission_current: bool
    reliable_input: bool = True
    reopen_offer: bool = False
    native_evidence: NativeStoryEvidence | None = None

    def __post_init__(self) -> None:
        if not self.input_id:
            raise ValueError("input ID required")
        _bounded_text(self.input_id, "story input ID", 128)
        _revision(self.epoch, "story input epoch", allow_zero=True)
        if not isinstance(self.readiness, ReadinessCatalog):
            raise ValueError("story turn must receive a typed readiness catalog")
        _exact_bool(self.permission_current, "current permission")
        _exact_bool(self.reliable_input, "reliable input")
        _exact_bool(self.reopen_offer, "explicit offer reopen")
        if self.proposal is not None and not isinstance(self.proposal, StoryProposal):
            raise ValueError("story turn proposal must be a bounded typed DTO")
        if self.jev is not None and not isinstance(self.jev, JevEvidence):
            raise ValueError("story turn JEV evidence must be typed")
        if self.native_evidence is not None and (type(self.native_evidence) is not NativeStoryEvidence or self.jev is not None):
            raise ValueError("native evidence must be independent of JEV")


@dataclass(frozen=True, slots=True)
class Stop:
    epoch: int

    def __post_init__(self) -> None:
        _revision(self.epoch, "Stop epoch", allow_zero=True)


@dataclass(frozen=True, slots=True)
class EffectPlan:
    grant_id: str
    transition_id: str
    kind: ReceiptKind
    scope_id: str
    story_id: str
    graph_revision: int
    canon_revision: int
    epoch: int
    offer_id: str | None
    capability_ids: tuple[str, ...] = ()
    capability_revision: str | None = None
    draft_cue_digest: str | None = None
    compiled_effect_id: str | None = None
    compiled_effect_digest: str | None = None
    receipt_requirement: ReceiptRequirement | None = None


@dataclass(frozen=True, slots=True)
class Reduction:
    state: StoryState
    code: ResultCode
    fallback: Fallback = Fallback.NONE
    effect_plan: EffectPlan | None = None
    explanation: str = ""


def _grant_id(state: StoryState, input_id: str, transition_id: str, epoch: int) -> str:
    raw = "|".join((state.scope_id, state.story_id, str(state.graph_revision), str(state.canon_revision), str(epoch), input_id, transition_id, str(state.revision + 1)))
    return "grant." + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _compatible(state: StoryState, definition: StoryDefinition) -> bool:
    return (state.story_id == definition.graph.story_id and state.graph_id == definition.graph.graph_id
            and state.graph_revision == definition.graph.revision and state.graph_hash == definition.graph.content_hash
            and state.canon_revision == definition.canon.revision and state.canon_hash == definition.canon.content_hash)


def bind_compiled_effect(state: StoryState, plan: EffectPlan, *, compiled_effect_id: str,
                         compiled_effect_digest: str, requirement: ReceiptRequirement,
                         actual_cue_digest: str | None = None) -> tuple[StoryState, EffectPlan]:
    """Bind a reviewed/compiled effect to the reducer-issued opaque grant.

    This boundary is called by Director after semantic review/compilation. The
    LLM cannot supply any effect or component identifiers.
    """
    pending = state.pending
    if pending is None or plan.grant_id != pending.grant_id or plan.transition_id != pending.transition_id:
        raise ValueError("effect plan has no matching current reducer grant")
    if (plan.scope_id != state.scope_id or plan.story_id != state.story_id
            or plan.graph_revision != state.graph_revision or plan.canon_revision != state.canon_revision
            or plan.epoch != state.epoch or pending.epoch != state.epoch):
        raise ValueError("compiled effect plan is stale or cross-scope/version")
    if (not compiled_effect_id or len(compiled_effect_id) > 128
            or not _is_sha256(compiled_effect_digest)):
        raise ValueError("compiled effect requires a bounded exact ID and SHA-256 digest")
    if pending.draft_cue_digest is not None and actual_cue_digest != pending.draft_cue_digest:
        raise ValueError("compiled cue differs from the reviewed LLM draft cue")
    if plan.transition_id == "t.offer":
        if requirement.component not in {ReceiptComponent.SUBTITLE, ReceiptComponent.SPEECH}:
            raise ValueError("offer requires one exact subtitle receipt or matching speech substitute")
        if requirement.cue_digest != pending.draft_cue_digest:
            raise ValueError("offer receipt must bind the exact reviewed cue digest")
        if requirement.component is ReceiptComponent.SUBTITLE and requirement.component_digest != requirement.cue_digest:
            raise ValueError("subtitle component digest must equal exact cue text digest")
        if requirement.component_id != compiled_effect_id:
            raise ValueError("offer component ID must equal the compiled cue effect ID")
    elif plan.transition_id in {"t.yes", "t.window"}:
        component = ReceiptComponent.SCENE if plan.transition_id == "t.window" else ReceiptComponent.WARDROBE
        if (requirement.component is not component
                or requirement.component_id != compiled_effect_id
                or requirement.component_digest != compiled_effect_digest):
            raise ValueError("wardrobe plan must bind exactly one compiled wardrobe effect receipt")
    else:
        raise ValueError("transition has no supported compiled effect binding")
    next_pending = replace(pending, compiled_effect_id=compiled_effect_id,
                           compiled_effect_digest=compiled_effect_digest,
                           receipt_requirement=requirement)
    bound_state = replace(state, pending=next_pending, revision=state.revision + 1)
    bound_plan = replace(plan, compiled_effect_id=compiled_effect_id,
                         compiled_effect_digest=compiled_effect_digest,
                         receipt_requirement=requirement)
    return bound_state, bound_plan


def begin_story_input(state: StoryState, input_id: str, epoch: int,
                      definition: StoryDefinition) -> StoryState:
    """Fence stale work at input-start without consuming the input ID.

    A previously acknowledged visible offer remains available for a YES reply.
    Only pending, unacknowledged effects are canceled here.
    """
    if not _compatible(state, definition) or not input_id or len(input_id) > 128:
        raise ValueError("input fence requires a matching story definition and bounded input ID")
    if epoch < state.epoch or input_id in state.last_input_ids:
        raise ValueError("input fence is stale or already consumed")
    if state.input_fence_id == input_id and state.epoch == epoch:
        return state
    base = replace(state, chapter=cancel_chapter(state.chapter))
    if state.pending is not None:
        # Both supported pending actions lead back to the last acknowledged cafe state.
        base = replace(base, node=StoryNode.CAFE_CHAT, pending=None,
                       offer_status=OfferStatus.SUSPENDED, active_offer_id=None,
                       clarification_used=False)
    return replace(base, epoch=epoch, input_fence_id=input_id, revision=base.revision + 1)


def fence_story_reply(state: StoryState, epoch: int, definition: StoryDefinition) -> StoryState:
    """Fence unpresented work without inventing an input or revoking an offer.

    The caller already fenced issued output grants. Unlike global Stop, a PTT
    control boundary preserves presented role/offer facts and their suspension.
    """
    if not _compatible(state,definition) or type(epoch) is not int:
        raise ValueError('reply fence requires current compatible story')
    if epoch == state.epoch: return state
    if epoch != state.epoch+1:
        raise ValueError('reply fence must follow the current epoch')
    chapter=state.chapter
    if chapter.pending is not None:
        chapter=replace(chapter,pending=None,revision=chapter.revision+1)
    base=replace(state,chapter=chapter)
    if state.pending is not None:
        base=replace(base,node=StoryNode.CAFE_CHAT,pending=None,
            offer_status=OfferStatus.SUSPENDED,active_offer_id=None,clarification_used=False)
    return replace(base,epoch=epoch,input_fence_id=None,revision=base.revision+1)


def reduce_story(state: StoryState, event: StoryTurn | Stop | PresentationReceipt, definition: StoryDefinition) -> Reduction:
    """Apply one fixed, typed event. No graph command is executed here."""
    if not _compatible(state, definition):
        return Reduction(state, ResultCode.REJECTED, explanation="graph/canon revision mismatch")
    if isinstance(event, Stop):
        if event.epoch < state.epoch:
            return Reduction(state, ResultCode.STALE, explanation="stale Stop epoch")
        updated = state
        if state.pending is not None:
            updated = replace(state, node=StoryNode.CAFE_CHAT, pending=None,
                              offer_status=OfferStatus.SUSPENDED, active_offer_id=None,
                              clarification_used=False)
        updated = replace(updated, chapter=cancel_chapter(updated.chapter,invalidate_offer=True), epoch=event.epoch, input_fence_id=None,
                          revision=updated.revision + 1)
        return Reduction(updated, ResultCode.STOPPED,
                         explanation="Stop invalidates pending effects but preserves acknowledged story/history")
    if isinstance(event, PresentationReceipt):
        return _apply_receipt(state, event)

    if event.input_id in state.last_input_ids:
        return Reduction(state, ResultCode.DUPLICATE, explanation="duplicate reliable input")
    try:
        base = begin_story_input(state, event.input_id, event.epoch, definition)
    except ValueError:
        return Reduction(state, ResultCode.STALE, explanation="stale input fence")
    if not event.reliable_input:
        return Reduction(base, ResultCode.REJECTED, explanation="unreliable input cancels pending effects but is not story control evidence")
    base = replace(base, input_fence_id=None,
                   last_input_ids=(base.last_input_ids + (event.input_id,))[-16:])

    proposal = event.proposal
    evidence = event.native_evidence if event.native_evidence is not None else event.jev
    if proposal and (proposal.input_id != event.input_id or proposal.epoch != event.epoch):
        return Reduction(base, ResultCode.REJECTED, explanation="LLM proposal is not bound to current reliable input/epoch")
    if evidence and (evidence.input_id != event.input_id or evidence.epoch != event.epoch):
        evidence = None  # Evidence mismatch is UNKNOWN; it cannot drive a transition.

    relevant = (evidence is not None and (type(evidence) is NativeStoryEvidence
        or evidence.relevance is Relevance.RELEVANT))

    # Chat proposals can improve dialogue, but never move the graph.
    if proposal and proposal.signal is ProposalSignal.CHAT and base.node is not StoryNode.AWAIT_RAIN_CHOICE:
        expected = "t.chat"
        if proposal.transition_id == expected and base.node in {StoryNode.CAFE_CHAT, StoryNode.RAIN_VIEW}:
            return Reduction(base, ResultCode.CHAT_HELD, Fallback.ORDINARY_CHAT, explanation="chat remains in current node")

    # Each optional branch can be invited after either acknowledged rain effect.
    # The existing receipt history remains authoritative for the visible scene.
    if base.node is StoryNode.RAIN_VIEW and proposal and proposal.transition_id == "t.offer":
        base = replace(base, node=StoryNode.CAFE_CHAT)

    if base.node is StoryNode.CAFE_CHAT:
        if not proposal or proposal.transition_id != "t.offer" or proposal.signal is not ProposalSignal.OFFER_RAIN:
            return Reduction(base, ResultCode.CHAT_HELD, Fallback.ORDINARY_CHAT, explanation="no admitted story proposal")
        if not event.permission_current or not relevant:
            return Reduction(base, ResultCode.REJECTED, Fallback.ORDINARY_CHAT, explanation="relevance and current permission required")
        if base.offer_status in {OfferStatus.DECLINED, OfferStatus.SUSPENDED, OfferStatus.CLOSED_CAPABILITY_UNAVAILABLE} and not event.reopen_offer:
            return Reduction(base, ResultCode.REJECTED, Fallback.ORDINARY_CHAT,
                             explanation="do not re-invite after decline/interruption/unavailability without explicit reopen")
        if not proposal.offer_id:
            return Reduction(base, ResultCode.REJECTED, explanation="offer proposal must have a bounded offer ID")
        grant_id = _grant_id(base, event.input_id, "t.offer", event.epoch)
        pending = PendingTransition("t.offer", grant_id, ReceiptKind.OFFER_PRESENTED, event.epoch,
                                    event.input_id, proposal.offer_id, base.node, base.node,
                                    StoryNode.AWAIT_RAIN_CHOICE,
                                    draft_cue_digest=hashlib.sha256((proposal.draft_cue or "").encode()).hexdigest())
        next_state = replace(base, pending=pending, active_offer_id=proposal.offer_id,
                             offer_status=OfferStatus.PROPOSED,
                             active_offer_capability=(proposal.target_capabilities[0] if proposal.target_capabilities else "mira.outfit.amber_raincoat"),
                             active_offer_cue=proposal.draft_cue)
        plan = EffectPlan(grant_id, "t.offer", ReceiptKind.OFFER_PRESENTED, base.scope_id,
                          base.story_id, base.graph_revision, base.canon_revision, event.epoch,
                          proposal.offer_id, draft_cue_digest=pending.draft_cue_digest)
        return Reduction(next_state, ResultCode.PROPOSAL_STAGED, effect_plan=plan,
                         explanation="proposal staged; only exact presentation receipt advances node")

    if base.node is StoryNode.AWAIT_RAIN_CHOICE:
        if base.offer_status not in {OfferStatus.PRESENTED, OfferStatus.UNKNOWN} or not base.active_offer_id:
            return Reduction(base, ResultCode.REJECTED, explanation="choice requires a presented active offer")
        if not evidence or evidence.offer_id != base.active_offer_id:
            return Reduction(base, ResultCode.CHOICE_UNKNOWN, Fallback.CALM_CLARIFICATION,
                             explanation="choice evidence does not match the active offer")
        choice = evidence.normalized_will()
        if choice is Will.NO:
            return Reduction(replace(base, node=StoryNode.CAFE_CHAT, active_offer_id=None,
                                     offer_status=OfferStatus.DECLINED, clarification_used=False),
                             ResultCode.CHOICE_NO, Fallback.ORDINARY_CHAT,
                             explanation="decline closes invitation; no relationship or affect penalty")
        if choice is Will.UNKNOWN:
            fallback = Fallback.CALM_CLARIFICATION if not base.clarification_used else Fallback.ORDINARY_CHAT
            return Reduction(replace(base, offer_status=OfferStatus.UNKNOWN, clarification_used=True),
                             ResultCode.CHOICE_UNKNOWN, fallback,
                             explanation="UNKNOWN holds the node and never retries the invitation")
        if choice is Will.YES and not relevant:
            return Reduction(base, ResultCode.CHOICE_UNKNOWN, Fallback.CALM_CLARIFICATION,
                             explanation="YES requires affirmative relevance to the presented offer")
        if proposal and proposal.transition_id == "t.window":
            if (proposal.offer_id != base.active_offer_id
                    or base.active_offer_capability != "cafe.scene.rain_window"
                    or not base.active_offer_cue or not event.permission_current):
                return Reduction(base, ResultCode.REJECTED, Fallback.ORDINARY_CHAT,
                                 explanation="scene requires this exact presented scene invitation")
            record = event.readiness.get("cafe.scene.rain_window")
            if record is None or record.state is CapabilityState.UNKNOWN:
                return Reduction(base, ResultCode.ASSET_UNKNOWN, Fallback.ORDINARY_CHAT)
            if record.state is CapabilityState.UNAVAILABLE:
                return Reduction(replace(base, node=StoryNode.CAFE_CHAT, active_offer_id=None,
                    active_offer_capability=None, active_offer_cue=None,
                    offer_status=OfferStatus.CLOSED_CAPABILITY_UNAVAILABLE),
                    ResultCode.ASSET_UNAVAILABLE, Fallback.CAPABILITY_UNAVAILABLE)
            if "scene.rain_window.composition" not in record.verified_assets:
                return Reduction(base, ResultCode.ASSET_UNKNOWN, Fallback.ORDINARY_CHAT)
            grant_id = _grant_id(base, event.input_id, "t.window", event.epoch)
            pending = PendingTransition("t.window", grant_id, ReceiptKind.SCENE_COMPLETED,
                event.epoch, event.input_id, base.active_offer_id, base.node, base.node,
                StoryNode.RAIN_VIEW, record.capability_id, record.asset_revision)
            plan = EffectPlan(grant_id, "t.window", ReceiptKind.SCENE_COMPLETED, base.scope_id,
                base.story_id, base.graph_revision, base.canon_revision, event.epoch,
                base.active_offer_id, (record.capability_id,), record.asset_revision)
            return Reduction(replace(base, pending=pending, offer_status=OfferStatus.ACCEPTED),
                ResultCode.PROPOSAL_STAGED, effect_plan=plan,
                explanation="scene staged; arrival requires its own exact completed receipt")
        if base.active_offer_capability == "cafe.scene.rain_window":
            return Reduction(base, ResultCode.REJECTED, Fallback.ORDINARY_CHAT,
                             explanation="window consent cannot authorize wardrobe")
        if not proposal or proposal.transition_id != "t.yes" or proposal.signal is not ProposalSignal.ACCEPT_RAINCOAT:
            return Reduction(base, ResultCode.CHOICE_UNKNOWN, Fallback.CALM_CLARIFICATION,
                             explanation="YES is evidence, not an executable graph command")
        if proposal.offer_id != base.active_offer_id:
            return Reduction(base, ResultCode.CHOICE_UNKNOWN, Fallback.CALM_CLARIFICATION,
                             explanation="LLM proposal does not bind to the active offer")
        if not event.permission_current:
            return Reduction(base, ResultCode.REJECTED, explanation="current permission required")
        cap_id = "mira.outfit.amber_raincoat"
        record = event.readiness.get(cap_id)
        if record is None or record.state is CapabilityState.UNKNOWN:
            return Reduction(base, ResultCode.ASSET_UNKNOWN, Fallback.CALM_CLARIFICATION,
                             explanation="logical capability ID alone does not establish readiness")
        if record.state is CapabilityState.UNAVAILABLE:
            return Reduction(replace(base, node=StoryNode.CAFE_CHAT, active_offer_id=None,
                                     offer_status=OfferStatus.CLOSED_CAPABILITY_UNAVAILABLE,
                                     clarification_used=False), ResultCode.ASSET_UNAVAILABLE,
                             Fallback.CAPABILITY_UNAVAILABLE,
                             explanation="unavailable assets close this invitation without outfit change")
        required_assets = {"outer.amber", "inner.cream"}
        if not required_assets.issubset(set(record.verified_assets)):
            return Reduction(base, ResultCode.ASSET_UNKNOWN, Fallback.CALM_CLARIFICATION,
                             explanation="the full approved raincoat plus inner-layer variant is not verified ready")
        if proposal.target_capabilities != (cap_id,):
            return Reduction(base, ResultCode.REJECTED, explanation="proposal capability set must exactly match approved raincoat target")
        grant_id = _grant_id(base, event.input_id, "t.yes", event.epoch)
        pending = PendingTransition("t.yes", grant_id, ReceiptKind.WARDROBE_COMPLETED, event.epoch,
                                    event.input_id, base.active_offer_id, base.node,
                                    StoryNode.RAINCOAT_PENDING, StoryNode.RAIN_VIEW,
                                    cap_id, record.asset_revision,
                                    draft_cue_digest=(hashlib.sha256(proposal.draft_cue.encode()).hexdigest()
                                                      if proposal.draft_cue else None))
        next_state = replace(base, node=StoryNode.RAINCOAT_PENDING, pending=pending,
                             offer_status=OfferStatus.ACCEPTED)
        plan = EffectPlan(grant_id, "t.yes", ReceiptKind.WARDROBE_COMPLETED, base.scope_id,
                          base.story_id, base.graph_revision, base.canon_revision, event.epoch,
                          base.active_offer_id, (cap_id,), record.asset_revision,
                          draft_cue_digest=pending.draft_cue_digest)
        return Reduction(next_state, ResultCode.PROPOSAL_STAGED, effect_plan=plan,
                         explanation="raincoat effect staged; current outfit waits for exact receipt")

    if base.node is StoryNode.RAIN_VIEW:
        # A separate scene/pose branch can be added only with its own catalog and receipts.
        return Reduction(base, ResultCode.CHAT_HELD, Fallback.ORDINARY_CHAT,
                         explanation="bounded runtime keeps look/scene assets behind the Director adapter")
    return Reduction(base, ResultCode.CHAT_HELD, Fallback.ORDINARY_CHAT,
                     explanation="pending effect requires receipt or a new input")


def _apply_receipt(state: StoryState, receipt: PresentationReceipt) -> Reduction:
    if receipt.receipt_id in state.receipt_ids:
        return Reduction(state, ResultCode.DUPLICATE, explanation="receipt already consumed")
    pending = state.pending
    if pending is None:
        return Reduction(state, ResultCode.REJECTED, explanation="no matching pending grant")
    exact = (
        receipt.scope_id == state.scope_id
        and receipt.story_id == state.story_id
        and receipt.graph_revision == state.graph_revision
        and receipt.canon_revision == state.canon_revision
        and receipt.epoch == pending.epoch == state.epoch
        and receipt.grant_id == pending.grant_id
        and receipt.transition_id == pending.transition_id
        and receipt.kind is pending.receipt_kind
        and pending.compiled_effect_id is not None
        and receipt.compiled_effect_id == pending.compiled_effect_id
        and receipt.compiled_effect_digest == pending.compiled_effect_digest
        and pending.receipt_requirement is not None
        and receipt.component is pending.receipt_requirement.component
        and receipt.component_id == pending.receipt_requirement.component_id
        and receipt.component_digest == pending.receipt_requirement.component_digest
        and receipt.cue_digest == pending.receipt_requirement.cue_digest
        and receipt.outcome == "complete"
    )
    if not exact:
        return Reduction(state, ResultCode.REJECTED, explanation="receipt scope/version/grant/action/epoch mismatch")
    accepted_receipts = (state.receipt_ids + (receipt.receipt_id,))[-64:]
    if receipt.kind is ReceiptKind.OFFER_PRESENTED:
        if receipt.offer_id != pending.offer_id or state.node is not StoryNode.CAFE_CHAT:
            return Reduction(state, ResultCode.REJECTED, explanation="offer presentation receipt mismatch")
        updated = replace(state, node=StoryNode.AWAIT_RAIN_CHOICE, offer_status=OfferStatus.PRESENTED,
                          pending=None, receipt_ids=accepted_receipts, revision=state.revision + 1)
        return Reduction(updated, ResultCode.RECEIPT_ACCEPTED,
                         explanation="software/client-reported cue presentation acknowledged; no human-heard claim")
    if receipt.kind is ReceiptKind.SCENE_COMPLETED:
        if (state.node is not StoryNode.AWAIT_RAIN_CHOICE
                or state.active_offer_capability != "cafe.scene.rain_window"
                or receipt.offer_id != pending.offer_id
                or receipt.capability_revision != pending.capability_revision):
            return Reduction(state, ResultCode.REJECTED, explanation="scene receipt does not match the admitted invitation")
        episode = EpisodeCandidate(
            candidate_id=f"episode.rain_window:{receipt.receipt_id}",
            event_code="cafe_rain_window_presented", receipt_id=receipt.receipt_id,
            compiled_effect_id=receipt.compiled_effect_id, compiled_effect_digest=receipt.compiled_effect_digest,
            component_id=receipt.component_id, component_digest=receipt.component_digest,
            evidence=receipt.evidence, story_id=state.story_id,
            graph_revision=state.graph_revision, canon_revision=state.canon_revision,
            character_state=(("scene_after", "rain_window"), ("offer_id", receipt.offer_id or ""),
                             ("asset_revision", receipt.capability_revision or "")))
        return Reduction(replace(state, node=StoryNode.RAIN_VIEW, pending=None,
            receipt_ids=accepted_receipts, episodes=(state.episodes + (episode,))[-32:],
            revision=state.revision + 1), ResultCode.RECEIPT_ACCEPTED,
            explanation="qualified software scene presentation; no physical movement claim")
    if receipt.kind is ReceiptKind.WARDROBE_COMPLETED:
        if (state.node is not StoryNode.RAINCOAT_PENDING
                or receipt.offer_id != pending.offer_id
                or receipt.before_outfit != state.current_outfit
                or receipt.after_outfit != "amber_raincoat"
                or receipt.capability_revision != pending.capability_revision):
            return Reduction(state, ResultCode.REJECTED, explanation="wardrobe completion payload is not the admitted exact change")
        episode = EpisodeCandidate(
            candidate_id=f"episode.wardrobe_change:{receipt.receipt_id}",
            event_code="mira_amber_raincoat_presented",
            receipt_id=receipt.receipt_id,
            compiled_effect_id=receipt.compiled_effect_id,
            compiled_effect_digest=receipt.compiled_effect_digest,
            component_id=receipt.component_id,
            component_digest=receipt.component_digest,
            evidence=receipt.evidence,
            story_id=state.story_id,
            graph_revision=state.graph_revision,
            canon_revision=state.canon_revision,
            character_state=(("outfit_before", receipt.before_outfit or ""),
                             ("outfit_after", receipt.after_outfit or ""),
                             ("offer_id", receipt.offer_id or "")),
        )
        updated = replace(state, node=StoryNode.RAIN_VIEW, current_outfit="amber_raincoat",
                          last_acknowledged_outfit="amber_raincoat",
                          pending=None, receipt_ids=accepted_receipts,
                          episodes=(state.episodes + (episode,))[-32:], revision=state.revision + 1)
        return Reduction(updated, ResultCode.RECEIPT_ACCEPTED,
                         explanation="qualified fictional character-state candidate; not user history")
    return Reduction(state, ResultCode.REJECTED, explanation="unsupported receipt kind")


@dataclass(frozen=True, slots=True)
class AffectTurn:
    input_id: str
    signal: AffectSignal
    reliable: bool = True
    specific_notice: bool = False

    def __post_init__(self) -> None:
        _bounded_text(self.input_id, "affect input ID", 128)
        if not isinstance(self.signal, AffectSignal):
            raise ValueError("affect signal must be a fixed typed label")
        _exact_bool(self.reliable, "affect evidence reliability")
        _exact_bool(self.specific_notice, "specific notice evidence")


@dataclass(frozen=True, slots=True)
class AffectProposal:
    candidate: Affect
    signal: AffectSignal
    evidence_input_ids: tuple[str, ...]
    canon_reason_id: str | None = None
    optional_alternative: Affect | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, Affect) or not isinstance(self.signal, AffectSignal):
            raise ValueError("affect proposal candidate/signal must be fixed typed labels")
        if self.canon_reason_id is not None:
            _bounded_text(self.canon_reason_id, "affect canon reason", 128)
        if len(self.evidence_input_ids) > 4 or len(set(self.evidence_input_ids)) != len(self.evidence_input_ids):
            raise ValueError("affect proposal evidence must be unique and bounded to four IDs")
        if any(not x or len(x) > 128 for x in self.evidence_input_ids):
            raise ValueError("affect evidence IDs must be bounded opaque IDs")
        if self.optional_alternative is not None and not isinstance(self.optional_alternative, Affect):
            raise ValueError("optional affect alternative must be a fixed label")


ALLOWED_AFFECT_PROPOSAL_FIELDS = frozenset({"candidate", "signal", "canon_reason_id"})


def parse_affect_proposal(payload: object, *, trusted_evidence_ids: tuple[str, ...],
                          approved_canon_ids: tuple[str, ...]) -> AffectProposal:
    """Parse only candidate labels; server stamps vetted evidence IDs and no score."""
    if not isinstance(payload, dict) or set(payload) - ALLOWED_AFFECT_PROPOSAL_FIELDS:
        raise ValueError("affect proposal accepts only candidate, signal, and optional canon_reason_id")
    if not isinstance(payload.get("candidate"), str) or not isinstance(payload.get("signal"), str):
        raise ValueError("affect proposal requires typed candidate and signal labels")
    try:
        candidate = Affect(payload["candidate"])
        signal = AffectSignal(payload["signal"])
    except ValueError as exc:
        raise ValueError("affect candidate/signal is not allowlisted") from exc
    reason = payload.get("canon_reason_id")
    if reason is not None and (not isinstance(reason, str) or reason not in approved_canon_ids):
        raise ValueError("affect canon reason must reference selected canon")
    if candidate is Affect.SHY and reason != "canon.shy_response":
        raise ValueError("shy proposal requires selected canon.shy_response")
    evidence = tuple(trusted_evidence_ids[-4:])
    if len(set(evidence)) != len(evidence) or any(not isinstance(x, str) or not x or len(x) > 128 for x in evidence):
        raise ValueError("trusted affect evidence IDs are invalid")
    return AffectProposal(candidate, signal, evidence, reason)


def affect_turn_from_jev(input_id: str, signal: AffectSignal, *,
                         sufficient_evidence: bool, specific_notice: bool = False) -> AffectTurn:
    """Map a JEV-approved typed signal into affect evidence, never a model score."""
    if not input_id or len(input_id) > 128 or not isinstance(signal, AffectSignal):
        raise ValueError("JEV affect observation requires a bounded ID and fixed signal")
    if type(sufficient_evidence) is not bool or type(specific_notice) is not bool:
        raise ValueError("JEV support and specific-notice values must be booleans")
    if not sufficient_evidence:
        return AffectTurn(input_id, AffectSignal.UNCERTAIN, reliable=False)
    return AffectTurn(input_id, signal, reliable=True, specific_notice=specific_notice)


@dataclass(frozen=True, slots=True)
class AffectState:
    story_id: str
    canon_revision: int
    emotion: Affect = Affect.NORMAL
    recent_turns: tuple[AffectTurn, ...] = ()
    seen_input_ids: tuple[str, ...] = ()
    unknown_streak: int = 0
    neutral_streak: int = 0
    shy_cue_remaining: int = 0
    smoothing_level: int = 0
    boundary_active: bool = False
    revision: int = 0

    def __post_init__(self) -> None:
        _bounded_text(self.story_id, "affect story ID", 128)
        _revision(self.canon_revision, "affect canon revision")
        _revision(self.revision, "affect state revision", allow_zero=True)
        if not isinstance(self.emotion, Affect) or not isinstance(self.recent_turns, tuple) or len(self.recent_turns) > 4:
            raise ValueError("affect state must contain fixed emotion and at most four immutable turns")
        if any(not isinstance(turn, AffectTurn) for turn in self.recent_turns):
            raise ValueError("affect turns must use fixed typed DTOs")
        if len({turn.input_id for turn in self.recent_turns}) != len(self.recent_turns):
            raise ValueError("affect turn IDs must be distinct")
        if (not isinstance(self.seen_input_ids, tuple) or len(self.seen_input_ids) > 64
                or len(set(self.seen_input_ids)) != len(self.seen_input_ids)
                or any(not isinstance(value, str) or not value or len(value) > 128 for value in self.seen_input_ids)):
            raise ValueError("affect duplicate-input ledger must be a bounded unique ID tuple")
        if not set(turn.input_id for turn in self.recent_turns).issubset(self.seen_input_ids):
            raise ValueError("recent affect evidence must be included in duplicate-input ledger")
        for field in (self.unknown_streak, self.neutral_streak, self.shy_cue_remaining, self.smoothing_level):
            _revision(field, "affect hysteresis counter", allow_zero=True)
        _exact_bool(self.boundary_active, "affect boundary state")

    @classmethod
    def initial(cls, definition: StoryDefinition) -> AffectState:
        return cls(story_id=definition.graph.story_id, canon_revision=definition.canon.revision)


def reduce_affect(state: AffectState, turn: AffectTurn, proposal: AffectProposal | None,
                  definition: StoryDefinition) -> AffectState:
    """Independent affect lane; story choice/progress is never an input."""
    if state.story_id != definition.graph.story_id or state.canon_revision != definition.canon.revision:
        return state
    if not turn.input_id or turn.input_id in state.seen_input_ids:
        return state
    seen = (state.seen_input_ids + (turn.input_id,))[-64:]
    if not turn.reliable or turn.signal is AffectSignal.UNCERTAIN:
        streak = state.unknown_streak + 1
        emotion = Affect.NORMAL if streak >= 2 and state.emotion is not Affect.GUARDED else state.emotion
        return replace(state, emotion=emotion, unknown_streak=streak, seen_input_ids=seen,
                      neutral_streak=0, smoothing_level=max(0, state.smoothing_level - 1),
                      shy_cue_remaining=max(0, state.shy_cue_remaining - 1), revision=state.revision + 1)
    recent = (state.recent_turns + (turn,))[-4:]
    # JEV-approved evidence owns the current signal; an LLM proposal cannot
    # strengthen or relabel it, even when it includes a model-generated score.
    signal = turn.signal
    record = replace(turn, signal=signal)
    recent = (state.recent_turns + (record,))[-4:]
    unique = {item.input_id: item for item in recent if item.reliable}
    rows = tuple(unique.values())
    boundary_n = sum(item.signal is AffectSignal.BOUNDARY_PRESSURE for item in rows)
    warm_n = sum(item.signal in {AffectSignal.PLEASANT_SHARED_ATTENTION, AffectSignal.COMFORTABLE_HUMOR} for item in rows)
    personal_n = sum(item.signal is AffectSignal.PERSONAL_ATTENTION for item in rows)
    specific_n = sum(item.signal is AffectSignal.PERSONAL_ATTENTION and item.specific_notice for item in rows)
    neutral = signal in {AffectSignal.NEUTRAL, AffectSignal.REPAIR}
    neutral_streak = state.neutral_streak + 1 if neutral else 0
    boundary_active = state.boundary_active
    if signal is AffectSignal.REPAIR:
        boundary_active = False
    emotion = state.emotion
    cue = max(0, state.shy_cue_remaining - 1)
    if signal is AffectSignal.REPAIR:
        emotion, boundary_active, cue = Affect.NORMAL, False, 0
    elif boundary_n >= 2:
        emotion, boundary_active, cue = Affect.GUARDED, True, 0
    elif (state.emotion in {Affect.HAPPY, Affect.SHY} and signal is AffectSignal.BOUNDARY_PRESSURE):
        # A single fresh boundary signal is enough to stop escalation immediately.
        emotion, boundary_active, cue = Affect.GUARDED, True, 0
    elif (proposal is not None and proposal.candidate is Affect.SHY
          and proposal.canon_reason_id == "canon.shy_response" and proposal.signal is AffectSignal.PERSONAL_ATTENTION
          and state.emotion in {Affect.HAPPY, Affect.SHY} and personal_n >= 2 and specific_n >= 1
          and boundary_n == 0):
        cited = set(proposal.evidence_input_ids)
        if (turn.input_id in cited
                and len(cited.intersection(item.input_id for item in rows if item.signal is AffectSignal.PERSONAL_ATTENTION)) >= 2):
            emotion, cue = Affect.SHY, 1
    elif warm_n >= 2 and boundary_n == 0 and (proposal is None or proposal.candidate in {Affect.HAPPY, Affect.NORMAL}):
        emotion = Affect.HAPPY
    elif state.emotion is Affect.GUARDED and neutral_streak >= 2:
        emotion, boundary_active = Affect.NORMAL, False
    elif state.emotion is Affect.HAPPY and neutral_streak >= 2:
        emotion = Affect.NORMAL
    elif state.emotion is Affect.SHY and cue == 0:
        emotion = Affect.HAPPY if warm_n >= 2 else Affect.NORMAL
    return replace(state, emotion=emotion, recent_turns=recent, seen_input_ids=seen, unknown_streak=0,
                  neutral_streak=neutral_streak, shy_cue_remaining=cue,
                  smoothing_level=min(2, state.smoothing_level + (1 if emotion is not state.emotion else 0)),
                  boundary_active=boundary_active, revision=state.revision + 1)


@dataclass(frozen=True, slots=True)
class StoryContextProjection:
    """One version-bound immutable projection shared by generation and JEV."""
    projection_id: str
    story_id: str
    graph_id: str
    graph_revision: int
    graph_hash: str
    canon_revision: int
    canon_hash: str
    canon_entry_ids: tuple[str, ...]
    canon_text: tuple[tuple[str, str], ...]
    canon_provenance: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...], int, str, str | None], ...]
    node: StoryNode
    offer_status: OfferStatus
    active_offer_id: str | None
    pending_transition_id: str | None
    outfit: str
    affect: Affect
    affect_revision: int
    state_revision: int
    scope_binding_hash: str
    acknowledged_presentations: tuple[EpisodeCandidate, ...]
    context_json: str
    last_acknowledged_outfit: str | None = None
    last_acknowledged_accessory: str | None = None
    last_acknowledged_emotion: str | None = None
    known_canon: tuple[CanonEntry, ...] = ()
    released_story_events: tuple[str, ...] = ()
    output_epoch: int = 0
    reentry_label: str = "session_state_only"
    active_offer_capability: str | None = None
    active_offer_cue: str | None = None
    chapter: ChapterState = ChapterState()


def _acknowledged_scene(episodes):
    return next((dict(item.character_state)["scene_after"] for item in reversed(episodes)
                 if item.event_code == "cafe_rain_window_presented" and dict(item.character_state).get("scene_after") == "rain_window"), None)


def project_shared_context(state: StoryState, affect: AffectState, definition: StoryDefinition) -> StoryContextProjection:
    if not _compatible(state, definition) or affect.story_id != state.story_id or affect.canon_revision != state.canon_revision:
        raise ValueError("story/affect/canon versions must match before projection")
    if not state.scope_id:
        raise ValueError("context projection is server-scope bound")
    scope_hash = hashlib.sha256(("mira.story.scope.v1:" + state.scope_id).encode()).hexdigest()
    visible_entries = tuple(entry for entry in definition.canon.entries
                            if entry.release_event_id is None
                            or (entry.release_event_id in state.released_story_events
                                and entry.release_event_id in _CANON_RELEASE_OVERRIDES.values()))
    canon_rows = tuple((entry.entry_id, entry.first_person_text or entry.text) for entry in visible_entries)
    provenance_rows = tuple((entry.entry_id, entry.status, entry.source_status, entry.source,
                             entry.author_created, entry.approval_basis,
                             entry.source_refs, entry.source_version, entry.disclosure_level,
                             entry.release_event_id) for entry in visible_entries)
    # Keep durable/bounded state intact while limiting repeated model context.
    # Appearance slots preserve older last-acknowledged controls independently.
    acknowledged = state.episodes[-8:]
    view = {
        "schema": "mira.story-context-projection.v3",
        "story_id": state.story_id,
        "graph_id": state.graph_id,
        "graph_revision": state.graph_revision,
        "graph_hash": definition.graph.content_hash,
        "canon_revision": state.canon_revision,
        "canon_hash": definition.canon.content_hash,
        "approved_canon": [{"id": entry.entry_id, "status": entry.status,
                            "source_status": entry.source_status, "source": entry.source,
                            "author_created": entry.author_created, "source_refs": list(entry.source_refs),
                            "source_revision": entry.source_version, "approval_basis": entry.approval_basis,
                            "disclosure_level": entry.disclosure_level,
                            "release_event_id": entry.release_event_id,
                            "text": entry.first_person_text or entry.text}
                            for entry in visible_entries],
        "node": state.node.value,
        "offer_status": state.offer_status.value,
        "active_offer_id": state.active_offer_id,
        "active_offer_capability": state.active_offer_capability if state.active_offer_id else None,
        "active_offer_cue": state.active_offer_cue if state.active_offer_id else None,
        "last_acknowledged_scene": _acknowledged_scene(acknowledged),
        "scene_scope": "historical_software_presentation_not_current_browser_restoration",
        "pending_transition_id": state.pending.transition_id if state.pending else None,
        "outfit": state.current_outfit,
        "last_acknowledged_appearance": {
            "outfit": state.last_acknowledged_outfit,
            "accessory": state.last_acknowledged_accessory,
            "emotion": state.last_acknowledged_emotion,
        },
        "appearance_scope": "historical_software_presentation_not_current_browser_restoration",
        "appearance_restoration_acknowledged": False,
        "relationship_delta": state.relationship_delta,
        "affect_visual_status": "internal_state_not_render_acknowledged",
        "readiness_scope": "software_asset_availability_not_human_perception",
        "affect": affect.emotion.value,
        "affect_revision": affect.revision,
        "state_revision": state.revision,
        "acknowledged_presentations": [_episode_projection_row(item) for item in acknowledged],
        "acknowledged_presentations_scope": "recent_bounded_history_not_complete_archive",
        "acknowledged_presentations_omitted": len(state.episodes) - len(acknowledged),
        "scope_binding_hash": scope_hash,
        "first_person_memory": first_person_story_memory(
            entries=definition.canon.entries, episodes=acknowledged,
            binding={"story_id": state.story_id, "graph_revision": state.graph_revision,
                "canon_revision": state.canon_revision, "canon_hash": state.canon_hash,
                "graph_hash": state.graph_hash, "state_revision": state.revision,
                "scope_binding_hash": scope_hash, "output_epoch": state.epoch},
            node=state.node.value, offer_status=state.offer_status.value,
            epoch=state.epoch, reentry_label=state.reentry_label,
            released_events=state.released_story_events, chapter=state.chapter),
        "constraints": [
            "fictional_character_state_only",
            "no_user_fact_inference_from_fiction",
            "no_claim_of_physical_action_or_human_hearing",
            "future_story_nodes_are_not_history",
            "NO_choice_has_zero_relationship_delta",
            "UNKNOWN_holds_current_node",
            "affect_is_internal_not_visual_receipt",
            "readiness_is_software_availability_only",
            "qualified_character_presentations_only",
        ],
    }
    if not chapter_is_dormant(state.chapter):
        view["chapter"] = chapter_projection(state.chapter)
    encoded = json.dumps(view, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    return StoryContextProjection(
        projection_id="storyctx." + digest,
        story_id=state.story_id, graph_id=state.graph_id, graph_revision=state.graph_revision,
        graph_hash=definition.graph.content_hash, canon_revision=state.canon_revision,
        canon_hash=definition.canon.content_hash,
        canon_entry_ids=tuple(i for i, _ in canon_rows), canon_text=canon_rows,
        canon_provenance=provenance_rows,
        node=state.node, offer_status=state.offer_status, active_offer_id=state.active_offer_id,
        pending_transition_id=state.pending.transition_id if state.pending else None,
        outfit=state.current_outfit, affect=affect.emotion, affect_revision=affect.revision,
        state_revision=state.revision, scope_binding_hash=scope_hash,
        acknowledged_presentations=acknowledged, context_json=encoded,
        last_acknowledged_outfit=state.last_acknowledged_outfit,
        last_acknowledged_accessory=state.last_acknowledged_accessory,
        last_acknowledged_emotion=state.last_acknowledged_emotion,
        chapter=state.chapter, known_canon=definition.canon.entries, released_story_events=state.released_story_events,
        output_epoch=state.epoch, reentry_label=state.reentry_label,
        active_offer_capability=state.active_offer_capability if state.active_offer_id else None,
        active_offer_cue=state.active_offer_cue if state.active_offer_id else None,
    )


def _episode_projection_row(item: EpisodeCandidate) -> dict[str, Any]:
    return {
        "candidate_id": item.candidate_id,
        "event_code": item.event_code,
        "receipt_id": item.receipt_id,
        "compiled_effect_id": item.compiled_effect_id,
        "compiled_effect_digest": item.compiled_effect_digest,
        "component_id": item.component_id,
        "component_digest": item.component_digest,
        "evidence": item.evidence.value,
        "story_id": item.story_id,
        "graph_revision": item.graph_revision,
        "canon_revision": item.canon_revision,
        "character_state": [list(row) for row in item.character_state],
        "claim_boundary": list(item.claim_boundary),
        "status": item.status,
    }


class StaleStoryProjection(ValueError):
    """Raised when a projected context no longer matches live story/affect state."""


def validate_projection_current(projection: StoryContextProjection, state: StoryState,
                                affect: AffectState, definition: StoryDefinition) -> bool:
    """Validate that an exact prior projection still names the current snapshot."""
    if not valid_story_projection(projection):
        raise StaleStoryProjection("story projection is malformed or hash-invalid")
    current = project_shared_context(state, affect, definition)
    if projection.projection_id != current.projection_id or projection.context_json != current.context_json:
        raise StaleStoryProjection("story/affect/canon projection is stale")
    return True


_PROJECTION_KEYS = frozenset({
    "schema", "story_id", "graph_id", "graph_revision", "graph_hash", "canon_revision", "canon_hash",
    "approved_canon", "node", "offer_status", "active_offer_id", "pending_transition_id",
    "outfit", "relationship_delta", "affect", "affect_revision", "state_revision",
    "scope_binding_hash", "constraints", "affect_visual_status", "readiness_scope",
    "acknowledged_presentations", "last_acknowledged_appearance", "appearance_scope",
    "appearance_restoration_acknowledged", "acknowledged_presentations_scope",
    "acknowledged_presentations_omitted", "first_person_memory",
    "active_offer_capability", "active_offer_cue", "last_acknowledged_scene", "scene_scope",
})
_PROJECTION_CONSTRAINTS = frozenset({
    "fictional_character_state_only", "no_user_fact_inference_from_fiction",
    "no_claim_of_physical_action_or_human_hearing", "future_story_nodes_are_not_history",
    "NO_choice_has_zero_relationship_delta", "UNKNOWN_holds_current_node",
    "affect_is_internal_not_visual_receipt", "readiness_is_software_availability_only",
    "qualified_character_presentations_only",
})
_MAX_PROJECTION_BYTES = 32768


def valid_story_projection(projection: object) -> bool:
    """Validate an untrusted/forged DTO before generation/review serialization.

    This checks structure, canonical JSON, hash, and mirrored DTO fields. It does
    not establish freshness; call `validate_projection_current` with live state
    for that stronger check.
    """
    if not isinstance(projection, StoryContextProjection):
        return False
    try:
        encoded = projection.context_json
        if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > _MAX_PROJECTION_BYTES:
            return False
        def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = value
            return result
        view = json.loads(encoded, object_pairs_hook=no_duplicate_keys)
        if not isinstance(view, dict) or set(view) not in (_PROJECTION_KEYS, _PROJECTION_KEYS | {"chapter"}):
            return False
        if json.dumps(view, sort_keys=True, separators=(",", ":"), ensure_ascii=False) != encoded:
            return False
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        if projection.projection_id != "storyctx." + digest:
            return False
        if not _is_sha256(projection.graph_hash) or view["graph_hash"] != projection.graph_hash:
            return False
        if not _is_sha256(projection.canon_hash) or view["canon_hash"] != projection.canon_hash:
            return False
        if not _is_sha256(projection.scope_binding_hash) or view["scope_binding_hash"] != projection.scope_binding_hash:
            return False
        if "scope_id" in view or not isinstance(view["story_id"], str) or not view["story_id"]:
            return False
        if type(projection.chapter) is not ChapterState:
            return False
        if chapter_is_dormant(projection.chapter):
            if "chapter" in view:
                return False
        elif view.get("chapter") != chapter_projection(projection.chapter):
            return False
        if view["schema"] != "mira.story-context-projection.v3":
            return False
        if view["graph_revision"] != projection.graph_revision or view["canon_revision"] != projection.canon_revision:
            return False
        if view["node"] != projection.node.value or view["offer_status"] != projection.offer_status.value:
            return False
        if view["active_offer_id"] != projection.active_offer_id or view["outfit"] != projection.outfit:
            return False
        if (view["active_offer_capability"] != projection.active_offer_capability
                or view["active_offer_cue"] != projection.active_offer_cue
                or projection.active_offer_capability not in {None, "mira.outfit.amber_raincoat", "cafe.scene.rain_window"}
                or (projection.active_offer_cue is not None and (not isinstance(projection.active_offer_cue, str) or len(projection.active_offer_cue) > 500))
                or view["last_acknowledged_scene"] != _acknowledged_scene(projection.acknowledged_presentations)
                or view["scene_scope"] != "historical_software_presentation_not_current_browser_restoration"):
            return False
        if view["affect"] != projection.affect.value or view["affect_revision"] != projection.affect_revision:
            return False
        if view["state_revision"] != projection.state_revision or view["pending_transition_id"] != projection.pending_transition_id:
            return False
        if view["story_id"] != projection.story_id or view["graph_id"] != projection.graph_id:
            return False
        if (type(projection.graph_revision) is not int or projection.graph_revision < 1
                or type(projection.canon_revision) is not int or projection.canon_revision < 1
                or type(projection.state_revision) is not int or projection.state_revision < 0
                or type(projection.affect_revision) is not int or projection.affect_revision < 0):
            return False
        if projection.node not in StoryNode or projection.offer_status not in OfferStatus or projection.affect not in Affect:
            return False
        if projection.outfit not in {"black_jacket", "cream_inner_only", "amber_raincoat"}:
            return False
        if view["last_acknowledged_appearance"] != {
                "outfit": projection.last_acknowledged_outfit,
                "accessory": projection.last_acknowledged_accessory,
                "emotion": projection.last_acknowledged_emotion}:
            return False
        if (projection.last_acknowledged_outfit not in {None, "black_jacket", "cream_inner_only", "amber_raincoat"}
                or projection.last_acknowledged_accessory not in {None, "camera_clip", "star_clip"}
                or projection.last_acknowledged_emotion not in {None, "normal", "guarded", "happy", "shy"}):
            return False
        if (view["appearance_scope"] != "historical_software_presentation_not_current_browser_restoration"
                or view["appearance_restoration_acknowledged"] is not False):
            return False
        if (view["acknowledged_presentations_scope"] != "recent_bounded_history_not_complete_archive"
                or type(view["acknowledged_presentations_omitted"]) is not int
                or not 0 <= view["acknowledged_presentations_omitted"] <= 24
                or len(projection.acknowledged_presentations) > 8):
            return False
        if view["relationship_delta"] != 0:
            return False
        if set(view["constraints"]) != _PROJECTION_CONSTRAINTS:
            return False
        rows = view["approved_canon"]
        if not isinstance(rows, list) or len(rows) > 32:
            return False
        if view["affect_visual_status"] != "internal_state_not_render_acknowledged" or view["readiness_scope"] != "software_asset_availability_not_human_perception":
            return False
        ids: list[str] = []
        text: list[tuple[str, str]] = []
        provenance: list[tuple[str, str, str, str, bool, str, tuple[str, ...], int, str, str | None]] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"id", "status", "source_status", "source", "author_created", "source_refs", "source_revision", "approval_basis", "disclosure_level", "release_event_id", "text"}:
                return False
            if (row["status"] not in {"inherited_canonical", "current_brief_constraint", "approved_author_canon"}
                    or row["source"] != "authored_backstory" or row["author_created"] is not True):
                return False
            if row["status"] == "approved_author_canon" and (row["source_status"] != "author_draft"
                    or row["approval_basis"] != "explicit_composition_selection"):
                return False
            if row["status"] == "inherited_canonical" and (row["source_status"] != "inherited_canonical"
                    or row["approval_basis"] != "inherited_source"):
                return False
            if not isinstance(row["id"], str) or not row["id"] or not isinstance(row["text"], str) or len(row["text"]) > 4000:
                return False
            if not isinstance(row["source_refs"], list) or len(row["source_refs"]) > 16 or any(not isinstance(x, str) for x in row["source_refs"]):
                return False
            if not isinstance(row["source_revision"], int) or isinstance(row["source_revision"], bool) or row["source_revision"] < 1:
                return False
            if row["disclosure_level"] not in {"public", "private_until_invited"}:
                return False
            if row["release_event_id"] is not None and row["release_event_id"] not in _CANON_RELEASE_OVERRIDES.values():
                return False
            ids.append(row["id"])
            text.append((row["id"], row["text"]))
            provenance.append((row["id"], row["status"], row["source_status"], row["source"], True,
                               row["approval_basis"], tuple(row["source_refs"]), row["source_revision"],
                               row["disclosure_level"], row["release_event_id"]))
        if len(ids) != len(set(ids)) or tuple(ids) != projection.canon_entry_ids:
            return False
        if tuple(text) != projection.canon_text or tuple(provenance) != projection.canon_provenance:
            return False
        if (type(projection.known_canon) is not tuple or len(projection.known_canon) > 32
                or any(type(entry) is not CanonEntry for entry in projection.known_canon)
                or type(projection.output_epoch) is not int or projection.output_epoch < 0
                or projection.reentry_label not in {"session_state_only", "qualified_character_presentation_history"}
                or type(projection.released_story_events) is not tuple
                or any(event not in _CANON_RELEASE_OVERRIDES.values() for event in projection.released_story_events)):
            return False
        visible = tuple(entry for entry in projection.known_canon if entry.release_event_id is None
            or entry.release_event_id in projection.released_story_events)
        if tuple((entry.entry_id, entry.first_person_text or entry.text) for entry in visible) != projection.canon_text:
            return False
        expected_memory = first_person_story_memory(
            entries=projection.known_canon, episodes=projection.acknowledged_presentations,
            binding={"story_id": projection.story_id, "graph_revision": projection.graph_revision,
                "canon_revision": projection.canon_revision, "canon_hash": projection.canon_hash,
                "graph_hash": projection.graph_hash, "state_revision": projection.state_revision,
                "scope_binding_hash": projection.scope_binding_hash, "output_epoch": projection.output_epoch},
            node=projection.node.value, offer_status=projection.offer_status.value,
            epoch=projection.output_epoch, reentry_label=projection.reentry_label,
            released_events=projection.released_story_events, chapter=projection.chapter)
        if view["first_person_memory"] != expected_memory:
            return False
        rows = view["acknowledged_presentations"]
        if not isinstance(rows, list) or len(rows) > 32:
            return False
        if (not isinstance(projection.acknowledged_presentations, tuple)
                or len(projection.acknowledged_presentations) > 32
                or any(not isinstance(item, EpisodeCandidate) for item in projection.acknowledged_presentations)):
            return False
        if rows != [_episode_projection_row(item) for item in projection.acknowledged_presentations]:
            return False
        return True
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeError):
        return False


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
