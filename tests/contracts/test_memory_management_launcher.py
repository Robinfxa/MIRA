"""Local-edit consent never inherits recording, pairing, or provider consent."""
from pathlib import Path

import pytest

from tools import live_dev
from mira.config.loader import ConfigurationError
from mira.config.memory import MemoryRecallOptions
from mira.domain.memory import MemoryScope
from mira.bootstrap.development_memory_management import create_development_memory_management_factory


def args(*extra):
    return ["check", "--env-file", "/synthetic/mira.env", "--admission", "/synthetic/admission.json", *extra]


def options():
    return MemoryRecallOptions(Path("/synthetic/private/memory.sqlite3"),
        MemoryScope("synthetic-user", "mira", "synthetic-world"), "local", True)


def test_local_management_flag_defaults_off_and_requires_explicit_selection():
    assert live_dev._build_parser().parse_args(args()).authorize_local_memory_management is False
    assert live_dev._build_parser().parse_args(args("--authorize-local-memory-management")).authorize_local_memory_management is True


def test_local_management_alone_does_not_enable_memory_or_read_admission(monkeypatch, capsys):
    monkeypatch.setattr(live_dev, "_read_admission", lambda *_: pytest.fail("admission accessed"))
    assert live_dev.main(args("--authorize-local-memory-management")) == 2
    result = capsys.readouterr().err
    assert "does not enable recall or transmission" in result
    assert "/synthetic" not in result


def test_existing_transmission_consent_does_not_authorize_local_edits():
    with pytest.raises(ConfigurationError, match="memory_management_consent_required"):
        create_development_memory_management_factory(options())
    for value in (None, 1, "true"):
        with pytest.raises(ConfigurationError, match="memory_management_consent_required"):
            create_development_memory_management_factory(options(), authorized=value)


def test_management_factory_is_inert_until_paired_app_invokes_it(monkeypatch):
    monkeypatch.setattr(Path, "open", lambda *_a, **_k: pytest.fail("storage opened"))
    assert callable(create_development_memory_management_factory(options(), authorized=True))
    with pytest.raises(ConfigurationError, match="memory_management_configuration_invalid"):
        create_development_memory_management_factory(object(), authorized=True)
