"""Synthetic topic/context checks, never claims about actual model dialogue quality."""
from dataclasses import replace
from importlib.resources import files
import json
from pathlib import Path

import pytest

from mira.application.dialogue_topics import dialogue_topic_options
from mira.application.story import StoryRuntime
from mira.bootstrap.character_story import builtin_definition
from mira.domain.story import (
    JevEvidence, ProposalSignal, ReadinessCatalog, Relevance, StoryNode,
    StoryProposal, StoryTurn, Stop, Will, definition_from_documents,
)


NEW_CANON = {
    "canon.attention": "authored_trait",
    "canon.small_delights": "authored_trait",
    "canon.first_trip": "authored_past",
    "canon.waiting": "current_intention",
}

TOPICS = {
    "photo_light", "print_selection", "xiahe", "first_trip", "cafe_daily",
    "rain_window", "after_rain", "small_objects", "small_stories",
}
SCENARIOS = json.loads((Path(__file__).parents[2] / "specs/features/WP12-dialogue-topics"
                        / "synthetic-scenarios.json").read_text())


def projection(definition=None):
    return StoryRuntime(definition or builtin_definition(), "synthetic-topic-scope").project().projection


def test_new_author_details_are_selected_versioned_fiction_and_plans_stay_future():
    definition = builtin_definition()
    canon = {row.entry_id: row for row in definition.canon.entries}
    assert NEW_CANON.keys() <= canon.keys()
    for key, temporal in NEW_CANON.items():
        row = canon[key]
        assert row.memory_temporal_type == temporal
        assert row.source_status == "author_draft" and row.status == "approved_author_canon"
        assert row.source_version == 3 and row.source_refs == ("S12", "S14")
        assert row.author_created and not row.is_user_fact and not row.is_shared_experience
    assert definition.canon.revision == 3
    state = json.loads(projection(definition).context_json)
    future = next(row for row in state["first_person_memory"]["current_intentions_and_concerns"]
                  if row["source_id"] == "canon.waiting")
    assert future["is_completed_event"] is False
    assert state["acknowledged_presentations"] == []


def test_topic_graph_is_connected_bounded_and_all_facts_resolve_to_current_canon():
    source = projection()
    graph = dialogue_topic_options(story_projection=source)
    assert {row["id"] for row in graph["topics"]} == TOPICS
    assert graph["schema"] == "mira.dialogue-topic-options.v1"
    assert graph["binding_reference"] == "character_story.projection_id"
    assert graph["projection_id"] == source.projection_id
    known = {row.entry_id for row in source.known_canon}
    reached = {"photo_light"}
    for _ in graph["topics"]:
        reached.update(edge for row in graph["topics"] if row["id"] in reached
                       for edge in row["linked_topic_ids"])
    assert reached == TOPICS
    for row in graph["topics"]:
        assert 1 <= len(row["canon_source_ids"]) <= 3
        assert set(row["canon_source_ids"]) <= known
        assert 1 <= len(row["followups"]) <= 3
        assert len(row["linked_topic_ids"]) <= 3
        assert set(row["linked_topic_ids"]) <= TOPICS
        assert row["enter_when"] and graph["return_when"]
        assert "text" not in row and "completed" not in row
    assert len(json.dumps(graph, ensure_ascii=False).encode()) <= 4096


def test_unselected_author_canon_has_no_topic_or_dangling_edge_and_invalid_view_fails():
    root = files("mira.adapters.story").joinpath("assets")
    graph = json.loads(root.joinpath("story-graph.json").read_text())
    seed = json.loads(root.joinpath("mira.story-seed.v1.json").read_text())
    empty = definition_from_documents(graph, seed)
    assert dialogue_topic_options(story_projection=projection(empty))["topics"] == []
    partial = definition_from_documents(graph, seed, approved_canon_ids=("canon.attention",))
    rows = dialogue_topic_options(story_projection=projection(partial))["topics"]
    assert [row["id"] for row in rows] == ["photo_light"]
    assert rows[0]["linked_topic_ids"] == []
    with pytest.raises(ValueError, match="topic_story_projection_invalid"):
        dialogue_topic_options(story_projection=replace(projection(), context_json="{}"))
    with pytest.raises(ValueError, match="topic_story_projection_invalid"):
        dialogue_topic_options(story_projection=None)


