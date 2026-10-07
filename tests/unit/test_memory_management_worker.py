from __future__ import annotations

import asyncio
import threading
from uuid import UUID

import pytest

from mira.adapters.memory.async_management import AsyncSQLiteMemoryManagement
from mira.adapters.memory.sqlite import SQLiteMemoryStore
from mira.application.memory_management import (
    MemoryManagement,
    MemoryManagementAuthorizationError,
    MemoryManagementOutcomeUnknownError,
    MemoryManagementUnavailableError,
)
from mira.application.ports.memory_management import (
    MemoryManagementBackendBusyError,
    MemoryManagementBackendUnavailableError,
    MemoryManagementCommand,
    MemoryManagementOperationResult,
    MemoryManagementPage,
    MemoryManagementOperation,
)
from mira.domain.memory import MemoryKind, MemoryScope


class NoIOBackend:
    def __init__(self):
        self.calls = 0

    async def open(self):
        self.calls += 1
        return self

    async def scope_revision(self):
        self.calls += 1
        return 0

    async def list_entries(self, *, limit, cursor):
        self.calls += 1
        raise AssertionError("no backend read expected")

    async def apply_operation(self, command):
        self.calls += 1
        raise AssertionError("no backend write expected")

    async def aclose(self):
        self.calls += 1


def _command() -> MemoryManagementCommand:
    return MemoryManagementCommand(
        operation_id=str(UUID("00000000-0000-4000-8000-000000000101")),
        expected_revision=0,
        operation=MemoryManagementOperation.RECORD,
        confirmed=True,
        text="I prefer the rain window",
        kind=MemoryKind.EPISODIC,
    )


@pytest.mark.asyncio
async def test_management_requires_explicit_authorization_and_existing_store(tmp_path):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    path = tmp_path / "private" / "memory.sqlite"
    backend = AsyncSQLiteMemoryManagement(path, scope)
    manager = MemoryManagement(backend)
    with pytest.raises(MemoryManagementAuthorizationError):
        await manager.open()
    assert not path.exists() and not path.parent.exists()

    with pytest.raises(MemoryManagementBackendUnavailableError):
        await AsyncSQLiteMemoryManagement(path, scope).open()
    assert not path.exists() and not path.parent.exists()

    fake = NoIOBackend()
    denied = MemoryManagement(fake, authorized=False)
    with pytest.raises(MemoryManagementAuthorizationError):
        await denied.open()
    assert fake.calls == 0


@pytest.mark.asyncio
async def test_one_worker_rejects_second_active_request_and_closes_after_cancel(tmp_path):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    path = tmp_path / "private" / "memory.sqlite"
    SQLiteMemoryStore(path).open().close()
    backend = AsyncSQLiteMemoryManagement(path, scope)
    manager = await MemoryManagement(backend, authorized=True).open()
    original_list = backend._store.management_list
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_list(bound_scope, *, limit, cursor):
        entered.set()
        release.wait(timeout=2)
        try:
            return original_list(bound_scope, limit=limit, cursor=cursor)
        finally:
            finished.set()

    backend._store.management_list = blocking_list
    first = asyncio.create_task(manager.list_entries(limit=20))
    assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 1), timeout=2)
    with pytest.raises(MemoryManagementBackendBusyError):
        await manager.list_entries(limit=20)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(MemoryManagementBackendBusyError):
        await manager.list_entries(limit=20)
    release.set()
    assert await asyncio.wait_for(asyncio.to_thread(finished.wait, 1), timeout=2)
    page = await manager.list_entries(limit=20)
    assert page.entries == ()
    await manager.aclose()
    assert backend._store._connection is None


