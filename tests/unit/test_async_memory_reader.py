from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import stat
import threading

import pytest

from mira.adapters.memory.async_read import AsyncSQLiteMemoryReader
from mira.adapters.memory.errors import (
    MemoryStoreFullError,
    MemoryStoreClosedError,
    UnknownMemoryDatabaseError,
    UnsafeMemoryPathError,
)
from mira.adapters.memory.sqlite import SQLiteMemoryStore
from mira.application.memory_context import MemoryContextError
from mira.domain.memory import MemoryEntry, MemoryKind, MemoryScope, MemorySource


def _entry(scope: MemoryScope) -> MemoryEntry:
    return MemoryEntry(
        id="entry-rain-1",
        scope=scope,
        source=MemorySource.USER_STATEMENT,
        text="The user likes the rain window and warm light",
        source_event_id="evt-rain-1",
        source_version=1,
        recorded_at="2026-10-04T12:00:00+00:00",
        kind=MemoryKind.EPISODIC,
    )


def _existing_db(tmp_path, scope: MemoryScope):
    path = tmp_path / "private" / "memory.sqlite"
    with SQLiteMemoryStore(path) as store:
        store.append(_entry(scope))
    return path


def _file_digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_reader_constructor_is_inert_and_missing_database_is_not_created(tmp_path):
    path = tmp_path / "not-created" / "memory.sqlite"
    reader = AsyncSQLiteMemoryReader(path, MemoryScope("user-a", "mira", "rain-cafe"))
    assert not path.parent.exists()

    async def attempt_open():
        with pytest.raises(UnsafeMemoryPathError):
            await reader.open()
        await reader.aclose()

    await attempt_open()
    assert not path.parent.exists()


@pytest.mark.asyncio
async def test_open_and_packet_capture_are_read_only_and_keep_full_request(tmp_path):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    path = _existing_db(tmp_path, scope)
    before = (path.stat().st_mode, path.stat().st_mtime_ns, path.stat().st_size,
              _file_digest(path), set(path.parent.iterdir()))
    reader = AsyncSQLiteMemoryReader(path, scope)
    request_text = "Please respond to this current request. " + "x" * 600

    async def capture():
        await reader.open()
        packet = await reader.build_packet(
            scope=scope,
            request_text=request_text,
            retrieval_query="rain window",
            timeout_ms=200,
            max_packet_bytes=8_192,
        )
        assert packet.request_text == request_text
        assert packet.snapshot_revision > 0
        assert any("rain window" in line.text for line in packet.past_candidates)
        assert await reader.scope_revision(scope) == packet.snapshot_revision
        await reader.aclose()

    await capture()
    after = (path.stat().st_mode, path.stat().st_mtime_ns, path.stat().st_size,
             _file_digest(path), set(path.parent.iterdir()))
    assert after == before
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_reader_rejects_nonidentical_scope_without_database_read(tmp_path):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    path = _existing_db(tmp_path, scope)
    reader = AsyncSQLiteMemoryReader(path, scope)

    async def attempt_mismatch():
        await reader.open()
        with pytest.raises(MemoryContextError, match="scope_invalid"):
            await reader.scope_revision(MemoryScope("user-b", "mira", "rain-cafe"))
        await reader.aclose()

    await attempt_mismatch()


@pytest.mark.asyncio
async def test_reader_rejects_unexpected_schema_object_without_rewriting_file(tmp_path):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    path = _existing_db(tmp_path, scope)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TRIGGER unexpected_trigger BEFORE INSERT ON memory_entries "
            "BEGIN SELECT 1; END"
        )
        connection.commit()
    finally:
        connection.close()
    before = (path.stat().st_mode, path.stat().st_mtime_ns, _file_digest(path))

    async def attempt_open():
        reader = AsyncSQLiteMemoryReader(path, scope)
        with pytest.raises(UnknownMemoryDatabaseError):
            await reader.open()
        await reader.aclose()

    await attempt_open()
    assert (path.stat().st_mode, path.stat().st_mtime_ns, _file_digest(path)) == before


