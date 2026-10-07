"""Versioned reported-confidence mechanics; synthetic transports only."""
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics
from mira.adapters.review.jev import (
    JevHttpResponse, JevReviewBackend, OUTPUT_QUESTION_SET_V3, OUTPUT_QUESTION_SET_INTERACTION, _choice, _questions,
    candidate_digest, context_digest,
)
from mira.adapters.review.jev_input import (
    INPUT_QUESTION_SET_V2, JevInputDecisionBackend, _parse as parse_input,
    _questions as input_questions,
)
from mira.application.choice_wire_policy import (
    CHOICE_WIRE_POLICY_LEGACY_STRICT, CHOICE_WIRE_POLICY_REPORTED_V2,
)
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext, ReviewVerdict
from mira.application.decision_contracts import (
    ChoiceProbability, InputDecisionObservation, InputDecisionStatus, PredicateObservation,
    ReferentObservation, SemanticValue, _usable_observation, evidence_digest,
)
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
from mira.bootstrap.development_app import create_development_app
from mira.bootstrap.development_review import create_development_review_providers
from mira.config.settings import Settings
from mira.domain.models import EffectKind
from tests.contracts.test_codex_generation import (
    SyntheticTransport as CodexTransport, agent, event, terminal,
)
from tests.contracts.test_decision_contracts import snapshot
from tests.contracts.test_development_app_entry import public_runtime, wait_ready
from tests.contracts.test_development_review_composition import SyntheticJevTransport as InputTransport
from tests.contracts.test_jev_review import MODEL, contract_for, inputs


def reported(choice="allow", probability=0.83, confidence=0.76):
    # This concrete wire example intentionally sums to one and is not a witness for
    # TypeSafe's derived confidence formula.
    values = {"allow": 0.83, "reject": 0.09, "unknown": 0.08}
    if choice != "allow":
        values[choice] = probability
        values["allow"] = 0.09
        values["unknown"] = 0.08
        values["reject"] = 0.09 if choice != "reject" else 0.83
    return {"type": "choice", "choice": choice, "confidence": confidence,
            "probabilities": values}


