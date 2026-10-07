"""Real JEV adapters and ASGI behavior for semantic UNKNOWN vs technical failure."""
import asyncio
import json
import time
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.adapters.review.jev import JevHttpResponse, JevReviewBackend, JevTransportError
from mira.adapters.review.jev_input import JevInputDecisionBackend
from mira.application.contracts import CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict
from mira.application.decision_contracts import (
    INPUT_QUESTION_SET_V2, mira26_author_policy,
)
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V1
from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
from mira.bootstrap.providers import Providers
from mira.config.settings import Settings
from mira.domain.models import EffectKind
from mira.entrypoints.http.app import create_app

MODEL = "jev-1.13.0"


def _choice(choice: str, *, probability: float = 1.0) -> dict:
    remaining = (1.0 - probability) / 2
    return {
        "type": "choice",
        "choice": choice,
        "confidence": (probability - 1 / 3) / (1 - 1 / 3),
        "probabilities": {
            name: probability if name == choice else remaining
            for name in ("allow", "reject", "unknown")
        },
    }


class InputTransport:
    def __init__(self, *, semantic_unknown: bool = False):
        self.semantic_unknown = semantic_unknown
        self.calls = []

    async def __call__(self, payload, *, timeout_seconds, max_response_bytes):
        request = json.loads(payload)
        self.calls.append(request)
        answers = {}
        for key, question in request["questions"].items():
            if question["type"] == "noul":
                unknown_predicate = self.semantic_unknown and key.endswith(":referent_required")
                answers[key] = {"type": "noul", "noul": 0.5 if unknown_predicate else 0.0}
            else:
                selected = "none" if "none" in question["criteria"] else sorted(question["criteria"])[0]
                probabilities = {name: 1.0 if name == selected else 0.0
                                 for name in question["criteria"]}
                answers[key] = {"type": "choice", "choice": selected,
                                "confidence": 1.0, "probabilities": probabilities}
        body = json.dumps({"model": MODEL, "answers": answers,
                           "usage": {"input_tokens": 2, "output_tokens": 1}},
                          separators=(",", ":")).encode()
        return JevHttpResponse(200, body)


class OutputTransport:
    def __init__(self, outcomes=(), *, block_first: bool = False):
        self.outcomes = list(outcomes)
        self.calls = []
        self.block_first = block_first
        self.entered = Event()
        self.release = Event()

    async def __call__(self, payload, *, timeout_seconds, max_response_bytes):
        request = json.loads(payload)
        self.calls.append(request)
        index = len(self.calls) - 1
        outcome = self.outcomes[index] if index < len(self.outcomes) else "allow"
        if self.block_first and index == 0:
            self.entered.set()
            try:
                await asyncio.to_thread(self.release.wait, 10)
            except asyncio.CancelledError:
                # Model a transport that suppresses cancellation and returns late.
                await asyncio.to_thread(self.release.wait, 10)
        if outcome == "transport":
            raise JevTransportError("jev_transport_error", cause_code="connect")
        answers = {}
        for key in request["questions"]:
            if outcome == "unknown_choice":
                answers[key] = _choice("unknown")
            elif outcome == "low_confidence":
                answers[key] = {
                    "type": "choice", "choice": "allow", "confidence": 0.325,
                    "probabilities": {"allow": 0.55, "reject": 0.45, "unknown": 0.0},
                }
            else:
                selected = "reject" if outcome == "reject" else "allow"
                answers[key] = _choice(selected)
        if outcome == "invalid":
            answers.pop(sorted(answers)[0])
        body = json.dumps({"model": MODEL, "answers": answers,
                           "usage": {"input_tokens": 2, "output_tokens": 1}},
                          separators=(",", ":")).encode()
        return JevHttpResponse(200, body)