@pytest.mark.asyncio
async def test_readonly_reader_rejects_world_writable_ancestor_without_chmod(tmp_path):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    ancestor = tmp_path / "writable-parent"
    ancestor.mkdir()
    path = ancestor / "private" / "memory.sqlite"
    with SQLiteMemoryStore(path) as store:
        store.append(_entry(scope))
    if os.name == "posix":
        ancestor.chmod(0o777)
        old_mode = stat.S_IMODE(ancestor.stat().st_mode)

        async def attempt_open():
            reader = AsyncSQLiteMemoryReader(path, scope)
            with pytest.raises(UnsafeMemoryPathError):
                await reader.open()
            await reader.aclose()

        await attempt_open()
        assert stat.S_IMODE(ancestor.stat().st_mode) == old_mode == 0o777


@pytest.mark.asyncio
async def test_reader_rejects_oversized_database_before_sqlite_validation(tmp_path):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "oversized.sqlite"
    with path.open("wb") as file:
        file.truncate(64 * 1024 * 1024 + 1)
    if os.name == "posix":
        path.chmod(0o600)
    before = (path.stat().st_mode, path.stat().st_size, path.stat().st_mtime_ns)

    async def attempt_open():
        reader = AsyncSQLiteMemoryReader(path, scope)
        with pytest.raises(MemoryStoreFullError):
            await reader.open()
        await reader.aclose()

    await attempt_open()
    assert (path.stat().st_mode, path.stat().st_size, path.stat().st_mtime_ns) == before


@pytest.mark.asyncio
async def test_cancelled_read_is_discarded_and_reader_has_no_waiter_queue(tmp_path, monkeypatch):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    path = _existing_db(tmp_path, scope)
    entered = threading.Event()
    release = threading.Event()
    from mira.adapters.memory import async_read

    original_builder = async_read.build_context_packet

    def blocked_builder(*args, **kwargs):
        entered.set()
        assert release.wait(1.0)
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(async_read, "build_context_packet", blocked_builder)

    async def exercise():
        reader = AsyncSQLiteMemoryReader(path, scope)
        await reader.open()
        first = asyncio.create_task(reader.build_packet(
            scope=scope,
            request_text="What do you remember about the rain?",
            retrieval_query="rain",
            timeout_ms=500,
            max_packet_bytes=8_192,
        ))
        assert await asyncio.to_thread(entered.wait, 1.0)
        with pytest.raises(RuntimeError, match="busy"):
            await reader.build_packet(
                scope=scope,
                request_text="A second read must not queue.",
                retrieval_query="second read",
                timeout_ms=500,
                max_packet_bytes=8_192,
            )
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        await reader.aclose()

    try:
        await exercise()
    finally:
        release.set()


@pytest.mark.asyncio
async def test_slow_read_times_out_without_blocking_loop_or_leaving_a_queue(tmp_path, monkeypatch):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    path = _existing_db(tmp_path, scope)
    entered = threading.Event()
    release = threading.Event()
    from mira.adapters.memory import async_read

    original_builder = async_read.build_context_packet

    def slow_builder(*args, **kwargs):
        entered.set()
        assert release.wait(1.0)
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(async_read, "build_context_packet", slow_builder)

    async def exercise():
        reader = AsyncSQLiteMemoryReader(path, scope)
        await reader.open()
        task = asyncio.create_task(reader.build_packet(
            scope=scope,
            request_text="A bounded slow read.",
            retrieval_query="bounded",
            timeout_ms=20,
            max_packet_bytes=8_192,
        ))
        assert await asyncio.to_thread(entered.wait, 1.0)
        with pytest.raises(TimeoutError):
            await task
        assert reader._state == "open"
        release.set()
        await reader.aclose()

    try:
        await exercise()
    finally:
        release.set()


