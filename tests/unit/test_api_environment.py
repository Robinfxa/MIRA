"""Synthetic transports only: never read account files or send production requests."""
import json
import os
import socket
from pathlib import Path

import httpx
import pytest

from mira.config.loader import load_settings
from tools.api_environment import ServicePreparationError, initialize_private_env, inspect_services, probe_models

ROOT = Path(__file__).resolve().parents[2]


def settings(**service_overrides):
    return load_settings(root=ROOT, environ={}, overrides={"services": service_overrides})


def ready_services(**kwargs):
    data = {
        "probe": {"allow_metadata": True, "max_requests": 3},
        "gateway": {"api_key": "synthetic-gateway-secret", "access_confirmed": True, "text_model": "model-a"},
        "jev": {"api_key": "synthetic-jev-secret", "model": "jev-fixed"},
        "openai": {"api_key": "synthetic-openai-secret", "text_model": "model-b"},
    }
    data.update(kwargs)
    return settings(**data)


def test_offline_inspection_does_not_call_network_or_claim_live(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network"))
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("network"))
    report = inspect_services(settings(), executable_available=False)
    assert report["live_ready"] is False
    assert report["inference_verified"] == "not_run"
    assert report["capabilities"]["text"]["adapter"] == "implemented_in_explicit_development_entry"
    assert report["capabilities"]["text"]["fields_complete"] is False
    assert report["capabilities"]["text"]["account_access"] == "not_run"
    assert report["capabilities"]["text"]["default_provider_factory_composed"] is False
    assert not report["core_fields_complete"]


def test_selected_route_reports_implemented_development_entries_without_claiming_readiness():
    s = ready_services(
        routes={"text": "codex_native", "image": "codex_native", "vision": "codex_native"},
        codex={"text_model": "chosen-codex"},
        jev={"api_key": "synthetic-jev-secret", "model": "jev-fixed"},
        speech={"project_id": "mira-example", "quota_project_id": "mira-example",
                "tts_voice": "Kore"},
    )
    report = inspect_services(s, executable_available=True)
    rows = report["capabilities"]
    for capability, entrypoint in (("text", "tools/live_dev.py"),
                                   ("review", "tools/live_dev.py"),
                                   ("asr", "tools/live_voice.py"),
                                   ("tts", "tools/live_voice.py")):
        assert rows[capability]["adapter"] == "implemented_in_explicit_development_entry"
        assert rows[capability]["adapter_entrypoint"] == entrypoint
        assert rows[capability]["default_provider_factory_composed"] is False
    assert rows["image"]["adapter"] == "not_implemented"
    assert rows["vision"]["adapter"] == "not_implemented"
    assert report["live_ready"] is False
    assert report["inference_verified"] == "not_run"
    assert all(rows[name]["account_access"] == "not_run" for name in ("text", "review", "asr", "tts"))
    assert "synthetic-jev-secret" not in json.dumps(report)


@pytest.mark.parametrize("route", ["gateway", "openai_api"])
def test_generic_text_route_remains_unimplemented_even_with_complete_fields(route):
    group = "gateway" if route == "gateway" else "openai"
    s = ready_services(routes={"text": route}, **{
        group: {"api_key": "synthetic-route-secret", "text_model": "model-ready",
               **({"access_confirmed": True} if group == "gateway" else {})},
    })
    row = inspect_services(s)["capabilities"]["text"]
    assert row["fields_complete"]
    assert row["adapter"] == "not_implemented"
    assert row["adapter_entrypoint"] is None
    assert row["default_provider_factory_composed"] is False


def test_explicit_env_file_missing_has_safe_specific_guidance_and_never_falls_back(tmp_path, monkeypatch, capsys):
    from tools import api_env
    root_env = tmp_path / ".env"
    root_env.write_text("MIRA_HTTP__PORT=8765\n")
    missing = tmp_path / "private-not-here.env"
    monkeypatch.setattr(api_env, "ROOT", tmp_path)
    monkeypatch.setattr(api_env, "load_settings",
                        lambda **kwargs: pytest.fail("explicit missing file must block before project .env fallback"))
    monkeypatch.setattr("sys.argv", ["api_env", "check", "--env-file", str(missing)])

    assert api_env.main() == 2
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["status"] == "blocked"
    assert report["reason"] == "explicit_env_file_missing"
    assert report["live_ready"] is False
    assert "existing private" in report["next"]
    assert "init" in report["next"]
    assert str(missing) not in output.out + output.err
    assert "Traceback" not in output.err


