"""Authenticated HTTP and real streaming lifecycle contracts for reviewed PCM capture.

Only synthetic PCM and fake injected providers are used; no microphone or live provider is touched.
"""
import asyncio
import base64
import hashlib
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.application.diagnostic_events import DiagnosticStatus
from mira.application.ports.media import AudioPacket, TranscriptRevision
from mira.bootstrap.providers import Providers
from mira.config.settings import Settings
from mira.domain.models import EffectKind
from mira.application.contracts import CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict
from mira.adapters.diagnostics.audio_review import AudioCaptureLimits
from mira.entrypoints.http.app import create_app

ORIGIN = {"Origin": "http://localhost:8000"}
PCM = b"\x10\x00\x20\x00\x30\x00\x40\x00"


class Sink:
    def __init__(self, *, capture_result=True):
        self.recording = False
        self.capture_result = capture_result
        self.records = []
        self.events = []

    def set_recording(self, enabled, *, consent=False):
        if enabled and consent is not True:
            return False
        self.recording = enabled
        return True

    def status(self):
        return DiagnosticStatus(available=True, recording_active=self.recording)

    def capture(self, record):
        if self.capture_result:
            self.records.append(record)
        return self.capture_result

    def capture_text(self, *args, **kwargs):
        return False

    def emit(self, event):
        self.events.append(event)
        return True

    def add_secret(self, value):
        return True

    def close(self):
        self.recording = False


class Stt:
    async def transcribe(self, packets):
        stream_id = None
        revision = 0
        async for packet in packets:
            stream_id = packet.stream_id
            revision += 1
        if stream_id is not None:
            yield TranscriptRevision(stream_id, revision, "测试文本", True)


class NonfinalStt:
    async def transcribe(self, packets):
        async for packet in packets:
            yield TranscriptRevision(packet.stream_id, 1, "部分文本", False)


class GenerateSpeech:
    async def generate(self, context):
        yield CandidateRange((EffectProposal(EffectKind.SPEECH, "测试语音"),), "synthetic")


class Review:
    async def review(self, context, candidate):
        return ReviewObservation(ReviewVerdict.ALLOW, "synthetic")


class Tts:
    async def synthesize(self, approved_text, stream_id):
        yield AudioPacket(stream_id, 0, 24000, PCM)


def app_with(sink=None, *, stt=None, tts=None):
    return create_app(Settings(), providers=Providers(GenerateSpeech(), Review()),
                      speech_recognition=stt, speech_synthesis=tts,
                      diagnostics=sink or Sink())


def create(client):
    created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
    path = "/api/v1/sessions/" + created["session"]["session_id"]
    return path, {"X-Mira-Session-Token": created["session_token"]}, created["session"]


def recording(client, path, headers, enabled):
    return client.post(path + "/reviewed-audio/recording", headers=headers,
                       json={"enabled": enabled, "consent": enabled})


def send_microphone(client, path, headers, state, *, audio=PCM, finish=True):
    stream_id = str(uuid4())
    with client.websocket_connect(path + "/microphone", headers=ORIGIN) as socket:
        socket.send_json({"type": "start", "session_token": headers["X-Mira-Session-Token"],
            "stream_id": stream_id, "activity_seq": state["activity_seq"],
            "input_epoch": state["input_epoch"], "sample_rate_hz": 16000})
        assert socket.receive_json()["type"] == "ready"
        socket.send_json({"type": "audio", "sequence": 1, "first_sample": 0,
                          "pcm_base64": base64.b64encode(audio).decode("ascii")})
        if finish:
            socket.send_json({"type": "finish"})
            messages = []
            while True:
                item = socket.receive_json()
                messages.append(item)
                if item["type"] in ("complete", "error"):
                    break
            assert messages[-1]["type"] == "complete"
    return stream_id


def review(client, path, headers, stream_id):
    return client.post(path + f"/reviewed-audio/streams/{stream_id}/review", headers=headers)


