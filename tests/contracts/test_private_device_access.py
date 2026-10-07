"""Synthetic-only private LAN policy and per-browser one-use pairing checks."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from mira.config.settings import HttpSettings
from mira.entrypoints.http.app import create_app

ORIGIN = "https://mira.local:8443"
CODES = ("synthetic-phone-pairing-code-00000001", "synthetic-desktop-pairing-code-00002")


def private_settings(settings, origin=ORIGIN, host="192.168.20.8"):
    return settings.model_copy(update={"http": settings.http.model_copy(update={
        "host": host, "port": 8443, "allowed_origins": (origin,), "private_network": True}),
        "runtime": settings.runtime.model_copy(update={"max_sessions": 2})})


def device_pairing(origin=ORIGIN):
    from mira.entrypoints.http.device_pairing import DevicePairing
    return DevicePairing(CODES, (origin,))


def test_loopback_default_and_explicit_private_only():
    assert HttpSettings().host == "127.0.0.1"
    for host in ("0.0.0.0", "::", "8.8.8.8", "192.168.20.8"):
        with pytest.raises(ValidationError):
            HttpSettings(host=host)
    for host in ("192.168.20.8", "10.3.2.1", "172.16.2.8", "fd12:3456::8"):
        assert HttpSettings(host=host, port=8443, private_network=True,
                            allowed_origins=(ORIGIN,)).host == host


@pytest.mark.parametrize("host,origin", [
    ("0.0.0.0", ORIGIN), ("::", ORIGIN), ("8.8.8.8", ORIGIN),
    ("100.64.0.1", ORIGIN), ("169.254.1.8", ORIGIN), ("fe80::8", ORIGIN),
    ("192.168.20.8", "https://mira.local:8443/"),
    ("192.168.20.8", "https://mira.local:8443?token=secret"),
    ("192.168.20.8", "https://user@mira.local:8443"),
    ("192.168.20.8", "https://*.local:8443"),
    ("192.168.20.8", "https://mira.local:9443"),
    ("192.168.20.8", "https://8.8.8.8:8443"),
])
def test_private_configuration_rejects_ambiguous_bind_or_origin(host, origin):
    with pytest.raises(ValidationError):
        HttpSettings(host=host, port=8443, private_network=True, allowed_origins=(origin,))


def test_two_codes_are_independent_one_use_and_revoke_is_scoped():
    pairing = device_pairing()
    pairing.bind_app("app-one")
    phone = pairing.pair(CODES[0], ORIGIN, "mira.local:8443", app_id="app-one")
    desktop = pairing.pair(CODES[1], ORIGIN, "mira.local:8443", app_id="app-one")
    assert phone and desktop and phone != desktop
    assert pairing.pair(CODES[0], ORIGIN, "mira.local:8443", app_id="app-one") is None
    assert pairing.identity(phone) != pairing.identity(desktop)
    assert not pairing.is_authenticated(phone, ORIGIN, "other.local:8443", app_id="app-one")
    identity = pairing.identity(phone)
    assert pairing.revoke_device(phone) == identity
    assert pairing.identity(phone) is None
    assert pairing.status(phone)["revoked"]
    assert pairing.is_authenticated(desktop, ORIGIN, "mira.local:8443", app_id="app-one")
    assert not pairing.is_authenticated(desktop, ORIGIN, "mira.local:8443", app_id="another-app")
    pairing.revoke()
    assert pairing.status()["revoked"]
    assert pairing.identity(desktop) is None


def test_wrong_pairing_origin_cannot_consume_valid_code():
    pairing = device_pairing()
    pairing.bind_app("app-one")
    assert pairing.pair(CODES[0], "https://evil.local:8443", "evil.local:8443", app_id="app-one") is None
    assert pairing.pair(CODES[0], ORIGIN, "mira.local:8443", app_id="app-one")


def test_private_app_requires_temporary_device_pairing_before_runtime(settings):
    from mira.config.loader import ConfigurationError
    with pytest.raises(ConfigurationError, match="private_device_pairing_required"):
        create_app(private_settings(settings))
    app = create_app(private_settings(settings), operator_pairing=device_pairing())
    with TestClient(app, base_url=ORIGIN) as client:
        assert app.state.container is None
        assert client.post("/api/v1/sessions", headers={"Origin": ORIGIN},
                           json={"client_instance_id": str(uuid4())}).status_code == 401
        assert app.state.container is None
        response = client.post("/api/v1/operator/pair", headers={"Origin": ORIGIN}, json={"code": CODES[0]})
        assert response.status_code == 204
        assert "Secure" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert app.state.container is not None
        assert client.post("/api/v1/sessions", headers={"Origin": ORIGIN},
                           json={"client_instance_id": str(uuid4())}).status_code == 201


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.local:8443"},
    {"Origin": ORIGIN, "Host": "evil.local:8443"},
    {"Origin": ORIGIN, "Host": "mira.local:9443"},
    {"Origin": ORIGIN, "Host": "127.0.0.1:8443"},
    {},
    [("origin", ORIGIN), ("origin", ORIGIN)],
    [("origin", ORIGIN), ("host", "mira.local:8443"), ("host", "mira.local:8443")],
])
def test_private_pairing_rejects_csrf_wrong_authority_and_duplicate_headers(settings, headers):
    app = create_app(private_settings(settings), operator_pairing=device_pairing())
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post("/api/v1/operator/pair", headers=headers, json={"code": CODES[0]})
        assert response.status_code == 403
        assert app.state.container is None


def test_private_tls_policy_rejects_plaintext_and_forwarded_spoofing(settings):
    app = create_app(private_settings(settings), operator_pairing=device_pairing())
    with TestClient(app, base_url="http://mira.local:8443") as client:
        assert client.get("/", headers={"X-Forwarded-Proto": "https"}).status_code == 403
        assert client.post("/api/v1/operator/pair", headers={"Origin": ORIGIN,
            "X-Forwarded-Proto": "https"}, json={"code": CODES[0]}).status_code == 403
        assert app.state.container is None


def test_private_websocket_requires_matching_origin_host_and_cookie_before_runtime(settings):
    app = create_app(private_settings(settings), operator_pairing=device_pairing())
    with TestClient(app, base_url=ORIGIN) as client:
        for headers in ({"Origin": ORIGIN}, {"Origin": "https://evil.local:8443"},
                        {"Origin": ORIGIN, "Host": "mira.local:9443"}):
            with pytest.raises(WebSocketDisconnect) as caught:
                with client.websocket_connect("wss://mira.local:8443/api/v1/sessions/unknown/listen", headers=headers):
                    pass
            assert caught.value.code == 4403
        assert app.state.container is None


def test_private_mode_rejects_memory_factories_and_more_than_two_sessions(settings):
    from mira.config.loader import ConfigurationError
    configured = private_settings(settings)
    with pytest.raises(ConfigurationError, match="private_device_mode_ephemeral_only"):
        create_app(configured, operator_pairing=device_pairing(), character_binding_factory=lambda: None)
    with pytest.raises(ConfigurationError, match="private_device_session_capacity"):
        create_app(configured.model_copy(update={"runtime": configured.runtime.model_copy(update={"max_sessions": 3})}),
                   operator_pairing=device_pairing())
