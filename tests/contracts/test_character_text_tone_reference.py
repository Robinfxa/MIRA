"""Authored tone fixtures verify requests and transport, never live LLM quality."""
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from mira.adapters.generation.codex_support.payload import author_instructions, parse_effects
from mira.adapters.generation.codex_support.types import CodexGenerationError, CodexLimits
from mira.adapters.generation.direct_codex_responses import (
    DirectCodexResponsesGenerationBackend, DirectResponsesLimits, ResponsesRoute,
)
from mira.application.contracts import GenerationContext
from mira.bootstrap.character_story import ephemeral_character_factory
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.bootstrap.development_usage import UsageProfile
from tests.contracts.test_conversation_first import Wire, session, settled, submit
from tests.contracts.test_direct_codex_responses import (
    ByteStream, CredentialSource, completed, item_done,
)
from tests.contracts.test_direct_provider_app import arguments

FIXTURE = (Path(__file__).parents[2] / 'specs/features/WP12-text-tone-reference'
           / 'fixtures/conversation.json')
TURNS = json.loads(FIXTURE.read_text())['turns']
TONE_MARKER = 'Text tone refinement: mira-text-tone-v1.'
TONE_RULES = (
    'React to the interesting, important or emotional point',
    'none is a quota or an every-turn opener or closer.',
    'For distress or serious help, give a complete, respectful reply',
    'without automatic laughter or flirtation; care and clarity outrank brevity.',
    'without tiny-message targets or a no-punctuation quota.',
    'Avoid borrowed intimate nicknames or closeness not established in this conversation.',
    'never copy distinctive lines or adopt their names, experiences, relationships or promises',
    'These choices do not alter message timing, cue grouping or speech/subtitle contracts.',
)


def assert_tone_request(instructions):
    # Exact instruction assertions describe the authoring contract, not a reply score.
    assert instructions.count(TONE_MARKER) == 1
    assert instructions.count('mira-character-voice-v4') == 1
    for rule in TONE_RULES:
        assert rule in instructions
    assert 'truthfully identify as an AI portraying the fictional character Mira' in instructions
    assert 'Never fake expertise or certainty.' in instructions
    assert 'Return only one JSON object with effects.' in instructions
    assert 'at most one speech' in instructions
    assert 'separately authored subtitle corresponding to that same speech cue' in instructions
    assert len(instructions.encode()) < 12_000  # Preserve the existing request assertion.
    for turn in TURNS:
        assert turn['user'] not in instructions
        assert turn['reply'] not in instructions
        assert turn['contrast'] not in instructions


@pytest.mark.parametrize('speech', [False, True])
@pytest.mark.parametrize('memory', [False, True])
@pytest.mark.parametrize('story', [False, True])
def test_tone_refinement_is_fixed_once_on_each_existing_capability_path(speech, memory, story):
    instructions = author_instructions(speech_enabled=speech, memory_enabled=memory,
                                       character_story_enabled=story)
    assert_tone_request(instructions)
    assert ('explicitly text-only' in instructions) is (not speech)
    assert ('optional facts.memory_evidence' in instructions) is memory
    assert ('optional facts.character_story' in instructions) is story
    assert CodexLimits().max_prompt_bytes == DirectResponsesLimits().max_prompt_bytes == 65_536


def authored_effects(speech):
    # Deliberately complete, multi-sentence serious help: never one TTS call per sentence.
    effects = [{'kind': 'subtitle', 'value': TURNS[3]['reply']}]
    if speech:
        effects.append({'kind': 'speech', 'value': TURNS[3]['reply']})
    return effects


@pytest.mark.asyncio
@pytest.mark.parametrize('speech', [False, True])
async def test_native_request_keeps_tone_and_complete_authored_cue(speech):
    from tests.contracts.test_codex_generation import (
        SyntheticTransport, agent, collect, event, make, terminal,
    )
    effects = authored_effects(speech)
    transport = SyntheticTransport(events=[
        event('item/completed', item=agent(json.dumps({'effects': effects}, ensure_ascii=False))),
        terminal(),
    ])
    backend, _, factory = make(transport, speech_enabled=speech)
    context = GenerationContext(TURNS[3]['user'], (TURNS[3]['user'],), (), 1)
    candidates = await collect(backend, context)
    start = next(call['params'] for call in transport.sent if call['method'] == 'thread/start')
    turns = [call['params'] for call in transport.sent if call['method'] == 'turn/start']
    assert_tone_request(start['baseInstructions'])
    assert len(turns) == len(factory.calls) == len(candidates) == 1
    assert json.loads(turns[0]['input'][0]['text'])['facts']['user_text'] == TURNS[3]['user']
    assert [{'kind': row.kind.value, 'value': row.value}
            for row in candidates[0].effects] == effects
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('speech', [False, True])
async def test_direct_request_keeps_tone_and_complete_authored_cue(route, speech):
    effects = authored_effects(speech)
    calls, streams = [], []

    async def handler(request):
        calls.append(json.loads(request.content))
        raw = json.dumps({'effects': effects}, ensure_ascii=False)
        wire = item_done(raw) + completed(output=None)
        stream = ByteStream([wire[i:i + 7] for i in range(0, len(wire), 7)])
        streams.append(stream)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)

    source = CredentialSource()
    generation = DirectCodexResponsesGenerationBackend(
        route, 'synthetic-model', source, admitted=True, request_limit=1,
        speech_enabled=speech, transport=httpx.MockTransport(handler))
    context = GenerationContext(TURNS[3]['user'], (TURNS[3]['user'],), (), 1)
    candidates = [row async for row in generation.generate(context)]
    assert len(calls) == source.calls == len(candidates) == 1
    assert_tone_request(calls[0]['instructions'])
    assert calls[0]['store'] is False and 'tools' not in calls[0]
    assert json.loads(calls[0]['input'][0]['content'][0]['text'])['facts']['user_text'] == TURNS[3]['user']
    assert [{'kind': row.kind.value, 'value': row.value}
            for row in candidates[0].effects] == effects
    assert all(stream.closed for stream in streams)


