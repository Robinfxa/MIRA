from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import replace

import pytest

from mira.adapters.memory.errors import (
    MemoryConflictError,
    MemoryDeadlineExceededError,
    MemoryEntryNotFoundError,
    MemoryPrivacyError,
    MemoryResultTooLargeError,
    MemoryStoreFullError,
    UnknownMemoryDatabaseError,
    UnsafeMemoryPathError,
)
from mira.adapters.memory.sqlite import SQLiteMemoryStore
from mira.domain.memory import (
    MemoryEntry,
    MemoryKind,
    MemoryMutationKind,
    MemoryQuery,
    MemoryScope,
    MemorySource,
)


@pytest.fixture
def scope() -> MemoryScope:
    return MemoryScope("user-a", "mira", "rain-cafe")


@pytest.fixture
def store(tmp_path):
    result = SQLiteMemoryStore(tmp_path / "private" / "memory.sqlite")
    result.open()
    yield result
    result.close()


def entry(
    scope: MemoryScope,
    event_id: str,
    text: str,
    *,
    entry_id: str | None = None,
    source: MemorySource = MemorySource.USER_STATEMENT,
    version: int = 1,
    kind: MemoryKind = MemoryKind.EPISODIC,
    supersedes_id: str | None = None,
    depends_on: tuple[str, ...] = (),
) -> MemoryEntry:
    return MemoryEntry(
        id=entry_id or f"entry-{event_id}-{version}",
        scope=scope,
        source=source,
        text=text,
        source_event_id=event_id,
        source_version=version,
        recorded_at="2026-10-04T00:00:00.000000+00:00",
        supersedes_id=supersedes_id,
        depends_on=depends_on,
        kind=kind,
    )


def test_constructor_does_no_io_then_explicit_open_creates_private_sqlite(tmp_path):
    path = tmp_path / "private" / "memory.sqlite"
    created = SQLiteMemoryStore(path)
    assert not path.parent.exists()
    with created:
        assert path.is_file()
        if os.name == "posix":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_explicit_existing_writer_never_creates_or_changes_os_modes(tmp_path, scope):
    path = tmp_path / "private" / "memory.sqlite"
    missing = SQLiteMemoryStore(path)
    with pytest.raises(UnsafeMemoryPathError):
        missing.open_existing_writable()
    assert not path.exists()
    assert not path.parent.exists()

    creator = SQLiteMemoryStore(path).open()
    creator.close()
    before = (stat.S_IMODE(path.stat().st_mode), stat.S_IMODE(path.parent.stat().st_mode))
    writer = SQLiteMemoryStore(path).open_existing_writable()
    writer.append(entry(scope, "evt-existing-writer", "I prefer the rain window"))
    writer.close()
    after = (stat.S_IMODE(path.stat().st_mode), stat.S_IMODE(path.parent.stat().st_mode))
    assert before == after == (0o600, 0o700)


@pytest.mark.parametrize("drift", ["replacement", "mode"])
def test_readonly_store_rechecks_path_identity_and_mode_on_every_operation(tmp_path, scope, drift):
    path = tmp_path / "private" / "memory.sqlite"
    SQLiteMemoryStore(path).open().close()
    reader = SQLiteMemoryStore(path).open_readonly()
    try:
        if drift == "replacement":
            replacement = tmp_path / "private" / "replacement.sqlite"
            SQLiteMemoryStore(replacement).open().close()
            os.replace(replacement, path)
        else:
            path.chmod(0o640)
        with pytest.raises(UnsafeMemoryPathError):
            reader.scope_revision(scope)
    finally:
        reader.close()


def test_store_requires_exact_scope_and_preserves_provenance_across_restart(tmp_path, scope):
    path = tmp_path / "private" / "memory.sqlite"
    first = SQLiteMemoryStore(path).open()
    saved = first.append(entry(scope, "evt-user-1", "I prefer the rain window"))
    first.close()

    reopened = SQLiteMemoryStore(path).open()
    try:
        same = reopened.recall(MemoryQuery(scope, "rain window"))
        other = MemoryQuery(MemoryScope("user-b", "mira", "rain-cafe"), "rain window")
        assert same == (saved,)
        assert reopened.recall(other) == ()
        assert same[0].source is MemorySource.USER_STATEMENT
        assert same[0].source_event_id == "evt-user-1"
        assert same[0].source_version == 1
    finally:
        reopened.close()


