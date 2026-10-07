"""Narrow deterministic user commands; model output is never an input here.

The visible control is the complete interface. These conservative aliases cover
unambiguous user commands, not arbitrary natural-language intent classification.
An unrecognized sentence preserves the existing preference, especially mute.
"""
import re
from dataclasses import replace
from typing import Literal

from mira.domain.models import SessionState

ResponseMode = Literal["voice", "text_only"]
_UNMUTE = frozenset(("取消静音", "可以开声音", "开启声音", "打开声音", "恢复语音", "可以说话了", "现在可以说话了",
                     "unmute", "enable voice", "turn on voice"))
_MUTE = re.compile(r"^(?:请|麻烦)?(?P<scope>这次|这一轮|本轮|这条回复|以后|今后|从现在起|从现在开始)?"
                   r"(?:请|都)?(?:保持静音|静音|只打字|只用文字(?:回复)?|仅用文字(?:回复)?|别说话|不要说话|不要出声)"
                   r"(?:[，,。.!！;；]|$)")
_TURN = frozenset(("这次", "这一轮", "本轮", "这条回复"))


def user_response_preference(text: str) -> Literal["mute", "turn_text_only", "unmute"] | None:
    value = text.strip().lower().rstrip("。.!！ ")
    # Full utterance match only for granting voice. Quotes, negation and reported
    # speech cannot restore it, nor can text after "until I say ...".
    if value.removeprefix('请') in _UNMUTE:
        return "unmute"
    if value in ("mute", "text only", "don't speak", "do not speak"):
        return "mute"
    if value in ("text only this turn", "this turn text only"):
        return "turn_text_only"
    command = _MUTE.match(value)
    if command:
        return "turn_text_only" if command['scope'] in _TURN else "mute"
    return None


def begin_response(state: SessionState, text: str, *, speech_available: bool) -> SessionState:
    command = user_response_preference(text)
    muted = state.response_muted
    if command == "mute":
        muted = True
    elif command == "unmute":
        muted = False
    mode = "text_only" if muted or command == "turn_text_only" or not speech_available else "voice"
    return replace(state, response_muted=muted, response_mode=mode,
                   # Repeated explicit commands also fence an older UI write.
                   response_preference_revision=state.response_preference_revision + int(command in ('mute', 'unmute')))


def generation_speech_enabled(context, configured: bool) -> bool:
    if (type(configured) is not bool or (context.response_mode is not None
            and (type(context.response_mode) is not str
                 or context.response_mode not in ("voice", "text_only")))):
        raise ValueError("response_mode_invalid")
    return configured and context.response_mode != "text_only"
