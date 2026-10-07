"""Synthetic JEV transport failures retain only fixed, typed cause categories."""
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics
from mira.adapters.review.jev import (
    QUESTION_SET_VERSION, JevHttpResponse, JevReviewBackend, JevReviewContract,
    candidate_digest, context_digest,
)
from mira.adapters.review.jev_input import JevInputDecisionBackend
from mira.adapters.review.jev_support.http import HttpxJevTransport
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext, ReviewVerdict
from mira.application.decision_contracts import INPUT_QUESTION_SET_V2, mira26_author_policy
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V1
from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
from mira.application.diagnostic_errors import classify_reason
from mira.application.diagnostic_events import DiagnosticCode
from mira.bootstrap.providers import Providers
from mira.config.settings import Settings
from mira.domain.models import EffectKind
from mira.entrypoints.http.app import create_app

MODEL = "jev-1.13.0"
SECRET_MARKER = "SYNTHETIC-TRANSPORT-MARKER-99017"


@pytest.mark.asyncio
@pytest.mark.parametrize(("error", "cause"), [
    (httpx.ConnectError(SECRET_MARKER), "connect"),
    (httpx.ProxyError(SECRET_MARKER), "proxy"),
    (httpx.RemoteProtocolError(SECRET_MARKER), "protocol"),
    (httpx.ReadError(SECRET_MARKER), "read"),
    (httpx.WriteError(SECRET_MARKER), "write"),
    (httpx.ConnectTimeout(SECRET_MARKER), "timeout"),
    (httpx.ReadTimeout(SECRET_MARKER), "timeout"),
    (httpx.WriteTimeout(SECRET_MARKER), "timeout"),
    (httpx.UnsupportedProtocol(SECRET_MARKER), "unknown"),
])
async def test_transport_error_boundary_keeps_only_closed_httpx_category(error, cause, caplog, capsys):
    def handler(_request):
        raise error

    transport = HttpxJevTransport(SecretStr("synthetic-key"), transport=httpx.MockTransport(handler))
    with pytest.raises(Exception) as caught:
        await transport(b"{}", timeout_seconds=1, max_response_bytes=32)

    assert getattr(caught.value, "cause_code", None) == cause
    assert SECRET_MARKER not in repr(caught.value) + caplog.text + str(capsys.readouterr())


def output_contract():
    context = GenerationContext("Synthetic request", ("Synthetic request",), (), 1)
    candidate = CandidateRange(
        (EffectProposal(EffectKind.SUBTITLE, "Synthetic answer"),), "synthetic-candidate")
    contract = JevReviewContract(
        "synthetic-contract", QUESTION_SET_VERSION, context_digest(context),
        candidate_digest(candidate), (), ("Synthetic request",), ("Fictional adult character",),
        synthetic=True,
    )
    return context, candidate, contract


@pytest.mark.asyncio
@pytest.mark.parametrize(("error", "cause", "diagnostic_code"), [
    (httpx.ConnectError(SECRET_MARKER), "connect", DiagnosticCode.TRANSPORT_CONNECT),
    (httpx.ProxyError(SECRET_MARKER), "proxy", DiagnosticCode.TRANSPORT_PROXY),
    (httpx.RemoteProtocolError(SECRET_MARKER), "protocol", DiagnosticCode.TRANSPORT_PROTOCOL),
    (httpx.ReadError(SECRET_MARKER), "read", DiagnosticCode.TRANSPORT_READ),
    (httpx.WriteError(SECRET_MARKER), "write", DiagnosticCode.TRANSPORT_WRITE),
    (httpx.ReadTimeout(SECRET_MARKER), "timeout", DiagnosticCode.TIMEOUT),
])
async def test_review_result_preserves_safe_cause_and_existing_failure_taxonomy(
        error, cause, diagnostic_code, caplog, capsys):
    count = 0

    def handler(_request):
        nonlocal count
        count += 1
        raise error

    transport = HttpxJevTransport(SecretStr("synthetic-key"), transport=httpx.MockTransport(handler))
    context, candidate, contract = output_contract()
    backend = JevReviewBackend(transport=transport, model=MODEL,
        contract_resolver=lambda *_: contract, request_limit=1, timeout_seconds=1)
    result = await backend.review_detailed(context, candidate)

    expected_reason = f"jev_transport_{cause}_error"
    assert result.observation.verdict == ReviewVerdict.UNKNOWN
    assert result.observation.reason_code == expected_reason
    assert classify_reason(expected_reason).code == diagnostic_code
    assert count == 1
    assert SECRET_MARKER not in repr(result) + caplog.text + str(capsys.readouterr())


@pytest.mark.asyncio
async def test_unknown_transport_exception_keeps_legacy_unknown_cause():
    async def transport(*_args, **_kwargs):
        raise RuntimeError(SECRET_MARKER)

    context, candidate, contract = output_contract()
    backend = JevReviewBackend(transport=transport, model=MODEL,
        contract_resolver=lambda *_: contract, request_limit=1, timeout_seconds=1)
    result = await backend.review_detailed(context, candidate)

    assert result.observation.verdict == ReviewVerdict.UNKNOWN
    assert result.observation.reason_code == "jev_transport_error"
    assert classify_reason(result.observation.reason_code).code == DiagnosticCode.UNAVAILABLE
    assert SECRET_MARKER not in repr(result)


