"""The offline demo never chooses an unvalidated Python or installs dependencies."""
import subprocess
import sys
from pathlib import Path

import pytest

from tools import dev

_REAL_WHICH = dev.shutil.which


def put_tools_on_path(monkeypatch, tmp_path, *names):
    bin_dir = tmp_path / "synthetic-path"
    bin_dir.mkdir()
    for name in names:
        executable = bin_dir / name
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(dev.shutil, "which", lambda name: _REAL_WHICH(name, path=str(bin_dir)))


def fake_launch(monkeypatch, tmp_path, *, ready=(), project_python=True):
    python = tmp_path / ".venv/bin/python"
    if project_python:
        python.parent.mkdir(parents=True)
        python.touch()
    compiler = tmp_path / "node_modules/typescript/bin/tsc"
    compiler.parent.mkdir(parents=True)
    compiler.touch()
    esbuild = tmp_path / "node_modules/esbuild/lib/main.js"
    esbuild.parent.mkdir(parents=True)
    esbuild.touch()
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    monkeypatch.setattr(dev.shutil, "which", lambda name: "/synthetic/bin/" + name)
    # The old launcher only inspects its own interpreter; retain that stimulus.
    if hasattr(dev, "importlib"):
        monkeypatch.setattr(dev.importlib.util, "find_spec", lambda name: object())
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if "-c" in command:
            code = 0 if command[0] in ready else 1
            return subprocess.CompletedProcess(command, code, "", "synthetic-private-detail")
        return subprocess.CompletedProcess(command, 0, "v24.19.0\n", "")

    monkeypatch.setattr(dev.subprocess, "run", run)
    return python, calls


def invoke(monkeypatch, *arguments):
    monkeypatch.setattr(sys, "argv", ["tools/dev.py", *arguments])
    try:
        result = dev.main()
        return result or 0
    except SystemExit as error:
        return error.code


def test_incomplete_project_python_does_not_hide_ready_current_python(monkeypatch, tmp_path):
    python, calls = fake_launch(monkeypatch, tmp_path, ready=(sys.executable,))
    assert invoke(monkeypatch, "--no-bootstrap") == 0
    exports = [command for command, _ in calls if any("export_contracts.py" in part for part in command)]
    assert exports and exports[0][0] == sys.executable
    assert exports[0][0] != str(python)


def test_missing_dependencies_fail_without_any_install(monkeypatch, tmp_path, capsys):
    _, calls = fake_launch(monkeypatch, tmp_path, project_python=False)
    if hasattr(dev, "importlib"):
        monkeypatch.setattr(dev.importlib.util, "find_spec", lambda name: None)
    assert invoke(monkeypatch) == 2
    assert not any("bootstrap.py" in str(command) or "install" in command for command, _ in calls)
    output = capsys.readouterr()
    assert "bootstrap.py" in output.err
    assert "synthetic-private-detail" not in output.err


def test_explicit_python_is_used_and_not_guessed(monkeypatch, tmp_path):
    explicit = str(tmp_path / "chosen environment/bin/python")
    _, calls = fake_launch(monkeypatch, tmp_path, ready=(explicit, sys.executable))
    assert invoke(monkeypatch, "--python", explicit) == 0
    assert any(command[0] == explicit and "--serve" in command for command, _ in calls)
    assert not any(".venv313" in str(command) for command, _ in calls)


def test_invalid_explicit_python_is_an_error_not_a_fallback(monkeypatch, tmp_path, capsys):
    _, calls = fake_launch(monkeypatch, tmp_path, ready=(sys.executable,))
    assert invoke(monkeypatch, "--python", "missing-python") == 2
    assert "not usable" in capsys.readouterr().err
    assert not any("export_contracts.py" in str(command) for command, _ in calls)


@pytest.mark.parametrize("profile", ["mock", "replay", "rehearsal"])
def test_demo_settings_ignore_dotenv_process_credentials_and_live_configuration(monkeypatch, tmp_path, profile):
    from mira.config import loader

    config = tmp_path / "config"
    (config / "profiles").mkdir(parents=True)
    (config / "defaults.toml").write_text("[providers]\ngeneration = 'codex'\nreview = 'jev'\n")
    (config / f"profiles/{profile}.toml").write_text("")
    (tmp_path / ".env").write_text("MIRA_PROVIDERS__GENERATION=api\nOPENAI_API_KEY=synthetic\n")
    monkeypatch.setenv("MIRA_PROVIDERS__GENERATION", "api")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.setenv("MIRA_DIAGNOSTICS__DEVELOPMENT_RECORDING", "true")
    monkeypatch.setattr(loader, "dotenv_values", lambda *a, **kw: pytest.fail("dotenv read"))
    settings = dev.demo_settings(root=tmp_path, profile=profile, port=8123, scenario="photo-tour")
    assert settings.providers.generation == profile
    assert settings.providers.review == "fixture"
    assert not settings.providers.allow_external_calls and not settings.providers.allow_paid_api
    assert settings.services.openai.api_key is None
    assert not settings.diagnostics.development_recording
    assert settings.http.port == 8123
    assert settings.http.allowed_origins == ("http://127.0.0.1:8123", "http://localhost:8123")


def test_python_probe_has_timeout_and_redacts_child_failure(monkeypatch, tmp_path):
    def timeout(command, **kwargs):
        assert kwargs["timeout"] <= 15
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], stderr="synthetic-private-detail")

    monkeypatch.setattr(dev.subprocess, "run", timeout)
    assert dev.python_ready(str(tmp_path / "python")) is False


