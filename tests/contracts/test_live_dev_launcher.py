"""Default-unarmed CLI and fresh TypeScript output served by the same app."""
import os
import shutil
import subprocess
import sys
import tempfile
import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.contracts.test_development_app_entry import make_app
import tools.live_dev as live_dev


ROOT = Path(__file__).resolve().parents[2]
LOCAL_NODE_MODULES = ROOT / "node_modules"


def test_no_argument_subprocess_is_unarmed_without_pythonpath():
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable,
         str(ROOT / "tools/live_dev.py")],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "Unarmed" in result.stdout
    assert "no configuration or admission files were opened" in result.stdout
    assert result.stderr == ""


def test_check_reports_only_private_config_declarations_and_never_calls_providers(capsys):
    with tempfile.TemporaryDirectory(prefix="mira-live-check-", dir="/tmp") as raw:
        private = Path(raw)
        env_file = private / "mira.env"
        admission_file = private / "admission.json"
        env_file.write_text(
            "MIRA_SERVICES__JEV__MODEL=jev-1.13.0\n"
            "MIRA_SERVICES__JEV__API_KEY=synthetic-key-for-check\n", encoding="utf-8")
        env_file.chmod(0o600)
        admission = {
            "authorized": True, "route_kind": "public",
            "runtime": {
                "executable": "/synthetic/codex", "codex_home": "/synthetic/home",
                "runtime_cwd": "/synthetic/run", "environment": {},
                "expected_config_sha256": "a" * 64,
                "policy_environment_confirmed": True, "development_context": None,
            },
            "limits": {
                "codex_requests": 1, "session_turns": 1,
                "input_jev_requests": 2, "output_jev_requests": 2,
                "input_jev_timeout_seconds": 10, "output_jev_timeout_seconds": 10,
            },
        }
        admission_file.write_text(json.dumps(admission), encoding="utf-8")
        admission_file.chmod(0o600)

        assert live_dev.main(["check", "--env-file", str(env_file), "--admission",
                              str(admission_file)]) == 0
        output = capsys.readouterr().out
        status = json.loads(output)
        assert status["armed"] is False
        assert status["declaration_checked"] is True
        assert status["admission_authorized"] is True
        assert status["usage_profile"] == "probe"
        assert status["live_ready"] is False
        assert '"inference": "not_run"' in output
        assert '"speech_enabled": false' in output
        assert '"quota_or_entitlement_verified": false' in output
        assert "synthetic-key-for-check" not in output

        # A legacy admission with no profile remains probe and cannot inherit the
        # application ceiling by shape or a previous process selection.
        admission["limits"].update({
            "codex_requests": 8, "session_turns": 8,
            "input_jev_requests": 8, "output_jev_requests": 8,
        })
        admission_file.write_text(json.dumps(admission), encoding="utf-8")
        admission_file.chmod(0o600)
        parsed = live_dev._read_admission(admission_file)
        assert parsed.usage_profile == "probe"
        assert parsed.limits.codex_requests == 8
        admission["limits"]["codex_requests"] = 9
        admission_file.write_text(json.dumps(admission), encoding="utf-8")
        admission_file.chmod(0o600)
        try:
            live_dev._read_admission(admission_file)
        except live_dev.EntryError as error:
            assert "between 1 and 8" in str(error)
        else:
            raise AssertionError("legacy admission must reject application-only ceiling")

        admission["usage_profile"] = "application"
        admission["limits"].update({
            "codex_requests": 100, "session_turns": 100,
            "input_jev_requests": 100, "output_jev_requests": 100,
        })
        admission_file.write_text(json.dumps(admission), encoding="utf-8")
        admission_file.chmod(0o600)
        parsed = live_dev._read_admission(admission_file)
        assert parsed.usage_profile == "application"
        assert parsed.limits.input_jev_requests == 100
        admission["limits"]["output_jev_requests"] = 101
        admission_file.write_text(json.dumps(admission), encoding="utf-8")
        admission_file.chmod(0o600)
        try:
            live_dev._read_admission(admission_file)
        except live_dev.EntryError as error:
            assert "between 1 and 100" in str(error)
        else:
            raise AssertionError("application admission must reject over-limit ceiling")


