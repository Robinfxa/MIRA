"""Offline source/context contracts; injected responses never prove model quality."""
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from mira.adapters.generation.codex_support.payload import author_instructions
from mira.adapters.generation.direct_codex_responses import (
    DirectCodexResponsesGenerationBackend, ResponsesRoute,
)
from mira.application.contracts import GenerationContext, generation_context_data
from mira.bootstrap.character_story import builtin_definition, ephemeral_character_factory
from mira.bootstrap.development_usage import UsageProfile
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.application.story import StoryRuntime
from mira.domain.models import Effect, EffectKind
from tests.contracts.test_conversation_first import Wire, session, settled, submit
from tests.contracts.test_direct_codex_responses import ByteStream, CredentialSource, completed, item_done
from tests.contracts.test_direct_provider_app import arguments

# Self-authored structural fixture, not the user's transcript or desired replacements.
# Bad repeated prose is intentional: software must preserve source evidence, not rewrite it.
SYNTHETIC_TURNS = (
    ('早啊', '早啊，我是 Mira。窗边很适合打招呼。'),
    ('早，Mira', '早，叫我 Mira。窗边很适合打招呼。'),
    ('你来这里做什么？', '我在等老朋友，有件小事还没办完。'),
    ('什么小事？', '有张选好的海边照片，想交给朋友。'),
    ('为什么拖到现在？', '我一直在选片。'),
    ('把那张拿给我看看', '我打算展示那张照片。'),
    ('有不同的照片吗？', '这一张之外，我现在没有可展示的照片。'),
    ('想看别的，可以吗？', '暂时没有另一张可展示的。'),
)
CONTINUITY_RULES = (
    'A repeated greeting does not restart the scene or require reintroduction.',
    'Resolve short follow-ups from the recent user inputs and presented replies,',
    'Available assets limit what can be shown, not what to talk about.',
    'Do not substitute the same photo or its story for a request for another one.',
)


@pytest.mark.parametrize('story', [False, True])
@pytest.mark.parametrize('speech', [False, True])
@pytest.mark.parametrize('memory', [False, True])
def test_fixed_prompt_uses_dialogue_continuity_without_canned_opening(story, speech, memory):
    instructions = author_instructions(speech_enabled=speech, memory_enabled=memory,
                                      character_story_enabled=story)
    for rule in CONTINUITY_RULES:
        assert rule in instructions
    assert instructions.count('mira-dialogue-continuity-v1') == 1
    assert 'For an ordinary greeting or identity question, introduce yourself naturally;' not in instructions
    assert '"我是 Mira，平时拍照片。" is a possible brief introduction' not in instructions
    assert 'never invent shared user experiences' in instructions
    assert len(instructions.encode()) < 12_000


def _effect(index, kind, text, epoch):
    return Effect(f'effect.{index}', kind, text, str(index).zfill(64), epoch, epoch)


def _projection():
    return StoryRuntime(builtin_definition(), 'synthetic-continuity-scope').project().projection


def _resolved_replies(data):
    result = []
    for row in data['first_person_dialogue']['presented_replies']:
        index = int(row['quoted_text_reference'].removeprefix('presented_effects[').removesuffix('].value'))
        result.append(data['presented_effects'][index])
    return result


def test_four_recent_distinct_reply_texts_do_not_spend_slots_on_paired_modalities():
    effects = tuple(_effect(2 * turn + modality, kind, f'合成回复 {turn}', turn + 1)
                    for turn in range(4)
                    for modality, kind in enumerate((EffectKind.SUBTITLE, EffectKind.SPEECH)))
    context = GenerationContext('继续', ('开场', '第二句', '第三句', '第四句', '继续'), effects, 5,
                                character_story=_projection())
    data = generation_context_data(context)
    assert [row['value'] for row in _resolved_replies(data)] == [f'合成回复 {turn}' for turn in range(4)]
    assert data['first_person_dialogue']['user_statements_omitted'] == 1
    assert data['first_person_dialogue']['presented_replies_omitted'] == 4
    assert data['presented_effects'] == generation_context_data(context, max_context_bytes=None)['presented_effects']
    assert context.presented_effects == effects


def test_equal_words_in_separate_turns_remain_separate_qualified_sources():
    repeated = tuple(_effect(i, EffectKind.SUBTITLE, '相同的合成文字', i + 1) for i in range(4))
    pending = _effect(9, EffectKind.SUBTITLE, '未展示的话不可进入历史', 5)
    context = GenerationContext('继续', ('继续',) * 5, repeated, 5,
                                accepted_prefix=(pending,), character_story=_projection())
    data = generation_context_data(context)
    assert [row['id'] for row in _resolved_replies(data)] == [row.id for row in repeated]
    assert pending.id not in [row['id'] for row in _resolved_replies(data)]
    assert data['first_person_dialogue']['physical_hearing_or_understanding_established'] is False


