"""Local ASGI/WebSocket checks for explicit manual continuous-listening commits.

Only synthetic PCM, synthetic VAD/final events, local generation/review and fake
providers are used. No browser, microphone, Google, Codex or JEV request is made.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.application.ports.continuous_speech import (
    ContinuousSpeechActivity, ContinuousTranscriptResult,
)
from mira.application.continuous_listening import ListeningLimits
from mira.bootstrap.providers import Providers
from mira.config.settings import Settings
from mira.entrypoints.http.app import create_app
from mira.application.contracts import CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict
from mira.domain.models import EffectKind


class _Generate:
    async def generate(self, _context):
        yield CandidateRange((EffectProposal(EffectKind.SPEECH, "fixture response"),), "test")


class _Review:
    async def review(self, _context, _candidate):
        return ReviewObservation(ReviewVerdict.ALLOW, "synthetic allow")


class _SyntheticContinuous:
    endpoint_mode = "google_vad_offsets"
    max_stream_seconds = 2

    def __init__(self):
        self.dispatches = 0
        self.closed = 0
        self.audio = []
        self.emit_transcript = True

    async def transcribe_events(self, packets):
        try:
            # A fake provider dispatches only after the first chunk, as the real adapter does.
            packet = await anext(packets)
            self.dispatches += 1
            self.audio.append(packet)
            if self.emit_transcript:
                yield ContinuousSpeechActivity("begin", 0)
                yield ContinuousTranscriptResult("你好，", False, None)
                yield ContinuousTranscriptResult("你好，", True, 20)
                yield ContinuousSpeechActivity("end", 40)
            async for rest in packets:
                self.audio.append(rest)
        finally:
            self.closed += 1


def _app(asr, *, limits=None):
    settings = Settings().model_copy(update={
        "environment": "test",
        "http": Settings().http.model_copy(update={"allowed_origins": ("http://testserver",)}),
    })
    return create_app(settings, providers=Providers(_Generate(), _Review()),
        continuous_speech_recognition=asr,
        listening_limits=limits or ListeningLimits(max_seconds=2, max_samples=32_000,
            max_streams_per_session=3, max_total_streams=8))


def _new_session(client):
    response = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())})
    assert response.status_code == 201
    body = response.json()
    return body["session"]["session_id"], body["session_token"], body["session"]


def _start(ws, session_token, lease_id=None, expected_max_seconds=2):
    lease_id = lease_id or str(uuid4())
    ws.send_json({"type": "start", "session_token": session_token, "lease_id": lease_id})
    ready = ws.receive_json()
    assert ready["type"] == "ready"
    assert ready["lease_id"] == lease_id
    assert ready["manual_commit_required"] is True
    assert ready["sample_rate_hz"] == 16000
    assert ready["max_seconds"] == expected_max_seconds
    return lease_id, ready


def _audio(ws, lease_id, *, seq=1, first=0, pcm=b"\0\0" * 80):
    ws.send_json({"type": "audio", "lease_id": lease_id, "sequence": seq,
                  "first_sample": first, "pcm_base64": base64.b64encode(pcm).decode("ascii")})


def test_malformed_and_unauthenticated_first_frames_do_not_dispatch_provider():
    asr = _SyntheticContinuous()
    app = _app(asr)
    with TestClient(app) as client:
        session_id, token, _state = _new_session(client)
        path = f"/api/v1/sessions/{session_id}/continuous-listening"
        with client.websocket_connect(path, headers={"origin": "http://testserver"}) as ws:
            ws.send_text('{"type":"start","type":"start","session_token":"bad","lease_id":"%s"}' % uuid4())
            with pytest.raises(Exception):
                ws.receive_json()
        with client.websocket_connect(path, headers={"origin": "http://testserver"}) as ws:
            ws.send_json({"type": "start", "session_token": "wrong", "lease_id": str(uuid4())})
            with pytest.raises(Exception):
                ws.receive_json()
        with client.websocket_connect(path, headers={"origin": "http://testserver"}) as ws:
            lease_id, _ready = _start(ws, token)
            assert asr.dispatches == 0, "no provider RPC before the first accepted PCM frame"
            # Silence is a valid stream state; it stays connected and does not make a turn.
            asr.emit_transcript = False
            _audio(ws, lease_id)
            deadline = time.monotonic() + 1
            while asr.dispatches == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert asr.dispatches == 1
            _audio(ws, lease_id, seq=2, first=80)
            assert app.state.container.listening_leases._active[session_id].active
            state_after = client.get(f"/api/v1/sessions/{session_id}",
                headers={"X-Mira-Session-Token": token}).json()
            assert not app.state.container.sessions.get(session_id, token)._decision_inputs
            ws.send_json({"type": "stop", "lease_id": lease_id, "reason": "permission_lost"})
            assert ws.receive_json()["type"] == "stopped"
    assert asr.dispatches == 1


def test_manual_commit_round_trips_through_standard_input_barrier_and_survives_reply_turn():
    asr = _SyntheticContinuous()
    app = _app(asr)
    with TestClient(app) as client:
        session_id, token, initial = _new_session(client)
        path = f"/api/v1/sessions/{session_id}/continuous-listening"
        with client.websocket_connect(path, headers={"origin": "http://testserver"}) as ws:
            lease_id, _ready = _start(ws, token)
            _audio(ws, lease_id)
            transcript = None
            endpoint = None
            while transcript is None or endpoint is None:
                frame = ws.receive_json()
                if frame["type"] == "transcript" and frame["is_final"]:
                    transcript = frame
                elif frame["type"] == "endpoint_pending":
                    endpoint = frame
            assert transcript["text"] == "你好，"
            assert endpoint["text"] == "你好，"
            assert not app.state.container.sessions.get(session_id, token)._decision_inputs

            # Explicit user boundary, tied to the exact revision the UI displayed.
            commit_id = str(uuid4())
            ws.send_json({"type": "commit", "lease_id": lease_id,
                          "commit_id": commit_id, "revision": transcript["revision"]})
            ready = None
            while ready is None:
                frame = ws.receive_json()
                if frame["type"] == "commit_ready":
                    ready = frame
            assert ready["commit_id"] == commit_id
            assert ready["text"] == "你好，"
            assert ready["segment_seq"] == 1

            request_id = str(uuid4())
            submit = client.post(f"/api/v1/sessions/{session_id}/inputs", headers={
                "X-Mira-Session-Token": token,
            }, json={"request_id": request_id, "activity_seq": initial["activity_seq"] + 1,
                    "presentation_cutoff": 0, "text": ready["text"],
                    "listening_utterance_id": commit_id})
            assert submit.status_code == 202
            state = submit.json()
            actor = app.state.container.sessions.get(session_id, token)
            assert actor._decision_inputs[-1].text == "你好，"
            assert app.state.container.listening_leases._active[session_id].lease_id == lease_id
            assert asr.dispatches == 1

            # A new reply/input epoch does not kill the independent listening lease.
            current = app.state.container.listening_leases._active.get(session_id)
            assert current is not None and current.active
            ws.send_json({"type": "stop", "lease_id": lease_id, "reason": "user_stop"})
            stopped_frame = None
            while stopped_frame is None:
                candidate = ws.receive_json()
                if candidate["type"] == "stopped":
                    stopped_frame = candidate

            # Exact retries remain idempotent after Actor accepted the user input.
            retry = client.post(f"/api/v1/sessions/{session_id}/inputs", headers={
                "X-Mira-Session-Token": token,
            }, json={"request_id": request_id, "activity_seq": initial["activity_seq"] + 1,
                    "presentation_cutoff": 0, "text": ready["text"],
                    "listening_utterance_id": commit_id})
            assert retry.status_code == 202
            assert actor._decision_inputs[-1].text == "你好，"


def test_global_stop_revokes_unaccepted_manual_commit_and_stops_lease():
    asr = _SyntheticContinuous()
    app = _app(asr)
    with TestClient(app) as client:
        session_id, token, _initial = _new_session(client)
        path = f"/api/v1/sessions/{session_id}/continuous-listening"
        with client.websocket_connect(path, headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _start(ws, token)
            _audio(ws, lease_id)
            transcript = None
            while transcript is None:
                frame = ws.receive_json()
                if frame["type"] == "transcript" and frame["is_final"]:
                    transcript = frame
            commit_id = str(uuid4())
            ws.send_json({"type": "commit", "lease_id": lease_id,
                          "commit_id": commit_id, "revision": transcript["revision"]})
            ready = None
            while ready is None:
                frame = ws.receive_json()
                if frame["type"] == "commit_ready":
                    ready = frame
            state = client.get(f"/api/v1/sessions/{session_id}",
                headers={"X-Mira-Session-Token": token}).json()
            # Actor sequence after a commit is the current activity sequence returned from the snapshot.
            stopped = client.post(f"/api/v1/sessions/{session_id}/stop", headers={
                "X-Mira-Session-Token": token,
            }, json={"activity_seq": state["activity_seq"] + 1,
                    "presentation_cutoff": 0})
            assert stopped.status_code == 200
            while True:
                candidate = ws.receive_json()
                if candidate["type"] == "stopped":
                    assert candidate["reason"] == "user_stop"
                    break
            failed = client.post(f"/api/v1/sessions/{session_id}/inputs", headers={
                "X-Mira-Session-Token": token,
            }, json={"request_id": str(uuid4()), "activity_seq": state["activity_seq"] + 2,
                    "presentation_cutoff": 0, "text": ready["text"],
                    "listening_utterance_id": commit_id})
            assert failed.status_code == 409


def test_duration_cap_is_visible_and_stops_without_rollover():
    asr = _SyntheticContinuous()
    limits = ListeningLimits(max_seconds=1, max_samples=16_000, max_streams_per_session=1,
                             max_total_streams=1)
    app = _app(asr, limits=limits)
    with TestClient(app) as client:
        session_id, token, _ = _new_session(client)
        path = f"/api/v1/sessions/{session_id}/continuous-listening"
        with client.websocket_connect(path, headers={"origin": "http://testserver"}) as ws:
            lease_id, ready = _start(ws, token, expected_max_seconds=1)
            assert ready["max_seconds"] == 1
            # Provider only starts when PCM arrives; while silent the lease remains connected.
            _audio(ws, lease_id)
            assert ws.receive_json()["type"] == "transcript"
            stopped = None
            while stopped is None:
                frame = ws.receive_json()
                if frame["type"] == "stopped":
                    stopped = frame
            assert stopped["reason"] == "max_duration"
        with client.websocket_connect(path, headers={"origin": "http://testserver"}) as ws:
            ws.send_json({"type": "start", "session_token": token, "lease_id": str(uuid4())})
            refused = ws.receive_json()
            assert refused["type"] == "stopped"
            assert refused["reason"] == "session_capacity"


def test_subsecond_stt_bound_disables_continuous_before_provider_dispatch():
    asr = _SyntheticContinuous()
    limits = ListeningLimits(max_seconds=0, max_samples=0, max_streams_per_session=1,
                             max_total_streams=1)
    app = _app(asr, limits=limits)
    with TestClient(app) as client:
        session_id, token, _ = _new_session(client)
        capabilities = client.get("/api/v1/voice-capabilities").json()
        assert capabilities["continuous_listening_enabled"] is False
        with client.websocket_connect(
                f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            ws.send_json({"type": "start", "session_token": token, "lease_id": str(uuid4())})
            stopped = ws.receive_json()
            assert stopped["type"] == "stopped"
            assert stopped["reason"] == "microphone_unavailable"
        assert asr.dispatches == 0


def _google_sdk_asr(*, failure=False, duplicate_after_interim=False):
    """Production SDK mapping/backend with finite responses; no client credentials or RPC."""
    from google.cloud.speech_v2.types import cloud_speech
    from google.protobuf.duration_pb2 import Duration
    from mira.adapters.speech.errors import SpeechProviderError
    from mira.adapters.speech.google_stt_continuous_v2 import (
        GoogleSpeechV2ContinuousBackend, GoogleSpeechV2GrpcContinuousTransport,
    )
    from mira.adapters.speech.google_stt_v2 import SttOptions

    enum = cloud_speech.StreamingRecognizeResponse.SpeechEventType
    def result(text, offset, final=True):
        return cloud_speech.StreamingRecognizeResponse(results=[
            cloud_speech.StreamingRecognitionResult(
                alternatives=[cloud_speech.SpeechRecognitionAlternative(transcript=text)],
                is_final=final, result_end_offset=Duration(nanos=offset * 62_500))])

    responses = [
        cloud_speech.StreamingRecognizeResponse(speech_event_type=enum.SPEECH_ACTIVITY_BEGIN,
            speech_event_offset=Duration()),
        cloud_speech.StreamingRecognizeResponse(speech_event_type=enum.SPEECH_ACTIVITY_END,
            speech_event_offset=Duration(nanos=2_500_000)),
        result("前半句。", 20),
        result("后半句。", 40),
    ]
    if duplicate_after_interim:
        responses += [result("新一句还在说", 60, False), result("后半句。", 40)]

    class Rpc:
        closed = False
        async def __aiter__(self):
            for response in responses:
                yield response
            if failure:
                raise SpeechProviderError("unavailable")
        async def aclose(self):
            self.closed = True

    class Client:
        dispatches = 0
        rpc = Rpc()
        async def streaming_recognize(self, *, requests, timeout, retry):
            assert retry is None
            self.dispatches += 1
            config = await anext(requests)
            assert config.streaming_config.streaming_features.enable_voice_activity_events
            audio = await anext(requests)
            assert audio.audio == b"\0\0" * 80
            return self.rpc

    client = Client()
    transport = GoogleSpeechV2GrpcContinuousTransport(client,
        request_factory=cloud_speech.StreamingRecognizeRequest, response_event_type=enum)
    backend = GoogleSpeechV2ContinuousBackend(
        SttOptions(project_id="mira-test", max_stream_seconds=2), transport)
    return backend, client


@pytest.mark.parametrize("failure", [False, True])
def test_google_sdk_final_tail_survives_provider_terminal_before_http_writer(failure):
    backend, sdk = _google_sdk_asr(failure=failure)
    app = _app(backend)
    with TestClient(app) as client:
        session_id, token, initial = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _start(ws, token)
            _audio(ws, lease_id)
            frames = []
            while not frames or frames[-1]["type"] != "stopped":
                frames.append(ws.receive_json())
            previews = [frame for frame in frames if frame["type"] == "transcript"]
            assert previews, "provider completion must not erase recognized text waiting for the HTTP writer"
            assert previews[-1]["text"] == "前半句。后半句。"
            assert previews[-1]["is_final"] is True
            assert len({frame["revision"] for frame in previews}) == len(previews)
            assert frames[-1]["reason"] == ("unavailable" if failure else "provider_stream_ended")
            assert not app.state.container.sessions.get(session_id, token)._decision_inputs
            assert not app.state.container.listening_leases._utterances
        # Recovery remains an ordinary explicit text input, after the old lease is terminal.
        sent = client.post(f"/api/v1/sessions/{session_id}/inputs", headers={
            "X-Mira-Session-Token": token}, json={"request_id": str(uuid4()),
            "activity_seq": initial["activity_seq"] + 1, "presentation_cutoff": 0,
            "text": "新的手动输入"})
        assert sent.status_code == 202
        assert app.state.container.sessions.get(session_id, token)._decision_inputs[-1].text == "新的手动输入"
    assert sdk.dispatches == 1
    assert sdk.rpc.closed


def test_google_sdk_duplicate_final_retains_interim_at_terminal_without_promoting_it():
    backend, sdk = _google_sdk_asr(duplicate_after_interim=True)
    app = _app(backend)
    with TestClient(app) as client:
        session_id, token, _ = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _start(ws, token)
            _audio(ws, lease_id)
            frames = []
            while not frames or frames[-1]["type"] != "stopped":
                frames.append(ws.receive_json())
            previews = [frame for frame in frames if frame["type"] == "transcript"]
            assert previews
            assert previews[-1]["text"] == "前半句。后半句。新一句还在说"
            assert previews[-1]["is_final"] is False
            assert previews[-1]["revision"] == 3
            assert not app.state.container.listening_leases._utterances
    assert sdk.dispatches == 1
    assert sdk.rpc.closed


def test_simultaneous_stop_frame_fences_unsent_google_sdk_terminal_preview():
    backend, sdk = _google_sdk_asr()
    app = _app(backend)
    with TestClient(app) as client:
        session_id, token, _ = _new_session(client)

        async def exchange():
            incoming, outgoing = asyncio.Queue(), asyncio.Queue()
            lease_id = str(uuid4())
            path = f"/api/v1/sessions/{session_id}/continuous-listening"
            scope = {"type": "websocket", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "scheme": "ws", "path": path, "raw_path": path.encode(), "query_string": b"",
                "root_path": "", "headers": [(b"host", b"testserver"), (b"origin", b"http://testserver")],
                "client": ("testclient", 123), "server": ("testserver", 80), "subprotocols": []}
            task = asyncio.create_task(app(scope, incoming.get, outgoing.put))
            def frame(value):
                incoming.put_nowait({"type": "websocket.receive", "text": json.dumps(value)})
            try:
                async with asyncio.timeout(2):
                    incoming.put_nowait({"type": "websocket.connect"})
                    assert (await outgoing.get())["type"] == "websocket.accept"
                    frame({"type": "start", "session_token": token, "lease_id": lease_id})
                    assert json.loads((await outgoing.get())["text"])["type"] == "ready"
                    # Both frames are queued in the same event-loop turn. The recognized
                    # terminal event and the explicit Stop become ready together.
                    frame({"type": "audio", "lease_id": lease_id, "sequence": 1,
                           "first_sample": 0, "pcm_base64": base64.b64encode(b"\0\0" * 80).decode()})
                    frame({"type": "stop", "lease_id": lease_id, "reason": "user_stop"})
                    received = []
                    while True:
                        message = await outgoing.get()
                        if message["type"] == "websocket.close":
                            break
                        received.append(json.loads(message["text"]))
                    await task
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            return received

        received = client.portal.call(exchange)
        assert [frame["type"] for frame in received] == ["stopped"]
        assert not app.state.container.sessions.get(session_id, token)._decision_inputs
    assert sdk.dispatches == 1
    assert sdk.rpc.closed


def test_natural_google_sdk_two_turns_preserve_accepted_late_correction_identity():
    from google.cloud.speech_v2.types import cloud_speech
    from google.protobuf.duration_pb2 import Duration
    from mira.adapters.speech.google_stt_continuous_v2 import (
        GoogleSpeechV2ContinuousBackend, GoogleSpeechV2GrpcContinuousTransport,
    )
    from mira.adapters.speech.google_stt_v2 import SttOptions

    enum = cloud_speech.StreamingRecognizeResponse.SpeechEventType
    class Rpc:
        closed = False
        def __init__(self):
            self.responses = asyncio.Queue()
        async def __aiter__(self):
            while True:
                response = await self.responses.get()
                if response is None:
                    return
                yield response
        async def aclose(self):
            self.closed = True
    class Sdk:
        rpc = Rpc()
        dispatches = 0
        async def streaming_recognize(self, *, requests, timeout, retry):
            self.dispatches += 1
            await anext(requests)
            await anext(requests)
            return self.rpc
    sdk = Sdk()
    backend = GoogleSpeechV2ContinuousBackend(SttOptions(project_id="mira-test", max_stream_seconds=2),
        GoogleSpeechV2GrpcContinuousTransport(sdk, request_factory=cloud_speech.StreamingRecognizeRequest,
            response_event_type=enum))
    app = _app(backend)
    with TestClient(app) as client:
        def activity(kind, offset):
            response = cloud_speech.StreamingRecognizeResponse(
                speech_event_type=enum.SPEECH_ACTIVITY_BEGIN if kind == "begin" else enum.SPEECH_ACTIVITY_END,
                speech_event_offset=Duration(nanos=offset * 62_500))
            client.portal.call(sdk.rpc.responses.put_nowait, response)
        def final(text, offset):
            response = cloud_speech.StreamingRecognizeResponse(results=[cloud_speech.StreamingRecognitionResult(
                alternatives=[cloud_speech.SpeechRecognitionAlternative(transcript=text)],
                is_final=True, result_end_offset=Duration(nanos=offset * 62_500))])
            client.portal.call(sdk.rpc.responses.put_nowait, response)
        def until(ws, kind):
            while True:
                event = ws.receive_json()
                assert event["type"] != "stopped", event
                if event["type"] == kind:
                    return event
        session_id, token, state = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id = str(uuid4())
            ws.send_json({"type": "start", "session_token": token, "lease_id": lease_id, "mode": "natural"})
            ready = ws.receive_json()
            assert ready["endpoint_mode"] == "google_vad_offsets_natural"
            assert ready["manual_commit_required"] is False
            _audio(ws, lease_id)
            activity("begin", 1)
            activity("end", 40)
            final("喂，", 20)
            final("你好。", 40)
            first = until(ws, "utterance_ready")
            first_commit = str(uuid4())
            ws.send_json({"type": "commit", "lease_id": lease_id, "commit_id": first_commit,
                "revision": first["revision"], "utterance_id": first["utterance_id"]})
            committed = until(ws, "commit_ready")
            assert committed["utterance_id"] == first["utterance_id"]
            request_id = str(uuid4())
            sent = client.post(f"/api/v1/sessions/{session_id}/inputs", headers={"X-Mira-Session-Token": token},
                json={"request_id": request_id, "activity_seq": state["activity_seq"] + 1,
                    "presentation_cutoff": 0, "text": committed["text"], "listening_utterance_id": first_commit})
            assert sent.status_code == 202
            state = sent.json()
            final("补充尾词", 45)
            correction = until(ws, "utterance_revision")
            assert correction["utterance_id"] == first["utterance_id"]
            assert correction["commit_id"] == first_commit
            assert correction["text"] == "喂，你好。补充尾词"
            assert correction["submission_state"] == "accepted"
            assert correction["requires_review"] is True
            activity("begin", 50)
            activity("end", 70)
            final("第二句话。", 70)
            second = until(ws, "utterance_ready")
            assert second["utterance_id"] != first["utterance_id"]
            assert second["text"] == "第二句话。"
            second_commit = str(uuid4())
            ws.send_json({"type": "commit", "lease_id": lease_id, "commit_id": second_commit,
                "revision": second["revision"], "utterance_id": second["utterance_id"]})
            committed = until(ws, "commit_ready")
            sent = client.post(f"/api/v1/sessions/{session_id}/inputs", headers={"X-Mira-Session-Token": token},
                json={"request_id": str(uuid4()), "activity_seq": state["activity_seq"] + 1,
                    "presentation_cutoff": 0, "text": committed["text"], "listening_utterance_id": second_commit})
            assert sent.status_code == 202
            actor = app.state.container.sessions.get(session_id, token)
            assert [item.text for item in actor._decision_inputs] == ["喂，你好。", "第二句话。"]
            ws.send_json({"type": "stop", "lease_id": lease_id, "reason": "user_stop"})
            while ws.receive_json()["type"] != "stopped":
                pass
    assert sdk.dispatches == 1
    assert sdk.rpc.closed


class _V2Sdk:
    """Real DTO/request flow with controlled request EOF and final-result drain."""
    def __init__(self, scripts):
        self.scripts = scripts
        self.rpcs = []

    async def streaming_recognize(self, *, requests, timeout, retry):
        assert retry is None
        initial, after_half_close = self.scripts[len(self.rpcs)]
        rpc = _V2Rpc(initial, after_half_close)
        self.rpcs.append(rpc)
        config = await anext(requests)
        assert config.streaming_config.streaming_features.enable_voice_activity_events
        first = await anext(requests)
        rpc.audio.append(first.audio)
        rpc.reader = asyncio.create_task(rpc.read_audio(requests))
        return rpc


class _V2Rpc:
    def __init__(self, initial, after_half_close):
        self.initial, self.after_half_close = initial, after_half_close
        self.responses = asyncio.Queue()
        self.requests_done = asyncio.Event()
        self.audio = []
        self.reader = None
        self.closed = False

    async def read_audio(self, requests):
        try:
            async for request in requests:
                self.audio.append(request.audio)
        finally:
            self.requests_done.set()

    async def __aiter__(self):
        for response in self.initial:
            yield response
        if self.after_half_close is not None:
            await self.requests_done.wait()
            for response in self.after_half_close:
                yield response
            return
        while True:
            response = await self.responses.get()
            if response is None:
                return
            if isinstance(response, tuple) and response[0] == "drain":
                await self.requests_done.wait()
                for final in response[1]:
                    yield final
                return
            yield response

    async def aclose(self):
        self.closed = True
        if self.reader is not None and not self.reader.done():
            self.reader.cancel()
        if self.reader is not None:
            await asyncio.gather(self.reader, return_exceptions=True)


def _sdk_activity(kind, offset):
    from google.cloud.speech_v2.types import cloud_speech
    from google.protobuf.duration_pb2 import Duration
    enum = cloud_speech.StreamingRecognizeResponse.SpeechEventType
    return cloud_speech.StreamingRecognizeResponse(
        speech_event_type=enum.SPEECH_ACTIVITY_BEGIN if kind == "begin" else enum.SPEECH_ACTIVITY_END,
        speech_event_offset=Duration(nanos=offset * 62_500))


def _sdk_text(text, *, offset=None, final=True):
    from google.cloud.speech_v2.types import cloud_speech
    from google.protobuf.duration_pb2 import Duration
    result = cloud_speech.StreamingRecognitionResult(
        alternatives=[cloud_speech.SpeechRecognitionAlternative(transcript=text)], is_final=final)
    if offset is not None:
        result.result_end_offset = Duration(nanos=offset * 62_500)
    return cloud_speech.StreamingRecognizeResponse(results=[result])


def _v2_app(scripts, *, requests=3, limits=None, stream_seconds=2):
    from google.cloud.speech_v2.types import cloud_speech
    from mira.adapters.speech.google_stt_continuous_v2 import (
        GoogleSpeechV2ContinuousBackend, GoogleSpeechV2GrpcContinuousTransport,
    )
    from mira.adapters.speech.google_stt_v2 import SttOptions
    from mira.bootstrap.development_voice import _AttemptBudget, _BoundedRecognitionEvents
    sdk = _V2Sdk(scripts)
    budget = _AttemptBudget(requests, "input_limit")
    backend = GoogleSpeechV2ContinuousBackend(SttOptions(project_id="mira-test", max_stream_seconds=stream_seconds),
        GoogleSpeechV2GrpcContinuousTransport(sdk, request_factory=cloud_speech.StreamingRecognizeRequest,
            response_event_type=cloud_speech.StreamingRecognizeResponse.SpeechEventType))
    asr = _BoundedRecognitionEvents(backend, attempts=budget, max_seconds=stream_seconds)
    settings = Settings().model_copy(update={"environment": "test",
        "http": Settings().http.model_copy(update={"allowed_origins": ("http://testserver",)})})
    app = create_app(settings, providers=Providers(_Generate(), _Review()),
        continuous_speech_recognition=asr, stt_request_budget=budget,
        listening_limits=limits or ListeningLimits(max_seconds=2, max_samples=32000,
            natural_grace_seconds=.25, max_recognition_streams=3))
    return app, sdk, budget


def _natural_start(ws, token, *, client_endpointing=False):
    lease_id = str(uuid4())
    ws.send_json({"type": "start", "lease_id": lease_id, "session_token": token, "mode": "natural",
        "client_endpointing": client_endpointing})
    ready = ws.receive_json()
    assert ready["type"] == "ready" and ready["manual_commit_required"] is False
    assert ready["natural_grace_ms"] == 250
    return lease_id, ready


def _until_event(ws, kind, seen):
    while True:
        event = ws.receive_json()
        seen.append(event)
        if event["type"] == kind:
            return event
        assert event["type"] != "stopped", event


def _natural_submit(ws, client, session_id, token, state, lease_id, ready, seen):
    commit_id = str(uuid4())
    control = {"type": "commit", "lease_id": lease_id, "commit_id": commit_id,
        "revision": ready["revision"], "utterance_id": ready["utterance_id"]}
    ws.send_json(control)
    committed = _until_event(ws, "commit_ready", seen)
    assert committed["text"] == ready["text"]
    response = client.post(f"/api/v1/sessions/{session_id}/inputs", headers={"X-Mira-Session-Token": token},
        json={"request_id": str(uuid4()), "activity_seq": state["activity_seq"] + 1,
            "presentation_cutoff": 0, "text": committed["text"], "listening_utterance_id": commit_id})
    assert response.status_code == 202
    return response.json(), control, committed


def test_natural_vad_grace_submits_two_activity_suffixes_without_requiring_offset_equality():
    initial = [_sdk_activity("begin", 2), _sdk_activity("end", 160), _sdk_text("自然第一句。", offset=120)]
    app, sdk, budget = _v2_app([(initial, None)])
    with TestClient(app) as client:
        session_id, token, state = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token)
            _audio(ws, lease_id, pcm=b"\x01\x00" * 640)
            seen = []
            first = _until_event(ws, "utterance_ready", seen)
            assert first["endpoint_basis"] == "vad_final_grace"
            assert first["final_offset_samples"] < first["end_offset_samples"]
            assert first["source_end_sample"] == first["end_offset_samples"]
            # Playback overlap keeps this activity held; it must not contaminate a fresh suffix.
            for response in [_sdk_activity("begin", 200), _sdk_activity("end", 480),
                             _sdk_text("打断后新说的话。", offset=440)]:
                client.portal.call(sdk.rpcs[0].responses.put_nowait, response)
            second = _until_event(ws, "utterance_ready", seen)
            assert second["text"] == "打断后新说的话。"
            state, control, committed = _natural_submit(ws, client, session_id, token, state, lease_id, second, seen)
            lease = app.state.container.listening_leases._active[session_id]
            assert lease.stable_text == "自然第一句。"
            assert [item.text for item in app.state.container.sessions.get(session_id, token)._decision_inputs] == [second["text"]]
            ws.send_json(control)
            assert _until_event(ws, "commit_ready", seen) == committed
            ws.send_json({"type": "stop", "lease_id": lease_id, "reason": "user_stop"})
            _until_event(ws, "stopped", seen)
    assert budget.snapshot().used == 1 and len(sdk.rpcs) == 1
    assert sdk.rpcs[0].closed


def test_natural_missing_offset_half_close_drains_two_turns_with_exact_pcm_and_shared_budget():
    initial = [_sdk_activity("begin", 2), _sdk_text("临时", final=False), _sdk_activity("end", 160)]
    scripts = [(initial, [_sdk_text("完整第一句。")]),
               (initial, [_sdk_text("完整第二句。")])]
    app, sdk, budget = _v2_app(scripts, requests=2)
    with TestClient(app) as client:
        session_id, token, state = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token)
            first_pcm, second_pcm = b"\x01\x00" * 320, b"\x02\x00" * 320
            _audio(ws, lease_id, pcm=first_pcm)
            seen = []
            first = _until_event(ws, "utterance_ready", seen)
            assert first["endpoint_basis"] == "stream_finalized"
            assert first["final_offset_samples"] is None
            assert first["source_end_sample"] == 320
            _audio(ws, lease_id, seq=2, first=320, pcm=second_pcm)
            state, _control, _committed = _natural_submit(ws, client, session_id, token, state, lease_id, first, seen)
            second = _until_event(ws, "utterance_ready", seen)
            assert second["endpoint_basis"] == "stream_finalized"
            assert second["begin_offset_samples"] == 322
            assert second["source_end_sample"] == 640
            state, _control, _committed = _natural_submit(ws, client, session_id, token, state, lease_id, second, seen)
            stopped = _until_event(ws, "stopped", seen)
            assert stopped["reason"] == "input_limit"
            assert [item.text for item in app.state.container.sessions.get(session_id, token)._decision_inputs] == ["完整第一句。", "完整第二句。"]
            assert app.state.container.listening_leases._active[session_id].audio.samples == 640
            reservations = [(event["stream_index"], event["stt_requests_used"]) for event in seen
                if event["type"] == "recognition_status" and event["state"] == "opening"
                and event["stt_requests_used"] == event["stream_index"]]
            assert (1, 1) in reservations and (2, 2) in reservations
    assert budget.snapshot().used == 2
    assert len(sdk.rpcs) == 2
    assert sdk.rpcs[0].audio == [first_pcm]
    assert sdk.rpcs[1].audio == [second_pcm]
    assert all(rpc.closed for rpc in sdk.rpcs)


def test_quiet_natural_stream_reports_reserved_attempt_before_any_transcript_and_never_refunds_stop():
    app, sdk, budget = _v2_app([([], None)], requests=1)
    with TestClient(app) as client:
        session_id, token, _ = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token)
            _audio(ws, lease_id)
            seen = []
            while True:
                status = _until_event(ws, "recognition_status", seen)
                if status["stt_requests_used"] == 1:
                    break
            assert status["stt_requests_remaining"] == 0
            assert not any(event["type"] == "transcript" for event in seen)
            ws.send_json({"type": "stop", "lease_id": lease_id, "reason": "user_stop"})
            _until_event(ws, "stopped", seen)
    assert budget.snapshot().used == 1
    assert all(rpc.closed for rpc in sdk.rpcs)


@pytest.mark.parametrize("chunks,samples", [(100, 320), (200, 1)])
def test_natural_pending_commit_audio_queue_limit_is_visible_and_preserves_text(chunks, samples):
    initial = [_sdk_activity("begin", 2), _sdk_text("临时", final=False), _sdk_activity("end", 160)]
    limits = ListeningLimits(max_seconds=4, max_samples=64000, natural_grace_seconds=.25)
    app, sdk, budget = _v2_app([(initial, [_sdk_text("等待确认的完整句子。")])],
        requests=2, limits=limits, stream_seconds=4)
    with TestClient(app) as client:
        session_id, token, _ = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token)
            _audio(ws, lease_id, pcm=b"\x01\x00" * 320)
            seen = []
            ready = _until_event(ws, "utterance_ready", seen)
            lease = app.state.container.listening_leases._active[session_id]
            # Model already-paced PCM without spending real wall time on this cap test.
            client.portal.call(setattr, lease.audio, "_started", time.monotonic() - 2)
            for index in range(chunks):
                _audio(ws, lease_id, seq=index + 2, first=320 + index * samples,
                    pcm=b"\x02\x00" * samples)
            _audio(ws, lease_id, seq=chunks + 2, first=320 + chunks * samples, pcm=b"\x03\x00")
            stopped = _until_event(ws, "stopped", seen)
            assert stopped["reason"] == "queue_limit"
            assert lease.stable_text == ready["text"]
            assert lease.audio._queued_samples == lease.audio._queued_packets == 0
            assert not lease.active
    assert len(sdk.rpcs) == 1 and budget.snapshot().used == 1
    assert sdk.rpcs[0].closed


def test_new_recognition_stream_orphan_final_remains_provisional_instead_of_revising_previous_turn():
    initial = [_sdk_activity("begin", 2), _sdk_activity("end", 160)]
    app, sdk, budget = _v2_app([(initial, [_sdk_text("前一条完整输入。")]),
        ([_sdk_text("新流缺少BEGIN的文字", offset=80)], None)], requests=2)
    with TestClient(app) as client:
        session_id, token, state = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token)
            _audio(ws, lease_id, pcm=b"\x01\x00" * 320)
            seen = []
            ready = _until_event(ws, "utterance_ready", seen)
            _audio(ws, lease_id, seq=2, first=320, pcm=b"\x02\x00" * 320)
            state, _, committed = _natural_submit(ws, client, session_id, token, state, lease_id, ready, seen)
            while True:
                event = ws.receive_json()
                seen.append(event)
                assert event["type"] not in {"utterance_revision", "stopped"}, event
                if event["type"] == "transcript" and event["text"] == "新流缺少BEGIN的文字":
                    break
            assert [item.text for item in app.state.container.sessions.get(session_id, token)._decision_inputs] == [committed["text"]]
            ws.send_json({"type": "stop", "lease_id": lease_id, "reason": "user_stop"})
            _until_event(ws, "stopped", seen)
    assert len(sdk.rpcs) == budget.snapshot().used == 2
    assert all(rpc.closed for rpc in sdk.rpcs)


def test_held_missing_offset_turn_is_retained_while_acknowledged_hold_allows_only_fresh_turn_input():
    initial = [_sdk_activity("begin", 2), _sdk_text("临时", final=False), _sdk_activity("end", 160)]
    app, sdk, budget = _v2_app([(initial, [_sdk_text("播放重叠时保留的旧句。")]),
        (initial, [_sdk_text("显式打断后的新句。")])], requests=2)
    with TestClient(app) as client:
        session_id, token, state = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token)
            _audio(ws, lease_id, pcm=b"\x01\x00" * 320)
            seen = []
            first = _until_event(ws, "utterance_ready", seen)
            assert first["endpoint_basis"] == "stream_finalized"
            _audio(ws, lease_id, seq=2, first=320, pcm=b"\x02\x00" * 320)
            hold = {"type": "hold", "lease_id": lease_id,
                    "utterance_id": first["utterance_id"], "revision": first["revision"]}
            ws.send_json(hold)
            held = _until_event(ws, "utterance_held", seen)
            assert held["text"] == first["text"]
            assert held["utterance_id"] == first["utterance_id"]
            second = _until_event(ws, "utterance_ready", seen)
            assert second["utterance_id"] != first["utterance_id"]
            assert second["text"] == "显式打断后的新句。"
            assert not app.state.container.listening_leases._utterances
            assert not app.state.container.sessions.get(session_id, token)._decision_inputs
            # The same hold can be acknowledged again without another RPC or model input.
            ws.send_json(hold)
            assert _until_event(ws, "utterance_held", seen) == held
            ws.send_json({**hold, "revision": hold["revision"] + 1})
            assert _until_event(ws, "hold_rejected", seen)["reason"] == "identity_conflict"
            ws.send_json({**hold, "utterance_id": str(uuid4())})
            assert _until_event(ws, "hold_rejected", seen)["reason"] in {"stale_revision", "identity_conflict"}
            ws.send_json({"type": "commit", "lease_id": lease_id, "commit_id": str(uuid4()),
                "utterance_id": first["utterance_id"], "revision": first["revision"]})
            assert _until_event(ws, "commit_rejected", seen)["reason"] == "stale_revision"
            state, _, _ = _natural_submit(ws, client, session_id, token, state, lease_id, second, seen)
            assert _until_event(ws, "stopped", seen)["reason"] == "input_limit"
            lease = app.state.container.listening_leases._active[session_id]
            assert lease.stable_text == held["text"]
            assert [item.text for item in app.state.container.sessions.get(session_id, token)._decision_inputs] == [second["text"]]
            assert len(app.state.container.listening_leases._utterances) == 1
            from mira.domain.errors import DomainError
            with pytest.raises(DomainError, match="revoked"):
                client.portal.call(lambda: lease.hold_candidate(
                    utterance_id=first["utterance_id"], revision=first["revision"]))
    assert len(sdk.rpcs) == budget.snapshot().used == 2
    assert sdk.rpcs[0].audio == [b"\x01\x00" * 320]
    assert sdk.rpcs[1].audio == [b"\x02\x00" * 320]
    assert all(rpc.closed for rpc in sdk.rpcs)


def test_failed_hold_ack_cannot_open_next_rpc_or_create_input_and_keeps_observed_text(monkeypatch):
    from starlette.websockets import WebSocket, WebSocketDisconnect
    original_send = WebSocket.send_text
    async def fail_hold_ack(websocket, data):
        if json.loads(data).get("type") == "utterance_held":
            raise RuntimeError("synthetic failed acknowledgment")
        await original_send(websocket, data)
    monkeypatch.setattr(WebSocket, "send_text", fail_hold_ack)
    initial = [_sdk_activity("begin", 2), _sdk_activity("end", 160)]
    app, sdk, budget = _v2_app([(initial, [_sdk_text("确认丢失也保留的文字。")]),
        (initial, [_sdk_text("不应启动的下一流。")])], requests=2)
    with TestClient(app) as client:
        session_id, token, _ = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token)
            _audio(ws, lease_id, pcm=b"\x01\x00" * 320)
            seen = []
            ready = _until_event(ws, "utterance_ready", seen)
            lease = app.state.container.listening_leases._active[session_id]
            _audio(ws, lease_id, seq=2, first=320, pcm=b"\x02\x00" * 320)
            ws.send_json({"type": "hold", "lease_id": lease_id,
                "utterance_id": ready["utterance_id"], "revision": ready["revision"]})
            with pytest.raises(WebSocketDisconnect):
                while True:
                    event = ws.receive_json()
                    assert event["type"] not in {"utterance_held", "commit_ready"}
                    assert event.get("stream_index", 1) == 1
            assert not lease.active
            assert lease.stable_text == ready["text"]
            assert not app.state.container.listening_leases._utterances
            assert not app.state.container.sessions.get(session_id, token)._decision_inputs
    assert len(sdk.rpcs) == budget.snapshot().used == 1
    assert sdk.rpcs[0].closed


@pytest.mark.parametrize("first_basis", ["offset_coverage", "vad_final_grace"])
def test_later_missing_offset_activity_in_same_rpc_drains_only_after_proven_previous_coverage(first_basis):
    first_offset = 160 if first_basis == "offset_coverage" else 120
    first_script = [_sdk_activity("begin", 2), _sdk_activity("end", 160),
                    _sdk_text("第一句已经提交。", offset=first_offset)]
    next_script = [_sdk_activity("begin", 2), _sdk_text("临时", final=False), _sdk_activity("end", 160)]
    app, sdk, budget = _v2_app([(first_script, None),
        (next_script, [_sdk_text("打断之后真正的新句。")])], requests=2)
    with TestClient(app) as client:
        session_id, token, state = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token)
            pcm1, pcm2, pcm3 = (bytes([value, 0]) * 320 for value in (1, 2, 3))
            _audio(ws, lease_id, pcm=pcm1)
            seen = []
            first = _until_event(ws, "utterance_ready", seen)
            assert first["endpoint_basis"] == first_basis
            state, _, _ = _natural_submit(ws, client, session_id, token, state, lease_id, first, seen)
            _audio(ws, lease_id, seq=2, first=320, pcm=pcm2)
            for response in [_sdk_activity("begin", 400), _sdk_text("播放重叠临时词", final=False),
                             _sdk_activity("end", 600), ("drain", [_sdk_text("需要保留的播放重叠句。")])]:
                client.portal.call(sdk.rpcs[0].responses.put_nowait, response)
            if first_basis == "vad_final_grace":
                stopped = _until_event(ws, "stopped", seen)
                assert stopped["reason"] == "incomplete_stream"
                assert [item.text for item in app.state.container.sessions.get(session_id, token)._decision_inputs] == [first["text"]]
            else:
                echo = _until_event(ws, "utterance_ready", seen)
                assert echo["endpoint_basis"] == "stream_finalized"
                assert echo["text"] == "需要保留的播放重叠句。"
                _audio(ws, lease_id, seq=3, first=640, pcm=pcm3)
                ws.send_json({"type": "hold", "lease_id": lease_id,
                    "utterance_id": echo["utterance_id"], "revision": echo["revision"]})
                held = _until_event(ws, "utterance_held", seen)
                fresh = _until_event(ws, "utterance_ready", seen)
                assert fresh["begin_offset_samples"] == 642
                assert fresh["source_end_sample"] == 960
                state, _, _ = _natural_submit(ws, client, session_id, token, state, lease_id, fresh, seen)
                assert _until_event(ws, "stopped", seen)["reason"] == "input_limit"
                assert app.state.container.listening_leases._active[session_id].stable_text == held["text"]
                assert [item.text for item in app.state.container.sessions.get(session_id, token)._decision_inputs] == [first["text"], fresh["text"]]
    assert len(sdk.rpcs) == budget.snapshot().used == (2 if first_basis == "offset_coverage" else 1)
    assert sdk.rpcs[0].audio == [pcm1, pcm2]
    if first_basis == "offset_coverage":
        assert sdk.rpcs[1].audio == [pcm3]
    assert all(rpc.closed for rpc in sdk.rpcs)


def _client_endpoint(ws, lease_id, source_end, endpoint_id=None):
    endpoint_id = endpoint_id or str(uuid4())
    ws.send_json({"type": "client_endpoint", "lease_id": lease_id,
        "endpoint_id": endpoint_id, "source_end_sample": source_end})
    return endpoint_id


def test_client_silence_without_provider_activity_or_offsets_drains_two_exact_turns():
    app, sdk, budget = _v2_app([([], [_sdk_text("沉默后第一句。")]),
                              ([], [_sdk_text("沉默后第二句。")])], requests=2)
    with TestClient(app) as client:
        session_id, token, state = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, capabilities = _natural_start(ws, token, client_endpointing=True)
            seen = []
            expected = []
            for turn in range(2):
                pcm = bytes([turn + 1, 0]) * 320
                expected.append(pcm)
                _audio(ws, lease_id, seq=turn + 1, first=turn * 320, pcm=pcm)
                endpoint_id = _client_endpoint(ws, lease_id, (turn + 1) * 320)
                ready = _until_event(ws, "utterance_ready", seen)
                assert ready["endpoint_basis"] == "client_silence_finalized"
                assert ready["begin_offset_samples"] == turn * 320
                assert ready["source_end_sample"] == (turn + 1) * 320
                assert ready["final_offset_samples"] is None
                assert any(event["type"] == "endpoint_status" and event["endpoint_id"] == endpoint_id
                           and event["state"] == "queued" for event in seen)
                state, _control, _committed = _natural_submit(
                    ws, client, session_id, token, state, lease_id, ready, seen)
            assert _until_event(ws, "stopped", seen)["reason"] == "input_limit"
            assert [item.text for item in app.state.container.sessions.get(session_id, token)._decision_inputs] == [
                "沉默后第一句。", "沉默后第二句。"]
            assert capabilities["client_endpoint_supported"] is True
            assert capabilities["client_silence_ms"] == 700
    assert budget.snapshot().used == 2 and len(sdk.rpcs) == 2
    assert [rpc.audio for rpc in sdk.rpcs] == [[pcm] for pcm in expected]
    assert all(rpc.closed for rpc in sdk.rpcs)


@pytest.mark.parametrize("response", [None, "[noise]", "[silence]", "...", "interim"])
def test_client_silence_empty_or_unstable_drain_stops_visibly_without_a_turn(response):
    finals = [] if response is None else [_sdk_text(response, final=response != "interim")]
    app, sdk, budget = _v2_app([([], finals)], requests=2)
    with TestClient(app) as client:
        session_id, token, _ = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token, client_endpointing=True)
            _audio(ws, lease_id, pcm=b"\0\0" * 320)
            _client_endpoint(ws, lease_id, 320)
            seen = []
            stopped = _until_event(ws, "stopped", seen)
            assert stopped["reason"] == "incomplete_stream"
            assert not [event for event in seen if event["type"] == "utterance_ready"]
            assert not app.state.container.sessions.get(session_id, token)._decision_inputs
            if response is not None:
                assert any(event["type"] == "transcript" and event["text"] == response for event in seen)
    assert budget.snapshot().used == 1 and len(sdk.rpcs) == 1


def test_client_silence_repeated_endpoint_and_hold_retain_old_text_then_accept_fresh_input():
    app, sdk, budget = _v2_app([([], [_sdk_text("先保留这句。")]),
                              ([], [_sdk_text("接着说的新句。")])], requests=2)
    with TestClient(app) as client:
        session_id, token, state = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token, client_endpointing=True)
            _audio(ws, lease_id, pcm=b"\0\0" * 320)
            first_id = _client_endpoint(ws, lease_id, 320)
            seen = []
            first = _until_event(ws, "utterance_ready", seen)
            _client_endpoint(ws, lease_id, 320, first_id)
            status = _until_event(ws, "endpoint_status", seen)
            assert status["state"] == "completed"
            ws.send_json({"type": "cancel_endpoint", "lease_id": lease_id, "endpoint_id": first_id})
            assert _until_event(ws, "endpoint_status", seen)["state"] == "completed"
            held = {"type": "hold", "lease_id": lease_id, "utterance_id": first["utterance_id"],
                    "revision": first["revision"]}
            ws.send_json(held)
            assert _until_event(ws, "utterance_held", seen)["text"] == first["text"]
            _audio(ws, lease_id, seq=2, first=320, pcm=b"\0\0" * 320)
            _client_endpoint(ws, lease_id, 640)
            second = _until_event(ws, "utterance_ready", seen)
            assert second["text"] == "接着说的新句。"
            _natural_submit(ws, client, session_id, token, state, lease_id, second, seen)
            assert _until_event(ws, "stopped", seen)["reason"] == "input_limit"
            lease = app.state.container.listening_leases._active[session_id]
            assert lease.stable_text == first["text"]
            assert [item.text for item in app.state.container.sessions.get(session_id, token)._decision_inputs] == [second["text"]]
    assert budget.snapshot().used == 2 and len(sdk.rpcs) == 2


@pytest.mark.parametrize("provider_events", [[], [_sdk_activity("begin", 0)],
                                           [_sdk_activity("end", 200)],
                                           [_sdk_activity("begin", 0), _sdk_activity("begin", 100)]])
def test_client_silence_missing_activity_variants_drain_at_exact_sample_limit(provider_events):
    limits = ListeningLimits(max_seconds=2, max_samples=320, natural_grace_seconds=.25,
                             max_recognition_streams=1)
    app, sdk, budget = _v2_app([(provider_events, [_sdk_text("最后一句。", offset=320)])],
                             requests=1, limits=limits)
    with TestClient(app) as client:
        session_id, token, state = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token, client_endpointing=True)
            _audio(ws, lease_id, pcm=b"\0\0" * 320)
            _client_endpoint(ws, lease_id, 320)
            seen = []
            candidate = _until_event(ws, "utterance_ready", seen)
            assert candidate["source_end_sample"] == 320
            _natural_submit(ws, client, session_id, token, state, lease_id, candidate, seen)
            assert _until_event(ws, "stopped", seen)["reason"] == "input_limit"
    assert budget.snapshot().used == 1 and len(sdk.rpcs) == 1


@pytest.mark.parametrize("frontier", [0, True, 319, 321, 4_640_001])
def test_client_silence_rejects_unbound_frontier_without_input(frontier):
    app, sdk, budget = _v2_app([([], None)])
    with TestClient(app) as client:
        session_id, token, _ = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token, client_endpointing=True)
            _audio(ws, lease_id, pcm=b"\0\0" * 320)
            _client_endpoint(ws, lease_id, frontier)
            seen = []
            assert _until_event(ws, "stopped", seen)["reason"] == "invalid_input"
            assert not app.state.container.listening_leases._utterances
    assert budget.snapshot().used <= 1


def test_client_silence_nonclosing_provider_hits_bounded_drain_timeout():
    limits = ListeningLimits(max_seconds=2, max_samples=32000, natural_grace_seconds=.25,
                             drain_timeout_seconds=.1)
    app, sdk, budget = _v2_app([([], None)], limits=limits)
    with TestClient(app) as client:
        session_id, token, _ = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token, client_endpointing=True)
            _audio(ws, lease_id, pcm=b"\0\0" * 320)
            _client_endpoint(ws, lease_id, 320)
            seen = []
            assert _until_event(ws, "stopped", seen)["reason"] == "timeout"
            assert not app.state.container.listening_leases._utterances
    assert len(sdk.rpcs) == budget.snapshot().used == 1


def test_client_silence_real_asgi_cancel_queued_endpoint_then_resend_same_stream():
    app, sdk, budget = _v2_app([([], [_sdk_text("继续说完之后。")])], requests=1)
    original = sdk.streaming_recognize
    permit_read = asyncio.Event()

    async def delayed_open(**kwargs):
        await permit_read.wait()
        return await original(**kwargs)

    sdk.streaming_recognize = delayed_open
    with TestClient(app) as client:
        session_id, token, state = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token, client_endpointing=True)
            _audio(ws, lease_id, pcm=b"\x01\0" * 320)
            _audio(ws, lease_id, seq=2, first=320, pcm=b"\x02\0" * 320)
            endpoint = _client_endpoint(ws, lease_id, 640)
            seen = []
            assert _until_event(ws, "endpoint_status", seen)["state"] == "queued"
            ws.send_json({"type": "cancel_endpoint", "lease_id": lease_id, "endpoint_id": endpoint})
            cancelled = _until_event(ws, "endpoint_status", seen)
            assert cancelled["state"] == "cancelled" and cancelled["endpoint_id"] == endpoint
            _audio(ws, lease_id, seq=3, first=640, pcm=b"\x03\0" * 320)
            replacement = _client_endpoint(ws, lease_id, 960)
            assert _until_event(ws, "endpoint_status", seen)["state"] == "queued"
            client.portal.call(permit_read.set)
            ready = _until_event(ws, "utterance_ready", seen)
            assert ready["client_endpoint_id"] == replacement
            assert ready["source_end_sample"] == 960
            _natural_submit(ws, client, session_id, token, state, lease_id, ready, seen)
            assert _until_event(ws, "stopped", seen)["reason"] == "input_limit"
    assert len(sdk.rpcs) == budget.snapshot().used == 1
    assert sdk.rpcs[0].audio == [bytes([value, 0]) * 320 for value in (1, 2, 3)]


def test_client_silence_mode_defers_provider_endpoint_until_local_quiet_intent():
    initial = [_sdk_activity("begin", 0), _sdk_activity("end", 200), _sdk_text("说到一半", offset=200)]
    app, sdk, budget = _v2_app([(initial, [_sdk_text("现在说完。", offset=600)])], requests=1)
    with TestClient(app) as client:
        session_id, token, state = _new_session(client)
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/continuous-listening",
                headers={"origin": "http://testserver"}) as ws:
            lease_id, _ = _natural_start(ws, token, client_endpointing=True)
            _audio(ws, lease_id, pcm=b"\x01\0" * 320)
            seen = []
            _until_event(ws, "transcript", seen)
            # Wait past legacy VAD grace: only a client quiet intent may half-close.
            time.sleep(.3)
            lease = app.state.container.listening_leases._active[session_id]
            assert lease.natural_candidate() is None
            assert not lease._segment.draining
            _audio(ws, lease_id, seq=2, first=320, pcm=b"\x02\0" * 320)
            endpoint = _client_endpoint(ws, lease_id, 640)
            ready = _until_event(ws, "utterance_ready", seen)
            assert ready["text"] == "说到一半现在说完。"
            assert ready["client_endpoint_id"] == endpoint
            assert len([event for event in seen if event["type"] == "utterance_ready"]) == 1
            _natural_submit(ws, client, session_id, token, state, lease_id, ready, seen)
            assert _until_event(ws, "stopped", seen)["reason"] == "input_limit"
    assert len(sdk.rpcs) == budget.snapshot().used == 1