def test_recording_status_and_mode_are_private_session_authenticated_and_app_wide():
    with TestClient(app_with()) as client:
        path, headers, _ = create(client)
        status = client.get(path + "/reviewed-audio", headers=headers)
        assert status.status_code == 200
        assert status.json()["scope"] == "application"
        assert not status.json()["recording_active"]
        assert "所有已认证会话" in status.json()["scope_notice"]

        assert client.get(path + "/reviewed-audio").status_code == 422
        assert client.post(path + "/reviewed-audio/recording", json={
            "enabled": True, "consent": True}).status_code == 422

        refused = client.post(path + "/reviewed-audio/recording", headers=headers,
                              json={"enabled": True, "consent": False})
        assert refused.status_code == 409 and not refused.json()["recording_active"]

        enabled = recording(client, path, headers, True)
        assert enabled.status_code == 200 and enabled.json()["recording_active"]
        assert enabled.json()["scope"] == "application"
        assert "所有已认证会话" in enabled.json()["scope_notice"]
        assert recording(client, path, headers, False).json()["recording_active"] is False


def test_microphone_exact_buffer_preview_and_confirmation_are_owner_bound():
    sink = Sink()
    with TestClient(app_with(sink, stt=Stt())) as client:
        path_a, headers_a, state_a = create(client)
        path_b, headers_b, _ = create(client)
        assert recording(client, path_a, headers_a, True).status_code == 200
        stream_id = send_microphone(client, path_a, headers_a, state_a)

        pending = client.get(path_a + "/reviewed-audio", headers=headers_a).json()
        assert pending["has_pending_audio"] is True
        assert pending["staged_bytes"] == len(PCM)
        assert pending["pending_stream_id"] == stream_id
        assert pending["pending_kind"] == "audio_input" and pending["input_completion_ready"]

        reviewed = review(client, path_a, headers_a, stream_id)
        assert reviewed.status_code == 200
        ticket = reviewed.json()
        assert ticket["digest"] == hashlib.sha256(PCM).hexdigest()
        assert ticket["sample_rate_hz"] == 16000 and ticket["byte_count"] == len(PCM)
        foreign_status = client.get(path_b + "/reviewed-audio", headers=headers_b).json()
        assert not foreign_status["has_pending_audio"] and foreign_status["staged_bytes"] == 0
        assert foreign_status["pending_stream_id"] is None and foreign_status["pending_kind"] is None
        assert not foreign_status["input_completion_ready"]

        other = client.get(path_b + f"/reviewed-audio/reviews/{ticket['review_id']}/preview",
                           headers=headers_b)
        wrong_token = client.get(path_a + f"/reviewed-audio/reviews/{ticket['review_id']}/preview",
                                 headers=headers_b)
        assert other.status_code == 404 and wrong_token.status_code == 404
        assert PCM not in other.content and ticket["digest"] not in other.text
        foreign_confirm = client.post(path_b + f"/reviewed-audio/reviews/{ticket['review_id']}/confirm",
            headers=headers_b, json={"reviewed_digest": ticket["digest"], "review": "approved",
                                     "persist_consent": True})
        assert foreign_confirm.status_code == 404 and sink.records == []

        same_input = client.post(path_a + "/inputs", headers=headers_a, json={
            "request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0,
            "text": "测试文本", "source_audio_stream_id": stream_id})
        assert same_input.status_code == 202
        same_status = client.get(path_a + "/reviewed-audio", headers=headers_a).json()
        assert same_status["has_pending_audio"] and same_status["pending_stream_id"] == stream_id
        assert same_status["pending_kind"] == "audio_input" and same_status["input_completion_ready"]

        preview = client.get(path_a + f"/reviewed-audio/reviews/{ticket['review_id']}/preview",
                             headers=headers_a)
        assert preview.status_code == 200 and preview.content == PCM
        assert preview.headers["Cache-Control"] == "no-store"
        assert preview.headers["X-Mira-Audio-Format"] == "pcm16le-mono"
        assert sink.records == []

        mismatch = client.post(path_a + f"/reviewed-audio/reviews/{ticket['review_id']}/confirm",
            headers=headers_a, json={"reviewed_digest": "0" * 64, "review": "approved",
                                      "persist_consent": True})
        assert mismatch.status_code == 409 and mismatch.json()["code"] == "digest_mismatch"
        assert sink.records == []
        late = client.post(path_a + f"/reviewed-audio/reviews/{ticket['review_id']}/confirm",
            headers=headers_a, json={"reviewed_digest": ticket["digest"], "review": "approved",
                                      "persist_consent": True})
        assert late.status_code == 404 and sink.records == []


