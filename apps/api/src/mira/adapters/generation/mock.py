"""Deterministic fixtures for protocol work, not a substitute for live semantics."""
import asyncio
from collections.abc import AsyncIterator

from mira.adapters.fixture_catalog import FIXTURES as FIXTURES
from mira.application.contracts import CandidateRange, GenerationContext




class MockGenerationBackend:
    def __init__(self, delay_ms: int, *, character_review: bool = False) -> None:
        self._delay = delay_ms / 1000
        self._character_review = character_review

    async def generate(self, context: GenerationContext) -> AsyncIterator[CandidateRange]:
        if context.user_text == "/fail":
            await asyncio.sleep(self._delay)
            raise RuntimeError("synthetic provider failure")
        key = {"不要拍我": "camera", "听雨": "quiet", "看照片": "photo"}.get(
            context.user_text, "hello"
        )
        if self._character_review:
            key = {"演示：黑夹克":"code_black_jacket", "演示：奶油内搭":"code_cream_inner",
                   "演示：琥珀雨衣":"code_amber_raincoat", "演示：平常":"code_emotion_normal",
                   "演示：戒备":"code_emotion_guarded", "演示：开心":"code_emotion_happy",
                   "演示：娇羞":"code_emotion_shy", "演示：相机头饰":"code_camera_clip",
                   "演示：银星发卡":"code_star_clip"}.get(context.user_text, key)
        for name in (("photo", "photo_caption") if key == "photo" else (key,)):
            await asyncio.sleep(self._delay)
            yield CandidateRange(FIXTURES[name], name)
