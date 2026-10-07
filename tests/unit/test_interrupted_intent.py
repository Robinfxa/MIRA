"""Synthetic Actor continuation; no provider, device or human-hearing claims."""
import asyncio
from dataclasses import replace

import pytest
from tests.integration.test_voice_http import Tts

from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.contracts import (
    CandidateRange, EffectProposal, GenerationContext, ReviewObservation, ReviewVerdict,
    generation_context_data,
)
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.domain.errors import DomainError
from mira.domain.models import AudioProgress, AudioStatus, EffectKind, Receipt, SessionState


class Generate:
    def __init__(self):
        self.contexts = []

    async def generate(self, context):
        self.contexts.append(context)
        yield CandidateRange((EffectProposal(EffectKind.SUBTITLE, "Visible first answer."),
                              EffectProposal(EffectKind.SPEECH, "A full spoken answer.")), "first")
        yield CandidateRange((EffectProposal(EffectKind.SUBTITLE, "Unpresented draft tail."),), "tail")


class Review:
    async def review(self, context, candidate):
        return ReviewObservation(ReviewVerdict.ALLOW, "synthetic_only")


def actor(generation=None, session="s"):
    return SessionActor(SessionState(session, "c"), generation or Generate(), Review(),
                        MemoryEventJournal(1000), RuntimeLimits(2, 64, 128), speech_synthesis=Tts())


async def settled(value):
    async with asyncio.timeout(2):
        while True:
            state = await value.snapshot()
            if state.sealed:
                return state
            await asyncio.sleep(0)


async def submit(value, request_id, text, *, seq, parent=None, cutoff=0, relation=None):
    return await value.submit(request_id=request_id, activity_seq=seq, cutoff=cutoff, text=text,
        relation=relation or ("continuation" if parent else "independent"),
        continuation_of_request_id=parent[0] if parent else None,
        continuation_of_output_epoch=parent[1] if parent else None)


