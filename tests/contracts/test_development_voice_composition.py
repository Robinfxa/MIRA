"""Synthetic bounded-composition contract; never uses Google auth or transports."""
import asyncio

import pytest

from mira.adapters.speech.errors import SpeechProviderError
from mira.adapters.speech.google_gemini_tts import GeminiTtsOptions
from mira.adapters.speech.google_stt_v2 import SttOptions
from mira.application.ports.media import AudioPacket, TranscriptRevision
from mira.bootstrap import development_voice
from mira.bootstrap.providers import GoogleVoiceProviders
from mira.config.loader import ConfigurationError
from mira.config.service_settings import SpeechSettings


def settings(**updates):
    values = {"project_id": "synthetic-project", "tts_voice": "Kore"}
    values.update(updates)
    return SpeechSettings(**values)


def pcm(stream="out-1", first=0, rate=24000, samples=24):
    return AudioPacket(stream, first, rate, b"\x00\x00" * samples)


def input_pcm(stream="in-1", first=0, rate=16000, samples=16):
    return AudioPacket(stream, first, rate, b"\x00\x00" * samples)


def limits(**updates):
    return development_voice.DevelopmentVoiceLimits(
        tts_request_limit=1, stt_request_limit=1,
        tts_max_audio_seconds=0.001, stt_max_input_seconds=0.001,
        **updates,
    )


async def token_provider():
    return "synthetic-token"


class FakeSynthesis:
    def __init__(self, producer):
        self.producer = producer
        self.calls = 0
        self.options = GeminiTtsOptions(project_id="synthetic-project", voice="Kore")

    def synthesize(self, approved_text, stream_id):
        self.calls += 1
        return self.producer(approved_text, stream_id)


class FakeRecognition:
    def __init__(self, producer):
        self.producer = producer
        self.calls = 0
        self.seen = []
        self.options = SttOptions(project_id="synthetic-project")

    def transcribe(self, packets):
        self.calls += 1
        return self.producer(packets, self.seen)


class FakeBundle:
    def __init__(self, synthesis, recognition):
        self.closed = 0

        async def close():
            self.closed += 1

        self.bundle = GoogleVoiceProviders(recognition, synthesis, close)


def make_factory(monkeypatch, *, voice_settings=None, voice_limits=None,
                 http_client=None, stt_ssl_channel_credentials=None):
    synthesis = FakeSynthesis(lambda _text, stream_id: _one(pcm(stream=stream_id)))
    recognition = FakeRecognition(_echo_transcript)
    bundle = FakeBundle(synthesis, recognition)
    calls = []

    def fake_google_voice(actual_settings, **kwargs):
        calls.append((actual_settings, kwargs))
        return bundle.bundle

    monkeypatch.setattr(development_voice, "create_google_voice", fake_google_voice)
    factory = development_voice.create_development_voice_factory(
        speech_settings=voice_settings if voice_settings is not None else settings(),
        credentials=object(), token_provider=token_provider, authorized=True,
        limits=voice_limits if voice_limits is not None else limits(),
        http_client=http_client,
        stt_ssl_channel_credentials=stt_ssl_channel_credentials,
    )
    return factory, calls, bundle, synthesis, recognition


async def _one(packet):
    yield packet


async def _echo_transcript(packets, seen):
    async for packet in packets:
        seen.append(packet)
        yield TranscriptRevision(packet.stream_id, len(seen), "synthetic", True)


@pytest.mark.asyncio
async def test_factory_is_opt_in_delayed_exact_and_single_use(monkeypatch):
    factory, calls, bundle, _, _ = make_factory(monkeypatch)
    assert calls == []  # constructing the closure never composes a provider

    voice = factory()
    assert len(calls) == 1
    selected, injected = calls[0]
    assert selected is not None
    assert injected["authorized"] is True
    assert injected["credentials"] is not None
    assert injected["token_provider"] is token_provider
    assert injected["http_client"] is None
    assert injected["stt_max_stream_seconds"] == 0.001
    assert injected["tts_max_audio_samples"] == 24
    assert selected.stt_model == "chirp_3"
    assert selected.tts_model == "gemini-3.8-flash-tts"
    assert selected.tts_voice == "Kore" and selected.tts_location == "global"
    with pytest.raises(ConfigurationError, match="once"):
        factory()
    await voice.close()
    await voice.close()
    assert bundle.closed == 1