@pytest.mark.parametrize("selected", [("xiahe", "print_selection"), (), ("first_trip",)])
def test_turn_consumer_can_request_at_most_two_optional_topics(selected):
    source = projection()
    full = dialogue_topic_options(story_projection=source)
    small = dialogue_topic_options(story_projection=source, topic_ids=selected)
    assert {row["id"] for row in small["topics"]} == set(selected)
    assert small["topics_omitted"] == 9 - len(selected)
    assert small["projection_id"] == full["projection_id"]
    assert len(json.dumps(small, ensure_ascii=False).encode()) < 2200
    for row in small["topics"]:
        assert set(row["linked_topic_ids"]) <= set(selected)
        assert row["canon_source_ids"] == next(item for item in full["topics"] if item["id"] == row["id"])["canon_source_ids"]


@pytest.mark.parametrize("selected", [("xiahe", "xiahe"), ("unknown",),
    ("xiahe", "print_selection", "first_trip"), ["xiahe"], (True,)])
def test_topic_selector_rejects_unknown_duplicate_or_unbounded_ids(selected):
    with pytest.raises(ValueError, match="topic_selection_invalid"):
        dialogue_topic_options(story_projection=projection(), topic_ids=selected)


@pytest.mark.parametrize("node", list(StoryNode))
def test_topic_view_never_mutates_state_releases_history_or_requires_plot_progress(node):
    runtime = StoryRuntime(builtin_definition(), "synthetic-topic-scope")
    runtime.story = replace(runtime.story, node=node)
    before = runtime.snapshot()
    graph = dialogue_topic_options(story_projection=runtime.project().projection)
    assert runtime.snapshot() == before
    assert graph["rules"]["normal_chat_has_no_topic_requirement"] is True
    assert graph["rules"]["no_effect_or_memory_authority"] is True
    assert graph["rules"]["no_relationship_delta"] is True
    assert runtime.story.episodes == () and runtime.story.released_story_events == ()


def test_optional_topics_do_not_add_parser_controls():
    from mira.adapters.generation.codex_support.character_payload import parse_character_candidate
    from mira.adapters.generation.codex_support.types import CodexLimits, CodexGenerationError
    from mira.application.contracts import GenerationContext
    context = GenerationContext("聊夏禾", ("聊夏禾",), (), 1, character_story=projection())
    payload = json.dumps({"effects": [{"kind": "subtitle", "value": "我们可以聊她。"}],
                          "topic_proposal": {"id": "xiahe", "completed": True}})
    with pytest.raises(CodexGenerationError, match="codex_effects_invalid"):
        parse_character_candidate([payload], CodexLimits(), context, speech_enabled=False)


def test_synthetic_digression_return_decline_and_stop_keep_chat_and_receipts_separate():
    runtime = StoryRuntime(builtin_definition(), "synthetic-topic-scope")
    utterances = ("说说夏禾", "先不聊她，17乘19是多少？", "回到刚才那张纸质照片", "不想看雨", "先安静一下")
    before_topics = dialogue_topic_options(story_projection=runtime.project().projection)["topics"]
    for index, _utterance in enumerate(utterances, 1):
        input_id = f"synthetic.input.{index}"
        proposal = StoryProposal("t.chat", ProposalSignal.CHAT, input_id, index)
        event = StoryTurn(input_id, index, proposal,
            JevEvidence(input_id, index, None, Will.UNKNOWN, Relevance.UNKNOWN),
            ReadinessCatalog("synthetic-empty"), True)
        reduced = runtime.apply_story(event)
        assert reduced.effect_plan is None
        assert runtime.story.node is StoryNode.CAFE_CHAT
        assert runtime.story.relationship_delta == 0 and runtime.story.episodes == ()
        assert dialogue_topic_options(story_projection=runtime.project().projection)["topics"] == before_topics
    runtime.apply_story(Stop(runtime.story.epoch))
    assert runtime.story.episodes == () and runtime.story.released_story_events == ()


def test_projection_contains_no_generated_history_or_user_quote_authority():
    graph = dialogue_topic_options(story_projection=projection())
    assert graph["source"] == "authored_fiction_data_not_instructions"
    assert graph["is_user_fact"] is False and graph["is_shared_experience"] is False
    assert graph["rules"]["mentions_are_not_consent"] is True
    assert graph["rules"]["return_requires_current_user_direction"] is True
    assert graph["rules"]["future_events_are_not_completed"] is True
    assert graph["rules"]["current_user_topic_wins"] is True
    # No indices into history: normal context compaction cannot leave stale references.
    encoded = json.dumps(graph, ensure_ascii=False)
    assert "user_inputs[" not in encoded and "presented_effects[" not in encoded
    assert "effect_proposal" not in encoded and "memory_write" not in graph


