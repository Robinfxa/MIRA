"""Synthetic, offline paired HTTP tests for explicit local memory management."""

from __future__ import annotations

import hashlib
import asyncio
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from mira.adapters.memory.sqlite import SQLiteMemoryStore
from mira.bootstrap.development_memory import create_development_memory_factory
from mira.bootstrap.development_memory_management import (
    create_development_memory_management_factory,
)
from mira.application.actor_memory import SessionMemoryBinding
from mira.application.memory_management import MemoryManagement
from mira.config.memory import MemoryRecallOptions
from mira.domain.memory import MemoryEntry, MemoryKind, MemoryScope, MemorySource
from mira.entrypoints.http.app import create_app
from mira.entrypoints.http.operator_pairing import OperatorPairing

ORIGIN = "http://testserver"
CODE = "synthetic-management-pair-code-0000000000"


def _settings(settings):
    return settings.model_copy(update={
        "runtime": settings.runtime.model_copy(update={"max_sessions": 1}),
        "http": settings.http.model_copy(update={"allowed_origins": (ORIGIN,)}),
    })


def _app(tmp_path, settings, *, management_enabled=True):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "memory.sqlite3"
    scope = MemoryScope("synthetic-user", "mira", "synthetic-world")
    with SQLiteMemoryStore(path) as store:
        store.append(MemoryEntry(
            "saved-tea", scope, MemorySource.USER_STATEMENT,
            "I prefer unsweetened tea.", "manual-tea-event", 1,
            kind=MemoryKind.EPISODIC,
        ))
        store.append(MemoryEntry(
            "authored-private", scope, MemorySource.AUTHORED_BACKSTORY,
            "Synthetic authored private background.", "authored-event", 1,
        ))
        store.append(MemoryEntry(
            "interpretation-private", scope, MemorySource.INTERPRETATION,
            "Synthetic private interpretation.", "interpretation-event", 1,
        ))
    options = MemoryRecallOptions(path, scope, "local", True)
    calls = {"reader": 0, "manager": 0}
    reader_factory = create_development_memory_factory(options)

    async def tracked_reader_factory():
        calls["reader"] += 1
        return await reader_factory()

    management_factory = None
    if management_enabled:
        raw_management_factory = create_development_memory_management_factory(
            options, authorized=True
        )

        async def tracked_management_factory():
            calls["manager"] += 1
            return await raw_management_factory()

        management_factory = tracked_management_factory
    app = create_app(
        _settings(settings), memory_factory=tracked_reader_factory,
        memory_management_factory=management_factory,
        operator_pairing=OperatorPairing(CODE, (ORIGIN,)),
    )
    return app, path, scope, calls


def _pair(client):
    return client.post("/api/v1/operator/pair", json={"code": CODE},
                       headers={"Origin": ORIGIN})


def test_unpaired_and_cross_origin_requests_do_not_open_private_store(tmp_path, settings):
    app, _path, _scope, calls = _app(tmp_path, settings)
    with TestClient(app, base_url=ORIGIN) as client:
        for method, path, payload in (
            ("get", "/api/v1/memory-management/status", None),
            ("get", "/api/v1/memory-management/entries", None),
            ("post", "/api/v1/memory-management/operations", {
                "operation_id": str(uuid4()), "expected_revision": 0,
                "operation": "record", "confirmed": True,
                "text": "synthetic private attempted text", "kind": "episodic",
            }),
        ):
            request_args = {
                "headers": {"Origin": ORIGIN,
                            "X-Mira-Session-Token": "not-an-operator-cookie"},
            }
            if payload is not None:
                request_args["json"] = payload
            response = getattr(client, method)(path, **request_args)
            assert response.status_code == 401
        assert calls == {"reader": 0, "manager": 0}

        paired = _pair(client)
        assert paired.status_code == 204
        assert calls == {"reader": 1, "manager": 1}
        cookie = paired.cookies.get("mira_operator_session")
        assert cookie
        cross_origin = client.get(
            "/api/v1/memory-management/status",
            headers={"Origin": "http://evil.example", "Cookie": f"mira_operator_session={cookie}"},
        )
        assert cross_origin.status_code == 401
        assert calls == {"reader": 1, "manager": 1}


