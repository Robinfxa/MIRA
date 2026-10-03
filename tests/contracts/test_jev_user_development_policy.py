"""Synthetic mechanics for the explicit user-selected JEV 0.6 development policy."""
from dataclasses import replace

import pytest

from mira.adapters.review.jev import JevReviewBackend
from mira.adapters.review.jev_input import JevInputDecisionBackend
from mira.application.contracts import CandidateRange, EffectProposal, ReviewVerdict
from mira.application.decision_contracts import (
    InputDecisionStatus, ResponseContractProducer, SemanticValue,
)
from mira.application.decision_runtime import SemanticReviewCoordinator
from mira.application.decision_policy import (
    DecisionThresholdPolicy, DecisionPolicyRef, USER_DEVELOPMENT_0_6_V1,
)
from mira.domain.models import EffectKind
from tests.contracts.test_decision_contracts import candidate, snapshot
from tests.contracts.test_jev_input import SyntheticTransport as InputTransport
from tests.contracts.test_jev_review import (
    MODEL, SyntheticTransport as OutputTransport, contract_for, inputs,
)


def _choice(choice: str, probability: float) -> dict:
    other = (1 - probability) / 2
    confidence = (probability - 1 / 3) / (1 - 1 / 3)
    return {
        "type": "choice", "choice": choice, "confidence": confidence,
        "probabilities": {name: probability if name == choice else other
                          for name in ("allow", "reject", "unknown")},
    }


def _referent_choice(choice: str, probability: float, confidence: float) -> dict:
    others = (1 - probability) / 2
    return {
        "type": "choice", "choice": choice, "confidence": confidence,
        "probabilities": {"photo-1": probability if choice == "photo-1" else others,
                          "none": probability if choice == "none" else others,
                          "ambiguous": probability if choice == "ambiguous" else others},
    }


def _output_backend(transport, **kwargs):
    return JevReviewBackend(transport=transport, model=MODEL, contract_resolver=contract_for,
        request_limit=1, decision_policy=USER_DEVELOPMENT_0_6_V1, **kwargs)


