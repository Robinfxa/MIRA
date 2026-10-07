"""Single authored fixture catalogue for both generators and their strict reviewer."""
from collections.abc import Mapping
from types import MappingProxyType

from mira.application.contracts import EffectProposal
from mira.domain.models import EffectKind

FIXTURES: Mapping[str, tuple[EffectProposal, ...]] = MappingProxyType({
    "code_black_jacket": (EffectProposal(EffectKind.POSE, "outfit_black_jacket"),
        EffectProposal(EffectKind.SUBTITLE, "离线固定换装示范：黑夹克。没有调用模型。")),
    "code_cream_inner": (EffectProposal(EffectKind.POSE, "outfit_cream_inner_only"),
        EffectProposal(EffectKind.SUBTITLE, "离线固定换装示范：保留奶油色内搭。没有调用模型。")),
    "code_amber_raincoat": (EffectProposal(EffectKind.POSE, "outfit_amber_raincoat"),
        EffectProposal(EffectKind.SUBTITLE, "离线固定换装示范：琥珀雨衣。没有调用模型。")),
    "code_emotion_normal": (EffectProposal(EffectKind.POSE, "emotion_normal"),),
    "code_emotion_guarded": (EffectProposal(EffectKind.POSE, "emotion_guarded"),),
    "code_emotion_happy": (EffectProposal(EffectKind.POSE, "emotion_happy"),),
    "code_emotion_shy": (EffectProposal(EffectKind.POSE, "emotion_shy"),),
    "code_camera_clip": (EffectProposal(EffectKind.POSE, "accessory_camera_clip"),),
    "code_star_clip": (EffectProposal(EffectKind.POSE, "accessory_star_clip"),),
    "camera": (EffectProposal(EffectKind.POSE, "camera_lowered"),),
    "quiet": (EffectProposal(EffectKind.SCENE, "rain_window"),),
    "photo": (EffectProposal(EffectKind.MEDIA, "trip_photo_placeholder"),),
    "photo_caption": (EffectProposal(EffectKind.SUBTITLE, "这是一张受控的占位照片；还没有接入真实素材。"),),
    "hello": (EffectProposal(EffectKind.SUBTITLE, "MIRA 基础联调已连通。当前是 Mock，没有调用真实模型。"),),
})
