"""Speaker request and receipt contracts; authored replies are NOT live evaluation."""
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from mira.adapters.generation.codex_support.character_voice import CHARACTER_VOICE_REVISION
from mira.adapters.generation.codex_support.payload import author_instructions
from mira.adapters.generation.direct_codex_responses import (
    DirectCodexResponsesGenerationBackend, DirectResponsesLimits, ResponsesRoute,
)
from mira.bootstrap.character_story import ephemeral_character_factory, reenter_runtime
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.bootstrap.development_usage import UsageProfile
from tests.contracts.test_conversation_first import Wire, session, settled, submit
from tests.contracts.test_direct_codex_responses import (
    ByteStream, CredentialSource, completed, item_done,
)
from tests.contracts.test_direct_provider_app import arguments

FIXTURE = Path(__file__).parents[2] / 'specs/features/WP12-conversation-perspective/fixtures/conversation.json'
TURNS = json.loads(FIXTURE.read_text())['turns']
REVISION = 'mira-character-voice-v4'
PERSPECTIVE_RULES = (
    'Keep this perspective in off-plot chat as well as story scenes.',
    'Knowledge and interest shape depth, not permission to talk.',
    'Answer familiar elementary facts directly; do not perform ignorance.',
    'You may decline an unwanted long task or offer a smaller part',
    'Present-moment preferences need not become permanent character facts.',
    'Do not force photography or cafe metaphors, habitual hesitation sounds',
    'do not claim a real human body or physical contact with the user.',
)


def assert_speaker_request(instructions):
    # These are exact authoring-contract assertions, not a keyword score of replies.
    missing = [rule for rule in PERSPECTIVE_RULES if rule not in instructions]
    assert not missing, missing
    assert instructions.count(REVISION) == 1
    assert 'truthfully identify as an AI portraying the fictional character Mira' in instructions
    assert 'never invent shared user experiences' in instructions


@pytest.mark.parametrize('speech', [False, True])
@pytest.mark.parametrize('memory', [False, True])
@pytest.mark.parametrize('story', [False, True])
def test_speaker_perspective_is_fixed_on_every_existing_capability_path(speech, memory, story):
    instructions = author_instructions(speech_enabled=speech, memory_enabled=memory,
                                       character_story_enabled=story)
    assert_speaker_request(instructions)
    assert CHARACTER_VOICE_REVISION == REVISION
    assert ('explicitly text-only' in instructions) is (not speech)
    assert ('optional facts.memory_evidence' in instructions) is memory
    assert ('optional facts.character_story' in instructions) is story
    assert len(instructions.encode()) < 12_000


@pytest.mark.asyncio
@pytest.mark.parametrize('speech', [False, True])
async def test_native_adapter_serializes_perspective_and_preserves_authored_candidate(speech):
    from tests.contracts.test_codex_generation import (
        SyntheticTransport, agent, collect, event, make, terminal,
    )
    effects = [{'kind': 'subtitle', 'value': TURNS[2]['reply']}]
    if speech:
        effects.append({'kind': 'speech', 'value': TURNS[2]['reply']})
    transport = SyntheticTransport(events=[
        event('item/completed', item=agent(json.dumps({'effects': effects}, ensure_ascii=False))),
        terminal(),
    ])
    backend, _, factory = make(transport, speech_enabled=speech)
    from mira.application.contracts import GenerationContext
    context = GenerationContext(TURNS[2]['user'], (TURNS[2]['user'],), (), 1)
    result = await collect(backend, context)
    start = next(call['params'] for call in transport.sent if call['method'] == 'thread/start')
    turn = next(call['params'] for call in transport.sent if call['method'] == 'turn/start')
    assert_speaker_request(start['baseInstructions'])
    assert json.loads(turn['input'][0]['text'])['facts']['user_text'] == TURNS[2]['user']
    assert [{'kind': item.kind.value, 'value': item.value} for item in result[0].effects] == effects
    assert len(factory.calls) == 1 and transport.closed
    assert len([call for call in transport.sent if call['method'] == 'turn/start']) == 1


