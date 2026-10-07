"""A completion Future is not a thread-termination receipt; synthetic local state only."""
import asyncio
import threading

import pytest

from mira.adapters.memory.async_story import AsyncStoryCloseTimeout, AsyncStoryStoreClosed
from tests.contracts.test_story_persistence_independent_regression import open_store, private_db


def tail_barrier(store):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    original = store._worker

    def worker():
        original()
        loop.call_soon_threadsafe(entered.set)
        release.wait(3)

    store._worker = worker
    return entered, release


@pytest.mark.asyncio
async def test_close_waits_for_actual_worker_return_without_blocking_event_loop(tmp_path):
    store = open_store(private_db(tmp_path))
    entered, release = tail_barrier(store)
    await store.open()
    closing = asyncio.create_task(store.aclose())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert store._terminated.done() and store._thread.is_alive()
        # Completion and barrier callbacks are posted in this order by the same
        # worker. Let their scheduled awaiters run before inspecting close.
        await asyncio.sleep(0)
        assert not closing.done(), "aclose returned while its owned thread was alive"
        with pytest.raises(AsyncStoryStoreClosed):
            await store.load()
        release.set()
        await asyncio.wait_for(closing, 1)
        assert not store._thread.is_alive()
    finally:
        release.set()
        await asyncio.gather(closing, return_exceptions=True)
        await asyncio.to_thread(store._thread.join, 1)


@pytest.mark.asyncio
async def test_thread_exit_consumes_same_finite_close_deadline_and_can_be_reconciled(tmp_path):
    store = open_store(private_db(tmp_path), close_timeout_ms=50)
    entered, release = tail_barrier(store)
    await store.open()
    try:
        with pytest.raises(AsyncStoryCloseTimeout):
            await asyncio.wait_for(store.aclose(), 1)
        assert entered.is_set() and store._thread.is_alive()
        release.set()
        await store.aclose()
        assert not store._thread.is_alive()
    finally:
        release.set()
        await asyncio.to_thread(store._thread.join, 1)


@pytest.mark.asyncio
async def test_never_opened_close_is_still_inert_and_idempotent(tmp_path):
    store = open_store(private_db(tmp_path))
    await store.aclose()
    await store.aclose()
    assert store._thread is None


@pytest.mark.asyncio
async def test_executor_wait_is_also_inside_the_close_deadline(tmp_path, monkeypatch):
    store = open_store(private_db(tmp_path), close_timeout_ms=50)
    entered, release = tail_barrier(store)
    await store.open()
    original_to_thread = asyncio.to_thread
    called = asyncio.Event()
    parked = asyncio.Event()

    async def busy_executor(function, *args, **kwargs):
        called.set()
        await parked.wait()
        return await original_to_thread(function, *args, **kwargs)

    monkeypatch.setattr(asyncio, 'to_thread', busy_executor)
    try:
        with pytest.raises(AsyncStoryCloseTimeout):
            await asyncio.wait_for(store.aclose(), 1)
        assert entered.is_set() and called.is_set()
    finally:
        release.set()
        parked.set()
        await original_to_thread(store._thread.join, 1)
