"""PDF-08 structural caption contract for Codex candidates; entirely offline."""
import json

import pytest

from mira.adapters.generation.codex_support.payload import parse_effects
from mira.adapters.generation.codex_support.types import CodexGenerationError, CodexLimits
from mira.domain.models import EffectKind


def parse(*effects):
    body = {"effects": [{"kind": kind, "value": value} for kind, value in effects]}
    return parse_effects([json.dumps(body, ensure_ascii=False)], CodexLimits())


def test_speech_without_explicit_caption_is_rejected():
    with pytest.raises(CodexGenerationError, match="codex_effects_invalid"):
        parse(("speech", "窗外正下着雨。"), ("pose", "look_at_rain"))


def test_spoken_reply_requires_one_explicit_corresponding_caption():
    spoken = "我们一起听雨。"
    caption = "雨声很轻。"
    effects = parse(("speech", spoken), ("subtitle", caption), ("pose", "look_at_rain"))
    assert [(effect.kind, effect.value) for effect in effects] == [
        (EffectKind.SPEECH, spoken), (EffectKind.SUBTITLE, caption),
        (EffectKind.POSE, "look_at_rain"),
    ]


def test_spoken_reply_rejects_multiple_captions():
    text = "窗外正下着雨。"
    with pytest.raises(CodexGenerationError, match="codex_effects_invalid"):
        parse(("speech", text), ("subtitle", text), ("subtitle", text))


def test_visual_only_subtitle_remains_valid_without_speech():
    text = "雨声很轻。"
    effects = parse(("subtitle", text), ("scene", "rain_window"))
    assert [(effect.kind, effect.value) for effect in effects] == [
        (EffectKind.SUBTITLE, text), (EffectKind.SCENE, "rain_window"),
    ]


def test_visual_controls_remain_valid_without_speech():
    effects = parse(("pose", "face_warm"), ("scene", "cafe_warm"))
    assert [(effect.kind, effect.value) for effect in effects] == [
        (EffectKind.POSE, "face_warm"), (EffectKind.SCENE, "cafe_warm"),
    ]
