from pathlib import Path

import pytest

from mira.config.local_memory import (
    LocalMemoryManagementOptions,
    load_local_memory_management_options,
)


def private_fixture(tmp_path: Path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    database = private / "memory.sqlite3"
    database.write_bytes(b"synthetic existing database placeholder")
    database.chmod(0o600)
    scope_config = private / "scopes.json"
    scope_config.write_text(
        '{"version":1,"scopes":[{"name":"test-local","user_id":"synthetic-user",'
        '"character_id":"mira-test","world_id":"synthetic-world"}]}',
        encoding="utf-8",
    )
    scope_config.chmod(0o600)
    return database, scope_config


def test_management_options_have_no_transmission_authorization(tmp_path):
    database, config = private_fixture(tmp_path)
    options = load_local_memory_management_options(
        database=database,
        scope_config=config,
        scope_alias="test-local",
        consent_local_memory=True,
        checkout_root=Path(__file__).resolve().parents[2],
    )
    assert type(options) is LocalMemoryManagementOptions
    assert options.database == database
    assert options.scope_alias == "test-local"
    assert not hasattr(options, "authorized_transmission")


@pytest.mark.parametrize("consent", [False, 1, "true", None])
def test_scope_configuration_requires_exact_local_access_consent(tmp_path, consent):
    database, config = private_fixture(tmp_path)
    with pytest.raises(ValueError, match="memory_local_consent_required"):
        load_local_memory_management_options(
            database=database,
            scope_config=config,
            scope_alias="test-local",
            consent_local_memory=consent,
            checkout_root=Path(__file__).resolve().parents[2],
        )


def test_local_management_options_validate_but_do_not_open_existing_database(tmp_path, monkeypatch):
    from mira.adapters.memory.sqlite import SQLiteMemoryStore

    database, config = private_fixture(tmp_path)
    monkeypatch.setattr(SQLiteMemoryStore, "open", lambda *_a, **_k: pytest.fail("database opened"))
    options = load_local_memory_management_options(
        database=database,
        scope_config=config,
        scope_alias="test-local",
        consent_local_memory=True,
        checkout_root=Path(__file__).resolve().parents[2],
    )
    assert options.database.exists()