@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('story_mode', ['off', 'fresh', 'resumed'])
def test_authored_multiturn_through_real_adapter_asgi_retains_topic_and_receipt_context(
        tmp_path, monkeypatch, route, story_mode):
    from mira.adapters.diagnostics.recorder import LocalDiagnostics

    def diagnostics(options, **kwargs):
        return LocalDiagnostics(replace(options, root=tmp_path / Path(options.root)), **kwargs)
    monkeypatch.setattr('mira.bootstrap.container.LocalDiagnostics', diagnostics)
    async def forbid_subprocess(*_args, **_kwargs):
        raise AssertionError('Direct speaker path must not add native model calls')
    monkeypatch.setattr('asyncio.create_subprocess_exec', forbid_subprocess)
    requests, streams, characters = [], [], []
    source, review = CredentialSource(), Wire('reject')

    def inspect_request(request, index):
        body = json.loads(request.content)
        assert_speaker_request(body['instructions'])
        assert 'explicitly text-only' in body['instructions']
        assert body['store'] is False and 'tools' not in body
        assert len(request.content) < 65_536
        prompt = json.loads(body['input'][0]['content'][0]['text'])
        facts = prompt['facts']
        assert facts['user_inputs'] == [turn['user'] for turn in TURNS[:index + 1]]
        assert facts['user_text'] == TURNS[index]['user']
        assert [effect['value'] for effect in facts['presented_effects']] == [
            turn['reply'] for turn in TURNS[:index]]
        assert all(effect['kind'] == 'subtitle' for effect in facts['presented_effects'])
        assert facts['accepted_prefix'] == [] and facts['audio_progress'] == []
        assert 'memory_evidence' not in facts
        assert ('character_story' in facts) is (story_mode != 'off')
        # An asserted shared event stays attributed dialogue, never character canon.
        assert '柏林' not in json.dumps(prompt['author_policy'], ensure_ascii=False)
        if story_mode != 'off':
            memory = facts['character_story']['first_person_memory']
            assert memory['is_user_fact'] is False
            assert memory['qualified_shared_presentations'] == []
            assert memory['story_options']['completed'] is False
            assert all(not row['is_shared_experience']
                       for row in memory['autobiographical_fiction'])
            assert all(row['is_completed_event'] is False
                       for row in memory['current_intentions_and_concerns'])
            if story_mode == 'resumed':
                assert memory['arrival_frame']['mode'] == 'resumed_scene'
            dialogue = facts['first_person_dialogue']
            assert dialogue['user_statements_type'] == 'reliable_input_not_verified_user_fact'
            assert dialogue['physical_hearing_or_understanding_established'] is False
            for row in dialogue['presented_replies']:
                ref = row['quoted_text_reference']
                prior = int(ref.removeprefix('presented_effects[').removesuffix('].value'))
                assert facts['presented_effects'][prior]['value'] == TURNS[prior]['reply']

    async def handler(request):
        requests.append(request)
        index = len(requests) - 1
        raw = json.dumps({'effects': [{'kind': 'subtitle', 'value': TURNS[index]['reply']}]},
                         ensure_ascii=False)
        wire = item_done(raw) + completed(output=None)
        stream = ByteStream([wire[i:i + 7] for i in range(0, len(wire), 7)])
        streams.append(stream)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)

    factory = ephemeral_character_factory()
    def character_factory(state):
        character = factory(state)
        if story_mode == 'resumed':
            character.runtime = reenter_runtime(character.runtime)
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
        character_factory=character_factory if story_mode != 'off' else None))
    with TestClient(app) as client:
        path, headers = session(client)
        initial_node = characters[0].runtime.story.node if characters else None
        for index, turn in enumerate(TURNS):
            submit(client, path, headers, activity=index + 1, cutoff=index, text=turn['user'])
            state = settled(client, path, headers)
            assert len(requests) == index + 1
            inspect_request(requests[index], index)
            assert state['sealed'] and state['last_error'] is None, (turn['id'], state['last_error'])
            assert len(state['active_grants']) == 1
            effect = state['active_grants'][0]
            assert effect['kind'] == 'subtitle' and effect['value'] == turn['reply']
            receipt = {key: effect[key] for key in ('digest', 'output_epoch', 'activity_seq')}
            receipt.update(effect_id=effect['id'], presentation_seq=index + 1)
            result = client.post(path + '/receipts', headers=headers, json=receipt)
            assert result.status_code == 200, result.text
            if characters:
                assert characters[0].runtime.story.node is initial_node
                assert not characters[0].runtime.story.pending
                assert not characters[0].runtime.story.episodes
                assert characters[0].runtime.story.relationship_delta == 0
        assert len(requests) == source.calls == len(TURNS)
        assert review.calls == []  # No interest or eligibility classifier for ordinary text.
        assert all(stream.closed for stream in streams)
        assert client.delete(path, headers=headers).status_code in (200, 204)
    assert app.state.container.diagnostics.flush()
    assert not app.state.container.sessions._sessions
    assert DirectResponsesLimits().max_prompt_bytes == 65_536
