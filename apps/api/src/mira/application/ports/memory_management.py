"""Typed, scope-free app boundary for explicit local memory management."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from mira.domain.memory import MemoryKind

MAX_MANAGEMENT_PAGE_ITEMS = 20


class MemoryManagementBackendError(RuntimeError):
    """Stable application boundary for safe, fixed-code storage failures."""

    code = "memory_management_unavailable"


class MemoryManagementBackendUnavailableError(MemoryManagementBackendError):
    code = "memory_management_unavailable"


class MemoryManagementBackendBusyError(MemoryManagementBackendError):
    code = "memory_management_busy"


class MemoryManagementBackendOperationIdConflictError(MemoryManagementBackendError):
    code = "operation_id_conflict"


class MemoryManagementBackendConflictError(MemoryManagementBackendError):
    code = "operation_conflict"


class MemoryManagementBackendEntryNotFoundError(MemoryManagementBackendError):
    code = "entry_not_found"


class MemoryManagementBackendTextRejectedError(MemoryManagementBackendError):
    code = "statement_ineligible"


class MemoryManagementBackendLimitError(MemoryManagementBackendError):
    code = "memory_store_full"


class MemoryManagementOperation(StrEnum):
    RECORD = "record"
    CORRECT = "correct"
    FORGET = "forget"
    RESTORE = "restore"


@dataclass(frozen=True, slots=True)
class MemoryManagementCommand:
    """Exact operation submitted after local user confirmation.

    No scope or source field exists here: those are fixed by the server-side
    backend. Operation-specific shape is validated again in the application
    service so non-HTTP callers cannot bypass it.
    """

    operation_id: str
    expected_revision: int
    operation: MemoryManagementOperation
    confirmed: bool
    text: str | None = None
    kind: MemoryKind | None = None
    entry_id: str | None = None
    forget_event_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.operation_id) is not str:
            raise ValueError("operation_id_invalid")
        try:
            canonical_id = str(UUID(self.operation_id))
        except (ValueError, AttributeError, TypeError):
            raise ValueError("operation_id_invalid") from None
        object.__setattr__(self, "operation_id", canonical_id)
        if (type(self.expected_revision) is not int or self.expected_revision < 0
                or not isinstance(self.operation, MemoryManagementOperation)
                or type(self.confirmed) is not bool):
            raise ValueError("management_command_invalid")
        if self.text is not None and type(self.text) is not str:
            raise ValueError("management_command_invalid")
        if self.kind is not None and not isinstance(self.kind, MemoryKind):
            raise ValueError("management_command_invalid")
        for value in (self.entry_id, self.forget_event_id):
            if value is not None and (
                    type(value) is not str or not 1 <= len(value) <= 128
                    or any(ord(char) < 33 or ord(char) == 127 or char.isspace() for char in value)):
                raise ValueError("management_command_invalid")


@dataclass(frozen=True, slots=True)
class MemoryManagementEntry:
    entry_id: str
    text: str
    kind: MemoryKind
    source_version: int
    recorded_at: str
    active: bool
    forget_event_id: str | None = None
    forgotten_at: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryManagementPage:
    revision: int
    entries: tuple[MemoryManagementEntry, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class MemoryManagementOperationResult:
    status: str
    operation_id: str
    revision: int
    entry_id: str | None = None
    event_id: str | None = None
    replayed: bool = False


class MemoryManagementBackend(Protocol):
    """Single fixed-scope store adapter; receives no caller-selected scope."""

    async def open(self) -> MemoryManagementBackend: ...
    async def scope_revision(self) -> int: ...
    async def list_entries(self, *, limit: int, cursor: str | None) -> MemoryManagementPage: ...
    async def apply_operation(
        self, command: MemoryManagementCommand
    ) -> MemoryManagementOperationResult: ...
    async def aclose(self) -> None: ...
