from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from mira.adapters.memory.errors import MemoryEntryNotFoundError, MemoryRevisionChangedError
from mira.adapters.memory.sqlite import SQLiteMemoryStore
from mira.application.ports.memory_management import (
    MemoryManagementCommand,
    MemoryManagementOperation,
)
from mira.domain.memory import (
    MemoryEntry, MemoryKind, MemoryMutationKind, MemoryQuery, MemoryScope, MemorySource,
)


def _entry(scope: MemoryScope, source_event_id: str, text: str, *, version: int = 1,
           entry_id: str | None = None, source: MemorySource = MemorySource.USER_STATEMENT,
           kind: MemoryKind = MemoryKind.EPISODIC, supersedes_id: str | None = None) -> MemoryEntry:
    return MemoryEntry(
        id=entry_id or f"entry-{source_event_id}-{version}",
        scope=scope,
        source=source,
        text=text,
        source_event_id=source_event_id,
        source_version=version,
        recorded_at="2026-10-04T00:00:00+00:00",
        supersedes_id=supersedes_id,
        kind=kind,
    )


def _command(op_id: str, revision: int, operation: MemoryManagementOperation, **values):
    return MemoryManagementCommand(
        operation_id=op_id,
        expected_revision=revision,
        operation=operation,
        confirmed=True,
        **values,
    )


def test_list_is_bounded_to_user_statement_heads_and_reversible_tombstone(tmp_path):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    store = SQLiteMemoryStore(tmp_path / "private" / "memory.sqlite").open()
    try:
        original = _entry(scope, "evt-preference", "I prefer the cafe window")
        store.append(original)
        store.append(_entry(scope, "evt-private", "The author wrote a secret history",
                            source=MemorySource.AUTHORED_BACKSTORY))
        store.append(_entry(scope, "evt-interpretation", "The user probably likes rain",
                            source=MemorySource.INTERPRETATION))
        second = _entry(scope, "evt-second", "I like soft light")
        store.append(second)
        corrected = _entry(scope, "evt-preference", "I prefer the rain window", version=2)
        corrected = store.supersede(scope, original.id, corrected)
        forgotten = store.forget(scope, corrected.id)

        first_page = store.management_list(scope, limit=1)
        assert first_page.revision == store.scope_revision(scope)
        assert len(first_page.entries) == 1
        item = first_page.entries[0]
        assert item.entry_id == corrected.id
        assert item.text == "I prefer the rain window"
        assert item.kind is MemoryKind.EPISODIC
        assert item.active is False
        assert item.forget_event_id == forgotten.id
        assert item.forgotten_at == forgotten.recorded_at
        assert first_page.next_cursor is not None

        second_page = store.management_list(scope, limit=1, cursor=first_page.next_cursor)
        assert len(second_page.entries) == 1
        assert second_page.entries[0].entry_id == second.id
        assert second_page.entries[0].active is True
        assert second_page.next_cursor is None
        returned_ids = {item.entry_id for page in (first_page, second_page) for item in page.entries}
        assert original.id not in returned_ids
        assert returned_ids == {corrected.id, second.id}

        stale_cursor = first_page.next_cursor
        store.append(_entry(scope, "evt-new", "I like warm light"))
        with pytest.raises(MemoryRevisionChangedError):
            store.management_list(scope, limit=1, cursor=stale_cursor)
    finally:
        store.close()


def test_expected_revision_compare_and_write_is_atomic_and_scope_fixed(tmp_path):
    path = tmp_path / "private" / "memory.sqlite"
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    other_scope = MemoryScope("user-b", "mira", "rain-cafe")
    store = SQLiteMemoryStore(path).open()
    other = _entry(other_scope, "evt-other", "I like blue light")
    store.append(other)
    try:
        original = _entry(scope, "evt-parent", "I prefer the cafe window")
        store.append(original)
        expected = store.scope_revision(scope)
        store.append(_entry(scope, "evt-cli-race", "I like a quiet scene"))
        stale = _command(
            str(UUID("00000000-0000-4000-8000-000000000001")), expected,
            MemoryManagementOperation.RECORD,
            text="I prefer the rain window", kind=MemoryKind.EPISODIC,
        )
        with pytest.raises(MemoryRevisionChangedError):
            store.management_apply(scope, stale)
        assert store.scope_revision(scope) == expected + 1

        current = store.scope_revision(scope)
        corrected = _command(
            str(UUID("00000000-0000-4000-8000-000000000002")), current,
            MemoryManagementOperation.CORRECT,
            text="I prefer the rain window", entry_id=original.id,
        )
        result = store.management_apply(scope, corrected)
        assert result.status == "committed"
        assert result.revision == current + 1
        assert result.entry_id == corrected.operation_id
        head = store.recall(MemoryQuery(scope, "rain window"))
        assert len(head) == 1
        assert head[0].source is MemorySource.USER_STATEMENT
        assert head[0].supersedes_id == original.id
        assert head[0].source_event_id == original.source_event_id
        assert head[0].source_version == original.source_version + 1

        cross_scope_forget = _command(
            str(UUID("00000000-0000-4000-8000-000000000003")), store.scope_revision(scope),
            MemoryManagementOperation.FORGET, entry_id=other.id,
        )
        with pytest.raises(MemoryEntryNotFoundError):
            store.management_apply(scope, cross_scope_forget)
    finally:
        store.close()


def test_exact_operation_replay_is_idempotent_and_changed_body_conflicts(tmp_path):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    store = SQLiteMemoryStore(tmp_path / "private" / "memory.sqlite").open()
    try:
        record = _command(
            str(UUID("00000000-0000-4000-8000-000000000010")), 0,
            MemoryManagementOperation.RECORD,
            text="I prefer the rain window", kind=MemoryKind.BOUNDARY,
        )
        first = store.management_apply(scope, record)
        replay = store.management_apply(scope, record)
        assert replay.status == "committed"
        assert replay.replayed is True
        assert replay.entry_id == first.entry_id == record.operation_id
        assert replay.revision == first.revision
        assert store.scope_revision(scope) == 1
        assert len(store.history(scope, limit=10)) == 1

        changed = replace(record, text="I prefer the cafe window")
        with pytest.raises(Exception) as conflict:
            store.management_apply(scope, changed)
        assert conflict.type.__name__ == "MemoryManagementOperationIdConflictError"

        forget_command = _command(
            str(UUID("00000000-0000-4000-8000-000000000011")), store.scope_revision(scope),
            MemoryManagementOperation.FORGET, entry_id=record.operation_id,
        )
        forgotten = store.management_apply(scope, forget_command)
        again = store.management_apply(scope, forget_command)
        assert forgotten.event_id == again.event_id == forget_command.operation_id
        assert again.replayed is True
        assert sum(item.kind is MemoryMutationKind.FORGET for item in store.history(scope, limit=10)) == 1

        restore = _command(
            str(UUID("00000000-0000-4000-8000-000000000012")), store.scope_revision(scope),
            MemoryManagementOperation.RESTORE, forget_event_id=forgotten.event_id,
        )
        restored = store.management_apply(scope, restore)
        replayed_restore = store.management_apply(scope, restore)
        assert restored.event_id == replayed_restore.event_id == restore.operation_id
        assert replayed_restore.replayed is True
        history = store.history(scope, limit=10)
        assert sum(item.kind is MemoryMutationKind.FORGET for item in history) == 1
        assert sum(item.kind is MemoryMutationKind.RESTORE for item in history) == 1
    finally:
        store.close()
