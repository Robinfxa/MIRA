"""Explicit happens-before points for deterministic async contract tests."""
import asyncio


class StepBarrier:
    """Pause on the second sleep call (the second step or terminal checkpoint)."""

    def __init__(self) -> None:
        self.calls: list[float] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if len(self.calls) == 2:
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

