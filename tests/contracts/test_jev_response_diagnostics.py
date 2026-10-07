"""Synthetic JEV diagnostics through the real adapters, Actor, ASGI and recorder."""
import hashlib
import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4
import zipfile

import pytest
from fastapi.testclient import TestClient

from mira.adapters.diagnostics.export import export_diagnostics
from mira.adapters.diagnostics.privacy import encode_event, validate_event_record
from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics
from mira.adapters.review import jev
from mira.adapters.review.jev import JevHttpResponse, JevReviewBackend, JevReviewContract
from mira.adapters.review.jev_input import JevInputDecisionBackend
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext, ReviewObservation, ReviewVerdict
from mira.application.decision_contracts import (
    INPUT_QUESTION_SET_V2, mira26_author_policy,
)
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V1
from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
from mira.application.diagnostic_events import (
    DiagnosticContext, DiagnosticEvent, DiagnosticOutcome, DiagnosticStage, DiagnosticStatus,
)
from mira.bootstrap.providers import Providers
from mira.config.settings import Settings
from mira.domain.models import EffectKind
from mira.entrypoints.http.app import create_app

MODEL = "jev-1.13.0"
PRIVATE_MARKER = "SYNTHETIC_PROVIDER_CREDENTIAL_8801"


def output_inputs():
    context = GenerationContext(
        user_text="Synthetic request", user_inputs=("Synthetic request",),
        presented_effects=(), output_epoch=1,
    )
    candidate = CandidateRange(
        (EffectProposal(EffectKind.SUBTITLE, "Synthetic answer"),), "synthetic-candidate")
    contract = JevReviewContract(
        "synthetic-contract", jev.QUESTION_SET_VERSION, jev.context_digest(context),
        jev.candidate_digest(candidate), (), ("Synthetic request",), ("Adult fictional character",),
        synthetic=True,
    )
    return context, candidate, contract


def _choice(choice="allow", probability=1.0):
    remaining = (1.0 - probability) / 2
    return {
        "type": "choice", "choice": choice,
        "confidence": (probability - 1 / 3) / (1 - 1 / 3),
        "probabilities": {
            name: probability if name == choice else remaining
            for name in ("allow", "reject", "unknown")
        },
    }


class DirectOutputTransport:
    def __init__(self, *, choice="allow", malformed=False, raw_bad_number=None,
                 probability_values=None):
        self.choice, self.malformed, self.raw_bad_number = choice, malformed, raw_bad_number
        self.probability_values = probability_values
        self.calls = []
        self.last_body = None

    async def __call__(self, payload, *, timeout_seconds, max_response_bytes):
        request = json.loads(payload)
        self.calls.append(request)
        answers = {key: _choice(self.choice) for key in request["questions"]}
        first = sorted(answers)[0]
        if self.malformed:
            answers[first] = {
                "type": "choice", "choice": "allow", "confidence": 0.80,
                "probabilities": {"allow": 0.88, "reject": 0.12, "unknown": 0,
                                  "api_key": PRIVATE_MARKER},
            }
        elif self.probability_values is not None:
            for answer in answers.values():
                answer.update(choice="allow", confidence=0.55,
                              probabilities=self.probability_values)
        elif self.raw_bad_number is not None:
            answers[first]["probabilities"]["reject"] = "__RAW_NUMBER__"
        body = json.dumps({"model": MODEL, "answers": answers,
                           "usage": {"input_tokens": 2, "output_tokens": 1}},
                          separators=(",", ":")).encode()
        if self.raw_bad_number is not None:
            body = body.replace(b'"__RAW_NUMBER__"', self.raw_bad_number)
        self.last_body = body
        return JevHttpResponse(200, body)


def direct_backend(transport):
    context, candidate, contract = output_inputs()
    return JevReviewBackend(transport=transport, model=MODEL,
        contract_resolver=lambda *_: contract, request_limit=1, timeout_seconds=1), context, candidate


