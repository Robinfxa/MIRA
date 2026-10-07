from __future__ import annotations

import json
import hashlib
from dataclasses import replace
from pathlib import Path
import pytest

from mira.domain.story import (
    Affect, AffectProposal, AffectSignal, AffectTurn, CapabilityRecord,
    CapabilityState, EvidenceLabel, JevEvidence, OfferStatus, PresentationReceipt,
    ProposalSignal, ReadinessCatalog, Relevance, ReceiptKind, ReceiptComponent, ReceiptRequirement, ResultCode,
    StoryNode, StoryProposal, StoryTurn, Stop, Will, parse_story_proposal, bind_compiled_effect,
    definition_from_documents, project_shared_context, reduce_affect, reduce_story,
    validate_projection_current, StaleStoryProjection, begin_story_input, valid_story_projection,
    AffectState, parse_affect_proposal, affect_turn_from_jev,
)
from mira.adapters.memory.story import (
    ScopeMismatch, StoryCheckpointStore, StoreDisabled, Tombstoned, VersionMismatch,
)
from mira.application.story import RuntimeSnapshot, StoryRuntime

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "tests" / "fixtures" / "story"
GRAPH_DOC = json.loads((PACKAGE / "story-graph.json").read_text())
SEED_DOC = json.loads((PACKAGE / "mira.story-seed.v1.json").read_text())


@pytest.fixture
def definition():
    return definition_from_documents(GRAPH_DOC, SEED_DOC)


def catalog_ready():
    return ReadinessCatalog("catalog-raincoat-v1", (
        CapabilityRecord("mira.outfit.amber_raincoat", CapabilityState.READY,
                         "asset-raincoat-v3", ("outer.amber", "inner.cream"), "asset-audit-7"),
    ))


def new_story(definition, scope="scope-A"):
    return StoryRuntime(definition, scope).story


def offer_turn(story, definition, *, input_id="input.offer", epoch=1):
    proposal = StoryProposal("t.offer", ProposalSignal.OFFER_RAIN, input_id, epoch, "offer-1",
                             draft_cue="雨变细了。我想披上那件琥珀色雨衣，在窗边看一会儿。你想一起看吗？")
    jev = JevEvidence(input_id, epoch, None, Will.UNKNOWN, Relevance.RELEVANT)
    return bind_staged(reduce_story(story, StoryTurn(input_id, epoch, proposal, jev, ReadinessCatalog("empty"), True), definition))


def bind_staged(result, *, component=ReceiptComponent.SUBTITLE):
    assert result.effect_plan is not None
    plan = result.effect_plan
    effect_id = f"compiled.{plan.grant_id}"
    effect_digest = hashlib.sha256(effect_id.encode()).hexdigest()
    if plan.transition_id == "t.offer":
        cue_digest = plan.draft_cue_digest
        requirement = ReceiptRequirement(component, effect_id,
            cue_digest if component is ReceiptComponent.SUBTITLE else hashlib.sha256(b"exact-reviewed-speech").hexdigest(),
            cue_digest)
        actual_cue = cue_digest
    else:
        cue_digest = plan.draft_cue_digest
        requirement = ReceiptRequirement(ReceiptComponent.WARDROBE, effect_id, effect_digest, cue_digest)
        actual_cue = cue_digest
    state, bound = bind_compiled_effect(result.state, plan, compiled_effect_id=effect_id,
                                       compiled_effect_digest=effect_digest,
                                       requirement=requirement, actual_cue_digest=actual_cue)
    return replace(result, state=state, effect_plan=bound)


def offer_receipt(plan, *, scope="scope-A", graph=1, canon=1, receipt_id="receipt.offer"):
    requirement = plan.receipt_requirement
    return PresentationReceipt(receipt_id, scope, plan.story_id, graph, canon, plan.epoch,
                               plan.grant_id, plan.transition_id, ReceiptKind.OFFER_PRESENTED,
                               EvidenceLabel.CLIENT_REPORT, "complete", offer_id=plan.offer_id,
                               compiled_effect_id=plan.compiled_effect_id,
                               compiled_effect_digest=plan.compiled_effect_digest,
                               component=requirement.component, component_id=requirement.component_id,
                               component_digest=requirement.component_digest, cue_digest=requirement.cue_digest)


