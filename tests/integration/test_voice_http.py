"""Browser-facing media paths with synthetic providers and no external calls."""
import asyncio
import base64
import json
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mira.application.contracts import CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict
from mira.application.ports.media import AudioPacket, TranscriptRevision
from mira.bootstrap.providers import Providers
from mira.config.settings import Settings
from mira.domain.models import EffectKind
from mira.entrypoints.http.app import create_app

ORIGIN = {"Origin": "http://localhost:8000"}


class GenerateSpeech:
    async def generate(self, context):
        yield CandidateRange((EffectProposal(EffectKind.SPEECH, "Approved speech only."),), "test")


class Review:
    async def review(self, context, candidate):
        return ReviewObservation(ReviewVerdict.ALLOW, "test")


class Tts:
    def __init__(self):
        self.calls = []
        self.closed = threading.Event()

    async def synthesize(self, approved_text, stream_id):
        self.calls.append((approved_text, stream_id))
        try:
            yield AudioPacket(stream_id, 0, 24000, b"\x01\x00" * 10000)
        finally:
            self.closed.set()


class Stt:
    def __init__(self):
        self.packets = []
        self.closed = threading.Event()

    async def transcribe(self, packets):
        try:
            async for packet in packets:
                self.packets.append(packet)
                yield TranscriptRevision(packet.stream_id, len(self.packets), "你好", True)
        finally:
            self.closed.set()


def app_with(tts=None, stt=None):
    # Optional explicit media injection must never select a provider by itself.
    return create_app(Settings(), providers=Providers(GenerateSpeech(), Review()),
                      speech_synthesis=tts, speech_recognition=stt)


def create(client, speak=False):
    created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
    path = "/api/v1/sessions/" + created["session"]["session_id"]
    headers = {"X-Mira-Session-Token": created["session_token"]}
    state = created["session"]
    if speak:
        client.post(path + "/inputs", headers=headers, json={"request_id": str(uuid4()),
                    "activity_seq": 1, "presentation_cutoff": 0, "text": "hello"})
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = client.get(path, headers=headers).json()
            if state["sealed"]:
                break
            time.sleep(.005)
        assert state["sealed"]
    return path, headers, state


def speech_request(client, path, headers, effect, **extra):
    return client.post(path + "/speech/" + effect["id"] + "/stream", headers=headers,
                       json={k: effect[k] for k in ("digest", "output_epoch", "activity_seq")} | extra)


def mic_start(headers, state):
    return {"type": "start", "session_token": headers["X-Mira-Session-Token"],
            "stream_id": str(uuid4()), "activity_seq": state["activity_seq"],
            "input_epoch": state["input_epoch"], "sample_rate_hz": 16000}


def audio(sequence=1, first_sample=0, pcm=b"\0\0" * 320):
    return {"type": "audio", "sequence": sequence, "first_sample": first_sample,
            "pcm_base64": base64.b64encode(pcm).decode()}


def test_speech_stream_is_origin_bound_bounded_and_approved():
    tts = Tts()
    with TestClient(app_with(tts=tts)) as client:
        path, headers, state = create(client, speak=True)
        effect = state["active_grants"][0]
        response = speech_request(client, path, headers, effect)
        assert response.status_code == 200
        frames = [json.loads(line) for line in response.text.splitlines()]
        assert [frame["type"] for frame in frames] == ["audio", "audio", "complete"]
        assert frames[-1]["total_samples"] == 10000
        for i, frame in enumerate(frames[:-1]):
            assert frame["effect_id"] == effect["id"] and frame["digest"] == effect["digest"]
            assert frame["sequence"] == i + 1 and frame["first_sample"] == i * 6000
            assert len(base64.b64decode(frame["pcm_base64"])) <= 12000
        assert tts.calls == [(effect["value"], effect["id"])] and tts.closed.is_set()
        assert speech_request(client, path, headers, effect).status_code == 409


def test_speech_missing_provider_fails_clearly_without_mock_audio():
    with TestClient(app_with()) as client:
        path, headers, state = create(client, speak=True)
        response = speech_request(client, path, headers, state["active_grants"][0])
        assert response.status_code == 503 and response.json()["code"] == "speech_unavailable"