def test_management_disabled_launch_has_no_writer_or_panel_marker(tmp_path, settings):
    app, path, _scope, calls = _app(tmp_path, settings, management_enabled=False)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert 'data-memory-management="enabled"' not in root.text
        assert _pair(client).status_code == 204
        response = client.get("/api/v1/memory-management/status")
        assert response.status_code == 200
        assert response.json() == {"enabled": False, "revision": None}
        assert app.state.memory_management is None
        assert calls == {"reader": 1, "manager": 0}
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("stop_mode", ["revoke", "shutdown"])
def test_revoke_and_shutdown_close_management_writer(tmp_path, settings, stop_mode):
    app, _path, _scope, calls = _app(tmp_path, settings)
    manager = None
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        assert _pair(client).status_code == 204
        manager = app.state.memory_management
        assert manager is not None and manager.is_open
        assert manager._backend._store._connection is not None
        if stop_mode == "revoke":
            revoked = client.post("/api/v1/operator/revoke")
            assert revoked.status_code == 204
            assert manager.is_open is False
            assert manager._backend._store._connection is None
            assert app.state.memory_management is None
            status = client.get("/api/v1/memory-management/status")
            assert status.status_code == 401
            assert calls == {"reader": 1, "manager": 1}
    assert manager is not None and manager.is_open is False
    assert manager._backend._store._connection is None
    assert app.state.memory_management is None


def test_late_management_factory_result_is_closed_after_pair_timeout(monkeypatch, settings):
    import mira.entrypoints.http.app as app_module

    monkeypatch.setattr(app_module, "MEMORY_FACTORY_STARTUP_TIMEOUT_SECONDS", 0.01)
    scope = MemoryScope("synthetic-user", "mira", "synthetic-world")
    release = threading.Event()
    started = threading.Event()
    closed = threading.Event()

    class Reader:
        def __init__(self):
            self.closed = False

        async def build_packet(self, **_kwargs):
            raise AssertionError("no recall expected")

        async def scope_revision(self, _scope):
            return 0

        async def aclose(self):
            self.closed = True

    class Backend:
        async def open(self):
            return self

        async def scope_revision(self):
            return 0

        async def list_entries(self, *, limit, cursor):
            raise AssertionError("no list expected")

        async def apply_operation(self, command):
            raise AssertionError("no write expected")

        async def aclose(self):
            closed.set()

    reader = Reader()

    async def memory_factory():
        return SessionMemoryBinding(reader, scope)

    manager = MemoryManagement(Backend(), authorized=True)

    async def late_management_factory():
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            while not release.is_set():
                try:
                    await asyncio.to_thread(release.wait, 0.05)
                except asyncio.CancelledError:
                    continue
        return manager

    configured = _settings(settings)
    app = app_module.create_app(
        configured, memory_factory=memory_factory,
        memory_management_factory=late_management_factory,
        operator_pairing=OperatorPairing(CODE, (ORIGIN,)),
    )
    try:
        with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
            response = _pair(client)
            assert response.status_code == 503
            assert started.wait(timeout=1)
            assert reader.closed is True
            release.set()
            assert closed.wait(timeout=2)
            assert manager.is_open is False
            assert app.state.memory_management is None
    finally:
        release.set()


