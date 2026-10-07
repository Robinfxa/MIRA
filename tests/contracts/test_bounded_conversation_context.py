"""Synthetic conversation projection tests; no provider, credentials or private DB."""
import asyncio
import json
from dataclasses import replace

import pytest

from mira.adapters.generation.codex_support.payload import build_prompt
from mira.adapters.generation.direct_codex_responses import DirectResponsesLimits
from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.actor_memory import SessionMemoryBinding, ActorMemoryBindingError
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext, ReviewObservation, ReviewVerdict, generation_context_data
from mira.application.interrupted_intent import AcceptedInput, begin_request
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.domain.memory import MemoryScope, MemoryRevisionChangedError
from mira.domain.models import Effect, EffectKind, Phase, Receipt, SessionState


class Review:
    async def review(self, *_):
        return ReviewObservation(ReviewVerdict.ALLOW, "synthetic")


class Generation:
    def __init__(self, size=2):
        self.size = size
        self.prompts = []
        self.contexts = []

    async def generate(self, context):
        self.contexts.append(context)
        self.prompts.append(build_prompt(context, DirectResponsesLimits(), speech_enabled=False))
        yield CandidateRange((EffectProposal(EffectKind.SUBTITLE, "合" * self.size),), "synthetic")


async def idle(actor):
    for _ in range(500):
        await asyncio.sleep(0)
        state = await actor.snapshot()
        if state.phase in (Phase.READY, Phase.ERROR, Phase.STOPPED):
            return state
    raise AssertionError("actor did not settle")


@pytest.mark.parametrize("size", [2, 1200, 4096])
@pytest.mark.asyncio
async def test_real_actor_100_turns_bounded_without_losing_local_ledger(size):
    async def run():
        gen = Generation(size)
        actor = SessionActor(SessionState("synthetic", "client"), gen, Review(), MemoryEventJournal(32), RuntimeLimits(2, 100, 1000))
        seq = 0
        try:
            for turn in range(1, 101):
                await actor.submit(request_id=str(turn), activity_seq=turn, cutoff=seq, text=f"合成可靠输入 {turn}")
                state = await idle(actor)
                assert state.phase is Phase.READY, (turn, state.last_error)
                facts = json.loads(gen.prompts[-1])["facts"]
                assert facts["user_inputs"][-1] == f"合成可靠输入 {turn}"
                assert len(facts["user_inputs"]) <= 64
                assert len(gen.prompts[-1].encode()) <= 65536
                if turn in (5, 20, 65, 100):
                    assert len(state.user_inputs) == turn
                    assert len(state.presented_effects) == turn - 1
                for effect in state.active_grants:
                    seq += 1
                    await actor.receipt(Receipt(effect.id, effect.digest, effect.output_epoch, effect.activity_seq, seq))
            assert len((await actor.snapshot()).presented_effects) == 100
            assert facts["conversation_history"]["historical_detail_omitted"] is True
            assert facts["conversation_history"]["semantic_summary_available"] is False
        finally:
            await actor.close()
    await run()


def effect(index, kind=EffectKind.SUBTITLE, text=None):
    return Effect(str(index), kind, text or f"displayed {index}", f"digest-{index}", index + 1, index + 1)


def test_projection_keeps_exact_linked_identity_and_actual_current_state():
    inputs = tuple(["old input"] * 98 + ["same", "same"])
    root = AcceptedInput("root", 112, "same", "asr_final", 98)
    packet = begin_request(None, root, relation="independent", parent_id=None, parent_epoch=None)
    packet = begin_request(packet, AcceptedInput("new", 114, "same", "text", 99), relation="continuation", parent_id="root", parent_epoch=112)
    shown = (effect(0, EffectKind.POSE, "outfit_amber_raincoat"), effect(1, EffectKind.MEDIA, "travel_photo"),
             effect(2, EffectKind.POSE, "lower_camera")) + tuple(effect(i, text="合" * 4096) for i in range(3, 99))
    context = GenerationContext("same", inputs, shown, 114, request_context=packet)
    data = generation_context_data(context)
    linked = data["request_context"]["accepted_inputs"]
    assert [(x["request_id"], x["output_epoch"], x["source"]) for x in linked] == [("root", 112, "asr_final"), ("new", 114, "text")]
    assert [data["user_inputs"][x["user_input_index"]] for x in linked] == ["same", "same"]
    assert [data["conversation_history"]["source_user_input_indices"][x["user_input_index"]] for x in linked] == [98, 99]
    for expected in shown[:3]:
        assert any(x["id"] == expected.id and x["digest"] == expected.digest for x in data["presented_effects"])
    assert len(context.user_inputs) == 100 and context.request_context == packet
    assert len(build_prompt(context, DirectResponsesLimits()).encode()) <= 65536


