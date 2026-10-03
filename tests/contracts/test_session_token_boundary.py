"""Hostile WebSocket token strings are authentication failures, never tracebacks."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.config.settings import Settings
from mira.entrypoints.http.app import create_app


@pytest.mark.parametrize("bad_token, expected_code", [
    ("密" * 32, "session_not_found"), ("🔒" * 32, "session_not_found"),
    ("\ud800", "invalid_input"),  # Invalid Unicode is already rejected by the DTO boundary.
])
def test_non_ascii_microphone_token_is_rejected_safely(bad_token, expected_code):
    settings = Settings(diagnostics={"enabled": False})
    with TestClient(create_app(settings)) as client:
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        session_id = created["session"]["session_id"]
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/microphone",
                headers={"Origin": "http://localhost:8000"}) as socket:
            socket.send_json({"type": "start", "session_token": bad_token,
                "stream_id": str(uuid4()), "activity_seq": 0, "input_epoch": 0,
                "sample_rate_hz": 16000})
            frame = socket.receive_json()
            assert set(frame) == {"type", "code", "diagnostic_id"}
            assert frame["type"] == "error" and frame["code"] == expected_code
            assert __import__("re").fullmatch(r"h_[0-9a-f]{32}", frame["diagnostic_id"])
            assert bad_token not in frame["diagnostic_id"]
        # Failed authentication does not revoke or disclose the actual session token.
        response = client.get(f"/api/v1/sessions/{session_id}",
            headers={"X-Mira-Session-Token": created["session_token"]})
        assert response.status_code == 200