class Generation:
    def __init__(self, *, kind: EffectKind = EffectKind.SUBTITLE, gated_second: bool = False):
        self.kind = kind
        self.gated_second = gated_second
        self.second_ready = Event()
        self.release_second = Event()
        self.calls = 0

    async def generate(self, _context):
        self.calls += 1
        value = "Synthetic first range" if self.gated_second else "Synthetic answer"
        yield CandidateRange((EffectProposal(self.kind, value),), "synthetic-first")
        if self.gated_second:
            self.second_ready.set()
            await asyncio.to_thread(self.release_second.wait, 10)
            yield CandidateRange((EffectProposal(self.kind, "Synthetic uncertain remainder"),),
                                 "synthetic-second")


class CapturingCoordinator(SemanticReviewCoordinator):
    def __init__(self, input_backend, output_backend):
        super().__init__(input_backend, output_backend)
        self.results = []

    async def review(self, *args, **kwargs):
        result = await super().review(*args, **kwargs)
        self.results.append(result)
        return result


class FixedUnknownReview:
    """Synthetic technical/integrity failure at the output-review port boundary."""
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        self.calls = 0

    async def review_contract(self, _context, _candidate, _contract):
        self.calls += 1
        return ReviewObservation(ReviewVerdict.UNKNOWN, self.reason_code)


def _app(*, input_transport=None, output_transport=None, generation=None,
         input_policy=USER_DEVELOPMENT_0_6_V1,
         output_policy=USER_DEVELOPMENT_0_6_V1, output_calibration=None,
         input_limit=16, output_limit=16, output_review=None):
    input_transport = input_transport or InputTransport()
    output_transport = output_transport or OutputTransport()
    generation = generation or Generation()
    input_backend = JevInputDecisionBackend(
        transport=input_transport, model=MODEL, decision_policy=input_policy,
        question_set_revision=INPUT_QUESTION_SET_V2, request_limit=input_limit,
        timeout_seconds=1,
    )
    output_backend = JevReviewBackend(
        transport=output_transport, model=MODEL, decision_policy=output_policy,
        calibration_ref=output_calibration, request_limit=output_limit, timeout_seconds=1,
    )
    coordinator = CapturingCoordinator(input_backend, output_review or output_backend)
    providers = Providers(generation, output_review or output_backend, semantic_review=coordinator,
                          decision_owner=DecisionSnapshotOwner(mira26_author_policy()))
    return create_app(Settings(), providers=providers), input_transport, output_transport, generation, coordinator


def _new_session(client):
    response = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())})
    assert response.status_code == 201
    body = response.json()
    return ("/api/v1/sessions/" + body["session"]["session_id"],
            {"X-Mira-Session-Token": body["session_token"]})


def _submit(client, path, headers, activity_seq):
    return client.post(path + "/inputs", headers=headers, json={
        "request_id": str(uuid4()), "activity_seq": activity_seq,
        "presentation_cutoff": 0, "text": "Synthetic user request",
    })


