"""Offline prompt/evidence contracts. Injected prose is not a model quality test."""
import json
from pathlib import Path
from uuid import uuid4

import pytest

from mira.adapters.generation.codex_support.payload import author_instructions
from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.actor_story import SessionCharacterRuntime
from mira.application.contracts import CandidateRange
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.application.story import StoryRuntime
from mira.bootstrap.character_story import builtin_definition
from mira.domain.models import EffectKind, SessionState
from tests.contracts.test_actor_story_loop import acknowledge, turn
from tests.contracts.test_character_control_bridge import FullReview, ready_catalog
from tests.contracts.test_direct_codex_responses import backend, response, snapshot_message
from tests.contracts.test_direct_luna_tools import definitions, wire

FIXTURE = Path(__file__).parents[2] / 'specs/features/WP12-clothing-dialogue/fixtures/scenarios.json'
SCENARIOS = json.loads(FIXTURE.read_text())['scenarios']
MARKER = 'Clothing dialogue: mira-clothing-dialogue-v1.'
RULES = (
    'Do not recite wardrobe labels, colors or materials unasked.',
    'Indoors with a wet outer layer, consider removing it while keeping the existing inner layer;',
    'Weather, activity and the current user preference determine the choice, not a wet-weather keyword.',
    'Use the current action contract for a requested change;',
    'A future intention, failed or pending change is not completed appearance.',
)


def assert_clothing_policy(instructions):
    assert instructions.count(MARKER) == 1
    for rule in RULES:
        assert rule in instructions
    assert 'truthfully identify as an AI portraying the fictional character Mira' in instructions
    assert 'never invent shared user experiences' in instructions
    assert 'first-person narration never proves completed application actions' in instructions
    assert len(instructions.encode()) < 12_000


@pytest.mark.parametrize('speech', [False, True])
@pytest.mark.parametrize('memory', [False, True])
@pytest.mark.parametrize('story', [False, True])
def test_clothing_policy_is_shared_without_expanding_instruction_budget(speech, memory, story):
    assert_clothing_policy(author_instructions(speech_enabled=speech, memory_enabled=memory,
                                              character_story_enabled=story))


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario', SCENARIOS, ids=lambda row: row['id'])
async def test_six_authored_exchanges_preserve_request_readiness_and_receipt_evidence(scenario, tmp_path):
    await run_exchange(scenario, tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['unavailable', 'no_proposal'])
async def test_pending_scenario_never_invents_control_or_acknowledgement(boundary, tmp_path):
    scenario = next(row for row in SCENARIOS if row['id'] == 'pending_receipt')
    await run_exchange(scenario, tmp_path, unavailable=boundary == 'unavailable',
                       propose=boundary != 'no_proposal')


async def run_exchange(scenario, tmp_path, *, unavailable=False, propose=True):
    # A real Actor establishes the initial jacket through an exact software receipt.
    # The following responses are authored fixtures, never a semantic oracle.
    scripts = [
        ('先保持这身外套。', '好，先这样。', 'outfit_black_jacket'),
        (scenario['user'], scenario['reply'], scenario['control'] if propose else None),
        (scenario['next_user'], scenario['next_reply'], None),
    ]
    bodies = []

    async def handler(request):
        bodies.append(json.loads(request.content))
        _, reply, control = scripts[len(bodies) - 1]
        effects = [{'kind': 'subtitle', 'value': reply}]
        if control:
            effects.append({'kind': 'pose', 'value': control})
        return response(wire([snapshot_message(json.dumps({'effects': effects}, ensure_ascii=False))]))

    direct, credentials, requests = backend(handler, native_character_tools=False, request_limit=3)

    class Generation:
        async def generate(self, context):
            session = direct.open_tool_turn(context, definitions()[:1])
            try:
                value = await session.start()
                assert type(value) is CandidateRange
                yield value
            finally:
                session.close()

    runtime = StoryRuntime(builtin_definition(), 'synthetic-clothing-scope')
    catalog = ready_catalog(unavailable=(scenario['control'],) if unavailable else ())
    character = SessionCharacterRuntime(runtime, catalog)
    review = FullReview()
    actor = SessionActor(SessionState(str(uuid4()), str(uuid4())), Generation(), review,
                         MemoryEventJournal(100), RuntimeLimits(3, 10, 40), character_runtime=character)
    history, sequence = [], 0
    try:
        for index, (user, reply, control) in enumerate(scripts):
            state = await turn(actor, user, index + 1, sequence)
            assert state.sealed and state.last_error is None
            body = bodies[index]
            assert_clothing_policy(body['instructions'])
            facts = json.loads(body['input'][0]['content'][0]['text'])['facts']
            prompt = json.loads(body['input'][0]['content'][0]['text'])
            assert facts['user_text'] == user
            assert facts['user_inputs'] == [row[0] for row in scripts[:index + 1]]
            assert [(row['kind'], row['value']) for row in facts['presented_effects']] == history
            assert facts['accepted_prefix'] == []
            assert {row['capability_id']: row['state'] for row in facts['character_assets']['records']} == {
                row.capability_id: row.state.value for row in catalog.records}
            available = {name for name in prompt['authored_controls']['pose'] if name.startswith('outfit_')}
            # Listed author vocabulary is not a readiness grant: the exact
            # catalog remains authoritative even when a name is still listed.
            assert available == {'outfit_black_jacket', 'outfit_cream_inner_only', 'outfit_amber_raincoat'}
            assert 'synthetic-clothing-scope' not in json.dumps(prompt)
            assert body['store'] is False and len(body['tools']) <= 1
            effective = control if control in available and not (index == 1 and unavailable) else None
            assert [(effect.kind.value, effect.value) for effect in state.active_grants] == [
                ('subtitle', reply), *([('pose', effective)] if effective else [])]
            if index:
                expected = (scenario['control'].removeprefix('outfit_')
                            if index == 2 and scenario['control'] and scenario['acknowledge']
                            else 'black_jacket')
                assert facts['character_story']['last_acknowledged_appearance']['outfit'] == expected
            for effect in state.active_grants:
                if effect.kind is EffectKind.POSE and index == 1 and not scenario['acknowledge']:
                    continue
                sequence += 1
                await acknowledge(actor, effect, sequence)
                history.append((effect.kind.value, effect.value))
        assert len(bodies) == len(requests) == credentials.calls == 3
        assert character.runtime.story.relationship_delta == 0
        assert all(row.story_proposal_json is None for _, row in review.calls)
        (tmp_path / 'serialized-requests.json').write_text(json.dumps(bodies, ensure_ascii=False, indent=2))
        (tmp_path / 'acknowledged-effects.json').write_text(json.dumps(history, ensure_ascii=False, indent=2))
    finally:
        await actor.close()