def wardrobe_receipt(plan, *, scope="scope-A", graph=1, canon=1, receipt_id="receipt.wardrobe",
                    offer_id="offer-1", before="black_jacket", after="amber_raincoat", capability_revision="asset-raincoat-v3"):
    requirement = plan.receipt_requirement
    return PresentationReceipt(receipt_id, scope, plan.story_id, graph, canon, plan.epoch,
        plan.grant_id, plan.transition_id, ReceiptKind.WARDROBE_COMPLETED, EvidenceLabel.SOFTWARE,
        "complete", offer_id, before, after, capability_revision,
        compiled_effect_id=plan.compiled_effect_id, compiled_effect_digest=plan.compiled_effect_digest,
        component=requirement.component, component_id=requirement.component_id,
        component_digest=requirement.component_digest, cue_digest=requirement.cue_digest)


def yes_turn(story, definition, *, input_id="input.yes", epoch=2, readiness=None):
    p = StoryProposal("t.yes", ProposalSignal.ACCEPT_RAINCOAT, input_id, epoch,
                      story.active_offer_id, ("mira.outfit.amber_raincoat",))
    j = JevEvidence(input_id, epoch, story.active_offer_id, Will.YES, Relevance.RELEVANT)
    result = reduce_story(story, StoryTurn(input_id, epoch, p, j, readiness or catalog_ready(), True), definition)
    return bind_staged(result) if result.effect_plan is not None else result


def test_authored_package_only_projects_selected_canon_and_four_node_graph(definition):
    assert tuple(n.value for n in definition.graph.nodes) == (
        "cafe_chat", "await_rain_choice", "raincoat_pending", "rain_view")
    assert {entry.status for entry in definition.canon.entries} == {"inherited_canonical"}
    assert set(definition.canon.proposal_ids) == {
        row["id"] for row in SEED_DOC["canonical_fiction"] if row["status"] == "author_draft"
    }
    assert all(not entry.is_user_fact and not entry.is_shared_experience for entry in definition.canon.entries)
    chosen = definition_from_documents(GRAPH_DOC, SEED_DOC, approved_canon_ids=("canon.identity", "canon.layers"))
    assert {entry.entry_id for entry in chosen.canon.entries} == {"canon.identity", "canon.layers"}
    approved = definition_from_documents(GRAPH_DOC, SEED_DOC,
        approved_canon_ids=("canon.identity", "canon.attention", "canon.shy_response"))
    by_id = {entry.entry_id: entry for entry in approved.canon.entries}
    assert by_id["canon.attention"].status == "approved_author_canon"
    assert by_id["canon.attention"].source_status == "author_draft"
    assert by_id["canon.attention"].source_version == SEED_DOC["version"]
    assert by_id["canon.attention"].approval_basis == "explicit_composition_selection"
    assert "canon.attention" not in approved.canon.proposal_ids
    with pytest.raises(ValueError):
        definition_from_documents(GRAPH_DOC, SEED_DOC, approved_canon_ids=("canon.not-a-canon",))


def test_offer_advances_only_after_exact_presentation_receipt(definition):
    state = new_story(definition)
    staged = offer_turn(state, definition)
    assert staged.code is ResultCode.PROPOSAL_STAGED
    assert staged.state.node is StoryNode.CAFE_CHAT
    assert staged.state.pending is not None
    assert staged.effect_plan is not None
    shown = reduce_story(staged.state, offer_receipt(staged.effect_plan), definition)
    assert shown.code is ResultCode.RECEIPT_ACCEPTED
    assert shown.state.node is StoryNode.AWAIT_RAIN_CHOICE
    assert shown.state.offer_status is OfferStatus.PRESENTED
    assert not shown.state.episodes


def test_explicit_refusal_is_processed_before_generic_chat_proposal(definition):
    staged = offer_turn(new_story(definition), definition)
    visible = reduce_story(staged.state, offer_receipt(staged.effect_plan), definition).state
    chat = StoryProposal("t.chat", ProposalSignal.CHAT, "input.refuse", 2)
    refusal = JevEvidence("input.refuse", 2, "offer-1", Will.UNKNOWN, Relevance.RELEVANT, refusal=True)
    result = reduce_story(visible, StoryTurn("input.refuse", 2, chat, refusal,
                             ReadinessCatalog("empty"), True), definition)
    assert result.code is ResultCode.CHOICE_NO
    assert result.state.node is StoryNode.CAFE_CHAT
    assert result.state.offer_status is OfferStatus.DECLINED
    assert result.state.relationship_delta == 0


def test_offer_with_missing_relevance_or_permission_is_not_staged(definition):
    state = new_story(definition)
    p = StoryProposal("t.offer", ProposalSignal.OFFER_RAIN, "i1", 1, "offer-1", draft_cue="我想看一会儿雨。")
    for relevance, permission in [(Relevance.UNKNOWN, True), (Relevance.RELEVANT, False)]:
        j = JevEvidence("i1", 1, None, Will.UNKNOWN, relevance)
        result = reduce_story(state, StoryTurn("i1", 1, p, j, ReadinessCatalog("empty"), permission), definition)
        assert result.state.pending is None
        assert result.state.node is StoryNode.CAFE_CHAT


