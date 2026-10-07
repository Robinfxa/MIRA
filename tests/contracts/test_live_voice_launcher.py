"""Explicit voice CLI contracts with synthetic auth and resources only."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import tools.live_voice as live_voice


ROOT = Path(__file__).resolve().parents[2]


def _external_temp_parent() -> Path:
    """Choose a system temp parent that stays outside the checkout."""
    repository = ROOT.resolve()
    candidates = (Path(tempfile.gettempdir()), Path("/tmp"), Path("/var/tmp"))
    for candidate in candidates:
        try:
            parent = candidate.resolve(strict=True)
        except OSError:
            continue
        if parent.is_dir() and parent != repository and repository not in parent.parents:
            return parent
    raise RuntimeError("No temporary directory outside the MIRA checkout is available")


@pytest.fixture
def private_tmp_path():
    """Own and clean synthetic private inputs outside any pytest basetemp."""
    with tempfile.TemporaryDirectory(prefix="mira-live-voice-test-",
                                     dir=_external_temp_parent()) as directory:
        yield Path(directory)


def _inputs(tmp_path: Path, *, speech: dict[str, str] | None = None,
            runtime_environment: dict[str, str] | None = None):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    env_file = private / "mira.env"
    env = {
        "MIRA_SERVICES__JEV__MODEL": "jev-1.13.0",
        "MIRA_SERVICES__JEV__API_KEY": "synthetic-jev-key",
        "MIRA_SERVICES__SPEECH__PROJECT_ID": "synthetic-project",
        "MIRA_SERVICES__SPEECH__TTS_VOICE": "Kore",
    }
    env.update(speech or {})
    env_file.write_text("".join(f"{key}={value}\n" for key, value in env.items()), encoding="utf-8")
    env_file.chmod(0o600)

    admission_file = private / "admission.json"
    admission = {
        "authorized": True,
        "route_kind": "public",
        "runtime": {
            "executable": "/synthetic/codex", "codex_home": "/synthetic/home",
            "runtime_cwd": "/synthetic/run", "environment": runtime_environment or {},
            "expected_config_sha256": "a" * 64,
            "policy_environment_confirmed": True, "development_context": None,
        },
        "limits": {
            "codex_requests": 1, "session_turns": 1,
            "input_jev_requests": 1, "output_jev_requests": 1,
            "input_jev_timeout_seconds": 10, "output_jev_timeout_seconds": 10,
        },
    }
    admission_file.write_text(json.dumps(admission), encoding="utf-8")
    admission_file.chmod(0o600)
    adc_file = private / "explicit-adc.json"
    # Deliberately invalid JSON: check must inspect only path metadata, never content.
    adc_file.write_text("synthetic content must not be parsed or disclosed", encoding="utf-8")
    adc_file.chmod(0o600)
    return {"env": env_file, "admission": admission_file, "adc": adc_file,
            "admission_document": admission}


def _args(paths: dict[str, Path], command: str = "check") -> list[str]:
    return [command, "--env-file", str(paths["env"]), "--admission", str(paths["admission"]),
            "--adc-file", str(paths["adc"]), "--authorize-google-voice-data-and-spend",
            "--tts-requests", "2", "--stt-requests", "3", "--tts-max-seconds", "8.5",
            "--stt-max-seconds", "29"]


def _clear_network_environment(monkeypatch):
    for key in live_voice._NETWORK_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_unarmed_and_help_never_read_admission_or_load_google_auth(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(live_voice, "_read_text_admission", lambda *_a, **_k: calls.append("admission"))
    monkeypatch.setattr(live_voice, "_load_google_credentials", lambda *_a, **_k: calls.append("auth"))
    assert live_voice.main([]) == 0
    assert "Unarmed" in capsys.readouterr().out
    with pytest.raises(SystemExit) as result:
        live_voice.main(["--help"])
    assert result.value.code == 0
    help_text = capsys.readouterr().out
    assert "microphone audio" in help_text.lower()
    assert "not dollar caps" in help_text.lower()
    assert calls == []


def test_check_reports_declared_voice_without_reading_adc_or_touching_provider(private_tmp_path, monkeypatch,
                                                                               capsys):
    paths = _inputs(private_tmp_path)
    original_open = Path.open

    def block_adc_open(path, *args, **kwargs):
        if path == paths["adc"]:
            raise AssertionError("check read ADC contents")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", block_adc_open)
    monkeypatch.setattr(live_voice, "_load_google_credentials",
                        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("auth loaded")))
    monkeypatch.setattr(live_voice, "_new_google_http_client",
                        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("client created")))
    assert live_voice.main(_args(paths)) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["voice_mode"] == "declared_only"
    assert status["voice_data_spend_acknowledged"] is True
    assert status["auth_contents"] == "not_read"
    assert status["credentials_loaded"] is False
    assert status["provider_activity"] == "not_run"
    assert status["armed"] is False
    assert status["declaration_checked"] is True
    assert status["admission_authorized"] is True
    assert status["live_ready"] is False
    assert status["quota_or_entitlement_verified"] is False
    assert status["spend_dollar_cap"] is None
    assert status["limits_are_dollar_caps"] is False
    assert status["limits"]["tts_requests_per_instance"] == 2
    assert status["limits"]["stt_requests_per_instance"] == 3
    assert status["data_scope"]["microphone_audio"] == "Google Speech-to-Text V2"
    assert status["data_scope"]["approved_speech_text"] == "Google Gemini Enterprise TTS"
    assert status["data_scope"]["prior_app_dialogue"] == "Codex and JEV under text admission"
    assert status["microphone_capture_on_startup"] is False
    assert status["microphone_requires_browser_user_gesture"] is True
    assert "synthetic content" not in capsys.readouterr().out


def test_missing_jev_key_stops_voice_check_before_adc_or_provider(private_tmp_path, monkeypatch, capsys):
    paths = _inputs(private_tmp_path)
    paths["env"].write_text(
        paths["env"].read_text(encoding="utf-8").replace(
            "MIRA_SERVICES__JEV__API_KEY=synthetic-jev-key\n", ""),
        encoding="utf-8",
    )
    paths["env"].chmod(0o600)
    calls = []
    monkeypatch.setattr(live_voice, "_load_google_credentials", lambda *_a, **_k: calls.append("auth"))
    monkeypatch.setattr(live_voice, "_new_google_http_client", lambda *_a, **_k: calls.append("http"))

    assert live_voice.main(_args(paths)) == 2
    assert calls == []
    assert "explicit env file must declare" in capsys.readouterr().err


def test_separate_voice_consent_is_required_before_admission_or_auth(private_tmp_path, monkeypatch, capsys):
    paths = _inputs(private_tmp_path)
    calls = []
    monkeypatch.setattr(live_voice, "_read_text_admission", lambda *_a, **_k: calls.append("read"))
    monkeypatch.setattr(live_voice, "_load_google_credentials", lambda *_a, **_k: calls.append("auth"))
    with pytest.raises(SystemExit) as result:
        live_voice.main(["serve", "--env-file", str(paths["env"]), "--admission",
                         str(paths["admission"]), "--adc-file", str(paths["adc"]),
                         "--tts-requests", "1", "--stt-requests", "1",
                         "--tts-max-seconds", "10", "--stt-max-seconds", "10"])
    assert result.value.code == 2
    assert calls == []
    assert "authorize-google-voice-data-and-spend" in capsys.readouterr().err


@pytest.mark.parametrize("speech", [
    {"MIRA_SERVICES__SPEECH__STT_MODEL": "chirp_2"},
    {"MIRA_SERVICES__SPEECH__TTS_MODEL": "gemini-2.5-flash-preview-tts"},
    {"MIRA_SERVICES__SPEECH__TTS_VOICE": "Aoede"},
])
def test_nonselected_voice_setup_stops_before_adc_or_provider(private_tmp_path, monkeypatch, speech, capsys):
    paths = _inputs(private_tmp_path, speech=speech)
    calls = []
    monkeypatch.setattr(live_voice, "_load_google_credentials", lambda *_a, **_k: calls.append("auth"))
    monkeypatch.setattr(live_voice, "_prepare_frontend", lambda: calls.append("frontend"))
    assert live_voice.main(_args(paths)) == 2
    assert calls == []
    error = capsys.readouterr().err
    assert any(message in error for message in (
        "explicit env file", "values were not printed", "fixed Google voice selection"))


def test_voice_file_and_limit_validation_precedes_auth(private_tmp_path, monkeypatch, capsys):
    paths = _inputs(private_tmp_path)
    calls = []
    monkeypatch.setattr(live_voice, "_load_google_credentials", lambda *_a, **_k: calls.append("auth"))
    argv = _args(paths)
    argv[argv.index("--adc-file") + 1] = str(paths["adc"].parent / "missing-adc.json")
    assert live_voice.main(argv) == 2
    assert calls == []
    assert "private owner-only regular file" in capsys.readouterr().err
    assert live_voice.main([*_args(paths), "--tts-requests", "9"]) == 2
    assert calls == []


def test_application_voice_profile_requires_matching_explicit_admission_and_keeps_user_selected_limits(
        private_tmp_path, monkeypatch, capsys):
    paths = _inputs(private_tmp_path)
    admission = paths["admission_document"]
    admission["usage_profile"] = "application"
    admission["limits"].update({
        "codex_requests": 100, "session_turns": 100,
        "input_jev_requests": 100, "output_jev_requests": 100,
    })
    paths["admission"].write_text(json.dumps(admission), encoding="utf-8")
    paths["admission"].chmod(0o600)
    calls = []
    real_load_settings = live_voice._load_explicit_settings
    monkeypatch.setattr(live_voice, "_load_explicit_settings",
                        lambda *_a, **_k: calls.append("config"))
    # An omitted flag remains probe even when a private file names an application
    # admission; it may not silently upgrade voice limits.
    assert live_voice.main(_args(paths)) == 2
    assert calls == []
    assert "exactly match" in capsys.readouterr().err
    monkeypatch.setattr(live_voice, "_load_explicit_settings", real_load_settings)

    args = _args(paths)
    args[args.index("--tts-requests") + 1] = "1"
    args[args.index("--stt-requests") + 1] = "2"
    args[args.index("--tts-max-seconds") + 1] = "30"
    args[args.index("--stt-max-seconds") + 1] = "290"
    args.extend(["--usage-profile", "application"])
    # A setup-only check reports the exact caller-selected ceiling, does not expand
    # values to the profile maximum, and does not read ADC or create a provider.
    assert live_voice.main(args) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["usage_profile"] == "application"
    assert status["limits"]["tts_requests_per_instance"] == 1
    assert status["limits"]["stt_requests_per_instance"] == 2
    assert status["limits"]["stt_max_stream_seconds_per_stream"] == 290
    assert status["provider_activity"] == "not_run"


def test_network_environment_drift_blocks_auth_and_frontend(private_tmp_path, monkeypatch, capsys):
    approved = {"HTTPS_PROXY": "http://approved-proxy.invalid:8080"}
    paths = _inputs(private_tmp_path, runtime_environment=approved)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    calls = []
    monkeypatch.setattr(live_voice, "_load_google_credentials", lambda *_a, **_k: calls.append("auth"))
    monkeypatch.setattr(live_voice, "_prepare_frontend", lambda: calls.append("frontend"))
    assert live_voice.main(_args(paths, "serve")) == 2
    assert calls == []
    assert "environment differs from the approved runtime" in capsys.readouterr().err


def test_unsupported_approved_proxy_stops_before_auth_loading(private_tmp_path, monkeypatch, capsys):
    proxy = "socks5h://proxy.invalid:1080"
    paths = _inputs(private_tmp_path, runtime_environment={"HTTPS_PROXY": proxy})
    _clear_network_environment(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", proxy)
    calls = []
    monkeypatch.setattr(live_voice, "_load_google_credentials", lambda *_a, **_k: calls.append("auth"))
    monkeypatch.setattr(live_voice, "_prepare_frontend", lambda: calls.append("frontend"))
    assert live_voice.main(_args(paths, "serve")) == 2
    assert calls == []
    assert "unsupported route" in capsys.readouterr().err


def test_admitted_serve_uses_existing_factory_and_voice_required_lifespan(private_tmp_path, monkeypatch):
    paths = _inputs(private_tmp_path)
    _clear_network_environment(monkeypatch)
    events = []

    class Credentials:
        valid = True
        token = "synthetic-sdk-token"

        def refresh(self, _request):
            events.append("refresh")

    class FakeHttpClient:
        def __init__(self):
            self.close_count = 0

        async def aclose(self):
            self.close_count += 1

        @property
        def is_closed(self):
            return self.close_count > 0

    http_client = FakeHttpClient()
    monkeypatch.setattr(live_voice, "_load_google_credentials",
                        lambda path: events.append(("auth", path)) or Credentials())
    monkeypatch.setattr(live_voice, "_make_google_token_provider",
                        lambda credentials: (events.append(("token-provider", credentials))
                                             or (lambda: None)))
    monkeypatch.setattr(live_voice, "_new_google_http_client",
                        lambda runtime: events.append(("http", runtime)) or http_client)
    monkeypatch.setattr(live_voice, "_prepare_frontend", lambda: events.append("frontend"))

    from mira.bootstrap import development_app, development_voice
    from mira.bootstrap.providers import GoogleVoiceProviders

    real_app_factory = development_app.create_development_app
    app_call = {}

    def capture_app_factory(**kwargs):
        app_call.update(kwargs)
        app = real_app_factory(**kwargs)
        app_call["app"] = app
        return app

    monkeypatch.setattr(development_app, "create_development_app", capture_app_factory)

    class FakeGoogleBundle:
        def __init__(self):
            self.close_count = 0

        async def close(self):
            self.close_count += 1

    google_bundle = FakeGoogleBundle()
    provider_args = []

    def fake_create_google_voice(settings, **kwargs):
        provider_args.append((settings, kwargs))
        return GoogleVoiceProviders(object(), object(), google_bundle.close)

    monkeypatch.setattr(development_voice, "create_google_voice", fake_create_google_voice)

    def fake_uvicorn_run(app, **kwargs):
        events.append(("uvicorn", kwargs))
        with TestClient(app):
            pass

    monkeypatch.setattr(live_voice, "_run_uvicorn", fake_uvicorn_run)
    assert live_voice.main(_args(paths, "serve")) == 0

    assert events[0] == "frontend"
    assert events[1] == ("auth", paths["adc"])
    assert events[2][0] == "token-provider"
    assert events[3][0] == "http"
    assert events[4][0] == "uvicorn"
    from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
    assert app_call["decision_policy"] == USER_DEVELOPMENT_0_6_V2
    assert app_call["voice_required"] is True
    assert app_call["usage_profile"] == "probe"
    assert app_call["voice_usage_limits"].usage_profile.value == "probe"
    assert app_call["app"].state.usage_declaration.tts_requests == 2
    assert app_call["app"].state.usage_declaration.stt_max_stream_seconds == 29
    assert app_call["app"].state.usage_snapshot.stt_requests_used is None
    assert callable(app_call["voice_factory"])
    assert len(provider_args) == 1
    speech, supplied = provider_args[0]
    assert speech.project_id == "synthetic-project"
    assert speech.stt_model == "chirp_3"
    assert speech.tts_model == "gemini-3.8-flash-tts"
    assert speech.tts_voice == "Kore" and speech.tts_location == "global"
    assert supplied["authorized"] is True
    assert supplied["credentials"].token == "synthetic-sdk-token"
    assert supplied["stt_max_stream_seconds"] == 29.0
    assert supplied["tts_max_audio_samples"] == 8.5 * 24000
    assert supplied["http_client"] is http_client
    assert google_bundle.close_count == 1
    assert http_client.close_count == 1


def test_google_voice_startup_failure_closes_http_client_and_suppresses_details(
        private_tmp_path, monkeypatch, capsys):
    paths = _inputs(private_tmp_path)
    _clear_network_environment(monkeypatch)

    class Credentials:
        valid = True
        token = "opaque-synthetic-token"

        def refresh(self, _request):
            raise AssertionError("valid fake credentials do not refresh")

    class FakeHttpClient:
        def __init__(self):
            self.close_count = 0

        async def aclose(self):
            self.close_count += 1

        @property
        def is_closed(self):
            return self.close_count > 0

    http_client = FakeHttpClient()
    monkeypatch.setattr(live_voice, "_load_google_credentials", lambda _path: Credentials())
    monkeypatch.setattr(live_voice, "_new_google_http_client", lambda _runtime: http_client)
    monkeypatch.setattr(live_voice, "_prepare_frontend", lambda: None)
    from mira.bootstrap import development_voice

    monkeypatch.setattr(development_voice, "create_google_voice",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("synthetic-secret")))

    def run_test_app(app, **_kwargs):
        with TestClient(app):
            pass

    monkeypatch.setattr(live_voice, "_run_uvicorn", run_test_app)
    assert live_voice.main(_args(paths, "serve")) == 2
    assert http_client.close_count == 1
    captured = capsys.readouterr()
    assert "synthetic-secret" not in captured.err
    assert "credentials and provider details were suppressed" in captured.err


def test_official_adc_loader_uses_only_explicit_file_and_google_sdk(monkeypatch, private_tmp_path):
    paths = _inputs(private_tmp_path)
    import google.auth

    calls = []
    expected = object()

    def load_credentials_from_file(path, *, scopes):
        calls.append((path, tuple(scopes)))
        return expected, "ignored-project-from-file"

    monkeypatch.setattr(google.auth, "load_credentials_from_file", load_credentials_from_file)
    assert live_voice._load_google_credentials(paths["adc"]) is expected
    assert calls == [(str(paths["adc"]), ("https://www.googleapis.com/auth/cloud-platform",))]


@pytest.mark.asyncio
async def test_sdk_token_provider_defers_refresh_and_uses_opaque_google_credentials(monkeypatch):
    from google.auth.transport import requests

    request_marker = object()
    monkeypatch.setattr(requests, "Request", lambda: request_marker)

    class OpaqueCredentials:
        valid = False
        token = None

        def __init__(self):
            self.refresh_calls = []

        def refresh(self, request):
            self.refresh_calls.append(request)
            self.valid = True
            self.token = "synthetic-sdk-token"

    credentials = OpaqueCredentials()
    provider = live_voice._make_google_token_provider(credentials)
    assert credentials.refresh_calls == []
    assert await provider() == "synthetic-sdk-token"
    assert credentials.refresh_calls == [request_marker]


def test_text_cli_voice_flag_remains_fail_closed(private_tmp_path, monkeypatch, capsys):
    import tools.live_dev as live_dev

    paths = _inputs(private_tmp_path)
    calls = []
    monkeypatch.setattr(live_dev, "_read_admission", lambda *_a, **_k: calls.append("read"))
    assert live_dev.main(["serve", "--env-file", str(paths["env"]), "--admission",
                          str(paths["admission"]), "--voice-required"]) == 2
    assert calls == []
    assert "none is loaded by this CLI" in capsys.readouterr().err


def test_fallback_http_cleanup_preserves_external_event_loop():
    previous_policy = asyncio.get_event_loop_policy()
    isolated_policy = asyncio.DefaultEventLoopPolicy()
    external_loop = asyncio.new_event_loop()
    isolated_policy.set_event_loop(external_loop)
    asyncio.set_event_loop_policy(isolated_policy)
    closed = []

    class Client:
        is_closed = False

        async def aclose(self):
            closed.append(asyncio.get_running_loop())

    try:
        live_voice._close_http_client(Client())
        assert asyncio.get_event_loop() is external_loop
        assert not external_loop.is_closed()
        assert len(closed) == 1 and closed[0] is not external_loop
        assert closed[0].is_closed()
    finally:
        external_loop.close()
        asyncio.set_event_loop_policy(previous_policy)


def test_explicit_approved_ca_is_bridged_to_verifying_grpc(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import grpc
    import ssl

    ca_file = tmp_path / "synthetic-roots.pem"
    pem = b"-----BEGIN CERTIFICATE-----\nsynthetic-fixture\n-----END CERTIFICATE-----\n"
    ca_file.write_bytes(pem)
    runtime = SimpleNamespace(environment={"SSL_CERT_FILE": str(ca_file)})
    _clear_network_environment(monkeypatch)
    monkeypatch.setenv("SSL_CERT_FILE", str(ca_file))
    validated = []
    supplied = []
    marker = object()
    monkeypatch.setattr(ssl, "create_default_context",
                        lambda **kwargs: validated.append(kwargs) or object())
    monkeypatch.setattr(grpc, "ssl_channel_credentials",
                        lambda **kwargs: supplied.append(kwargs) or marker)
    assert live_voice._make_google_stt_tls(runtime) is marker
    assert validated == [{"cadata": pem.decode("ascii")}]
    assert supplied == [{"root_certificates": pem}]


def test_invalid_explicit_ca_fails_closed_without_grpc(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import grpc

    ca_file = tmp_path / "bad-roots.pem"
    ca_file.write_bytes(b"not a valid certificate")
    runtime = SimpleNamespace(environment={"SSL_CERT_FILE": str(ca_file)})
    _clear_network_environment(monkeypatch)
    monkeypatch.setenv("SSL_CERT_FILE", str(ca_file))
    calls = []
    monkeypatch.setattr(grpc, "ssl_channel_credentials", lambda **_kwargs: calls.append(True))
    with pytest.raises(live_voice.EntryError, match="approved CA"):
        live_voice._make_google_stt_tls(runtime)
    assert calls == []


def test_no_custom_ca_uses_platform_roots_and_directory_only_is_explicitly_blocked(monkeypatch):
    from types import SimpleNamespace

    _clear_network_environment(monkeypatch)
    assert live_voice._make_google_stt_tls(SimpleNamespace(environment={})) is None
    monkeypatch.setenv("SSL_CERT_DIR", "/synthetic/certs")
    with pytest.raises(live_voice.EntryError, match="CA file"):
        live_voice._make_google_stt_tls(
            SimpleNamespace(environment={"SSL_CERT_DIR": "/synthetic/certs"}))

@pytest.mark.parametrize("value", ["zero", "0", "101", "01"])
def test_voice_count_parse_error_reports_application_ceiling_without_widening_profile(value):
    import argparse
    with pytest.raises(argparse.ArgumentTypeError, match="1 to 100"):
        live_voice._voice_request_count(value)
    assert live_voice._voice_request_count("100") == 100
    assert live_voice._VOICE_REQUESTS_MAX == 100
