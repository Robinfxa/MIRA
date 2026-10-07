"""CLI transmission opt-in is separate from local recording and provider admission."""
import pytest

from tools import live_dev


def arguments(*extra):
    return ["check", "--env-file", "/synthetic/private.env", "--admission", "/synthetic/admission.json", *extra]


def test_absent_memory_options_do_not_load_any_memory(monkeypatch):
    from mira.config import memory
    monkeypatch.setattr(memory, "load_memory_recall_options", lambda **_: pytest.fail("unexpected memory read"))
    args = live_dev._build_parser().parse_args(arguments())
    assert live_dev._memory_options(args) is None


@pytest.mark.parametrize("options", [
    ["--memory-db", "/synthetic/private/memory.sqlite3"],
    ["--authorize-memory-to-codex-and-jev"],
    ["--memory-db", "/synthetic/private/memory.sqlite3", "--memory-scope-config", "/synthetic/private/scopes.json", "--memory-scope", "local"],
])
def test_partial_memory_flags_fail_before_admission_or_memory_reads(monkeypatch, capsys, options):
    from mira.config import memory
    monkeypatch.setattr(live_dev, "_read_admission", lambda *_: pytest.fail("admission opened"))
    monkeypatch.setattr(memory, "load_memory_recall_options", lambda **_: pytest.fail("memory opened"))
    assert live_dev.main(arguments(*options)) == 2
    text = capsys.readouterr().err
    assert "Memory recall needs all" in text
    assert "/synthetic" not in text


def test_complete_flags_forward_explicit_consent_only(monkeypatch):
    from mira.config import memory
    seen = {}
    sentinel = object()
    def load(**kwargs):
        seen.update(kwargs)
        return sentinel
    monkeypatch.setattr(memory, "load_memory_recall_options", load)
    args = live_dev._build_parser().parse_args(arguments(
        "--memory-db", "/synthetic/private/memory.sqlite3",
        "--memory-scope-config", "/synthetic/private/scopes.json", "--memory-scope", "local",
        "--authorize-memory-to-codex-and-jev", "--create-local-operator-pairing"))
    assert live_dev._memory_options(args) is sentinel
    assert seen["authorized_transmission"] is True
    assert seen["scope_alias"] == "local"
    assert seen["checkout_root"] == live_dev.ROOT


def test_memory_help_names_recipients_and_separate_no_recording(capsys):
    with pytest.raises(SystemExit):
        live_dev._build_parser().parse_args(["serve", "--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "Codex" in text and "TypeSafe JEV" in text
    assert "does not record" in text


def test_memory_pairing_flag_required_before_reads(monkeypatch, capsys):
    from mira.config import memory
    monkeypatch.setattr(memory, "load_memory_recall_options", lambda **_: pytest.fail("read before pairing opt-in"))
    assert live_dev.main(arguments("--memory-db", "/synthetic/private/memory.sqlite3",
        "--memory-scope-config", "/synthetic/private/scopes.json", "--memory-scope", "local",
        "--authorize-memory-to-codex-and-jev")) == 2
    assert "--create-local-operator-pairing" in capsys.readouterr().err


def test_pairing_flag_without_memory_is_rejected(capsys):
    assert live_dev.main(arguments("--create-local-operator-pairing")) == 2
    assert "only with explicitly enabled memory" in capsys.readouterr().err


def _mock_entry(monkeypatch, tmp_path):
    from mira.config.settings import Settings
    from mira.config.memory import MemoryRecallOptions
    from mira.domain.memory import MemoryScope
    from tests.contracts.test_development_app_entry import public_runtime
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    opts = MemoryRecallOptions(private / "synthetic.sqlite3", MemoryScope("synthetic", "mira", "world"), "local", True)
    admission = live_dev.Admission(True, "public", public_runtime(), live_dev.AdmissionLimits(1, 1, 2, 2, 10, 10))
    settings = Settings()
    monkeypatch.setattr(live_dev, "_memory_options", lambda _args: opts)
    monkeypatch.setattr(live_dev, "_read_admission", lambda _path: admission)
    monkeypatch.setattr(live_dev, "_load_settings", lambda *_a, **_k: settings)
    monkeypatch.setattr(live_dev, "_check_settings", lambda *_a, **_k: None)
    return private, opts, settings


def test_check_never_creates_operator_credential(monkeypatch, tmp_path, capsys):
    import json
    from tools import operator_pairing_file
    _mock_entry(monkeypatch, tmp_path)
    monkeypatch.setattr(operator_pairing_file, "create_pairing_material", lambda *_a, **_k: pytest.fail("credential created during check"))
    assert live_dev.main(arguments()) == 0
    status = json.loads(capsys.readouterr().out)["memory_recall"]
    assert status["operator_pairing_required"] is True
    assert status["pairing_file_created"] is False and status["database_opened"] is False


def test_serve_creates_only_explicit_synthetic_pairing_and_never_prints_code(monkeypatch, tmp_path, capsys):
    from mira.bootstrap import development_app
    from tools import operator_pairing_file
    import uvicorn
    private, opts, _settings = _mock_entry(monkeypatch, tmp_path)
    # The checked-in quality runner places basetemp under the checkout. Pairing
    # storage must be outside the configured checkout, so this test injects an
    # adjacent synthetic root while keeping its private directory in tmp_path.
    monkeypatch.setattr(live_dev, "ROOT", tmp_path / "synthetic-checkout-root")
    synthetic = "synthetic-fixed-code-for-tests-00000000"
    captured = {}
    original = operator_pairing_file.create_pairing_material
    def material(directory, *, checkout_root):
        return original(directory, checkout_root=checkout_root, code_factory=lambda: synthetic)
    monkeypatch.setattr(operator_pairing_file, "create_pairing_material", material)
    monkeypatch.setattr(live_dev, "_prepare_frontend", lambda: None)
    monkeypatch.setattr(development_app, "jev_transport_from_settings", lambda _: object())
    def app(**kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setattr(development_app, "create_development_app", app)
    monkeypatch.setattr(uvicorn, "run", lambda *_a, **_k: None)
    args = arguments(); args[0] = "serve"
    assert live_dev.main(args) == 0
    files = list(private.glob("mira-operator-*.txt"))
    assert len(files) == 1 and files[0].read_text() == synthetic + "\n"
    assert captured["memory_options"] is opts
    assert captured["operator_pairing"] is not None
    output = capsys.readouterr().out
    assert synthetic not in output and str(files[0]) in output
    assert "five minutes" in output


def test_failed_frontend_build_does_not_create_pairing(monkeypatch, tmp_path):
    from tools import operator_pairing_file
    _mock_entry(monkeypatch, tmp_path)
    def failed():
        raise live_dev.EntryError("synthetic build failure")
    monkeypatch.setattr(live_dev, "_prepare_frontend", failed)
    monkeypatch.setattr(operator_pairing_file, "create_pairing_material", lambda *_a, **_k: pytest.fail("premature credential"))
    args = arguments(); args[0] = "serve"
    assert live_dev.main(args) == 2
