"""Replay approved fixture references without network, sessions, or mutable shared cursors."""
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

from mira.adapters.fixture_catalog import FIXTURES
from mira.adapters.generation.replay.script import ReplayScript
from mira.application.contracts import CandidateRange, GenerationContext

AsyncSleep = Callable[[float], Awaitable[None]]


class ReplayProviderFailure(RuntimeError):
    """Intentional fixture failure; it must not be confused with a clean end-of-plan."""


class ReplayGenerationBackend:
    def __init__(self, script: ReplayScript, *, sleep: AsyncSleep = asyncio.sleep) -> None:
        self._script = script
        self._sleep = sleep

    async def generate(self, context: GenerationContext) -> AsyncIterator[CandidateRange]:
        # Context is deliberately not interpreted: this adapter is a fixed test fixture.
        # The cursor lives in this invocation, not on the backend shared by sessions.
        for step in self._script.steps:
            await self._sleep(step.delay_ms / 1000)
            yield CandidateRange(FIXTURES[step.fixture_id], step.fixture_id)
        # Yield cooperatively even after zero-delay fixtures; cancellation is never swallowed.
        await self._sleep(0)
        if self._script.finish == "fail":
            raise ReplayProviderFailure("fixture_provider_failure")