@pytest.mark.parametrize("error,continues", [(OSError("synthetic missing"), True), (TimeoutError(), True),
    (ActorMemoryBindingError("scope_invalid"), False), (MemoryRevisionChangedError("memory_context_stale"), False),
    (ValueError("consent_revoked"), False), (PermissionError("synthetic denied"), False)])
@pytest.mark.asyncio
async def test_optional_operational_absence_degrades_but_authority_failures_do_not(error, continues):
    class Reader:
        async def build_packet(self, **_): raise error
        async def scope_revision(self, _): return 0
        async def aclose(self): pass
    async def run():
        gen = Generation()
        actor = SessionActor(SessionState("synthetic", "client"), gen, Review(), MemoryEventJournal(32), RuntimeLimits(2, 100, 1000),
            memory_binding=SessionMemoryBinding(Reader(), MemoryScope("user", "mira", "world")))
        try:
            await actor.submit(request_id="greeting", activity_seq=1, cutoff=0, text="hello")
            state = await idle(actor)
            assert (state.phase is Phase.READY) is continues
            assert len(gen.contexts) == int(continues)
            if continues:
                facts = json.loads(gen.prompts[0])["facts"]
                assert "memory_evidence" not in facts
                assert facts["memory_recall_status"] == "unavailable"
        finally: await actor.close()
    await run()


@pytest.mark.parametrize("turns", [5, 20, 65, 100])
@pytest.mark.asyncio
async def test_real_jev_wires_fit_without_dropping_permission_inputs(turns):
    from mira.application.decision_contracts import ReliableUserInput, InputDecisionStatus, ResponseContractProducer, valid_snapshot
    from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
    from mira.bootstrap.development_review import create_development_review_providers
    from tests.contracts.test_development_review_composition import SyntheticJevTransport
    async def run():
        wire = SyntheticJevTransport()
        providers = create_development_review_providers(generation=Generation(), input_transport=wire,
            output_transport=wire, authorized=True, decision_policy=USER_DEVELOPMENT_0_6_V2,
            conversation_first=True, usage_profile="application")
        user_inputs = tuple(["Never photograph me."] + ["synthetic continuation"] * (turns - 1))
        shown = tuple(effect(i, text="合" * 4096) for i in range(turns - 1))
        state = SessionState("synthetic", "client", revision=turns, activity_seq=turns, input_epoch=turns,
            output_epoch=turns, request_id=f"r{turns}", user_inputs=user_inputs, issued_effects=shown,
            receipts=tuple(Receipt(e.id, e.digest, e.output_epoch, e.activity_seq, i + 1) for i, e in enumerate(shown)))
        reliable = tuple(ReliableUserInput(f"r{i}", value) for i, value in enumerate(user_inputs))
        snap = providers.decision_owner.snapshot(state, reliable)
        assert snap is not None and valid_snapshot(snap)
        observation = await providers.semantic_review.observe(snap)
        assert observation.status is InputDecisionStatus.OBSERVED, observation.reason_code
        proposal = CandidateRange((EffectProposal(EffectKind.POSE, "face_calm"),), "synthetic")
        result = await providers.semantic_review.review(snap, proposal, observation)
        assert result.verdict is ReviewVerdict.ALLOW, result.reason_code
        assert len(wire.calls) == 2
        for request, *_ in wire.calls:
            maximum = 32768 if "contract" in request["state"] else 16384
            assert len(json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()) <= maximum
            snapshot_data = request["state"].get("contract", {}).get("snapshot", request["state"])
            assert snapshot_data["reliable_inputs"][0]["text"] == "Never photograph me."
            assert len(snapshot_data["reliable_inputs"]) == turns
    await run()
