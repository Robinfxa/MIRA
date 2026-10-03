"""Synthetic composition mechanics; never Chinese calibration or device evidence."""
import json
from dataclasses import asdict, replace

import pytest

from mira.adapters.review.jev import (
    JevReviewBackend, JevReviewContract, QUESTION_SET_VERSION, candidate_digest, context_digest,
)
from mira.application.contracts import GenerationContext, ReviewVerdict
from mira.application.decision_contracts import (
    InputDecisionStatus, ReliableUserInput, ResponseContractProducer, evidence_digest,
    mira26_author_policy, valid_snapshot,
)
from mira.application.decision_runtime import (
    DecisionSnapshotOwner, SemanticReviewCoordinator, snapshot_matches_state, snapshot_same_branch,
)
from mira.domain import transitions
from mira.domain.models import AudioProgress, AudioStatus, Effect, EffectKind, Receipt, SessionState
from tests.contracts.test_decision_contracts import candidate, observation, snapshot
from tests.contracts.test_jev_review import MODEL, SyntheticTransport


def owner_state():
    state = transitions.begin_input(SessionState("session", "browser"), activity_seq=1,
                                    cutoff=0, request_id="input-1", text="请介绍雨。")
    visual = Effect("visual-1", EffectKind.SUBTITLE, "下雨了。", "visual-digest", 1, 1)
    speech = Effect("speech-1", EffectKind.SPEECH, "下雨了。", "speech-digest", 1, 1)
    state = transitions.accept_range(state, output_epoch=1, effects=(visual, speech))
    state = transitions.record_receipt(state, Receipt(visual.id, visual.digest, 1, 1, 1))
    state = transitions.record_audio_progress(state, AudioProgress(
        speech.id, speech.digest, 1, 1, 2, 24000, 2400, AudioStatus.RENDERED))
    return state, (ReliableUserInput("input-1", "请介绍雨。", "asr_final"),)


def typed_contract(snap=None, obs=None):
    snap = snap or snapshot()
    return ResponseContractProducer().produce(snap.context, candidate(), snapshot=snap,
                                              observation=obs or observation(snap))


def output_backend(transport, **kwargs):
    return JevReviewBackend(transport=transport, model=MODEL, contract_resolver=lambda *_: None,
        request_limit=10, calibration_ref="synthetic-output-test-only", **kwargs)


def test_owner_snapshot_preserves_reliable_events_and_actual_partial_audio():
    state, events = owner_state()
    snap = DecisionSnapshotOwner(mira26_author_policy()).snapshot(state, events)
    assert snap is not None and valid_snapshot(snap)
    assert snap.reliable_inputs == events
    assert snap.context.accepted_prefix == state.active_grants
    assert snap.context.presented_effects == state.presented_effects
    assert snap.context.audio_progress == state.audio_progress
    assert [fact.status for fact in snap.presentation_facts] == ["presented", "partial"]
    assert all(fact.observed_text is None for fact in snap.presentation_facts)
    assert snap.input_revision == 1 and snap.generation_id == "input-1"


def test_owner_never_invents_missing_input_event_or_issued_effect_identity():
    state, events = owner_state()
    owner = DecisionSnapshotOwner(mira26_author_policy())
    assert owner.snapshot(state, ()) is None
    assert owner.snapshot(state, (replace(events[0], text="invented"),)) is None
    assert owner.snapshot(replace(state, issued_effects=state.issued_effects[:1]), events) is None


def test_owner_keeps_original_directives_and_controlled_referents_without_string_packing():
    snap = snapshot()
    state, events = owner_state()
    owner = DecisionSnapshotOwner(snap.author_policy, snap.effective_constraints,
                                   snap.response_obligations)
    built = owner.snapshot(state, events)
    assert built is not None
    assert built.effective_constraints == snap.effective_constraints
    assert built.author_policy == snap.author_policy