def test_speech_rejects_arbitrary_text_mismatch_other_session_and_stale_grant():
    tts = Tts()
    with TestClient(app_with(tts=tts)) as client:
        path, headers, state = create(client, speak=True)
        effect = state["active_grants"][0]
        assert speech_request(client, path, headers, effect, text="Unreviewed").status_code == 422
        assert speech_request(client, path, headers, effect, digest="b" * 64).status_code == 409
        _, other, _ = create(client)
        assert speech_request(client, path, other, effect).status_code == 404
        client.post(path + "/stop", headers=headers, json={"activity_seq": 2, "presentation_cutoff": 0})
        assert speech_request(client, path, headers, effect).status_code == 409
        assert tts.calls == []


def test_microphone_transcript_requires_explicit_turn_submission():
    stt = Stt()
    with TestClient(app_with(stt=stt)) as client:
        path, headers, state = create(client)
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as ws:
            start = mic_start(headers, state)
            ws.send_json(start)
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(audio())
            revision = ws.receive_json()
            assert revision["type"] == "transcript" and revision["is_final"] is True
            assert revision["stream_id"] == start["stream_id"]
            ws.send_json({"type": "finish"})
            complete = ws.receive_json()
            assert complete["type"] == "complete" and complete["text"] == "你好"
            assert complete["had_final"] is True and complete["revision"] == 1
        after = client.get(path, headers=headers).json()
        assert after == state and stt.closed.is_set()


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
def test_microphone_requires_allowed_origin(origin):
    with TestClient(app_with(stt=Stt())) as client:
        path, _, _ = create(client)
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(path + "/microphone", headers={} if origin is None else {"Origin": origin}):
                pass
        assert error.value.code == 1008


def test_microphone_authentication_is_not_accepted_in_query():
    with TestClient(app_with(stt=Stt())) as client:
        path, headers, _ = create(client)
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(path + "/microphone?session_token=" + headers["X-Mira-Session-Token"], headers=ORIGIN):
                pass
        assert error.value.code == 1008


def test_microphone_bad_token_fails_before_provider_use():
    stt = Stt()
    with TestClient(app_with(stt=stt)) as client:
        path, headers, state = create(client)
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as ws:
            ws.send_json(mic_start(headers, state) | {"session_token": "wrong"})
            assert ws.receive_json()["code"] == "session_not_found"
        assert stt.packets == []


@pytest.mark.parametrize("patch", [{"sequence": 2}, {"first_sample": 1}, {"pcm_base64": "not base64"},
                                  {"pcm_base64": base64.b64encode(b"x").decode()}])
def test_microphone_invalid_chunk_closes_and_cancels_provider(patch):
    stt = Stt()
    with TestClient(app_with(stt=stt)) as client:
        path, headers, state = create(client)
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as ws:
            ws.send_json(mic_start(headers, state))
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(audio() | patch)
            assert ws.receive_json()["type"] == "error"
        assert stt.closed.wait(1)


def test_microphone_stop_closes_old_stream_without_new_authority():
    stt = Stt()
    with TestClient(app_with(stt=stt)) as client:
        path, headers, state = create(client)
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as ws:
            ws.send_json(mic_start(headers, state))
            assert ws.receive_json()["type"] == "ready"
            stopped = client.post(path + "/stop", headers=headers,
                                 json={"activity_seq": 1, "presentation_cutoff": 0}).json()
            assert ws.receive_json()["code"] == "media_cancelled"
        assert stt.closed.wait(1)
        assert client.get(path, headers=headers).json() == stopped


def test_voice_capabilities_are_explicit_and_injection_is_not_live_proof():
    with TestClient(app_with()) as client:
        disabled = client.get("/api/v1/voice-capabilities").json()
        assert disabled["speech_enabled"] is False and disabled["microphone_enabled"] is False
        assert disabled["qualification"] == "unavailable" and disabled["generation_mode"] == "injected"
    with TestClient(app_with(tts=Tts(), stt=Stt())) as client:
        enabled = client.get("/api/v1/voice-capabilities").json()
        assert enabled["speech_enabled"] and enabled["microphone_enabled"]
        assert enabled["qualification"] == "injected_unverified"
        assert client.get("/api/v1/health").json()["live_audio"] is None


@pytest.mark.parametrize("bad", [AudioPacket("wrong", 0, 24000, b"\0\0"),
                                  AudioPacket("match", 1, 24000, b"\0\0"),
                                  AudioPacket("match", 0, 16000, b"\0\0"),
                                  AudioPacket("match", 0, 24000, b"x")])
