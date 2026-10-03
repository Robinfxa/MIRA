"""Cross-boundary synthetic acceptance for OBS-02; no network provider requests."""
import asyncio
import hashlib
import json
import threading
import time
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mira.adapters.diagnostics.export import export_diagnostics
from mira.adapters.diagnostics.privacy import correlation_hash
from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics
from mira.adapters.generation.mock import MockGenerationBackend
from mira.adapters.review.jev import JevReviewBackend
from mira.adapters.review.jev_support.http import HttpxJevTransport
from mira.application.contracts import CandidateRange, EffectProposal, ReviewObservation
from mira.application.decision_contracts import (
    ChoiceProbability, InputDecisionObservation, InputDecisionStatus, PredicateObservation,
    ReferentObservation, SemanticValue, evidence_digest, mira26_author_policy,
)
from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
from mira.application.diagnostic_events import CancellationReason, DiagnosticOutcome, DiagnosticStage
from mira.domain.models import SessionState
from mira.entrypoints.http.mappers import session_view
from mira.bootstrap.providers import Providers
from mira.config.settings import Settings
from mira.domain.models import EffectKind
from mira.entrypoints.http.app import create_app

PRIVATE_INPUT = "SYNTHETIC_PRIVATE_TEXT_Q7__not-a-user__"
PRIVATE_PROVIDER_BODY = b"synthetic-provider-private-body-Z8"
PRIVATE_PROVIDER_TOKEN = "synthetic-provider-token-T9"


def answer():
    return {"type":"choice", "choice":"allow", "confidence":1.0,
            "probabilities":{"allow":1.0,"reject":0.0,"unknown":0.0}}


class FakeJevTransport(httpx.AsyncBaseTransport):
    def __init__(self, status=None, *, timeout=False, held=False):
        self.status, self.timeout, self.held = status, timeout, held
        self.requests = []
        self.entered = threading.Event()
        self.cancelled = threading.Event()
        self.release = threading.Event()
        self.count_lock = threading.Lock()
        self.count = 0

    async def handle_async_request(self, request):
        with self.count_lock:
            self.count += 1
            count = self.count
        self.requests.append(request)
        self.entered.set()
        if self.held and count == 1:
            try:
                await asyncio.to_thread(self.release.wait, 3)
            except asyncio.CancelledError:
                self.cancelled.set()
                # Simulate an uncooperative provider transport delivering a late response.
                await asyncio.to_thread(self.release.wait, 3)
                return httpx.Response(401, request=request, content=PRIVATE_PROVIDER_BODY)
        if self.timeout and count == 1:
            raise httpx.ReadTimeout("synthetic provider transport timeout", request=request)
        if self.held and count > 1:
            return httpx.Response(429, request=request, content=PRIVATE_PROVIDER_BODY,
                headers={"X-Synthetic-Private": "synthetic-provider-response-header"})
        return httpx.Response(self.status, request=request, content=PRIVATE_PROVIDER_BODY,
            headers={"X-Synthetic-Private": "synthetic-provider-response-header"})

    async def aclose(self):
        return None


class InputDecision:
    async def observe(self, snapshot):
        return InputDecisionObservation(snapshot.snapshot_id, evidence_digest(snapshot),
            InputDecisionStatus.OBSERVED, "synthetic",
            tuple(PredicateObservation(name, SemanticValue.NO, 0.0) for name in (
                "speech_restriction", "capture_restriction", "display_request")),
            ReferentObservation("none", None, (ChoiceProbability("none", 1.0),
                ChoiceProbability("ambiguous", 0.0)), 1.0),
            calibration_ref="synthetic-input-only", model="synthetic-input-1")


class OldReview:
    async def review(self, *args):
        raise AssertionError("typed synthetic reviewer is the only route")


class Generated:
    async def generate(self, context):
        yield CandidateRange((EffectProposal(EffectKind.SUBTITLE, "Synthetic candidate"),), "synthetic")


def providers(transport, *, limit=3):
    backend = JevReviewBackend(transport=HttpxJevTransport(
        SecretStr(PRIVATE_PROVIDER_TOKEN), transport=transport), model="jev-1.13.0",
        request_limit=limit, calibration_ref="synthetic-test-only")
    return Providers(Generated(), OldReview(), SemanticReviewCoordinator(InputDecision(), backend),
        DecisionSnapshotOwner(mira26_author_policy()))


def make_app(root, backend_providers, *, diagnostics=None):
    settings = Settings(environment="test", runtime={"timeout_seconds": 4},
        diagnostics={"directory": "var/diagnostics"})
    return create_app(settings, providers=backend_providers, diagnostics=diagnostics)