def test_fields_and_credential_presence_are_not_authentication():
    s = ready_services(routes={"text": "gateway", "image": "gateway", "vision": "gateway"},
                       speech={"project_id": "mira-example", "quota_project_id": "mira-example", "tts_voice": "cmn-CN-chosen"})
    report = inspect_services(s)
    assert report["core_fields_complete"]
    assert report["capabilities"]["text"]["account_access"] == "not_run"
    assert not report["live_ready"]
    assert "synthetic-" not in json.dumps(report)


def test_native_credentials_are_managed_not_read_or_guessed():
    report = inspect_services(settings(codex={"text_model": "chosen-codex"}), executable_available=True)
    row = report["capabilities"]["text"]
    assert row["fields_complete"]
    assert row["authentication"] == "codex_managed_not_checked"
    assert row["account_access"] == "not_run"


def test_placeholder_key_is_not_configuration_complete():
    s = ready_services(jev={"api_key": "YOUR_API_KEY", "model": "fixed"})
    assert not inspect_services(s)["capabilities"]["review"]["fields_complete"]


def test_initializer_is_private_and_does_not_replace_existing_files(tmp_path):
    path = tmp_path / "private.env"
    initialize_private_env(ROOT, path)
    before = path.read_bytes()
    assert b"MIRA_PROFILE=development" in before
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ServicePreparationError):
        initialize_private_env(ROOT, path)
    assert path.read_bytes() == before


def test_initializer_rejects_symlink(tmp_path):
    existing = tmp_path / "untouched"; existing.write_text("keep")
    link = tmp_path / "link.env"; link.symlink_to(existing)
    with pytest.raises(ServicePreparationError):
        initialize_private_env(ROOT, link)
    assert existing.read_text() == "keep"


@pytest.mark.parametrize("kwargs,names", [
    ({"probe": {"allow_metadata": False, "max_requests": 3}}, ["jev"]),
    ({"probe": {"allow_metadata": True, "max_requests": 0}}, ["jev"]),
    ({"probe": {"allow_metadata": True, "max_requests": 1}}, ["jev", "openai"]),
    ({"gateway": {"api_key": "synthetic-key", "access_confirmed": False}}, ["gateway"]),
    ({"jev": {"model": "fixed"}}, ["jev"]),
    ({}, ["jev", "jev"]),
    ({}, []),
    ({}, ["unknown"]),
])
def test_probe_admission_rejects_before_any_network(kwargs, names):
    calls = []
    transport = httpx.MockTransport(lambda req: calls.append(req) or httpx.Response(200))
    with pytest.raises(ServicePreparationError):
        probe_models(ready_services(**kwargs).services, names, transport=transport)
    assert not calls


def test_metadata_selects_correct_endpoint_and_credential_without_inference():
    calls = []
    def handle(req):
        calls.append((str(req.url), req.headers["authorization"], req.method, req.content))
        if req.url.host == "api.typesafe.ai":
            return httpx.Response(200, json={"models": [{"name": "jev-fixed"}]})
        return httpx.Response(200, json={"data": [{"id": "model-a"}, {"id": "model-b"}]})
    report = probe_models(ready_services().services, ["gateway", "jev", "openai"], transport=httpx.MockTransport(handle))
    assert [c[0] for c in calls] == ["http://127.0.0.1:8317/v1/models", "https://api.typesafe.ai/v1/models", "https://api.openai.com/v1/models"]
    assert [c[1] for c in calls] == ["Bearer synthetic-gateway-secret", "Bearer synthetic-jev-secret", "Bearer synthetic-openai-secret"]
    assert all(method == "GET" and content == b"" for _, _, method, content in calls)
    assert all(row["catalog_valid"] for row in report["results"])
    assert "synthetic-" not in json.dumps(report)
    assert report["inference_verified"] == "not_run" and report["live_ready"] is False


@pytest.mark.parametrize("status,expected", [(401, "unauthorized"), (403, "forbidden"), (429, "rate_limited"), (503, "service_unavailable"), (302, "redirect_refused")])
def test_errors_are_redacted_and_never_retried(status, expected):
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(status, text="synthetic-jev-secret", headers={"location": "https://evil.invalid/"})
    report = probe_models(ready_services().services, ["jev"], transport=httpx.MockTransport(handle))
    assert len(calls) == 1
    assert report["results"][0]["status"] == expected
    assert "synthetic-jev-secret" not in json.dumps(report)