def test_currentness_ignores_unrelated_revision_but_rebuilds_changed_presentation():
    state, events = owner_state()
    snap = DecisionSnapshotOwner(mira26_author_policy()).snapshot(state, events)
    assert snap is not None
    assert snapshot_matches_state(replace(state, revision=state.revision + 1), snap)
    advanced = replace(state, audio_progress=state.audio_progress + (
        replace(state.audio_progress[-1], presentation_seq=3, rendered_samples=4800),))
    assert snapshot_same_branch(advanced, snap)
    assert not snapshot_matches_state(advanced, snap)
    for changed in (replace(state, input_epoch=2), replace(state, activity_seq=2),
                    replace(state, request_id="new"), replace(state, output_epoch=2)):
        assert not snapshot_same_branch(changed, snap)
        assert not snapshot_matches_state(changed, snap)


class InputSpy:
    def __init__(self, result):
        self.result, self.calls = result, []

    async def observe(self, snap):
        self.calls.append(snap)
        return self.result


class OutputSpy:
    def __init__(self):
        self.calls = []

    async def review_contract(self, context, proposal, contract):
        self.calls.append((context, proposal, contract))
        from mira.application.contracts import ReviewObservation
        return ReviewObservation(ReviewVerdict.ALLOW, "synthetic")


@pytest.mark.asyncio
async def test_composition_preserves_complete_contract_and_separate_await_boundaries():
    snap = snapshot()
    input_backend, output = InputSpy(observation(snap)), OutputSpy()
    coordinator = SemanticReviewCoordinator(input_backend, output)
    observed = await coordinator.observe(snap)
    assert observed == observation(snap) and not output.calls
    reviewed = await coordinator.review(snap, candidate(), observed, scope="seal")
    assert reviewed.verdict == ReviewVerdict.ALLOW
    contract = output.calls[0][2]
    assert contract.snapshot == snap and contract.input_observation == observed
    assert contract.scope == "seal"


@pytest.mark.asyncio
async def test_unknown_input_or_stop_never_reaches_output_review():
    snap = snapshot()
    unknown = replace(observation(snap), status=InputDecisionStatus.UNKNOWN, calibration_ref=None)
    input_backend, output = InputSpy(unknown), OutputSpy()
    coordinator = SemanticReviewCoordinator(input_backend, output)
    result = await coordinator.review(snap, candidate(), unknown)
    assert result.verdict == ReviewVerdict.UNKNOWN and not output.calls
    stopped = replace(snap, local_stop=True)
    result = await coordinator.observe(stopped)
    assert result.status == InputDecisionStatus.UNAVAILABLE and not input_backend.calls


@pytest.mark.asyncio
async def test_production_output_requires_typed_evidence_not_legacy_raw_arrays():
    snap = snapshot()
    raw = JevReviewContract("legacy", QUESTION_SET_VERSION, context_digest(snap.context),
        candidate_digest(candidate()), (), (snap.context.user_text,), ("成年角色",),
        allowed_controls=snap.author_policy.allowed_controls)
    transport = SyntheticTransport()
    backend = JevReviewBackend(transport=transport, model=MODEL, contract_resolver=lambda *_: raw,
                               request_limit=1, calibration_ref="synthetic-test-only")
    result = await backend.review(snap.context, candidate())
    assert result.verdict == ReviewVerdict.UNKNOWN and not transport.calls


@pytest.mark.asyncio
async def test_output_typed_snapshot_and_observation_serialize_without_loss():
    snap = snapshot()
    contract = typed_contract(snap)
    transport = SyntheticTransport()
    result = await output_backend(transport).review_contract(snap.context, candidate(), contract)
    assert result.verdict == ReviewVerdict.ALLOW
    data = transport.calls[0]["state"]["contract"]
    assert data["snapshot"] == json.loads(json.dumps(asdict(snap)))
    assert data["input_observation"] == json.loads(json.dumps(asdict(observation(snap))))
    assert data["basis_snapshot_digest"] == evidence_digest(snap)
    assert data["response_contract_digest"] == contract.contract_digest
    assert data["effective_constraints"] == list(contract.effective_constraints)
    assert data["snapshot"]["author_policy"]["policy_revision"] == contract.policy_revision
    assert data["policy_revision"] == QUESTION_SET_VERSION


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("contract_id", "forged"), ("contract_digest", "0" * 64),
    ("basis_snapshot_digest", "0" * 64), ("policy_revision", "forged"),
    ("effective_constraints", ("dropped original",)), ("response_obligations", ("forged",)),
    ("character_facts", ("forged",)), ("allowed_controls", ()),
])
async def test_mutated_application_contract_is_rejected_before_transport(field, value):
    snap = snapshot()
    transport = SyntheticTransport()
    bad = replace(typed_contract(snap), **{field: value})
    result = await output_backend(transport).review_contract(snap.context, candidate(), bad)
    assert result.verdict == ReviewVerdict.UNKNOWN and not transport.calls


