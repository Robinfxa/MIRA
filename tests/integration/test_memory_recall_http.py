"""Real SQLite → read-only worker → Actor → generation/review ASGI seam.

The generation and review doubles are synthetic; no external provider or actual
user memory is involved and no presentation receipt is manufactured.
"""
import hashlib
import json
import threading
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from mira.adapters.memory.sqlite import SQLiteMemoryStore
from mira.application.contracts import CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict
from mira.bootstrap.development_memory import create_development_memory_factory
from mira.bootstrap.providers import Providers
from mira.config.memory import MemoryRecallOptions
from mira.domain.memory import MemoryEntry, MemoryKind, MemoryScope, MemorySource
from mira.domain.models import EffectKind
from mira.entrypoints.http.app import create_app
from mira.entrypoints.http.operator_pairing import OperatorPairing

ORIGIN = "http://127.0.0.1:8000"
CODE = "synthetic-pairing-code-only-0000000000"

def pair(client):
    response = client.post("/api/v1/operator/pair", json={"code": CODE})
    assert response.status_code == 204



def test_opted_in_asgi_turn_uses_same_scoped_packet_without_recording(tmp_path, settings):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    database = private / "memory.sqlite3"
    scope = MemoryScope("synthetic-user", "mira", "synthetic-world")
    other_scope = MemoryScope("other-user", "mira", "synthetic-world")
    with SQLiteMemoryStore(database) as writer:
        writer.append(MemoryEntry("saved-boundary", scope, MemorySource.USER_STATEMENT,
            "Do not take my picture.", "manual-event-1", 1, kind=MemoryKind.BOUNDARY))
        writer.append(MemoryEntry("saved-episode", scope, MemorySource.USER_STATEMENT,
            "I prefer tea to coffee.", "manual-event-2", 1))
        writer.append(MemoryEntry("other-episode", other_scope, MemorySource.USER_STATEMENT,
            "Other user private coffee preference.", "manual-event-3", 1))
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    observed = {}
    reviewed = threading.Event()

    class Generation:
        async def generate(self, context):
            observed["generation"] = context.memory_packet
            yield CandidateRange((EffectProposal(EffectKind.SUBTITLE, "Synthetic reviewed reply."),),
                                 "synthetic-memory-case")

    class Review:
        async def review(self, context, _candidate):
            observed["review"] = context.memory_packet
            reviewed.set()
            return ReviewObservation(ReviewVerdict.ALLOW, "synthetic")

    configured = settings.model_copy(update={"runtime": settings.runtime.model_copy(update={"max_sessions": 1})})
    memory_factory = create_development_memory_factory(
        MemoryRecallOptions(database, scope, "local", True))
    app = create_app(configured, providers=Providers(Generation(), Review()),
                     memory_factory=memory_factory,
                     operator_pairing=OperatorPairing(CODE, tuple(configured.http.allowed_origins)))
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        pair(client)
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        path = "/api/v1/sessions/" + created["session"]["session_id"]
        headers = {"X-Mira-Session-Token": created["session_token"]}
        response = client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0,
            "text": "What did I say about coffee?"})
        assert response.status_code == 202
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = client.get(path, headers=headers).json()
            if state["phase"] == "error" or (state["phase"] == "ready" and state["sealed"]):
                break
            time.sleep(0.01)
        assert state["phase"] == "ready", state.get("last_error")
        assert reviewed.is_set()
        packet = observed["generation"]
        assert packet is not None and observed["review"] is packet
        assert packet.request_text == "What did I say about coffee?"
        assert [row.text for row in packet.persistent_boundaries] == ["Do not take my picture."]
        assert [row.text for row in packet.past_candidates] == ["I prefer tea to coffee."]
        assert all(row.trust == "untrusted_quoted_evidence" for row in packet.past_candidates)
        assert state["presented_effects"] == []
        assert len(state["active_grants"]) == 1
        assert "Other user private" not in str(state)
        assert "memory_packet" not in state and "memory_evidence" not in state
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    with SQLiteMemoryStore(database) as reader:
        assert len(reader.history(scope)) == 2


def test_public_development_factory_binds_memory_to_real_adapter_wires(tmp_path):
    from tests.contracts.test_development_app_entry import make_app

    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    database = private / "memory.sqlite3"
    scope = MemoryScope("synthetic-user", "mira", "synthetic-world")
    statement = "I prefer unsweetened tea."
    with SQLiteMemoryStore(database) as writer:
        writer.append(MemoryEntry("saved-tea", scope, MemorySource.USER_STATEMENT,
                                 statement, "manual-tea-event", 1))
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    app, codex, input_jev, output_jev = make_app(
        memory_options=MemoryRecallOptions(database, scope, "local", True),
        operator_pairing=OperatorPairing(CODE, (ORIGIN, "http://localhost:8000")))
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        pair(client)
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        path = "/api/v1/sessions/" + created["session"]["session_id"]
        headers = {"X-Mira-Session-Token": created["session_token"]}
        response = client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0,
            "text": "Tell me about tea."})
        assert response.status_code == 202
        # READY means that a reviewed prefix is available. A later seal review
        # may still be running, so it is not by itself a terminal observation.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = client.get(path, headers=headers).json()
            if state["phase"] == "error" or (state["phase"] == "ready" and state["sealed"]):
                break
            time.sleep(0.01)
        assert state["phase"] == "ready", state.get("last_error")
        assert state["sealed"] is True
        assert len(state["active_grants"]) == 2 and state["presented_effects"] == []
        assert len(input_jev.calls) == 2 and len(output_jev.calls) == 2
        turn = next(message for message in codex.sent if message["method"] == "turn/start")
        prompt = json.loads(turn["params"]["input"][0]["text"])
        packet = prompt["facts"]["memory_evidence"]
        assert packet["past_candidates"][0]["text"] == statement
        assert all(statement not in json.dumps(call[0]) for call in input_jev.calls)
        for call, _timeout, _max_bytes in output_jev.calls:
            assert call["state"]["context"]["memory_evidence"] == packet
            assert call["state"]["contract"]["snapshot"]["context"]["memory_evidence"] == packet
        assert "synthetic-user" not in json.dumps(prompt)
        assert statement not in json.dumps(state)
    assert codex.closed
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
