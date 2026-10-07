import asyncio

import pytest
from fastapi.testclient import TestClient

from mira.application.memory_management import MemoryManagement
from mira.application.ports.memory_management import MemoryManagementPage
from mira.entrypoints.http.local_memory_app import create_local_memory_app
from mira.entrypoints.http import local_memory_app
from mira.entrypoints.http.operator_pairing import OperatorPairing

ORIGIN = "http://127.0.0.1:8761"
HOST = "127.0.0.1:8761"
CODE = "synthetic-local-pair-code-0123456789"


class FakeBackend:
    def __init__(self):
        self.opened = 0
        self.closed = 0

    async def open(self):
        self.opened += 1

    async def scope_revision(self):
        return 0

    async def list_entries(self, **_kwargs):
        return MemoryManagementPage(revision=0, entries=(), next_cursor=None)

    async def apply_operation(self, _command):
        raise AssertionError("not needed by these route-boundary tests")

    async def aclose(self):
        self.closed += 1


def test_console_exposes_only_allowlisted_local_routes(tmp_path):
    app = create_local_memory_app(
        management_factory=lambda: None,
        pairing=OperatorPairing(CODE, (ORIGIN,)),
        web_root=tmp_path,
    )
    paths = {route.path for route in app.routes}
    assert paths == {
        "/health", "/", "/local-memory.js", "/local-memory.css",
        "/api/v1/operator/status", "/api/v1/operator/pair", "/api/v1/operator/revoke",
        "/api/v1/memory-management/status", "/api/v1/memory-management/entries",
        "/api/v1/memory-management/operations",
    }
    with TestClient(app) as client:
        assert client.get("/health", headers={"host": HOST}).status_code == 200
        assert client.get("/api/v1/health", headers={"host": HOST}).status_code == 404
        assert client.post("/api/v1/sessions", headers={"host": HOST}).status_code == 404
        assert client.get("/docs", headers={"host": HOST}).status_code == 404
        assert client.get("/local-memory.js", headers={"host": HOST}).status_code == 404


def test_console_rejects_unapproved_host_and_origin(tmp_path):
    app = create_local_memory_app(
        management_factory=lambda: None,
        pairing=OperatorPairing(CODE, (ORIGIN,)),
        web_root=tmp_path,
    )
    with TestClient(app) as client:
        assert client.get("/health", headers={"host": "example.test"}).status_code == 400
        status = client.get("/api/v1/operator/status", headers={"host": HOST,
                                                                  "origin": "https://evil.test"})
        assert status.status_code == 403


def test_pairing_is_the_first_operation_that_opens_management_store(tmp_path):
    calls = []
    backend = FakeBackend()

    async def factory():
        calls.append("open")
        manager = MemoryManagement(backend, authorized=True)
        await manager.open()
        return manager

    app = create_local_memory_app(
        management_factory=factory,
        pairing=OperatorPairing(CODE, (ORIGIN,)),
        web_root=tmp_path,
    )
    with TestClient(app) as client:
        headers = {"host": HOST, "origin": ORIGIN}
        assert client.get("/health", headers={"host": HOST}).status_code == 200
        assert client.get("/api/v1/operator/status", headers=headers).json() == {
            "required": True, "paired": False, "revoked": False,
        }
        assert client.get("/api/v1/memory-management/status", headers=headers).status_code == 401
        assert calls == []
        paired = client.post("/api/v1/operator/pair", headers=headers, json={"code": "wrong"})
        assert paired.status_code == 401 and calls == []
        paired = client.post("/api/v1/operator/pair", headers=headers, json={"code": CODE})
        assert paired.status_code == 204 and calls == ["open"]
        status = client.get("/api/v1/memory-management/status", headers=headers)
        assert status.status_code == 200 and status.json() == {"enabled": True, "revision": 0}
        assert backend.opened == 1


def test_revoke_and_shutdown_close_manager_and_revoke_pairing(tmp_path):
    backend = FakeBackend()

    async def factory():
        manager = MemoryManagement(backend, authorized=True)
        await manager.open()
        return manager

    pairing = OperatorPairing(CODE, (ORIGIN,))
    app = create_local_memory_app(management_factory=factory, pairing=pairing, web_root=tmp_path)
    with TestClient(app) as client:
        headers = {"host": HOST, "origin": ORIGIN}
        assert client.post("/api/v1/operator/pair", headers=headers, json={"code": CODE}).status_code == 204
        assert client.post("/api/v1/operator/revoke", headers=headers).status_code == 204
        assert backend.closed == 1 and pairing.status()["revoked"] is True
    assert backend.closed == 1


def test_shutdown_without_revoke_closes_manager_and_revokes_pairing(tmp_path):
    backend = FakeBackend()

    async def factory():
        manager = MemoryManagement(backend, authorized=True)
        await manager.open()
        return manager

    pairing = OperatorPairing(CODE, (ORIGIN,))
    app = create_local_memory_app(management_factory=factory, pairing=pairing, web_root=tmp_path)
    with TestClient(app) as client:
        assert client.post("/api/v1/operator/pair", headers={"host": HOST, "origin": ORIGIN},
                           json={"code": CODE}).status_code == 204
        assert backend.closed == 0
    assert backend.closed == 1
    assert pairing.status()["revoked"] is True


def test_timed_out_pairing_startup_cancels_lazy_factory_and_revokes(tmp_path, monkeypatch):
    cancelled = []

    async def factory():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append("cancelled")
            raise

    monkeypatch.setattr(local_memory_app, "MANAGEMENT_FACTORY_TIMEOUT_SECONDS", 0.01)
    pairing = OperatorPairing(CODE, (ORIGIN,))
    app = create_local_memory_app(management_factory=factory, pairing=pairing, web_root=tmp_path)
    with TestClient(app) as client:
        result = client.post("/api/v1/operator/pair", headers={"host": HOST, "origin": ORIGIN},
                             json={"code": CODE})
        assert result.status_code == 503
        assert cancelled == ["cancelled"]
        assert pairing.status()["revoked"] is True