def _input_backend(transport, **kwargs):
    return JevInputDecisionBackend(transport=transport, model=MODEL, request_limit=1,
        decision_policy=USER_DEVELOPMENT_0_6_V1, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("probability", [0.5999, 0.6, 0.6001])
async def test_output_probability_boundaries_do_not_bypass_confidence(probability):
    def mutate(response):
        response["answers"] = {key: _choice("allow", probability)
                               for key in response["answers"]}
    result = await _output_backend(OutputTransport(mutate)).review_detailed(*inputs())
    # For this 3-option wire statistic, confidence is about 0.4 at p=0.6.
    # Both user-selected thresholds apply; probability alone cannot admit.
    assert result.observation.verdict == ReviewVerdict.UNKNOWN
    assert result.observation.reason_code == "jev_user_development_0_6_v1_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence,expected", [
    (0.5999, ReviewVerdict.UNKNOWN),
    (0.6, ReviewVerdict.ALLOW),
    (0.6001, ReviewVerdict.ALLOW),
])
async def test_output_confidence_boundaries_allow_without_calibration(confidence, expected):
    probability = 1 / 3 + confidence * (1 - 1 / 3)
    def mutate(response):
        response["answers"] = {key: _choice("allow", probability)
                               for key in response["answers"]}
    transport = OutputTransport(mutate)
    result = await _output_backend(transport).review_detailed(*inputs())
    assert result.observation.verdict == expected
    assert result.observation.reason_code == (
        "jev_user_development_0_6_v1_allow" if expected == ReviewVerdict.ALLOW
        else "jev_user_development_0_6_v1_unknown")
    assert len(transport.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("label,expected", [
    ("reject", ReviewVerdict.REJECT), ("unknown", ReviewVerdict.UNKNOWN),
])
async def test_high_confidence_reject_and_unknown_labels_keep_their_meaning(label, expected):
    def mutate(response):
        response["answers"] = {key: _choice(label, 0.9) for key in response["answers"]}
    result = await _output_backend(OutputTransport(mutate)).review_detailed(*inputs())
    assert result.observation.verdict == expected
    assert result.observation.reason_code == f"jev_user_development_0_6_v1_{label}"


@pytest.mark.asyncio
async def test_development_reject_label_survives_low_confidence():
    confidence = 0.5999
    probability = 1 / 3 + confidence * (1 - 1 / 3)
    def mutate(response):
        response["answers"] = {key: _choice("reject", probability)
                               for key in response["answers"]}
    result = await _output_backend(OutputTransport(mutate)).review_detailed(*inputs())
    assert result.observation.verdict == ReviewVerdict.REJECT
    assert result.observation.reason_code == "jev_user_development_0_6_v1_reject"


@pytest.mark.asyncio
async def test_selected_policy_cannot_allow_a_revoked_output_contract():
    state = {"current": True}
    class RevokingTransport(OutputTransport):
        async def __call__(self, payload, **kwargs):
            response = await super().__call__(payload, **kwargs)
            state["current"] = False
            return response
    transport = RevokingTransport()
    review = JevReviewBackend(transport=transport, model=MODEL,
        contract_resolver=lambda context, proposal: (
            contract_for(context, proposal) if state["current"] else None),
        request_limit=1, decision_policy=USER_DEVELOPMENT_0_6_V1)
    result = await review.review_detailed(*inputs())
    assert result.observation.verdict == ReviewVerdict.UNKNOWN
    assert result.observation.reason_code == "jev_contract_stale"
    assert len(transport.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("probability,expected", [
    (0.5999, SemanticValue.UNKNOWN), (0.6, SemanticValue.YES),
    (0.6001, SemanticValue.YES), (0.4001, SemanticValue.UNKNOWN),
    (0.4, SemanticValue.NO), (0.3999, SemanticValue.NO),
])
async def test_noul_thresholds_mean_prohibition_yes_and_absence_no(probability, expected):
    def mutate(body):
        key = next(key for key in body["answers"] if key.endswith("capture_restriction"))
        body["answers"][key]["noul"] = probability
    result = await _input_backend(InputTransport(mutate)).observe(snapshot())
    actual = next(item.value for item in result.predicates
                  if item.predicate == "capture_restriction")
    assert actual == expected
    assert result.status == (InputDecisionStatus.UNKNOWN if expected == SemanticValue.UNKNOWN
                             else InputDecisionStatus.OBSERVED)
    assert result.calibration_ref is None
    assert result.decision_policy_ref == DecisionPolicyRef.USER_DEVELOPMENT_0_6_V1


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence,expected", [
    (0.5999, "unknown"), (0.6, "resolved"), (0.6001, "resolved"),
])
async def test_referent_confidence_boundaries_preserve_supported_identity(confidence, expected):
    probability = 1 / 3 + confidence * (1 - 1 / 3)
    def mutate(body):
        key = next(key for key in body["answers"] if key.endswith("referent"))
        body["answers"][key] = _referent_choice("photo-1", probability, confidence)
    result = await _input_backend(InputTransport(mutate)).observe(snapshot())
    assert result.referent.status == expected
    assert result.referent.referent_id == ("photo-1" if expected == "resolved" else None)
    assert result.status == (InputDecisionStatus.OBSERVED if expected == "resolved"
                             else InputDecisionStatus.UNKNOWN)
    if expected == "resolved":
        snap = snapshot()
        assert ResponseContractProducer().produce(
            snap.context, candidate(), snapshot=snap, observation=result) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("probabilities,expected_status,contract_expected", [
    ({"photo-1": 0.73, "none": 0.14, "ambiguous": 0.13},
     InputDecisionStatus.OBSERVED, True),
    ({"photo-1": 0.72, "none": 0.14, "ambiguous": 0.14},
     InputDecisionStatus.INVALID, False),
])
async def test_cent_grid_referent_validator_matches_adapter_intervals(
    probabilities, expected_status, contract_expected,
):
    snap = snapshot()
    def mutate(body):
        key = next(key for key in body["answers"] if key.endswith("referent"))
        body["answers"][key] = {
            "type": "choice", "choice": "photo-1", "confidence": 0.60,
            "probabilities": probabilities,
        }
    observation = await _input_backend(InputTransport(mutate)).observe(snap)
    assert observation.status == expected_status
    contract = ResponseContractProducer().produce(
        snap.context, candidate(), snapshot=snap, observation=observation)
    assert (contract is not None) is contract_expected


@pytest.mark.asyncio
@pytest.mark.parametrize("probability", [0.5999, 0.6, 0.6001])
async def test_referent_probability_boundaries_do_not_invent_confidence(probability):
    confidence = (probability - 1 / 3) / (1 - 1 / 3)
    def mutate(body):
        key = next(key for key in body["answers"] if key.endswith("referent"))
        body["answers"][key] = _referent_choice("photo-1", probability, confidence)
    result = await _input_backend(InputTransport(mutate)).observe(snapshot())
    # At p ~= 0.6 the reported Choice statistic is only ~= 0.4. Both gates apply.
    assert result.status == InputDecisionStatus.UNKNOWN
    assert result.referent.status == "unknown"


