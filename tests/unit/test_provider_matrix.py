"""ENV-02: the approved MVP provider matrix is explicit and fail-closed."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from mira.config.loader import load_settings
from mira.config.service_settings import SpeechSettings
from tools.api_environment import inspect_services

ROOT = Path(__file__).resolve().parents[2]


def load_dev(**overrides):
    return load_settings(root=ROOT, environ={"MIRA_PROFILE": "development"}, overrides=overrides)


def test_development_profile_freezes_openai_family_and_google_speech_matrix():
    settings = load_dev()
    assert settings.services.routes.text == "codex_native"
    assert settings.services.routes.image == "codex_native"
    assert settings.services.routes.vision == "codex_native"
    assert settings.services.speech.asr_provider == "google_cloud"
    assert settings.services.speech.tts_provider == "google_cloud"


def test_review_route_remains_jev_and_is_not_silently_folded_into_main_llm():
    report = inspect_services(load_dev())
    assert report["capabilities"]["review"]["route"] == "jev"


def test_speech_report_comes_from_typed_provider_fields():
    report = inspect_services(load_dev())
    assert report["capabilities"]["asr"]["route"] == "google_cloud_stt_v2"
    assert report["capabilities"]["tts"]["route"] == "google_gemini_enterprise_tts"


def test_google_speech_provider_is_currently_intentional_not_arbitrary_string():
    with pytest.raises(ValidationError):
        SpeechSettings(asr_provider="other")
    with pytest.raises(ValidationError):
        SpeechSettings(tts_provider="other")


def test_openai_api_stays_explicit_alternative_not_automatic_fallback():
    settings = load_dev(services={"routes": {"text": "openai_api", "image": "openai_api", "vision": "openai_api"}})
    report = inspect_services(settings)
    assert report["capabilities"]["text"]["route"] == "openai_api"
    assert report["capabilities"]["image"]["route"] == "openai_api"
    assert report["capabilities"]["vision"]["route"] == "openai_api"
    assert not settings.providers.allow_paid_api
    assert report["live_ready"] is False


def test_gemini_38_tts_has_exact_current_endpoint_model_and_global_location():
    speech = load_dev().services.speech
    assert speech.tts_endpoint == "aiplatform.googleapis.com"
    assert speech.tts_model == "gemini-3.8-flash-tts"
    assert speech.tts_location == "global"
    assert speech.tts_voice is None


@pytest.mark.parametrize("changes", [
    {"tts_endpoint": "texttospeech.googleapis.com"},
    {"tts_model": "gemini-2.5-flash-preview-tts"},
    {"tts_location": "us-central1"},
])
def test_exact_tts_target_cannot_silently_use_a_legacy_endpoint_or_model(changes):
    with pytest.raises(ValidationError):
        SpeechSettings(**changes)


def test_tts_model_location_and_style_use_existing_loader_entry():
    settings = load_settings(root=ROOT, environ={
        "MIRA_SERVICES__SPEECH__TTS_MODEL": "gemini-3.8-flash-tts",
        "MIRA_SERVICES__SPEECH__TTS_LOCATION": "global",
        "MIRA_SERVICES__SPEECH__TTS_STYLE": "calm",
        "MIRA_SERVICES__SPEECH__TTS_VOICE": "Kore",
    })
    assert settings.services.speech.tts_style == "calm"
    assert settings.services.speech.tts_voice == "Kore"


def test_voice_preparation_does_not_require_separate_quota_project_or_claim_access():
    report = inspect_services(load_dev(services={"speech": {
        "project_id": "mira-example", "tts_voice": "Kore",
    }}))
    assert report["capabilities"]["asr"]["fields_complete"]
    tts = report["capabilities"]["tts"]
    assert tts["fields_complete"]
    assert tts["route"] == "google_gemini_enterprise_tts"
    assert tts["model"] == "gemini-3.8-flash-tts"
    assert tts["location"] == "global"
    assert tts["release_stage"] == "preview"
    assert tts["account_access"] == "not_run"
    assert report["live_ready"] is False
