"""Single authored fixture catalogue for both generators and their strict reviewer."""
from collections.abc import Mapping
from types import MappingProxyType

from mira.application.contracts import EffectProposal
from mira.domain.models import EffectKind

FIXTURES: Mapping[str, tuple[EffectProposal, ...]] = MappingProxyType({
    "camera": (EffectProposal(EffectKind.POSE, "camera_lowered"),),
    "quiet": (EffectProposal(EffectKind.SCENE, "rain_window"),),
    "photo": (EffectProposal(EffectKind.MEDIA, "trip_photo_placeholder"),),
    "photo_caption": (EffectProposal(EffectKind.SUBTITLE, "这是一张受控的占位照片；还没有接入真实素材。"),),
    "hello": (EffectProposal(EffectKind.SUBTITLE, "MIRA 基础联调已连通。当前是 Mock，没有调用真实模型。"),),
})
