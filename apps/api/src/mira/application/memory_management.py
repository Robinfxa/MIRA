"""Use case for user-confirmed edits to the fixed local memory scope."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Self

from mira.application.ports.memory_management import (
    MemoryManagementBackend,
    MemoryManagementCommand,
    MemoryManagementOperation,
    MemoryManagementOperationResult,
    MemoryManagementPage,
    MAX_MANAGEMENT_PAGE_ITEMS,
)
from mira.domain.memory import MemoryKind

MAX_MANAGEMENT_TEXT_CHARS = 4_096
MAX_MANAGEMENT_TEXT_BYTES = 16_384
class MemoryManagementError(RuntimeError):
    """Fixed non-content-revealing failure from the local management use case."""

    code = "memory_management_unavailable"


class MemoryManagementAuthorizationError(MemoryManagementError):
    code = "memory_management_consent_required"


class MemoryManagementUnavailableError(MemoryManagementError):
    code = "memory_management_unavailable"


class MemoryManagementValidationError(MemoryManagementError):
    code = "invalid_request"


class MemoryManagementOutcomeUnknownError(MemoryManagementError):
    """A manager closed after dispatch; the durable operation ID must be reconciled."""

    code = "memory_management_timeout"


@dataclass(frozen=True, slots=True)
class MemoryManagementStatus:
    enabled: bool
    revision: int


class MemoryManagement:
    """Application facade; every operation is bound by its adapter's fixed scope."""

    def __init__(self, backend: MemoryManagementBackend, *, authorized: bool = False) -> None:
        if type(authorized) is not bool:
            raise ValueError("memory_management_authorization_invalid")
        if not all(callable(getattr(backend, name, None)) for name in (
                "open", "scope_revision", "list_entries", "apply_operation", "aclose")):
            raise ValueError("memory_management_backend_invalid")
        self._backend = backend
        self._authorized = authorized
        self._state = "new"
        self._generation = 0
        self._close_lock = asyncio.Lock()

    @property
    def is_open(self) -> bool:
        return self._state == "open"

    async def open(self) -> Self:
        """Start the writer only after the independent local opt-in is explicit."""
        if self._state == "open":
            return self
        if not self._authorized:
            raise MemoryManagementAuthorizationError("memory_management_consent_required")
        if self._state != "new":
            raise MemoryManagementUnavailableError("memory_management_unavailable")
        self._state = "opening"
        self._generation += 1
        generation = self._generation
        try:
            await self._backend.open()
        except BaseException:
            if self._state == "opening" and self._generation == generation:
                self._state = "failed"
            raise
        if self._state != "opening" or self._generation != generation:
            try:
                await self._backend.aclose()
            except Exception:
                pass
            raise MemoryManagementUnavailableError("memory_management_unavailable")
        self._state = "open"
        return self

    async def status(self) -> MemoryManagementStatus:
        generation = self._require_open()
        revision = await self._backend.scope_revision()
        self._require_same_open_generation(generation)
        return MemoryManagementStatus(enabled=True, revision=revision)

    async def list_entries(
        self, *, limit: int = 20, cursor: str | None = None
    ) -> MemoryManagementPage:
        generation = self._require_open()
        if type(limit) is not int or not 1 <= limit <= MAX_MANAGEMENT_PAGE_ITEMS:
            raise MemoryManagementValidationError("invalid_request")
        if cursor is not None and (type(cursor) is not str or not 1 <= len(cursor) <= 64):
            raise MemoryManagementValidationError("invalid_request")
        page = await self._backend.list_entries(limit=limit, cursor=cursor)
        self._require_same_open_generation(generation)
        return page

    async def apply_operation(
        self, command: MemoryManagementCommand
    ) -> MemoryManagementOperationResult:
        generation = self._require_open()
        self._validate_command(command)
        result = await self._backend.apply_operation(command)
        if self._state != "open" or self._generation != generation:
            raise MemoryManagementOutcomeUnknownError(
                "memory_management_outcome_unknown"
            )
        return result

    async def aclose(self) -> None:
        async with self._close_lock:
            if self._state == "closed":
                return
            self._state = "closing"
            self._generation += 1
            try:
                await self._backend.aclose()
            finally:
                self._state = "closed"

    def _require_open(self) -> int:
        if self._state != "open":
            raise MemoryManagementUnavailableError("memory_management_unavailable")
        return self._generation

    def _require_same_open_generation(self, generation: int) -> None:
        if self._state != "open" or self._generation != generation:
            raise MemoryManagementUnavailableError("memory_management_unavailable")

    @staticmethod
    def _validate_command(command: MemoryManagementCommand) -> None:
        if type(command) is not MemoryManagementCommand or command.confirmed is not True:
            raise MemoryManagementValidationError("invalid_request")
        operation = command.operation
        if operation is MemoryManagementOperation.RECORD:
            valid_shape = (type(command.text) is str and command.kind in {
                MemoryKind.EPISODIC, MemoryKind.BOUNDARY,
            } and command.entry_id is None and command.forget_event_id is None)
        elif operation is MemoryManagementOperation.CORRECT:
            valid_shape = (type(command.text) is str and command.kind is None
                           and command.entry_id is not None and command.forget_event_id is None)
        elif operation is MemoryManagementOperation.FORGET:
            valid_shape = (command.text is None and command.kind is None
                           and command.entry_id is not None and command.forget_event_id is None)
        elif operation is MemoryManagementOperation.RESTORE:
            valid_shape = (command.text is None and command.kind is None
                           and command.entry_id is None and command.forget_event_id is not None)
        else:
            valid_shape = False
        if not valid_shape:
            raise MemoryManagementValidationError("invalid_request")
        if command.text is not None:
            try:
                byte_length = len(command.text.encode("utf-8", errors="strict"))
            except UnicodeEncodeError:
                raise MemoryManagementValidationError("invalid_request") from None
            if (not command.text.strip() or len(command.text) > MAX_MANAGEMENT_TEXT_CHARS
                    or byte_length > MAX_MANAGEMENT_TEXT_BYTES):
                raise MemoryManagementValidationError("invalid_request")
