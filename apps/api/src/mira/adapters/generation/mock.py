"""Deterministic fixtures for protocol work, not a substitute for live semantics."""
import asyncio
from collections.abc import AsyncIterator

from mira.adapters.fixture_catalog import FIXTURES as FIXTURES
from mira.application.contracts import CandidateRange, GenerationContext




class MockGenerationBackend:
    def __init__(self, delay_ms: int) -> None:
        self._delay = delay_ms / 1000

    async def generate(self, context: GenerationContext) -> AsyncIterator[CandidateRange]:
        if context.user_text == "/fail":
            await asyncio.sleep(self._delay)
            raise RuntimeError("synthetic provider failure")
        key = {"不要拍我": "camera", "听雨": "quiet", "看照片": "photo"}.get(
            context.user_text, "hello"
        )
        for name in (("photo", "photo_caption") if key == "photo" else (key,)):
            await asyncio.sleep(self._delay)
            yield CandidateRange(FIXTURES[name], name)