def test_check_reports_missing_jev_as_unverified_declaration_without_arming(capsys):
    with tempfile.TemporaryDirectory(prefix="mira-live-missing-jev-", dir="/tmp") as raw:
        private = Path(raw)
        env_file = private / "mira.env"
        env_file.write_text("MIRA_SERVICES__JEV__MODEL=jev-1.13.0\n", encoding="utf-8")
        env_file.chmod(0o600)
        admission_file = private / "admission.json"
        admission_file.write_text(json.dumps({
            "authorized": True, "route_kind": "public",
            "runtime": {
                "executable": "/synthetic/codex", "codex_home": "/synthetic/home",
                "runtime_cwd": "/synthetic/run", "environment": {},
                "expected_config_sha256": "a" * 64,
                "policy_environment_confirmed": True, "development_context": None,
            },
            "limits": {
                "codex_requests": 1, "session_turns": 1,
                "input_jev_requests": 2, "output_jev_requests": 2,
                "input_jev_timeout_seconds": 10, "output_jev_timeout_seconds": 10,
            },
        }), encoding="utf-8")
        admission_file.chmod(0o600)

        assert live_dev.main(["check", "--env-file", str(env_file), "--admission",
                              str(admission_file)]) == 0
        status = json.loads(capsys.readouterr().out)
        assert status["armed"] is False
        assert status["declaration_checked"] is True
        assert status["admission_authorized"] is True
        assert status["jev_credential_declared"] is False
        assert status["live_ready"] is False


def test_clean_no_dist_copy_builds_and_serves_compiled_main_js(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="mira-live-dev-copy-", dir="/tmp") as raw:
        copy_root = Path(raw) / "clean-checkout"
        (copy_root / "apps/api").mkdir(parents=True)
        (copy_root / "tools").mkdir()
        (copy_root / "packages").mkdir()
        shutil.copytree(ROOT / "apps/api/src", copy_root / "apps/api/src")
        shutil.copytree(ROOT / "apps/web", copy_root / "apps/web",
                        ignore=shutil.ignore_patterns("dist"))
        shutil.copytree(ROOT / "packages/contracts", copy_root / "packages/contracts")
        shutil.copy2(ROOT / "tools/export_contracts.py", copy_root / "tools/export_contracts.py")
        shutil.copy2(ROOT / "tools/build_web.mjs", copy_root / "tools/build_web.mjs")
        shutil.copy2(ROOT / "package.json", copy_root / "package.json")
        shutil.copy2(ROOT / "package-lock.json", copy_root / "package-lock.json")
        (copy_root / "node_modules").symlink_to(LOCAL_NODE_MODULES.resolve(), target_is_directory=True)
        web_root = copy_root / "apps/web"
        assert not (web_root / "dist").exists()

        monkeypatch.setattr(live_dev, "ROOT", copy_root)
        live_dev._prepare_frontend()

        main_js = web_root / "dist/app/main.js"
        assert main_js.is_file()
        app, codex, input_jev, output_jev = make_app(web_root=web_root)
        with TestClient(app) as client:
            index = client.get("/")
            script = client.get("/dist/app/main.js")
            assert index.status_code == 200
            assert 'src="/dist/app/main.js"' in index.text
            assert script.status_code == 200
            # Minification may rename classes. Verify actual bytes and local bundle
            # dependencies instead of relying on an implementation identifier.
            assert script.content == main_js.read_bytes()
            assert script.content
            chunks = sorted((web_root / "dist/app/chunks").glob("*.js"))
            assert chunks
            for chunk in chunks:
                resource = client.get("/dist/app/chunks/" + chunk.name)
                assert resource.status_code == 200
                assert resource.content == chunk.read_bytes()
            assert client.get("/api/v1/voice-capabilities").json()["speech_enabled"] is False
        assert codex.sent == []
        assert input_jev.calls == [] and output_jev.calls == []