def test_bounded_dialogue_references_remap_to_exact_source_rows():
    inputs = tuple(f'合成用户句 {i}' for i in range(80))
    effects = tuple(_effect(2 * turn + modality, kind, f'合成第{turn}轮：' + '字' * 150, turn + 1)
                    for turn in range(79)
                    for modality, kind in enumerate((EffectKind.SUBTITLE, EffectKind.SPEECH)))
    context = GenerationContext(inputs[-1], inputs, effects, 80, character_story=_projection())
    data = generation_context_data(context)
    assert data['conversation_history']['historical_detail_omitted'] is True
    assert data['first_person_dialogue']['user_statements_omitted'] == len(inputs) - 4
    rows = _resolved_replies(data)
    assert [row['value'] for row in rows] == [f'合成第{i}轮：' + '字' * 150 for i in range(75, 79)]
    for row in rows:
        source = next(effect for effect in effects if effect.id == row['id'])
        assert (row['value'], row['digest'], row['output_epoch'], row['activity_seq'], row['kind']) == (
            source.value, source.digest, source.output_epoch, source.activity_seq, source.kind)
    assert data['first_person_dialogue']['presented_replies_omitted'] == len(effects) - len(rows)


def run_dialogue_probe(tmp_path, monkeypatch, route, story, turns=SYNTHETIC_TURNS):
    """Run only in-memory transports; callers supply synthetic or private local data."""
    from mira.adapters.diagnostics.recorder import LocalDiagnostics
    monkeypatch.setattr('mira.bootstrap.container.LocalDiagnostics',
                        lambda options, **kw: LocalDiagnostics(replace(options, root=tmp_path / Path(options.root)), **kw))
    async def forbidden(*_args, **_kwargs):
        raise AssertionError('No subprocess or provider is used by the dialogue probe')
    monkeypatch.setattr('asyncio.create_subprocess_exec', forbidden)
    bodies, characters = [], []
    source, review = CredentialSource(), Wire('reject')

    async def handler(request):
        body = json.loads(request.content)
        index = len(bodies)
        bodies.append(body)
        raw = json.dumps({'effects': [{'kind': 'subtitle', 'value': turns[index][1]}]}, ensure_ascii=False)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              stream=ByteStream([item_done(raw) + completed(output=None)]))

    base_factory = ephemeral_character_factory()
    def factory(state):
        character = base_factory(state)
        characters.append(character)
        return character
    generation = DirectCodexResponsesGenerationBackend(
        route, 'synthetic-model', source, admitted=True, request_limit=len(turns),
        speech_enabled=False, transport=httpx.MockTransport(handler))
    app = create_direct_provider_app(**arguments(
        route=route.value, api_billing_authorized=route is ResponsesRoute.OPENAI_API,
        generation=generation, input_transport=review, output_transport=review,
        usage_profile=UsageProfile.APPLICATION, generation_request_limit=len(turns),
        session_turn_limit=len(turns), character_factory=factory if story else None))
    with TestClient(app) as client:
        path, headers = session(client)
        for index, (user, reply) in enumerate(turns):
            submit(client, path, headers, activity=index + 1, cutoff=index, text=user)
            state = settled(client, path, headers)
            assert state['sealed'] and state['last_error'] is None
            assert len(bodies) == index + 1
            body = bodies[index]
            facts = json.loads(body['input'][0]['content'][0]['text'])['facts']
            assert facts['user_text'] == user
            assert facts['user_inputs'] == [row[0] for row in turns[:index + 1]]
            assert [effect['value'] for effect in facts['presented_effects']] == [row[1] for row in turns[:index]]
            assert facts['accepted_prefix'] == []
            assert 'conversation_history' not in facts  # This short session is not truncated.
            assert body['store'] is False and 'tools' not in body
            assert len(json.dumps(body, ensure_ascii=False).encode()) < 65_536
            if story:
                arrival = facts['character_story']['first_person_memory']['arrival_frame']
                assert arrival['mode'] == ('fresh_opening' if index == 0 else 'ongoing_scene')
                assert facts['first_person_dialogue']['output_epoch'] == facts['output_epoch']
                assert facts['first_person_dialogue']['binding_reference'] == 'character_story.projection_id'
                assert [effect['value'] for effect in _resolved_replies(facts)] == [row[1] for row in turns[max(0,index-4):index]]
            effect, = state['active_grants']
            assert effect['kind'] == 'subtitle' and effect['value'] == reply
            receipt = {key: effect[key] for key in ('digest', 'output_epoch', 'activity_seq')}
            receipt.update(effect_id=effect['id'], presentation_seq=index + 1)
            assert client.post(path + '/receipts', headers=headers, json=receipt).status_code == 200
        assert review.calls == []
        assert source.calls == len(turns)
        if characters:
            assert not characters[0].runtime.story.episodes
            assert not characters[0].runtime.story.pending
        assert client.delete(path, headers=headers).status_code in (200, 204)
    assert app.state.container.diagnostics.flush()
    return bodies


@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('story', [False, True])
def test_actor_direct_request_preserves_second_greeting_and_photo_followup(tmp_path, monkeypatch, route, story):
    run_dialogue_probe(tmp_path, monkeypatch, route, story)
