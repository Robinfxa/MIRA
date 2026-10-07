"""Fixed prompt, serialized requests and receipts; never live semantic scoring."""
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from mira.adapters.generation.codex_support.payload import author_instructions, parse_effects
from mira.adapters.generation.codex_support.types import CodexLimits
from mira.adapters.generation.direct_codex_responses import DirectCodexResponsesGenerationBackend, ResponsesRoute
from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.actor_story import SessionCharacterRuntime
from mira.application.contracts import CandidateRange, GenerationContext
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.application.story import StoryRuntime
from mira.bootstrap.character_story import builtin_definition, ephemeral_character_factory
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.domain.models import EffectKind, SessionState
from tests.contracts.test_actor_story_loop import acknowledge, turn
from tests.contracts.test_character_control_bridge import FullReview, ready_catalog
from tests.contracts.test_conversation_first import Wire, session, settled, submit
from tests.contracts.test_direct_codex_responses import CredentialSource, backend, completed, item_done, response, snapshot_message
from tests.contracts.test_direct_luna_tools import definitions, wire
from tests.contracts.test_direct_provider_app import arguments

FIXTURE = Path(__file__).parents[2] / 'specs/features/WP12-ordinary-scene/fixtures/conversation.json'
TURNS = json.loads(FIXTURE.read_text())['turns']
RULES = (
    'Ordinary scene dialogue: mira-ordinary-scene-v1.',
    'Default everyday location, reasons, invitations, weather and clothing to the current scene.',
    'Do not ask users to choose role versus reality for ordinary scene dialogue.',
    'Source/provenance labels are internal grounding metadata, not spoken qualifications.',
    'AI/model/program identity, real humanity, physical-world presence/contact or actual provenance',
    'Generic intensifiers, figurative speech and question prefixes alone do not switch frames.',
    'A clear short acceptance of your presented outfit suggestion requests that change now;',
    'Mention a relevant clothing detail once; do not echo it on unrelated turns.',
)


def assert_policy(instructions):
    for rule in RULES:
        assert instructions.count(rule) == 1
    assert 'truthfully identify as an AI portraying the fictional character Mira' in instructions
    assert 'never invent shared user experiences' in instructions
    assert 'first-person narration never proves completed application actions' in instructions
    assert len(instructions.encode()) < 12_000
    for case in TURNS:
        assert case['user'] not in instructions
        assert case['reply'] not in instructions
        assert case['contrast'] not in instructions


@pytest.mark.parametrize('speech', [False, True])
@pytest.mark.parametrize('memory', [False, True])
@pytest.mark.parametrize('story', [False, True])
def test_fixed_scene_frame_contract_preserves_honesty_and_instruction_budget(speech, memory, story):
    assert_policy(author_instructions(speech_enabled=speech, memory_enabled=memory,
                                     character_story_enabled=story))


@pytest.mark.parametrize('case', TURNS, ids=lambda case: case['id'])
def test_editorial_pairs_are_not_mistaken_for_a_semantic_oracle(case):
    assert case['frame'] in {'scene', 'reality', 'provenance'}
    assert case['reply'] != case['contrast']
    for text in (case['reply'], case['contrast']):
        parsed = parse_effects([json.dumps({'effects': [{'kind': 'subtitle', 'value': text}]})],
                               CodexLimits(), speech_enabled=False)
        assert parsed[0].value == text


