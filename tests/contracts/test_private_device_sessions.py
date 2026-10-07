"""Synthetic two-browser privacy, revocation and expiry; never opens a socket."""
from uuid import uuid4
from types import SimpleNamespace

from fastapi import WebSocket
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from mira.entrypoints.http.app import create_app
from tests.contracts.test_private_device_access import private_settings, device_pairing, ORIGIN, CODES


def pair(client, code):
    assert client.post("/api/v1/operator/pair", headers={"Origin": ORIGIN}, json={"code": code}).status_code == 204
    return client.cookies.get("mira_operator_session")


def create(client, cookie):
    client.cookies.clear()
    return client.post("/api/v1/sessions", headers={"Origin": ORIGIN,
        "Cookie": "mira_operator_session=" + cookie}, json={"client_instance_id": str(uuid4())})


def headers(cookie, token=None):
    return {"Origin": ORIGIN, "Cookie": "mira_operator_session=" + cookie,
            **({"X-Mira-Session-Token": token} if token else {})}


def test_separate_browser_ownership_rejects_foreign_bearer_and_bounds_one_session_each(settings):
    app = create_app(private_settings(settings), operator_pairing=device_pairing())
    with TestClient(app, base_url=ORIGIN) as client:
        phone = pair(client, CODES[0]); desktop = pair(client, CODES[1])
        first = create(client, phone).json(); second = create(client, desktop).json()
        path = "/api/v1/sessions/" + first["session"]["session_id"]
        assert first["session"]["session_id"] != second["session"]["session_id"]
        assert client.get(path, headers=headers(desktop, first["session_token"])).status_code == 403
        assert client.get(path, headers=headers(phone, first["session_token"])).status_code == 200
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect("wss://mira.local:8443" + path + "/continuous-listening",
                headers=headers(desktop)):
                pass
        assert caught.value.code == 4403
        replacement = create(client, phone)
        assert replacement.status_code == 201
        assert client.get(path, headers=headers(phone, first["session_token"])).status_code == 403
        fresh = replacement.json()
        assert client.delete("/api/v1/sessions/" + fresh["session"]["session_id"],
                             headers=headers(phone, fresh["session_token"])).status_code == 204
        assert create(client, phone).status_code == 201
        assert client.get("/api/v1/sessions/" + second["session"]["session_id"],
                          headers=headers(desktop, second["session_token"])).status_code == 200


def test_revoking_phone_closes_only_phone_and_its_open_socket(settings):
    app = create_app(private_settings(settings), operator_pairing=device_pairing())
    async def echo(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"ready": True})
        while True:
            await websocket.receive_text()
    app.add_api_websocket_route("/api/v1/sessions/{session_id}/synthetic-socket", echo)
    with TestClient(app, base_url=ORIGIN) as client:
        phone = pair(client, CODES[0]); desktop = pair(client, CODES[1])
        first = create(client, phone).json(); second = create(client, desktop).json()
        container = app.state.container
        path = "/api/v1/sessions/" + first["session"]["session_id"]
        with client.websocket_connect("wss://mira.local:8443" + path + "/synthetic-socket", headers=headers(phone)) as ws:
            assert ws.receive_json()["ready"]
            assert client.post("/api/v1/operator/revoke", headers=headers(phone)).status_code == 204
            with pytest.raises(WebSocketDisconnect) as caught:
                ws.receive_json()
            assert caught.value.code == 4403
        assert app.state.container is container
        assert first["session"]["session_id"] not in container.sessions._sessions
        assert client.get("/api/v1/sessions/" + second["session"]["session_id"],
                          headers=headers(desktop, second["session_token"])).status_code == 200
        assert client.get("/api/v1/operator/status", headers=headers(phone)).json()["revoked"]
        assert client.get("/api/v1/operator/status", headers=headers(desktop)).json()["paired"]


def test_expiry_closes_owned_session_and_socket_without_new_http_request(settings, monkeypatch):
    from mira.entrypoints.http import operator_pairing
    clock = [100.0]
    monkeypatch.setattr(operator_pairing, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    from mira.entrypoints.http.device_pairing import DevicePairing
    pairing = DevicePairing(CODES, (ORIGIN,), session_ttl_seconds=60)
    app = create_app(private_settings(settings), operator_pairing=pairing)
    async def echo(websocket: WebSocket):
        await websocket.accept(); await websocket.send_json({"ready": True})
        await websocket.receive_text()
    app.add_api_websocket_route("/api/v1/sessions/{session_id}/synthetic-socket", echo)
    with TestClient(app, base_url=ORIGIN) as client:
        phone = pair(client, CODES[0]); first = create(client, phone).json()
        clock[0] = 130.0
        desktop = pair(client, CODES[1]); second = create(client, desktop).json()
        path = "/api/v1/sessions/" + first["session"]["session_id"]
        with client.websocket_connect("wss://mira.local:8443" + path + "/synthetic-socket", headers=headers(phone)) as ws:
            assert ws.receive_json()["ready"]
            clock[0] = 161.0
            with pytest.raises(WebSocketDisconnect) as caught:
                ws.receive_json()
            assert caught.value.code == 4403
        # Force sweep completion deterministically through its public async method.
        client.portal.call(app.state.device_sessions.sweep, app.state.container, pairing)
        assert first["session"]["session_id"] not in app.state.container.sessions._sessions
        assert second["session"]["session_id"] in app.state.container.sessions._sessions


def test_private_devices_cannot_enable_application_global_raw_audio_recording(settings):
    app = create_app(private_settings(settings), operator_pairing=device_pairing())
    with TestClient(app, base_url=ORIGIN) as client:
        phone = pair(client, CODES[0]); desktop = pair(client, CODES[1])
        sessions = [(phone, create(client, phone).json()),
                    (desktop, create(client, desktop).json())]
        for cookie, session in sessions:
            path = '/api/v1/sessions/' + session['session']['session_id'] + '/reviewed-audio'
            response = client.post(path + '/recording',
                headers=headers(cookie, session['session_token']),
                json={'enabled': True, 'consent': True})
            assert response.status_code == 409
            assert response.json()['code'] == 'private_device_audio_recording_unavailable'
            assert response.json()['recording_active'] is False
        for cookie, session in sessions:
            path = '/api/v1/sessions/' + session['session']['session_id'] + '/reviewed-audio'
            assert client.get(path, headers=headers(cookie, session['session_token'])).json()['recording_active'] is False
