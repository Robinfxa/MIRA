"""FND02-005/006: replay follows the original Actor, permit and receipt path."""
import asyncio

import pytest

from mira.adapters.generation.replay.backend import ReplayGenerationBackend
from mira.adapters.generation.replay.script import load_script
from mira.adapters.journal.memory import MemoryEventJournal
from mira.adapters.review.mock import FixtureReviewBackend
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.domain.models import Phase, Receipt, SessionState
from tests.support.barriers import StepBarrier


class SignalJournal(MemoryEventJournal):
    def __init__(self):
        super().__init__(100)
        self.failed = asyncio.Event()

    def append(self, event):
        super().append(event)
        if event.kind == "generation_failed":
            self.failed.set()


def make_actor(scenario):
    barrier = StepBarrier()
    journal = SignalJournal()
    backend = ReplayGenerationBackend(load_script(scenario), sleep=barrier)
    actor = SessionActor(SessionState("s", "c"), backend, FixtureReviewBackend(), journal,
                         RuntimeLimits(2, 16, 64))
    return actor, barrier, journal


@pytest.mark.asyncio
async def test_stop_revokes_tail_without_waiting_for_replay():
    actor, barrier, _ = make_actor("delayed-photo")
    try:
        async with asyncio.timeout(1):
            await actor.submit(request_id="r1", activity_seq=1, cutoff=0, text="fixture")
            await barrier.entered.wait()
            before = await actor.snapshot()
            assert len(before.active_grants) == 1
            stopped = await actor.stop(activity_seq=2, cutoff=0)
            await barrier.cancelled.wait()
            barrier.release.set()
            assert await actor.snapshot() == stopped
            assert stopped.phase == Phase.STOPPED
            assert stopped.active_grants == () and not stopped.sealed
    finally:
        barrier.release.set()
        await actor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("present_first", [False, True])
async def test_failed_tail_preserves_only_receipted_history(present_first):
    actor, barrier, journal = make_actor("failed-tail")
    try:
        async with asyncio.timeout(1):
            await actor.submit(request_id="r1", activity_seq=1, cutoff=0, text="fixture")
            await barrier.entered.wait()
            state = await actor.snapshot()
            assert len(state.active_grants) == 1 and not state.sealed
            if present_first:
                effect = state.active_grants[0]
                await actor.receipt(Receipt(effect.id, effect.digest, 1, 1, 1))
            barrier.release.set()
            await journal.failed.wait()
            failed = await actor.snapshot()
            assert failed.last_error == "generation_failed"
            assert failed.phase == Phase.ERROR and not failed.sealed
            assert failed.active_grants == ()
            assert len(failed.presented_effects) == int(present_first)
    finally:
        barrier.release.set()
        await actor.close()