@pytest.mark.asyncio
async def test_close_timeout_retains_worker_until_its_own_cleanup(tmp_path, monkeypatch):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    path = _existing_db(tmp_path, scope)
    entered = threading.Event()
    release = threading.Event()
    from mira.adapters.memory import async_read

    original_builder = async_read.build_context_packet

    def blocked_builder(*args, **kwargs):
        entered.set()
        assert release.wait(2.0)
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(async_read, "build_context_packet", blocked_builder)

    async def exercise():
        reader = AsyncSQLiteMemoryReader(path, scope)
        await reader.open()
        task = asyncio.create_task(reader.build_packet(
            scope=scope,
            request_text="A read which will be cancelled by close.",
            retrieval_query="close",
            timeout_ms=1_000,
            max_packet_bytes=8_192,
        ))
        assert await asyncio.to_thread(entered.wait, 1.0)
        with pytest.raises(MemoryStoreClosedError, match="still closing"):
            await reader.aclose()
        assert reader._state == "closing"
        assert reader._thread is not None and reader._thread.is_alive()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await reader.aclose()
        assert reader._state == "closed"

    try:
        await exercise()
    finally:
        release.set()


@pytest.mark.asyncio
async def test_cancelled_open_requests_shutdown_and_later_closes_on_worker(monkeypatch, tmp_path):
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    from mira.adapters.memory import async_read

    class SlowOpenStore:
        _connection = None

        def __init__(self, path):
            pass

        def open_readonly(self, *, timeout_ms):
            entered.set()
            assert release.wait(2.0)
            return self

        def close(self):
            closed.set()

    monkeypatch.setattr(async_read, "SQLiteMemoryStore", SlowOpenStore)

    async def exercise():
        reader = AsyncSQLiteMemoryReader(
            tmp_path / "inert" / "memory.sqlite",
            MemoryScope("user-a", "mira", "rain-cafe"),
        )
        opening = asyncio.create_task(reader.open())
        assert await asyncio.to_thread(entered.wait, 1.0)
        opening.cancel()
        with pytest.raises(asyncio.CancelledError):
            await opening
        assert reader._state == "closing"
        release.set()
        await reader.aclose()
        assert closed.is_set()
        assert reader._state == "closed"

    try:
        await exercise()
    finally:
        release.set()


@pytest.mark.asyncio
async def test_next_revision_read_can_start_before_completion_callback_returns(tmp_path, monkeypatch):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    path = _existing_db(tmp_path, scope)
    builder_entered = threading.Event()
    release_builder = threading.Event()
    future_set = threading.Event()
    release_future_set = threading.Event()
    from mira.adapters.memory import async_read

    original_builder = async_read.build_context_packet

    def blocked_builder(*args, **kwargs):
        builder_entered.set()
        assert release_builder.wait(1.0)
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(async_read, "build_context_packet", blocked_builder)

    async def exercise():
        reader = AsyncSQLiteMemoryReader(path, scope, timeout_ms=1_000)
        await reader.open()
        packet_task = asyncio.create_task(reader.build_packet(
            scope=scope,
            request_text="What do you remember about rain?",
            retrieval_query="rain",
            timeout_ms=1_000,
            max_packet_bytes=8_192,
        ))
        assert await asyncio.to_thread(builder_entered.wait, 1.0)
        operation = reader._active
        assert operation is not None
        original_set_result = operation.future.set_result

        def paused_set_result(value):
            original_set_result(value)
            future_set.set()
            release_future_set.wait(0.5)

        operation.future.set_result = paused_set_result
        release_builder.set()
        loop = asyncio.get_running_loop()
        until = loop.time() + 0.5
        while not future_set.is_set() and loop.time() < until:
            await asyncio.sleep(0.001)
        assert future_set.is_set()
        revision_task = asyncio.create_task(reader.scope_revision(scope))
        await asyncio.sleep(0)
        assert not revision_task.done()
        release_future_set.set()
        packet = await packet_task
        assert future_set.is_set()
        assert await revision_task == packet.snapshot_revision
        await reader.aclose()

    try:
        await exercise()
    finally:
        release_builder.set()
        release_future_set.set()