def test_bad_tts_packet_fails_without_emitting_audio(bad):
    class BadTts(Tts):
        async def synthesize(self, approved_text, stream_id):
            from dataclasses import replace
            yield replace(bad, stream_id=stream_id if bad.stream_id == "match" else bad.stream_id)
    with TestClient(app_with(tts=BadTts())) as client:
        path, headers, state = create(client, speak=True)
        response = speech_request(client, path, headers, state["active_grants"][0])
        frames = [json.loads(line) for line in response.text.splitlines()]
        assert len(frames) == 1 and frames[0]["type"] == "error"
        assert frames[0]["code"] == "invalid_audio"
        state = client.get(path, headers=headers).json()
        assert state["phase"] == "error" and state["active_grants"] == []


def test_stop_drops_cancellation_resistant_late_tts_without_blocking():
    from concurrent.futures import ThreadPoolExecutor
    class LateTts(Tts):
        def __init__(self):
            super().__init__()
            self.entered = threading.Event()
            self.cancelled = threading.Event()
            self.release = asyncio.Event()
        async def synthesize(self, approved_text, stream_id):
            try:
                self.entered.set()
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    self.cancelled.set()
                    await self.release.wait()
                yield AudioPacket(stream_id, 0, 24000, b"\0\0" * 100)
            finally:
                self.closed.set()
    tts = LateTts()
    with TestClient(app_with(tts=tts)) as client, ThreadPoolExecutor(max_workers=1) as pool:
        path, headers, state = create(client, speak=True)
        future = pool.submit(speech_request, client, path, headers, state["active_grants"][0])
        assert tts.entered.wait(1)
        stopped = client.post(path + "/stop", headers=headers,
                              json={"activity_seq": 2, "presentation_cutoff": 0})
        assert stopped.status_code == 200 and tts.cancelled.wait(1)
        client.portal.call(tts.release.set)
        frames = [json.loads(line) for line in future.result(2).text.splitlines()]
        assert [frame["type"] for frame in frames] == ["error"]
        assert frames[0]["code"] == "media_cancelled" and tts.closed.wait(1)
        assert client.get(path, headers=headers).json() == stopped.json()


def test_microphone_cancel_during_final_drain_cancels_provider():
    class DrainStt(Stt):
        def __init__(self):
            super().__init__()
            self.draining = threading.Event()
        async def transcribe(self, packets):
            try:
                async for packet in packets:
                    self.packets.append(packet)
                self.draining.set()
                await asyncio.Event().wait()
                if False:
                    yield
            finally:
                self.closed.set()
    stt = DrainStt()
    with TestClient(app_with(stt=stt)) as client:
        path, headers, state = create(client)
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as ws:
            ws.send_json(mic_start(headers, state))
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(audio())
            ws.send_json({"type": "finish"})
            assert stt.draining.wait(1)
            ws.send_json({"type": "cancel"})
            assert ws.receive_json()["code"] == "media_cancelled"
        assert stt.closed.wait(1)


def test_microphone_disconnect_during_final_drain_cancels_provider():
    class DrainStt(Stt):
        def __init__(self):
            super().__init__()
            self.draining = threading.Event()
        async def transcribe(self, packets):
            try:
                async for packet in packets:
                    self.packets.append(packet)
                self.draining.set()
                await asyncio.Event().wait()
                if False:
                    yield
            finally:
                self.closed.set()
    stt = DrainStt()
    with TestClient(app_with(stt=stt)) as client:
        path, headers, state = create(client)
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as ws:
            ws.send_json(mic_start(headers, state))
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(audio())
            ws.send_json({"type": "finish"})
            assert stt.draining.wait(1)
            ws.close()
        assert stt.closed.wait(1)


@pytest.mark.parametrize("kind", ["empty", "interim"])
def test_empty_or_interim_only_microphone_cannot_be_reliable_input(kind):
    class PartialStt(Stt):
        async def transcribe(self, packets):
            async for packet in packets:
                if kind == "interim":
                    yield TranscriptRevision(packet.stream_id, 1, "unfinished", False)
    with TestClient(app_with(stt=PartialStt())) as client:
        path, headers, state = create(client)
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as ws:
            ws.send_json(mic_start(headers, state))
            ws.receive_json()
            ws.send_json(audio())
            ws.send_json({"type": "finish"})
            frame = ws.receive_json()
            if kind == "interim":
                assert frame["type"] == "transcript"
                frame = ws.receive_json()
            assert frame["type"] == "complete" and frame["had_final"] is False and frame["text"] == ""
        assert client.get(path, headers=headers).json() == state