@pytest.mark.parametrize('route', list(ResponsesRoute))
def test_authored_scene_reality_sequence_crosses_actual_asgi_without_jev_text_gate(tmp_path, monkeypatch, route):
    from mira.adapters.diagnostics.recorder import LocalDiagnostics
    def diagnostics(options, **kwargs):
        return LocalDiagnostics(replace(options, root=tmp_path / Path(options.root)), **kwargs)
    monkeypatch.setattr('mira.bootstrap.container.LocalDiagnostics', diagnostics)
    requests, source, review = [], CredentialSource(), Wire('reject')
    async def handler(request):
        requests.append(json.loads(request.content))
        case = TURNS[len(requests) - 1]
        raw = json.dumps({'effects': [{'kind': 'subtitle', 'value': case['reply']}]}, ensure_ascii=False)
        return response(item_done(raw) + completed(output=None))
    generation = DirectCodexResponsesGenerationBackend(route, 'synthetic-model', source,
        admitted=True, request_limit=len(TURNS), speech_enabled=False, transport=httpx.MockTransport(handler))
    app = create_direct_provider_app(**arguments(route=route.value,
        api_billing_authorized=route is ResponsesRoute.OPENAI_API,
        generation=generation, input_transport=review, output_transport=review,
        generation_request_limit=len(TURNS), session_turn_limit=len(TURNS), usage_profile='application',
        character_factory=ephemeral_character_factory()))
    with TestClient(app) as client:
        path, headers = session(client)
        for index, case in enumerate(TURNS):
            submit(client, path, headers, activity=index + 1, cutoff=index, text=case['user'])
            state = settled(client, path, headers)
            assert state['sealed'] and state['last_error'] is None
            body = requests[index]
            assert_policy(body['instructions'])
            prompt = json.loads(body['input'][0]['content'][0]['text'])
            facts = prompt['facts']
            assert facts['user_inputs'] == [row['user'] for row in TURNS[:index + 1]]
            assert [row['value'] for row in facts['presented_effects']] == [row['reply'] for row in TURNS[:index]]
            assert facts['accepted_prefix'] == []
            memory = facts['character_story']['first_person_memory']
            assert memory['is_user_fact'] is False
            assert all(not row['is_shared_experience'] for row in memory['autobiographical_fiction'])
            assert facts['first_person_dialogue']['physical_hearing_or_understanding_established'] is False
            # The compact stranger projection omits chapter until it has state.
            assert facts['character_story'].get('chapter', {}).get('role_active', False) is False
            assert body['store'] is False and 'tools' not in body
            assert len(state['active_grants']) == 1
            effect = state['active_grants'][0]
            assert effect['kind'] == 'subtitle' and effect['value'] == case['reply']
            receipt = {key: effect[key] for key in ('digest', 'output_epoch', 'activity_seq')}
            receipt.update(effect_id=effect['id'], presentation_seq=index + 1)
            assert client.post(path + '/receipts', headers=headers, json=receipt).status_code == 200
        assert len(requests) == source.calls == len(TURNS) and review.calls == []
        assert client.delete(path, headers=headers).status_code in (200, 204)
    assert app.state.container.diagnostics.flush()
    (tmp_path / 'serialized-requests.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2))


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('case', TURNS, ids=lambda case: case['id'])
async def test_actual_tool_request_keeps_the_same_semantic_frame_contract(case, route, tmp_path):
    async def handle(request):
        return response(wire([snapshot_message(json.dumps({'effects': [
            {'kind': 'subtitle', 'value': case['reply']}]}))]))
    direct, source, requests = backend(handle, native_character_tools=False, route=route, request_limit=2)
    context = GenerationContext(case['user'], (case['user'],), (), 1,
        character_story=StoryRuntime(builtin_definition(), 'synthetic-scene').project().projection,
        character_assets=ready_catalog())
    tool_turn = direct.open_tool_turn(context, definitions()[:1])
    try:
        candidate = await tool_turn.start()
        assert type(candidate) is CandidateRange
    finally:
        tool_turn.close()
    body = json.loads(requests[0].content)
    assert_policy(body['instructions'])
    prompt = json.loads(body['input'][0]['content'][0]['text'])
    assert prompt['facts']['user_text'] == case['user']
    assert prompt['facts']['presented_effects'] == []
    assert [tool['name'] for tool in body['tools']] == ['show_photo']
    assert body['text']['format']['strict'] is True and body['store'] is False
    assert len(requests) == source.calls == 1
    (tmp_path / 'serialized-request.json').write_text(json.dumps(body, ensure_ascii=False, indent=2))


@pytest.mark.asyncio
@pytest.mark.parametrize('case', [TURNS[0], TURNS[10]], ids=lambda case: case['id'])
async def test_native_speaker_receives_same_frame_with_no_extra_request(case):
    from tests.contracts.test_codex_generation import SyntheticTransport, agent, collect, event, make, terminal
    raw = json.dumps({'effects': [{'kind': 'subtitle', 'value': case['reply']}]})
    transport = SyntheticTransport(events=[event('item/completed', item=agent(raw)), terminal()])
    generation, _, factory = make(transport, speech_enabled=False)
    context = GenerationContext(case['user'], (case['user'],), (), 1)
    assert len(await collect(generation, context)) == 1
    start = next(call['params'] for call in transport.sent if call['method'] == 'thread/start')
    assert_policy(start['baseInstructions'])
    assert len([call for call in transport.sent if call['method'] == 'turn/start']) == 1
    assert len(factory.calls) == 1 and transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['presented', 'pending', 'unavailable', 'no_proposal'])