def test_strict_http_errors_never_reflect_memory_text_or_scope_fields(tmp_path, settings):
    app, path, _scope, calls = _app(tmp_path, settings)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        assert _pair(client).status_code == 204
        status = client.get("/api/v1/memory-management/status")
        assert status.status_code == 200
        current_revision = status.json()["revision"]
        assert status.json() == {"enabled": True, "revision": current_revision}

        secret_text = "Synthetic statement must not appear in errors 123-45-6789"
        unknown = client.post("/api/v1/memory-management/operations", json={
            "operation_id": str(uuid4()), "expected_revision": current_revision,
            "operation": "record", "confirmed": True,
            "text": secret_text, "kind": "episodic", "source": "authored_backstory",
            "user_id": "another-user", "database": "/tmp/other.sqlite",
            "source_event_id": "spoofed-event", "recorded_at": "2020-01-01T00:00:00Z",
        })
        assert unknown.status_code == 422
        assert secret_text not in unknown.text
        assert "another-user" not in unknown.text and "/tmp/other.sqlite" not in unknown.text

        stale = client.post("/api/v1/memory-management/operations", json={
            "operation_id": str(uuid4()), "expected_revision": current_revision - 1,
            "operation": "record", "confirmed": True,
            "text": secret_text, "kind": "episodic",
        })
        assert stale.status_code == 409
        assert stale.json()["code"] == "stale_revision"
        assert stale.json()["current_revision"] == current_revision
        assert secret_text not in stale.text

        false_confirmation = client.post("/api/v1/memory-management/operations", json={
            "operation_id": str(uuid4()), "expected_revision": current_revision,
            "operation": "record", "confirmed": False,
            "text": secret_text, "kind": "episodic",
        })
        assert false_confirmation.status_code == 422
        boolean_revision = client.post("/api/v1/memory-management/operations", json={
            "operation_id": str(uuid4()), "expected_revision": True,
            "operation": "record", "confirmed": True,
            "text": secret_text, "kind": "episodic",
        })
        assert boolean_revision.status_code == 422
        coerced_confirmation = client.post("/api/v1/memory-management/operations", json={
            "operation_id": str(uuid4()), "expected_revision": current_revision,
            "operation": "record", "confirmed": 1,
            "text": secret_text, "kind": "episodic",
        })
        assert coerced_confirmation.status_code == 422
        assert secret_text not in (false_confirmation.text + boolean_revision.text
                                   + coerced_confirmation.text)

        body = {
            "operation_id": str(uuid4()), "expected_revision": current_revision,
            "operation": "record", "confirmed": True,
            "text": "I like the soft rain window.", "kind": "boundary",
        }
        saved = client.post("/api/v1/memory-management/operations", json=body)
        assert saved.status_code == 200
        assert saved.json()["status"] == "committed"
        assert saved.json()["replayed"] is False
        replay = client.post("/api/v1/memory-management/operations", json=body)
        assert replay.status_code == 200 and replay.json()["replayed"] is True
        assert replay.json()["revision"] == saved.json()["revision"]
        assert calls == {"reader": 1, "manager": 1}

        changed_body = {**body, "text": "I like a different scene."}
        conflict = client.post("/api/v1/memory-management/operations", json=changed_body)
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "operation_id_conflict"
        assert body["text"] not in conflict.text and changed_body["text"] not in conflict.text

        cross_scope = client.post("/api/v1/memory-management/operations", json={
            "operation_id": str(uuid4()), "expected_revision": replay.json()["revision"],
            "operation": "forget", "confirmed": True,
            "entry_id": "other-scope-private-entry",
        })
        assert cross_scope.status_code == 409
        assert cross_scope.json()["code"] == "entry_not_found"
        assert "other-scope-private-entry" not in cross_scope.text

        listed = client.get("/api/v1/memory-management/entries?limit=1")
        assert listed.status_code == 200
        entries = listed.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["source"] == "user_statement"
        assert "Synthetic authored private background" not in listed.text
        assert "Synthetic private interpretation" not in listed.text
        oversized_page = client.get("/api/v1/memory-management/entries?limit=21")
        assert oversized_page.status_code == 422
    assert hashlib.sha256(path.read_bytes()).hexdigest() != before


def test_restore_keeps_entry_forgotten_until_all_active_tombstones_are_reversed(tmp_path, settings):
    app, path, scope, _calls = _app(tmp_path, settings)
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        assert _pair(client).status_code == 204
        with SQLiteMemoryStore(path).open() as writer:
            first = writer.forget(scope, "saved-tea")
            second = writer.forget(scope, "saved-tea")

        page = client.get("/api/v1/memory-management/entries?limit=20").json()
        item = next(entry for entry in page["entries"] if entry["entry_id"] == "saved-tea")
        assert item["active"] is False and item["forget_event_id"] == second.id
        restore_latest = {
            "operation_id": str(uuid4()), "expected_revision": page["revision"],
            "operation": "restore", "confirmed": True, "forget_event_id": second.id,
        }
        restored = client.post("/api/v1/memory-management/operations", json=restore_latest)
        assert restored.status_code == 200
        page = client.get("/api/v1/memory-management/entries?limit=20").json()
        item = next(entry for entry in page["entries"] if entry["entry_id"] == "saved-tea")
        assert item["active"] is False and item["forget_event_id"] == first.id

        restore_first = {
            "operation_id": str(uuid4()), "expected_revision": page["revision"],
            "operation": "restore", "confirmed": True, "forget_event_id": first.id,
        }
        restored = client.post("/api/v1/memory-management/operations", json=restore_first)
        assert restored.status_code == 200
        page = client.get("/api/v1/memory-management/entries?limit=20").json()
        item = next(entry for entry in page["entries"] if entry["entry_id"] == "saved-tea")
        assert item["active"] is True
        assert item["forget_event_id"] is None and item["forgotten_at"] is None
