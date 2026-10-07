"""One bounded asynchronous worker for the opt-in conversation archive.

Cancellation abandons a wait, not a committed write. A running operation retains
its sole slot until it actually finishes; no second queued mutation is admitted.
"""
from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor

from mira.adapters.memory.conversation import ConversationArchive
from mira.application.conversation_archive import ConversationArchiveError, ConversationArchiveBusyError


class AsyncConversationArchive:
    def __init__(self, path, *, fixed_scope, enabled=False,
                 authorize_transcript_persistence=False, timeout_seconds=5.0):
        if type(timeout_seconds) not in (int, float) or not 0.05 <= timeout_seconds <= 5:
            raise ValueError('conversation_timeout_invalid')
        self._archive = ConversationArchive(path, fixed_scope=fixed_scope, enabled=enabled,
            authorize_transcript_persistence=authorize_transcript_persistence)
        self._timeout = timeout_seconds
        self._executor = None
        self._active = None
        self._closed = False

    async def open(self, *, pairing_confirmed=False):
        if self._closed or self._executor is not None:
            raise ConversationArchiveError('conversation_worker_already_started')
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mira-conversation')
        try:
            await self._run(self._archive.open, pairing_confirmed=pairing_confirmed)
        except BaseException:
            await self.aclose()
            raise
        return self

    async def _run(self, function, *args, **kwargs):
        if self._closed or self._executor is None:
            raise ConversationArchiveError('conversation_worker_closed')
        if self._active is not None and not self._active.done():
            raise ConversationArchiveBusyError('conversation_worker_busy')
        future = self._executor.submit(function, *args, **kwargs)
        self._active = future
        # Shield the underlying worker: canceling the caller must not release its
        # slot or pretend an accepted write did not happen.
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(lambda result: None if result.cancelled() else result.exception())
        return await asyncio.wait_for(asyncio.shield(wrapped), self._timeout)

    async def capture(self, session_id, inputs, effects, receipts, audio_progress, provenance=None):
        return await self._run(self._archive.capture, session_id, inputs, effects, receipts, audio_progress, provenance)

    async def load_session(self, session_id):
        return await self._run(self._archive.load_session, session_id)

    async def session_revision(self, session_id):
        return await self._run(self._archive.session_revision, session_id)

    async def list_sessions(self, *, cursor=None):
        return await self._run(self._archive.list_sessions,cursor=cursor)

    async def management_page(self, session_id, *, cursor=None):
        return await self._run(self._archive.management_page,session_id,cursor=cursor)

    async def management_apply(self, session_id, command):
        from mira.adapters.memory.errors import (MemoryConflictError,MemoryEntryNotFoundError,
            MemoryPrivacyError,MemoryManagementOperationIdConflictError)
        from mira.application.ports.memory_management import (MemoryManagementBackendConflictError,
            MemoryManagementBackendEntryNotFoundError,MemoryManagementBackendTextRejectedError,
            MemoryManagementBackendOperationIdConflictError)
        try:return await self._run(self._archive.management_apply,session_id,command)
        except MemoryManagementOperationIdConflictError:
            raise MemoryManagementBackendOperationIdConflictError() from None
        except MemoryConflictError:raise MemoryManagementBackendConflictError() from None
        except MemoryEntryNotFoundError:raise MemoryManagementBackendEntryNotFoundError() from None
        except MemoryPrivacyError:raise MemoryManagementBackendTextRejectedError() from None

    async def wait_idle(self):
        active=self._active
        if active is not None and not active.done():
            await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(active)),self._timeout)

    async def aclose(self):
        if self._closed:
            return
        self._closed = True
        executor = self._executor
        if executor is None:
            return
        # One final close queues behind the sole accepted operation; new work is
        # already disabled. Even if the wait times out, the worker owns cleanup.
        final = executor.submit(self._archive.close)
        executor.shutdown(wait=False, cancel_futures=False)
        await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(final)), self._timeout)
