"""Synthetic mechanics for the explicit versioned JEV 0.6 v2 policy."""
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from mira.adapters.review.jev import JevHttpResponse, JevReviewBackend
from mira.adapters.review.jev_input import JevInputDecisionBackend
from mira.application.contracts import CandidateRange, EffectProposal, ReviewVerdict
from mira.application.decision_contracts import (
    INPUT_QUESTION_SET_V2, InputDecisionStatus, ResponseContractProducer,
)
from mira.application.decision_policy import (
    DecisionPolicyRef, USER_DEVELOPMENT_0_6_V1,
    USER_DEVELOPMENT_0_6_V2, is_supported_development_policy,
)
from tests.contracts.test_decision_contracts import candidate, snapshot
from tests.contracts.test_jev_input import SyntheticTransport as InputTransport
from tests.contracts.test_jev_review import MODEL, contract_for, inputs
from tests.contracts.test_semantic_unknown_fallback import (
    InputTransport as AsgiInputTransport,
    _app, _await_state, _new_session, _submit,
)
from mira.domain.models import EffectKind


def _choice(choice: str, probability: float, confidence: float | None = None) -> dict:
    confidence = (confidence if confidence is not None else
                  (probability - 1 / 3) / (1 - 1 / 3))
    other = (1 - probability) / 2
    return {
        "type": "choice", "choice": choice, "confidence": confidence,
        "probabilities": {name: probability if name == choice else other
                          for name in ("allow", "reject", "unknown")},
    }


class OutputTransport:
    def __init__(self, choice="allow", probability=0.9, *, malformed=None):
        self.choice = choice
        self.probability = probability
        self.malformed = malformed
        self.calls = []

    async def __call__(self, payload, **_kwargs):
        request = json.loads(payload)
        self.calls.append(request)
        answers = {key: _choice(self.choice, self.probability)
                   for key in request["questions"]}
        if self.malformed is not None:
            first = answers[next(iter(answers))]
            if self.malformed == "nan_confidence":
                first["confidence"] = float("nan")
            elif self.malformed == "boolean_probability":
                first["probabilities"]["allow"] = True
            elif self.malformed == "negative_probability":
                first["probabilities"]["allow"] = -0.1
            elif self.malformed == "oversized_probability":
                first["probabilities"]["allow"] = 1.1
            elif self.malformed == "nan_probability":
                first["probabilities"]["allow"] = float("nan")
        body = json.dumps({"model": MODEL, "answers": answers,
                           "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()
        return JevHttpResponse(200, body)


def _backend(transport, policy=USER_DEVELOPMENT_0_6_V2):
    return JevReviewBackend(transport=transport, model=MODEL,
        contract_resolver=contract_for, request_limit=1, decision_policy=policy)


@pytest.mark.asyncio
@pytest.mark.parametrize("probability", [0.599, 0.6, 0.6001])
async def test_v2_allow_probability_boundaries_stay_unknown_when_confidence_is_low(probability):
    result = await _backend(OutputTransport("allow", probability)).review_detailed(*inputs())
    assert result.observation.verdict == ReviewVerdict.UNKNOWN
    assert result.observation.reason_code == "jev_user_development_0_6_v2_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(("confidence", "expected"), [
    (0.599, ReviewVerdict.UNKNOWN),
    (0.6, ReviewVerdict.ALLOW),
    (0.6001, ReviewVerdict.ALLOW),
])
async def test_v2_allow_confidence_boundary_is_inclusive(confidence, expected):
    probability = 1 / 3 + confidence * (1 - 1 / 3)
    result = await _backend(OutputTransport("allow", probability)).review_detailed(*inputs())
    assert result.observation.verdict == expected
    assert result.observation.reason_code == f"jev_user_development_0_6_v2_{expected.value}"


@pytest.mark.asyncio
@pytest.mark.parametrize(("probability", "expected"), [
    (0.599, ReviewVerdict.UNKNOWN), (0.6, ReviewVerdict.UNKNOWN),
    (0.6001, ReviewVerdict.UNKNOWN), (0.7333, ReviewVerdict.UNKNOWN),
    (0.7334, ReviewVerdict.REJECT),
])
async def test_v2_reject_needs_both_selected_probability_and_confidence(probability, expected):
    result = await _backend(OutputTransport("reject", probability)).review_detailed(*inputs())
    assert result.observation.verdict == expected
    assert result.observation.reason_code == f"jev_user_development_0_6_v2_{expected.value}"


@pytest.mark.asyncio
async def test_v2_unknown_label_never_becomes_allow():
    unknown = await _backend(OutputTransport("unknown", 0.9)).review_detailed(*inputs())
    assert unknown.observation.verdict == ReviewVerdict.UNKNOWN
    assert unknown.observation.reason_code == "jev_user_development_0_6_v2_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed_number", [
    "nan_confidence", "boolean_probability", "negative_probability",
    "oversized_probability", "nan_probability",
])
async def test_v2_malformed_numbers_fail_closed(malformed_number):
    malformed = await _backend(OutputTransport(malformed=malformed_number)).review_detailed(*inputs())
    assert malformed.observation.verdict == ReviewVerdict.UNKNOWN
    assert malformed.observation.reason_code == "jev_response_contract_invalid"