def test_unknown_holds_node_then_yes_needs_ready_assets_and_exact_receipt(definition):
    offered = offer_turn(new_story(definition), definition)
    state = reduce_story(offered.state, offer_receipt(offered.effect_plan), definition).state
    unknown = reduce_story(state, StoryTurn("input.unknown", 2, None,
                           JevEvidence("input.unknown", 2, "offer-1", Will.UNKNOWN),
                           ReadinessCatalog("empty"), True), definition)
    assert unknown.state.node is StoryNode.AWAIT_RAIN_CHOICE
    assert unknown.fallback.value == "calm_clarification"
    assert unknown.state.offer_status is OfferStatus.UNKNOWN

    # A logical asset name without a readiness record is UNKNOWN, not READY.
    no_catalog = yes_turn(unknown.state, definition, readiness=ReadinessCatalog("logical-only"))
    assert no_catalog.code is ResultCode.ASSET_UNKNOWN
    assert no_catalog.state.node is StoryNode.AWAIT_RAIN_CHOICE
    assert no_catalog.state.current_outfit == "black_jacket"

    ready = yes_turn(unknown.state, definition)
    assert ready.code is ResultCode.PROPOSAL_STAGED
    assert ready.state.node is StoryNode.RAINCOAT_PENDING
    assert ready.state.current_outfit == "black_jacket"
    assert ready.state.episodes == ()
    plan = ready.effect_plan
    assert plan is not None
    receipt = wardrobe_receipt(plan)
    completed = reduce_story(ready.state, receipt, definition)
    assert completed.state.node is StoryNode.RAIN_VIEW
    assert completed.state.current_outfit == "amber_raincoat"
    assert len(completed.state.episodes) == 1
    episode = completed.state.episodes[0]
    assert episode.evidence is EvidenceLabel.SOFTWARE
    assert episode.status == "candidate_only"
    assert "no_claim_of_physical_action" in episode.claim_boundary
    assert "no_claim_that_a_human_heard_or_understood" in episode.claim_boundary
    duplicate = reduce_story(completed.state, receipt, definition)
    assert duplicate.code is ResultCode.DUPLICATE
    assert duplicate.state == completed.state


def test_no_and_asset_unavailable_keep_character_indoors_without_penalty(definition):
    offered = offer_turn(new_story(definition), definition)
    state = reduce_story(offered.state, offer_receipt(offered.effect_plan), definition).state
    no = reduce_story(state, StoryTurn("input.no", 2, None,
                      JevEvidence("input.no", 2, "offer-1", Will.NO, refusal=True),
                      ReadinessCatalog("empty"), True), definition)
    assert no.state.node is StoryNode.CAFE_CHAT
    assert no.state.current_outfit == "black_jacket"
    assert no.state.offer_status is OfferStatus.DECLINED
    assert no.state.episodes == ()
    assert no.state.active_offer_id is None
    assert no.state.relationship_delta == 0

    open_again = StoryTurn("input.open", 3,
        StoryProposal("t.offer", ProposalSignal.OFFER_RAIN, "input.open", 3, "offer-2",
                      draft_cue="好，雨停之前我们再看一会儿。"),
        JevEvidence("input.open", 3, None, Will.UNKNOWN, Relevance.RELEVANT), ReadinessCatalog("empty"), True,
        reopen_offer=True)
    reopened = bind_staged(reduce_story(no.state, open_again, definition))
    state2 = reopened.state
    receipt2 = offer_receipt(reopened.effect_plan, receipt_id="receipt.offer.2")
    state2 = reduce_story(state2, receipt2, definition).state
    unavailable_catalog = ReadinessCatalog("no-raincoat", (
        CapabilityRecord("mira.outfit.amber_raincoat", CapabilityState.UNAVAILABLE),
    ))
    unavailable = yes_turn(state2, definition, input_id="input.yes.noasset", epoch=4, readiness=unavailable_catalog)
    assert unavailable.code is ResultCode.ASSET_UNAVAILABLE
    assert unavailable.state.node is StoryNode.CAFE_CHAT
    assert unavailable.state.current_outfit == "black_jacket"
    assert unavailable.state.offer_status is OfferStatus.CLOSED_CAPABILITY_UNAVAILABLE