def output_body(probabilities=None, confidence=0.76):
    probabilities = probabilities or {"allow": 0.83, "reject": 0.09, "unknown": 0.08}
    answer = {"type": "choice", "choice": "allow", "confidence": confidence,
              "probabilities": probabilities}
    return json.dumps({"model": MODEL, "answers": {"question:o1": answer},
                       "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()


def test_legacy_and_reported_policy_admit_same_wire_differently():
    wire = reported()
    with pytest.raises(ValueError, match="inconsistent_confidence"):
        _choice(wire)
    parsed = _choice(wire, CHOICE_WIRE_POLICY_REPORTED_V2)
    assert parsed == ("allow", 0.83, 0.76)
    assert wire["probabilities"] == {"allow": 0.83, "reject": 0.09, "unknown": 0.08}
    assert wire["confidence"] == 0.76
    with pytest.raises(ValueError, match="choice_wire_policy_unsupported"):
        _choice(wire, "jev-reported-confidence-v99")


def test_versioned_parser_keeps_probability_and_confidence_values_unchanged():
    from mira.adapters.review.jev import _parse_response

    body = output_body()
    with pytest.raises(ValueError, match="inconsistent_confidence"):
        _parse_response(body, MODEL, {"question:o1"})
    parsed, _ = _parse_response(body, MODEL, {"question:o1"},
                                choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2)
    assert parsed == [("allow", 0.83, 0.76)]
    assert JevReviewBackend(transport=None, model=MODEL)._choice_wire_policy_version == (
        CHOICE_WIRE_POLICY_LEGACY_STRICT)
    assert JevInputDecisionBackend(transport=None, model=MODEL)._choice_wire_policy_version == (
        CHOICE_WIRE_POLICY_LEGACY_STRICT)


@pytest.mark.parametrize("bad", [
    {"allow": 0.70, "reject": 0.28, "unknown": 0.00},
    {"allow": 0.70, "reject": 0.31, "unknown": 0.01},
    {"allow": float("nan"), "reject": 0.0, "unknown": 0.0},
    {"allow": -0.01, "reject": 1.0, "unknown": 0.01},
    {"allow": True, "reject": 0, "unknown": 0},
    {"allow": 0.83, "reject": 0.09, "extra": 0.08},
])
def test_nonconfidence_structure_and_probability_gates_stay_hard(bad):
    answer = {"type": "choice", "choice": "allow", "confidence": 0.76,
              "probabilities": bad}
    with pytest.raises(ValueError):
        _choice(answer, CHOICE_WIRE_POLICY_REPORTED_V2)
    with pytest.raises(ValueError, match="choice_not_maximum"):
        _choice({"type": "choice", "choice": "reject", "confidence": 0.76,
                 "probabilities": {"allow": 0.83, "reject": 0.09, "unknown": 0.08}},
                CHOICE_WIRE_POLICY_REPORTED_V2)


@pytest.mark.parametrize("answer", [
    {"type": "choice", "choice": "allow", "confidence": True,
     "probabilities": {"allow": 0.83, "reject": 0.09, "unknown": 0.08}},
    {"type": "choice", "choice": "allow", "confidence": -0.01,
     "probabilities": {"allow": 0.83, "reject": 0.09, "unknown": 0.08}},
    {"type": "choice", "choice": "allow", "confidence": float("nan"),
     "probabilities": {"allow": 0.83, "reject": 0.09, "unknown": 0.08}},
    {"type": "choice", "choice": "allow", "confidence": 0.76,
     "probabilities": {"allow": 0.83, "reject": 0.09, "unknown": 0.08}, "extra": 1},
])
def test_bad_confidence_and_wrong_choice_fields_stay_hard(answer):
    with pytest.raises(ValueError):
        _choice(answer, CHOICE_WIRE_POLICY_REPORTED_V2)


class ReviewTransport:
    def __init__(self, *, weak_confidence=None, explicit_ban=False, reject_o3=False):
        self.calls = []
        self.weak_confidence = weak_confidence
        self.explicit_ban = explicit_ban
        self.reject_o3 = reject_o3

    async def __call__(self, payload, **_kwargs):
        request = json.loads(payload)
        self.calls.append(request)
        answers = {}
        for key, question in request["questions"].items():
            suffix = key.rsplit(":", 1)[-1]
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.0}
            elif suffix == "o6":
                answers[key] = reported(confidence=(self.weak_confidence
                    if self.weak_confidence is not None else 0.76))
            elif suffix == "o4" and self.explicit_ban:
                answers[key] = reported("reject", confidence=0.76)
            elif suffix == "o3" and self.reject_o3:
                answers[key] = reported("reject", confidence=0.76)
            else:
                maximum = 1.0
                confidence = 1.0
                answers[key] = {"type": "choice", "choice": "allow", "confidence": confidence,
                    "probabilities": {"allow": maximum, "reject": 0.0, "unknown": 0.0}}
        body = json.dumps({"model": MODEL, "answers": answers,
                           "usage": {"input_tokens": 2, "output_tokens": 1}}).encode()
        return JevHttpResponse(200, body)


def v3_backend(transport, context=None, candidate=None):
    context = context or inputs()[0]
    candidate = candidate or inputs()[1]
    contract = replace(contract_for(context, candidate), policy_revision=OUTPUT_QUESTION_SET_V3)
    return JevReviewBackend(transport=transport, model=MODEL,
        contract_resolver=lambda *_: contract, decision_policy=USER_DEVELOPMENT_0_6_V2,
        question_set_revision=OUTPUT_QUESTION_SET_V3,
        choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2, request_limit=1)


@pytest.mark.asyncio
@pytest.mark.parametrize(("probability", "confidence", "expected"), [
    (0.83, 0.5999, ReviewVerdict.UNKNOWN),
    (0.5999, 0.83, ReviewVerdict.UNKNOWN),
    (0.51, 0.99, ReviewVerdict.UNKNOWN),
    (0.99, 0.10, ReviewVerdict.UNKNOWN),
    (0.60, 0.60, ReviewVerdict.ALLOW),
    (0.6001, 0.6001, ReviewVerdict.ALLOW),
])
async def test_both_original_thresholds_are_still_required_and_reject_stays_reject(
    probability, confidence, expected,
):
    # Alter only the O6 reported values; all other questions are fully strong.
    context, candidate = inputs()
    contract = replace(contract_for(context, candidate), policy_revision="mira-output-v2")

    class ThresholdTransport:
        async def __call__(self, payload, **_kwargs):
            request = json.loads(payload)
            answers = {}
            for key in request["questions"]:
                suffix = key.rsplit(":", 1)[-1]
                if suffix == "o6":
                    probs = {"allow": probability, "reject": 1 - probability, "unknown": 0.0}
                    answers[key] = {"type": "choice", "choice": "allow", "confidence": confidence,
                                    "probabilities": probs}
                else:
                    answers[key] = {"type": "choice", "choice": "allow", "confidence": 1.0,
                                    "probabilities": {"allow": 1.0, "reject": 0.0, "unknown": 0.0}}
            return JevHttpResponse(200, json.dumps({"model": MODEL, "answers": answers,
                "usage": {"input_tokens": 1, "output_tokens": 1}}).encode())

    backend = JevReviewBackend(transport=ThresholdTransport(), model=MODEL,
        contract_resolver=lambda *_: contract, decision_policy=USER_DEVELOPMENT_0_6_V2,
        question_set_revision="mira-output-v2", choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2,
        request_limit=1)
    assert (await backend.review(context, candidate)).verdict == expected

@pytest.mark.asyncio
async def test_reported_confidence_policy_does_not_change_v3_explicit_ban():
    context, candidate = inputs()
    transport = ReviewTransport(explicit_ban=True)
    # The O4 reject is selected strongly in its exact reported triple.
    backend = v3_backend(transport, context, candidate)
    result = await backend.review(context, candidate)
    assert result.verdict == ReviewVerdict.REJECT


@pytest.mark.asyncio
async def test_v3_clear_no_skips_only_o3_under_reported_confidence_policy():
    context, candidate = inputs()
    result = await v3_backend(ReviewTransport(reject_o3=True), context, candidate).review(
        context, candidate)
    assert result.verdict == ReviewVerdict.ALLOW


def test_input_parser_uses_reported_profile_without_changing_noul_direction():
    snap = snapshot()
    questions = input_questions(snap, "synthetic-binding", INPUT_QUESTION_SET_V2)
    answers = {}
    for key, question in questions.items():
        if question["type"] == "noul":
            answers[key] = {"type": "noul", "noul": 0.0}
        else:
            values = {option: 0.0 for option in question["criteria"]}
            values["photo-1" if "photo-1" in values else sorted(values)[0]] = 0.99
            if "ambiguous" in values:
                values["ambiguous"] = 0.01
            answers[key] = {"type": "choice", "choice": ("photo-1" if "photo-1" in values else sorted(values)[0]),
                            "confidence": 0.60, "probabilities": values}
    body = json.dumps({"model": MODEL, "answers": answers,
                       "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()
    predicates, referent, _ = parse_input(body, MODEL, questions, USER_DEVELOPMENT_0_6_V2,
        choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2)
    assert {item.value for item in predicates} == {SemanticValue.NO}
    assert referent.status == "resolved" and referent.confidence == 0.60

    observation = InputDecisionObservation(
        snap.snapshot_id, evidence_digest(snap), InputDecisionStatus.OBSERVED, "synthetic",
        predicates, referent, question_set_revision=INPUT_QUESTION_SET_V2,
        decision_policy_ref=USER_DEVELOPMENT_0_6_V2.reference, model=MODEL,
        choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2,
    )
    assert _usable_observation(snap, observation)
    legacy = replace(observation, choice_wire_policy_version=CHOICE_WIRE_POLICY_LEGACY_STRICT)
    assert not _usable_observation(snap, legacy)


class AsgiReportedTransport:
    def __init__(self, *, confidence=0.76, explicit_ban=False):
        self.calls = []
        self.confidence = confidence
        self.explicit_ban = explicit_ban

    async def __call__(self, payload, **_kwargs):
        request = json.loads(payload)
        self.calls.append(request)
        answers = {}
        for key, question in request["questions"].items():
            suffix = key.rsplit(":", 1)[-1]
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.0}
            elif suffix == "o6":
                answers[key] = reported(confidence=self.confidence)
            elif self.explicit_ban and suffix == "o4":
                answers[key] = reported("reject", confidence=0.76)
            else:
                answers[key] = {"type": "choice", "choice": "allow", "confidence": 1.0,
                                "probabilities": {"allow": 1.0, "reject": 0.0, "unknown": 0.0}}
        return JevHttpResponse(200, json.dumps({"model": MODEL, "answers": answers,
            "usage": {"input_tokens": 2, "output_tokens": 1}}).encode())


class AsgiReportedInputTransport:
    def __init__(self):
        self.calls = []

    async def __call__(self, payload, **_kwargs):
        request = json.loads(payload)
        self.calls.append(request)
        answers = {}
        for key, question in request["questions"].items():
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.0}
            else:
                probabilities = {option: 0.0 for option in question["criteria"]}
                probabilities["none"] = 0.99
                probabilities["ambiguous"] = 0.01
                answers[key] = {"type": "choice", "choice": "none", "confidence": 0.60,
                                "probabilities": probabilities}
        return JevHttpResponse(200, json.dumps({"model": MODEL, "answers": answers,
            "usage": {"input_tokens": 2, "output_tokens": 1}}).encode())


@pytest.mark.asyncio
async def test_actual_development_asgi_allows_and_falls_back_with_safe_warning(tmp_path, monkeypatch):
    from mira.bootstrap import development_app as module
    from mira.application.choice_wire_policy import CHOICE_WIRE_POLICY_REPORTED_V2

    generation = {"effects": [
        {"kind": "subtitle", "value": "你好，我们一起听雨。"},
        {"kind": "pose", "value": "look_at_rain"},
    ]}
    codex = CodexTransport(events=[event("item/completed", item=agent(
        json.dumps(generation, ensure_ascii=False))), terminal()])

    async def codex_factory(*_):
        return codex

    original_create_app = module.create_app
    observations = []
    for label, confidence, expected_error in (
        ("allow", 0.76, None), ("fallback", 0.5999, "review_uncertain"),
    ):
        root = tmp_path / label
        sink = LocalDiagnostics(DiagnosticOptions(root), worker=False)
        monkeypatch.setattr(module, "create_app",
            lambda settings, _sink=sink, **kwargs: original_create_app(
                settings, **kwargs, diagnostics=_sink))
        output = AsgiReportedTransport(confidence=confidence)
        input_transport = AsgiReportedInputTransport()
        app = create_development_app(runtime=public_runtime(), settings=Settings(),
            route_kind="public", input_transport=input_transport, output_transport=output,
            authorized=True, decision_policy=USER_DEVELOPMENT_0_6_V2,
            codex_transport_factory=codex_factory)
        with TestClient(app) as client:
            created = client.post("/api/v1/sessions", json={
                "client_instance_id": str(uuid4())}).json()
            path = "/api/v1/sessions/" + created["session"]["session_id"]
            headers = {"X-Mira-Session-Token": created["session_token"]}
            submitted = client.post(path + "/inputs", headers=headers, json={
                "request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0,
                "text": "请写一句你好，并看看雨。 SYNTHETIC_NONCE_7719 SYNTHETIC_SECRET_7719",
            })
            assert submitted.status_code == 202
            state = wait_ready(client, path, headers)
        assert state["last_error"] == expected_error
        assert bool(state["active_grants"]) is (expected_error is None)
        assert all(call["state"]["contract"]["policy_revision"] == OUTPUT_QUESTION_SET_INTERACTION
                   for call in output.calls)
        assert codex.closed
        assert sink.flush()
        records = [json.loads(line) for file in (root / "events").glob("events-*.jsonl")
                   for line in file.read_text().splitlines()]
        candidates = [item for item in records
            if item.get("stage") == "output_review" and "response_validation" in item]
        assert candidates, f"No bounded output warning found: status={sink.status()}, records={records!r}"
        event_record = candidates[0]
        summary = event_record["response_validation"]
        assert summary["choice_wire_policy_version"] == CHOICE_WIRE_POLICY_REPORTED_V2
        warning = next(item for item in summary["answer_facts"]
                       if item["question_suffix"] == "o6")
        assert warning["confidence_consistent"] is False
        assert warning["confidence_mismatch_warning"] is True
        assert warning["selected_probability"] == 0.83
        assert warning["confidence"] == confidence
        input_event = next(item for item in records if item.get("stage") == "input_review"
                           and "reported_confidence_warning" in item)
        input_warning = input_event["reported_confidence_warning"]
        assert input_warning["choice_wire_policy_version"] == CHOICE_WIRE_POLICY_REPORTED_V2
        assert input_warning["maximum_probability"] == 0.99
        assert input_warning["confidence"] == 0.60
        assert input_warning["probability_sum"] == 1.0
        rendered = json.dumps(records, ensure_ascii=False)
        assert "SYNTHETIC_NONCE_7719" not in rendered
        assert "SYNTHETIC_SECRET_7719" not in rendered
        assert '"answers"' not in rendered and '"probabilities"' not in rendered
        assert all(question not in rendered for call in output.calls
                   for question in call["questions"])
        assert "probabilities\"" not in rendered and "headers" not in rendered
        observations.append(summary)
        sink.close()
    assert len(observations) == 2


def test_product_factory_keeps_constructor_default_legacy_and_selects_v2():
    class Generation:
        async def generate(self, _context):
            if False:
                yield None

    async def transport(*_args, **_kwargs):
        return JevHttpResponse(200, b"{}")

    providers = create_development_review_providers(
        generation=Generation(), input_transport=transport, output_transport=transport,
        authorized=True, decision_policy=USER_DEVELOPMENT_0_6_V2,
    )
    assert providers.review._choice_wire_policy_version == CHOICE_WIRE_POLICY_REPORTED_V2
    assert providers.semantic_review._input_decision._choice_wire_policy_version == (
        CHOICE_WIRE_POLICY_REPORTED_V2)