def test_only_explicit_approval_and_private_save_consent_queue_audio():
    sink = Sink()
    with TestClient(app_with(sink, stt=Stt())) as client:
        path, headers, state = create(client)
        assert recording(client, path, headers, True).status_code == 200
        stream_id = send_microphone(client, path, headers, state)
        ticket = review(client, path, headers, stream_id).json()
        rejected = client.post(path + f"/reviewed-audio/reviews/{ticket['review_id']}/confirm",
            headers=headers, json={"reviewed_digest": ticket["digest"], "review": "rejected",
                                   "persist_consent": True})
        assert rejected.status_code == 409 and rejected.json()["code"] == "review_not_approved"
        assert sink.records == []

        stream_id = send_microphone(client, path, headers, state)
        ticket = review(client, path, headers, stream_id).json()
        no_consent = client.post(path + f"/reviewed-audio/reviews/{ticket['review_id']}/confirm",
            headers=headers, json={"reviewed_digest": ticket["digest"], "review": "approved",
                                   "persist_consent": False})
        assert no_consent.status_code == 409 and no_consent.json()["code"] == "persist_consent_required"
        assert sink.records == []

        stream_id = send_microphone(client, path, headers, state)
        ticket = review(client, path, headers, stream_id).json()
        saved = client.post(path + f"/reviewed-audio/reviews/{ticket['review_id']}/confirm",
            headers=headers, json={"reviewed_digest": ticket["digest"], "review": "approved",
                                   "persist_consent": True})
        assert saved.status_code == 200 and saved.json()["code"] == "queued_private_local"
        assert saved.json()["accepted_for_queue"] is True
        assert sink.records[0].kind.value == "audio_input" and sink.records[0].audio == PCM
        assert sink.records[0].context.turn_id is None and sink.records[0].context.effect_id is None
        assert all(not hasattr(event, "audio") for event in sink.events)
        assert not hasattr(sink, "export")
        assert client.post(path + "/reviewed-audio/export", headers=headers,
                           json={"include_raw": True}).status_code == 404


def test_mode_off_stop_new_input_disconnect_quota_and_expiry_clear_staged_pcm():
    sink = Sink()
    with TestClient(app_with(sink, stt=Stt())) as client:
        path, headers, state = create(client)
        stream_id = send_microphone(client, path, headers, state)
        assert review(client, path, headers, stream_id).status_code == 404  # off by default

        assert recording(client, path, headers, True).status_code == 200
        stream_id = send_microphone(client, path, headers, state)
        capture = client.app.state.container.reviewed_audio
        capture.limits = AudioCaptureLimits(max_audio_bytes=4)
        quota_stream = send_microphone(client, path, headers, state, audio=PCM)
        assert quota_stream != stream_id
        assert client.get(path + "/reviewed-audio", headers=headers).json()["has_pending_audio"] is False

        capture.limits = AudioCaptureLimits()
        stream_id = send_microphone(client, path, headers, state)
        ticket = review(client, path, headers, stream_id).json()
        off = recording(client, path, headers, False)
        assert off.status_code == 200
        assert client.get(path + f"/reviewed-audio/reviews/{ticket['review_id']}/preview",
                          headers=headers).status_code == 404
        assert sink.records == []

        assert recording(client, path, headers, True).status_code == 200
        stream_id = send_microphone(client, path, headers, state)
        stopped = client.post(path + "/stop", headers=headers,
                              json={"activity_seq": 1, "presentation_cutoff": 0})
        assert stopped.status_code == 200
        assert review(client, path, headers, stream_id).status_code == 404

        fresh = client.get(path, headers=headers).json()
        assert recording(client, path, headers, True).status_code == 200
        stream_id = send_microphone(client, path, headers, fresh)
        client.post(path + "/inputs", headers=headers, json={"request_id": str(uuid4()),
            "activity_seq": fresh["activity_seq"] + 1, "presentation_cutoff": 0, "text": "新输入"})
        assert review(client, path, headers, stream_id).status_code == 404

        capture.limits = AudioCaptureLimits(ttl_seconds=1)
        current = client.get(path, headers=headers).json()
        # The accepted input above advances the epochs; the new mic still uses the real current origin.
        stream_id = send_microphone(client, path, headers, current)
        assert client.get(path + "/reviewed-audio", headers=headers).json()["has_pending_audio"]
        ticket = review(client, path, headers, stream_id).json()
        time.sleep(1.2)
        assert client.get(path + "/reviewed-audio", headers=headers).json()["has_pending_audio"] is False
        late = client.post(path + f"/reviewed-audio/reviews/{ticket['review_id']}/confirm",
            headers=headers, json={"reviewed_digest": ticket["digest"], "review": "approved",
                                   "persist_consent": True})
        assert late.status_code == 404
        assert sink.records == []