def test_exact_source_event_retry_is_idempotent_and_payload_or_source_conflicts(store, scope):
    original = entry(scope, "evt-immutable", "I like warm light")
    assert store.append(original) == original
    retry = replace(original, id="different-retry-id", recorded_at="2026-10-05T00:00:00.000000+00:00")
    assert store.append(retry) == original
    conflicting_text = replace(original, id="different", text="I like blue light")
    conflicting_source = replace(original, id="other-source", source=MemorySource.PRESENTATION_RECEIPT)
    with pytest.raises(MemoryConflictError):
        store.append(conflicting_text)
    with pytest.raises(MemoryConflictError):
        store.append(conflicting_source)


def test_later_source_event_version_must_continue_the_supersession_chain(store, scope):
    original = entry(scope, "evt-versioned", "I prefer the cafe window", version=1)
    store.append(original)
    skipped = entry(scope, "evt-versioned", "I prefer the rain window", version=2)
    with pytest.raises(MemoryConflictError):
        store.append(skipped)
    corrected = store.supersede(scope, original.id, skipped)
    assert corrected.source_event_id == original.source_event_id
    assert corrected.source_version == original.source_version + 1
    assert store.recall(MemoryQuery(scope, "cafe")) == (corrected,)


def test_recall_is_deterministic_lexical_and_enforces_count_character_budgets(store, scope):
    store.append(entry(scope, "evt-weak", "Rain makes the cafe feel quiet"))
    strong = entry(scope, "evt-strong", "I remember the rain window and the warm light")
    store.append(strong)
    store.append(entry(scope, "evt-long", "rain " + "warm " * 10))
    query = MemoryQuery(scope, "rain window", limit=2, max_chars=len(strong.text) + 3)
    result = store.recall(query)
    assert result == (strong,)
    assert store.recall(query) == result
    assert sum(len(item.text) for item in result) <= query.max_chars


def test_interpretation_is_not_returned_as_source_fact_by_default(store, scope):
    source = entry(scope, "evt-user", "The user said the rain feels comforting")
    derived = entry(
        scope, "evt-interpretation", "Mira thinks rain is important to the user",
        source=MemorySource.INTERPRETATION, depends_on=(source.id,),
    )
    store.append(source)
    store.append(derived)
    assert store.recall(MemoryQuery(scope, "rain")) == (source,)
    explicit = store.recall(MemoryQuery(scope, "rain", include_interpretations=True))
    assert tuple(item.source for item in explicit) == (
        MemorySource.USER_STATEMENT, MemorySource.INTERPRETATION,
    )


def test_supersession_returns_latest_head_and_never_resurrects_stale_ancestor(store, scope):
    original = entry(scope, "evt-boundary-old", "Please do not photograph me", kind=MemoryKind.BOUNDARY)
    store.append(original)
    corrected = entry(scope, "evt-boundary-corrected", "A photo of the window is okay")
    result = store.supersede(scope, original.id, corrected)
    assert result.kind is MemoryKind.BOUNDARY
    assert result.supersedes_id == original.id
    # Old wording can find the current head, but the obsolete text is never
    # returned as current content.
    assert store.recall(MemoryQuery(scope, "photograph")) == (result,)
    assert store.recall(MemoryQuery(scope, "window")) == (result,)

    forgotten = store.forget(scope, result.id)
    assert forgotten.kind is MemoryMutationKind.FORGET
    assert store.recall(MemoryQuery(scope, "photograph")) == ()
    assert store.recall(MemoryQuery(scope, "window")) == ()
    unrelated = entry(scope, "evt-unrelated", "The cafe has warm light")
    store.append(unrelated)
    assert store.recall(MemoryQuery(scope, "warm")) == (unrelated,)
    history = store.history(scope, original.id)
    assert original in history and result in history and forgotten in history


