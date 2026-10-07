"""Prefer recent actual dialogue to older optional input under the same wire cap."""
import json
from dataclasses import replace

from mira.application.contracts import GenerationContext, generation_context_data
from mira.domain.models import EffectKind
from tests.contracts.test_bounded_conversation_context import effect


def size(data):
    return len(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def test_recent_presented_reply_group_survives_older_input_pressure():
    inputs = tuple("旧事" * 250 for _ in range(56)) + ("看看",)
    outfit = effect(0, EffectKind.POSE, "outfit_amber_raincoat")
    old = tuple(effect(i + 1, text="旧话" * 160) for i in range(56))
    recent = (
        replace(effect(100, text="如果你想看内搭，"), output_epoch=100),
        replace(effect(101, text="我可以先把雨衣脱下来。"), output_epoch=100),
    )
    context = GenerationContext("看看", inputs, (outfit,) + old + recent, 101)
    data = generation_context_data(context)
    shown = {row["id"]: row for row in data["presented_effects"]}
    assert all(shown[item.id]["value"] == item.value for item in recent)
    assert shown[outfit.id]["digest"] == outfit.digest
    assert data["user_inputs"][-1] == "看看"
    assert data["conversation_history"]["omitted_accepted_inputs"] > 0
    assert data["conversation_history"]["semantic_summary_available"] is False
    assert size(data) <= 48_000
    assert context.user_inputs == inputs and context.presented_effects == (outfit,) + old + recent


def test_oversized_recent_reply_stays_optional_and_does_not_block_current_input():
    latest = effect(100, text="很长的已显示文本" * 10_000)
    context = GenerationContext("现在的问题", ("以前的问题", "现在的问题"), (latest,), 102)
    data = generation_context_data(context, max_context_bytes=4_000)
    assert data["user_inputs"][-1] == "现在的问题"
    assert data["presented_effects"] == ()
    assert data["conversation_history"]["omitted_presented_effects"] == 1
    assert data["conversation_history"]["historical_detail_omitted"] is True
    assert size(data) <= 4_000
    assert context.presented_effects == (latest,)