def test_new_input_and_stop_invalidate_pending_grants_and_old_receipts(definition):
    staged = offer_turn(new_story(definition), definition)
    state = staged.state
    old_receipt = offer_receipt(staged.effect_plan)
    interrupted = reduce_story(state, StoryTurn("input.interrupt", 2, None, None,
                                   ReadinessCatalog("empty"), True), definition)
    assert interrupted.state.pending is None
    assert interrupted.state.node is StoryNode.CAFE_CHAT
    assert interrupted.state.offer_status is OfferStatus.SUSPENDED
    late = reduce_story(interrupted.state, old_receipt, definition)
    assert late.code is ResultCode.REJECTED
    assert late.state.node is StoryNode.CAFE_CHAT

    staged = offer_turn(new_story(definition), definition)
    stopped = reduce_story(staged.state, Stop(2), definition)
    assert stopped.code is ResultCode.STOPPED
    assert stopped.state.pending is None
    assert stopped.state.node is StoryNode.CAFE_CHAT
    assert reduce_story(stopped.state, offer_receipt(staged.effect_plan), definition).code is ResultCode.REJECTED


def test_unreliable_input_still_cancels_pending_effect(definition):
    staged = offer_turn(new_story(definition), definition)
    result = reduce_story(staged.state, StoryTurn("draft-asr", 2, None, None,
                            ReadinessCatalog("empty"), True, reliable_input=False), definition)
    assert result.state.pending is None
    assert result.state.offer_status is OfferStatus.SUSPENDED
    assert result.state.node is StoryNode.CAFE_CHAT


def test_new_input_cancels_pending_wardrobe_without_falsely_changing_outfit(definition):
    staged_offer = offer_turn(new_story(definition), definition)
    presented = reduce_story(staged_offer.state, offer_receipt(staged_offer.effect_plan, receipt_id="offer-ack"), definition).state
    pending = yes_turn(presented, definition)
    assert pending.state.node is StoryNode.RAINCOAT_PENDING
    wardrobe_plan = pending.effect_plan
    interrupted = reduce_story(pending.state, StoryTurn(
        "freechat-interrupt", 3, StoryProposal("t.chat", ProposalSignal.CHAT, "freechat-interrupt", 3),
        JevEvidence("freechat-interrupt", 3, "offer-1", Will.UNKNOWN), ReadinessCatalog("empty"), True), definition)
    assert interrupted.state.node is StoryNode.CAFE_CHAT
    assert interrupted.state.pending is None
    assert interrupted.state.current_outfit == "black_jacket"
    assert interrupted.state.episodes == ()
    old_completion = wardrobe_receipt(wardrobe_plan, receipt_id="late-wardrobe")
    late = reduce_story(interrupted.state, old_completion, definition)
    assert late.code is ResultCode.REJECTED
    assert late.state.current_outfit == "black_jacket"
    assert late.state.episodes == ()


def test_affect_lane_is_independent_of_freechat_and_story_refusal(definition):
    runtime = StoryRuntime(definition, "scope-A")
    # Free chat stays in cafe; independent affect can move from typed recent-turn evidence.
    chat = StoryProposal("t.chat", ProposalSignal.CHAT, "turn-1", 1)
    runtime.apply_story(StoryTurn("turn-1", 1, chat, JevEvidence("turn-1", 1, None, Will.UNKNOWN),
                                  ReadinessCatalog("empty"), True))
    runtime.apply_affect(AffectTurn("turn-1", AffectSignal.PLEASANT_SHARED_ATTENTION))
    runtime.apply_story(StoryTurn("turn-2", 2, StoryProposal("t.chat", ProposalSignal.CHAT, "turn-2", 2),
                                  JevEvidence("turn-2", 2, None, Will.UNKNOWN), ReadinessCatalog("empty"), True))
    affect = runtime.apply_affect(AffectTurn("turn-2", AffectSignal.COMFORTABLE_HUMOR))
    assert runtime.story.node is StoryNode.CAFE_CHAT
    assert affect.emotion is Affect.HAPPY

    # Declining the story is never fed to affect reduction or penalized.
    affect_before = runtime.affect
    assert affect_before.emotion is Affect.HAPPY
    unknown1 = reduce_affect(affect_before, AffectTurn("turn-3", AffectSignal.UNCERTAIN), None, definition)
    assert unknown1.emotion is Affect.HAPPY
    unknown2 = reduce_affect(unknown1, AffectTurn("turn-4", AffectSignal.UNCERTAIN), None, definition)
    assert unknown2.emotion is Affect.NORMAL
    guard1 = reduce_affect(unknown2, AffectTurn("turn-5", AffectSignal.BOUNDARY_PRESSURE), None, definition)
    guard2 = reduce_affect(guard1, AffectTurn("turn-6", AffectSignal.BOUNDARY_PRESSURE), None, definition)
    assert guard2.emotion is Affect.GUARDED
    repaired = reduce_affect(guard2, AffectTurn("turn-7", AffectSignal.REPAIR), None, definition)
    assert repaired.emotion is Affect.NORMAL


