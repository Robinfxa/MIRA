"""FND02-001/008: configuration reaches HTTP without a second execution engine."""
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.config.loader import ConfigurationError, load_settings
from mira.entrypoints.http.app import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_replay_profile_uses_existing_http_permits_and_receipts():
    settings = load_settings(root=ROOT, environ={"MIRA_PROFILE": "replay"})
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/v1/health").json()
        assert health["mode"] == "mock"  # fixed-fixture family, NOT live inference
        assert not any(health[key] for key in ("live_llm", "live_audio", "live_images"))
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        path = "/api/v1/sessions/" + created["session"]["session_id"]
        headers = {"X-Mira-Session-Token": created["session_token"]}
        body = {"request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0, "text": "fixture"}
        assert client.post(path + "/inputs", headers=headers, json=body).status_code == 202
        deadline = time.monotonic() + 1
        while True:
            state = client.get(path, headers=headers).json()
            if state["sealed"]:
                break
            assert time.monotonic() < deadline, "fixture did not finish"
            time.sleep(0.001)  # polling an actual HTTP state, not manufacturing a race
        assert len(state["active_grants"]) == 2 and not state["presented_effects"]
        first = state["active_grants"][0]
        receipt = {"effect_id": first["id"], "digest": first["digest"], "output_epoch": 1,
                   "activity_seq": 1, "presentation_seq": 1}
        assert client.post(path + "/receipts", headers=headers, json=receipt).status_code == 200
        stopped = client.post(path + "/stop", headers=headers,
                              json={"activity_seq": 2, "presentation_cutoff": 1}).json()
        assert stopped["active_grants"] == [] and len(stopped["presented_effects"]) == 1
        assert client.post(path + "/inputs", headers=headers, json=body).json() == stopped
        assert client.delete(path, headers=headers).status_code == 204


@pytest.mark.parametrize("name", ["../../.env", "https://example.test", "not-registered"])
def test_bad_replay_configuration_fails_without_reflecting_value(name):
    with pytest.raises(ConfigurationError) as error:
        load_settings(root=ROOT, environ={"MIRA_PROVIDERS__REPLAY_SCENARIO": name})
    assert name not in str(error.value)
