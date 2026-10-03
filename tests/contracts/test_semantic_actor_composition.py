"""Actor composition races with synthetic judgments; no live content admission."""
import asyncio
from dataclasses import replace

import pytest

from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.contracts import CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict
from mira.application.decision_contracts import (
    ChoiceProbability, InputDecisionObservation, InputDecisionStatus, PredicateObservation,
    ReferentObservation, SemanticValue, evidence_digest, mira26_author_policy,
)
from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.domain.models import EffectKind, Phase, Receipt, SessionState


def observed(snap):
    return InputDecisionObservation(snap.snapshot_id, evidence_digest(snap),
        InputDecisionStatus.OBSERVED, "synthetic",
        tuple(PredicateObservation(name, SemanticValue.NO, 0.0) for name in (
            "speech_restriction", "capture_restriction", "display_request")),
        ReferentObservation("none", None, (ChoiceProbability("none", 1.0),
                                          ChoiceProbability("ambiguous", 0.0)), 1.0),
        calibration_ref="synthetic-input-only", model="jev-1.13.0")


class Input:
    def __init__(self):
        self.calls = []

    async def observe(self, snap):
        self.calls.append(snap)
        return observed(snap)


class Output:
    def __init__(self):
        self.calls = []

    async def review_contract(self, context, candidate, contract):
        self.calls.append(contract)
        return ReviewObservation(ReviewVerdict.ALLOW, "synthetic")


class Generation:
    def __init__(self, count=1):
        self.count = count

    async def generate(self, context):
        for index in range(self.count):
            yield CandidateRange((EffectProposal(EffectKind.POSE, "face_calm"),), f"candidate-{index}")


class ForbiddenLegacyReview:
    async def review(self, *args):
        raise AssertionError("Typed composition must never fall back to legacy or fixture review")


def actor(input_backend=None, output_backend=None, count=1):
    return SessionActor(SessionState("s", "c"), Generation(count), ForbiddenLegacyReview(),
        MemoryEventJournal(100), RuntimeLimits(2, 32, 128),
        semantic_review=SemanticReviewCoordinator(input_backend or Input(), output_backend or Output()),
        decision_owner=DecisionSnapshotOwner(mira26_author_policy()))


async def submit(value, request="input-1", activity=1):
    return await value.submit(request_id=request, activity_seq=activity, cutoff=0, text="请看雨。")


async def finish(value):
    async with asyncio.timeout(3):
        await asyncio.gather(*tuple(value._tasks), return_exceptions=True)
    return await value.snapshot()


@pytest.mark.asyncio
async def test_actor_uses_typed_stage_and_seal_without_fixture_fallback():
    source, output = Input(), Output()
    value = actor(source, output)
    await submit(value)
    state = await finish(value)
    assert state.sealed and len(state.active_grants) == 1
    assert [contract.scope for contract in output.calls] == ["stage", "seal"]
    assert output.calls[0].snapshot.reliable_inputs[0].event_id == "input-1"
    assert output.calls[0].snapshot.context.accepted_prefix == ()
    assert output.calls[-1].snapshot.context.accepted_prefix == state.active_grants
    assert not output.calls[-1].snapshot.context.presented_effects
    await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_stage", ["input", "output"])
async def test_stop_remains_local_while_uncooperative_semantic_wait_returns_late(blocked_stage):
    entered, release = asyncio.Event(), asyncio.Event()
    class SlowInput(Input):
        async def observe(self, snap):
            if blocked_stage == "input":
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
            return await super().observe(snap)
    class SlowOutput(Output):
        async def review_contract(self, *args):
            if blocked_stage == "output":
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
            return await super().review_contract(*args)
    output = SlowOutput()
    value = actor(SlowInput(), output)
    await submit(value)
    async with asyncio.timeout(1):
        await entered.wait()
        stopped = await value.stop(activity_seq=2, cutoff=0)
    assert stopped.phase == Phase.STOPPED
    release.set()
    state = await finish(value)
    assert state == stopped and not state.issued_effects and state.user_inputs == ("请看雨。",)
    if blocked_stage == "input":
        assert not output.calls
    await value.close()