@pytest.mark.parametrize("body,expected", [
    (b'{"models":[]}', "catalog_valid"),
    (b'{"models":[{"name":42}]}', "invalid_catalog"),
    (b'{"data":[{"id":"not-the-jev-schema"}]}', "invalid_catalog"),
    (b'{"models":[],"models":[]}', "invalid_json"),
    (b'synthetic-secret-not-json', "invalid_json"),
    (b'x' * (256 * 1024 + 1), "response_too_large"),
], ids=["empty", "bad-type", "wrong-provider-shape", "duplicate", "invalid-json", "oversized"])
def test_result_contract_and_size_are_checked(body, expected):
    report = probe_models(ready_services().services, ["jev"], transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)))
    assert report["results"][0]["status"] == expected
    assert report["inference_verified"] == "not_run"


def test_timeout_has_no_raw_exception_or_fallback():
    calls = []
    def fail(req):
        calls.append(req)
        raise httpx.ReadTimeout("synthetic-jev-secret", request=req)
    report = probe_models(ready_services().services, ["jev"], transport=httpx.MockTransport(fail))
    assert len(calls) == 1
    assert report["results"][0]["status"] == "timeout"
    assert "synthetic" not in json.dumps(report)


def test_metadata_has_no_environment_proxy_or_redirect_following(monkeypatch):
    seen = {}
    real = httpx.Client
    def client(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)
    monkeypatch.setattr(httpx, "Client", client)
    probe_models(ready_services().services, ["jev"], transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"models": []})))
    assert seen["trust_env"] is False and seen["follow_redirects"] is False


def test_encoded_metadata_is_rejected_without_decompression():
    import gzip
    report = probe_models(ready_services().services, ["jev"], transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=gzip.compress(b'{"models":[]}'), headers={"content-encoding": "gzip"})))
    assert report["results"][0]["status"] == "encoded_response_refused"


def test_cli_check_reports_missing_setup_not_product_success(tmp_path):
    import subprocess
    import sys
    path = tmp_path / "private.env"
    initialize_private_env(ROOT, path)
    result = subprocess.run([sys.executable, str(ROOT / "tools/api_env.py"), "check", "--env-file", str(path)],
                            cwd=ROOT, env={}, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["live_ready"] is False and report["scope"] == "offline_configuration_only"
    assert "Traceback" not in result.stderr


def test_cli_error_does_not_echo_secret_input(tmp_path):
    import subprocess
    import sys
    path = tmp_path / "private.env"
    path.write_text("MIRA_HTTP__PORT=synthetic-dont-print-me\n")
    result = subprocess.run([sys.executable, str(ROOT / "tools/api_env.py"), "check", "--env-file", str(path)],
                            cwd=ROOT, env={}, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "synthetic-dont-print-me" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "configuration_invalid"


def test_cli_metadata_cannot_be_mistaken_for_offline_check(tmp_path):
    import subprocess
    import sys
    path = tmp_path / "private.env"
    initialize_private_env(ROOT, path)
    result = subprocess.run([sys.executable, str(ROOT / "tools/api_env.py"), "check", "--env-file", str(path), "--service", "jev"],
                            cwd=ROOT, env={}, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "--service is only valid for metadata" in result.stderr


def test_offline_lanes_strip_standard_service_credentials(tmp_path, monkeypatch):
    import sys
    from tools.quality_plan import Lane, Plan
    from tools.quality_run import run_plan
    names = ("OPENAI_API_KEY", "TYPESAFE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "CODEX_ACCESS_TOKEN", "ACCESS_TOKEN")
    for name in names:
        monkeypatch.setenv(name, "synthetic-private-value")
    code = f"import os; assert not any(k in os.environ for k in {names!r}); print('isolated')"
    lane = Lane("secret-env", "command", command=(sys.executable, "-c", code))
    report = run_plan(tmp_path, Plan("lanes", (lane,), ("secret-env",)), output_dir=tmp_path / "output")
    assert report["status"] == "passed"
    assert "synthetic-private-value" not in (tmp_path / "output/secret-env/stdout.txt").read_text()