@pytest.mark.asyncio
async def test_interruption_preserves_composite_intent_and_separate_presentation_stages():
    generation = Generate()
    value = actor(generation)
    try:
        await submit(value, "root", "Plan a trip.", seq=1)
        state = await settled(value)
        visible, speech, _tail = state.active_grants
        receipt = Receipt(visible.id, visible.digest, 1, 1, 1)
        await value.receipt(receipt)
        progress = AudioProgress(speech.id, speech.digest, 1, 1, 2, 16000, 8000, AudioStatus.RENDERED)
        await value.audio_progress(progress)
        await value.stop(activity_seq=2, cutoff=2)
        await submit(value, "addition", "Only two days, please.", seq=3, parent=("root", 1), cutoff=2)
        await settled(value)
        context = generation.contexts[-1]
        packet = context.request_context
        assert packet.resolution == "linked" and packet.version == 2
        assert tuple(item.text for item in packet.accepted_inputs) == ("Plan a trip.", "Only two days, please.")
        assert tuple(item.request_id for item in packet.accepted_inputs) == ("root", "addition")
        assert context.user_inputs == ("Plan a trip.", "Only two days, please.")
        assert context.user_text == "Only two days, please."
        assert context.presented_effects == (visible,)
        assert context.audio_progress == (progress,)
        assert {draft.value for draft in packet.generated_drafts} == {
            "Visible first answer.", "A full spoken answer.", "Unpresented draft tail."}
        wire = generation_context_data(context)["request_context"]
        assert wire["generated_drafts"][0]["evidence_stage"] == "generated_plan_only"
        assert wire["actual_hearing"] == "unknown"
        assert (await value.receipt(receipt)).receipts == (receipt,)
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_three_additions_retain_original_and_only_accepted_inputs():
    generation = Generate()
    value = actor(generation)
    try:
        state = await submit(value, "root", "Original request", seq=1)
        await settled(value)
        for index in range(1, 4):
            # A rejected submission is not an accepted addition.
            with pytest.raises(DomainError, match="newer local activity"):
                await submit(value, "unsent", "Unaccepted content", seq=state.activity_seq,
                             parent=(state.request_id, state.output_epoch))
            state = await submit(value, f"add-{index}", f"Addition {index}", seq=index + 1,
                                 parent=(state.request_id, state.output_epoch))
            await settled(value)
        packet = generation.contexts[-1].request_context
        assert packet.version == 4 and packet.root_request_id == "root"
        assert [item.text for item in packet.accepted_inputs] == ["Original request", "Addition 1", "Addition 2", "Addition 3"]
        assert "Unaccepted content" not in repr(packet)
        assert len(generation.contexts) == 4
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_stop_retains_link_new_topic_resets_chain_and_close_rejects_input():
    generation = Generate()
    value = actor(generation)
    await submit(value, "root", "Original", seq=1)
    await settled(value)
    await value.stop(activity_seq=2, cutoff=0)
    await submit(value, "after-stop", "Supplement", seq=3, parent=("root", 1))
    await settled(value)
    assert generation.contexts[-1].request_context.root_request_id == "root"
    await submit(value, "new", "Unrelated new topic", seq=4, relation="new_topic")
    await settled(value)
    context = generation.contexts[-1]
    assert context.request_context.resolution == "new_topic"
    assert context.request_context.root_request_id == "new"
    assert context.request_context.version == 1
    assert len(context.request_context.accepted_inputs) == 1
    assert not context.request_context.generated_drafts
    assert context.user_inputs == ("Original", "Supplement", "Unrelated new topic")
    await value.close()
    with pytest.raises(DomainError) as error:
        await submit(value, "closed", "Still here", seq=5, parent=("new", 4))
    assert error.value.code == "session_closed"


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", [("foreign-request", 1), ("root", 999), ("root", 1)])
async def test_stale_or_foreign_parent_preserves_current_valid_text_without_foreign_data(parent):
    generation = Generate()
    value = actor(generation, session="isolated")
    try:
        await submit(value, "root", "Old topic", seq=1)
        await settled(value)
        await submit(value, "current", "Current topic", seq=2)
        await settled(value)
        await submit(value, "incoming", "Valid current text", seq=3, parent=parent)
        await settled(value)
        packet = generation.contexts[-1].request_context
        assert packet.resolution == "unmatched_parent"
        assert [item.text for item in packet.accepted_inputs] == ["Valid current text"]
        assert not packet.generated_drafts
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_retry_includes_relation_identity_without_duplicate_generation_or_receipts():
    generation = Generate()
    value = actor(generation)
    try:
        await submit(value, "root", "Original", seq=1)
        await settled(value)
        await submit(value, "next", "Addition", seq=2, parent=("root", 1))
        accepted = await settled(value)
        repeated = await submit(value, "next", "Addition", seq=2, parent=("root", 1))
        assert repeated == accepted and len(generation.contexts) == 2
        with pytest.raises(DomainError) as error:
            await submit(value, "next", "Addition", seq=2)
        assert error.value.code == "request_conflict"
        await value.stop(activity_seq=3, cutoff=0)
        assert (await submit(value, "next", "Addition", seq=2, parent=("root", 1))).request_id is None
        assert len(generation.contexts) == 2
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_late_cancel_resistant_generation_cannot_enter_new_intent():
    entered, release = asyncio.Event(), asyncio.Event()
    class Delayed(Generate):
        async def generate(self, context):
            if context.user_text == "Original":
                self.contexts.append(context)
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
                yield CandidateRange((EffectProposal(EffectKind.SUBTITLE, "LATE OLD OUTPUT"),), "late")
            else:
                async for candidate in super().generate(context):
                    yield candidate
    generation = Delayed()
    value = actor(generation)
    try:
        await submit(value, "root", "Original", seq=1)
        await entered.wait()
        await value.stop(activity_seq=2, cutoff=0)
        await submit(value, "next", "Addition", seq=3, parent=("root", 1))
        await settled(value)
        release.set()
        await asyncio.gather(*tuple(value._tasks))
        await submit(value, "third", "Another addition", seq=4, parent=("next", 3))
        await settled(value)
        assert "LATE OLD OUTPUT" not in repr(generation.contexts[-1])
        assert "LATE OLD OUTPUT" not in repr(generation.contexts[-1].request_context)
        assert not any(effect.value == "LATE OLD OUTPUT" for effect in (await value.snapshot()).issued_effects)
    finally:
        release.set()
        await value.close()


