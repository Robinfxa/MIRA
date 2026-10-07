"""Synthetic, local-only transmission admission. No provider calls."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from mira.config.loader import ConfigurationError
from mira.config.memory import load_memory_recall_options


def files(tmp_path: Path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    db = private / "memory.sqlite3"
    db.write_bytes(b"fixture: the reader owns database validation")
    db.chmod(0o600)
    scopes = private / "scopes.json"
    scopes.write_text(json.dumps({"version": 1, "scopes": [
        {"name": "local", "user_id": "synthetic-user", "character_id": "mira",
         "world_id": "synthetic-world"}]}))
    scopes.chmod(0o600)
    return db, scopes


def load(tmp_path, db, scopes, **kwargs):
    return load_memory_recall_options(database=db, scope_config=scopes,
        scope_alias="local", authorized_transmission=True, checkout_root=tmp_path / "checkout",
        **kwargs)


def test_missing_transmission_consent_does_not_access_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "lstat", lambda *_: pytest.fail("path accessed before consent"))
    with pytest.raises(ConfigurationError, match="memory_transmission_consent_required"):
        load_memory_recall_options(database=tmp_path / "missing", scope_config=tmp_path / "missing2",
            scope_alias="local", authorized_transmission=False, checkout_root=tmp_path / "checkout")


def test_explicit_options_are_private_immutable_and_bound_to_alias(tmp_path):
    db, scopes = files(tmp_path)
    options = load(tmp_path, db, scopes)
    assert options.database == db
    assert options.scope.user_id == "synthetic-user"
    assert options.scope.world_id == "synthetic-world"
    assert options.authorized_transmission is True
    assert options.timeout_ms == 200
    assert options.max_packet_bytes == 8192
    assert "synthetic-user" not in repr(options) and str(db) not in repr(options)
    with pytest.raises(FrozenInstanceError):
        options.scope_alias = "different"


@pytest.mark.parametrize("field", ["database", "scope_config"])
def test_missing_existing_file_never_creates_it(tmp_path, field):
    db, scopes = files(tmp_path)
    missing = db.parent / "absent"
    values = {"database": db, "scope_config": scopes}
    values[field] = missing
    with pytest.raises(ConfigurationError, match="memory_.*unavailable"):
        load_memory_recall_options(**values, scope_alias="local", authorized_transmission=True,
                                  checkout_root=tmp_path / "checkout")
    assert not missing.exists()


@pytest.mark.parametrize("field", ["database", "scope_config"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public"])
def test_unsafe_files_are_rejected_without_repair(tmp_path, field, kind):
    db, scopes = files(tmp_path)
    original = db if field == "database" else scopes
    path = original
    if kind == "symlink":
        path = original.with_suffix(".link")
        path.symlink_to(original)
    elif kind == "hardlink":
        path = original.with_suffix(".link")
        path.hardlink_to(original)
    else:
        original.chmod(0o644)
    values = {"database": db, "scope_config": scopes}; values[field] = path
    with pytest.raises(ConfigurationError, match="memory_.*private"):
        load_memory_recall_options(**values, scope_alias="local", authorized_transmission=True,
                                  checkout_root=tmp_path / "checkout")


def test_checkout_paths_and_public_parent_are_rejected(tmp_path):
    db, scopes = files(tmp_path)
    with pytest.raises(ConfigurationError, match="outside_checkout"):
        load_memory_recall_options(database=db, scope_config=scopes, scope_alias="local",
            authorized_transmission=True, checkout_root=tmp_path)
    db.parent.chmod(0o755)
    with pytest.raises(ConfigurationError, match="private"):
        load(tmp_path, db, scopes)


def test_writable_nonsticky_ancestor_is_rejected(tmp_path):
    unsafe = tmp_path / "shared"
    unsafe.mkdir(mode=0o700)
    db, scopes = files(unsafe)
    unsafe.chmod(0o777)
    with pytest.raises(ConfigurationError, match="not_private"):
        load(tmp_path, db, scopes)


@pytest.mark.parametrize("document", [
    '{"version":1,"version":1,"scopes":[]}',
    '{"version":true,"scopes":[]}',
    '{"version":1,"scopes":[],"unexpected":"private-text"}',
    '{"version":1,"scopes":[{"name":"local","user_id":"private-text"}]}',
])
def test_invalid_scope_schema_has_safe_fixed_error(tmp_path, document):
    db, scopes = files(tmp_path); scopes.write_text(document)
    with pytest.raises(ConfigurationError, match="memory_scope_config_invalid") as failure:
        load(tmp_path, db, scopes)
    assert "private-text" not in str(failure.value)


def test_unknown_scope_and_query_limits_fail_closed(tmp_path):
    db, scopes = files(tmp_path)
    with pytest.raises(ConfigurationError, match="memory_scope_unavailable"):
        load_memory_recall_options(database=db, scope_config=scopes, scope_alias="other",
            authorized_transmission=True, checkout_root=tmp_path / "checkout")
    for limits in ({"timeout_ms": True}, {"timeout_ms": 1001},
                   {"max_packet_bytes": 32769}, {"max_packet_bytes": 1023}):
        with pytest.raises(ConfigurationError, match="memory_limits_invalid"):
            load(tmp_path, db, scopes, **limits)