def test_abnormal_microphone_disconnect_invalidates_audio_review_stage():
    with TestClient(app_with(stt=Stt())) as client:
        path, headers, state = create(client)
        assert recording(client, path, headers, True).status_code == 200
        stream_id = str(uuid4())
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as socket:
            socket.send_json({"type": "start", "session_token": headers["X-Mira-Session-Token"],
                "stream_id": stream_id, "activity_seq": state["activity_seq"],
                "input_epoch": state["input_epoch"], "sample_rate_hz": 16000})
            assert socket.receive_json()["type"] == "ready"
            socket.send_json({"type": "audio", "sequence": 1, "first_sample": 0,
                              "pcm_base64": base64.b64encode(PCM).decode("ascii")})
            socket.close()
        status = client.get(path + "/reviewed-audio", headers=headers).json()
        assert status["has_pending_audio"] is False and status["staged_bytes"] == 0
        assert review(client, path, headers, stream_id).status_code == 404


def test_transcript_link_is_server_completed_session_scoped_and_one_use():
    with TestClient(app_with(stt=Stt())) as client:
        path_a, headers_a, _ = create(client)
        path_b, headers_b, _ = create(client)
        assert recording(client, path_a, headers_a, True).status_code == 200

        state_a = client.get(path_a, headers=headers_a).json()
        stream_a = send_microphone(client, path_a, headers_a, state_a)
        status_a = client.get(path_a + "/reviewed-audio", headers=headers_a).json()
        assert status_a["input_completion_ready"] and status_a["pending_stream_id"] == stream_a

        # A different session cannot claim A's completion; its input does not clear A's stage.
        foreign = client.post(path_b + "/inputs", headers=headers_b, json={
            "request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0,
            "text": "测试文本", "source_audio_stream_id": stream_a})
        assert foreign.status_code == 202
        assert client.get(path_a + "/reviewed-audio", headers=headers_a).json()["has_pending_audio"]
        assert not client.get(path_b + "/reviewed-audio", headers=headers_b).json()["has_pending_audio"]

        # The actual stream ID is not enough when forged to another input.
        forged = client.post(path_a + "/inputs", headers=headers_a, json={
            "request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0,
            "text": "测试文本", "source_audio_stream_id": str(uuid4())})
        assert forged.status_code == 202
        assert not client.get(path_a + "/reviewed-audio", headers=headers_a).json()["has_pending_audio"]

        # A fresh exact server-final pairing can preserve once, but another request cannot reuse it.
        state_a = client.get(path_a, headers=headers_a).json()
        stream_a = send_microphone(client, path_a, headers_a, state_a)
        first_request = str(uuid4())
        valid = client.post(path_a + "/inputs", headers=headers_a, json={
            "request_id": first_request, "activity_seq": state_a["activity_seq"] + 1,
            "presentation_cutoff": 0, "text": "测试文本", "source_audio_stream_id": stream_a})
        assert valid.status_code == 202
        assert client.get(path_a + "/reviewed-audio", headers=headers_a).json()["has_pending_audio"]

        reused = client.post(path_a + "/inputs", headers=headers_a, json={
            "request_id": str(uuid4()), "activity_seq": state_a["activity_seq"] + 2,
            "presentation_cutoff": 0, "text": "测试文本", "source_audio_stream_id": stream_a})
        assert reused.status_code == 202
        assert not client.get(path_a + "/reviewed-audio", headers=headers_a).json()["has_pending_audio"]

        # Equal text alone does not preserve a fresh stream when its source ID is omitted.
        state_a = client.get(path_a, headers=headers_a).json()
        stream_a = send_microphone(client, path_a, headers_a, state_a)
        same_words = client.post(path_a + "/inputs", headers=headers_a, json={
            "request_id": str(uuid4()), "activity_seq": state_a["activity_seq"] + 1,
            "presentation_cutoff": 0, "text": "测试文本"})
        assert same_words.status_code == 202
        assert not client.get(path_a + "/reviewed-audio", headers=headers_a).json()["has_pending_audio"]

        # A stale completed stream ID cannot preserve an unrelated newer capture.
        state_a = client.get(path_a, headers=headers_a).json()
        unrelated_stream = send_microphone(client, path_a, headers_a, state_a)
        assert client.get(path_a + "/reviewed-audio", headers=headers_a).json()["pending_stream_id"] == unrelated_stream
        stale = client.post(path_a + "/inputs", headers=headers_a, json={
            "request_id": str(uuid4()), "activity_seq": state_a["activity_seq"] + 1,
            "presentation_cutoff": 0, "text": "测试文本", "source_audio_stream_id": stream_a})
        assert stale.status_code == 202
        assert not client.get(path_a + "/reviewed-audio", headers=headers_a).json()["has_pending_audio"]