def _await_state(client, path, headers, predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        state = response.json()
        if predicate(state):
            return state
        time.sleep(0.003)
    raise AssertionError("synthetic ASGI session did not reach the expected state")


@pytest.mark.parametrize(("outcome", "calibrated"), [
    ("unknown_choice", False), ("low_confidence", False), ("unknown_choice", True),
])
def test_asgi_output_semantic_unknown_is_fail_closed_clarification(outcome, calibrated):
    input_transport = InputTransport()
    output_transport = OutputTransport([outcome])
    kwargs = {"output_policy": None, "output_calibration": "synthetic-calibration"} if calibrated else {}
    app, _, _, generation, _ = _app(input_transport=input_transport,
        output_transport=output_transport, **kwargs)
    with TestClient(app) as client:
        path, headers = _new_session(client)
        submitted = _submit(client, path, headers, 1)
        state = _await_state(client, path, headers, lambda item: item["phase"] == "error")
        assert submitted.status_code == 202
        assert state["last_error"] == "review_uncertain"
        assert state["request_id"] is None and state["active_grants"] == []
        assert len(input_transport.calls) == 1 and len(output_transport.calls) == 1
        assert generation.calls == 1


def test_asgi_input_semantic_unknown_propagates_without_output_dispatch():
    input_transport = InputTransport(semantic_unknown=True)
    output_transport = OutputTransport(["allow"])
    app, _, _, generation, coordinator = _app(input_transport=input_transport,
                                               output_transport=output_transport)
    with TestClient(app) as client:
        path, headers = _new_session(client)
        assert _submit(client, path, headers, 1).status_code == 202
        state = _await_state(client, path, headers, lambda item: item["phase"] == "error")
        assert state["last_error"] == "review_uncertain"
        assert state["request_id"] is None and state["active_grants"] == []
        assert len(input_transport.calls) == 1 and output_transport.calls == []
        assert generation.calls == 1 and len(coordinator.results) == 1
        assert coordinator.results[0].reason_code == "jev_input_semantic_unknown"


def test_asgi_consecutive_unknowns_allow_a_later_valid_turn():
    input_transport = InputTransport()
    output_transport = OutputTransport(["unknown_choice", "unknown_choice", "allow", "allow"])
    app, _, _, generation, _ = _app(input_transport=input_transport, output_transport=output_transport)
    with TestClient(app) as client:
        path, headers = _new_session(client)
        for activity in (1, 2):
            assert _submit(client, path, headers, activity).status_code == 202
            failed = _await_state(client, path, headers, lambda item: item["phase"] == "error")
            assert failed["last_error"] == "review_uncertain"
            assert failed["active_grants"] == [] and failed["request_id"] is None
        assert _submit(client, path, headers, 3).status_code == 202
        recovered = _await_state(client, path, headers, lambda item: item["sealed"] is True)
        assert recovered["phase"] == "ready" and recovered["last_error"] is None
        assert recovered["request_id"] is not None and len(recovered["active_grants"]) == 1
        assert len(output_transport.calls) == 4
        assert len(input_transport.calls) == 4
        assert generation.calls == 3


def test_asgi_presented_prefix_survives_uncertain_remainder():
    input_transport = InputTransport()
    output_transport = OutputTransport(["allow", "unknown_choice"])
    generation = Generation(gated_second=True)
    app, _, _, _, _ = _app(input_transport=input_transport,
                             output_transport=output_transport, generation=generation)
    with TestClient(app) as client:
        path, headers = _new_session(client)
        assert _submit(client, path, headers, 1).status_code == 202
        active = _await_state(client, path, headers,
                              lambda item: len(item["active_grants"]) == 1)
        first = active["active_grants"][0]
        assert generation.second_ready.wait(2)
        receipt = client.post(path + "/receipts", headers=headers, json={
            "effect_id": first["id"], "digest": first["digest"],
            "output_epoch": first["output_epoch"], "activity_seq": first["activity_seq"],
            "presentation_seq": 1,
        })
        assert receipt.status_code == 200
        generation.release_second.set()
        failed = _await_state(client, path, headers, lambda item: item["phase"] == "error")
        assert failed["last_error"] == "review_uncertain"
        assert failed["active_grants"] == [] and failed["request_id"] is None
        assert [item["value"] for item in failed["presented_effects"]] == ["Synthetic first range"]
        assert len(input_transport.calls) == 2 and len(output_transport.calls) == 2
    generation.release_second.set()


@pytest.mark.parametrize("replacement", ["stop", "new_input"])
def test_asgi_stop_or_new_input_fences_late_unknown(replacement):
    input_transport = InputTransport()
    output_transport = OutputTransport(["unknown_choice", "allow", "allow"], block_first=True)
    app, _, _, generation, _ = _app(input_transport=input_transport,
                                    output_transport=output_transport)
    with TestClient(app) as client:
        path, headers = _new_session(client)
        assert _submit(client, path, headers, 1).status_code == 202
        assert output_transport.entered.wait(2)
        if replacement == "stop":
            stopped = client.post(path + "/stop", headers=headers,
                                  json={"activity_seq": 2, "presentation_cutoff": 0})
            assert stopped.status_code == 200
        else:
            assert _submit(client, path, headers, 2).status_code == 202
        output_transport.release.set()
        if replacement == "stop":
            state = _await_state(client, path, headers, lambda item: item["phase"] == "stopped")
            assert state["last_error"] is None and state["active_grants"] == []
            assert len(output_transport.calls) == 1
        else:
            state = _await_state(client, path, headers, lambda item: item["sealed"] is True)
            assert state["phase"] == "ready" and state["last_error"] is None
            assert len(state["active_grants"]) == 1 and len(output_transport.calls) == 3
        assert generation.calls == (1 if replacement == "stop" else 2)
    output_transport.release.set()


@pytest.mark.parametrize(("failure", "expected", "input_limit", "output_limit", "calibrated",
                          "candidate_kind", "input_calibrated"), [
    ("reject", "review_not_allowed", 16, 16, True, EffectKind.SUBTITLE, True),
    ("invalid", "invalid_response", 16, 16, True, EffectKind.SUBTITLE, True),
    ("transport", "unavailable", 16, 16, True, EffectKind.SUBTITLE, True),
    ("budget", "review_budget_exhausted", 16, 0, True, EffectKind.SUBTITLE, True),
    ("budget", "review_budget_exhausted", 0, 16, True, EffectKind.SUBTITLE, True),
    ("uncalibrated", "unknown", 16, 16, False, EffectKind.SUBTITLE, True),
    ("input_uncalibrated", "unknown", 16, 16, True, EffectKind.SUBTITLE, False),
    ("contract", "unknown", 16, 16, True, EffectKind.MEDIA, True),
    ("binding", "unknown", 16, 16, True, EffectKind.SUBTITLE, True),
    ("unclassified", "unknown", 16, 16, True, EffectKind.SUBTITLE, True),
])
def test_asgi_technical_failures_do_not_enter_clarification(
        failure, expected, input_limit, output_limit, calibrated, candidate_kind,
        input_calibrated):
    input_transport = InputTransport()
    output_transport = OutputTransport([failure if failure not in ("budget", "uncalibrated",
                                                                     "input_uncalibrated", "contract")
                                       else "allow"])
    input_policy = USER_DEVELOPMENT_0_6_V1 if input_calibrated else None
    output_policy = USER_DEVELOPMENT_0_6_V1 if calibrated else None
    output_calibration = None if calibrated else None
    generation = Generation(kind=candidate_kind)
    output_review = None
    if failure == "binding":
        output_review = FixedUnknownReview("jev_contract_binding_mismatch")
    elif failure == "unclassified":
        output_review = FixedUnknownReview("synthetic_unclassified_technical_unknown")
    app, _, _, _, coordinator = _app(input_transport=input_transport,
        output_transport=output_transport, generation=generation,
        input_policy=input_policy, output_policy=output_policy,
        output_calibration=output_calibration, input_limit=input_limit,
        output_limit=output_limit, output_review=output_review)
    with TestClient(app) as client:
        path, headers = _new_session(client)
        assert _submit(client, path, headers, 1).status_code == 202
        failed = _await_state(client, path, headers, lambda item: item["phase"] == "error")
        assert failed["last_error"] == expected
        assert failed["last_error"] != "review_uncertain"
        assert failed["request_id"] is None and failed["active_grants"] == []
        if input_limit == 0 or not input_calibrated:
            assert output_transport.calls == []
        if output_limit == 0 or failure == "contract":
            assert output_transport.calls == []
        if failure in ("reject", "invalid", "transport", "uncalibrated"):
            assert len(output_transport.calls) == 1
        if failure in ("binding", "unclassified"):
            assert len(output_transport.calls) == 0
            assert output_review.calls == 1
        if failure == "unclassified":
            assert "synthetic_unclassified_technical_unknown" not in json.dumps(failed)
        if failure == "input_uncalibrated":
            assert coordinator.results[0].reason_code == "semantic_contract_unavailable"
