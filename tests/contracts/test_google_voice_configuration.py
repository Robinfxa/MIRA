"""Explicit voice configuration using synthetic settings and in-memory HTTP only."""
import base64
import json

import httpx
import pytest

from mira.adapters.speech.errors import SpeechProviderError
from mira.bootstrap import development_voice
from mira.config.loader import ConfigurationError
from mira.config.service_settings import SpeechSettings


def _settings(**updates):
    return SpeechSettings(project_id="synthetic-project", tts_voice="Kore").model_copy(
        update=updates,
    )


def _limits(profile="application"):
    return development_voice.DevelopmentVoiceLimits(
        tts_request_limit=1, stt_request_limit=1,
        tts_max_audio_seconds=1, stt_max_input_seconds=1,
        usage_profile=profile,
    )


async def _unused_token_provider():
    raise AssertionError("Configuration validation must never request a token")


@pytest.mark.parametrize("voice,language,style", [("Kore", "cmn-CN", "warm"),
    ("Gacrux", "cmn-CN", "warm"), ("Gacrux", "en-US", "warm"),
    ("Gacrux", "cmn-CN", "御姐音，语调轻快，爽朗自然，咬字清晰，亲切有活力，不刻意压低嗓音或拖慢语速。")])
@pytest.mark.asyncio
async def test_application_voice_reaches_actual_request_and_preserves_content(monkeypatch, voice, language, style):
    import google.cloud.speech_v2

    sdk_allocations, sent, tokens, closed = [], [], [], []

    class FakeSpeechClient:
        def __init__(self, **kwargs):
            sdk_allocations.append(kwargs)
            self.transport = self

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(google.cloud.speech_v2, "SpeechAsyncClient", FakeSpeechClient)

    async def synthetic_token_provider():
        tokens.append(True)
        return "synthetic-token"

    async def synthetic_response(request):
        sent.append(request)
        event = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{
            "inlineData": {"mimeType": "audio/L16;rate=24000;channels=1",
                           "data": base64.b64encode(b"\0\0").decode()},
        }]}}]}
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=("data: " + json.dumps(event) + "\n\n").encode())

    selected = _settings(tts_voice=voice, tts_style=style, tts_language_code=language)
    async with httpx.AsyncClient(transport=httpx.MockTransport(synthetic_response),
                                trust_env=False) as client:
        factory = development_voice.create_development_voice_factory(
            speech_settings=selected, credentials=object(),
            token_provider=synthetic_token_provider, authorized=True,
            limits=_limits(), http_client=client,
        )
        assert sdk_allocations == [] and sent == [] and tokens == []
        bundle = factory()
        assert len(sdk_allocations) == 1 and sent == [] and tokens == []
        packets = [packet async for packet in bundle.speech_synthesis.synthesize(
            "这是已获准的测试句。", "synthetic-out",
        )]
        assert len(packets) == 1
        with pytest.raises(SpeechProviderError, match="output_limit"):
            await anext(bundle.speech_synthesis.synthesize("不应发送。", "second"))
        await bundle.close()
    assert len(sent) == len(tokens) == len(closed) == 1
    body = json.loads(sent[0].content)
    assert str(sent[0].url) == (
        "https://aiplatform.googleapis.com/v1/projects/synthetic-project/locations/global/"
        "publishers/google/models/gemini-3.8-flash-tts:streamGenerateContent?alt=sse"
    )
    assert body["contents"] == [{"role": "user", "parts": [{
        "text": "这是已获准的测试句。", "speechMetadata": {"style": style},
    }]}]
    assert body["generationConfig"]["speechConfig"] == {"voiceConfig": {"voice": voice}}
    assert selected.tts_voice == voice
    assert selected.tts_language_code == language  # retained config; not applied to this route


@pytest.mark.parametrize("voice", [None, "unknown", "Aoede", "gacrux", ["Kore"]])
def test_application_rejects_unselected_voice_before_provider_allocation(monkeypatch, voice):
    allocations = []
    monkeypatch.setattr(development_voice, "create_google_voice",
                        lambda *args, **kwargs: allocations.append(True))
    with pytest.raises(ConfigurationError, match="voice selection"):
        development_voice.create_development_voice_factory(
            speech_settings=_settings(tts_voice=voice), credentials=object(),
            token_provider=_unused_token_provider, authorized=True, limits=_limits(),
        )
    assert allocations == []