@pytest.mark.asyncio
async def test_unknown_input_fails_closed_without_output_or_legacy_review():
    class Unknown(Input):
        async def observe(self, snap):
            return replace(observed(snap), status=InputDecisionStatus.UNKNOWN, calibration_ref=None)
    output = Output()
    value = actor(Unknown(), output)
    await submit(value)
    state = await finish(value)
    assert state.phase == Phase.ERROR and not state.issued_effects and not output.calls
    await value.close()


@pytest.mark.asyncio
async def test_seal_rejection_does_not_mark_incomplete_plan_complete():
    class RejectSeal(Output):
        async def review_contract(self, context, candidate, contract):
            self.calls.append(contract)
            return ReviewObservation(ReviewVerdict.REJECT if contract.scope == "seal"
                                     else ReviewVerdict.ALLOW, "synthetic")
    value = actor(output_backend=RejectSeal())
    await submit(value)
    state = await finish(value)
    assert state.phase == Phase.ERROR and not state.sealed and not state.active_grants
    assert len(state.issued_effects) == 1
    await value.close()


@pytest.mark.asyncio
async def test_presentation_change_during_review_rebuilds_same_candidate_before_grant():
    entered, release = asyncio.Event(), asyncio.Event()
    class SlowSecond(Output):
        async def review_contract(self, context, proposal, contract):
            self.calls.append(contract)
            if len(self.calls) == 2:
                entered.set()
                await release.wait()
            return ReviewObservation(ReviewVerdict.ALLOW, "synthetic")
    source, output = Input(), SlowSecond()
    value = actor(source, output, count=2)
    await submit(value)
    async with asyncio.timeout(1):
        await entered.wait()
    first = (await value.snapshot()).active_grants[0]
    await value.receipt(Receipt(first.id, first.digest, first.output_epoch, first.activity_seq, 1))
    release.set()
    state = await finish(value)
    assert state.sealed and len(state.active_grants) == 2
    assert len(output.calls) == 4  # first stage, stale second, rebuilt second, seal
    assert output.calls[1].candidate_digest == output.calls[2].candidate_digest
    assert output.calls[1].snapshot.context.presented_effects == ()
    assert output.calls[2].snapshot.context.presented_effects == (first,)
    assert source.calls[1].snapshot_id != source.calls[2].snapshot_id
    await value.close()


@pytest.mark.asyncio
async def test_latest_pending_input_waits_for_one_semantic_call_and_discards_superseded():
    entered, release = asyncio.Event(), asyncio.Event()
    class FirstBlocked(Input):
        def __init__(self):
            super().__init__()
            self.active = self.peak = 0
        async def observe(self, snap):
            self.active += 1
            self.peak = max(self.active, self.peak)
            self.calls.append(snap)
            if len(self.calls) == 1:
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
            self.active -= 1
            return observed(snap)
    source, output = FirstBlocked(), Output()
    value = actor(source, output)
    await submit(value)
    async with asyncio.timeout(1):
        await entered.wait()
    await submit(value, "input-2", 2)
    await submit(value, "input-3", 3)
    release.set()
    state = await finish(value)
    assert source.peak == 1
    assert state.sealed and state.request_id == "input-3" and len(state.active_grants) == 1
    assert {contract.snapshot.generation_id for contract in output.calls} == {"input-3"}
    assert all(item.generation_id != "input-2" for item in source.calls)
    assert len(source.calls[-1].reliable_inputs) == 3
    await value.close()


@pytest.mark.asyncio
async def test_container_explicit_semantic_injection_keeps_default_factory_offline():
    from mira.bootstrap.container import build_container
    from mira.bootstrap.providers import Providers, create_providers
    from mira.config.loader import load_settings
    settings = load_settings(environ={})
    default = create_providers(settings.providers)
    assert getattr(default, "semantic_review", None) is None
    source, output = Input(), Output()
    providers = Providers(Generation(), ForbiddenLegacyReview(),
        semantic_review=SemanticReviewCoordinator(source, output),
        decision_owner=DecisionSnapshotOwner(mira26_author_policy()))
    container = build_container(settings, providers=providers)
    value, token = container.sessions.create("synthetic-browser")
    await submit(value)
    state = await finish(value)
    assert state.sealed and [item.scope for item in output.calls] == ["stage", "seal"]
    await container.close()