def create_session(client):
    result = client.post("/api/v1/sessions", json={"client_instance_id": "11111111-1111-1111-1111-111111111111"})
    assert result.status_code == 201
    body = result.json()
    return body["session"]["session_id"], {"X-Mira-Session-Token": body["session_token"]}


def submit(client, path, headers, request_id, activity):
    return client.post(path + "/inputs", headers=headers, json={"request_id": request_id,
        "activity_seq": activity, "presentation_cutoff": 0, "text": PRIVATE_INPUT})


def state_when(client, path, headers, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        value = response.json()
        if predicate(value):
            return value
        time.sleep(.003)
    raise AssertionError("synthetic session did not reach the requested state")


def archive_records(root, destination):
    manifest = export_diagnostics(root, destination)
    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
        events = [json.loads(line) for line in archive.read("events.jsonl").decode().splitlines() if line]
        raw_bytes = archive.read("reviewed-raw.jsonl") if "reviewed-raw.jsonl" in names else b""
    return manifest, names, events, raw_bytes


@pytest.mark.parametrize(("status", "expected"), [(401, "unauthenticated"),
    (403, "permission_denied"), (429, "quota_exhausted"), (504, "timeout")])
def test_in_process_http_actor_provider_failure_has_safe_exported_trace(tmp_path, monkeypatch, status, expected):
    monkeypatch.chdir(tmp_path)
    transport = FakeJevTransport(status, timeout=(status == 504))
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path / "diag"), secrets=(PRIVATE_PROVIDER_TOKEN,), worker=False)
    app = make_app(tmp_path, providers(transport), diagnostics=sink)
    with TestClient(app) as client:
        path_id, headers = create_session(client)
        path = "/api/v1/sessions/" + path_id
        request_id = "22222222-2222-2222-2222-222222222222"
        accepted = submit(client, path, headers, request_id, 1)
        assert accepted.status_code == 202
        http_request_id = accepted.headers["x-request-id"]
        state = state_when(client, path, headers, lambda s: s["phase"] == "error")
        locator = state["last_error_diagnostic_id"]
        assert locator == correlation_hash(http_request_id)
        assert locator != correlation_hash(request_id)
        assert state["request_id"] is None and state["active_grants"] == []
        assert sink.status().recording_active is False
        assert PRIVATE_INPUT not in accepted.text + json.dumps(state)
        assert PRIVATE_PROVIDER_TOKEN not in accepted.text + json.dumps(state)
        assert len(transport.requests) == 1
        outgoing = transport.requests[0]
        assert outgoing.headers["authorization"] == "Bearer " + PRIVATE_PROVIDER_TOKEN
        assert outgoing.content and PRIVATE_INPUT.encode() in outgoing.content
        assert sink.flush()
        manifest, names, records, raw = archive_records(tmp_path / "diag", tmp_path / "default.zip")
        trace = [r for r in records if r["stage"] == "output_review" and r["outcome"] == "failed"
            and r["context"].get("request_id") == locator]
        assert len(trace) == 1 and trace[0]["code"] == expected
        assert manifest["raw_included"] is False and "reviewed-raw.jsonl" not in names and not raw
        exported = json.dumps(manifest) + json.dumps(records) + raw.decode()
        for secret in (PRIVATE_INPUT, PRIVATE_PROVIDER_BODY.decode(), PRIVATE_PROVIDER_TOKEN,
                       "synthetic-provider-response-header", request_id, http_request_id):
            assert secret not in exported
    sink.close()


