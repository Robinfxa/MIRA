"""ENV-01: service preparation does not secretly enable live application execution."""
import json
from pathlib import Path

import pytest

from mira.bootstrap.providers import create_providers
from mira.config.loader import ConfigurationError, load_settings

ROOT = Path(__file__).resolve().parents[2]


def load(values=None, **kwargs):
    return load_settings(root=ROOT, environ=values or {}, **kwargs)


def test_services_are_available_but_disabled_by_default():
    settings = load()
    assert getattr(settings, "services", None) is not None
    assert settings.services.routes.text == "codex_native"
    assert not settings.services.probe.allow_metadata
    assert settings.services.probe.max_requests == 0
    assert not settings.providers.allow_external_calls
    assert not settings.providers.allow_paid_api
    assert create_providers(settings.providers).generation is not None


def test_development_template_is_valid_and_keeps_runtime_mock():
    settings = load_settings(root=ROOT, env_file=ROOT / ".env.development.example", environ={})
    assert settings.providers.generation == "mock"
    assert settings.services.jev.model is None
    assert settings.services.speech.tts_voice is None


def test_separate_secrets_are_never_serialized_or_in_repr():
    values = {
        "MIRA_SERVICES__GATEWAY__API_KEY": "synthetic-gateway-token",
        "MIRA_SERVICES__OPENAI__API_KEY": "synthetic-openai-token",
        "MIRA_SERVICES__JEV__API_KEY": "synthetic-jev-token",
    }
    settings = load(values)
    output = repr(settings) + settings.model_dump_json()
    assert all(secret not in output for secret in values.values())
    assert settings.services.jev.api_key.get_secret_value() == "synthetic-jev-token"
    assert settings.services.openai.api_key.get_secret_value() == "synthetic-openai-token"


def test_standard_aliases_are_resolved_in_the_existing_loader():
    s = load({"OPENAI_API_KEY": "synthetic-openai-token", "TYPESAFE_API_KEY": "synthetic-jev-token",
              "GOOGLE_CLOUD_PROJECT": "mira-example", "GOOGLE_CLOUD_QUOTA_PROJECT": "mira-quota"})
    assert s.services.openai.api_key.get_secret_value() == "synthetic-openai-token"
    assert s.services.jev.api_key.get_secret_value() == "synthetic-jev-token"
    assert s.services.speech.project_id == "mira-example"
    assert s.services.speech.quota_project_id == "mira-quota"


def test_alias_and_canonical_conflict_is_not_silently_resolved():
    with pytest.raises(ConfigurationError) as error:
        load({"OPENAI_API_KEY": "synthetic-first", "MIRA_SERVICES__OPENAI__API_KEY": "synthetic-second"})
    assert "synthetic" not in str(error.value)


def test_environment_layer_beats_file_alias(tmp_path):
    path = tmp_path / "private.env"
    path.write_text("OPENAI_API_KEY=synthetic-old\n")
    s = load({"MIRA_SERVICES__OPENAI__API_KEY": "synthetic-new"}, env_file=path)
    assert s.services.openai.api_key.get_secret_value() == "synthetic-new"


def test_legacy_generic_key_is_not_reused_for_other_services():
    s = load({"MIRA_PROVIDERS__API_KEY": "synthetic-legacy"})
    assert s.services.openai.api_key is None and s.services.jev.api_key is None


@pytest.mark.parametrize("url", [
    "https://example.com/v1", "http://0.0.0.0:8317/v1", "http://127.0.0.1.evil.test:8317/v1",
    "http://user:pass@127.0.0.1:8317/v1", "http://127.0.0.1:8317/v1?key=secret",
    "http://127.0.0.1:8317/v1#fragment", "http://127.0.0.1:8317/backend-api",
    "http://localhost:8317/v1", "http://127.0.0.1:8317/v1/../private",
])
def test_gateway_accepts_only_explicit_numeric_loopback_and_v1(url):
    with pytest.raises(ConfigurationError):
        load({"MIRA_SERVICES__GATEWAY__BASE_URL": url})


@pytest.mark.parametrize("url", ["http://127.0.0.1:8317/v1", "http://[::1]:8317/v1/"])
def test_valid_gateway_urls(url):
    assert load({"MIRA_SERVICES__GATEWAY__BASE_URL": url}).services.gateway.base_url.rstrip("/") == url.rstrip("/")


def test_toml_cannot_hold_nested_service_credentials(tmp_path):
    (tmp_path / "config/profiles").mkdir(parents=True)
    (tmp_path / "config/defaults.toml").write_text('[services.jev]\napi_key="synthetic-private"\n')
    (tmp_path / "config/profiles/mock.toml").write_text("")
    with pytest.raises(ConfigurationError, match="Secrets") as error:
        load_settings(root=tmp_path, environ={})
    assert "synthetic-private" not in str(error.value)


@pytest.mark.parametrize("field,value", [
    ("JEV__API_KEY", "synthetic\r\ninjected"), ("GATEWAY__TEXT_MODEL", "bad\nmodel"),
    ("PROBE__MAX_REQUESTS", "1000"), ("ROUTES__TEXT", "auto"),
    ("OPENAI__BASE_URL", "https://not-openai.example/v1"),
])
def test_invalid_service_inputs_are_redacted(field, value):
    with pytest.raises(ConfigurationError) as error:
        load({f"MIRA_SERVICES__{field}": value})
    assert value not in str(error.value)


def test_speech_uses_separate_locale_and_region_fields():
    s = load({"MIRA_SERVICES__SPEECH__PROJECT_ID": "mira-example",
              "MIRA_SERVICES__SPEECH__STT_LOCATION": "eu"}).services.speech
    assert s.stt_language_code == "cmn-Hans-CN"
    assert s.tts_language_code == "cmn-CN"
    assert s.stt_endpoint == "eu-speech.googleapis.com"
    assert s.recognizer == "projects/mira-example/locations/eu/recognizers/_"


def test_preparation_never_enables_live_factory():
    settings = load({"MIRA_SERVICES__ROUTES__TEXT": "gateway", "MIRA_SERVICES__GATEWAY__TEXT_MODEL": "chosen-model"})
    assert settings.providers.generation == "mock"
    create_providers(settings.providers)
    with pytest.raises(ConfigurationError, match="verified explicit admission"):
        create_providers(settings.providers.model_copy(update={"generation": "codex"}))
