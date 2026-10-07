"""Bounded asyncio bridge for explicit story checkpoint and episode IO.

Construction is inert. Every SQLite operation runs on one dedicated worker
thread, with at most one accepted operation at a time. A caller timeout or
cancellation never pretends that a started write rolled back; the worker keeps
the adapter busy until SQLite actually returns so an identical retry can
reconcile through the synchronous store's monotonic/idempotent rules.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

from mira.adapters.memory.story import (
    EpisodeCandidate,
    StoryCheckpointStore,
    StoryStoreError,
    ScopeMismatch,
    VersionMismatch,
)
from mira.application.story import RuntimeSnapshot, StoryRuntime
from mira.domain.story import StoryDefinition

_T = TypeVar("_T")


class AsyncStoryStoreError(RuntimeError):
    """Base class for asynchronous adapter lifecycle and scheduling errors."""


class AsyncStoryStoreClosed(AsyncStoryStoreError):
    pass


class AsyncStoryStoreBusy(AsyncStoryStoreError):
    pass


class AsyncStoryDeadlineExceeded(AsyncStoryStoreError):
    def __init__(self, operation: str, *, outcome_unknown: bool) -> None:
        self.operation = operation
        self.outcome_unknown = outcome_unknown
        suffix = "; write outcome is unknown" if outcome_unknown else ""
        super().__init__(f"story {operation} exceeded its time bound{suffix}")


class AsyncStoryCloseTimeout(AsyncStoryStoreError):
    pass


@dataclass(slots=True)
class _Operation:
    name: str
    deadline: float
    work: Callable[[], object]
    mutation: bool
    future: concurrent.futures.Future[object] = field(
        default_factory=concurrent.futures.Future
    )


class AsyncStoryCheckpointStore:
    """Explicit, exact-scope async façade over ``StoryCheckpointStore``.

    ``fixed_scope`` and ``definition`` are server-composed values. The exact
    path, enablement, and authorization flag are passed through to the sync
    private-path/consent guard. ``open`` checks the private path read-only and
    starts the worker; it does not create a database. Only ``save`` can cause
    the synchronous store's explicitly authorized creation path to run.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        fixed_scope: str,
        definition: StoryDefinition,
        enabled: bool = False,
        explicitly_authorized: bool = False,
        read_timeout_ms: int = 750,
        write_timeout_ms: int = 1_500,
        open_timeout_ms: int = 500,
        close_timeout_ms: int = 2_000,
    ) -> None:
        if type(fixed_scope) is not str or not fixed_scope or len(fixed_scope) > 256:
            raise ValueError("an explicit bounded fixed story scope is required")
        if type(definition) is not StoryDefinition:
            raise ValueError("an explicit StoryDefinition is required")
        self._store = StoryCheckpointStore(
            path,
            enabled=enabled,
            explicitly_authorized=explicitly_authorized,
            authorized_scope_id=fixed_scope,
        )
        for value, low, high, label in (
            (read_timeout_ms, 10, 2_000, "read timeout"),
            (write_timeout_ms, 50, 3_000, "write timeout"),
            (open_timeout_ms, 10, 2_000, "open timeout"),
            (close_timeout_ms, 50, 5_000, "close timeout"),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{label} is out of range")
        self._fixed_scope = fixed_scope
        self._definition = definition
        self._read_timeout_ms = read_timeout_ms
        self._write_timeout_ms = write_timeout_ms
        self._open_timeout_ms = open_timeout_ms
        self._close_timeout_ms = close_timeout_ms
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._startup: concurrent.futures.Future[None] | None = None
        self._terminated: concurrent.futures.Future[None] | None = None
        self._request: _Operation | None = None
        self._active: _Operation | None = None
        self._state = "new"
        self._close_requested = False

    async def open(self) -> AsyncStoryCheckpointStore:
        """Start the sole worker and verify the private path without creating it."""
        asyncio.get_running_loop()
        with self._condition:
            if self._state == "open":
                return self
            if self._state != "new":
                raise AsyncStoryStoreClosed("story checkpoint adapter cannot be reopened")
            self._state = "opening"
            self._startup = concurrent.futures.Future()
            self._terminated = concurrent.futures.Future()
            self._thread = threading.Thread(
                target=self._worker,
                name="mira-story-checkpoint",
                daemon=True,
            )
            startup = self._startup
            self._thread.start()
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(startup)),
                timeout=self._open_timeout_ms / 1_000,
            )
        except asyncio.TimeoutError:
            self._request_close()
            await self._wait_for_worker_briefly()
            raise AsyncStoryDeadlineExceeded("open", outcome_unknown=False) from None
        except asyncio.CancelledError:
            self._request_close()
            await self._wait_for_worker_briefly()
            raise
        with self._condition:
            if self._state != "open" or self._close_requested:
                raise AsyncStoryStoreClosed("story checkpoint adapter is closing")
        return self

    async def load(self, story_id: str | None = None) -> RuntimeSnapshot | None:
        """Load the fixed story. A missing DB/checkpoint is a read-only miss."""
        expected_id = self._definition.graph.story_id
        if story_id is not None and story_id != expected_id:
            raise ScopeMismatch("requested story differs from the fixed definition")
        deadline = time.monotonic() + self._read_timeout_ms / 1_000

        def work() -> RuntimeSnapshot | None:
            try:
                loaded = self._store.load(
                    self._fixed_scope,
                    expected_id,
                    graph_id=self._definition.graph.graph_id,
                    graph_revision=self._definition.graph.revision,
                    canon_revision=self._definition.canon.revision,
                    graph_hash=self._definition.graph.content_hash,
                    canon_hash=self._definition.canon.content_hash,
                )
            except VersionMismatch:
                from mira.adapters.memory.story_upgrade import StoryCanonUpgrade, CanonUpgradeRequired
                try:
                    plan = StoryCanonUpgrade(self._store, self._definition).preview()
                except (StoryStoreError, ValueError, TypeError, KeyError):
                    raise VersionMismatch("checkpoint graph or canon revision differs") from None
                if plan.status == "ready":
                    raise CanonUpgradeRequired("story_checkpoint_canon_upgrade_required") from None
                raise
            if loaded is None:
                return None
            story, affect = loaded
            snapshot = RuntimeSnapshot(
                story,
                affect,
                self._definition.graph.revision,
                self._definition.canon.revision,
                self._definition.graph.content_hash,
                self._definition.canon.content_hash,
            )
            StoryRuntime.from_snapshot(self._definition, snapshot)
            return snapshot

        return await self._submit("load", deadline, work, mutation=False)  # type: ignore[return-value]

    async def load_episodes(self, story_id: str | None = None) -> tuple[EpisodeCandidate, ...]:
        """Load the append-only qualified-fiction archive, separate from context."""
        expected_id = self._definition.graph.story_id
        if story_id is not None and story_id != expected_id:
            raise ScopeMismatch("requested story differs from the fixed definition")
        deadline = time.monotonic() + self._read_timeout_ms / 1_000

        def work() -> tuple[EpisodeCandidate, ...]:
            return self._store.load_episodes(
                self._fixed_scope,
                expected_id,
                graph_id=self._definition.graph.graph_id,
                graph_revision=self._definition.graph.revision,
                canon_revision=self._definition.canon.revision,
                graph_hash=self._definition.graph.content_hash,
                canon_hash=self._definition.canon.content_hash,
            )

        return await self._submit("load_episodes", deadline, work, mutation=False)  # type: ignore[return-value]

    async def save(self, snapshot: RuntimeSnapshot) -> None:
        """Persist a monotonic current snapshot and any new qualified episodes."""
        story, affect = self._validate_snapshot(snapshot)
        deadline = time.monotonic() + self._write_timeout_ms / 1_000

        def work() -> None:
            self._store.save(story, affect)

        await self._submit("save", deadline, work, mutation=True)

    async def aclose(self) -> None:
        """Reject future work, drain one accepted call, then permanently close."""
        self._request_close()
        await self._wait_for_worker_briefly(raise_on_timeout=True)

    def _validate_snapshot(self, snapshot: RuntimeSnapshot):
        if type(snapshot) is not RuntimeSnapshot:
            raise ValueError("a typed RuntimeSnapshot is required")
        story = snapshot.story
        affect = snapshot.affect
        definition = self._definition
        if story.scope_id != self._fixed_scope:
            raise ScopeMismatch("snapshot differs from the adapter's fixed scope")
        if story.story_id != definition.graph.story_id or story.graph_id != definition.graph.graph_id:
            raise VersionMismatch("snapshot differs from the adapter's fixed story definition")
        if affect.story_id != story.story_id:
            raise VersionMismatch("story and affect snapshots must share a story ID")
        # Validate graph/canon revisions and the StoryState/AffectState pair
        # before reserving the worker. This is pure in-memory validation.
        StoryRuntime.from_snapshot(definition, snapshot)
        return story, affect

    async def _submit(self, name: str, deadline: float, work: Callable[[], _T], *,
                      mutation: bool) -> _T:
        with self._condition:
            if self._state != "open" or self._close_requested:
                raise AsyncStoryStoreClosed("story checkpoint adapter is not open")
            # _request remains occupied while work runs, even if its caller
            # timed out or was cancelled. No unbounded queue or leaked threads.
            if self._request is not None or self._active is not None:
                raise AsyncStoryStoreBusy("story checkpoint adapter is busy")
            request = _Operation(name, deadline, work, mutation)
            self._request = request
            self._condition.notify()
        try:
            timeout = max(0.0, deadline - time.monotonic())
            return await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(request.future)),
                timeout=timeout,
            )  # type: ignore[return-value]
        except asyncio.TimeoutError:
            raise AsyncStoryDeadlineExceeded(name, outcome_unknown=mutation) from None
        except asyncio.CancelledError:
            # The worker owns the accepted request until it ends. For writes,
            # cancellation therefore leaves the commit outcome potentially
            # unknown and the caller may safely reconcile with load/retry.
            raise

    def _request_close(self) -> None:
        with self._condition:
            if self._state in {"closed", "failed"}:
                return
            self._close_requested = True
            if self._thread is None:
                self._state = "closed"
                self._condition.notify_all()
                return
            self._state = "closing"
            self._condition.notify_all()

    async def _wait_for_worker_briefly(self, *, raise_on_timeout: bool = False) -> None:
        with self._condition:
            terminated = self._terminated
            thread = self._thread
        if terminated is None:
            return
        deadline = time.monotonic() + self._close_timeout_ms / 1_000
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(terminated)),
                timeout=max(0.0, deadline - time.monotonic()),
            )
            # The worker publishes its Future before Python marks its thread
            # stopped. Join off-loop within the same deadline, so successful
            # close really releases the owned thread before session replacement.
            if thread is not None and thread.is_alive():
                remaining = max(0.0, deadline - time.monotonic())
                await asyncio.wait_for(asyncio.to_thread(thread.join, remaining), timeout=remaining)
                if thread.is_alive():
                    raise asyncio.TimeoutError
        except asyncio.TimeoutError:
            if raise_on_timeout:
                raise AsyncStoryCloseTimeout(
                    "story checkpoint worker is still finishing an accepted operation"
                ) from None

    def _worker(self) -> None:
        startup = self._startup
        terminated = self._terminated
        assert startup is not None and terminated is not None
        try:
            # Private-path validation is intentionally read-only. A missing DB
            # is valid for a future authorized save and remains absent on load.
            self._store._check_private_path(create=False)
        except BaseException as error:
            with self._condition:
                self._state = "failed"
                self._close_requested = True
                self._condition.notify_all()
            startup.set_exception(error)
            terminated.set_result(None)
            return
        with self._condition:
            if self._close_requested:
                self._state = "closed"
                startup.set_exception(AsyncStoryStoreClosed("adapter closed while opening"))
                self._condition.notify_all()
                terminated.set_result(None)
                return
            self._state = "open"
            startup.set_result(None)
            self._condition.notify_all()

        while True:
            with self._condition:
                while self._request is None and not self._close_requested:
                    self._condition.wait()
                if self._request is None and self._close_requested:
                    self._state = "closed"
                    self._condition.notify_all()
                    terminated.set_result(None)
                    return
                request = self._request
                self._request = None
                self._active = request
            assert request is not None
            failure = None
            result = None
            try:
                result = request.work()
            except BaseException as error:
                failure = error
            # Release the completed operation before publishing its result. A
            # caller that immediately awaits its next operation must not see
            # the old operation as spuriously busy after successful completion.
            with self._condition:
                self._active = None
                self._condition.notify_all()
            if failure is not None:
                request.future.set_exception(failure)
            else:
                request.future.set_result(result)


__all__ = [
    "AsyncStoryCheckpointStore",
    "AsyncStoryStoreBusy",
    "AsyncStoryStoreClosed",
    "AsyncStoryDeadlineExceeded",
    "AsyncStoryCloseTimeout",
    "AsyncStoryStoreError",
]