def test_probe_remains_fixed_kore_and_no_voice_default_is_silently_changed(monkeypatch):
    allocations = []
    monkeypatch.setattr(development_voice, "create_google_voice",
                        lambda *args, **kwargs: allocations.append(True))
    selected = _settings()
    development_voice.create_development_voice_factory(
        speech_settings=selected, credentials=object(),
        token_provider=_unused_token_provider, authorized=True, limits=_limits("probe"),
    )
    assert selected.tts_voice == "Kore"
    assert SpeechSettings().tts_voice is None
    with pytest.raises(ConfigurationError, match="fixed Google voice selection"):
        development_voice.create_development_voice_factory(
            speech_settings=_settings(tts_voice="Gacrux"), credentials=object(),
            token_provider=_unused_token_provider, authorized=True, limits=_limits("probe"),
        )
    assert allocations == []


def test_application_voice_selection_does_not_grant_authorization(monkeypatch):
    allocations = []
    monkeypatch.setattr(development_voice, "create_google_voice",
                        lambda *args, **kwargs: allocations.append(True))
    with pytest.raises(ConfigurationError, match="authorization"):
        development_voice.create_development_voice_factory(
            speech_settings=_settings(tts_voice="Gacrux"), credentials=object(),
            token_provider=_unused_token_provider, authorized=False, limits=_limits(),
        )
    assert allocations == []


@pytest.mark.parametrize("voice", ["Kore", "Gacrux"])
def test_shared_settings_validator_is_inert_and_returns_exact_selection(monkeypatch, voice):
    import google.cloud.speech_v2

    allocations = []

    def forbidden(*args, **kwargs):
        allocations.append(True)
        raise AssertionError("Settings validation must not allocate a client")

    monkeypatch.setattr(google.cloud.speech_v2, "SpeechAsyncClient", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    selected = _settings(tts_voice=voice)
    assert development_voice.validate_development_voice_settings(
        selected, usage_profile="application",
    ) is selected
    assert allocations == []


@pytest.mark.parametrize("updates", [
    {"asr_provider": "other"}, {"tts_provider": "other"}, {"auth": "other"},
    {"tts_endpoint": "example.test"}, {"tts_model": "other"},
    {"tts_location": "us"}, {"stt_model": "chirp_2"}, {"project_id": None},
    {"tts_voice": "unknown"},
])
def test_shared_settings_validator_rejects_other_routes_and_selections(updates):
    with pytest.raises(ConfigurationError):
        development_voice.validate_development_voice_settings(
            _settings(**updates), usage_profile="application",
        )


def test_shared_settings_validator_retains_probe_and_profile_guards():
    with pytest.raises(ConfigurationError, match="fixed Google voice selection"):
        development_voice.validate_development_voice_settings(
            _settings(tts_voice="Gacrux"), usage_profile="probe",
        )
    with pytest.raises(ConfigurationError, match="usage_profile_invalid"):
        development_voice.validate_development_voice_settings(
            _settings(), usage_profile="unlimited",
        )
    with pytest.raises(ConfigurationError, match="typed speech settings"):
        development_voice.validate_development_voice_settings(None, usage_profile="application")


@pytest.mark.parametrize("voice", ["unknown", ["Kore"]])
@pytest.mark.asyncio
async def test_low_level_unknown_voice_rejects_before_sdk_and_http_allocation(monkeypatch, voice):
    import google.cloud.speech_v2
    from mira.bootstrap.providers import create_google_voice

    allocations = []

    def forbidden(*args, **kwargs):
        allocations.append(True)
        raise AssertionError("Invalid voice must reject before client construction")

    monkeypatch.setattr(google.cloud.speech_v2, "SpeechAsyncClient", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(ConfigurationError, match="adapter options"):
        create_google_voice(_settings(tts_voice=voice), credentials=object(),
                            token_provider=_unused_token_provider, authorized=True)
    assert allocations == []


def test_public_selected_google_preset_loads_without_enabling_calls():
    from pathlib import Path
    from mira.config.loader import load_settings
    root = Path(__file__).resolve().parents[2]
    settings = load_settings(root=root, env_file=root / '.env.development.example', environ={})
    assert settings.services.speech.tts_voice == 'Gacrux'
    assert settings.services.speech.tts_style == '御姐音，语调轻快，爽朗自然，咬字清晰，亲切有活力，不刻意压低嗓音或拖慢语速。'
    assert settings.services.speech.tts_model == 'gemini-3.8-flash-tts'
    assert settings.services.speech.tts_location == 'global'
    assert not settings.providers.allow_external_calls
    assert not settings.providers.allow_paid_api