def test_input_start_fences_pending_work_without_consuming_input_and_preserves_visible_offer(definition):
    staged = offer_turn(new_story(definition), definition)
    visible = reduce_story(staged.state, offer_receipt(staged.effect_plan), definition).state
    started = begin_story_input(visible, "reply-yes", 2, definition)
    assert started.node is StoryNode.AWAIT_RAIN_CHOICE
    assert started.active_offer_id == "offer-1"
    assert started.offer_status is OfferStatus.PRESENTED
    assert started.input_fence_id == "reply-yes"
    assert "reply-yes" not in started.last_input_ids
    admitted = yes_turn(started, definition, input_id="reply-yes", epoch=2)
    assert admitted.state.node is StoryNode.RAINCOAT_PENDING
    assert admitted.state.input_fence_id is None


def test_stop_after_receipt_preserves_acknowledged_offer_and_wardrobe_history(definition):
    staged = offer_turn(new_story(definition), definition)
    visible = reduce_story(staged.state, offer_receipt(staged.effect_plan), definition).state
    stopped_offer = reduce_story(visible, Stop(2), definition).state
    assert stopped_offer.node is StoryNode.AWAIT_RAIN_CHOICE
    assert stopped_offer.offer_status is OfferStatus.PRESENTED
    assert stopped_offer.active_offer_id == "offer-1"
    yes = yes_turn(stopped_offer, definition, input_id="after-stop-yes", epoch=3)
    completed = reduce_story(yes.state, wardrobe_receipt(yes.effect_plan), definition).state
    stopped_after = reduce_story(completed, Stop(4), definition).state
    assert stopped_after.node is StoryNode.RAIN_VIEW
    assert stopped_after.current_outfit == "amber_raincoat"
    assert len(stopped_after.episodes) == 1


def test_affect_proposal_parser_uses_only_candidate_labels_and_server_stamped_evidence(definition):
    selected = definition_from_documents(GRAPH_DOC, SEED_DOC,
        approved_canon_ids=("canon.identity", "canon.shy_response"))
    proposal = parse_affect_proposal(
        {"candidate": "shy", "signal": "personal_attention", "canon_reason_id": "canon.shy_response"},
        trusted_evidence_ids=("input.1", "input.2"), approved_canon_ids=tuple(e.entry_id for e in selected.canon.entries))
    assert proposal.evidence_input_ids == ("input.1", "input.2")
    with pytest.raises(ValueError):
        parse_affect_proposal({"candidate": "shy", "signal": "personal_attention", "confidence": 100},
                              trusted_evidence_ids=("input.1",), approved_canon_ids=("canon.shy_response",))
    unknown = affect_turn_from_jev("input.3", AffectSignal.BOUNDARY_PRESSURE, sufficient_evidence=False)
    assert unknown.signal is AffectSignal.UNCERTAIN and not unknown.reliable


def test_explicit_author_canon_selection_retains_private_release_gate_in_projection(definition):
    selected = definition_from_documents(GRAPH_DOC, SEED_DOC,
        approved_canon_ids=("canon.identity", "canon.first_trip", "canon.waiting", "canon.shy_response"))
    state = new_story(selected)
    projection = project_shared_context(state, AffectState.initial(selected), selected)
    assert "canon.shy_response" in projection.canon_entry_ids
    assert "canon.first_trip" not in projection.canon_entry_ids
    view = json.loads(projection.context_json)
    assert "灯塔" not in json.dumps(view["approved_canon"], ensure_ascii=False)
    known = view["first_person_memory"]["autobiographical_fiction"]
    assert any(row["source_id"] == "canon.first_trip" and row["disclosure_status"] == "not_yet_released" for row in known)
    assert state.released_story_events == ()
    assert valid_story_projection(projection)
    forged = replace(projection, projection_id="storyctx." + "0" * 64)
    assert not valid_story_projection(forged)