@pytest.mark.asyncio
async def test_output_response_summary_contains_only_bounded_safe_facts():
    transport = DirectOutputTransport(malformed=True)
    backend, context, candidate = direct_backend(transport)
    result = await backend.review_detailed(context, candidate)
    assert result.observation.verdict == ReviewVerdict.UNKNOWN
    assert result.observation.reason_code == "jev_response_contract_invalid"
    summary = result.observation.response_diagnostics
    assert summary.parser_reason == "probabilities"
    assert summary.expected_answer_count == len(transport.calls[0]["questions"])
    assert summary.answer_count == summary.expected_answer_count
    assert summary.invalid_probability_count == 1
    assert summary.response_bytes == len(transport.last_body)
    assert summary.response_sha256 == hashlib.sha256(transport.last_body).hexdigest()
    encoded = json.dumps(asdict(summary), allow_nan=False, sort_keys=True)
    assert PRIVATE_MARKER not in encoded
    assert "api_key" not in encoded and "headers" not in encoded
    assert all(question_key not in encoded for question_key in transport.calls[0]["questions"])
    assert {item.question_suffix for item in summary.answer_facts} <= {
        *(f"o{index}" for index in range(1, 7)), *(f"effect_{index}" for index in range(8)),
    }
    assert result.observation == ReviewObservation(ReviewVerdict.UNKNOWN,
                                                   "jev_response_contract_invalid")
    assert len(transport.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("probabilities", "expected_sum"), [
    # These sums are outside the exact cent-interval feasibility range.
    ({"allow": 0.70, "reject": 0.31, "unknown": 0.01}, 1.02),
    ({"allow": 0.70, "reject": 0.28, "unknown": 0.00}, 0.98),
])
async def test_invalid_probability_sum_and_selected_value_remain_observable(
    probabilities, expected_sum,
):
    transport = DirectOutputTransport(probability_values=probabilities)
    backend, context, candidate = direct_backend(transport)
    result = await backend.review_detailed(context, candidate)
    assert result.observation.verdict == ReviewVerdict.UNKNOWN
    assert result.observation.reason_code == "jev_response_contract_invalid"
    summary = result.observation.response_diagnostics
    assert (summary.probability_sum_range, summary.selected_probability_range) == (
        (expected_sum, expected_sum), (0.70, 0.70))
    assert len(summary.answer_facts) == summary.expected_answer_count
    assert {item.question_suffix for item in summary.answer_facts} <= {
        *(f"o{index}" for index in range(1, 7)), *(f"effect_{index}" for index in range(8)),
    }
    assert all(item.selected_probability == 0.70 and item.probability_sum == expected_sum
               and item.answer_reason.value == "probabilities" for item in summary.answer_facts)
    assert len(transport.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_number,expected_field", [
    (b"NaN", "nonfinite_numeric_count"),
    (str(10 ** 400).encode(), "oversized_integer_count"),
])
async def test_nonfinite_and_huge_probability_values_are_bounded(raw_number, expected_field):
    transport = DirectOutputTransport(raw_bad_number=raw_number)
    backend, context, candidate = direct_backend(transport)
    result = await backend.review_detailed(context, candidate)
    assert result.observation.verdict == ReviewVerdict.UNKNOWN
    assert result.observation.reason_code == "jev_response_contract_invalid"
    summary = result.observation.response_diagnostics
    assert getattr(summary, expected_field) >= 1
    assert len(json.dumps(asdict(summary), allow_nan=False)) < 8192
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_summary_failure_keeps_response_fail_closed(monkeypatch, caplog):
    transport = DirectOutputTransport(malformed=True)
    backend, context, candidate = direct_backend(transport)

    def broken(*_args, **_kwargs):
        raise RuntimeError(PRIVATE_MARKER)

    monkeypatch.setattr(jev, "summarize_response_validation", broken)
    result = await backend.review_detailed(context, candidate)
    assert result.observation.verdict == ReviewVerdict.UNKNOWN
    assert result.observation.reason_code == "jev_response_contract_invalid"
    assert result.observation.response_diagnostics is None
    assert len(transport.calls) == 1
    assert PRIVATE_MARKER not in caplog.text + repr(result)


class FixedGeneration:
    def __init__(self):
        self.calls = 0

    async def generate(self, context):
        self.calls += 1
        yield CandidateRange(
            (EffectProposal(EffectKind.SUBTITLE, "窗外正下着雨。"),), "asgi-synthetic")


