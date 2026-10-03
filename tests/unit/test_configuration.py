from pathlib import Path

import pytest
from pydantic import SecretStr

from mira.bootstrap.container import build_container
from mira.bootstrap.providers import create_providers
from mira.config.loader import ConfigurationError, load_settings
from mira.config.settings import ProviderSettings

ROOT = Path(__file__).resolve().parents[2]


def test_mock_without_dotenv_or_credentials():
    settings=load_settings(root=ROOT,environ={})
    assert settings.providers.generation == "mock"
    assert not settings.providers.allow_paid_api
    assert settings.providers.api_key is None


def test_precedence_is_defaults_profile_dotenv_environment_overrides(tmp_path):
    path=tmp_path/"local.env"
    path.write_text("MIRA_PROFILE=test\nMIRA_PROVIDERS__MOCK_DELAY_MS=12\n")
    settings=load_settings(root=ROOT,env_file=path,environ={"MIRA_PROVIDERS__MOCK_DELAY_MS":"30"},
                           overrides={"providers":{"mock_delay_ms":44}})
    assert settings.environment == "test" and settings.providers.mock_delay_ms == 44


def test_environment_overrides_dotenv(tmp_path):
    path=tmp_path/"local.env";path.write_text("MIRA_HTTP__PORT=8010\n")
    assert load_settings(root=ROOT,env_file=path,environ={"MIRA_HTTP__PORT":"8020"}).http.port == 8020


def test_unknown_env_fails_fast():
    with pytest.raises(ConfigurationError,match="Unknown"):
        load_settings(root=ROOT,environ={"MIRA_HTTP__POTR":"8000"})


def test_invalid_port_fails_without_echoing_input():
    with pytest.raises(ConfigurationError) as error:
        load_settings(root=ROOT,environ={"MIRA_HTTP__PORT":"DO-NOT-LOG"})
    assert "DO-NOT-LOG" not in str(error.value)


def test_invalid_bool_fails():
    with pytest.raises(ConfigurationError):
        load_settings(root=ROOT,environ={"MIRA_PROVIDERS__ALLOW_PAID_API":"sometimes"})


def test_profile_path_traversal_rejected():
    with pytest.raises(ConfigurationError,match="profile|PROFILE"):
        load_settings(root=ROOT,environ={"MIRA_PROFILE":"../../secret"})


def test_unknown_profile_rejected():
    with pytest.raises(ConfigurationError,match="Missing"):
        load_settings(root=ROOT,environ={"MIRA_PROFILE":"does-not-exist"})


def test_explicit_missing_dotenv_rejected(tmp_path):
    with pytest.raises(ConfigurationError,match="dotenv"):
        load_settings(root=ROOT,env_file=tmp_path/"missing",environ={})


def test_secret_repr_is_redacted():
    settings=load_settings(root=ROOT,environ={"MIRA_PROVIDERS__API_KEY":"test-not-a-real-key"})
    assert isinstance(settings.providers.api_key,SecretStr)
    assert "test-not-a-real-key" not in repr(settings)


@pytest.mark.parametrize("generation,review", [
    ("codex", "fixture"),
    ("api", "fixture"),
    ("mock", "jev"),
    ("mock", "api"),
], ids=["codex-generation", "api-generation", "jev-review", "api-review"])
def test_live_provider_factory_rejection_is_truthful_and_actionable(generation, review):
    with pytest.raises(ConfigurationError) as error:
        create_providers(ProviderSettings(generation=generation, review=review))

    assert str(error.value) == (
        "Live adapters exist, but this application factory does not yet compose them under "
        "verified explicit admission. Configured fields alone do not enable live startup. "
        "Run offline configuration checks and consult current service-setup documentation. "
        "No automatic Mock or paid-API fallback is used."
    )


def test_no_live_generation_with_fixture_review():
    with pytest.raises(ConfigurationError):
        create_providers(ProviderSettings(generation="api",review="fixture"))


def test_no_implicit_paid_fallback():
    with pytest.raises(ConfigurationError,match="paid"):
        create_providers(ProviderSettings(allow_paid_api=True))


def test_unknown_toml_field_rejected(tmp_path):
    (tmp_path/"config/profiles").mkdir(parents=True)
    (tmp_path/"config/defaults.toml").write_text("typo = true\n")
    (tmp_path/"config/profiles/mock.toml").write_text("")
    with pytest.raises(ConfigurationError): load_settings(root=tmp_path,environ={})


def test_toml_secrets_rejected(tmp_path):
    (tmp_path/"config/profiles").mkdir(parents=True)
    (tmp_path/"config/defaults.toml").write_text('[providers]\napi_key="not-real"')
    (tmp_path/"config/profiles/mock.toml").write_text("")
    with pytest.raises(ConfigurationError,match="Secrets"): load_settings(root=tmp_path,environ={})


def test_factory_is_instance_scoped(settings):
    first,second=build_container(settings),build_container(settings)
    assert first.sessions is not second.sessions
    assert first.journal is not second.journal


def test_external_bind_not_silently_enabled():
    with pytest.raises(ConfigurationError):
        load_settings(root=ROOT,environ={"MIRA_HTTP__HOST":"0.0.0.0"})


def test_dotenv_is_not_auto_discovered_or_mutated(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path/".env").write_text("MIRA_HTTP__PORT=8888\n")
    settings=load_settings(root=ROOT,environ={})
    assert settings.http.port==8000