async def test_short_acceptance_resolves_presented_outfit_suggestion_and_requires_exact_receipt(boundary, tmp_path):
    scripts = [
        ('先保持原来的外套。', '好，先这样。', 'outfit_black_jacket'),
        ('一会儿想看看外面的雨。', '要出去的话，我可以先加件雨衣。', None),
        ('那就换上吧。', '好，我先换上雨衣。', None if boundary == 'no_proposal' else 'outfit_amber_raincoat'),
        ('现在穿好了没有？', '换好了。' if boundary == 'presented' else '还没有确认换好。', None),
    ]
    bodies = []
    async def handler(request):
        bodies.append(json.loads(request.content))
        _, reply, control = scripts[len(bodies) - 1]
        effects = [{'kind': 'subtitle', 'value': reply}]
        if control:
            effects.append({'kind': 'pose', 'value': control})
        return response(wire([snapshot_message(json.dumps({'effects': effects}, ensure_ascii=False))]))
    direct, credentials, requests = backend(handler, native_character_tools=False, request_limit=4)
    class Generation:
        async def generate(self, context):
            current = direct.open_tool_turn(context, definitions()[:1])
            try:
                yield await current.start()
            finally:
                current.close()
    catalog = ready_catalog(unavailable=('outfit_amber_raincoat',) if boundary == 'unavailable' else ())
    character = SessionCharacterRuntime(StoryRuntime(builtin_definition(), 'synthetic-outfit'), catalog)
    review = FullReview()
    actor = SessionActor(SessionState(str(uuid4()), str(uuid4())), Generation(), review,
        MemoryEventJournal(100), RuntimeLimits(3, 10, 40), character_runtime=character)
    history, sequence = [], 0
    try:
        for index, (user, reply, control) in enumerate(scripts):
            state = await turn(actor, user, index + 1, sequence)
            assert state.sealed and state.last_error is None
            body = bodies[index]
            assert_policy(body['instructions'])
            facts = json.loads(body['input'][0]['content'][0]['text'])['facts']
            assert facts['user_inputs'] == [row[0] for row in scripts[:index + 1]]
            assert [(row['kind'], row['value']) for row in facts['presented_effects']] == history
            if index >= 2:
                assert ('subtitle', scripts[1][1]) in history
                expected = 'amber_raincoat' if index == 3 and boundary == 'presented' else 'black_jacket'
                assert facts['character_story']['last_acknowledged_appearance']['outfit'] == expected
            poses = [effect.value for effect in state.active_grants if effect.kind is EffectKind.POSE]
            expected_pose = control if not (index == 2 and boundary == 'unavailable') else None
            assert poses == ([expected_pose] if expected_pose else [])
            for effect in state.active_grants:
                if index == 2 and effect.kind is EffectKind.POSE and boundary == 'pending':
                    continue
                sequence += 1
                await acknowledge(actor, effect, sequence)
                history.append((effect.kind.value, effect.value))
        assert len(bodies) == len(requests) == credentials.calls == 4
        assert character.runtime.story.current_outfit == ('amber_raincoat' if boundary == 'presented' else 'black_jacket')
        assert all(candidate.story_proposal_json is None for _, candidate in review.calls)
        (tmp_path / 'serialized-requests.json').write_text(json.dumps(bodies, ensure_ascii=False, indent=2))
        (tmp_path / 'receipted-effects.json').write_text(json.dumps(history, ensure_ascii=False, indent=2))
    finally:
        await actor.close()
