"""App-owned read-only memory lifecycle with synthetic ports, no network providers."""
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from mira.application.actor_memory import SessionMemoryBinding
from mira.config.loader import ConfigurationError
from mira.domain.memory import MemoryScope
from mira.entrypoints.http.app import create_app
from mira.entrypoints.http.operator_pairing import OperatorPairing

ORIGIN = "http://127.0.0.1:8000"
CODE = "synthetic-pairing-code-only-0000000000"

def pairing(settings):
    return OperatorPairing(CODE, tuple(settings.http.allowed_origins))

def pair(client):
    return client.post("/api/v1/operator/pair", json={"code": CODE})



class Reader:
    def __init__(self):
        self.closed = 0
        self.reads = 0

    async def build_packet(self, **_kwargs):
        self.reads += 1
        raise AssertionError("no turn was submitted")

    async def scope_revision(self, _scope):
        self.reads += 1
        return 0

    async def aclose(self):
        self.closed += 1


def bound_factory():
    reader = Reader()
    scope = MemoryScope("synthetic-user", "mira", "synthetic-world")
    calls = []
    async def factory():
        calls.append("open")
        return SessionMemoryBinding(reader, scope)
    return factory, reader, calls


def single_operator(settings):
    return settings.model_copy(update={"runtime": settings.runtime.model_copy(update={"max_sessions": 1})})


def test_memory_factory_is_inert_until_operator_pairing_and_app_owns_close(settings):
    factory, reader, calls = bound_factory()
    app = create_app(single_operator(settings), memory_factory=factory, operator_pairing=pairing(settings))
    assert calls == [] and reader.reads == 0
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        assert calls == []
        assert pair(client).status_code == 204
        assert calls == ["open"]
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())})
        assert created.status_code == 201
        body = created.json()
        session = body["session"]["session_id"]
        result = client.delete("/api/v1/sessions/" + session,
            headers={"X-Mira-Session-Token": body["session_token"]})
        assert result.status_code == 204
        # Deleting a session must not close the app-owned reader.
        assert reader.closed == 0 and reader.reads == 0
    assert reader.closed == 1


def test_memory_single_operator_constraint_checked_before_factory(settings):
    factory, _reader, calls = bound_factory()
    with pytest.raises(ConfigurationError, match="memory_recall_requires_single_operator"):
        create_app(settings, memory_factory=factory)
    assert calls == []


def test_memory_cannot_silently_expand_transmission_to_voice(settings):
    factory, _reader, calls = bound_factory()
    with pytest.raises(ConfigurationError, match="memory_recall_text_only"):
        create_app(single_operator(settings), memory_factory=factory, operator_pairing=pairing(settings), voice_factory=lambda: None)
    assert calls == []


def test_startup_container_failure_still_closes_memory(settings, monkeypatch):
    from mira.entrypoints.http import app as module
    factory, reader, calls = bound_factory()
    monkeypatch.setattr(module, "build_container", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic")))
    application = create_app(single_operator(settings), memory_factory=factory, operator_pairing=pairing(settings))
    with TestClient(application, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        assert calls == []
        assert pair(client).status_code == 503
        assert client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).status_code == 401
    assert calls == ["open"] and reader.closed == 1


def test_http_cannot_select_memory_scope_or_return_private_binding(settings):
    factory, reader, _calls = bound_factory()
    app = create_app(single_operator(settings), memory_factory=factory, operator_pairing=pairing(settings))
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        assert pair(client).status_code == 204
        rejected = client.post("/api/v1/sessions", json={
            "client_instance_id": str(uuid4()), "user_id": "other", "world_id": "other",
            "memory_scope": "other"})
        assert rejected.status_code == 422
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())})
        assert created.status_code == 201
        assert "synthetic-user" not in created.text and "synthetic-world" not in created.text
        assert "memory_packet" not in created.text
    assert reader.reads == 0 and reader.closed == 1