@pytest.mark.asyncio
async def test_cancelled_mutation_stays_busy_until_commit_then_reconciles_by_id(tmp_path):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    path = tmp_path / "private" / "memory.sqlite"
    SQLiteMemoryStore(path).open().close()
    backend = AsyncSQLiteMemoryManagement(path, scope)
    manager = await MemoryManagement(backend, authorized=True).open()
    original_apply = backend._store.management_apply
    committed = threading.Event()
    release = threading.Event()

    def commit_then_wait(bound_scope, command):
        result = original_apply(bound_scope, command)
        committed.set()
        release.wait(timeout=2)
        return result

    backend._store.management_apply = commit_then_wait
    command = _command()
    request = asyncio.create_task(manager.apply_operation(command))
    assert await asyncio.wait_for(asyncio.to_thread(committed.wait, 1), timeout=2)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    with pytest.raises(MemoryManagementBackendBusyError):
        await manager.apply_operation(command)
    release.set()
    # Wait until the worker has released its single active slot.
    for _ in range(100):
        try:
            replay = await manager.apply_operation(command)
            break
        except MemoryManagementBackendBusyError:
            await asyncio.sleep(0.005)
    else:
        pytest.fail("management worker did not release its active request")
    assert replay.replayed is True
    assert replay.entry_id == command.operation_id
    assert (await manager.status()).revision == 1
    await manager.aclose()


@pytest.mark.asyncio
async def test_close_during_open_cannot_revive_manager_or_leave_backend_open():
    class SlowOpenBackend(NoIOBackend):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.closed = False

        async def open(self):
            self.started.set()
            await self.release.wait()
            return self

        async def aclose(self):
            self.closed = True

    backend = SlowOpenBackend()
    manager = MemoryManagement(backend, authorized=True)
    opening = asyncio.create_task(manager.open())
    await asyncio.wait_for(backend.started.wait(), timeout=1)
    await manager.aclose()
    backend.release.set()
    with pytest.raises(MemoryManagementUnavailableError):
        await opening
    assert manager.is_open is False and backend.closed is True


@pytest.mark.asyncio
async def test_post_close_list_result_is_discarded():
    class SlowReadBackend(NoIOBackend):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.closed = False

        async def open(self):
            return self

        async def list_entries(self, *, limit, cursor):
            self.started.set()
            await self.release.wait()
            return MemoryManagementPage(0, (), None)

        async def aclose(self):
            self.closed = True

    backend = SlowReadBackend()
    manager = await MemoryManagement(backend, authorized=True).open()
    reading = asyncio.create_task(manager.list_entries(limit=20))
    await asyncio.wait_for(backend.started.wait(), timeout=1)
    await manager.aclose()
    backend.release.set()
    with pytest.raises(MemoryManagementUnavailableError):
        await reading
    assert manager.is_open is False and backend.closed is True


@pytest.mark.asyncio
async def test_post_close_mutation_result_remains_unknown_and_is_not_rolled_back():
    class SlowCommitBackend(NoIOBackend):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.closed = False
            self.committed = False

        async def open(self):
            return self

        async def apply_operation(self, command):
            self.committed = True
            self.started.set()
            await self.release.wait()
            return MemoryManagementOperationResult(
                "committed", command.operation_id, 1, entry_id=command.operation_id,
            )

        async def aclose(self):
            self.closed = True

    backend = SlowCommitBackend()
    manager = await MemoryManagement(backend, authorized=True).open()
    command = _command()
    submitting = asyncio.create_task(manager.apply_operation(command))
    await asyncio.wait_for(backend.started.wait(), timeout=1)
    await manager.aclose()
    backend.release.set()
    with pytest.raises(MemoryManagementOutcomeUnknownError):
        await submitting
    assert backend.committed is True
    assert manager.is_open is False and backend.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize('closed', [False, True])
async def test_backend_unopened_or_closed_operations_have_safe_unavailable_error(tmp_path, closed):
    """Error translation must not reference an obsolete exception import name."""
    scope = MemoryScope('user-a', 'mira', 'rain-cafe')
    backend = AsyncSQLiteMemoryManagement(tmp_path / 'private' / 'memory.sqlite', scope)
    if closed:
        await backend.aclose()
    for operation in (backend.scope_revision, lambda: backend.list_entries(limit=20),
                      lambda: backend.apply_operation(_command())):
        with pytest.raises(MemoryManagementBackendUnavailableError):
            await operation()
    if closed:
        with pytest.raises(MemoryManagementBackendUnavailableError):
            await backend.open()
    assert not (tmp_path / 'private').exists()