@pytest.mark.asyncio
async def test_reliable_asr_source_is_preserved_and_idempotence_cannot_relabel_it():
    from mira.domain.errors import DomainError
    source = Input()
    value = actor(source)
    await value.submit(request_id="asr-final", activity_seq=1, cutoff=0,
                       text="请看雨。", source="asr_final")
    state = await finish(value)
    assert state.sealed and source.calls[0].reliable_inputs[0].source == "asr_final"
    with pytest.raises(DomainError, match="reused"):
        await value.submit(request_id="asr-final", activity_seq=1, cutoff=0,
                           text="请看雨。", source="text")
    with pytest.raises(DomainError, match="reliable"):
        await value.submit(request_id="partial", activity_seq=2, cutoff=0,
                           text="partial", source="asr_partial")
    await value.close()


@pytest.mark.asyncio
async def test_receipt_during_input_wait_is_reobserved_before_any_output_call():
    entered, release = asyncio.Event(), asyncio.Event()
    class SecondInput(Input):
        async def observe(self, snap):
            self.calls.append(snap)
            if len(self.calls) == 2:
                entered.set()
                await release.wait()
            return observed(snap)
    source, output = SecondInput(), Output()
    value = actor(source, output, count=2)
    await submit(value)
    async with asyncio.timeout(1):
        await entered.wait()
    effect = (await value.snapshot()).active_grants[0]
    await value.receipt(Receipt(effect.id, effect.digest, 1, 1, 1))
    release.set()
    state = await finish(value)
    assert state.sealed and len(source.calls) == 4 and len(output.calls) == 3
    assert output.calls[1].snapshot == source.calls[2]
    assert output.calls[1].snapshot.context.presented_effects == (effect,)
    await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_stage", ["input", "output"])
async def test_semantic_timeout_cannot_be_swallowed_into_a_permit(blocked_stage):
    class TimeoutInput(Input):
        async def observe(self, snap):
            if blocked_stage == "input":
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    pass
            return observed(snap)
    class TimeoutOutput(Output):
        async def review_contract(self, *args):
            if blocked_stage == "output":
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    pass
            return await super().review_contract(*args)
    value = actor(TimeoutInput(), TimeoutOutput())
    value._limits = RuntimeLimits(.02, 32, 128)
    await submit(value)
    state = await finish(value)
    assert state.phase == Phase.ERROR and state.last_error == "generation_timeout"
    assert not state.issued_effects and not state.sealed
    await value.close()


@pytest.mark.asyncio
async def test_semantic_cancellation_diagnostics_do_not_report_late_input_success():
    from mira.application.diagnostic_events import DiagnosticOutcome, DiagnosticStage
    from tests.contracts.test_diagnostics_runtime import CollectDiagnostics
    entered, release = asyncio.Event(), asyncio.Event()
    class Slow(Input):
        async def observe(self, snap):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return observed(snap)
    sink = CollectDiagnostics()
    value = actor(Slow())
    value._diagnostics = sink
    await submit(value)
    async with asyncio.timeout(1):
        await entered.wait()
    await value.stop(activity_seq=2, cutoff=0)
    release.set()
    await finish(value)
    terminals = [event for event in sink.events if event.stage == DiagnosticStage.INPUT_REVIEW
                 and event.outcome != DiagnosticOutcome.STARTED]
    assert len(terminals) == 1 and terminals[0].outcome == DiagnosticOutcome.CANCELLED
    assert "请看雨。" not in repr(sink.events)
    await value.close()


@pytest.mark.parametrize("reason,expected", [
    ("jev_input_authentication_failed", "unauthenticated"),
    ("jev_input_forbidden", "permission_denied"),
    ("jev_input_rate_limited", "quota_exhausted"),
    ("jev_input_timeout", "timeout"),
    ("jev_input_response_invalid", "invalid_response"),
    ("jev_input_transport_error", "unavailable"),
])
def test_input_review_fault_diagnostics_use_only_verified_reason_aliases(reason, expected):
    from mira.application.diagnostic_errors import classify_reason
    assert classify_reason(reason).code.value == expected
    assert classify_reason(reason + ": synthetic private server body").code.value == "unknown"
    assert "billing" not in classify_reason("jev_input_forbidden").message
