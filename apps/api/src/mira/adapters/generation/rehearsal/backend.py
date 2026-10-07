"""Finite authored rehearsal, coupled to exact package clips and existing Actor effects.

Unknown input is never interpreted, echoed, or approved as arbitrary generated
content. Every response is authored and explicitly identified as an offline fixture.
"""
import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from importlib.resources import files
from types import MappingProxyType

from mira.application.contracts import (
    CandidateRange, EffectProposal, GenerationContext, ReviewObservation, ReviewVerdict,
)
from mira.application.ports.media import AudioPacket
from mira.domain.models import EffectKind

CLIP_IDS = frozenset({"greeting", "camera", "photo", "detail", "absent", "story", "rain", "warm"})
COMMANDS = MappingProxyType({"你好": "greeting", "不要拍我": "camera", "看照片": "photo",
                             "听雨": "rain", "暖灯": "warm"})
TRANSLATIONS = MappingProxyType({
    "greeting": "你好，我是 MIRA。这是离线排练。要一起看看旅行插画吗？",
    "camera": "当然，我会放低相机。你不需要出现在照片里。",
    "photo": "这是原创旅行插画：雨后的海岸，山岬上亮着灯的灯塔。",
    "detail": "画面还留在这里。灯塔照亮幽暗的海岸，暖光朝海面延伸。",
    "absent": "我们还没有打开旅行插画。请先选择「看照片」。",
    "story": "想象长途步行后抵达海岸。雨刚停，灯塔照着深色海面。暖光标出山岬，晚潮慢慢平静。不必匆忙，我们可以多看一会儿。",
    "rain": "一起转向雨窗吧。我们可以在这里停一停，留意窗外的世界。",
    "warm": "咖啡馆的灯光暖了起来。谢谢你一起度过这段安静的时光。",
})
HELP = "离线排练只支持固定口令：你好、不要拍我、看照片、照片里有什么、讲讲旅途、听雨、暖灯、/fail。未识别或转述刚才的文字，请点选口令。"


@dataclass(frozen=True, slots=True)
class RehearsalClip:
    text: str
    pcm: bytes


def load_clips() -> Mapping[str, RehearsalClip]:
    """Load only this package's named, integrity-checked authored fixture assets."""
    root = files(__package__).joinpath("fixtures/audio")
    manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != 1 or manifest.get("fixture_set") != "offline-rehearsal-v1"
            or manifest.get("sample_rate") != 24000 or manifest.get("channels") != 1
            or manifest.get("sample_width_bytes") != 2 or manifest.get("encoding") != "pcm_s16le"
            or manifest.get("synthetic") is not True or manifest.get("offline_only") is not True
            or set(manifest.get("clips", {})) != CLIP_IDS):
        raise ValueError("Invalid offline rehearsal audio manifest")
    clips = {}
    for name in sorted(CLIP_IDS):
        item = manifest["clips"][name]
        text = item.get("caption")
        if (item.get("pcm_file") != name + ".pcm" or not isinstance(text, str)
                or not 1 <= len(text) <= 1000):
            raise ValueError("Invalid offline rehearsal clip identity")
        pcm = root.joinpath(name + ".pcm").read_bytes()
        if (not 2 <= len(pcm) <= 24000 * 2 * 30 or len(pcm) % 2
                or item.get("frames") != len(pcm) // 2
                or hashlib.sha256(pcm).hexdigest() != item.get("pcm_sha256")):
            raise ValueError("Offline rehearsal clip failed integrity validation")
        clips[name] = RehearsalClip(text, pcm)
    if sum(len(clip.pcm) for clip in clips.values()) > 24000 * 2 * 90:
        raise ValueError("Offline rehearsal catalog exceeds its bound")
    if len({clip.text for clip in clips.values()}) != len(clips):
        raise ValueError("Offline rehearsal captions must be distinct")
    return MappingProxyType(clips)


def fixture_for(context: GenerationContext) -> str:
    if context.user_text in {"照片里有什么", "讲讲旅途"}:
        exposed = any(effect.kind == EffectKind.MEDIA and effect.value == "trip_photo"
                      for effect in context.presented_effects)
        if exposed and not context.photo_visible:
            return "closed"
        return ("detail" if context.user_text == "照片里有什么" else "story") if exposed and context.photo_visible else "absent"
    return COMMANDS.get(context.user_text, "help")


def authored_ranges(clips: Mapping[str, RehearsalClip]) -> Mapping[str, CandidateRange]:
    visuals = {
        "greeting": (EffectProposal(EffectKind.POSE, "face_curious"),),
        "camera": (EffectProposal(EffectKind.POSE, "camera_lowered"),),
        "photo": (EffectProposal(EffectKind.MEDIA, "trip_photo"),),
        "detail": (EffectProposal(EffectKind.POSE, "face_curious"),),
        "absent": (EffectProposal(EffectKind.POSE, "face_curious"),),
        "story": (EffectProposal(EffectKind.POSE, "face_reflective"),),
        "rain": (EffectProposal(EffectKind.SCENE, "rain_window"),),
        "warm": (EffectProposal(EffectKind.SCENE, "cafe_warm"),),
    }
    rows = {name: CandidateRange((
        EffectProposal(EffectKind.SPEECH, clip.text),
        EffectProposal(EffectKind.SUBTITLE, TRANSLATIONS[name] + "\n" + clip.text),
        *visuals[name],
    ), "rehearsal:" + name) for name, clip in clips.items()}
    rows["help"] = CandidateRange((EffectProposal(EffectKind.SUBTITLE, HELP),), "rehearsal:help")
    rows["closed"] = CandidateRange((EffectProposal(EffectKind.SUBTITLE,
        "旅行插画已收起。我们之前展示过那幅海岸与灯塔；选择「看照片」可以再次打开。"),), "rehearsal:closed")
    return MappingProxyType(rows)


class RehearsalGenerationBackend:
    def __init__(self, ranges: Mapping[str, CandidateRange], delay_ms: int) -> None:
        self._ranges = ranges
        self._delay = delay_ms / 1000

    async def generate(self, context: GenerationContext) -> AsyncIterator[CandidateRange]:
        await asyncio.sleep(self._delay)
        if context.user_text == "/fail":
            raise RuntimeError("synthetic rehearsal failure")
        yield self._ranges[fixture_for(context)]


class RehearsalReviewBackend:
    """Exact authored output AND command/presented-history context, not live review."""
    def __init__(self, ranges: Mapping[str, CandidateRange]) -> None:
        self._ranges = ranges

    async def review(self, context: GenerationContext, candidate: CandidateRange) -> ReviewObservation:
        accepted = context.user_text != "/fail" and candidate == self._ranges[fixture_for(context)]
        return ReviewObservation(ReviewVerdict.ALLOW if accepted else ReviewVerdict.REJECT,
                                 "exact_rehearsal_fixture" if accepted else "not_a_rehearsal_fixture")


class RehearsalSpeechBackend:
    """Serves prerecorded synthetic English PCM; no synthesis or network at runtime."""
    def __init__(self, clips: Mapping[str, RehearsalClip]) -> None:
        self._audio = MappingProxyType({clip.text: clip.pcm for clip in clips.values()})

    async def synthesize(self, approved_text: str, stream_id: str) -> AsyncIterator[AudioPacket]:
        pcm = self._audio.get(approved_text)
        if pcm is None:
            raise ValueError("Only exact authored rehearsal speech can be played")
        for start in range(0, len(pcm), 12000):
            await asyncio.sleep(0)  # existing Actor cancellation owns every continuation
            yield AudioPacket(stream_id, start // 2, 24000, pcm[start:start + 12000])