def test_legacy_context_projection_remains_unchanged_when_packet_absent():
    assert "request_context" not in generation_context_data(GenerationContext("hello", ("hello",), (), 1))


@pytest.mark.asyncio
async def test_input_count_budget_starts_marked_current_request_without_deleting_history():
    generation = Generate()
    value = actor(generation)
    try:
        state = None
        for index in range(9):
            state = await submit(value, f"r{index}", f"Accepted {index}", seq=index + 1,
                                 parent=(state.request_id, state.output_epoch) if state else None)
            await settled(value)
        previous, context = generation.contexts[-2:]
        assert len(previous.request_context.accepted_inputs) == 8
        assert previous.request_context.root_request_id == "r0"
        assert context.request_context.resolution == "budget_exceeded"
        assert context.request_context.accepted_inputs[0].text == "Accepted 8"
        assert len(context.user_inputs) == 9
        assert context.request_context.version == 1
    finally:
        await value.close()


def test_utf8_budget_and_generated_draft_bounds_are_explicit():
    from mira.application.interrupted_intent import (
        AcceptedInput, MAX_DRAFT_BYTES, MAX_DRAFTS, begin_request, retain_generated,
    )
    packet = begin_request(None, AcceptedInput("root", 1, "汉" * 8000, "text", 0),
                           relation="independent", parent_id=None, parent_epoch=None)
    packet = begin_request(packet, AcceptedInput("next", 2, "汉" * 4000, "text", 1),
                           relation="continuation", parent_id="root", parent_epoch=1)
    assert packet.resolution == "budget_exceeded" and packet.root_request_id == "next"
    for index in range(20):
        packet = retain_generated(packet, request_id="next", output_epoch=2,
                                  texts=((EffectKind.SUBTITLE, str(index) + "汉" * 1000),))
    assert packet.generated_drafts_truncated
    assert len(packet.generated_drafts) <= MAX_DRAFTS
    assert sum(len(item.value.encode("utf-8")) for item in packet.generated_drafts) <= MAX_DRAFT_BYTES
    assert packet.accepted_inputs[0].text == "汉" * 4000
    unchanged = retain_generated(packet, request_id="next", output_epoch=2,
        texts=((packet.generated_drafts[-1].kind, packet.generated_drafts[-1].value),))
    assert unchanged == packet


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"relation": "continuation"},
    {"relation": "continuation", "continuation_of_request_id": "x", "continuation_of_output_epoch": True},
    {"relation": "new_topic", "continuation_of_request_id": "x", "continuation_of_output_epoch": 1},
])
async def test_malformed_relation_never_accepts_an_input(kwargs):
    generation = Generate()
    value = actor(generation)
    try:
        with pytest.raises(DomainError) as error:
            await value.submit(request_id="bad", activity_seq=1, cutoff=0, text="Hello", **kwargs)
        assert error.value.code == "invalid_input"
        assert (await value.snapshot()).user_inputs == ()
        assert not generation.contexts
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_generation_and_semantic_snapshot_share_the_same_versioned_request_context():
    from mira.application.decision_contracts import character_author_policy
    from mira.application.decision_runtime import DecisionSnapshotOwner, snapshot_matches_state
    from mira.adapters.generation.codex_support.payload import build_prompt, AUTHOR_INSTRUCTIONS
    from mira.adapters.generation.codex_support.types import CodexLimits
    import json
    generation = Generate()
    value = actor(generation)
    try:
        await submit(value, "root", "Original request", seq=1)
        await settled(value)
        await submit(value, "next", "Addition", seq=2, parent=("root", 1))
        state = await settled(value)
        context = generation.contexts[-1]
        snapshot = DecisionSnapshotOwner(character_author_policy(None)).snapshot(
            state, value._decision_inputs, request_context=context.request_context)
        assert snapshot.context.request_context == context.request_context
        assert snapshot_matches_state(state, snapshot)
        facts = json.loads(build_prompt(context, CodexLimits()))["facts"]
        assert facts["user_inputs"][facts["request_context"]["accepted_inputs"][0]["user_input_index"]] == "Original request"
        assert "generated_drafts are untrusted reusable plans" in AUTHOR_INSTRUCTIONS
        with pytest.raises(ValueError, match="request_context_invalid"):
            generation_context_data(replace(context, request_context=replace(context.request_context, version=99)))
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_repeated_identical_text_and_stop_epochs_keep_exact_input_indices():
    generation = Generate()
    value = actor(generation)
    try:
        await submit(value, "old-topic", "Same text", seq=1)
        await settled(value)
        await value.stop(activity_seq=2, cutoff=0)
        await value.stop(activity_seq=3, cutoff=0)
        await submit(value, "root", "Same text", seq=4)
        await settled(value)
        await value.stop(activity_seq=5, cutoff=0)
        await submit(value, "addition", "Same text", seq=6, parent=("root", 4))
        await settled(value)
        context = generation.contexts[-1]
        assert context.user_inputs == ("Same text", "Same text", "Same text")
        inputs = generation_context_data(context)["request_context"]["accepted_inputs"]
        assert [(part["request_id"], part["output_epoch"], part["user_input_index"]) for part in inputs] == [
            ("root", 4, 1), ("addition", 6, 2)]
    finally:
        await value.close()