class V2InputTransport:
    def __init__(self, *, invalid=False):
        self.calls, self.invalid, self.suffixes = [], invalid, set()

    async def __call__(self, payload, *, timeout_seconds, max_response_bytes):
        request = json.loads(payload)
        self.calls.append(request)
        questions = request["questions"]
        self.suffixes = {key.rsplit(":", 1)[-1] for key in questions}
        if self.invalid:
            return JevHttpResponse(200, b'{"model":"jev-1.13.0","answers":{},"usage":{}}')
        answers = {}
        for key, question in questions.items():
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.0}
            else:
                criteria = question["criteria"]
                selected = "none" if "none" in criteria else sorted(criteria)[0]
                probabilities = {name: 1.0 if name == selected else 0.0 for name in criteria}
                answers[key] = {"type": "choice", "choice": selected,
                    "confidence": 1.0, "probabilities": probabilities}
        body = json.dumps({"model": MODEL, "answers": answers,
                           "usage": {"input_tokens": 2, "output_tokens": 1}},
                          separators=(",", ":")).encode()
        return JevHttpResponse(200, body)


class AsgiOutputTransport:
    def __init__(self, *, outcome="invalid"):
        self.calls, self.outcome = [], outcome

    async def __call__(self, payload, *, timeout_seconds, max_response_bytes):
        request = json.loads(payload)
        self.calls.append(request)
        choice = "allow" if self.outcome == "invalid" else self.outcome
        answers = {
            key: ({"type": "noul", "noul": 0.0} if question["type"] == "noul"
                  else _choice(choice))
            for key, question in request["questions"].items()
        }
        if self.outcome == "invalid":
            first = next(key for key in sorted(answers) if key.endswith(":o1"))
            answers[first] = {
                "type": "choice", "choice": "allow", "confidence": 0.80,
                "probabilities": {"allow": 0.88, "reject": 0.12, "unknown": 0,
                                  "api_key": PRIVATE_MARKER},
            }
        body = json.dumps({"model": MODEL, "answers": answers,
                           "usage": {"input_tokens": 2, "output_tokens": 1}},
                          separators=(",", ":")).encode()
        return JevHttpResponse(200, body)


class BrokenDiagnostics:
    def emit(self, _event):
        raise OSError(PRIVATE_MARKER)

    def capture(self, _record):
        return False

    def capture_text(self, *_args):
        return False

    def add_secret(self, _value):
        return True

    def status(self):
        return DiagnosticStatus()

    def close(self):
        pass


def _providers(input_transport, output_transport, generation=None):
    generation = generation or FixedGeneration()
    input_backend = JevInputDecisionBackend(
        transport=input_transport, model=MODEL, decision_policy=USER_DEVELOPMENT_0_6_V1,
        request_limit=1, timeout_seconds=1, question_set_revision=INPUT_QUESTION_SET_V2)
    output_backend = JevReviewBackend(
        transport=output_transport, model=MODEL, decision_policy=USER_DEVELOPMENT_0_6_V1,
        request_limit=1, timeout_seconds=1)
    return Providers(generation, output_backend,
        semantic_review=SemanticReviewCoordinator(input_backend, output_backend),
        decision_owner=DecisionSnapshotOwner(mira26_author_policy()))


def _new_session(client):
    created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())})
    assert created.status_code == 201
    body = created.json()
    return ("/api/v1/sessions/" + body["session"]["session_id"],
            {"X-Mira-Session-Token": body["session_token"]})


def _read_events(root: Path):
    records = []
    for path in (root / "events").glob("events-*.jsonl"):
        records.extend(json.loads(line) for line in path.read_text().splitlines())
    return records


def _await_state(client, path, headers, predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        state = client.get(path, headers=headers).json()
        if predicate(state):
            return state
        time.sleep(.003)
    raise AssertionError("synthetic ASGI request did not reach terminal state")


def _hashed(value):
    return "h_" + hashlib.sha256(value.encode()).hexdigest()[:32]


def test_asgi_invalid_output_response_has_correlated_diagnostic_event(tmp_path):
    input_transport, output_transport, generation = (
        V2InputTransport(), AsgiOutputTransport(outcome="invalid"), FixedGeneration())
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), secrets=(PRIVATE_MARKER,), worker=False)
    app = create_app(Settings(), providers=_providers(input_transport, output_transport, generation),
                     diagnostics=sink)
    with TestClient(app) as client:
        path, headers = _new_session(client)
        submitted = client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": 1,
            "presentation_cutoff": 0, "text": "请介绍窗外的雨。",
        })
        assert submitted.status_code == 202
        state = _await_state(client, path, headers, lambda value: value["phase"] == "error")
        assert "referent_required" in input_transport.suffixes
        assert input_transport.calls and len(output_transport.calls) == 1
        assert generation.calls == 1
        assert state["last_error"] == "invalid_response"
        assert state["last_error_diagnostic_id"] == _hashed(submitted.headers["x-request-id"])
        assert state["request_id"] is None and state["active_grants"] == []
        assert sink.flush()
        records = _read_events(tmp_path)
        event = next(record for record in records if record["stage"] == "output_review"
            and record["outcome"] == "failed" and "response_validation" in record)
        assert event["context"]["request_id"] == state["last_error_diagnostic_id"]
        assert event["response_validation"]["parser_reason"] == "probabilities"
        assert PRIVATE_MARKER not in json.dumps(state) + json.dumps(records)
        assert len(output_transport.calls) == 1
    sink.close()


