"""FND02-004/005: causal barriers, not sleep-based guesses, control the test schedule."""
import asyncio

import pytest

from mira.adapters.generation.replay.backend import ReplayGenerationBackend
from mira.adapters.generation.replay.script import load_script
from mira.application.contracts import GenerationContext
from tests.support.barriers import StepBarrier

CONTEXT = GenerationContext("fixture", ("fixture",), (), 1)




@pytest.mark.asyncio
async def test_cancel_pending_step_propagates_and_emits_no_tail():
    barrier = StepBarrier()
    backend = ReplayGenerationBackend(load_script("delayed-photo"), sleep=barrier)
    observed = []

    async def collect():
        async for item in backend.generate(CONTEXT):
            observed.append(item.fixture_id)

    task = asyncio.create_task(collect())
    try:
        async with asyncio.timeout(1):
            await barrier.entered.wait()
            assert observed == ["hello"]
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert barrier.cancelled.is_set()
        assert observed == ["hello"]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_injected_sleeper_receives_declared_order_not_wall_time_guesses():
    delays = []

    async def record_delay(seconds):
        delays.append(seconds)

    backend = ReplayGenerationBackend(load_script("delayed-photo"), sleep=record_delay)
    assert [item.fixture_id async for item in backend.generate(CONTEXT)] == ["hello", "photo"]
    assert delays == [0, 0.5, 0]