def test_soft_forget_suppresses_transitive_dependents_and_undo_restores_with_audit(store, scope):
    source = entry(scope, "evt-source", "The user prefers a quiet rain scene")
    child = entry(
        scope, "evt-child", "The user tends to like quiet scenes",
        source=MemorySource.INTERPRETATION, depends_on=(source.id,),
    )
    grandchild = entry(
        scope, "evt-summary", "A quiet scene may suit the user",
        depends_on=(child.id,),
    )
    store.append(source)
    store.append(child)
    store.append(grandchild)
    forget = store.forget(scope, source.id)
    assert store.recall(MemoryQuery(scope, "quiet", include_interpretations=True)) == ()
    assert source in store.history(scope, source.id)

    restored = store.undo_forget(scope, forget.id)
    assert restored.kind is MemoryMutationKind.RESTORE
    assert set(store.recall(MemoryQuery(scope, "quiet", include_interpretations=True))) == {
        child, grandchild, source,
    }
    with pytest.raises(MemoryConflictError):
        store.undo_forget(scope, forget.id)
    assert store.history(scope, source.id) == (source, forget, restored)


def test_overlapping_forgets_restore_only_the_referenced_tombstone(store, scope):
    source = entry(scope, "evt-double-forget", "The user likes rain")
    store.append(source)
    first = store.forget(scope, source.id)
    second = store.forget(scope, source.id)
    store.undo_forget(scope, first.id)
    assert store.recall(MemoryQuery(scope, "rain")) == ()
    store.undo_forget(scope, second.id)
    assert store.recall(MemoryQuery(scope, "rain")) == (source,)


def test_query_timeout_bounds_locked_read_wait(store, scope):
    store.append(entry(scope, "evt-lock", "The user likes rain"))
    blocker = sqlite3.connect(store.path, timeout=0.1, isolation_level=None)
    try:
        blocker.execute("BEGIN EXCLUSIVE")
        with pytest.raises(MemoryDeadlineExceededError):
            store.recall(MemoryQuery(scope, "rain", timeout_ms=10))
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()


def test_scope_revision_is_monotonic_and_isolated_to_exact_scope(store, scope):
    other = MemoryScope("user-b", "mira", "rain-cafe")
    assert store.scope_revision(scope) == 0
    assert store.scope_revision(other) == 0
    saved = store.append(entry(scope, "evt-revision", "The user likes rain"))
    after_append = store.scope_revision(scope)
    assert after_append > 0
    assert store.scope_revision(other) == 0
    forgotten = store.forget(scope, saved.id)
    after_forget = store.scope_revision(scope)
    assert after_forget > after_append
    store.undo_forget(scope, forgotten.id)
    assert store.scope_revision(scope) > after_forget


def test_only_explicit_user_statement_boundary_enters_current_constraints(store, scope):
    boundary = entry(scope, "evt-no-photo", "Do not take a photo of me", kind=MemoryKind.BOUNDARY)
    store.append(boundary)
    assert store.current_constraints(scope) == (boundary,)
    authored = entry(
        scope, "evt-authored-boundary", "Mira avoids photographing strangers",
        source=MemorySource.AUTHORED_BACKSTORY, kind=MemoryKind.BOUNDARY,
    )
    with pytest.raises(ValueError):
        store.append(authored)

    updated = entry(scope, "evt-updated-boundary", "A photo of the rain window is fine")
    replacement = store.supersede(scope, boundary.id, updated)
    assert replacement.kind is MemoryKind.BOUNDARY
    assert store.current_constraints(scope) == (replacement,)
    forgotten = store.forget(scope, replacement.id)
    assert store.current_constraints(scope) == ()
    store.undo_forget(scope, forgotten.id)
    assert store.current_constraints(scope) == (replacement,)


def test_an_interpretation_cannot_supersede_and_hide_source_evidence(store, scope):
    source = entry(scope, "evt-authoritative", "The user prefers warm light")
    store.append(source)
    proposal = entry(
        scope, "evt-interpretation-proposal", "Mira infers the user likes warm light",
        source=MemorySource.INTERPRETATION,
    )
    with pytest.raises(MemoryConflictError):
        store.supersede(scope, source.id, proposal)
    assert store.recall(MemoryQuery(scope, "warm")) == (source,)


def test_store_rejects_credential_envelopes_or_any_privacy_filter_change(store, scope):
    unsafe_text = 'The token is "synthetic-api-key-123456"'
    candidate = entry(scope, "evt-secret-shape", unsafe_text)
    with pytest.raises(MemoryPrivacyError) as caught:
        store.append(candidate)
    assert unsafe_text not in str(caught.value)
    assert store.recall(MemoryQuery(scope, "token")) == ()