def test_stale_microphone_start_and_reused_stream_id_are_rejected():
    with TestClient(app_with(stt=Stt())) as client:
        path, headers, state = create(client)
        start = mic_start(headers, state)
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as ws:
            ws.send_json(start | {"activity_seq": 1})
            assert ws.receive_json()["code"] == "stale_activity"
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as ws:
            ws.send_json(start)
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "finish"})
            assert ws.receive_json()["type"] == "complete"
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as ws:
            ws.send_json(start)
            assert ws.receive_json()["code"] == "stream_consumed"


def test_microphone_missing_provider_is_explicit():
    with TestClient(app_with()) as client:
        path, headers, state = create(client)
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as ws:
            ws.send_json(mic_start(headers, state))
            assert ws.receive_json()["code"] == "microphone_unavailable"


def test_delete_session_cancels_microphone_and_removes_token_authority():
    stt = Stt()
    with TestClient(app_with(stt=stt)) as client:
        path, headers, state = create(client)
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as ws:
            ws.send_json(mic_start(headers, state))
            assert ws.receive_json()["type"] == "ready"
            assert client.delete(path, headers=headers).status_code == 204
            assert ws.receive_json()["code"] == "media_cancelled"
        assert stt.closed.wait(1) and client.get(path, headers=headers).status_code == 404


def test_google_voice_factory_requires_explicit_admission_before_client_construction():
    from mira.bootstrap import providers
    from mira.config.loader import ConfigurationError
    from mira.config.service_settings import SpeechSettings
    factory = getattr(providers, "create_google_voice", None)
    assert factory is not None, "Concrete voice composition is missing."
    with pytest.raises(ConfigurationError):
        factory(SpeechSettings(), credentials=object(), token_provider=lambda: None,
                authorized=False)


@pytest.mark.asyncio
async def test_google_voice_factory_wires_exact_adapters_and_closes_owned_clients(monkeypatch):
    from mira.bootstrap import providers
    from mira.config.service_settings import SpeechSettings
    factory = getattr(providers, "create_google_voice", None)
    assert factory is not None, "Concrete voice composition is missing."
    import google.cloud.speech_v2
    import httpx
    closed, seen = [], {}
    credential = object()
    class FakeTransport:
        async def close(self):
            closed.append("stt")
    class FakeSttClient:
        def __init__(self, **kwargs):
            seen["stt"] = kwargs
            self.transport = FakeTransport()
    class FakeHttpClient:
        def __init__(self, **kwargs):
            seen["http"] = kwargs
        async def aclose(self):
            closed.append("http")
    async def token_provider():
        raise AssertionError("Offline composition must not request a token.")
    monkeypatch.setattr(google.cloud.speech_v2, "SpeechAsyncClient", FakeSttClient)
    monkeypatch.setattr(httpx, "AsyncClient", FakeHttpClient)
    voice = factory(SpeechSettings(project_id="test-project", quota_project_id="test-quota",
                                  tts_voice="Kore"), credentials=credential,
                    token_provider=token_provider, authorized=True)
    assert voice.speech_synthesis.options.model == "gemini-3.8-flash-tts"
    assert voice.speech_recognition.options.model == "chirp_3"
    assert seen["stt"]["credentials"] is credential
    assert seen["stt"]["client_options"].api_endpoint == "us-speech.googleapis.com"
    assert seen["http"]["trust_env"] is False and seen["http"]["follow_redirects"] is False
    await voice.close()
    await voice.close()
    assert sorted(closed) == ["http", "stt"]


def test_late_generation_failure_cannot_cancel_new_microphone():
    class LateGeneration:
        def __init__(self):
            self.entered = threading.Event()
            self.cancelled = threading.Event()
            self.release = asyncio.Event()
            self.failed = threading.Event()
        async def generate(self, context):
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                await self.release.wait()
            self.failed.set()
            raise RuntimeError("late old generation")
            if False:
                yield
    generation, stt = LateGeneration(), Stt()
    app = create_app(Settings(), providers=Providers(generation, Review()), speech_recognition=stt)
    with TestClient(app) as client:
        path, headers, state = create(client)
        assert client.post(path + "/inputs", headers=headers, json={"request_id": str(uuid4()),
                    "activity_seq": 1, "presentation_cutoff": 0, "text": "hello"}).status_code == 202
        assert generation.entered.wait(1)
        stopped = client.post(path + "/stop", headers=headers,
                              json={"activity_seq": 2, "presentation_cutoff": 0}).json()
        assert generation.cancelled.wait(1)
        with client.websocket_connect(path + "/microphone", headers=ORIGIN) as ws:
            ws.send_json(mic_start(headers, stopped))
            assert ws.receive_json()["type"] == "ready"
            client.portal.call(generation.release.set)
            assert generation.failed.wait(1)
            ws.send_json(audio())
            assert ws.receive_json()["type"] == "transcript"
            ws.send_json({"type": "finish"})
            assert ws.receive_json()["type"] == "complete"