def test_nonfinal_asr_cannot_bind_a_preservation_association():
    with TestClient(app_with(stt=NonfinalStt())) as client:
        path, headers, state = create(client)
        assert recording(client, path, headers, True).status_code == 200
        stream_id = send_microphone(client, path, headers, state)
        status = client.get(path + "/reviewed-audio", headers=headers).json()
        assert status["has_pending_audio"] and status["pending_stream_id"] == stream_id
        assert status["input_completion_ready"] is False
        committed = client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": state["activity_seq"] + 1,
            "presentation_cutoff": 0, "text": "部分文本", "source_audio_stream_id": stream_id})
        assert committed.status_code == 202
        assert not client.get(path + "/reviewed-audio", headers=headers).json()["has_pending_audio"]


def test_diagnostics_sink_refusal_is_not_reported_as_written_audio():
    sink = Sink(capture_result=False)
    with TestClient(app_with(sink, stt=Stt())) as client:
        path, headers, state = create(client)
        assert recording(client, path, headers, True).status_code == 200
        stream_id = send_microphone(client, path, headers, state)
        ticket = review(client, path, headers, stream_id).json()
        result = client.post(path + f"/reviewed-audio/reviews/{ticket['review_id']}/confirm",
            headers=headers, json={"reviewed_digest": ticket["digest"], "review": "approved",
                                   "persist_consent": True})
        assert result.status_code == 409 and result.json()["code"] == "local_queue_rejected"
        assert not result.json()["accepted_for_queue"] and sink.records == []


def test_session_delete_and_application_close_revoke_pending_buffers():
    sink = Sink()
    app = app_with(sink, stt=Stt())
    with TestClient(app) as client:
        path, headers, state = create(client)
        assert recording(client, path, headers, True).status_code == 200
        stream_id = send_microphone(client, path, headers, state)
        capture = client.app.state.container.reviewed_audio
        assert capture.status_for_session(path.rsplit("/", 1)[-1]).has_pending_audio
        assert client.delete(path, headers=headers).status_code == 204
        assert not capture.status().has_pending_audio
        assert sink.records == []

        path2, headers2, state2 = create(client)
        assert recording(client, path2, headers2, True).status_code == 200
        send_microphone(client, path2, headers2, state2)
        capture = client.app.state.container.reviewed_audio
        assert capture.status().has_pending_audio
    assert not capture.status().has_pending_audio
    assert not capture.status().recording_active and not sink.recording


def test_output_pcm_uses_validated_effect_identity_and_audio_output_kind():
    sink = Sink()
    with TestClient(app_with(sink, tts=Tts())) as client:
        path, headers, _ = create(client)
        assert recording(client, path, headers, True).status_code == 200
        client.post(path + "/inputs", headers=headers, json={"request_id": str(uuid4()),
            "activity_seq": 1, "presentation_cutoff": 0, "text": "请说话"})
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = client.get(path, headers=headers).json()
            if state["active_grants"]:
                break
            time.sleep(.005)
        effect = next(item for item in state["active_grants"] if item["kind"] == "speech")
        response = client.post(path + f"/speech/{effect['id']}/stream", headers=headers,
            json={k: effect[k] for k in ("digest", "output_epoch", "activity_seq")})
        assert response.status_code == 200
        assert client.get(path + "/reviewed-audio", headers=headers).json()["has_pending_audio"]
        ticket = review(client, path, headers, effect["id"]).json()
        assert ticket["sample_rate_hz"] == 24000 and ticket["byte_count"] == len(PCM)
        saved = client.post(path + f"/reviewed-audio/reviews/{ticket['review_id']}/confirm",
            headers=headers, json={"reviewed_digest": ticket["digest"], "review": "approved",
                                   "persist_consent": True})
        assert saved.status_code == 200 and sink.records[0].kind.value == "audio_output"
        assert sink.records[0].context.turn_id == str(effect["output_epoch"])
        assert sink.records[0].context.effect_id == effect["id"]
