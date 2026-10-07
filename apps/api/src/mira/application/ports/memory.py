"""Application-facing port for explicitly composed, opt-in evidence storage."""

from typing import Protocol

from mira.domain.memory import (
    MemoryEntry,
    MemoryHistoryItem,
    MemoryMutation,
    MemoryQuery,
    MemoryScope,
)


class MemoryPort(Protocol):
    def scope_revision(self, scope: MemoryScope) -> int:
        """Read the monotonic append-only revision for a scope snapshot guard."""
        ...

    def append(self, entry: MemoryEntry) -> MemoryEntry:
        """Append immutable evidence; exact source-event retries are idempotent."""
        ...

    def recall(self, query: MemoryQuery) -> tuple[MemoryEntry, ...]:
        """Return bounded, scoped, typed evidence only; never execution authority."""
        ...

    def current_constraints(self, scope: MemoryScope) -> tuple[MemoryEntry, ...]:
        """Return effective explicit BOUNDARY heads, or fail if bounds are exceeded."""
        ...

    def supersede(
        self, scope: MemoryScope, old_id: str, replacement: MemoryEntry
    ) -> MemoryEntry:
        """Append a replacement while permanently suppressing obsolete ancestors."""
        ...

    def forget(self, scope: MemoryScope, entry_id: str) -> MemoryMutation:
        """Append a reversible soft-forget event. This is not physical deletion."""
        ...

    def undo_forget(self, scope: MemoryScope, forget_event_id: str) -> MemoryMutation:
        """Append an audit event restoring one active forget event."""
        ...

    def history(
        self, scope: MemoryScope, entry_id: str | None = None, limit: int = 100
    ) -> tuple[MemoryHistoryItem, ...]:
        """Read a bounded, append-only source and mutation history."""
        ...
