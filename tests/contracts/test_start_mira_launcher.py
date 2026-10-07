"""First-use launcher contracts: temporary configuration, no real credentials or providers."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import start_mira as cli

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "MIRA source with spaces"
    root.mkdir()
    (root / ".env.example").write_bytes((ROOT / ".env.example").read_bytes())
    monkeypatch.setattr(cli, "ROOT", root, raising=False)
    monkeypatch.setattr(cli, "home_path", lambda: tmp_path / "Home with spaces", raising=False)
    monkeypatch.setattr(cli.os, "chdir", lambda *_: None)
    return root


def test_dry_run_is_exact_original_profile_without_mutation(project, capsys):
    before = set(project.rglob("*"))
    assert cli.main(["--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["argv"] == [str(project / ".venv/bin/python"),
        str(project / "tools/live_provider.py"), "serve", "--provider", "chatgpt_subscription",
        "--model", "gpt-6.1-sol", "--service-tier", "fast", "--env-file", str(project / ".env"),
        "--authorize-provider-data", "--voice", "--adc-file",
        str(project.parent / "Home with spaces/.config/gcloud/application_default_credentials.json"),
        "--authorize-google-voice-data-and-spend", "--story", "--story-images",
        "--authorize-story-image-data-to-openai", "--authorize-story-image-subscription-usage",
        "--authorize-story-image-custom-brief", "--story-image-review-model", "gpt-6-luna"]
    assert result["network"] == "not_run" and result["consent"] == "not_granted_by_preview"
    assert set(project.rglob("*")) == before


def test_dry_run_overrides_and_budget_passthrough_are_single_arguments(project, capsys):
    assert cli.main(["--dry-run", "--python", "/some path/python", "--model", "other-model",
        "--service-tier", "standard", "--port", "8123", "--no-voice", "--no-story-images",
        "--", "--generation-requests", "4", "--loopback-only"]) == 0
    args = json.loads(capsys.readouterr().out)["argv"]
    assert args[0] == "/some path/python"
    assert args[args.index("--model") + 1] == "other-model"
    assert args[args.index("--service-tier") + 1] == "standard"
    assert "--voice" not in args and "--adc-file" not in args and "--story-images" not in args
    assert args[-5:] == ["--port", "8123", "--generation-requests", "4", "--loopback-only"]


@pytest.mark.parametrize("prefix", ["$HOME", "${HOME}", "~"])
def test_adc_home_expansion_never_runs_shell(project, capsys, prefix):
    assert cli.main(["--dry-run", "--adc-file", prefix + "/folder with spaces/adc.json"]) == 0
    args = json.loads(capsys.readouterr().out)["argv"]
    assert args[args.index("--adc-file") + 1] == str(project.parent / "Home with spaces/folder with spaces/adc.json")


def test_expansion_treats_command_substitution_as_literal(project, capsys):
    assert cli.main(["--dry-run", "--adc-file", "$(touch NEVER_CREATED).json"]) == 0
    assert not (project / "NEVER_CREATED").exists()
    assert "$(touch NEVER_CREATED).json" in capsys.readouterr().out


def test_offline_preview_contains_no_live_flags_or_private_config(project, capsys):
    assert cli.main(["--preset", "offline", "--dry-run"]) == 0
    args = json.loads(capsys.readouterr().out)["argv"]
    assert "--profile" in args and "rehearsal" in args
    assert all("authorize" not in arg for arg in args)
    assert "--env-file" not in args


def test_no_tty_does_not_assume_live_or_write(project, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    assert cli.main([]) == 2
    assert not (project / ".env").exists()
    assert not (project / "var").exists()
    assert "--accept-live-profile" in capsys.readouterr().err


@pytest.mark.parametrize("choice", ["0", "", "cancel", "unexpected"])
def test_first_run_cancel_does_not_write_or_start(project, monkeypatch, capsys, choice):
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda _: choice)
    assert cli.main([]) == 0
    assert not (project / ".env").exists() and not (project / "var").exists()
    assert "取消" in capsys.readouterr().out


def test_init_creates_private_template_without_overwriting_existing(project):
    cli.ensure_env(project / ".env", default_path=True)
    config = project / ".env"
    assert config.read_bytes() == (project / ".env.example").read_bytes()
    assert config.stat().st_mode & 0o777 == 0o600
    config.write_text("PRIVATE_EXISTING_SENTINEL=unchanged\n")
    config.chmod(0o640)
    cli.ensure_env(config, default_path=True)
    assert config.read_text() == "PRIVATE_EXISTING_SENTINEL=unchanged\n"
    assert config.stat().st_mode & 0o777 == 0o640


def test_missing_custom_env_is_never_created(project):
    target = project / "custom.env"
    with pytest.raises(cli.StartError, match="--env-file"):
        cli.ensure_env(target, default_path=False)
    assert not target.exists()


@pytest.mark.parametrize("kind", ["world_readable", "symlink", "directory", "missing"])
def test_private_metadata_rejects_unsafe_files_without_reading(project, monkeypatch, kind):
    target = project / "private.json"
    if kind == "world_readable":
        target.write_text("SYNTHETIC_SECRET")
        target.chmod(0o644)
    elif kind == "symlink":
        actual = project / "actual.json"
        actual.write_text("SYNTHETIC_SECRET")
        target.symlink_to(actual)
    elif kind == "directory":
        target.mkdir()
    monkeypatch.setattr(Path, "read_text", lambda *_: pytest.fail("No private reads"))
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("No private reads"))
    with pytest.raises(cli.StartError):
        cli.private_metadata(target, "ADC", "Read FIRST-RUN.md")


def test_metadata_good_credentials_are_not_read(project, monkeypatch):
    target = project / "private.json"
    target.write_text("NOT EVEN VALID JSON")
    target.chmod(0o600)
    monkeypatch.setattr(Path, "read_text", lambda *_: pytest.fail("No private reads"))
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("No private reads"))
    cli.private_metadata(target, "ADC", "Read FIRST-RUN.md")


def test_saved_choice_is_bound_to_checkout_and_excluded_from_profile(project, monkeypatch):
    cli.save_choice("live")
    assert cli.saved_choice() == "live"
    saved = project / "var/launcher/choice.json"
    assert saved.stat().st_mode & 0o777 == 0o600
    other = project.parent / "second-copy"
    other.mkdir()
    (other / "var/launcher").mkdir(parents=True)
    copied = other / "var/launcher/choice.json"
    copied.write_bytes(saved.read_bytes())
    copied.chmod(0o600)
    monkeypatch.setattr(cli, "ROOT", other)
    assert cli.saved_choice() is None


def test_check_does_not_grant_consent_seed_env_or_start(project, monkeypatch, capsys):
    monkeypatch.setattr(cli, "select_python", lambda *_: "/ready/python")
    monkeypatch.setattr(cli, "preflight", lambda *_: None)
    monkeypatch.setattr(cli.os, "execve", lambda *_: pytest.fail("check cannot start"))
    assert cli.main(["--check", "--accept-live-profile"]) == 0
    assert not (project / ".env").exists() and not (project / "var").exists()
    assert "not_live_verified" in capsys.readouterr().out


def test_missing_dependencies_have_setup_guidance_without_install(project, monkeypatch, capsys):
    monkeypatch.setattr(cli, "python_ready", lambda *_: False)
    monkeypatch.setattr(cli.subprocess, "run", lambda *_a, **_k: pytest.fail("no installation"))
    assert cli.main(["--check"]) == 2
    assert "--setup" in capsys.readouterr().err
    assert not (project / ".env").exists()


def test_missing_login_and_adc_provide_precise_next_steps(project, capsys):
    args, extra = cli.parse_args(["--check"])
    config = project / ".env"
    config.write_text("SYNTHETIC=not_loaded\n")
    config.chmod(0o600)
    with pytest.raises(cli.StartError, match="provider_login.py login"):
        cli.preflight("/unused/python", args, extra)
    auth = cli.default_auth_path()
    auth.parent.mkdir(parents=True)
    auth.write_text("SYNTHETIC_NOT_PARSED")
    auth.chmod(0o600)
    with pytest.raises(cli.StartError, match="application-default login"):
        cli.preflight("/unused/python", args, extra)


@pytest.mark.parametrize("extra", [["--provider", "openai_api"], ["--provi", "openai_api"],
    ["--authorize-api-billing"], ["--env-file", "other.env"], ["--unknown"]])
def test_passthrough_cannot_change_provider_or_authorizations(project, capsys, extra):
    assert cli.main(["--dry-run", "--", *extra]) == 2
    assert not (project / "var").exists()


def test_live_choice_persists_once_without_touching_existing_environment(project, monkeypatch):
    config = project / ".env"
    config.write_text("PRIVATE_SENTINEL=not_logged\n")
    config.chmod(0o600)
    monkeypatch.setattr(cli, "select_python", lambda *_: "/ready/python")
    monkeypatch.setattr(cli, "preflight", lambda *_: None)
    calls = []
    monkeypatch.setattr(cli.os, "execve", lambda *args: calls.append(args))
    assert cli.main(["--accept-live-profile"]) == 0
    assert cli.main([]) == 0
    assert len(calls) == 2 and config.read_text() == "PRIVATE_SENTINEL=not_logged\n"
    assert calls[0][1] == calls[1][1]
    assert "--authorize-google-voice-data-and-spend" in calls[0][1]


def test_template_supported_voice_fields_and_chinese_style_round_trip():
    from mira.config.loader import load_settings
    settings = load_settings(root=ROOT, env_file=ROOT / ".env.example", environ={})
    speech = settings.services.speech
    assert speech.tts_voice == "Gacrux"
    assert speech.tts_model == "gemini-3.8-flash-tts" and speech.tts_location == "global"
    assert speech.tts_style == "御姐音，语调轻快，爽朗自然，咬字清晰，亲切有活力，不刻意压低嗓音或拖慢语速。"


def test_env_start_fields_are_used_without_rewriting_or_logging_secrets(project, capsys):
    target = project / ".env"
    content = ("MIRAAPP_PROVIDER=chatgpt_subscription\nMIRAAPP_MODEL=gpt-6-luna\n"
        "MIRAAPP_SERVICE_TIER=standard\nMIRAAPP_VOICE=true\nMIRAAPP_STORY=true\n"
        "MIRAAPP_STORY_IMAGES=true\nMIRAAPP_IMAGE_REVIEW_MODEL=gpt-6.1-sol\n"
        "MIRAAPP_ADC_FILE='${HOME}/a folder/adc.json'\n"
        "MIRAAPP_AUTH_STORE='${HOME}/private folder/mira.json'\n"
        "OPENAI_API_KEY=synthetic-private-do-not-output\n")
    target.write_text(content)
    target.chmod(0o600)
    assert cli.main(["--dry-run", "--python", sys.executable]) == 0
    text = capsys.readouterr().out
    args = json.loads(text)["argv"]
    assert args[args.index("--model") + 1] == "gpt-6-luna"
    assert args[args.index("--service-tier") + 1] == "standard"
    assert args[args.index("--story-image-review-model") + 1] == "gpt-6.1-sol"
    assert args[args.index("--adc-file") + 1] == str(project.parent / "Home with spaces/a folder/adc.json")
    assert args[args.index("--auth-store") + 1] == str(project.parent / "Home with spaces/private folder/mira.json")
    assert "synthetic-private" not in text and target.read_text() == content
    assert not (project / "var").exists()


def test_explicit_cli_wins_over_env_including_enable_and_disable(project, capsys):
    target = project / ".env"
    target.write_text("MIRAAPP_MODEL=gpt-6-luna\nMIRAAPP_SERVICE_TIER=standard\n"
        "MIRAAPP_VOICE=false\nMIRAAPP_STORY=false\nMIRAAPP_STORY_IMAGES=true\n")
    target.chmod(0o600)
    assert cli.main(["--dry-run", "--python", sys.executable, "--model", "gpt-6.1-sol",
        "--service-tier", "fast", "--voice", "--story", "--no-story-images"]) == 0
    args = json.loads(capsys.readouterr().out)["argv"]
    assert args[args.index("--model") + 1] == "gpt-6.1-sol"
    assert args[args.index("--service-tier") + 1] == "fast"
    assert "--voice" in args and "--story" in args and "--story-images" not in args


def test_env_disabling_story_removes_image_authorization_flags(project, capsys):
    target = project / ".env"
    target.write_text("MIRAAPP_VOICE=false\nMIRAAPP_STORY=false\nMIRAAPP_STORY_IMAGES=true\n")
    target.chmod(0o600)
    assert cli.main(["--dry-run", "--python", sys.executable]) == 0
    args = json.loads(capsys.readouterr().out)["argv"]
    assert "--voice" not in args and "--story" not in args
    assert all("story-image" not in value and "google" not in value for value in args)


@pytest.mark.parametrize("field", ["MIRAAPP_AUTHORIZE=true", "MIRAAPP_PROVIDER=openai_api",
    "MIRAAPP_VOICE=maybe", "MIRAAPP_MODEL=sk-synthetic-secret"])
def test_env_cannot_authorize_live_or_select_api_or_leak_bad_values(project, capsys, field):
    target = project / ".env"
    target.write_text(field + "\n")
    target.chmod(0o600)
    assert cli.main(["--dry-run", "--python", sys.executable]) == 2
    captured = capsys.readouterr()
    assert "sk-synthetic-secret" not in captured.out + captured.err
    assert not (project / "var").exists()


def test_env_profile_does_not_bypass_noninteractive_first_choice(project, monkeypatch):
    target = project / ".env"
    target.write_text((ROOT / ".env.example").read_text())
    target.chmod(0o600)
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(cli, "apply_profile", lambda *_: pytest.fail("No config read before choice"))
    assert cli.main([]) == 2
    assert not (project / "var").exists()


def test_saved_offline_is_used_by_preview_and_check_without_env_reads(project, monkeypatch, capsys):
    cli.save_choice("offline")
    monkeypatch.setattr(cli, "apply_profile", lambda *_: pytest.fail("Offline cannot read env"))
    assert cli.main(["--dry-run"]) == 0
    assert "rehearsal" in json.loads(capsys.readouterr().out)["argv"]
    monkeypatch.setattr(cli, "select_python", lambda *_: "/ready/python")
    monkeypatch.setattr(cli, "check_web", lambda: None)
    monkeypatch.setattr(cli, "preflight", lambda *_: pytest.fail("No live preflight"))
    assert cli.main(["--check"]) == 0


def test_setup_only_runs_existing_project_bootstrap_and_exits(project, monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(cli.subprocess, "run", run)
    monkeypatch.setattr(cli.os, "execve", lambda *_: pytest.fail("Setup cannot start MIRA"))
    assert cli.main(["--setup"]) == 0
    assert calls[0][0] == [sys.executable, str(project / "tools/bootstrap.py")]
    assert calls[0][1]["cwd"] == project and len(calls) == 1
    assert not (project / ".env").exists() and not (project / "var").exists()


def test_failed_config_check_never_replays_private_subprocess_output(project, monkeypatch, capsys):
    args, extra = cli.parse_args(["--check"])
    config = project / ".env"
    config.write_text("GOOGLE_CLOUD_PROJECT=synthetic-hidden-project\n")
    config.chmod(0o600)
    auth = cli.default_auth_path()
    auth.parent.mkdir(parents=True)
    auth.write_text("not parsed")
    auth.chmod(0o600)
    adc = cli.local_path(args.adc_file)
    adc.parent.mkdir(parents=True)
    adc.write_text("not parsed")
    adc.chmod(0o600)
    monkeypatch.setattr(cli, "check_web", lambda: None)
    monkeypatch.setattr(cli.subprocess, "run", lambda *_a, **_k: SimpleNamespace(
        returncode=2, stdout=b"synthetic-private-output", stderr=b"synthetic-private-error"))
    with pytest.raises(cli.StartError) as caught:
        cli.preflight("/ready/python", args, extra)
    assert "synthetic" not in str(caught.value)
    assert "synthetic" not in capsys.readouterr().out
