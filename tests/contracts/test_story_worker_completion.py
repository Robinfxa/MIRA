"""A completed operation must release capacity before callers observe completion."""
import asyncio
import pytest
from mira.adapters.memory import async_story as module
from mira.bootstrap.character_story import builtin_definition


@pytest.mark.asyncio
async def test_future_completion_observers_already_see_released_worker_capacity(tmp_path,monkeypatch):
    async def run():
        private=tmp_path/'private';private.mkdir(mode=0o700)
        store=module.AsyncStoryCheckpointStore(private/'story.sqlite3',fixed_scope='synthetic-scope',
            definition=builtin_definition(),enabled=True,explicitly_authorized=True)
        states=[];original=module._Operation
        def observed_operation(*args,**kwargs):
            operation=original(*args,**kwargs)
            operation.future.add_done_callback(lambda _:states.append(store._active is None and store._request is None))
            return operation
        monkeypatch.setattr(module,'_Operation',observed_operation)
        await store.open()
        try:
            assert await store.load() is None
            assert states==[True]
            assert await store.load() is None
            assert states==[True,True]
        finally:await store.aclose()
    await run()
