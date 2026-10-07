"""Single-worker async bridge for explicit writes to an existing private store."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

from mira.adapters.memory.errors import (
    MemoryConflictError as AdapterMemoryConflictError,
    MemoryEntryNotFoundError as AdapterMemoryEntryNotFoundError,
    MemoryManagementBusyError as AdapterMemoryManagementBusyError,
    MemoryManagementOperationIdConflictError as AdapterMemoryOperationIdConflictError,
    MemoryPrivacyError as AdapterMemoryPrivacyError,
    MemoryResultTooLargeError as AdapterMemoryResultTooLargeError,
    MemoryStoreClosedError as AdapterMemoryStoreClosedError,
    MemoryStoreError as AdapterMemoryStoreError,
    MemoryStoreFullError as AdapterMemoryStoreFullError,
)
from mira.adapters.memory.sqlite import SQLiteMemoryStore
from mira.application.ports.memory_management import (
    MemoryManagementBackendBusyError,
    MemoryManagementBackendConflictError,
    MemoryManagementBackendEntryNotFoundError,
    MemoryManagementBackendLimitError,
    MemoryManagementBackendOperationIdConflictError,
    MemoryManagementBackendTextRejectedError,
    MemoryManagementBackendUnavailableError,
    MemoryManagementCommand,
    MemoryManagementOperationResult,
    MemoryManagementPage,
    MAX_MANAGEMENT_PAGE_ITEMS,
)
from mira.domain.memory import MemoryDeadlineExceededError, MemoryScope

_T = TypeVar("_T")


def _translate_store_error(error: Exception) -> Exception:
    """Normalize adapter failures before crossing the application boundary."""
    if isinstance(error, AdapterMemoryManagementBusyError):
        return MemoryManagementBackendBusyError("memory_management_busy")
    if isinstance(error, AdapterMemoryOperationIdConflictError):
        return MemoryManagementBackendOperationIdConflictError("operation_id_conflict")
    if isinstance(error, AdapterMemoryEntryNotFoundError):
        return MemoryManagementBackendEntryNotFoundError("entry_not_found")
    if isinstance(error, AdapterMemoryConflictError):
        return MemoryManagementBackendConflictError("operation_conflict")
    if isinstance(error, AdapterMemoryPrivacyError):
        return MemoryManagementBackendTextRejectedError("statement_ineligible")
    if isinstance(error, AdapterMemoryResultTooLargeError):
        return MemoryManagementBackendLimitError("memory_store_full")
    if isinstance(error, AdapterMemoryStoreFullError):
        return MemoryManagementBackendLimitError("memory_store_full")
    if isinstance(error, (AdapterMemoryStoreClosedError, AdapterMemoryStoreError)):
        return MemoryManagementBackendUnavailableError("memory_management_unavailable")
    return error


@dataclass(slots=True)
class _ManagementRequest:
    deadline: float
    work: Callable[[], object]
    mutation: bool
    future: concurrent.futures.Future[object] = field(
        default_factory=concurrent.futures.Future
    )
    cancelled: threading.Event = field(default_factory=threading.Event)


class AsyncSQLiteMemoryManagement:
    """Fixed-scope store adapter with one thread and no unbounded work queue.

    Construction is inert. ``open`` is the only operation that opens the
    existing store; unlike the store's ordinary CLI ``open``, it never creates
    a missing path or changes OS permissions. A concurrent request is rejected
    as busy rather than enqueued.
    """

    def __init__(self, path: str | os.PathLike[str], fixed_scope: MemoryScope, *,
                 timeout_ms: int = 200, mutation_timeout_ms: int = 1_000) -> None:
        self._store = SQLiteMemoryStore(path)
        if not isinstance(fixed_scope, MemoryScope):
            raise ValueError("an explicit MemoryScope is required")
        if (type(timeout_ms) is not int or not 10 <= timeout_ms <= 1_000
                or type(mutation_timeout_ms) is not int
                or not 50 <= mutation_timeout_ms <= 2_000):
            raise ValueError("memory management timeout is out of range")
        self._fixed_scope = fixed_scope
        self._timeout_ms = timeout_ms
        self._mutation_timeout_ms = mutation_timeout_ms
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._startup: concurrent.futures.Future[None] | None = None
        self._terminated: concurrent.futures.Future[None] | None = None
        self._request: _ManagementRequest | None = None
        self._active: _ManagementRequest | None = None
        self._state = "new"
        self._close_requested = False
        self._close_wait_seconds = 1.0

    async def open(self) -> AsyncSQLiteMemoryManagement:
        """Explicitly open the existing private database on the owner worker."""
        asyncio.get_running_loop()
        with self._condition:
            if self._state == "open":
                return self
            if self._state != "new":
                raise MemoryManagementBackendUnavailableError("local memory management is closed")
            self._state = "opening"
            self._startup = concurrent.futures.Future()
            self._terminated = concurrent.futures.Future()
            self._thread = threading.Thread(
                target=self._worker, name="mira-memory-management", daemon=True
            )
            thread = self._thread
            startup = self._startup
            thread.start()
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(startup)),
                timeout=self._timeout_ms / 1_000 + 0.15,
            )
        except asyncio.TimeoutError:
            self._request_close(interrupt=True)
            await self._wait_for_worker_briefly()
            raise MemoryDeadlineExceededError(
                "local memory management open exceeded its time bound"
            ) from None
        except asyncio.CancelledError:
            self._request_close(interrupt=True)
            await self._wait_for_worker_briefly()
            raise
        except Exception as error:
            self._request_close(interrupt=True)
            await self._wait_for_worker_briefly()
            translated = _translate_store_error(error)
            if translated is error:
                raise
            raise translated from None
        with self._condition:
            if self._state != "open" or self._close_requested:
                raise MemoryManagementBackendUnavailableError("local memory management is closed")
        return self

    async def scope_revision(self) -> int:
        deadline = time.monotonic() + self._timeout_ms / 1_000

        def work() -> int:
            with self._store._bounded_read_deadline(deadline):
                return self._store.scope_revision(self._fixed_scope)

        try:
            return await self._submit(deadline, work, mutation=False)  # type: ignore[return-value]
        except asyncio.CancelledError:
            raise
        except Exception as error:
            translated = _translate_store_error(error)
            if translated is error:
                raise
            raise translated from None

    async def list_entries(self, *, limit: int = 20,
                           cursor: str | None = None) -> MemoryManagementPage:
        if type(limit) is not int or not 1 <= limit <= MAX_MANAGEMENT_PAGE_ITEMS:
            raise ValueError("management list limit is out of range")
        if cursor is not None and (type(cursor) is not str or not 1 <= len(cursor) <= 64):
            raise ValueError("memory_cursor_invalid")
        deadline = time.monotonic() + self._timeout_ms / 1_000

        def work() -> MemoryManagementPage:
            with self._store._bounded_read_deadline(deadline):
                return self._store.management_list(
                    self._fixed_scope, limit=limit, cursor=cursor
                )

        try:
            return await self._submit(deadline, work, mutation=False)  # type: ignore[return-value]
        except asyncio.CancelledError:
            raise
        except Exception as error:
            translated = _translate_store_error(error)
            if translated is error:
                raise
            raise translated from None

    async def apply_operation(
        self, command: MemoryManagementCommand
    ) -> MemoryManagementOperationResult:
        if not isinstance(command, MemoryManagementCommand):
            raise ValueError("a typed memory-management command is required")
        deadline = time.monotonic() + self._mutation_timeout_ms / 1_000

        def work() -> MemoryManagementOperationResult:
            with self._store._bounded_management_deadline(deadline):
                return self._store.management_apply(self._fixed_scope, command)

        try:
            return await self._submit(deadline, work, mutation=True)  # type: ignore[return-value]
        except asyncio.CancelledError:
            raise
        except Exception as error:
            translated = _translate_store_error(error)
            if translated is error:
                raise
            raise translated from None

    async def aclose(self) -> None:
        self._request_close(interrupt=True)
        await self._wait_for_worker_briefly(raise_on_timeout=True)

    async def _submit(self, deadline: float, work: Callable[[], _T], *,
                      mutation: bool) -> _T:
        with self._condition:
            if self._state != "open" or self._close_requested:
                raise MemoryManagementBackendUnavailableError("local memory management is closed")
            if self._request is not None or self._active is not None:
                raise AdapterMemoryManagementBusyError("memory_management_busy")
            request = _ManagementRequest(deadline, work, mutation)
            self._active = request
            self._request = request
            self._condition.notify()
        try:
            timeout = max(0.0, deadline - time.monotonic()) + 0.05
            return await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(request.future)), timeout=timeout
            )  # type: ignore[return-value]
        except asyncio.TimeoutError:
            self._cancel_request(request, interrupt=not mutation)
            raise MemoryDeadlineExceededError(
                "local memory management request exceeded its time bound"
            ) from None
        except asyncio.CancelledError:
            # Submitted mutations finish their short transaction when possible;
            # a durable UUID makes a post-commit disconnect reconcilable.
            self._cancel_request(request, interrupt=not mutation)
            raise

    def _cancel_request(self, request: _ManagementRequest, *, interrupt: bool) -> None:
        connection = None
        with self._condition:
            request.cancelled.set()
            if self._request is request:
                self._request = None
                if self._active is request:
                    self._active = None
            elif self._active is request and interrupt:
                connection = self._store._connection
            request.future.cancel()
            self._condition.notify_all()
        if connection is not None:
            try:
                connection.interrupt()
            except Exception:
                pass

    def _request_close(self, *, interrupt: bool) -> None:
        connection = None
        with self._condition:
            if self._state in {"closed", "failed"}:
                return
            prior_state = self._state
            self._close_requested = True
            if self._thread is None:
                self._state = "closed"
                self._condition.notify_all()
                return
            self._state = "closing"
            operation = self._active
            if self._request is not None:
                self._request.cancelled.set()
                self._request.future.cancel()
                self._request = None
                self._active = None
            elif operation is not None:
                operation.cancelled.set()
                operation.future.cancel()
                if interrupt:
                    connection = self._store._connection
            elif interrupt and prior_state == "opening":
                connection = self._store._connection
            self._condition.notify_all()
        if connection is not None:
            try:
                connection.interrupt()
            except Exception:
                pass

    async def _wait_for_worker_briefly(self, *, raise_on_timeout: bool = False) -> None:
        with self._condition:
            terminated = self._terminated
        if terminated is None:
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(terminated)),
                timeout=self._close_wait_seconds,
            )
        except asyncio.TimeoutError:
            if raise_on_timeout:
                raise MemoryManagementBackendUnavailableError(
                    "local memory management worker is still closing"
                ) from None

    def _worker(self) -> None:
        startup = self._startup
        terminated = self._terminated
        try:
            self._store.open_existing_writable(timeout_ms=self._timeout_ms)
            with self._condition:
                self._state = "closing" if self._close_requested else "open"
                if startup is not None and not startup.done():
                    startup.set_result(None)
            while True:
                with self._condition:
                    while self._request is None and not self._close_requested:
                        self._condition.wait()
                    if self._close_requested:
                        break
                    operation = self._request
                    self._request = None
                if operation is None or operation.cancelled.is_set():
                    with self._condition:
                        if self._active is operation:
                            self._active = None
                    continue
                try:
                    if time.monotonic() >= operation.deadline:
                        raise MemoryDeadlineExceededError(
                            "local memory management request exceeded its time bound"
                        )
                    result = operation.work()
                    if time.monotonic() >= operation.deadline:
                        # A mutation may have committed. Its operation ID is the
                        # durable reconciliation key; never report it rolled back.
                        raise MemoryDeadlineExceededError(
                            "local memory management request exceeded its time bound"
                        )
                except BaseException as exc:
                    result, error = None, exc
                else:
                    error = None
                with self._condition:
                    if self._active is operation:
                        self._active = None
                    if not operation.cancelled.is_set() and not operation.future.done():
                        if error is not None:
                            operation.future.set_exception(error)
                        else:
                            operation.future.set_result(result)
                    self._condition.notify_all()
        except BaseException as exc:
            with self._condition:
                self._state = "failed"
            if startup is not None and not startup.done():
                startup.set_exception(exc)
        finally:
            try:
                self._store.close()
            finally:
                with self._condition:
                    if self._state != "failed":
                        self._state = "closed"
                    self._condition.notify_all()
                if terminated is not None and not terminated.done():
                    terminated.set_result(None)