@pytest.mark.parametrize('raw', [
    '```json\n{"effects":[{"kind":"subtitle","value":"完整回答。"}]}\n```',
    '{"effects":[],"effects":[{"kind":"subtitle","value":"完整回答。"}]}',
    '{"effects":[{"kind":"speech","value":"缺少对应字幕。"}]}',
    '{"effects":[{"kind":"speech","value":"第一段。"},'
    '{"kind":"speech","value":"第二段。"},{"kind":"subtitle","value":"字幕。"}]}',
    '{"effects":[{"kind":"speech","value":"完整语音。"},'
    '{"kind":"subtitle","value":"第一段。"},{"kind":"subtitle","value":"第二段。"}]}',
])
def test_tone_refinement_does_not_relax_json_or_full_speech_cue_contract(raw):
    with pytest.raises(CodexGenerationError):
        parse_effects([raw], CodexLimits(), speech_enabled=True)


@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('story', [False, True])
def test_authored_tone_dialogue_through_actual_asgi_keeps_receipts_and_reference_boundary(
        tmp_path, monkeypatch, route, story):
    from mira.adapters.diagnostics.recorder import LocalDiagnostics

    def diagnostics(options, **kwargs):
        return LocalDiagnostics(replace(options, root=tmp_path / Path(options.root)), **kwargs)
    monkeypatch.setattr('mira.bootstrap.container.LocalDiagnostics', diagnostics)

    async def forbid_subprocess(*_args, **_kwargs):
        raise AssertionError('Tone refinement must not add native provider requests')
    monkeypatch.setattr('asyncio.create_subprocess_exec', forbid_subprocess)
    requests, streams, characters = [], [], []
    source, review = CredentialSource(), Wire('reject')

    async def handler(request):
        requests.append(request)
        turn = TURNS[len(requests) - 1]
        raw = json.dumps({'effects': [{'kind': 'subtitle', 'value': turn['reply']}]},
                         ensure_ascii=False)
        wire = item_done(raw) + completed(output=None)
        stream = ByteStream([wire[i:i + 7] for i in range(0, len(wire), 7)])
        streams.append(stream)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)

    factory = ephemeral_character_factory()

    def character_factory(state):
        character = factory(state)
        characters.append(character)
        return character

    generation = DirectCodexResponsesGenerationBackend(
        route, 'synthetic-model', source, admitted=True, request_limit=len(TURNS),
        speech_enabled=False, transport=httpx.MockTransport(handler))
    app = create_direct_provider_app(**arguments(
        route=route.value, api_billing_authorized=route is ResponsesRoute.OPENAI_API,
        generation=generation, input_transport=review, output_transport=review,
        usage_profile=UsageProfile.APPLICATION,
        generation_request_limit=len(TURNS), session_turn_limit=len(TURNS),
        character_factory=character_factory if story else None))
    with TestClient(app) as client:
        path, headers = session(client)
        initial_node = characters[0].runtime.story.node if characters else None
        for index, turn in enumerate(TURNS):
            submit(client, path, headers, activity=index + 1, cutoff=index, text=turn['user'])
            state = settled(client, path, headers)
            assert len(requests) == index + 1
            body = json.loads(requests[index].content)
            assert_tone_request(body['instructions'])
            assert 'explicitly text-only' in body['instructions']
            assert body['store'] is False and 'tools' not in body
            assert len(requests[index].content) < DirectResponsesLimits().max_request_bytes
            prompt = json.loads(body['input'][0]['content'][0]['text'])
            facts = prompt['facts']
            assert facts['user_inputs'] == [row['user'] for row in TURNS[:index + 1]]
            assert facts['user_text'] == turn['user']
            assert [row['value'] for row in facts['presented_effects']] == [
                row['reply'] for row in TURNS[:index]]
            assert facts['accepted_prefix'] == [] and facts['audio_progress'] == []
            assert 'memory_evidence' not in facts
            assert ('character_story' in facts) is story
            for invented in ('蓝湾桥', '小月糖'):
                assert invented not in json.dumps(prompt['author_policy'], ensure_ascii=False)
                if story:
                    assert invented not in json.dumps(facts['character_story'], ensure_ascii=False)
            assert state['sealed'] and state['last_error'] is None, (turn['id'], state['last_error'])
            assert len(state['active_grants']) == 1
            effect = state['active_grants'][0]
            assert effect['kind'] == 'subtitle' and effect['value'] == turn['reply']
            receipt = {key: effect[key] for key in ('digest', 'output_epoch', 'activity_seq')}
            receipt.update(effect_id=effect['id'], presentation_seq=index + 1)
            assert client.post(path + '/receipts', headers=headers, json=receipt).status_code == 200
            if characters:
                assert characters[0].runtime.story.node is initial_node
                assert not characters[0].runtime.story.pending
                assert not characters[0].runtime.story.episodes
                assert characters[0].runtime.story.relationship_delta == 0
        assert len(requests) == source.calls == len(TURNS)
        assert review.calls == []  # No JEV classifier is a prerequisite for plain text.
        assert all(stream.closed for stream in streams)
        assert client.delete(path, headers=headers).status_code in (200, 204)
    assert app.state.container.diagnostics.flush()
    assert not app.state.container.sessions._sessions