def test_exact_v2_policy_is_recognized_without_reinterpreting_v1():
    assert USER_DEVELOPMENT_0_6_V2.reference == "user-development-0.6-v2"
    assert DecisionPolicyRef.USER_DEVELOPMENT_0_6_V2 == "user-development-0.6-v2"
    assert is_supported_development_policy(USER_DEVELOPMENT_0_6_V1)
    assert is_supported_development_policy(USER_DEVELOPMENT_0_6_V2)
    assert USER_DEVELOPMENT_0_6_V1.reference == "user-development-0.6-v1"
    assert not is_supported_development_policy(replace(USER_DEVELOPMENT_0_6_V2,
                                                       confidence_min=0.59))


class WeakRejectTransport:
    def __init__(self):
        self.calls = []

    async def __call__(self, payload, **_kwargs):
        request = json.loads(payload)
        self.calls.append(request)
        # Reproduce the captured weak-reject statistics while keeping all
        # remaining probability mass normalized. Rounded 0.52 / 0.29 is valid.
        answers = {key: _choice("reject", 0.52, confidence=0.29)
                   for key in request["questions"]}
        body = json.dumps({"model": MODEL, "answers": answers,
                           "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()
        return JevHttpResponse(200, body)


def test_v2_weak_reject_uses_system_clarification_fallback_without_grant():
    output = WeakRejectTransport()
    app, input_transport, _unused, generation, coordinator = _app(
        input_transport=AsgiInputTransport(), output_transport=output,
        output_policy=USER_DEVELOPMENT_0_6_V2,
    )
    with TestClient(app) as client:
        path, headers = _new_session(client)
        assert _submit(client, path, headers, 1).status_code == 202
        state = _await_state(client, path, headers, lambda item: item["phase"] == "error")
    assert state["last_error"] == "review_uncertain"
    assert state["request_id"] is None and state["active_grants"] == []
    assert len(input_transport.calls) == len(output.calls) == generation.calls == 1
    assert coordinator.results[0].verdict == ReviewVerdict.UNKNOWN
    assert coordinator.results[0].reason_code == "jev_user_development_0_6_v2_unknown"


@pytest.mark.asyncio
async def test_v2_input_thresholds_and_deterministic_restrictions_remain_fail_closed():
    snap = snapshot()
    def prohibit_speech(body):
        key = next(key for key in body["answers"] if key.endswith("speech_restriction"))
        body["answers"][key]["noul"] = 0.6
    transport = InputTransport(prohibit_speech)
    backend = JevInputDecisionBackend(transport=transport, model=MODEL,
        decision_policy=USER_DEVELOPMENT_0_6_V2,
        question_set_revision=INPUT_QUESTION_SET_V2, request_limit=1)
    observation = await backend.observe(snap)
    assert observation.decision_policy_ref == DecisionPolicyRef.USER_DEVELOPMENT_0_6_V2
    assert observation.status == InputDecisionStatus.OBSERVED
    assert ResponseContractProducer().produce(
        snap.context,
        CandidateRange((EffectProposal(EffectKind.SPEECH, "hello"),), "speech-1"),
        snapshot=snap, observation=observation) is None


@pytest.mark.asyncio
async def test_v2_input_contract_uses_selected_thresholds_and_local_stop_still_preempts():
    snap = snapshot()
    def rounded_referent(body):
        key = next(key for key in body["answers"] if key.endswith("referent"))
        body["answers"][key] = {
            "type": "choice", "choice": "photo-1", "confidence": 0.60,
            "probabilities": {"photo-1": 0.73, "none": 0.14, "ambiguous": 0.13},
        }
        for key, answer in body["answers"].items():
            if key.endswith("speech_restriction"):
                answer["noul"] = 0.0
            elif key.endswith("capture_restriction"):
                answer["noul"] = 0.4
    transport = InputTransport(rounded_referent)
    backend = JevInputDecisionBackend(transport=transport, model=MODEL,
        decision_policy=USER_DEVELOPMENT_0_6_V2,
        question_set_revision=INPUT_QUESTION_SET_V2, request_limit=1)
    observation = await backend.observe(snap)
    assert observation.status == InputDecisionStatus.OBSERVED
    assert observation.reason_code == "jev_input_user_development_0_6_v2_observed"
    contract = ResponseContractProducer().produce(
        snap.context, candidate(), snapshot=snap, observation=observation)
    assert contract is not None

    stopped_transport = InputTransport()
    stopped_backend = JevInputDecisionBackend(transport=stopped_transport, model=MODEL,
        decision_policy=USER_DEVELOPMENT_0_6_V2,
        question_set_revision=INPUT_QUESTION_SET_V2, request_limit=1)
    stopped = await stopped_backend.observe(replace(snap, local_stop=True))
    assert stopped.status == InputDecisionStatus.UNAVAILABLE
    assert not stopped_transport.calls


@pytest.mark.asyncio
async def test_v2_capture_prohibition_does_not_authorize_media_or_other_deterministic_bypasses():
    snap = snapshot()
    def prohibit_capture(body):
        for key, answer in body["answers"].items():
            if key.endswith("speech_restriction"):
                answer["noul"] = 0.0
            elif key.endswith("capture_restriction"):
                answer["noul"] = 0.6
    observation = await JevInputDecisionBackend(transport=InputTransport(prohibit_capture),
        model=MODEL, decision_policy=USER_DEVELOPMENT_0_6_V2,
        question_set_revision=INPUT_QUESTION_SET_V2, request_limit=1).observe(snap)
    assert observation.status == InputDecisionStatus.OBSERVED
    media = CandidateRange((EffectProposal(EffectKind.MEDIA, "photo"),), "media-1")
    assert ResponseContractProducer().produce(
        snap.context, media, snapshot=snap, observation=observation) is None
