"""Only the three compiled chapter presentation values extend the legacy vocabulary.

These are untrusted candidate syntax, never permission to advance chapter state.
"""
import json

import pytest

from mira.adapters.generation.codex_support.payload import SCENES, output_schema, parse_effects
from mira.adapters.generation.codex_support.types import CodexGenerationError, CodexLimits


@pytest.mark.parametrize('value', ['xiahe_recognition', 'xiahe_gift_offer', 'xiahe_photo_handover'])
def test_three_chapter_beats_parse_as_scene_candidates(value):
    result = parse_effects([json.dumps({'effects': [{'kind': 'scene', 'value': value}]})], CodexLimits())
    assert len(result) == 1
    assert result[0].kind.value == 'scene'
    assert result[0].value == value


@pytest.mark.parametrize('value', ['xiahe_arrival', 'xiahe_doorway', '夏阖', 'handover_complete'])
def test_no_npc_arrival_alias_or_invented_completion_value(value):
    with pytest.raises(CodexGenerationError):
        parse_effects([json.dumps({'effects': [{'kind': 'scene', 'value': value}]})], CodexLimits())


def test_schema_advertises_exact_scene_vocabulary_without_media_aliasing():
    alternatives = output_schema()['properties']['effects']['items']['anyOf']
    scene = next(item for item in alternatives if item['properties']['kind']['enum'] == ['scene'])
    media = next(item for item in alternatives if item['properties']['kind']['enum'] == ['media'])
    assert scene['properties']['value']['enum'] == list(SCENES)
    assert set(SCENES) == {'cafe', 'rain_window', 'cafe_warm', 'xiahe_recognition', 'xiahe_gift_offer', 'xiahe_photo_handover'}
    assert 'xiahe_photo_handover' not in media['properties']['value']['enum']
