"""Continuous Google adapter contracts, entirely offline and using an injected fake SDK seam."""
from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

from mira.adapters.speech.google_stt_continuous_v2 import (
    GoogleSpeechV2ContinuousBackend, GoogleSpeechV2GrpcContinuousTransport,
)
from mira.adapters.speech.google_stt_v2 import SttOptions
from mira.application.ports.continuous_speech import (
    ContinuousSpeechActivity, ContinuousTranscriptResult,
)
from mira.application.ports.media import AudioPacket


class _FakeTransport:
    def __init__(self, events):
        self.events = events
        self.requests = []
        self.timeout = None

    async def stream(self, requests, *, timeout_seconds):
        self.timeout = timeout_seconds
        async for request in requests:
            self.requests.append(request)
        for event in self.events:
            yield event


@pytest.mark.asyncio
async def test_continuous_request_enables_vad_but_does_not_set_voice_activity_timeout():
    transport = _FakeTransport([
        ContinuousSpeechActivity("begin", 100),
        ContinuousTranscriptResult(" 你好", False, None),
        ContinuousTranscriptResult(" 你好", True, 15_400),
        ContinuousSpeechActivity("end", 22_000),
    ])
    options = SttOptions(project_id="mira-test", max_stream_seconds=2)
    backend = GoogleSpeechV2ContinuousBackend(options, transport)
    events = [event async for event in backend.transcribe_events(
        _packets([AudioPacket("lease-a", 0, 16_000, b"\0\0" * 1600)]))]
    config = transport.requests[0]["streaming_config"]
    assert config["streaming_features"] == {
        "interim_results": True,
        "enable_voice_activity_events": True,
    }
    assert "voice_activity_timeout" not in config["streaming_features"]
    assert events == [
        ContinuousSpeechActivity("begin", 100),
        ContinuousTranscriptResult(" 你好", False, None),
        ContinuousTranscriptResult(" 你好", True, 15_400),
        ContinuousSpeechActivity("end", 22_000),
    ]
    assert backend.max_stream_seconds == 2
    assert backend.endpoint_mode == "google_vad_offsets"


@pytest.mark.asyncio
async def test_empty_audio_does_not_open_provider_stream():
    transport = _FakeTransport([])
    backend = GoogleSpeechV2ContinuousBackend(SttOptions(project_id="mira-test"), transport)
    assert [event async for event in backend.transcribe_events(_packets([]))] == []
    assert transport.requests == []
    assert transport.timeout is None


@pytest.mark.asyncio
async def test_invalid_audio_is_rejected_before_provider_stream():
    transport = _FakeTransport([])
    backend = GoogleSpeechV2ContinuousBackend(SttOptions(project_id="mira-test"), transport)
    with pytest.raises(Exception):
        [event async for event in backend.transcribe_events(
            _packets([AudioPacket("lease-a", 1, 16_000, b"\0\0" * 10)]))]
    assert transport.requests == []


class _FakeRpc:
    def __init__(self, responses):
        self.responses = responses
        self.closed = False

    def __aiter__(self):
        async def values():
            for response in self.responses:
                yield response
        return values()

    async def aclose(self):
        self.closed = True


class _FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.kwargs = None
        self.rpc = _FakeRpc(responses)

    async def streaming_recognize(self, **kwargs):
        self.kwargs = kwargs
        # The transport hands a streaming request iterator just as the GAPIC bridge does.
        async for _ in kwargs["requests"]:
            pass
        return self.rpc


@pytest.mark.asyncio
async def test_grpc_transport_maps_sdk_vad_and_result_offsets_to_sample_offsets():
    from google.cloud.speech_v2.types import cloud_speech

    enum = cloud_speech.StreamingRecognizeResponse.SpeechEventType
    begin = SimpleNamespace(results=(), speech_event_type=enum.SPEECH_ACTIVITY_BEGIN,
                            speech_event_offset=SimpleNamespace(seconds=0, nanos=6_250_000))
    result = SimpleNamespace(alternatives=[SimpleNamespace(transcript="你好")], is_final=True,
                              result_end_offset=SimpleNamespace(seconds=1, nanos=25_000_000))
    final = SimpleNamespace(results=[result], speech_event_type=enum.SPEECH_EVENT_TYPE_UNSPECIFIED,
                             speech_event_offset=None)
    end = SimpleNamespace(results=(), speech_event_type=enum.SPEECH_ACTIVITY_END,
                          speech_event_offset=SimpleNamespace(seconds=1, nanos=500_000_000))
    client = _FakeClient([begin, final, end])
    transport = GoogleSpeechV2GrpcContinuousTransport(client,
        request_factory=lambda **kwargs: kwargs, response_event_type=enum)
    output = [event async for event in transport.stream(
        _requests([{"streaming_config": {}}, {"audio": b"\0\0"}]), timeout_seconds=60)]
    assert output == [
        ContinuousSpeechActivity("begin", 100),
        ContinuousTranscriptResult("你好", True, 16_400),
        ContinuousSpeechActivity("end", 24_000),
    ]
    assert client.kwargs["retry"] is None
    assert client.kwargs["timeout"] == 60
    assert client.rpc.closed is True  # this transport owns and closes only its per-call RPC


