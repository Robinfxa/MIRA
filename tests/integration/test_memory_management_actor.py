"""Actual paired HTTP edits invalidate old Actor memory snapshots (synthetic only)."""
import asyncio
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.adapters.memory.sqlite import SQLiteMemoryStore
from mira.application.contracts import CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict
from mira.bootstrap.development_memory import create_development_memory_factory
from mira.bootstrap.development_memory_management import create_development_memory_management_factory
from mira.bootstrap.providers import Providers
from mira.config.memory import MemoryRecallOptions
from mira.domain.memory import MemoryEntry, MemoryScope, MemorySource
from mira.domain.models import EffectKind
from mira.entrypoints.http.app import create_app
from mira.entrypoints.http.operator_pairing import OperatorPairing

ORIGIN = "http://127.0.0.1:8000"
CODE = "synthetic-management-pairing-only-0000000"


class Generation:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.packets = []

    async def generate(self, context):
        self.packets.append(context.memory_packet)
        if len(self.packets) == 1:
            self.started.set()
            while not self.release.is_set():
                await asyncio.sleep(0.005)
        yield CandidateRange((EffectProposal(EffectKind.SUBTITLE, "Synthetic memory reply."),),
                             "synthetic-managed-memory")


class Review:
    async def review(self, context, _candidate):
        return ReviewObservation(ReviewVerdict.ALLOW, "synthetic-only")


def setup_app(tmp_path, settings, *, edits=True):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "memory.sqlite3"
    scope = MemoryScope("synthetic-operator", "mira", "synthetic-world")
    with SQLiteMemoryStore(path) as store:
        store.append(MemoryEntry("legacy-opaque-id", scope, MemorySource.USER_STATEMENT,
                                 "An unrelated manually saved fact.", "legacy-event", 1))
    options = MemoryRecallOptions(path, scope, "local", True)
    configured = settings.model_copy(update={
        "runtime": settings.runtime.model_copy(update={"max_sessions": 1, "max_turns": 4}),
        "http": settings.http.model_copy(update={"allowed_origins": (ORIGIN,)}),
    })
    generation = Generation()
    app = create_app(configured, providers=Providers(generation, Review()),
        memory_factory=create_development_memory_factory(options),
        memory_management_factory=(create_development_memory_management_factory(options, authorized=True)
                                   if edits else None),
        operator_pairing=OperatorPairing(CODE, (ORIGIN,)))
    return app, generation, path, scope


def wait_terminal(client, path, headers):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        state = response.json()
        if state["phase"] == "error" or (state["phase"] == "ready" and state["sealed"]):
            return state
        time.sleep(0.005)
    raise AssertionError("synthetic actor did not terminate")


@pytest.mark.parametrize("mutation", ["correct", "forget"])
def test_paired_edit_during_generation_blocks_old_grants_and_next_turn_uses_new_scope(tmp_path, settings, mutation):
    app, generation, database, scope = setup_app(tmp_path, settings)
    original = "I prefer jasmine tea."
    replacement = "I now prefer mint tea."
    try:
        with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
            denied = client.get("/api/v1/memory-management/entries")
            assert denied.status_code == 401
            assert client.post("/api/v1/operator/pair", json={"code": CODE}).status_code == 204
            status = client.get("/api/v1/memory-management/status").json()
            saved = client.post("/api/v1/memory-management/operations", json={
                "operation_id": str(uuid4()), "expected_revision": status["revision"],
                "operation": "record", "confirmed": True, "text": original, "kind": "episodic"})
            assert saved.status_code == 200, saved.json().get("code")
            record = saved.json()
            created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())})
            assert created.status_code == 201
            session = created.json()
            endpoint = "/api/v1/sessions/" + session["session"]["session_id"]
            headers = {"X-Mira-Session-Token": session["session_token"]}
            submitted = client.post(endpoint + "/inputs", headers=headers, json={
                "request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0,
                "text": "What tea do I prefer?"})
            assert submitted.status_code == 202
            assert generation.started.wait(2)
            assert original in [row.text for row in generation.packets[0].past_candidates]
            command = {"operation_id": str(uuid4()), "expected_revision": record["revision"],
                       "operation": mutation, "confirmed": True, "entry_id": record["entry_id"]}
            if mutation == "correct":
                command["text"] = replacement
            changed = client.post("/api/v1/memory-management/operations", json=command)
            assert changed.status_code == 200, changed.json().get("code")
            generation.release.set()
            stale = wait_terminal(client, endpoint, headers)
            assert stale["phase"] == "error" and stale["last_error"] == "memory_context_stale"
            assert stale["active_grants"] == [] and stale["presented_effects"] == []

            submitted = client.post(endpoint + "/inputs", headers=headers, json={
                "request_id": str(uuid4()), "activity_seq": 2, "presentation_cutoff": 0,
                "text": "What tea do I prefer now?"})
            assert submitted.status_code == 202
            fresh = wait_terminal(client, endpoint, headers)
            assert fresh["phase"] == "ready" and fresh["sealed"] is True
            assert len(fresh["active_grants"]) == 1 and fresh["presented_effects"] == []
            recalled = [row.text for row in generation.packets[-1].past_candidates]
            assert original not in recalled
            if mutation == "correct":
                assert replacement in recalled
            assert "memory_evidence" not in fresh and original not in str(fresh)
            assert client.post("/api/v1/operator/revoke").status_code == 204
            assert client.get("/api/v1/memory-management/entries").status_code == 401
    finally:
        generation.release.set()
    with SQLiteMemoryStore(database) as store:
        # Seed, manual record, then exactly one correction or soft-forget. No auto recording.
        assert len(store.history(scope)) == 3


def test_recall_consent_without_edit_consent_keeps_management_disabled(tmp_path, settings):
    app, generation, database, scope = setup_app(tmp_path, settings, edits=False)
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        assert client.post("/api/v1/operator/pair", json={"code": CODE}).status_code == 204
        assert client.get("/api/v1/memory-management/status").json() == {"enabled": False, "revision": None}
        response = client.post("/api/v1/memory-management/operations", json={
            "operation_id": str(uuid4()), "expected_revision": 1, "operation": "record",
            "confirmed": True, "text": "This must not be saved.", "kind": "episodic"})
        assert response.status_code == 404
        assert generation.packets == []
    with SQLiteMemoryStore(database) as store:
        assert len(store.history(scope)) == 1