@pytest.mark.asyncio
async def test_high_confidence_ambiguous_referent_never_becomes_resolved():
    def mutate(body):
        key = next(key for key in body["answers"] if key.endswith("referent"))
        body["answers"][key] = _referent_choice("ambiguous", 0.9, 0.85)
    result = await _input_backend(InputTransport(mutate)).observe(snapshot())
    assert result.status == InputDecisionStatus.UNKNOWN
    assert result.referent.status == "ambiguous"
    assert result.referent.referent_id is None


@pytest.mark.asyncio
async def test_high_scoring_unpresented_referent_is_not_an_observation():
    original = snapshot()
    photo = original.presentation_facts[0]
    unpresented = replace(original, context=replace(original.context, presented_effects=()),
                          presentation_facts=(replace(photo, status="partial"),
                                              *original.presentation_facts[1:]))
    result = await _input_backend(InputTransport()).observe(unpresented)
    assert result.status == InputDecisionStatus.UNKNOWN
    assert result.reason_code == "jev_input_semantic_unknown"
    assert result.referent.status == "resolved"  # the wire answer is retained, not trusted
    assert ResponseContractProducer().produce(
        unpresented.context, candidate(), snapshot=unpresented, observation=result) is None


@pytest.mark.asyncio
async def test_development_observation_enters_contract_without_fake_calibration_and_keeps_bounds():
    snap = snapshot()
    observation = await _input_backend(InputTransport()).observe(snap)
    assert observation.status == InputDecisionStatus.OBSERVED
    assert observation.calibration_ref is None
    assert observation.decision_policy_ref == DecisionPolicyRef.USER_DEVELOPMENT_0_6_V1
    contract = ResponseContractProducer().produce(
        snap.context, candidate(), snapshot=snap, observation=observation)
    assert contract is not None
    assert "不要拍我。" in contract.effective_constraints
    assert snap.context.user_text in contract.effective_constraints
    forged = replace(observation, decision_policy_ref="user-development-0.7-v1")
    assert ResponseContractProducer().produce(
        snap.context, candidate(), snapshot=snap, observation=forged) is None


@pytest.mark.asyncio
async def test_explicit_development_policy_runs_through_semantic_coordinator():
    snap = snapshot()
    input_transport = InputTransport()
    def allow_threshold_answers(response):
        response["answers"] = {key: _choice("allow", 0.7334)
                               for key in response["answers"]}
    output_transport = OutputTransport(allow_threshold_answers)
    input_backend = _input_backend(input_transport)
    output_backend = JevReviewBackend(transport=output_transport, model=MODEL,
        contract_resolver=lambda *_: None, request_limit=1,
        decision_policy=USER_DEVELOPMENT_0_6_V1)
    coordinator = SemanticReviewCoordinator(input_backend, output_backend)
    observation = await coordinator.observe(snap)
    result = await coordinator.review(snap, candidate(), observation)
    assert observation.status == InputDecisionStatus.OBSERVED
    assert observation.calibration_ref is None
    assert observation.decision_policy_ref == DecisionPolicyRef.USER_DEVELOPMENT_0_6_V1
    assert result.verdict == ReviewVerdict.ALLOW
    assert result.reason_code == "jev_user_development_0_6_v1_allow"
    assert len(input_transport.calls) == len(output_transport.calls) == 1


@pytest.mark.asyncio
async def test_semantic_coordinator_stop_still_preempts_both_selected_adapters():
    snap = replace(snapshot(), local_stop=True)
    input_transport, output_transport = InputTransport(), OutputTransport()
    input_backend = _input_backend(input_transport)
    output_backend = JevReviewBackend(transport=output_transport, model=MODEL,
        contract_resolver=lambda *_: None, request_limit=1,
        decision_policy=USER_DEVELOPMENT_0_6_V1)
    coordinator = SemanticReviewCoordinator(input_backend, output_backend)
    observation = await coordinator.observe(snap)
    result = await coordinator.review(snap, candidate(), observation)
    assert observation.status == InputDecisionStatus.UNAVAILABLE
    assert observation.reason_code == "semantic_local_stop"
    assert result.verdict == ReviewVerdict.UNKNOWN
    assert not input_transport.calls and not output_transport.calls