@pytest.mark.asyncio
async def test_input_observation_for_other_snapshot_cannot_ride_output_contract():
    snap = snapshot()
    bad = replace(typed_contract(snap), input_observation=replace(observation(snap),
                                                                 snapshot_digest="0" * 64))
    transport = SyntheticTransport()
    result = await output_backend(transport).review_contract(snap.context, candidate(), bad)
    assert result.verdict == ReviewVerdict.UNKNOWN and not transport.calls


@pytest.mark.asyncio
async def test_typed_output_still_requires_separate_output_calibration():
    snap = snapshot()
    transport = SyntheticTransport()
    backend = JevReviewBackend(transport=transport, model=MODEL, contract_resolver=lambda *_: None,
                               request_limit=1)
    result = await backend.review_contract(snap.context, candidate(), typed_contract(snap))
    assert result.verdict == ReviewVerdict.UNKNOWN
    assert result.reason_code == "jev_policy_not_calibrated"


@pytest.mark.parametrize("corruption", ["receipt_missing", "receipt_digest", "active_missing"])
def test_owner_rejects_unbound_receipt_and_accepted_identities(corruption):
    state, events = owner_state()
    if corruption == "receipt_missing":
        state = replace(state, receipts=state.receipts + (Receipt("missing", "digest", 1, 1, 9),))
    elif corruption == "receipt_digest":
        state = replace(state, receipts=(replace(state.receipts[0], digest="forged"),))
    else:
        state = replace(state, active_grants=state.active_grants + (
            Effect("not-issued", EffectKind.POSE, "face_calm", "digest", 1, 1),))
    assert DecisionSnapshotOwner(mira26_author_policy()).snapshot(state, events) is None


@pytest.mark.asyncio
async def test_typed_and_synthetic_evidence_cannot_mix():
    from mira.adapters.review.jev import map_response_contract
    snap = snapshot()
    contract = replace(map_response_contract(typed_contract(snap)), synthetic=True)
    transport = SyntheticTransport()
    backend = JevReviewBackend(transport=transport, model=MODEL,
        contract_resolver=lambda *_: contract, request_limit=1,
        calibration_ref="synthetic-test-only")
    result = await backend.review(snap.context, candidate())
    assert result.verdict == ReviewVerdict.UNKNOWN and not transport.calls


@pytest.mark.asyncio
async def test_typed_resolver_change_after_output_wait_is_stale():
    from mira.adapters.review.jev import map_response_contract
    snap = snapshot()
    contract = map_response_contract(typed_contract(snap))
    current = contract
    async def transport(payload, **kwargs):
        nonlocal current
        current = replace(contract, input_observation=replace(observation(snap), reason_code="changed"))
        return await SyntheticTransport()(payload, **kwargs)
    backend = JevReviewBackend(transport=transport, model=MODEL,
        contract_resolver=lambda *_: current, request_limit=1, calibration_ref="synthetic-test-only")
    result = await backend.review(snap.context, candidate())
    assert result.verdict == ReviewVerdict.UNKNOWN and result.reason_code == "jev_contract_stale"


@pytest.mark.asyncio
async def test_per_call_typed_contract_mapping_has_no_shared_resolver_mutation():
    import asyncio
    first = snapshot()
    second = replace(first, snapshot_id="other-snapshot", event_watermark=8)
    transport = SyntheticTransport()
    backend = output_backend(transport)
    results = await asyncio.gather(
        backend.review_contract(first.context, candidate(), typed_contract(first)),
        backend.review_contract(second.context, candidate(), typed_contract(second)),
    )
    assert all(result.verdict == ReviewVerdict.ALLOW for result in results)
    assert {call["state"]["contract"]["snapshot"]["snapshot_id"] for call in transport.calls} == {
        first.snapshot_id, second.snapshot_id}
    assert backend._contract_resolver(first.context, candidate()) is None
