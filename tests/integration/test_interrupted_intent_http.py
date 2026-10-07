"""Actual ASGI request DTO, receipt barrier and continuation retry integration."""
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from mira.bootstrap.providers import Providers
from mira.config.settings import Settings
from mira.entrypoints.http.app import create_app
from tests.unit.test_interrupted_intent import Generate, Review


def _session(client):
    response = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())})
    assert response.status_code == 201
    value = response.json()
    return "/api/v1/sessions/" + value["session"]["session_id"], {"X-Mira-Session-Token": value["session_token"]}


def _ready(client, path, headers):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        state = client.get(path, headers=headers).json()
        if state["sealed"]:
            return state
        time.sleep(.002)
    raise AssertionError("synthetic turn did not seal")


def test_http_partial_reply_three_additions_exact_retry_and_new_topic():
    generation = Generate()
    app = create_app(Settings(), providers=Providers(generation, Review()))
    with TestClient(app) as client:
        path, headers = _session(client)
        request_id = str(uuid4())
        first = {"request_id": request_id, "activity_seq": 1, "presentation_cutoff": 0, "text": "Plan a trip"}
        assert client.post(path + "/inputs", json=first, headers=headers).status_code == 202
        original = _ready(client, path, headers)
        visible = original["active_grants"][0]
        # Stop preserves the unfinished presentation prefix; the input cannot outrun its receipt.
        assert client.post(path + "/stop", headers=headers,
            json={"activity_seq": 2, "presentation_cutoff": 1}).status_code == 200
        second = {"request_id": str(uuid4()), "activity_seq": 3, "presentation_cutoff": 1,
                  "text": "Only two days", "relation": "continuation",
                  "continuation_of_request_id": request_id, "continuation_of_output_epoch": 1}
        pending = client.post(path + "/inputs", json=second, headers=headers)
        assert pending.status_code == 409 and pending.json()["code"] == "history_pending"
        assert len(generation.contexts) == 1
        receipt = {key: visible[key] for key in ("digest", "output_epoch", "activity_seq")}
        receipt.update(effect_id=visible["id"], presentation_seq=1)
        assert client.post(path + "/receipts", json=receipt, headers=headers).status_code == 200
        assert client.post(path + "/inputs", json=second, headers=headers).status_code == 202
        state = _ready(client, path, headers)
        for index in (2, 3):
            body = {"request_id": str(uuid4()), "activity_seq": index + 2, "presentation_cutoff": 1,
                    "text": f"Addition {index}", "relation": "continuation",
                    "continuation_of_request_id": state["request_id"],
                    "continuation_of_output_epoch": state["output_epoch"]}
            assert client.post(path + "/inputs", json=body, headers=headers).status_code == 202
            state = _ready(client, path, headers)
        packet = generation.contexts[-1].request_context
        assert packet.version == 4 and packet.root_request_id == request_id
        assert [part.text for part in packet.accepted_inputs] == ["Plan a trip", "Only two days", "Addition 2", "Addition 3"]
        assert [effect.id for effect in generation.contexts[-1].presented_effects] == [visible["id"]]
        assert len(generation.contexts) == 4
        assert client.post(path + "/inputs", json=body, headers=headers).status_code == 202
        assert client.post(path + "/receipts", json=receipt, headers=headers).status_code == 200
        assert len(generation.contexts) == 4
        changed = dict(body, relation="independent")
        changed.pop("continuation_of_request_id")
        changed.pop("continuation_of_output_epoch")
        assert client.post(path + "/inputs", json=changed, headers=headers).json()["code"] == "request_conflict"
        new_topic = {"request_id": str(uuid4()), "activity_seq": 6, "presentation_cutoff": 1,
                     "text": "A different topic", "relation": "new_topic"}
        assert client.post(path + "/inputs", json=new_topic, headers=headers).status_code == 202
        _ready(client, path, headers)
        context = generation.contexts[-1]
        assert context.request_context.version == 1 and context.request_context.resolution == "new_topic"
        assert len(context.user_inputs) == 5 and len(context.presented_effects) == 1


def test_http_foreign_pointer_is_ordinary_input_and_malformed_relation_is_rejected():
    generation = Generate()
    app = create_app(Settings(), providers=Providers(generation, Review()))
    with TestClient(app) as client:
        path, headers = _session(client)
        foreign_id = str(uuid4())
        assert client.post(path + "/inputs", headers=headers, json={"request_id": foreign_id,
            "activity_seq": 1, "presentation_cutoff": 0, "text": "FOREIGN PRIVATE CONTENT"}).status_code == 202
        _ready(client, path, headers)
        other_path, other_headers = _session(client)
        incoming = {"request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0,
                    "text": "Current request", "relation": "continuation",
                    "continuation_of_request_id": foreign_id, "continuation_of_output_epoch": 1}
        assert client.post(other_path + "/inputs", headers=other_headers, json=incoming).status_code == 202
        _ready(client, other_path, other_headers)
        context = generation.contexts[-1]
        assert context.request_context.resolution == "unmatched_parent"
        assert context.user_inputs == ("Current request",)
        assert "FOREIGN PRIVATE CONTENT" not in repr(context.request_context)
        bad = dict(incoming, request_id=str(uuid4()), activity_seq=2)
        bad.pop("continuation_of_output_epoch")
        assert client.post(other_path + "/inputs", headers=other_headers, json=bad).status_code == 422
        assert len(generation.contexts) == 2
