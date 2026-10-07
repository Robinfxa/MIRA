"""Bounded asynchronous, read-only actor memory access.

The reader starts no worker and opens no file until ``open()`` is explicitly
awaited. A single dedicated worker owns the SQLite connection for its lifetime;
there is no executor pool or waiting job queue.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

from mira.adapters.memory.errors import MemoryStoreClosedError
from mira.adapters.memory.sqlite import SQLiteMemoryStore
from mira.application.memory_context import (
    ContextPacket,
    MemoryContextError,
    MAX_CONTEXT_REQUEST_CHARS,
    MAX_PACKET_BYTES,
    MAX_QUERY_CHARS,
    build_context_packet,
)
from mira.domain.memory import MemoryDeadlineExceededError, MemoryScope


_T = TypeVar("_T")


@dataclass(slots=True)
class _ReadOperation:
    deadline: float
    work: Callable[[], object]
    future: concurrent.futures.Future[object] = field(
        default_factory=concurrent.futures.Future
    )
    cancelled: threading.Event = field(default_factory=threading.Event)


class AsyncSQLiteMemoryReader:
    """Async ActorMemoryReader backed by one bounded read-only worker.

    The constructor validates shape only. ``open()`` is the sole operation that
    starts the worker and opens the explicit existing private database.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        fixed_scope: MemoryScope,
        *,
        timeout_ms: int = 200,
    ) -> None:
        self._store = SQLiteMemoryStore(path)
        if not isinstance(fixed_scope, MemoryScope):
            raise ValueError("an explicit MemoryScope is required")
        if (isinstance(timeout_ms, bool) or type(timeout_ms) is not int
                or not 10 <= timeout_ms <= 1_000):
            raise ValueError("timeout_ms must be an integer between 10 and 1000")
        self._fixed_scope = fixed_scope
        self._default_timeout_ms = timeout_ms
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._startup: concurrent.futures.Future[None] | None = None
        self._terminated: concurrent.futures.Future[None] | None = None
        self._request: _ReadOperation | None = None
        self._active: _ReadOperation | None = None
        self._state = "new"
        self._close_requested = False
        self._close_wait_seconds = 0.5

    async def open(self) -> AsyncSQLiteMemoryReader:
        """Explicitly start and await the read-only SQLite worker."""
        asyncio.get_running_loop()
        with self._condition:
            if self._state == "open":
                return self
            if self._state in {"closing", "closed", "failed"}:
                raise MemoryStoreClosedError("local memory reader is closed")
            if self._state == "new":
                self._state = "opening"
                self._startup = concurrent.futures.Future()
                self._terminated = concurrent.futures.Future()
                thread = threading.Thread(
                    target=self._worker,
                    name="mira-memory-readonly",
                    daemon=True,
                )
                self._thread = thread
                thread.start()
            startup = self._startup
        if startup is None:
            raise MemoryStoreClosedError("local memory reader is closed")
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(startup)),
                timeout=self._default_timeout_ms / 1_000 + 0.1,
            )
        except asyncio.TimeoutError:
            self._request_close(interrupt=True)
            await self._wait_for_worker_briefly()
            raise MemoryDeadlineExceededError("local memory open exceeded its time bound") from None
        except asyncio.CancelledError:
            self._request_close(interrupt=True)
            raise
        except Exception:
            # A failed open still owns a short-lived worker which must finish its
            # owner-thread close. Cleanup is bounded; the worker remains marked
            # closing until its own finally block releases the connection.
            self._request_close(interrupt=True)
            await self._wait_for_worker_briefly()
            raise
        with self._condition:
            if self._state != "open" or self._close_requested:
                raise MemoryStoreClosedError("local memory reader is closed")
        return self

    async def build_packet(
        self,
        *,
        scope: MemoryScope,
        request_text: str,
        retrieval_query: str,
        timeout_ms: int,
        max_packet_bytes: int,
    ) -> ContextPacket:
        """Build one same-revision immutable packet on the owner worker."""
        self._require_scope(scope)
        if (type(request_text) is not str or not request_text.strip()
                or len(request_text) > MAX_CONTEXT_REQUEST_CHARS):
            raise MemoryContextError("request_text_invalid")
        if (type(retrieval_query) is not str or not retrieval_query.strip()
                or len(retrieval_query) > MAX_QUERY_CHARS):
            raise MemoryContextError("retrieval_query_invalid")
        self._validate_bounds(timeout_ms, max_packet_bytes)
        deadline = time.monotonic() + timeout_ms / 1_000

        def work() -> ContextPacket:
            with self._store._bounded_read_deadline(deadline):
                return build_context_packet(
                    self._store,
                    scope,
                    request_text,
                    retrieval_query=retrieval_query,
                    max_packet_bytes=max_packet_bytes,
                    timeout_ms=timeout_ms,
                )

        return await self._submit(deadline, work)  # type: ignore[return-value]

    async def scope_revision(self, scope: MemoryScope) -> int:
        """Read only this reader's exact server-configured scope revision."""
        self._require_scope(scope)
        deadline = time.monotonic() + self._default_timeout_ms / 1_000

        def work() -> int:
            with self._store._bounded_read_deadline(deadline):
                return self._store.scope_revision(self._fixed_scope)

        return await self._submit(deadline, work)  # type: ignore[return-value]

    async def aclose(self) -> None:
        """Cancel pending work, interrupt SQLite, and close on the owner thread."""
        self._request_close(interrupt=True)
        await self._wait_for_worker_briefly(raise_on_timeout=True)

    async def _wait_for_worker_briefly(self, *, raise_on_timeout: bool = False) -> None:
        with self._condition:
            terminated = self._terminated
        if terminated is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(asyncio.wrap_future(terminated)),
                    timeout=self._close_wait_seconds,
                )
            except asyncio.TimeoutError:
                if raise_on_timeout:
                    raise MemoryStoreClosedError(
                        "local memory worker is still closing"
                    ) from None

    def _validate_bounds(self, timeout_ms: int, max_packet_bytes: int) -> None:
        if (isinstance(timeout_ms, bool) or type(timeout_ms) is not int
                or not 10 <= timeout_ms <= 1_000):
            raise MemoryContextError("timeout_invalid")
        if (isinstance(max_packet_bytes, bool) or type(max_packet_bytes) is not int
                or not 1_024 <= max_packet_bytes <= MAX_PACKET_BYTES):
            raise MemoryContextError("packet_limit_invalid")

    def _require_scope(self, scope: MemoryScope) -> None:
        if not isinstance(scope, MemoryScope) or scope != self._fixed_scope:
            raise MemoryContextError("scope_invalid")

    async def _submit(self, deadline: float, work: Callable[[], _T]) -> _T:
        with self._condition:
            if self._state != "open" or self._close_requested:
                raise MemoryStoreClosedError("local memory reader is closed")
            if self._active is not None or self._request is not None:
                raise RuntimeError("local memory reader is busy")
            operation = _ReadOperation(deadline=deadline, work=work)
            self._active = operation
            self._request = operation
            self._condition.notify()
        try:
            timeout = max(0.0, deadline - time.monotonic()) + 0.05
            return await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(operation.future)), timeout=timeout
            )  # type: ignore[return-value]
        except asyncio.TimeoutError:
            self._cancel_operation(operation)
            raise MemoryDeadlineExceededError("local memory read exceeded its time bound") from None
        except asyncio.CancelledError:
            self._cancel_operation(operation)
            raise

    def _cancel_operation(self, operation: _ReadOperation) -> None:
        connection = None
        with self._condition:
            operation.cancelled.set()
            if self._request is operation:
                self._request = None
                if self._active is operation:
                    self._active = None
            elif self._active is operation:
                connection = self._store._connection
            operation.future.cancel()
            self._condition.notify_all()
        if connection is not None:
            # sqlite3 explicitly supports interrupt() from another thread; the
            # worker remains the only thread that executes SQL or closes it.
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
                # open_readonly publishes the handle before schema validation,
                # so even a startup timeout can interrupt validation promptly.
                connection = self._store._connection
            self._condition.notify_all()
        if connection is not None:
            try:
                connection.interrupt()
            except Exception:
                pass

    def _worker(self) -> None:
        startup = self._startup
        terminated = self._terminated
        try:
            self._store.open_readonly(timeout_ms=self._default_timeout_ms)
            with self._condition:
                if self._close_requested:
                    self._state = "closing"
                else:
                    self._state = "open"
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
                            "local memory read exceeded its time bound"
                        )
                    result = operation.work()
                    if time.monotonic() >= operation.deadline:
                        raise MemoryDeadlineExceededError(
                            "local memory read exceeded its time bound"
                        )
                except BaseException as exc:
                    result = None
                    error: BaseException | None = exc
                else:
                    error = None
                with self._condition:
                    # Release ownership before waking the awaiting coroutine.
                    # It may immediately make the next read call on this reader.
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