class FixedGeneration:
    async def generate(self, _context):
        yield CandidateRange(
            (EffectProposal(EffectKind.SUBTITLE, "Synthetic answer"),), "synthetic-candidate")


class V2InputTransport:
    def __init__(self):
        self.calls = []

    async def __call__(self, payload, *, timeout_seconds, max_response_bytes):
        request = json.loads(payload)
        self.calls.append(request)
        answers = {}
        for key, question in request["questions"].items():
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


def test_asgi_local_diagnostics_persist_transport_category_without_private_text(tmp_path, caplog, capsys):
    input_transport = V2InputTransport()
    output_requests = []

    def output_handler(request):
        output_requests.append(request)
        raise httpx.ConnectError(SECRET_MARKER, request=request)

    output_transport = HttpxJevTransport(SecretStr("synthetic-key"),
        transport=httpx.MockTransport(output_handler))
    input_backend = JevInputDecisionBackend(
        transport=input_transport, model=MODEL, decision_policy=USER_DEVELOPMENT_0_6_V1,
        question_set_revision=INPUT_QUESTION_SET_V2, request_limit=1, timeout_seconds=1)
    output_backend = JevReviewBackend(
        transport=output_transport, model=MODEL, decision_policy=USER_DEVELOPMENT_0_6_V1,
        request_limit=1, timeout_seconds=1)
    providers = Providers(FixedGeneration(), output_backend,
        semantic_review=SemanticReviewCoordinator(input_backend, output_backend),
        decision_owner=DecisionSnapshotOwner(mira26_author_policy()))
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), secrets=(SECRET_MARKER,), worker=False)
    app = create_app(Settings(), providers=providers, diagnostics=sink)

    try:
        with TestClient(app) as client:
            path, headers = _new_session(client)
            submitted = client.post(path + "/inputs", headers=headers, json={
                "request_id": str(uuid4()), "activity_seq": 1,
                "presentation_cutoff": 0, "text": "Synthetic request",
            })
            state = _await_state(client, path, headers, lambda value: value["phase"] == "error")
            assert submitted.status_code == 202
            assert state["last_error"] == "unavailable"
            assert state["active_grants"] == [] and state["request_id"] is None
            assert len(input_transport.calls) == len(output_requests) == 1
            assert sink.flush()
            events = _read_events(tmp_path)
            event = next(item for item in events if item["stage"] == "output_review"
                         and item["outcome"] == "failed")
            assert event["code"] == "transport_connect"
            encoded = json.dumps(state, sort_keys=True) + json.dumps(events, sort_keys=True)
            assert SECRET_MARKER not in encoded + caplog.text + str(capsys.readouterr())
    finally:
        sink.close()


def test_asgi_input_transport_category_is_logged_and_never_becomes_semantic_uncertainty(
        tmp_path, caplog, capsys):
    input_requests = []

    def input_handler(request):
        input_requests.append(request)
        raise httpx.ProxyError(SECRET_MARKER, request=request)

    input_transport = HttpxJevTransport(SecretStr("synthetic-key"),
        transport=httpx.MockTransport(input_handler))

    class ForbiddenOutputTransport:
        async def __call__(self, *_args, **_kwargs):
            raise AssertionError("output review must not run after input transport failure")

    input_backend = JevInputDecisionBackend(
        transport=input_transport, model=MODEL, decision_policy=USER_DEVELOPMENT_0_6_V1,
        question_set_revision=INPUT_QUESTION_SET_V2, request_limit=1, timeout_seconds=1)
    output_backend = JevReviewBackend(
        transport=ForbiddenOutputTransport(), model=MODEL,
        decision_policy=USER_DEVELOPMENT_0_6_V1, request_limit=1, timeout_seconds=1)
    providers = Providers(FixedGeneration(), output_backend,
        semantic_review=SemanticReviewCoordinator(input_backend, output_backend),
        decision_owner=DecisionSnapshotOwner(mira26_author_policy()))
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), secrets=(SECRET_MARKER,), worker=False)
    app = create_app(Settings(), providers=providers, diagnostics=sink)

    try:
        with TestClient(app) as client:
            path, headers = _new_session(client)
            submitted = client.post(path + "/inputs", headers=headers, json={
                "request_id": str(uuid4()), "activity_seq": 1,
                "presentation_cutoff": 0, "text": "Synthetic request",
            })
            state = _await_state(client, path, headers, lambda value: value["phase"] == "error")
            assert submitted.status_code == 202
            assert state["last_error"] == "unavailable"
            assert state["active_grants"] == [] and state["request_id"] is None
            assert len(input_requests) == 1
            assert sink.flush()
            events = _read_events(tmp_path)
            event = next(item for item in events if item["stage"] == "input_review"
                         and item["outcome"] == "failed")
            assert event["code"] == "transport_proxy"
            assert SECRET_MARKER not in json.dumps(state) + json.dumps(events)
            assert "review_uncertain" not in state.values()
            assert SECRET_MARKER not in caplog.text + str(capsys.readouterr())
    finally:
        sink.close()


def test_startup_readonly_failure_guidance_is_fixed_and_does_not_guess_a_path():
    from mira.application.diagnostic_errors import classify_reason

    failure = classify_reason("codex_startup_readonly_filesystem")
    assert failure.code == DiagnosticCode.CODEX_STARTUP_READONLY_FILESYSTEM
    assert "只读文件系统" in failure.message
    assert "模型运行配置" in failure.action
    assert SECRET_MARKER not in failure.message + failure.action