def test_missing_compiler_fails_without_installing_or_starting(monkeypatch, tmp_path, capsys):
    _, calls = fake_launch(monkeypatch, tmp_path, ready=(sys.executable,))
    (tmp_path / "node_modules/typescript/bin/tsc").unlink()
    assert invoke(monkeypatch) == 2
    assert "TypeScript" in capsys.readouterr().err
    assert not any("export_contracts.py" in str(command) or "--serve" in command
                   for command, _ in calls)


def test_missing_node_explains_node_and_npm_must_be_installed_first(monkeypatch, tmp_path, capsys):
    _, calls = fake_launch(monkeypatch, tmp_path, ready=(sys.executable,))
    put_tools_on_path(monkeypatch, tmp_path, "npm")
    assert invoke(monkeypatch) == 2
    error = capsys.readouterr().err
    assert "Node.js 22.12+" in error
    assert "npm" in error
    assert "bootstrap.py" in error
    assert not any("export_contracts.py" in str(command) or "--serve" in command
                   for command, _ in calls)


def test_existing_locked_dependencies_build_without_starting_npm(monkeypatch, tmp_path, capsys):
    _, calls = fake_launch(monkeypatch, tmp_path, ready=(sys.executable,))
    put_tools_on_path(monkeypatch, tmp_path, "node")
    assert invoke(monkeypatch) == 0
    assert not any(Path(command[0]).name in {"npm", "npx"} for command, _ in calls)
    assert not any("install" in command or "ci" in command for command, _ in calls)
    assert any(command[-1] == str(tmp_path / "tools/build_web.mjs") for command, _ in calls)


def test_unsupported_node_version_fails_before_contract_export(monkeypatch, tmp_path, capsys):
    _, calls = fake_launch(monkeypatch, tmp_path, ready=(sys.executable,))
    put_tools_on_path(monkeypatch, tmp_path, "node", "npm")
    original_run = dev.subprocess.run

    def old_node(command, **kwargs):
        if command == [str(tmp_path / "synthetic-path/node"), "--version"]:
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "v20.18.0\n", "")
        return original_run(command, **kwargs)

    monkeypatch.setattr(dev.subprocess, "run", old_node)
    assert invoke(monkeypatch) == 2
    assert "Node.js 22.12+" in capsys.readouterr().err
    assert not any("export_contracts.py" in str(command) or "--serve" in command
                   for command, _ in calls)


def test_launcher_checks_contracts_then_runs_local_node_build_before_server(monkeypatch, tmp_path):
    _, calls = fake_launch(monkeypatch, tmp_path, ready=(sys.executable,))
    assert invoke(monkeypatch) == 0
    commands = [command for command, _ in calls]
    contract = next(i for i, command in enumerate(commands) if any("export_contracts.py" in part for part in command))
    build = commands.index(["/synthetic/bin/node", str(tmp_path / "tools/build_web.mjs")])
    serve = next(i for i, command in enumerate(commands) if "--serve" in command)
    assert contract < build < serve


@pytest.mark.parametrize('fallback',[False,True])
def test_offline_launcher_forwards_adopted_renderer_or_explicit_fallback(monkeypatch,tmp_path,fallback):
    _,calls=fake_launch(monkeypatch,tmp_path,ready=(sys.executable,))
    args=['--character-renderer','static-pixi'] if fallback else []
    assert invoke(monkeypatch,*args)==0
    command=next(command for command,_ in calls if '--serve' in command)
    assert '--character-renderer' in command
    assert command[command.index('--character-renderer')+1]==('static-pixi' if fallback else 'code-native-review')


@pytest.mark.parametrize('fallback',[False,True])
def test_offline_child_uses_same_renderer_without_loading_live_resources(monkeypatch,fallback):
    seen=[]
    def serve(*,profile,port,scenario,character_renderer='static-pixi'):
        seen.append(character_renderer)
    monkeypatch.setattr(dev,'serve',serve)
    assert invoke(monkeypatch,'--serve',*(['--character-renderer','static-pixi'] if fallback else []))==0
    assert seen==['static-pixi' if fallback else 'code-native-review']


def test_failed_local_node_build_does_not_start_server(monkeypatch, tmp_path, capsys):
    _, calls = fake_launch(monkeypatch, tmp_path, ready=(sys.executable,))
    original_run = dev.subprocess.run

    def fail_build(command, **kwargs):
        calls.append((command, kwargs))
        if command == ["/synthetic/bin/node", str(tmp_path / "tools/build_web.mjs")]:
            raise subprocess.CalledProcessError(1, command, output="", stderr="synthetic-build-detail")
        return original_run(command, **kwargs)

    monkeypatch.setattr(dev.subprocess, "run", fail_build)
    assert invoke(monkeypatch) == 2
    assert "Startup command failed" in capsys.readouterr().err
    assert not any("--serve" in command for command, _ in calls)


def test_child_environment_strips_service_configuration_and_credential_aliases(monkeypatch):
    for key in ("MIRA_PROFILE", "MIRA_PROVIDERS__GENERATION", "MIRA_DIAGNOSTICS__RECORDING_CONSENT",
                "OPENAI_API_KEY", "TYPESAFE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "PYTHONPATH"):
        monkeypatch.setenv(key, "synthetic")
    env = dev.child_environment()
    assert not any(key.startswith("MIRA_") for key in env)
    assert not {"OPENAI_API_KEY", "TYPESAFE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "PYTHONPATH"} & env.keys()


@pytest.mark.parametrize("argument", ["--profile=codex", "--port=0", "--port=65536"])
def test_demo_rejects_live_profile_and_invalid_ports(monkeypatch, argument):
    assert invoke(monkeypatch, argument) == 2


def test_shell_launcher_works_without_executable_file_mode(tmp_path):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(["sh", str(root / "scripts/dev"), "--help"], cwd=tmp_path,
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0
    assert "--python" in result.stdout and "--profile" in result.stdout
