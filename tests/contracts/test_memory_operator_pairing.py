"""Synthetic-only HTTP boundary tests for local operator memory pairing."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.application.actor_memory import SessionMemoryBinding
from mira.config.loader import ConfigurationError
from mira.domain.memory import MemoryScope
from mira.entrypoints.http.app import create_app
from mira.entrypoints.http.operator_pairing import OperatorPairing

ORIGIN = "http://testserver"
HOST = "testserver"
CODE = "synthetic-pair-code-only-0123456789"


class Reader:
    def __init__(self):
        self.closed = 0
        self.reads = 0

    async def build_packet(self, **_kwargs):
        self.reads += 1
        raise AssertionError("no private recall expected in pairing tests")

    async def scope_revision(self, _scope):
        self.reads += 1
        return 0

    async def aclose(self):
        self.closed += 1


def configured(settings):
    return settings.model_copy(update={
        "runtime": settings.runtime.model_copy(update={"max_sessions": 1}),
        "http": settings.http.model_copy(update={"allowed_origins": (ORIGIN,)}),
    })


def make_factory():
    reader = Reader()
    calls = []

    async def factory():
        calls.append("open")
        return SessionMemoryBinding(reader, MemoryScope("synthetic-user", "mira", "synthetic-world"))

    return factory, reader, calls


def pairing(code=CODE, **kwargs):
    return OperatorPairing(code, (ORIGIN,), **kwargs)


def headers(origin=ORIGIN, host=HOST):
    return {"Origin": origin, "Host": host}


def pair(client, code=CODE):
    return client.post("/api/v1/operator/pair", json={"code": code}, headers=headers())


def test_memory_mode_rejects_missing_ephemeral_pairing(settings):
    factory, _reader, calls = make_factory()
    with pytest.raises(ConfigurationError, match="memory_operator_pairing_required"):
        create_app(configured(settings), memory_factory=factory)
    assert calls == []


def test_pairing_rejected_for_non_memory_apps(settings):
    with pytest.raises(ConfigurationError, match="operator_pairing_requires_memory_mode"):
        create_app(configured(settings), operator_pairing=pairing())


def test_constructor_rejects_weak_pairing_codes():
    with pytest.raises(ValueError, match="operator_pairing_configuration_invalid"):
        OperatorPairing("short", (ORIGIN,))


def test_pairing_capability_cannot_be_shared_between_app_instances(settings):
    factory, _reader, _calls = make_factory()
    capability = pairing()
    create_app(configured(settings), memory_factory=factory, operator_pairing=capability)
    other_factory, _other_reader, _other_calls = make_factory()
    with pytest.raises(ConfigurationError, match="memory_operator_pairing_already_bound"):
        create_app(configured(settings), memory_factory=other_factory, operator_pairing=capability)


def test_pairing_origin_set_must_match_app_cors_allowlist(settings):
    factory, _reader, calls = make_factory()
    with pytest.raises(ConfigurationError, match="memory_operator_origins_mismatch"):
        create_app(configured(settings), memory_factory=factory,
                   operator_pairing=OperatorPairing(CODE, ("http://localhost:8000",)))
    assert calls == []


def test_status_exposes_only_three_booleans_before_pair(settings):
    factory, reader, calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        response = client.get("/api/v1/operator/status")
        assert response.status_code == 200
        assert response.json() == {"required": True, "paired": False, "revoked": False}
        assert calls == [] and reader.reads == 0


@pytest.mark.parametrize("path,method", [
    ("/api/v1/sessions", "post"),
    ("/api/v1/sessions/00000000-0000-0000-0000-000000000001", "get"),
    ("/api/v1/diagnostics-status", "get"),
    ("/api/v1/voice-capabilities", "get"),
    ("/api/v1/sessions/00000000-0000-0000-0000-000000000001/reviewed-audio", "get"),
    ("/api/v1/sessions/00000000-0000-0000-0000-000000000001/reviewed-audio/recording", "post"),
    ("/api/v1/sessions/00000000-0000-0000-0000-000000000001/speech/00000000-0000-0000-0000-000000000001/stream", "post"),
])
def test_private_http_and_recording_apis_are_blocked_pre_pair(settings, path, method):
    factory, reader, calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        request = getattr(client, method)
        response = request(path, json={"enabled": True}, headers=headers()) if method == "post" else request(path, headers=headers())
        assert response.status_code == 401
        assert calls == [] and reader.reads == 0


def test_unpaired_mutation_without_origin_is_rejected_before_memory_factory(settings):
    factory, reader, calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        response = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())})
        assert response.status_code == 403
        assert calls == [] and reader.reads == 0


def test_bad_pair_code_is_generic_and_does_not_start_memory(settings, caplog):
    factory, reader, calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        response = pair(client, "synthetic-wrong-code")
        assert response.status_code == 401
        assert "synthetic-wrong-code" not in response.text
        assert "synthetic-wrong-code" not in str(response.headers)
        assert "synthetic-wrong-code" not in caplog.text
        assert calls == [] and reader.reads == 0


@pytest.mark.parametrize("payload", [
    {"code": "synthetic-malformed-secret-000000000000", "unexpected": True},
    {"code": "synthetic-malformed-secret-000000000000" + "x" * 129},
    {"not_code": "synthetic-malformed-secret-000000000000"},
])
def test_invalid_pair_bodies_never_echo_synthetic_input(settings, caplog, payload):
    factory, reader, calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        response = client.post("/api/v1/operator/pair", json=payload, headers=headers())
        assert response.status_code == 422
        assert "synthetic-malformed-secret" not in response.text
        assert "synthetic-malformed-secret" not in str(response.headers)
        assert "synthetic-malformed-secret" not in caplog.text
        assert calls == [] and reader.reads == 0


@pytest.mark.parametrize("origin,host", [(None, HOST), ("http://evil", "evil"),
                                           (ORIGIN, "localhost:8000")])
def test_pair_requires_exact_origin_and_matching_host(settings, origin, host):
    factory, reader, calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        supplied = {}
        if origin is not None:
            supplied["Origin"] = origin
        if host is not None:
            supplied["Host"] = host
        response = client.post("/api/v1/operator/pair", json={"code": CODE}, headers=supplied)
        assert response.status_code >= 400
        assert calls == [] and reader.reads == 0


def test_pair_rejects_unknown_origin_before_route(settings):
    factory, reader, calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        response = client.post("/api/v1/operator/pair", json={"code": CODE},
                               headers=headers("http://evil", "evil"))
        assert response.status_code == 403
        assert calls == [] and reader.reads == 0


def test_successful_pair_only_sets_opaque_httponly_strict_cookie(settings):
    factory, reader, calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        response = pair(client)
        assert response.status_code == 204 and not response.content
        cookie = response.headers["set-cookie"].lower()
        assert "mira_operator_session=" in cookie
        assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/v1" in cookie
        assert CODE not in response.headers["set-cookie"] and CODE not in response.text
        assert calls == ["open"] and reader.reads == 0
        assert client.get("/api/v1/operator/status", headers=headers()).json() == {
            "required": True, "paired": True, "revoked": False}


def test_operator_status_does_not_report_another_clients_pairing(settings):
    factory, _reader, _calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        assert pair(client).status_code == 204
        assert client.get("/api/v1/operator/status", headers=headers()).json()["paired"] is True
        client.cookies.clear()
        unauthenticated = client.get("/api/v1/operator/status", headers={"Sec-Fetch-Site": "same-origin"})
        assert unauthenticated.json() == {"required": True, "paired": False, "revoked": False}


def test_browser_same_origin_get_without_origin_is_authenticated(settings):
    factory, reader, _calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        assert pair(client).status_code == 204
        status = client.get("/api/v1/operator/status", headers={"Sec-Fetch-Site": "same-origin"})
        assert status.status_code == 200 and status.json()["paired"] is True
        diagnostics = client.get("/api/v1/diagnostics-status", headers={"Sec-Fetch-Site": "same-origin"})
        assert diagnostics.status_code == 200
        assert reader.closed == 0


def test_missing_origin_safe_get_without_same_origin_metadata_is_denied(settings):
    factory, _reader, _calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        assert pair(client).status_code == 204
        assert client.get("/api/v1/diagnostics-status").status_code == 401


def test_browser_same_origin_referer_can_bind_safe_get_without_origin(settings):
    factory, _reader, _calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        assert pair(client).status_code == 204
        response = client.get("/api/v1/diagnostics-status", headers={"Referer": ORIGIN + "/"})
        assert response.status_code == 200


@pytest.mark.parametrize("fetch_site,referer", [
    ("cross-site", None), ("same-origin", "http://evil/"), (None, "http://evil/")])
def test_cross_origin_or_mismatched_metadata_safe_get_denied(settings, fetch_site, referer):
    factory, _reader, _calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        assert pair(client).status_code == 204
        request_headers = {}
        if fetch_site is not None:
            request_headers["Sec-Fetch-Site"] = fetch_site
        if referer is not None:
            request_headers["Referer"] = referer
        response = client.get("/api/v1/diagnostics-status", headers=request_headers)
        assert response.status_code == 401


def test_session_bearer_is_still_required_after_cookie_pairing(settings):
    factory, _reader, _calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        assert pair(client).status_code == 204
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())},
                              headers=headers())
        assert created.status_code == 201
        session_id = created.json()["session"]["session_id"]
        path = f"/api/v1/sessions/{session_id}"
        assert client.get(path, headers=headers()).status_code == 422
        assert client.get(path, headers={**headers(), "X-Mira-Session-Token": "wrong"}).status_code == 404
        good = {**headers(), "X-Mira-Session-Token": created.json()["session_token"]}
        assert client.get(path, headers=good).status_code == 200


def test_cookie_is_bound_to_exact_origin_and_host(settings):
    factory, reader, calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        assert pair(client).status_code == 204
        denied = client.get("/api/v1/diagnostics-status", headers=headers("http://localhost:8000", "localhost:8000"))
        assert denied.status_code == 401
        denied_host = client.get("/api/v1/diagnostics-status",
                                 headers={"Origin": ORIGIN, "Host": "localhost:8000"})
        assert denied_host.status_code == 401
        assert calls == ["open"] and reader.reads == 0


def test_pair_code_is_one_use_and_failed_attempt_bound(settings):
    verifier = pairing(max_attempts=2)
    assert verifier.pair("bad", ORIGIN, HOST) is None
    assert verifier.pair("bad-again", ORIGIN, HOST) is None
    assert verifier.pair(CODE, ORIGIN, HOST) is None
    assert verifier.status() == {"required": True, "paired": False, "revoked": True}
    verifier = pairing()
    cookie = verifier.pair(CODE, ORIGIN, HOST)
    assert cookie and verifier.pair(CODE, ORIGIN, HOST) is None
    assert verifier.is_authenticated(cookie, ORIGIN, HOST)


def test_pairing_expiry_rejects_candidate_without_runtime_start(settings, monkeypatch):
    import mira.entrypoints.http.operator_pairing as pairing_module
    now = [100.0]
    monkeypatch.setattr(pairing_module.time, "monotonic", lambda: now[0])
    verifier = pairing(ttl_seconds=2)
    now[0] += 3
    assert verifier.pair(CODE, ORIGIN, HOST) is None
    assert verifier.status() == {"required": True, "paired": False, "revoked": True}


def test_revocation_closes_runtime_invalidates_cookie_and_prevents_replay(settings):
    factory, reader, calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        assert pair(client).status_code == 204
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}, headers=headers())
        assert created.status_code == 201
        revoked = client.post("/api/v1/operator/revoke", headers=headers())
        assert revoked.status_code == 204
        assert reader.closed == 1
        assert client.get("/api/v1/operator/status").json() == {
            "required": True, "paired": False, "revoked": True}
        assert client.get("/api/v1/sessions", headers=headers()).status_code == 401
        assert pair(client).status_code == 423
        assert calls == ["open"]


def test_stop_does_not_unpair_operator(settings):
    factory, reader, _calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        assert pair(client).status_code == 204
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}, headers=headers()).json()
        stopped = client.post(f"/api/v1/sessions/{created['session']['session_id']}/stop",
            headers={**headers(), "X-Mira-Session-Token": created["session_token"]},
            json={"activity_seq": 1, "presentation_cutoff": 0})
        assert stopped.status_code == 200
        assert client.get("/api/v1/operator/status", headers=headers()).json()["paired"] is True
        assert reader.closed == 0


def test_startup_failure_after_valid_code_revokes_pair_and_closes_reader(settings, monkeypatch):
    from mira.entrypoints.http import app as app_module
    factory, reader, calls = make_factory()
    monkeypatch.setattr(app_module, "build_container",
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("private synthetic failure")))
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        response = pair(client)
        assert response.status_code == 503
        assert "private synthetic failure" not in response.text
        assert "synthetic-pair-code-only" not in response.text
        assert client.get("/api/v1/operator/status").json()["revoked"] is True
        assert calls == ["open"] and reader.closed == 1


def test_cancellation_resistant_late_factory_result_is_closed(settings, monkeypatch):
    import asyncio
    from mira.entrypoints.http import app as app_module

    monkeypatch.setattr(app_module, "MEMORY_FACTORY_STARTUP_TIMEOUT_SECONDS", 0.01)
    reader = Reader()
    calls = []

    async def slow_factory():
        calls.append("open")
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            # Simulate a factory that takes time to unwind cancellation and
            # returns an already-opened binding after its caller gave up.
            await asyncio.sleep(0.02)
            return SessionMemoryBinding(reader, MemoryScope("synthetic-user", "mira", "synthetic-world"))

    app = create_app(configured(settings), memory_factory=slow_factory, operator_pairing=pairing())
    with TestClient(app) as client:
        response = pair(client)
        assert response.status_code == 503
        assert client.get("/api/v1/operator/status", headers=headers()).json()["revoked"] is True
        # Let the late-completion callback schedule reader closure on the app loop.
        import time
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline and reader.closed == 0:
            time.sleep(0.005)
        assert calls == ["open"] and reader.closed == 1


def test_cancelled_pair_startup_closes_uncooperative_late_binding(settings):
    import asyncio
    import threading
    import time
    from concurrent.futures import CancelledError

    reader = Reader()
    started = threading.Event()

    async def slow_factory():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.02)
            return SessionMemoryBinding(reader, MemoryScope("synthetic-user", "mira", "synthetic-world"))

    app = create_app(configured(settings), memory_factory=slow_factory, operator_pairing=pairing())
    with TestClient(app) as client:
        # This directly exercises the post-auth startup cancellation seam. Match
        # the real pair route's accepted pairing before calling the internal hook.
        assert app.state.operator_pairing.pair(CODE, ORIGIN, HOST,
            app_id=app.state.operator_app_id) is not None
        future = client.portal.start_task_soon(app.state.ensure_runtime)
        assert started.wait(1.0)
        future.cancel()
        with pytest.raises(CancelledError):
            future.result(timeout=1.0)
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline and reader.closed == 0:
            time.sleep(0.005)
        assert reader.closed == 1 and app.state.container is None


def test_internal_lazy_startup_cannot_open_a_private_reader_before_pair(settings):
    factory, reader, calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        with pytest.raises(PermissionError):
            client.portal.call(app.state.ensure_runtime)
        assert calls == [] and reader.reads == 0 and app.state.container is None


def test_application_shutdown_invalidates_cookie_and_closes_reader(settings):
    factory, reader, _calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    client = TestClient(app)
    with client:
        assert pair(client).status_code == 204
    assert reader.closed == 1
    with TestClient(app) as again:
        assert again.get("/api/v1/operator/status").json()["revoked"] is True
        assert pair(again).status_code == 423


def test_websocket_private_path_is_blocked_before_pair(settings):
    factory, reader, calls = make_factory()
    app = create_app(configured(settings), memory_factory=factory, operator_pairing=pairing())
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/api/v1/sessions/00000000-0000-0000-0000-000000000001/microphone",
                headers=headers()):
                pass
        assert calls == [] and reader.reads == 0


def test_memory_index_gets_static_pairing_marker_nonmemory_index_does_not(settings, tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><html><body><main></main></body></html>")
    (tmp_path / "public").mkdir()
    (tmp_path / "dist").mkdir()
    factory, _reader, _calls = make_factory()
    memory_app = create_app(configured(settings), memory_factory=factory,
                            operator_pairing=pairing(), web_root=tmp_path)
    with TestClient(memory_app) as client:
        assert 'data-operator-pairing="required"' in client.get("/").text
        assert CODE not in client.get("/").text
    plain_app = create_app(configured(settings), web_root=tmp_path)
    with TestClient(plain_app) as client:
        assert "data-operator-pairing" not in client.get("/").text


def test_nonmemory_app_behavior_remains_unchanged(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/operator/status").status_code == 404
