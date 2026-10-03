"""Synthetic STT V2 streaming contract; no SDK credentials are discovered."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from mira.adapters.speech.errors import SpeechProviderError
from mira.adapters.speech.google_stt_v2 import (
    GoogleSpeechV2Backend,
    GoogleSpeechV2GrpcTransport,
    SttOptions,
    SttResponse,
    SttResult,
)
from mira.application.ports.media import AudioPacket


async def packets(*items):
    for item in items:
        yield item


class Transport:
    def __init__(self, responses):
        self.responses, self.calls, self.closed = responses, [], False
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def stream(self, requests, *, timeout_seconds):
        self.calls = [item async for item in requests]
        try:
            for response in self.responses:
                if response == "WAIT":
                    self.entered.set()
                    await self.release.wait()
                elif isinstance(response, Exception):
                    raise response
                else:
                    yield response
        finally:
            self.closed = True


def backend(transport, **kwargs):
    return GoogleSpeechV2Backend(SttOptions(project_id="mira-test", **kwargs), transport)


def packet(data=b"\0\0" * 10, first=0, stream="in-1", rate=16000):
    return AudioPacket(stream, first, rate, data)


@pytest.mark.asyncio
async def test_config_first_audio_chunking_and_cumulative_revisions():
    transport = Transport([
        SttResponse((SttResult("你", False),)),
        SttResponse((SttResult("你好", True), SttResult("世", False))),
        SttResponse((SttResult("世界", True),)),
    ])
    result = [r async for r in backend(transport).transcribe(packets(packet(b"\0\0" * 16000)))]
    assert [(r.revision, r.text, r.is_final) for r in result] == [(1, "你", False), (2, "你好世", False), (3, "你好世界", True)]
    assert {r.input_stream_id for r in result} == {"in-1"}
    config, *audio = transport.calls
    assert config == {"recognizer": "projects/mira-test/locations/us/recognizers/_", "streaming_config": {"config": {"explicit_decoding_config": {"encoding": "LINEAR16", "sample_rate_hertz": 16000, "audio_channel_count": 1}, "language_codes": ["cmn-Hans-CN"], "model": "chirp_3"}, "streaming_features": {"interim_results": True}}}
    assert all(set(item) == {"audio"} and 0 < len(item["audio"]) <= 12000 for item in audio)
    assert b"".join(item["audio"] for item in audio) == b"\0\0" * 16000
    assert transport.closed


@pytest.mark.asyncio
async def test_empty_input_opens_no_rpc():
    transport = Transport([])
    assert [r async for r in backend(transport).transcribe(packets())] == []
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("second", [packet(first=11), packet(first=10, stream="other"), packet(first=10, rate=24000), packet(data=b"\0", first=10)])
async def test_malformed_input_fails_explicitly(second):
    with pytest.raises(SpeechProviderError, match="invalid_input"):
        _ = [r async for r in backend(Transport([])).transcribe(packets(packet(), second))]


@pytest.mark.asyncio
async def test_input_duration_limit():
    with pytest.raises(SpeechProviderError, match="input_limit"):
        _ = [r async for r in backend(Transport([]), max_stream_seconds=1).transcribe(packets(packet(b"\0\0" * 16001)))]


@pytest.mark.asyncio
async def test_silence_is_empty_but_provider_failure_is_not():
    assert [r async for r in backend(Transport([SttResponse(())])).transcribe(packets(packet()))] == []
    with pytest.raises(SpeechProviderError) as caught:
        _ = [r async for r in backend(Transport([RuntimeError("secret-token")])).transcribe(packets(packet()))]
    assert caught.value.code == "unavailable" and "secret-token" not in str(caught.value)


@pytest.mark.asyncio
async def test_stt_cancellation_and_early_close():
    transport = Transport([SttResponse((SttResult("你", False),)), "WAIT", SttResponse((SttResult("你好", True),))])
    stream = backend(transport).transcribe(packets(packet()))
    await anext(stream)
    task = asyncio.create_task(anext(stream))
    await asyncio.wait_for(transport.entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    transport.release.set()
    assert transport.closed
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    transport2 = Transport([SttResponse((SttResult("你好", False),))])
    stream2 = backend(transport2).transcribe(packets(packet()))
    await anext(stream2)
    await stream2.aclose()
    assert transport2.closed


class Rpc:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def __aiter__(self):
        return self.responses()

    async def responses(self):
        yield SimpleNamespace(results=[SimpleNamespace(alternatives=[SimpleNamespace(transcript="你好")], is_final=True)])


class Client:
    def __init__(self):
        self.rpc = Rpc()

    async def streaming_recognize(self, *, requests, timeout, retry):
        self.requests = [item async for item in requests]
        self.timeout, self.retry = timeout, retry
        return self.rpc


@pytest.mark.asyncio
async def test_grpc_bridge_uses_injected_client_and_cancels_rpc():
    client = Client()
    transport = GoogleSpeechV2GrpcTransport(client, request_factory=lambda **kw: kw)
    result = [r async for r in backend(transport).transcribe(packets(packet()))]
    assert result[0].text == "你好" and client.rpc.cancelled
    assert client.timeout > 0 and client.retry is None
    assert client.requests[0]["recognizer"].endswith("/us/recognizers/_")


@pytest.mark.asyncio
async def test_invalid_first_packet_is_safe_and_does_not_open_rpc():
    transport = Transport([])
    with pytest.raises(SpeechProviderError, match="invalid_input"):
        _ = [r async for r in backend(transport).transcribe(packets(object()))]
    assert transport.calls == []


@pytest.mark.asyncio
async def test_early_close_closes_input_source():
    closed = asyncio.Event()

    async def source():
        try:
            yield packet()
            await asyncio.Event().wait()
        finally:
            closed.set()

    class EarlyTransport:
        async def stream(self, requests, *, timeout_seconds):
            await anext(requests)  # configuration
            await anext(requests)  # first packet
            yield SttResponse((SttResult("你", False),))

    stream = backend(EarlyTransport()).transcribe(source())
    await anext(stream)
    await stream.aclose()
    assert closed.is_set()


@pytest.mark.asyncio
async def test_invalid_transcript_order_or_response_is_explicit():
    for response in [object(), SttResponse((SttResult("interim", False), SttResult("final", True))), SttResponse((SttResult("hello", "true"),))]:
        with pytest.raises(SpeechProviderError, match="invalid_response"):
            _ = [r async for r in backend(Transport([response])).transcribe(packets(packet()))]


@pytest.mark.asyncio
@pytest.mark.parametrize("name,code", [("UNAUTHENTICATED", "unauthenticated"), ("PERMISSION_DENIED", "permission_denied"), ("RESOURCE_EXHAUSTED", "quota_exhausted"), ("DEADLINE_EXCEEDED", "timeout")])
async def test_grpc_status_mapping_without_error_text(name, code):
    class GrpcError(Exception):
        def code(self):
            return SimpleNamespace(name=name)

    class FailingClient:
        async def streaming_recognize(self, **kwargs):
            raise GrpcError("PRIVATE-CREDENTIAL")

    transport = GoogleSpeechV2GrpcTransport(FailingClient(), request_factory=lambda **kw: kw)
    with pytest.raises(SpeechProviderError) as caught:
        _ = [r async for r in backend(transport).transcribe(packets(packet()))]
    assert caught.value.code == code and "PRIVATE" not in str(caught.value)


@pytest.mark.asyncio
async def test_real_google_sdk_request_and_async_client_seam_without_network(monkeypatch):
    import google.auth
    import grpc
    import grpc.aio
    from google.auth.credentials import AnonymousCredentials
    from google.cloud.speech_v2 import SpeechAsyncClient
    from google.cloud.speech_v2.services.speech.transports.grpc_asyncio import SpeechGrpcAsyncIOTransport
    from google.cloud.speech_v2.types import cloud_speech

    def forbidden(*args, **kwargs):
        raise AssertionError("Neither ADC nor a network channel may be opened")

    monkeypatch.setattr(google.auth, "default", forbidden)
    monkeypatch.setattr(grpc.aio, "secure_channel", forbidden)
    monkeypatch.setattr(grpc.aio, "insecure_channel", forbidden)

    class NoNetworkChannel:
        def __init__(self):
            self._unary_unary_interceptors = []
            self.closed = False

        def unary_unary(self, *args, **kwargs):
            return forbidden

        def stream_stream(self, *args, **kwargs):
            return forbidden

        async def close(self):
            self.closed = True

    channel = NoNetworkChannel()
    channel_args = {}
    tls_credential = grpc.ssl_channel_credentials(root_certificates=_synthetic_root_ca())
    transport = SpeechGrpcAsyncIOTransport(
        credentials=AnonymousCredentials(), host="us-speech.googleapis.com",
        ssl_channel_credentials=tls_credential,
        channel=lambda *args, **kwargs: (channel_args.update(kwargs) or channel),
    )
    assert channel_args["ssl_credentials"] is tls_credential
    client = SpeechAsyncClient(transport=transport)
    requests, options = [], {}

    class RealResponseRpc(Rpc):
        async def responses(self):
            yield cloud_speech.StreamingRecognizeResponse(results=[{
                "alternatives": [{"transcript": "你好"}], "is_final": True,
            }])

    rpc = RealResponseRpc()

    async def intercepted(request_iterator, **kwargs):
        requests.extend([request async for request in request_iterator])
        options.update(kwargs)
        return rpc

    # Replace the network boundary, retaining real SDK client dispatch/protobufs.
    transport._wrapped_methods[transport.streaming_recognize] = intercepted
    selected = GoogleSpeechV2GrpcTransport(client, request_factory=cloud_speech.StreamingRecognizeRequest)
    result = [revision async for revision in backend(selected).transcribe(packets(packet()))]
    assert result[0].text == "你好" and result[0].is_final
    assert isinstance(requests[0], cloud_speech.StreamingRecognizeRequest)
    assert requests[0].streaming_config.config.explicit_decoding_config.encoding == cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16
    assert requests[0].streaming_config.streaming_features.interim_results
    assert requests[1].audio == packet().pcm and not requests[1].recognizer
    assert options["retry"] is None and rpc.cancelled
    await client.transport.close()
    assert channel.closed


def _synthetic_root_ca() -> bytes:
    """Ephemeral in-test CA fixture; never installed or used outside loopback tests."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-test-root")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM)


