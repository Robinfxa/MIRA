"""Real HTTP/domain audio progress with explicit synthetic, never-live providers."""
import time
from uuid import uuid4

import pytest
from tests.integration.test_voice_http import Tts
from fastapi.testclient import TestClient

from mira.application.contracts import (
    CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict,
)
from mira.bootstrap.providers import Providers
from mira.config.settings import Settings
from mira.domain.models import EffectKind
from mira.entrypoints.http.app import create_app


class SpeechGeneration:
    async def generate(self, context):
        yield CandidateRange((EffectProposal(EffectKind.SPEECH, "你好，雨还在下。"),),
                             "test-only-speech")


class TestOnlyReview:
    async def review(self, context, candidate):
        return ReviewObservation(ReviewVerdict.ALLOW, "explicit_test_double")


@pytest.fixture
def spoken():
    with TestClient(create_app(Settings(), providers=Providers(
            SpeechGeneration(), TestOnlyReview()), speech_synthesis=Tts())) as client:
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        path = "/api/v1/sessions/" + created["session"]["session_id"]
        headers = {"X-Mira-Session-Token": created["session_token"]}
        assert client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": 1,
            "presentation_cutoff": 0, "text": "hello",
        }).status_code == 202
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = client.get(path, headers=headers).json()
            if state["sealed"]:
                break
            time.sleep(.005)
        assert state["sealed"] and len(state["active_grants"]) == 1
        yield client, path, headers, state["active_grants"][0]


def record(effect, sequence=1, samples=2400, status="rendered"):
    return {"effect_id": effect["id"], "digest": effect["digest"],
            "output_epoch": effect["output_epoch"], "activity_seq": effect["activity_seq"],
            "presentation_seq": sequence, "sample_rate_hz": 24000,
            "rendered_samples": samples, "status": status}


def test_legacy_dom_receipt_cannot_claim_speech_was_rendered(spoken):
    client, path, headers, effect = spoken
    body = {key: value for key, value in record(effect).items()
            if key not in {"sample_rate_hz", "rendered_samples", "status"}}
    response = client.post(path + "/receipts", headers=headers, json=body)
    assert response.status_code == 409
    assert response.json()["code"] == "audio_receipt_required"


def test_audio_progress_is_partial_until_explicit_completion(spoken):
    client, path, headers, effect = spoken
    response = client.post(path + "/audio-progress", headers=headers, json=record(effect))
    assert response.status_code == 200
    state = response.json()
    assert state["presented_effects"] == []
    assert state["audio_progress"][-1]["rendered_samples"] == 2400
    assert state["phase"] != "idle"
    complete = client.post(path + "/audio-progress", headers=headers,
                          json=record(effect, sequence=2, samples=4800, status="completed"))
    assert complete.status_code == 200
    assert complete.json()["phase"] == "idle"
    assert complete.json()["presented_effects"] == [effect]


def test_duplicate_audio_fact_is_idempotent(spoken):
    client, path, headers, effect = spoken
    body = record(effect)
    first = client.post(path + "/audio-progress", headers=headers, json=body)
    assert first.status_code == 200
    again = client.post(path + "/audio-progress", headers=headers, json=body)
    assert again.status_code == 200
    assert again.json() == first.json()


def test_old_pre_stop_audio_fact_only_adds_history(spoken):
    client, path, headers, effect = spoken
    assert client.post(path + "/stop", headers=headers,
                       json={"activity_seq": 2, "presentation_cutoff": 1}).status_code == 200
    late = client.post(path + "/audio-progress", headers=headers, json=record(effect))
    assert late.status_code == 200
    state = late.json()
    assert state["phase"] == "stopped" and state["active_grants"] == []
    assert state["presented_effects"] == []
    assert state["audio_progress"][-1]["rendered_samples"] == 2400
    after = client.post(path + "/audio-progress", headers=headers,
                        json=record(effect, sequence=2, samples=4800))
    assert after.status_code == 409
    assert after.json()["code"] == "after_stop_fence"


@pytest.mark.parametrize("patch", [
    {"digest": "b" * 64}, {"output_epoch": 2}, {"activity_seq": 2},
])
def test_audio_origin_mismatch_is_rejected(spoken, patch):
    client, path, headers, effect = spoken
    response = client.post(path + "/audio-progress", headers=headers,
                           json=record(effect) | patch)
    assert response.status_code == 409
    assert response.json()["code"] == "receipt_mismatch"


def test_audio_progress_cannot_move_backwards_or_reuse_sequence(spoken):
    client, path, headers, effect = spoken
    assert client.post(path + "/audio-progress", headers=headers,
                       json=record(effect)).status_code == 200
    backwards = client.post(path + "/audio-progress", headers=headers,
                             json=record(effect, sequence=2, samples=1200))
    assert backwards.status_code == 409
    reused = client.post(path + "/audio-progress", headers=headers,
                         json=record(effect, sequence=1, samples=4800))
    assert reused.status_code == 409


def test_terminal_audio_record_cannot_be_rewritten(spoken):
    client, path, headers, effect = spoken
    assert client.post(path + "/audio-progress", headers=headers,
                       json=record(effect, status="completed")).status_code == 200
    response = client.post(path + "/audio-progress", headers=headers,
                           json=record(effect, sequence=2, samples=4800, status="completed"))
    assert response.status_code == 409


def test_audio_cutoff_cannot_erase_acknowledged_progress(spoken):
    client, path, headers, effect = spoken
    assert client.post(path + "/audio-progress", headers=headers,
                       json=record(effect)).status_code == 200
    response = client.post(path + "/stop", headers=headers,
                           json={"activity_seq": 2, "presentation_cutoff": 0})
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_cutoff"


def test_new_generation_context_retains_only_explicit_partial_audio(spoken):
    client, path, headers, effect = spoken
    progress_response = client.post(path + "/audio-progress", headers=headers, json=record(effect))
    assert progress_response.status_code == 200
    actor = client.app.state.container.sessions.get(path.rsplit("/", 1)[1], headers["X-Mira-Session-Token"])
    observed = []
    original = actor._generation.generate
    async def capture(context):
        observed.append(context)
        async for candidate in original(context):
            yield candidate
    actor._generation.generate = capture
    assert client.post(path + "/inputs", headers=headers, json={
        "request_id": str(uuid4()), "activity_seq": 2, "presentation_cutoff": 1,
        "text": "Continue from what was actually rendered.",
    }).status_code == 202
    deadline = time.monotonic() + 2
    while not observed and time.monotonic() < deadline:
        time.sleep(.005)
    assert observed[0].presented_effects == ()
    assert observed[0].audio_progress[-1].rendered_samples == 2400
    assert observed[0].audio_progress[-1].status == "rendered"