@pytest.mark.parametrize("action", ["stop", "new_input"])
def test_repeated_stop_and_new_input_fence_late_provider_response(tmp_path, monkeypatch, action):
    monkeypatch.chdir(tmp_path)
    transport = FakeJevTransport(held=True)
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path / "diag"), worker=False)
    app = make_app(tmp_path, providers(transport, limit=5), diagnostics=sink)
    with TestClient(app) as client:
        path_id, headers = create_session(client)
        path = "/api/v1/sessions/" + path_id
        first = submit(client, path, headers, "33333333-3333-3333-3333-333333333333", 1)
        assert first.status_code == 202
        assert transport.entered.wait(2)
        first_http_id = first.headers["x-request-id"]
        if action == "stop":
            stopped = client.post(path + "/stop", headers=headers,
                json={"activity_seq": 2, "presentation_cutoff": 0}).json()
            assert stopped["phase"] == "stopped" and stopped["last_error_diagnostic_id"] is None
            again = client.post(path + "/stop", headers=headers,
                json={"activity_seq": 3, "presentation_cutoff": 0}).json()
            assert again["phase"] == "stopped" and again["last_error_diagnostic_id"] is None
            assert transport.cancelled.wait(2)
            transport.release.set()
            final = state_when(client, path, headers, lambda s: s["phase"] == "stopped")
            assert final["last_error"] is None and final["last_error_diagnostic_id"] is None
        else:
            second = submit(client, path, headers, "44444444-4444-4444-4444-444444444444", 2)
            assert second.status_code == 202
            second_http_id = second.headers["x-request-id"]
            assert transport.cancelled.wait(2)
            transport.release.set()
            final = state_when(client, path, headers, lambda s: s["phase"] == "error")
            assert final["last_error_diagnostic_id"] == correlation_hash(second_http_id)
            assert final["last_error_diagnostic_id"] != correlation_hash(first_http_id)
            assert final["request_id"] is None
        assert sink.flush()
        _, _, records, _ = archive_records(tmp_path / "diag", tmp_path / "default.zip")
        if action == "stop":
            terminals = [r for r in records if r["stage"] == "output_review" and r["outcome"] == "cancelled"]
            assert len(terminals) == 1 and terminals[0]["cancellation_reason"] == "user_stop"
            assert terminals[0]["context"]["request_id"] == correlation_hash(first_http_id)
        else:
            terminals = [r for r in records if r["stage"] == "output_review" and r["outcome"] == "failed"]
            assert any(r["context"].get("request_id") == correlation_hash(second_http_id)
                       and r["code"] == "quota_exhausted" for r in terminals)
            assert not any(r["context"].get("request_id") == correlation_hash(first_http_id)
                           and r["outcome"] == "failed" for r in terminals)
    sink.close()


def test_explicit_synthetic_recording_never_enters_default_export(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    transport = FakeJevTransport(429)
    settings = Settings(environment="test", runtime={"timeout_seconds": 4}, diagnostics={
        "directory": "var/diagnostics", "development_recording": True, "recording_consent": True})
    app = create_app(settings, providers=providers(transport), diagnostics=None)
    with TestClient(app) as client:
        path_id, headers = create_session(client)
        path = "/api/v1/sessions/" + path_id
        accepted = submit(client, path, headers, "55555555-5555-5555-5555-555555555555", 1)
        assert accepted.status_code == 202
        status = client.get("/api/v1/diagnostics-status").json()
        assert status["recording_active"] is True and "开发录制中" in status["notice"]
        state_when(client, path, headers, lambda s: s["phase"] == "error")
        sink = app.state.container.diagnostics
        assert sink.status().recording_active and sink.flush()
    root = tmp_path / "var/diagnostics"
    manifest, names, records, raw = archive_records(root, tmp_path / "default.zip")
    assert manifest["raw_included"] is False and "reviewed-raw.jsonl" not in names and not raw
    assert PRIVATE_INPUT not in json.dumps(records)
    reviewed = tmp_path / "explicit-synthetic-raw.zip"
    raw_manifest = export_diagnostics(root, reviewed, include_raw=True, confirm_sensitive_export=True)
    assert raw_manifest["raw_included"] is True
    with zipfile.ZipFile(reviewed) as archive:
        raw_text = archive.read("reviewed-raw.jsonl").decode()
        assert PRIVATE_INPUT in raw_text
        assert "synthetic-provider-token" not in raw_text


def test_diagnostic_write_failure_does_not_break_http_or_actor(tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("sentinel")
    sink = LocalDiagnostics(DiagnosticOptions(blocker), worker=False)
    app = make_app(tmp_path, providers(FakeJevTransport(401)), diagnostics=sink)
    with TestClient(app) as client:
        path_id, headers = create_session(client)
        path = "/api/v1/sessions/" + path_id
        response = submit(client, path, headers, "77777777-7777-7777-7777-777777777777", 1)
        assert response.status_code == 202
        state = state_when(client, path, headers, lambda s: s["phase"] == "error")
        assert state["last_error_diagnostic_id"] == correlation_hash(response.headers["x-request-id"])
        assert "sentinel" not in response.text + json.dumps(state)
        assert sink.flush()
        assert sink.status().io_failures >= 1
        status = client.get("/api/v1/diagnostics-status").json()
        assert status["io_failures"] >= 1
    sink.close()


def test_malformed_and_prototype_like_ids_are_dropped_at_public_mapper():
    for bad in ("constructor", "toString", "__proto__", PRIVATE_INPUT,
                "h_" + "a" * 32 + "\n", 123, ["h_" + "a" * 32]):
        view = session_view(SessionState("s", "c", last_error=bad,
                                         last_error_diagnostic_id=bad)).model_dump()
        assert view["last_error"] == "unknown"
        assert view["last_error_diagnostic_id"] is None
        assert PRIVATE_INPUT not in json.dumps(view)
