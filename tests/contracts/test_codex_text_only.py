"""Text-only Codex output still enters the existing subtitle and pose renderer."""
import json

import pytest

from mira.adapters.generation.codex_app_server import CodexGenerationError, CodexLimits
from mira.adapters.generation.codex_support.payload import output_schema, parse_effects
from mira.domain.models import EffectKind
from tests.contracts.test_codex_generation import (
    CONTEXT, SyntheticTransport, agent, collect, event, make, terminal,
)


@pytest.mark.asyncio
async def test_text_only_candidate_has_independent_subtitle_and_pose_without_audio():
    output = {"effects": [
        {"kind": "subtitle", "value": "我写下一句新的话。"},
        {"kind": "pose", "value": "face_warm"},
    ]}
    transport = SyntheticTransport(events=[
        event("item/completed", item=agent(json.dumps(output, ensure_ascii=False))), terminal(),
    ])
    backend, _, _ = make(transport, speech_enabled=False)

    candidate, = await collect(backend)

    assert [effect.kind for effect in candidate.effects] == [EffectKind.SUBTITLE, EffectKind.POSE]
    assert all(effect.kind != EffectKind.SPEECH for effect in candidate.effects)
    calls = {item["method"]: item.get("params") for item in transport.sent}
    thread = calls["thread/start"]
    assert "text-only" in thread["baseInstructions"]
    turn = calls["turn/start"]
    allowed = {kind for choice in turn["outputSchema"]["properties"]["effects"]["items"]["anyOf"]
               for kind in choice["properties"]["kind"]["enum"]}
    assert allowed == {"subtitle", "pose", "scene", "media"}
    assert json.loads(turn["input"][0]["text"])["capabilities"] == {"speech_enabled": False}


def test_text_only_parser_rejects_speech_even_when_caption_is_present():
    body = {"effects": [
        {"kind": "speech", "value": "我会说出这句话。"},
        {"kind": "subtitle", "value": "字幕也在这里。"},
    ]}
    with pytest.raises(CodexGenerationError, match="codex_effects_unsupported"):
        parse_effects([json.dumps(body, ensure_ascii=False)], CodexLimits(), speech_enabled=False)


def test_legacy_generation_keeps_speech_schema_and_text_only_does_not():
    legacy = output_schema()
    text_only = output_schema(speech_enabled=False)
    def kinds(schema):
        return {kind for item in schema["properties"]["effects"]["items"]["anyOf"]
                for kind in item["properties"]["kind"]["enum"]}
    assert "speech" in kinds(legacy)
    assert "speech" not in kinds(text_only)



def test_text_only_fixed_photo_is_exact_and_arbitrary_media_is_rejected():
    effects=parse_effects([json.dumps({'effects':[
        {'kind':'subtitle','value':'可以看看这张原创插画。'},
        {'kind':'media','value':'trip_photo'}]})],CodexLimits(),speech_enabled=False)
    assert [(effect.kind.value,effect.value) for effect in effects]==[
        ('subtitle','可以看看这张原创插画。'),('media','trip_photo')]
    media=next(choice for choice in output_schema(speech_enabled=False)['properties']['effects']['items']['anyOf']
        if choice['properties']['kind']['enum']==['media'])
    assert media['properties']['value']['enum']==['trip_photo']
    for value in ('user_photo','trip_photo_placeholder','/tmp/photo.svg','https://example.com/photo.jpg'):
        with pytest.raises(CodexGenerationError,match='codex_effects_unsupported'):
            parse_effects([json.dumps({'effects':[{'kind':'media','value':value}]})],
                CodexLimits(),speech_enabled=False)