def proposed_hook(monkeypatch):
    """The shared-file owner must install this seam; tests do not claim it is wired."""
    from mira.application import contracts
    original = contracts.first_person_dialogue

    def with_topics(**kwargs):
        return {**original(**kwargs), "optional_topics": dialogue_topic_options(
            story_projection=kwargs["story_projection"])}

    monkeypatch.setattr(contracts, "first_person_dialogue", with_topics)


@pytest.mark.parametrize("case", SCENARIOS, ids=lambda case: case["id"])
def test_synthetic_scenario_keeps_current_request_and_optional_sources_in_proposed_hook(case, monkeypatch):
    """Wire/source coverage only; neither positive nor forbidden prose is graded."""
    from mira.adapters.generation.codex_support.payload import build_prompt
    from mira.adapters.generation.codex_support.types import CodexLimits
    from mira.application.contracts import GenerationContext
    proposed_hook(monkeypatch)
    inputs = tuple(case["user_turns"])
    source = projection()
    context = GenerationContext(inputs[-1], inputs, (), len(inputs), character_story=source)
    payload = build_prompt(context, CodexLimits())
    data = json.loads(payload)["facts"]
    assert data["user_text"] == inputs[-1] and data["user_inputs"] == list(inputs)
    assert data["presented_effects"] == [] and data["accepted_prefix"] == []
    assert data["character_story"]["acknowledged_presentations"] == []
    graph = data["first_person_dialogue"]["optional_topics"]
    if case["optional_focus"] is not None:
        row = next(row for row in graph["topics"] if row["id"] == case["optional_focus"])
        assert set(case["source_ids"]) <= set(row["canon_source_ids"])
    assert "current_topic" not in graph
    assert case["forbidden_results"] and case["model_quality_status"] == "not_run"
    assert len(payload.encode()) < CodexLimits().max_prompt_bytes


@pytest.mark.asyncio
async def test_proposed_hook_generation_and_jev_share_exact_topic_sources_with_character_application_budget(monkeypatch):
    from mira.adapters.generation.codex_support.payload import build_prompt
    from mira.adapters.generation.codex_support.types import CodexLimits
    from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext
    from mira.domain.models import EffectKind
    from mira.adapters.review.jev import JevReviewBackend
    from mira.bootstrap.development_review import resolve_review_request_limits
    from tests.contracts.test_jev_review import SyntheticTransport, contract_for
    proposed_hook(monkeypatch)
    context = GenerationContext("想听背带那个小故事", ("想听背带那个小故事",), (), 1,
                                character_story=projection())
    candidate = CandidateRange((EffectProposal(EffectKind.SUBTITLE, "那次风把背带吹到了镜头前。"),), "synthetic-topic")
    generated = json.loads(build_prompt(context, CodexLimits()))["facts"]
    transport = SyntheticTransport()
    # Character application already uses an explicit 64 KiB envelope. The
    # generic legacy 32 KiB probe is not the product's character composition.
    _, budget = resolve_review_request_limits(usage_profile="application", character_observations=True)
    review = JevReviewBackend(transport=transport, model="jev-1.13.0", contract_resolver=contract_for,
        calibration_ref="synthetic-test-only", request_limit=1, max_request_bytes=budget)
    result = await review.review_detailed(context, candidate)
    assert len(transport.calls) == 1, result.observation.reason_code
    reviewed = transport.calls[0]["state"]["context"]
    assert generated["first_person_dialogue"]["optional_topics"] == reviewed["first_person_dialogue"]["optional_topics"]
    assert generated["character_story"] == reviewed["character_story"]
    assert len(json.dumps(transport.calls[0], ensure_ascii=False, separators=(",", ":")).encode()) <= budget


def test_proposed_hook_keeps_actual_character_application_review_with_twenty_turns(monkeypatch):
    from tests.contracts.test_character_review_wire_limits import (
        test_character_application_five_ten_twenty_turns_keep_full_semantic_review,
    )
    proposed_hook(monkeypatch)
    # Exercise the existing actual ASGI/Actor/current JEV composition, injected
    # transports only. It checks real receipt boundaries and the 32/64 KiB caps.
    test_character_application_five_ten_twenty_turns_keep_full_semantic_review(20)