def test_logging_failure_keeps_response_fail_closed():
    input_transport = V2InputTransport()
    output_transport = AsgiOutputTransport(outcome="invalid")
    app = create_app(Settings(), providers=_providers(input_transport, output_transport),
                     diagnostics=BrokenDiagnostics())
    with TestClient(app) as client:
        path, headers = _new_session(client)
        response = client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": 1,
            "presentation_cutoff": 0, "text": "Synthetic request",
        })
        state = _await_state(client, path, headers, lambda value: value["phase"] == "error")
        assert response.status_code == 202
        assert state["last_error"] == "invalid_response"
        assert state["active_grants"] == [] and state["request_id"] is None
        assert len(output_transport.calls) == 1
        assert PRIVATE_MARKER not in json.dumps(state)


@pytest.mark.parametrize(("choice", "expected"), [
    ("reject", "review_not_allowed"), ("unknown", "review_uncertain"),
])
def test_semantic_reject_and_unknown_have_distinct_error_codes(tmp_path, choice, expected):
    input_transport = V2InputTransport()
    output_transport = AsgiOutputTransport(outcome=choice)
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    app = create_app(Settings(), providers=_providers(input_transport, output_transport), diagnostics=sink)
    with TestClient(app) as client:
        path, headers = _new_session(client)
        response = client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": 1,
            "presentation_cutoff": 0, "text": "Synthetic request",
        })
        state = _await_state(client, path, headers, lambda value: value["phase"] == "error")
        assert state["last_error"] == expected
        assert state["active_grants"] == [] and state["request_id"] is None
        assert response.status_code == 202 and len(output_transport.calls) == 1
    sink.close()


def test_input_invalid_response_remains_a_technical_failure(tmp_path):
    input_transport = V2InputTransport(invalid=True)
    output_transport = AsgiOutputTransport(outcome="allow")
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    app = create_app(Settings(), providers=_providers(input_transport, output_transport), diagnostics=sink)
    with TestClient(app) as client:
        path, headers = _new_session(client)
        response = client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": 1,
            "presentation_cutoff": 0, "text": "Synthetic request",
        })
        state = _await_state(client, path, headers, lambda value: value["phase"] == "error")
        assert response.status_code == 202
        assert state["last_error"] == "invalid_response"
        assert state["active_grants"] == [] and output_transport.calls == []
        assert sink.flush()
        assert any(record["stage"] == "input_review" and record.get("code") == "invalid_response"
                   for record in _read_events(tmp_path))
    sink.close()


@pytest.mark.asyncio
async def test_diagnostic_export_round_trips_only_typed_summary(tmp_path):
    transport = DirectOutputTransport(malformed=True)
    backend, context, candidate = direct_backend(transport)
    result = await backend.review_detailed(context, candidate)
    summary = result.observation.response_diagnostics
    event = DiagnosticEvent(DiagnosticStage.OUTPUT_REVIEW, DiagnosticOutcome.FAILED,
        DiagnosticContext(request_id=str(uuid4())), response_validation=summary)
    encoded = encode_event(event, 1000)
    assert validate_event_record(encoded) == encoded
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    assert sink.emit(event) and sink.flush()
    destination = tmp_path / "safe-diagnostics.zip"
    exported = export_diagnostics(tmp_path, destination)
    assert exported["event_count"] == 1
    with zipfile.ZipFile(destination) as archive:
        line = archive.read("events.jsonl").decode().strip()
    exported_record = json.loads(line)
    assert exported_record["response_validation"] == encoded["response_validation"]
    assert all("noul_probability" not in item
               for item in exported_record["response_validation"]["answer_facts"])
    hostile = dict(encoded)
    hostile["response_validation"] = dict(encoded["response_validation"], headers="Bearer " + PRIVATE_MARKER)
    with pytest.raises((TypeError, ValueError)):
        validate_event_record(hostile)
    assert PRIVATE_MARKER not in line
    sink.close()
