"""Real local HTTP ordering for a delayed, valid visual receipt."""
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from mira.config.loader import load_settings
from mira.entrypoints.http.app import create_app


ROOT = Path(__file__).resolve().parents[2]


def _settings():
    return load_settings(root=ROOT, environ={"MIRA_PROFILE": "rehearsal"},
                         overrides={"providers": {"mock_delay_ms": 0}})


def _wait(client, path, headers, *, output_epoch):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        state = client.get(path, headers=headers).json()
        if state["sealed"] and state["output_epoch"] == output_epoch:
            return state
        time.sleep(.005)
    raise AssertionError(f"rehearsal turn {output_epoch} did not seal")


def test_delayed_photo_receipt_blocks_http_input_then_exact_retry_uses_photo():
    with TestClient(create_app(_settings())) as client:
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        path = "/api/v1/sessions/" + created["session"]["session_id"]
        headers = {"X-Mira-Session-Token": created["session_token"]}
        first = {"request_id": str(uuid4()), "activity_seq": 1,
                 "presentation_cutoff": 0, "text": "看照片"}
        assert client.post(path + "/inputs", json=first, headers=headers).status_code == 202
        state = _wait(client, path, headers, output_epoch=1)
        photo = next(effect for effect in state["active_grants"]
                     if effect["kind"] == "media" and effect["value"] == "trip_photo")

        # The client has allocated seq 1 and sends Stop immediately, while its receipt POST is delayed.
        stopped = client.post(path + "/stop", headers=headers,
            json={"activity_seq": 2, "presentation_cutoff": 1})
        assert stopped.status_code == 200
        assert stopped.json()["phase"] == "stopped"
        assert stopped.json()["presented_effects"] == []

        retry = {"request_id": str(uuid4()), "activity_seq": 3,
                 "presentation_cutoff": 1, "text": "照片里有什么"}
        pending = client.post(path + "/inputs", json=retry, headers=headers)
        assert pending.status_code == 409
        assert pending.json()["code"] == "history_pending"
        still_stopped = client.get(path, headers=headers).json()
        assert still_stopped["activity_seq"] == 2 and still_stopped["input_epoch"] == 1
        assert still_stopped["phase"] == "stopped" and still_stopped["presented_effects"] == []

        receipt = {"effect_id": photo["id"], "digest": photo["digest"],
                   "output_epoch": photo["output_epoch"], "activity_seq": photo["activity_seq"],
                   "presentation_seq": 1}
        late = client.post(path + "/receipts", json=receipt, headers=headers)
        assert late.status_code == 200
        assert late.json()["phase"] == "stopped" and late.json()["request_id"] is None
        assert any(effect["id"] == photo["id"] for effect in late.json()["presented_effects"])

        accepted = client.post(path + "/inputs", json=retry, headers=headers)
        assert accepted.status_code == 202 and accepted.json()["request_id"] == retry["request_id"]
        detail = _wait(client, path, headers, output_epoch=3)
        assert any("The picture is still here" in effect["value"]
                   for effect in detail["active_grants"])
        assert not any("haven't opened" in effect["value"] for effect in detail["active_grants"])

        # Exact retransmission after acceptance remains idempotent.
        repeated = client.post(path + "/inputs", json=retry, headers=headers)
        assert repeated.status_code == 202
        assert repeated.json()["output_epoch"] == 3 and repeated.json()["input_epoch"] == 2