@pytest.mark.asyncio
async def test_google_voice_factory_allows_optional_quota_and_caller_owned_http_client(monkeypatch):
    from mira.bootstrap.providers import create_google_voice
    from mira.config.service_settings import SpeechSettings
    import google.cloud.speech_v2
    import httpx
    closed = []
    class FakeTransport:
        async def close(self):
            closed.append("stt")
    class FakeSttClient:
        def __init__(self, **kwargs):
            self.transport = FakeTransport()
    class ApprovedHttpClient:
        async def aclose(self):
            raise AssertionError("Injected HTTP client belongs to the caller.")
    def no_default_client(**kwargs):
        raise AssertionError("Do not substitute a default client for the explicit approved route.")
    async def token_provider():
        raise AssertionError("Offline test must not request tokens.")
    monkeypatch.setattr(google.cloud.speech_v2, "SpeechAsyncClient", FakeSttClient)
    monkeypatch.setattr(httpx, "AsyncClient", no_default_client)
    voice = create_google_voice(SpeechSettings(project_id="test-project", tts_voice="Kore"),
        credentials=object(), token_provider=token_provider, authorized=True,
        http_client=ApprovedHttpClient())
    assert voice.speech_synthesis.transport._quota_project_id is None
    await voice.close()
    assert closed == ["stt"]


def test_cli_websocket_ingress_is_bounded_without_access_logging(monkeypatch, tmp_path):
    from mira import __main__ as cli
    captured = {}
    monkeypatch.setattr(cli, "project_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda **kwargs: Settings())
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: captured.update(kwargs))
    cli.main()
    assert captured["ws_max_size"] == 32768 and captured["ws_max_queue"] == 8
    assert captured["access_log"] is False


@pytest.mark.asyncio
async def test_microphone_buffer_duration_pacing_and_capacity_are_bounded():
    from mira.application.media_runtime import MicrophoneBuffer
    from mira.domain.errors import DomainError
    buffer = MicrophoneBuffer("s")
    for i in range(8):
        buffer.push(sequence=i + 1, first_sample=i * 320, pcm=b"\0\0" * 320)
    with pytest.raises(DomainError, match="full"):
        buffer.push(sequence=9, first_sample=2560, pcm=b"\0\0" * 320)
    # Finish must not block receive/disconnect even with all eight credits held.
    async with asyncio.timeout(.1):
        await buffer.finish()
    assert len([packet async for packet in buffer.packets()]) == 8
    fast = MicrophoneBuffer("fast")
    fast.push(sequence=1, first_sample=0, pcm=b"\0\0" * 6000)
    fast.push(sequence=2, first_sample=6000, pcm=b"\0\0" * 6000)
    with pytest.raises(DomainError, match="pacing"):
        fast.push(sequence=3, first_sample=12000, pcm=b"\0\0" * 6000)
    elapsed = MicrophoneBuffer("elapsed")
    elapsed._started -= 61
    elapsed._samples = 16000 * 60
    with pytest.raises(DomainError, match="duration"):
        elapsed.push(sequence=1, first_sample=16000 * 60, pcm=b"\0\0")


