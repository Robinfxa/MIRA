import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest
from pydantic import SecretStr

from mira.bootstrap.container import build_container
from mira.bootstrap.providers import create_providers
from mira.config.loader import ConfigurationError, load_settings
from mira.config.settings import ProviderSettings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def isolated_cli_install(tmp_path_factory):
    """Exercise both Python entrypoints without touching the checkout's private .env."""
    base = tmp_path_factory.mktemp("mira-cli-entrypoints")
    installed = base / "installed"
    shutil.copytree(ROOT / "apps/api/src/mira", installed / "mira",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "config", installed / "config",
                    ignore=shutil.ignore_patterns(".env", ".env.*"))

    hook = base / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import uvicorn\n"
        "def _record_start(*args, **kwargs):\n"
        "    marker = os.environ.get('TEST_UVICORN_MARKER')\n"
        "    if marker:\n"
        "        Path(marker).write_text('called', encoding='utf-8')\n"
        "uvicorn.run = _record_start\n",
        encoding="utf-8",
    )

    console = base / "bin" / "mira"
    console.parent.mkdir()
    # This is the setuptools project.scripts entrypoint call shape: sys.exit(main()).
    console.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "from mira.__main__ import main\n"
        "if __name__ == '__main__':\n"
        "    sys.exit(main())\n",
        encoding="utf-8",
    )
    console.chmod(0o755)
    return {"base": base, "installed": installed, "hook": hook, "console": console}


def _invoke_isolated_cli(cli, entrypoint, variables):
    marker = cli["base"] / "uvicorn-called"
    marker.unlink(missing_ok=True)
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(cli["base"] / "home"),
        "PYTHONPATH": os.pathsep.join((str(cli["installed"]), str(cli["hook"]))),
        "MIRA_DIAGNOSTICS__ENABLED": "false",
        "TEST_UVICORN_MARKER": str(marker),
        "OPENAI_API_KEY": "SYNTHETIC_BEARER_SAMPLE_XYZ",
        "TYPESAFE_API_KEY": "SYNTHETIC_API_KEY_SAMPLE_QRS",
        **variables,
    }
    Path(environment["HOME"]).mkdir(exist_ok=True)
    command = ([sys.executable, "-m", "mira"] if entrypoint == "module"
               else [str(cli["console"])])
    result = subprocess.run(command, cwd=cli["base"], env=environment, capture_output=True, text=True,
                            timeout=15, check=False)
    return result, marker


@pytest.mark.parametrize("entrypoint", ["module", "console"])
@pytest.mark.parametrize("variables,category,field,untrusted", [
    ({"MIRA_PROFILE": "notthere-secretmarker"}, "missing_configuration_file", None,
     "notthere-secretmarker"),
    ({"MIRA_HTTP__PORT": "bad-port-SYNTHETIC_VALUE_MARKER"}, "invalid_fields", "http.port",
     "bad-port-SYNTHETIC_VALUE_MARKER"),
])
def test_cli_configuration_errors_are_safe_and_do_not_start_server(
        isolated_cli_install, entrypoint, variables, category, field, untrusted):
    result, marker = _invoke_isolated_cli(isolated_cli_install, entrypoint, variables)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    assert "ConfigurationError" not in result.stderr
    assert untrusted not in result.stderr
    assert "SYNTHETIC_BEARER_SAMPLE_XYZ" not in result.stderr
    assert "SYNTHETIC_API_KEY_SAMPLE_QRS" not in result.stderr
    diagnostic = json.loads(result.stderr)
    assert diagnostic["code"] == "configuration_error"
    assert uuid.UUID(diagnostic["diagnostic_id"])
    assert diagnostic["category"] == category
    assert diagnostic["fields"] == ([field] if field else [])
    assert "config/profiles" in diagnostic["recovery"]
    assert "docs/development/API_ENV.md" in diagnostic["recovery"]
    assert not marker.exists()


@pytest.mark.parametrize("entrypoint", ["module", "console"])
def test_cli_valid_defaults_continue_to_uvicorn(isolated_cli_install, entrypoint):
    result, marker = _invoke_isolated_cli(isolated_cli_install, entrypoint, {})

    assert result.returncode == 0
    assert result.stderr == ""
    assert marker.read_text(encoding="utf-8") == "called"


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