@pytest.mark.asyncio
async def test_selected_policy_does_not_override_speech_or_photography_prohibitions():
    snap = snapshot()
    def prohibit_speech(body):
        for key, answer in body["answers"].items():
            if key.endswith("speech_restriction"):
                answer["noul"] = 0.6
    speech_observation = await _input_backend(InputTransport(prohibit_speech)).observe(snap)
    assert speech_observation.status == InputDecisionStatus.OBSERVED
    assert {item.predicate: item.value for item in speech_observation.predicates}["speech_restriction"] \
        == SemanticValue.YES
    speech = CandidateRange((EffectProposal(EffectKind.SPEECH, "不应发声"),), "speech-1")
    producer = ResponseContractProducer()
    assert producer.produce(snap.context, speech, snapshot=snap,
                            observation=speech_observation) is None

    def prohibit_capture(body):
        for key, answer in body["answers"].items():
            if key.endswith("capture_restriction"):
                answer["noul"] = 0.6
            elif key.endswith("speech_restriction"):
                answer["noul"] = 0.0
    capture_observation = await _input_backend(InputTransport(prohibit_capture)).observe(snap)
    values = {item.predicate: item.value for item in capture_observation.predicates}
    assert capture_observation.status == InputDecisionStatus.OBSERVED
    assert values["speech_restriction"] == SemanticValue.NO
    assert values["capture_restriction"] == SemanticValue.YES
    safe_contract = producer.produce(snap.context, candidate(), snapshot=snap,
                                     observation=capture_observation)
    assert safe_contract is not None
    assert snap.context.user_text in safe_contract.effective_constraints
    photo = CandidateRange((EffectProposal(EffectKind.MEDIA, "不应拍摄"),), "photo-2")
    assert producer.produce(snap.context, photo, snapshot=snap,
                            observation=capture_observation) is None


@pytest.mark.asyncio
async def test_selected_policy_does_not_call_provider_after_local_stop():
    transport = InputTransport()
    result = await _input_backend(transport).observe(replace(snapshot(), local_stop=True))
    assert result.status == InputDecisionStatus.UNAVAILABLE
    assert result.reason_code == "jev_input_local_stop"
    assert not transport.calls


@pytest.mark.asyncio
async def test_selected_policy_cannot_observe_a_snapshot_revoked_during_request():
    current = iter((True, False))
    transport = InputTransport()
    result = await _input_backend(transport,
        snapshot_is_current=lambda _snapshot: next(current)).observe(snapshot())
    assert result.status == InputDecisionStatus.STALE
    assert result.reason_code == "jev_input_snapshot_stale"
    assert result.calibration_ref is None
    assert result.decision_policy_ref is None
    assert len(transport.calls) == 1


def test_policy_is_typed_versioned_and_rejects_threshold_forgery():
    assert USER_DEVELOPMENT_0_6_V1.reference == "user-development-0.6-v1"
    assert DecisionPolicyRef.USER_DEVELOPMENT_0_6_V1 == "user-development-0.6-v1"
    altered = replace(USER_DEVELOPMENT_0_6_V1, choice_probability_min=0.59)
    untyped_reference = replace(USER_DEVELOPMENT_0_6_V1,
                                reference="user-development-0.6-v1")
    with pytest.raises(ValueError, match="jev_configuration_invalid"):
        JevReviewBackend(transport=OutputTransport(), model=MODEL,
                         decision_policy=altered, request_limit=1)
    with pytest.raises(ValueError, match="jev_configuration_invalid"):
        JevReviewBackend(transport=OutputTransport(), model=MODEL,
                         decision_policy=untyped_reference, request_limit=1)
    with pytest.raises(ValueError, match="jev_configuration_invalid"):
        JevReviewBackend(transport=OutputTransport(), model=MODEL,
                         calibration_ref="fake-calibration",
                         decision_policy=USER_DEVELOPMENT_0_6_V1, request_limit=1)
    with pytest.raises(ValueError, match="jev_input_configuration_invalid"):
        JevInputDecisionBackend(transport=InputTransport(), model=MODEL,
                                decision_policy=altered, request_limit=1)
    with pytest.raises(ValueError, match="jev_input_configuration_invalid"):
        JevInputDecisionBackend(transport=InputTransport(), model=MODEL,
                                decision_policy=untyped_reference, request_limit=1)
    with pytest.raises(ValueError, match="jev_input_configuration_invalid"):
        JevInputDecisionBackend(transport=InputTransport(), model=MODEL,
                                calibration_ref="fake-calibration",
                                decision_policy=USER_DEVELOPMENT_0_6_V1, request_limit=1)