@pytest.mark.asyncio
async def test_grpc_transport_rejects_stream_closing_single_utterance_event():
    from google.cloud.speech_v2.types import cloud_speech

    enum = cloud_speech.StreamingRecognizeResponse.SpeechEventType
    response = SimpleNamespace(results=(), speech_event_type=enum.END_OF_SINGLE_UTTERANCE,
        speech_event_offset=SimpleNamespace(seconds=1, nanos=0))
    client = _FakeClient([response])
    transport = GoogleSpeechV2GrpcContinuousTransport(client,
        request_factory=lambda **kwargs: kwargs, response_event_type=enum)
    with pytest.raises(Exception):
        [event async for event in transport.stream(_requests([{"audio": b"\0\0"}]),
                                                    timeout_seconds=60)]


async def _packets(values):
    for value in values:
        yield value


async def _requests(values):
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_installed_sdk_proto_plus_duration_timedelta_and_absent_field():
    from datetime import timedelta
    from google.cloud.speech_v2.types import cloud_speech
    from google.protobuf.duration_pb2 import Duration

    enum = cloud_speech.StreamingRecognizeResponse.SpeechEventType
    sdk_final = cloud_speech.StreamingRecognitionResult(
        alternatives=[cloud_speech.SpeechRecognitionAlternative(transcript="你好")],
        is_final=True,
        result_end_offset=Duration(seconds=1, nanos=500_000_000),
    )
    absent = cloud_speech.StreamingRecognitionResult(
        alternatives=[cloud_speech.SpeechRecognitionAlternative(transcript="interim")],
        is_final=False,
    )
    sdk_begin = cloud_speech.StreamingRecognizeResponse(
        speech_event_type=enum.SPEECH_ACTIVITY_BEGIN,
        speech_event_offset=Duration(seconds=0, nanos=6_250_000),
    )
    sdk_text = cloud_speech.StreamingRecognizeResponse(results=[sdk_final, absent])
    sdk_end = cloud_speech.StreamingRecognizeResponse(
        speech_event_type=enum.SPEECH_ACTIVITY_END,
        speech_event_offset=Duration(seconds=1, nanos=500_000_000),
    )
    assert isinstance(sdk_final.result_end_offset, timedelta)
    assert sdk_final.result_end_offset == timedelta(seconds=1, microseconds=500_000)
    assert not sdk_text.results[1]._pb.HasField("result_end_offset")

    client = _FakeClient([sdk_begin, sdk_text, sdk_end])
    transport = GoogleSpeechV2GrpcContinuousTransport(client,
        request_factory=cloud_speech.StreamingRecognizeRequest,
        response_event_type=enum)
    output = [event async for event in transport.stream(_requests([
        {"recognizer": "projects/mira-test/locations/us/recognizers/_",
         "streaming_config": {"streaming_features": {"enable_voice_activity_events": True}}},
        {"audio": b"\0\0"},
    ]), timeout_seconds=10)]
    assert output == [
        ContinuousSpeechActivity("begin", 100),
        ContinuousTranscriptResult("你好", True, 24_000,
            provider_batch_complete=False, has_pending_interim=True),
        ContinuousTranscriptResult("interim", False, None, has_pending_interim=True),
        ContinuousSpeechActivity("end", 24_000),
    ]


@pytest.mark.asyncio
async def test_sdk_batch_keeps_all_interim_portions_and_marks_final_not_batch_complete():
    from google.cloud.speech_v2.types import cloud_speech
    from google.protobuf.duration_pb2 import Duration

    def result(text, final, nanos):
        return cloud_speech.StreamingRecognitionResult(
            alternatives=[cloud_speech.SpeechRecognitionAlternative(transcript=text)],
            is_final=final, result_end_offset=Duration(nanos=nanos))
    response = cloud_speech.StreamingRecognizeResponse(results=[
        result("已确定。", True, 1_000_000), result("第一临时段", False, 2_000_000),
        result("第二临时段", False, 3_000_000)])
    client = _FakeClient([response])
    transport = GoogleSpeechV2GrpcContinuousTransport(client,
        request_factory=cloud_speech.StreamingRecognizeRequest,
        response_event_type=cloud_speech.StreamingRecognizeResponse.SpeechEventType)
    output = [event async for event in transport.stream(_requests([{"audio": b"\0\0"}]), timeout_seconds=2)]
    assert output == [
        ContinuousTranscriptResult("已确定。", True, 16,
            provider_batch_complete=False, has_pending_interim=True),
        ContinuousTranscriptResult("第一临时段第二临时段", False, 48,
            provider_batch_complete=True, has_pending_interim=True)]


@pytest.mark.asyncio
@pytest.mark.parametrize("finality", [(True, True), (False, True)])
async def test_invalid_sdk_result_batch_fails_before_any_partial_candidate_is_yielded(finality):
    from google.cloud.speech_v2.types import cloud_speech
    from google.protobuf.duration_pb2 import Duration

    response = cloud_speech.StreamingRecognizeResponse(results=[
        cloud_speech.StreamingRecognitionResult(
            alternatives=[cloud_speech.SpeechRecognitionAlternative(transcript=f"portion-{index}")],
            is_final=final, result_end_offset=Duration(nanos=(index + 1) * 1_000_000))
        for index, final in enumerate(finality)])
    client = _FakeClient([response])
    transport = GoogleSpeechV2GrpcContinuousTransport(client,
        request_factory=cloud_speech.StreamingRecognizeRequest,
        response_event_type=cloud_speech.StreamingRecognizeResponse.SpeechEventType)
    output = []
    with pytest.raises(Exception):
        async for event in transport.stream(_requests([{"audio": b"\0\0"}]), timeout_seconds=2):
            output.append(event)
    assert output == []