def test_composition_approval_manifest_selects_exact_author_canon_only():
    selection = json.loads((ROOT / "apps/api/src/mira/adapters/story/assets/canon-selection.v1.json").read_text())
    seed_bytes = (ROOT / "apps/api/src/mira/adapters/story/assets/mira.story-seed.v1.json").read_bytes()
    assert hashlib.sha256(seed_bytes).hexdigest() == selection["seed_source"]["sha256"]
    ids = tuple(selection["default_selection"] + selection["explicit_composition_selection"])
    composed = definition_from_documents(GRAPH_DOC, json.loads(seed_bytes), approved_canon_ids=ids)
    assert {entry.entry_id for entry in composed.canon.entries} == set(ids)
    assert not composed.canon.proposal_ids
    assert all(entry.is_user_fact is False and entry.is_shared_experience is False for entry in composed.canon.entries)


def test_story_input_fixture_hashes_match_checked_in_manifest():
    manifest = json.loads((PACKAGE / "manifest.json").read_text())
    for row in manifest["files"]:
        raw = (PACKAGE / row["path"]).read_bytes()
        assert len(raw) == row["bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]


def test_shy_needs_bounded_personal_evidence_specific_notice_and_canon_reason(definition):
    state = AffectStateFor(definition)
    s1 = reduce_affect(state, AffectTurn("r1", AffectSignal.PLEASANT_SHARED_ATTENTION), None, definition)
    s2 = reduce_affect(s1, AffectTurn("r2", AffectSignal.COMFORTABLE_HUMOR), None, definition)
    assert s2.emotion is Affect.HAPPY
    s3 = reduce_affect(s2, AffectTurn("r3", AffectSignal.PERSONAL_ATTENTION, specific_notice=True), None, definition)
    s4 = reduce_affect(s3, AffectTurn("r4", AffectSignal.PERSONAL_ATTENTION),
                       AffectProposal(Affect.SHY, AffectSignal.PERSONAL_ATTENTION, ("r3", "r4"), "canon.shy_response"), definition)
    assert s4.emotion is Affect.SHY
    s5 = reduce_affect(s4, AffectTurn("r5", AffectSignal.NEUTRAL), None, definition)
    assert s5.emotion is not Affect.SHY
    assert s5.shy_cue_remaining == 0


def test_affect_duplicate_input_is_ignored_after_leaving_four_turn_evidence_window(definition):
    state = AffectStateFor(definition)
    state = reduce_affect(state, AffectTurn("same-input", AffectSignal.NEUTRAL), None, definition)
    for index in range(5):
        state = reduce_affect(state, AffectTurn(f"later-{index}", AffectSignal.NEUTRAL), None, definition)
    assert all(item.input_id != "same-input" for item in state.recent_turns)
    duplicate = reduce_affect(state, AffectTurn("same-input", AffectSignal.BOUNDARY_PRESSURE), None, definition)
    assert duplicate == state


def AffectStateFor(definition):
    from mira.domain.story import AffectState
    return AffectState.initial(definition)


def test_projection_is_version_bound_same_immutable_snapshot_and_has_no_raw_scope(definition):
    runtime = StoryRuntime(definition, "private/scope-A")
    projection = runtime.project().projection
    assert validate_projection_current(projection, runtime.story, runtime.affect, definition)
    assert projection.scope_binding_hash != "private/scope-A"
    assert "private/scope-A" not in projection.context_json
    assert "canon.attention" not in projection.context_json
    assert "author_draft" not in projection.context_json
    twin = runtime.project().projection
    assert twin.projection_id == projection.projection_id
    affect = reduce_affect(runtime.affect, AffectTurn("affect1", AffectSignal.NEUTRAL), None, definition)
    with pytest.raises(StaleStoryProjection):
        validate_projection_current(projection, runtime.story, affect, definition)


def test_strict_llm_proposal_parser_is_allowlisted_and_bound_by_server_ids():
    proposal = parse_story_proposal({"transition_id": "t.offer", "signal": "offer_rain",
                                     "offer_id": "o1", "target_capabilities": [], "draft_cue": "雨停了。"},
                                    input_id="trusted-input", epoch=9)
    assert proposal.input_id == "trusted-input" and proposal.epoch == 9
    with pytest.raises(ValueError):
        parse_story_proposal({"transition_id": "t.offer", "signal": "offer_rain", "node": "rain_view"}, input_id="i", epoch=1)
    with pytest.raises(ValueError):
        parse_story_proposal({"transition_id": "t.yes", "signal": "accept_raincoat", "target_capabilities": ["logical-only"]}, input_id="i", epoch=1)
    with pytest.raises(ValueError):
        StoryProposal("t.yes", ProposalSignal.ACCEPT_RAINCOAT, "i", 1, "o1")


def test_store_is_disabled_by_default_and_explicit_reentry_preserves_pending_unknown(tmp_path, definition):
    path = tmp_path / "private-story.sqlite3"
    locked = StoryCheckpointStore(path, enabled=False)
    with pytest.raises(StoreDisabled):
        locked.load("scope-A", definition.graph.story_id, graph_id=definition.graph.graph_id,
                    graph_revision=1, canon_revision=1, graph_hash=definition.graph.content_hash,
                    canon_hash=definition.canon.content_hash)
    assert not path.exists()

    offered = offer_turn(new_story(definition), definition)
    state = reduce_story(offered.state, offer_receipt(offered.effect_plan), definition).state
    unknown = reduce_story(state, StoryTurn("unknown-reopen", 2, None,
                           JevEvidence("unknown-reopen", 2, "offer-1", Will.UNKNOWN),
                           ReadinessCatalog("empty"), True), definition)
    store = StoryCheckpointStore(path, enabled=True, explicitly_authorized=True, authorized_scope_id="scope-A")
    store.save(unknown.state, __import__("mira.domain.story", fromlist=["AffectState"]).AffectState.initial(definition))
    reentered = store.load("scope-A", definition.graph.story_id, graph_id=definition.graph.graph_id,
                          graph_revision=1, canon_revision=1, graph_hash=definition.graph.content_hash,
                          canon_hash=definition.canon.content_hash)
    assert reentered is not None
    restored, affect = reentered
    assert restored.node is StoryNode.AWAIT_RAIN_CHOICE
    assert restored.offer_status is OfferStatus.UNKNOWN
    assert restored.current_outfit == "black_jacket"
    assert restored.pending is None
    assert affect.emotion is Affect.NORMAL


def test_store_restores_pending_effect_without_false_completion_and_checks_scope_version_tombstone(tmp_path, definition):
    path = tmp_path / "pending.sqlite3"
    offered = offer_turn(new_story(definition), definition)
    state = reduce_story(offered.state, offer_receipt(offered.effect_plan), definition).state
    pending = yes_turn(state, definition).state
    from mira.domain.story import AffectState
    store = StoryCheckpointStore(path, enabled=True, explicitly_authorized=True, authorized_scope_id="scope-A")
    store.save(pending, AffectState.initial(definition))
    restored, _ = store.load("scope-A", definition.graph.story_id, graph_id=definition.graph.graph_id,
                             graph_revision=1, canon_revision=1, graph_hash=definition.graph.content_hash,
                             canon_hash=definition.canon.content_hash)
    assert restored.node is StoryNode.RAINCOAT_PENDING
    assert restored.current_outfit == "black_jacket"
    assert restored.pending is not None
    assert restored.episodes == ()
    with pytest.raises(ScopeMismatch):
        store.load("scope-B", definition.graph.story_id, graph_id=definition.graph.graph_id,
                   graph_revision=1, canon_revision=1, graph_hash=definition.graph.content_hash,
                   canon_hash=definition.canon.content_hash)
    with pytest.raises(VersionMismatch):
        store.load("scope-A", definition.graph.story_id, graph_id=definition.graph.graph_id,
                   graph_revision=99, canon_revision=1, graph_hash=definition.graph.content_hash,
                   canon_hash=definition.canon.content_hash)
    assert store.tombstone("scope-A", definition.graph.story_id)
    with pytest.raises(Tombstoned):
        store.load("scope-A", definition.graph.story_id, graph_id=definition.graph.graph_id,
                   graph_revision=1, canon_revision=1, graph_hash=definition.graph.content_hash,
                   canon_hash=definition.canon.content_hash)
    with pytest.raises(Tombstoned):
        store.save(pending, AffectState.initial(definition))
    # Tombstone is retained, never physically purged.
    import sqlite3
    with sqlite3.connect(path) as db:
        assert db.execute("select tombstoned from story_checkpoint").fetchone()[0] == 1


def test_store_read_is_readonly_new_writes_are_owner_only_and_same_revision_is_compare_and_swap(tmp_path, definition):
    from mira.domain.story import AffectState
    missing = tmp_path / "not-created.sqlite3"
    store = StoryCheckpointStore(missing, enabled=True, explicitly_authorized=True, authorized_scope_id="scope-A")
    assert store.load("scope-A", definition.graph.story_id, graph_id=definition.graph.graph_id,
                      graph_revision=1, canon_revision=1, graph_hash=definition.graph.content_hash,
                      canon_hash=definition.canon.content_hash) is None
    assert not missing.exists()
    state = new_story(definition)
    affect = AffectState.initial(definition)
    store.save(state, affect)
    assert missing.exists()
    import os, stat
    assert stat.S_IMODE(os.stat(missing).st_mode) & 0o077 == 0
    store.save(state, affect)  # exact same revision/content is an idempotent write
    with pytest.raises(VersionMismatch):
        store.save(replace(state, current_outfit="cream_inner_only"), affect)
    with pytest.raises(StoreDisabled):
        StoryCheckpointStore(tmp_path / "bad.sqlite3", enabled=1,
                             explicitly_authorized=True, authorized_scope_id="scope-A")

    broad = tmp_path / "broad.sqlite3"
    broad.write_bytes(b"existing file")
    broad.chmod(0o644)
    rejected = StoryCheckpointStore(broad, enabled=True, explicitly_authorized=True, authorized_scope_id="scope-A")
    with pytest.raises(StoreDisabled):
        rejected.load("scope-A", definition.graph.story_id, graph_id=definition.graph.graph_id,
                      graph_revision=1, canon_revision=1, graph_hash=definition.graph.content_hash,
                      canon_hash=definition.canon.content_hash)

    target = tmp_path / "target.sqlite3"
    target.write_bytes(b"opaque")
    target.chmod(0o600)
    link = tmp_path / "link.sqlite3"
    link.symlink_to(target)
    linked = StoryCheckpointStore(link, enabled=True, explicitly_authorized=True, authorized_scope_id="scope-A")
    with pytest.raises(StoreDisabled):
        linked.load("scope-A", definition.graph.story_id, graph_id=definition.graph.graph_id,
                    graph_revision=1, canon_revision=1, graph_hash=definition.graph.content_hash,
                    canon_hash=definition.canon.content_hash)


def test_version_mismatch_and_cross_scope_receipts_never_apply(definition):
    staged = offer_turn(new_story(definition), definition)
    state = staged.state
    foreign = offer_receipt(staged.effect_plan, scope="scope-B")
    assert reduce_story(state, foreign, definition).code is ResultCode.REJECTED
    good = offer_receipt(staged.effect_plan)
    bad = replace(good, receipt_id="r-bad", graph_revision=2)
    assert reduce_story(state, bad, definition).state == state


def test_same_numeric_revisions_with_changed_graph_or_canon_hash_are_rejected(definition):
    changed_graph = json.loads(json.dumps(GRAPH_DOC))
    changed_graph["transitions"][0]["dialogue_example"] += " 变化"
    new_graph_def = definition_from_documents(changed_graph, SEED_DOC)
    old_state = new_story(definition)
    assert new_graph_def.graph.revision == definition.graph.revision
    assert new_graph_def.graph.content_hash != definition.graph.content_hash
    assert reduce_story(old_state, Stop(1), new_graph_def).code is ResultCode.REJECTED

    changed_seed = json.loads(json.dumps(SEED_DOC))
    changed_seed["canonical_fiction"][0]["text"] += " 变化"
    new_canon_def = definition_from_documents(GRAPH_DOC, changed_seed)
    assert new_canon_def.canon.revision == definition.canon.revision
    assert new_canon_def.canon.content_hash != definition.canon.content_hash
    assert reduce_story(old_state, Stop(1), new_canon_def).code is ResultCode.REJECTED


def test_qualified_wardrobe_episode_survives_reentry_as_scope_free_ack_context(tmp_path, definition):
    from mira.domain.story import AffectState
    offered = offer_turn(new_story(definition), definition)
    visible = reduce_story(offered.state, offer_receipt(offered.effect_plan), definition).state
    yes = yes_turn(visible, definition)
    completed = reduce_story(yes.state, wardrobe_receipt(yes.effect_plan), definition).state
    candidate = completed.episodes[0]
    assert candidate.compiled_effect_id == yes.effect_plan.compiled_effect_id
    assert candidate.compiled_effect_digest == yes.effect_plan.compiled_effect_digest
    assert candidate.receipt_id == "receipt.wardrobe"
    assert not hasattr(candidate, "scope_id")
    path = tmp_path / "episode.sqlite3"
    store = StoryCheckpointStore(path, enabled=True, explicitly_authorized=True, authorized_scope_id="scope-A")
    affect = AffectState.initial(definition)
    store.save(completed, affect)
    restored, restored_affect = store.load("scope-A", definition.graph.story_id,
        graph_id=definition.graph.graph_id, graph_revision=definition.graph.revision,
        canon_revision=definition.canon.revision, graph_hash=definition.graph.content_hash,
        canon_hash=definition.canon.content_hash)
    projection = project_shared_context(restored, restored_affect, definition)
    assert projection.acknowledged_presentations[0].receipt_id == candidate.receipt_id
    assert projection.acknowledged_presentations[0].compiled_effect_digest == candidate.compiled_effect_digest
    assert "scope-A" not in projection.context_json
    assert valid_story_projection(projection)