@pytest.mark.asyncio
async def test_speech_http_response_disconnect_closes_provider_and_releases_operation():
    from uuid import UUID
    from mira.bootstrap.container import build_container
    from mira.entrypoints.http.media_routes import speech_stream
    from mira.entrypoints.http.schemas import SpeechStreamRequest
    class WaitingTts(Tts):
        async def synthesize(self, approved_text, stream_id):
            try:
                yield AudioPacket(stream_id, 0, 24000, b"\0\0" * 100)
                await asyncio.Event().wait()
            finally:
                self.closed.set()
    tts = WaitingTts()
    container = build_container(Settings(), providers=Providers(GenerateSpeech(), Review()),
                                speech_synthesis=tts)
    actor, token = container.sessions.create(str(uuid4()))
    try:
        await actor.submit(request_id=str(uuid4()), activity_seq=1, cutoff=0, text="hello")
        async with asyncio.timeout(1):
            while not (state := await actor.snapshot()).sealed:
                await asyncio.sleep(0)
        effect = state.active_grants[0]
        response = await speech_stream(UUID(state.session_id), UUID(effect.id),
            SpeechStreamRequest(digest=effect.digest, output_epoch=1, activity_seq=1), token, container)
        disconnected = asyncio.Event()
        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                disconnected.set()
        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}
        async with asyncio.timeout(1):
            await response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send)
        async with asyncio.timeout(1):
            while not tts.closed.is_set() or actor._media_operations:
                await asyncio.sleep(0)
    finally:
        await container.close()


def test_shutdown_closes_explicit_media_lifecycle_once():
    calls = []
    async def shutdown():
        calls.append("closed")
    with TestClient(create_app(Settings(), media_shutdown=shutdown)) as client:
        assert client.get("/api/v1/health").status_code == 200
    assert calls == ["closed"]


@pytest.mark.parametrize("status", ["completed", "interrupted", "failed"])
def test_terminal_audio_fact_independently_cancels_server_synthesis(status):
    from concurrent.futures import ThreadPoolExecutor
    class WaitingTts(Tts):
        def __init__(self):
            super().__init__()
            self.blocked = threading.Event()
        async def synthesize(self, approved_text, stream_id):
            try:
                yield AudioPacket(stream_id, 0, 24000, b"\0\0" * 100)
                self.blocked.set()
                await asyncio.Event().wait()
            finally:
                self.closed.set()
    tts = WaitingTts()
    with TestClient(app_with(tts=tts)) as client, ThreadPoolExecutor(max_workers=1) as pool:
        path, headers, state = create(client, speak=True)
        effect = state["active_grants"][0]
        future = pool.submit(speech_request, client, path, headers, effect)
        assert tts.blocked.wait(1)
        response = client.post(path + "/audio-progress", headers=headers, json={
            "effect_id": effect["id"], "digest": effect["digest"], "output_epoch": effect["output_epoch"],
            "activity_seq": effect["activity_seq"], "presentation_seq": 1, "sample_rate_hz": 24000,
            "rendered_samples": 100, "status": status,
        })
        try:
            assert response.status_code == 200
            assert tts.closed.wait(.3), "Terminal software audio must revoke provider work independently."
            if status != "completed":
                assert response.json()["phase"] == "error" and response.json()["active_grants"] == []
            frames = [json.loads(line) for line in future.result(1).text.splitlines()]
            assert frames[-1]["type"] == "error" and frames[-1]["code"] == "media_cancelled"
        finally:
            # Bound negative-run cleanup without depending on executor shutdown.
            client.post(path + "/stop", headers=headers,
                        json={"activity_seq": 2, "presentation_cutoff": 1})
            future.result(2)


def test_voice_factory_constructs_on_application_loop_and_closes_once():
    from mira.bootstrap.providers import GoogleVoiceProviders
    observed = []
    async def shutdown():
        observed.append("closed")
    def factory():
        observed.append(asyncio.get_running_loop())
        return GoogleVoiceProviders(Stt(), Tts(), shutdown)
    with TestClient(create_app(Settings(), voice_factory=factory)) as client:
        assert client.get("/api/v1/voice-capabilities").json()["speech_enabled"] is True
        async def loop():
            return asyncio.get_running_loop()
        assert client.portal.call(loop) is observed[0]
    assert observed[1:] == ["closed"]


def test_voice_factory_cannot_silently_replace_other_media_injections():
    from mira.config.loader import ConfigurationError
    with pytest.raises(ConfigurationError):
        create_app(Settings(), voice_factory=lambda: None, speech_synthesis=Tts())


def test_google_voice_construction_without_running_loop_fails_before_sdk_resources():
    from mira.bootstrap.providers import create_google_voice
    from mira.config.loader import ConfigurationError
    from mira.config.service_settings import SpeechSettings
    with pytest.raises(ConfigurationError, match="lifespan"):
        create_google_voice(SpeechSettings(project_id="test-project", tts_voice="Kore"),
                            credentials=object(), token_provider=lambda: None, authorized=True)
