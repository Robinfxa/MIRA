"""Fixed, non-content-revealing adapter errors for local memory operations."""

from mira.domain.memory import MemoryDeadlineExceededError, MemoryRevisionChangedError


class MemoryStoreError(RuntimeError):
    """Base class; messages never contain stored text or filesystem content."""


class MemoryStoreClosedError(MemoryStoreError):
    pass


class UnsafeMemoryPathError(MemoryStoreError):
    pass


class UnknownMemoryDatabaseError(MemoryStoreError):
    pass


class MemoryConflictError(MemoryStoreError):
    pass


class MemoryManagementOperationIdConflictError(MemoryConflictError):
    """An operation UUID was already used for a different exact request body."""


class MemoryManagementBusyError(MemoryStoreError):
    """The bounded single-writer management worker or SQLite store is busy."""


class MemoryEntryNotFoundError(MemoryStoreError):
    pass


class MemoryStoreFullError(MemoryStoreError):
    pass


class MemoryPrivacyError(MemoryStoreError):
    pass


class MemoryResultTooLargeError(MemoryStoreError):
    pass