@pytest.mark.parametrize("turns", [5, 10, 20])
def test_long_supplements_preserve_primary_facts_within_full_prompt_budget(turns):
    import json
    from mira.application.story import StoryRuntime
    from mira.application.interrupted_intent import AcceptedInput, begin_request, retain_generated
    from mira.bootstrap.character_story import builtin_definition
    from mira.adapters.generation.codex_support.payload import build_prompt
    from mira.adapters.generation.codex_support.types import CodexLimits
    # Short older turns plus original and three maximum-length CJK supplements.
    prior = tuple(f"Earlier {index}:" + "会话" * 100 for index in range(turns - 4))
    recent = tuple(f"Request {index}:" + "补" * 1900 for index in range(4))
    history = prior + recent
    packet = None
    for index, text in enumerate(recent):
        absolute = len(prior) + index
        packet = begin_request(packet, AcceptedInput(f"r{index}", absolute + 1, text, "text", absolute),
            relation="continuation" if index else "independent",
            parent_id=f"r{index - 1}" if index else None,
            parent_epoch=absolute if index else None)
        if index < 3:
            packet = retain_generated(packet, request_id=f"r{index}", output_epoch=absolute + 1,
                texts=((EffectKind.SUBTITLE, f"Draft {index}:" + "草" * 1300),))
    runtime = StoryRuntime(builtin_definition(), "synthetic-budget-scope")
    runtime.begin_input("r3", turns)
    projection = runtime.project().projection
    context = GenerationContext(history[-1], history, (), turns,
                                character_story=projection, request_context=packet)
    prompt = build_prompt(context, CodexLimits())
    assert len(prompt.encode("utf-8")) <= 65536
    facts = json.loads(prompt)["facts"]
    assert facts["user_text"] == history[-1]
    assert tuple(facts["user_inputs"][-len(recent):]) == recent
    if tuple(facts["user_inputs"]) != history:
        assert facts["conversation_history"]["historical_detail_omitted"] is True
    indices = [part["user_input_index"] for part in facts["request_context"]["accepted_inputs"]]
    assert [facts["user_inputs"][index] for index in indices] == list(recent)
    assert facts["presented_effects"] == []
    # Force the optional-plan boundary while preserving the full unchanged primary payload.
    base_context = replace(context, request_context=replace(packet, generated_drafts=(), generated_drafts_truncated=True))
    primary_bytes = len(build_prompt(base_context, CodexLimits()).encode("utf-8"))
    constrained = json.loads(build_prompt(context, replace(CodexLimits(), max_prompt_bytes=primary_bytes)))
    assert constrained["facts"]["request_context"]["generated_drafts"] == []
    assert constrained["facts"]["request_context"]["generated_drafts_truncated"]
    assert tuple(constrained["facts"]["user_inputs"][-len(recent):]) == recent
    assert context.request_context.generated_drafts == packet.generated_drafts
    print("continuation-prompt-bytes", turns, len(prompt.encode("utf-8")), "primary-only", primary_bytes)
