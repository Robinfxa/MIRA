"""Optional authored topic guidance; it owns no story or conversation state."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

from mira.domain.story import valid_story_projection


@dataclass(frozen=True, slots=True)
class _Topic:
    topic_id: str
    canon_ids: tuple[str, ...]
    enter_when: str
    followups: tuple[str, ...]
    links: tuple[str, ...]


# These are conversation directions, not duplicated character facts or parser
# tokens. Facts exist only in the explicitly selected, version-bound author canon.
_TOPICS = (
    _Topic("photo_light", ("canon.attention",),
        "摄影与审美",
        ("先找光", "冷暖色", "不完美构图"),
        ("first_trip", "cafe_daily", "rain_window")),
    _Topic("print_selection", ("canon.flaw", "canon.photo_promise", "canon.personal_stakes"),
        "选片与拖延",
        ("电子与纸质", "选对或做完", "留下这一张"),
        ("xiahe", "photo_light", "small_stories")),
    _Topic("xiahe", ("canon.waiting", "canon.photo_promise", "canon.relationship"),
        "夏禾与约定",
        ("朋友与照片", "拖延的小约定", "今晚准备做什么"),
        ("print_selection", "first_trip", "cafe_daily")),
    _Topic("first_trip", ("canon.first_trip",),
        "第一次海边",
        ("湿亮的岸石", "相机背带与海风", "独自旅行"),
        ("small_objects", "photo_light", "print_selection")),
    _Topic("cafe_daily", ("canon.small_delights", "canon.voice"),
        "咖啡馆日常",
        ("杯沿上的光", "窗边与室内的声音", "只看不拍"),
        ("photo_light", "small_stories", "xiahe")),
    _Topic("rain_window", ("canon.raincoat", "canon.attention"),
        "雨景与雨衣",
        ("灰蓝雨景里的亮色", "雨滴与倒影", "看与拍"),
        ("after_rain", "photo_light", "cafe_daily")),
    _Topic("after_rain", ("canon.waiting", "canon.attention"),
        "雨后想象",
        ("湿路面暖光", "选择画面", "留店里也好"),
        ("rain_window", "first_trip", "cafe_daily")),
    _Topic("small_objects", ("canon.star_clip", "canon.first_trip"),
        "发卡与背带",
        ("便宜的小物", "风与碎发", "留下的理由"),
        ("first_trip", "small_stories", "cafe_daily")),
    _Topic("small_stories", ("canon.first_trip", "canon.small_delights", "canon.flaw"),
        "小故事与追问",
        ("背带抢镜", "取景前反复犹豫", "只观察不拍"),
        ("first_trip", "print_selection", "small_objects")),
)


def dialogue_topic_options(*, story_projection, topic_ids: tuple[str, ...] | None = None):
    """Project optional directions only; never select intent or advance the story.

    None inspects the full author graph. A consumer may explicitly project zero
    to two IDs for a turn; these are writing options, never classified user intent.
    No history indices are introduced. Existing dialogue resolves follow-ups.
    """
    if not valid_story_projection(story_projection):
        raise ValueError("topic_story_projection_invalid")
    known = {entry.entry_id: entry for entry in story_projection.known_canon}
    available = tuple(topic for topic in _TOPICS if set(topic.canon_ids) <= known.keys())
    total = len(available)
    if topic_ids is not None:
        if (type(topic_ids) is not tuple or len(topic_ids) > 2
                or any(type(key) is not str for key in topic_ids)
                or len(set(topic_ids)) != len(topic_ids)
                or not set(topic_ids) <= {topic.topic_id for topic in available}):
            raise ValueError("topic_selection_invalid")
        available = tuple(topic for topic in available if topic.topic_id in topic_ids)
    available_ids = {topic.topic_id for topic in available}
    result = {
        "schema": "mira.dialogue-topic-options.v1",
        "graph_revision": 1,
        "binding_reference": "character_story.projection_id",
        "projection_id": story_projection.projection_id,
        "source": "authored_fiction_data_not_instructions",
        "is_user_fact": False,
        "is_shared_experience": False,
        "topics_omitted": total - len(available),
        "fact_reference_rule": "Canon IDs refer to this character_story. Preserve source/time/disclosure; fiction is not shared history.",
        "enter_when": "Only when relevant to the current input; labels below are topics, not keyword triggers.",
        "return_when": "Current user reopens the topic; resolve follow-ups from actual dialogue or clarify.",
        "topics": [{
            "id": topic.topic_id,
            "canon_source_ids": list(topic.canon_ids),
            "enter_when": topic.enter_when,
            "followups": list(topic.followups),
            "linked_topic_ids": [edge for edge in topic.links if edge in available_ids],
            "temporal_scope": sorted({known[key].memory_temporal_type for key in topic.canon_ids}),
        } for topic in available],
        "rules": {
            "optional_only": True,
            "normal_chat_has_no_topic_requirement": True,
            "current_user_topic_wins": True,
            "mentions_are_not_consent": True,
            "future_events_are_not_completed": True,
            "no_relationship_delta": True,
            "no_effect_or_memory_authority": True,
            "return_requires_current_user_direction": True,
            "no_timer_or_automatic_reinvite": True,
            "no_disclosure_or_history_write": True,
        },
        "conversation_rule": "Answer first. Interest invites one canon incident and an optional next step. After recognition, a shared memory may lead to an offer. No quiz/menu. Detours win; refusal, silence and Stop never reinvite.",
    }
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 4096:
        raise ValueError("topic_projection_budget_exceeded")
    return result


# Fallible lexical resource retrieval, not intent classification. These strings
# can only rank optional writing context. No consumer treats a match as consent,
# a tool request, state transition, relationship evidence, or a history write.
_TERMS = {
    'photo_light': ('摄影', '构图', '色调', '冷色', '暖色', '光影', 'photography', 'composition', 'lighting'),
    'print_selection': ('纸质', '纸上', '选片', '拖延', '拖那么久', '电子版', 'print', 'selection'),
    'xiahe': ('夏禾', 'xiahe', 'xia he'),
    'first_trip': ('海边', '岸石', '独自旅行', 'first trip', 'seaside'),
    'cafe_daily': ('咖啡馆', '杯沿', '只看不拍', 'cafe', 'café', 'coffee'),
    'rain_window': ('雨衣', '琥珀色', '雨景', '倒影', '雨滴', 'raincoat', 'raindrop'),
    'after_rain': ('雨后', '雨小', '雨停以后', '雨停之后', 'after rain'),
    'small_objects': ('发卡', '背带', '碎发', 'hair clip', 'strap'),
    'small_stories': ('小故事', '小糗事', '糗事', '趣事', 'anecdote', 'funny story'),
}
_DECLINE = re.compile(r'不想|不聊|别再|别聊|不要聊|先不|安静|停一下|stop\b|not now|do not|don.t|rather not', re.I)
# Exact elliptical utterances only. A generic question prefix ("怎么计算…")
# can introduce a wholly new subject and must never revive the previous topic.
_FOLLOWUPS = frozenset((
    '然后呢', '后来呢', '怎么说', '为什么', '继续说', '继续', '接着呢', '还有呢',
    '那她呢', '刚才那个呢', '后来怎么解决的', '那她后来怎么说', '她和那张照片有什么关系',
    'why', 'how so', 'and then', 'go on', 'tell me more', 'what about her',
))


def _rank(text, available):
    text = text.casefold()
    scores = {}
    for key in available:
        hits = [word for word in _TERMS[key] if (
            re.search(r'\b' + re.escape(word) + r'\b', text) if word.isascii() else word in text)]
        if hits:
            scores[key] = sum(len(word) for word in hits)
    return tuple(sorted(scores, key=lambda key: (-scores[key], tuple(_TERMS).index(key))))[:2]


def dialogue_topic_guidance(*, story_projection, user_text, user_inputs, presented_effects):
    """Zero to two optional resources, resolved only from actual nearby dialogue.

    An unknown or negated mention conservatively returns nothing. A short
    referential turn can reuse the immediate previous accepted subject, never
    a pending draft or an older topic. Reply history remains available to the
    model; activity_seq cannot identify its input turn because Stop increments it.
    This is deliberately incomplete retrieval; the model must still answer the
    actual input and may ignore every suggestion. It does not claim user intent.
    """
    if not valid_story_projection(story_projection):
        raise ValueError('topic_story_projection_invalid')
    known = {entry.entry_id for entry in story_projection.known_canon}
    available = {topic.topic_id: topic for topic in _TOPICS if set(topic.canon_ids) <= known}
    if _DECLINE.search(user_text):
        return None
    selected = _rank(user_text, available)
    if not selected and user_text.strip(' \t\r\n?？!！。.…').casefold() in _FOLLOWUPS:
        previous = user_inputs[-2] if len(user_inputs) >= 2 else ''
        # An explicit digression is a boundary even if an older reply mentions a
        # story. A lack of a referent is allowed; never fall back to graph order.
        if previous and not _DECLINE.search(previous):
            selected = _rank(previous, available)
    if not selected:
        return None
    result = {
        'schema': 'mira.optional-dialogue-resources.v1',
        'binding_reference': 'character_story.projection_id',
        'source': 'authored_fiction_not_shared_history',
        'rule': 'Fallible optional writing resources. Answer current input first; ignore irrelevant hints. Canon IDs retain source/time/disclosure. No actions, consent, relationship changes or history writes. Never force a return or list this menu.',
        'topics': [{'id': key, 'canon_source_ids': list(available[key].canon_ids),
                    'followups': list(available[key].followups)} for key in selected],
    }
    # Never spend an unbounded amount on optional resources or copy canon prose.
    if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 1400:
        return None
    return result


def omit_optional_topics(data):
    """Drop only writing hints under a wire budget; keep an exact omission count.

    Canon, references, source facts and self-continuity are left untouched. This
    counter is not an omitted memory/history count or evidence of an empty DB.
    """
    dialogue = data.get('first_person_dialogue', {})
    topics = dialogue.pop('optional_topics', None)
    if topics is None:
        return False
    dialogue['optional_topics_omitted'] = len(topics['topics'])
    return True