@pytest.mark.asyncio
async def test_stt_interim_tail_is_not_successful_completion():
    transport = Transport([SttResponse((SttResult("未完成", False),))])
    stream = backend(transport).transcribe(packets(packet()))
    assert not (await anext(stream)).is_final
    with pytest.raises(SpeechProviderError, match="incomplete_stream"):
        await anext(stream)
    assert transport.closed


@pytest.mark.asyncio
async def test_stt_suppressed_transport_cancellation_cannot_emit_late_transcript():
    class Uncooperative(Transport):
        async def stream(self, requests, **kwargs):
            try:
                self.entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    yield SttResponse((SttResult("迟到", True),))
            finally:
                self.closed = True

    transport = Uncooperative([])
    stream = backend(transport).transcribe(packets(packet()))
    task = asyncio.create_task(anext(stream))
    await asyncio.wait_for(transport.entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.closed


@pytest.mark.asyncio
async def test_voice_factory_passes_explicit_tls_roots_into_sdk_transport(monkeypatch):
    import google.cloud.speech_v2
    from google.cloud.speech_v2.services.speech import transports
    from mira.bootstrap.providers import create_google_voice
    from mira.config.service_settings import SpeechSettings

    observed = {}
    tls_credential = object()

    class FakeGrpcTransport:
        def __init__(self, **kwargs):
            observed["transport"] = kwargs
            self._kwargs = kwargs
            self._unary_unary_interceptors = []

        async def close(self):
            observed["transport_closed"] = True

    class FakeSpeechClient:
        def __init__(self, *, transport=None, **kwargs):
            observed["client_transport"] = transport
            observed["client_kwargs"] = kwargs
            self.transport = transport

    class FakeHttpClient:
        async def aclose(self):
            observed["http_closed"] = True

    async def token_provider():
        raise AssertionError("Offline composition must not request tokens")

    monkeypatch.setattr(transports.grpc_asyncio, "SpeechGrpcAsyncIOTransport", FakeGrpcTransport)
    monkeypatch.setattr(google.cloud.speech_v2, "SpeechAsyncClient", FakeSpeechClient)
    voice = create_google_voice(
        SpeechSettings(project_id="mira-test", tts_voice="Kore"), credentials=object(),
        token_provider=token_provider, authorized=True, http_client=FakeHttpClient(),
        stt_ssl_channel_credentials=tls_credential,
    )
    assert observed["transport"]["host"] == "us-speech.googleapis.com"
    assert observed["transport"]["ssl_channel_credentials"] is tls_credential
    assert observed["client_transport"] is not None
    await voice.close()
    assert observed["transport_closed"] is True