def test_storage_and_event_history_have_hard_bounds(tmp_path, scope):
    store = SQLiteMemoryStore(tmp_path / "limited" / "memory.sqlite", max_records=1,
                              max_entry_chars=128).open()
    try:
        first = entry(scope, "evt-only", "The user likes rain")
        store.append(first)
        with pytest.raises(MemoryStoreFullError):
            store.append(entry(scope, "evt-over-count", "The user likes warmth"))
        with pytest.raises(MemoryStoreFullError):
            store.append(entry(scope, "evt-over-text", "x" * 129))
        forget = store.forget(scope, first.id)
        store.undo_forget(scope, forget.id)
        with pytest.raises(MemoryStoreFullError):
            store.forget(scope, first.id)
    finally:
        store.close()


def test_current_constraint_overflow_fails_closed_instead_of_truncating(store, scope):
    # Lower the class-independent public bound without constructing live/user data.
    # 65 tiny independent BOUNDARY rows exceed the count limit of 64.
    for index in range(65):
        store.append(entry(
            scope, f"evt-boundary-{index}", f"Boundary {index}", kind=MemoryKind.BOUNDARY,
        ))
    with pytest.raises(MemoryResultTooLargeError):
        store.current_constraints(scope)


def test_unknown_existing_database_is_rejected_without_schema_changes(tmp_path):
    path = tmp_path / "private" / "memory.sqlite"
    path.parent.mkdir(mode=0o700)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE user_data(secret TEXT)")
    if os.name == "posix":
        path.chmod(0o600)
    with pytest.raises(UnknownMemoryDatabaseError):
        SQLiteMemoryStore(path).open()
    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "user_data" in tables and "memory_entries" not in tables


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and mode checks")
def test_existing_unsafe_file_or_directory_is_rejected_without_chmod(tmp_path):
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    unsafe_file = parent / "unsafe.sqlite"
    unsafe_file.write_bytes(b"")
    unsafe_file.chmod(0o644)
    with pytest.raises(UnsafeMemoryPathError):
        SQLiteMemoryStore(unsafe_file).open()
    assert stat.S_IMODE(unsafe_file.stat().st_mode) == 0o644

    public_parent = tmp_path / "public"
    public_parent.mkdir(mode=0o700)
    public_parent.chmod(0o755)
    with pytest.raises(UnsafeMemoryPathError):
        SQLiteMemoryStore(public_parent / "memory.sqlite").open()
    assert stat.S_IMODE(public_parent.stat().st_mode) == 0o755


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symbolic links are unavailable")
def test_symlinked_database_and_parent_are_rejected(tmp_path):
    safe = SQLiteMemoryStore(tmp_path / "safe" / "memory.sqlite").open()
    safe.close()
    target = tmp_path / "safe" / "memory.sqlite"
    file_link = tmp_path / "safe" / "linked.sqlite"
    file_link.symlink_to(target)
    with pytest.raises(UnsafeMemoryPathError):
        SQLiteMemoryStore(file_link).open()

    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(target.parent, target_is_directory=True)
    with pytest.raises(UnsafeMemoryPathError):
        SQLiteMemoryStore(parent_link / "memory.sqlite").open()


@pytest.mark.skipif(not hasattr(os, "link"), reason="hard links are unavailable")
def test_hardlinked_database_inode_is_rejected(tmp_path):
    source = tmp_path / "private" / "existing.sqlite"
    source.parent.mkdir(mode=0o700)
    source.write_bytes(b"x")
    if os.name == "posix":
        source.chmod(0o600)
    linked = source.parent / "memory.sqlite"
    os.link(source, linked)
    with pytest.raises(UnsafeMemoryPathError):
        SQLiteMemoryStore(linked).open()


def test_source_scope_and_query_bounds_are_validated(scope):
    with pytest.raises(ValueError):
        MemoryScope("", "mira", "rain-cafe")
    with pytest.raises(ValueError):
        MemoryEntry("x", scope, "user_statement", "text", "evt", 1)
    with pytest.raises(ValueError):
        MemoryQuery(scope, "rain", limit=101)
    with pytest.raises(ValueError):
        MemoryQuery(scope, "rain", max_chars=0)
    with pytest.raises(ValueError):
        MemoryQuery(scope, "rain", timeout_ms=1)