@pytest.mark.asyncio
async def test_approved_custom_transport_inputs_are_passed_opaque(monkeypatch):
    client, tls = object(), object()
    factory, calls, _, _, _ = make_factory(
        monkeypatch, http_client=client, stt_ssl_channel_credentials=tls,
    )
    factory()
    assert calls[0][1]["http_client"] is client
    assert calls[0][1]["stt_ssl_channel_credentials"] is tls


@pytest.mark.parametrize("change,match", [
    ({"authorized": False}, "authorization"),
    ({"credentials": None}, "credentials"),
    ({"token_provider": None}, "token provider"),
    ({"speech_settings": None}, "settings"),
    ({"speech_settings": settings(project_id=None)}, "project config"),
    ({"limits": None}, "limits"),
])
def test_missing_or_denied_inputs_fail_before_provider_construction(monkeypatch, change, match):
    calls = []
    monkeypatch.setattr(development_voice, "create_google_voice",
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    values = {
        "speech_settings": settings(), "credentials": object(),
        "token_provider": token_provider, "authorized": True, "limits": limits(),
    }
    values.update(change)
    with pytest.raises(ConfigurationError, match=match):
        development_voice.create_development_voice_factory(**values)
    assert calls == []


@pytest.mark.parametrize("updates", [
    {"stt_model": "chirp_2"}, {"tts_voice": "Aoede"}, {"tts_location": "us"},
])
def test_nonselected_model_voice_or_region_is_rejected(monkeypatch, updates):
    calls = []
    monkeypatch.setattr(development_voice, "create_google_voice",
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    with pytest.raises(ConfigurationError, match="fixed Google voice selection"):
        development_voice.create_development_voice_factory(
            # model_copy(update=...) deliberately bypasses pydantic re-validation so
            # the composition's own fixed-selection guard is directly exercised.
            speech_settings=settings().model_copy(update=updates), credentials=object(),
            token_provider=token_provider, authorized=True, limits=limits(),
        )
    assert calls == []


def test_limit_configuration_is_typed_finite_and_hard_bounded():
    for kwargs in (
        {"tts_request_limit": True}, {"stt_request_limit": 9},
        {"tts_max_audio_seconds": float("inf")}, {"stt_max_input_seconds": 31},
        {"tts_max_audio_seconds": 0},
    ):
        fields = dict(tts_request_limit=1, stt_request_limit=1,
                      tts_max_audio_seconds=1.0, stt_max_input_seconds=1.0)
        fields.update(kwargs)
        with pytest.raises(ConfigurationError):
            development_voice.DevelopmentVoiceLimits(**fields)


def test_application_voice_profile_accepts_bounded_continuous_stream_limits_only():
    application = development_voice.DevelopmentVoiceLimits(
        tts_request_limit=100, stt_request_limit=100,
        tts_max_audio_seconds=30, stt_max_input_seconds=290,
        usage_profile="application",
    )
    assert application.usage_profile.value == "application"
    assert application.tts_max_samples == 720_000
    assert application.stt_max_input_seconds == 290
    for updates in (
        {"tts_request_limit": 101}, {"stt_request_limit": 0},
        {"tts_max_audio_seconds": 30.01}, {"stt_max_input_seconds": 290.01},
        {"tts_request_limit": True}, {"stt_max_input_seconds": float("nan")},
        {"usage_profile": "unlimited"},
    ):
        values = dict(tts_request_limit=1, stt_request_limit=1,
                      tts_max_audio_seconds=30, stt_max_input_seconds=120,
                      usage_profile="application")
        values.update(updates)
        with pytest.raises(ConfigurationError):
            development_voice.DevelopmentVoiceLimits(**values)


@pytest.mark.asyncio
async def test_first_valid_pcm_is_forwarded_without_lookahead(monkeypatch):
    gate, second_requested = asyncio.Event(), asyncio.Event()
    state = {"yielded": 0}

    async def producer(_text, stream_id):
        state["yielded"] += 1
        yield pcm(stream=stream_id)
        second_requested.set()
        await gate.wait()
        state["yielded"] += 1
        yield pcm(stream=stream_id, first=24)

    synthesis = FakeSynthesis(producer)
    factory, _, _, _, _ = make_factory(monkeypatch)
    # Replace only the fake builder's returned port, never the Google builder itself.
    monkeypatch.setattr(development_voice, "create_google_voice", lambda *a, **k:
                        GoogleVoiceProviders(FakeRecognition(_echo_transcript), synthesis,
                                             _noop_close))
    voice = factory()
    stream = voice.speech_synthesis.synthesize("合成测试", "out-1")
    first = await anext(stream)
    assert first == pcm()
    assert state["yielded"] == 1
    pending = asyncio.create_task(anext(stream))
    await asyncio.wait_for(second_requested.wait(), timeout=1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    gate.set()
    with pytest.raises(SpeechProviderError, match="output_limit"):
        await anext(voice.speech_synthesis.synthesize("第二次", "out-2"))
    assert state["yielded"] == 1  # cancelled attempts are not refunded
    await voice.close()


async def _noop_close():
    return None


@pytest.mark.asyncio
async def test_tts_duration_limit_blocks_over_budget_packet(monkeypatch):
    synthesis = FakeSynthesis(lambda _text, stream_id: _two(
        pcm(stream=stream_id), pcm(stream=stream_id, first=24, samples=1)))
    factory, _, _, _, recognition = make_factory(monkeypatch)
    monkeypatch.setattr(development_voice, "create_google_voice", lambda *a, **k:
                        GoogleVoiceProviders(recognition, synthesis, _noop_close))
    voice = factory()
    stream = voice.speech_synthesis.synthesize("合成测试", "out-1")
    assert await anext(stream) == pcm()
    with pytest.raises(SpeechProviderError, match="output_limit"):
        await anext(stream)
    await voice.close()


async def _two(first, second):
    yield first
    yield second


@pytest.mark.asyncio
async def test_invalid_tts_pcm_never_reaches_consumer(monkeypatch):
    synthesis = FakeSynthesis(lambda _text, stream_id: _one(
        AudioPacket(stream_id, 0, 24000, b"\x01")))
    factory, _, _, _, recognition = make_factory(monkeypatch)
    monkeypatch.setattr(development_voice, "create_google_voice", lambda *a, **k:
                        GoogleVoiceProviders(recognition, synthesis, _noop_close))
    voice = factory()
    with pytest.raises(SpeechProviderError, match="invalid_audio"):
        await anext(voice.speech_synthesis.synthesize("合成测试", "out-1"))
    await voice.close()


@pytest.mark.asyncio
async def test_stt_empty_input_does_not_reserve_and_cancelled_attempt_is_not_refunded(monkeypatch):
    released = asyncio.Event()
    recognition = FakeRecognition(_blocking_transcript(released))
    factory, _, _, synthesis, _ = make_factory(monkeypatch)
    monkeypatch.setattr(development_voice, "create_google_voice", lambda *a, **k:
                        GoogleVoiceProviders(recognition, synthesis, _noop_close))
    voice = factory()
    assert [item async for item in voice.speech_recognition.transcribe(_empty())] == []
    assert recognition.calls == 0

    stream = voice.speech_recognition.transcribe(_one(input_pcm()))
    assert (await anext(stream)).text == "synthetic"
    await stream.aclose()
    with pytest.raises(SpeechProviderError, match="input_limit"):
        await anext(voice.speech_recognition.transcribe(_one(input_pcm())))
    assert recognition.calls == 1
    released.set()
    await voice.close()


def _blocking_transcript(released):
    async def produce(packets, seen):
        first = await anext(packets)
        seen.append(first)
        yield TranscriptRevision(first.stream_id, 1, "synthetic", True)
        await released.wait()
    return produce


async def _empty():
    if False:
        yield None


@pytest.mark.asyncio
async def test_stt_duration_ceiling_rejects_extra_pcm_before_forwarding(monkeypatch):
    recognition = FakeRecognition(_drain_input)
    factory, _, _, synthesis, _ = make_factory(monkeypatch)
    monkeypatch.setattr(development_voice, "create_google_voice", lambda *a, **k:
                        GoogleVoiceProviders(recognition, synthesis, _noop_close))
    voice = factory()

    async def source():
        yield input_pcm(samples=16)  # exactly 1 ms at 16 kHz
        yield input_pcm(first=16, samples=1)

    with pytest.raises(SpeechProviderError, match="input_limit"):
        _ = [item async for item in voice.speech_recognition.transcribe(source())]
    assert len(recognition.seen) == 1
    assert len(recognition.seen[0].pcm) == 32
    await voice.close()


@pytest.mark.asyncio
async def test_concurrent_tts_attempts_cannot_oversubscribe_one_instance(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def producer(_text, stream_id):
        entered.set()
        await release.wait()
        yield pcm(stream=stream_id)

    synthesis = FakeSynthesis(producer)
    factory, _, _, _, recognition = make_factory(monkeypatch)
    monkeypatch.setattr(development_voice, "create_google_voice", lambda *a, **k:
                        GoogleVoiceProviders(recognition, synthesis, _noop_close))
    voice = factory()
    first_stream = voice.speech_synthesis.synthesize("第一句", "out-1")
    first_task = asyncio.create_task(anext(first_stream))
    await asyncio.wait_for(entered.wait(), timeout=1)
    with pytest.raises(SpeechProviderError, match="output_limit"):
        await anext(voice.speech_synthesis.synthesize("第二句", "out-2"))
    assert synthesis.calls == 1
    release.set()
    assert (await first_task).stream_id == "out-1"
    await first_stream.aclose()
    await voice.close()


async def _drain_input(packets, seen):
    async for packet in packets:
        seen.append(packet)
        yield TranscriptRevision(packet.stream_id, len(seen), "synthetic", True)

class FakeContinuousRecognition:
    def __init__(self, producer):
        self.producer = producer
        self.calls = 0
        self.max_stream_seconds = 30
        self.endpoint_mode = "google_vad_offsets"

    def transcribe_events(self, packets):
        self.calls += 1
        return self.producer(packets)


async def _one_final_event(packets):
    from mira.application.ports.continuous_speech import ContinuousTranscriptResult

    packet = await anext(packets)
    yield ContinuousTranscriptResult("synthetic final", True, packet.first_sample + len(packet.pcm) // 2)


@pytest.mark.asyncio
async def test_ptt_and_continuous_share_one_irreversible_stt_budget(monkeypatch):
    recognition = FakeRecognition(_echo_transcript)
    continuous = FakeContinuousRecognition(_one_final_event)
    synthesis = FakeSynthesis(lambda _text, stream_id: _one(pcm(stream=stream_id)))
    monkeypatch.setattr(development_voice, "create_google_voice", lambda *a, **k:
        GoogleVoiceProviders(recognition, synthesis, _noop_close,
                             continuous_speech_recognition=continuous))
    factory = development_voice.create_development_voice_factory(
        speech_settings=settings(), credentials=object(), token_provider=token_provider,
        authorized=True, limits=limits())
    voice = factory()
    # First PTT stream consumes the sole shared attempt.
    ptt = voice.speech_recognition.transcribe(_one(input_pcm()))
    assert (await anext(ptt)).text == "synthetic"
    await ptt.aclose()
    assert voice.stt_request_budget.snapshot().used == 1
    # The continuous stream uses the same budget and cannot dispatch a second STT request.
    with pytest.raises(SpeechProviderError, match="input_limit"):
        await anext(voice.continuous_speech_recognition.transcribe_events(
            _one(input_pcm(stream="lease-one"))))
    assert recognition.calls == 1
    assert continuous.calls == 0
    assert voice.stt_request_budget.snapshot().remaining == 0
    await voice.close()


@pytest.mark.asyncio
async def test_continuous_first_pcm_reserves_shared_stt_budget_before_ptt(monkeypatch):
    recognition = FakeRecognition(_echo_transcript)
    continuous = FakeContinuousRecognition(_one_final_event)
    synthesis = FakeSynthesis(lambda _text, stream_id: _one(pcm(stream=stream_id)))
    monkeypatch.setattr(development_voice, "create_google_voice", lambda *a, **k:
        GoogleVoiceProviders(recognition, synthesis, _noop_close,
                             continuous_speech_recognition=continuous))
    voice = development_voice.create_development_voice_factory(
        speech_settings=settings(), credentials=object(), token_provider=token_provider,
        authorized=True, limits=limits())()
    stream = voice.continuous_speech_recognition.transcribe_events(_one(input_pcm(stream="lease-two")))
    event = await anext(stream)
    assert isinstance(event, development_voice.ContinuousRecognitionStarted)
    assert (event.requests_used, event.requests_remaining) == (1, 0)
    event = await anext(stream)
    assert event.text == "synthetic final"
    await stream.aclose()
    assert voice.stt_request_budget.snapshot().used == 1
    with pytest.raises(SpeechProviderError, match="input_limit"):
        await anext(voice.speech_recognition.transcribe(_one(input_pcm(stream="ptt-two"))))
    assert continuous.calls == 1
    assert recognition.calls == 0
    await voice.close()


@pytest.mark.asyncio
async def test_concurrent_ptt_and_continuous_contend_for_same_atomic_limit_one(monkeypatch):
    recognition = FakeRecognition(_echo_transcript)
    continuous = FakeContinuousRecognition(_one_final_event)
    synthesis = FakeSynthesis(lambda _text, stream_id: _one(pcm(stream=stream_id)))
    monkeypatch.setattr(development_voice, "create_google_voice", lambda *a, **k:
        GoogleVoiceProviders(recognition, synthesis, _noop_close,
                             continuous_speech_recognition=continuous))
    voice = development_voice.create_development_voice_factory(
        speech_settings=settings(), credentials=object(), token_provider=token_provider,
        authorized=True, limits=limits())()

    async def run_ptt():
        try:
            return [value async for value in voice.speech_recognition.transcribe(
                _one(input_pcm(stream="ptt-concurrent")))]
        except SpeechProviderError as error:
            return error.code.value

    async def run_continuous():
        try:
            return [value async for value in voice.continuous_speech_recognition.transcribe_events(
                _one(input_pcm(stream="lease-concurrent")))]
        except SpeechProviderError as error:
            return error.code.value

    results = await asyncio.gather(run_ptt(), run_continuous())
    successes = sum(isinstance(value, list) for value in results)
    failures = [value for value in results if not isinstance(value, list)]
    assert successes == 1
    assert failures == ["input_limit"]
    assert voice.stt_request_budget.snapshot().used == 1
    assert recognition.calls + continuous.calls == 1
    await voice.close()


@pytest.mark.asyncio
async def test_invalid_continuous_pcm_does_not_reserve_shared_stt_attempt(monkeypatch):
    recognition = FakeRecognition(_echo_transcript)
    continuous = FakeContinuousRecognition(_one_final_event)
    synthesis = FakeSynthesis(lambda _text, stream_id: _one(pcm(stream=stream_id)))
    monkeypatch.setattr(development_voice, "create_google_voice", lambda *a, **k:
        GoogleVoiceProviders(recognition, synthesis, _noop_close,
                             continuous_speech_recognition=continuous))
    voice = development_voice.create_development_voice_factory(
        speech_settings=settings(), credentials=object(), token_provider=token_provider,
        authorized=True, limits=limits())()
    bad = AudioPacket("lease-invalid", 1, 16_000, b"\0\0" * 20)
    with pytest.raises(SpeechProviderError, match="invalid_input"):
        await anext(voice.continuous_speech_recognition.transcribe_events(_one(bad)))
    assert voice.stt_request_budget.snapshot().used == 0
    ptt = voice.speech_recognition.transcribe(_one(input_pcm(stream="ptt-after-invalid")))
    assert (await anext(ptt)).text == "synthetic"
    assert voice.stt_request_budget.snapshot().used == 1
    await ptt.aclose()
    await voice.close()
