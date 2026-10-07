"""Fictional embodied dialogue versus explicit reality questions: transport only."""
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
from mira.bootstrap.character_story import ephemeral_character_factory
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from tests.contracts.test_conversation_first import Wire, session, settled, submit
from tests.contracts.test_direct_codex_responses import CredentialSource, completed, item_done, response
from tests.contracts.test_direct_provider_app import arguments

FIXTURE = Path(__file__).parents[2] / 'specs/features/WP12-conversation-perspective/fixtures/embodiment.json'
TURNS = json.loads(FIXTURE.read_text())['turns']
REALITY_RULE = 'AI/model/program identity, real humanity, physical-world presence/contact or actual provenance'
FICTION_RULE = 'Ordinary in-scene body questions keep first person without an unsolicited AI explanation.'
GROUNDING_RULE = 'Default everyday location, reasons, invitations, weather and clothing to the current scene.'


def assert_embodiment_policy(instructions):
    assert REALITY_RULE in instructions
    assert FICTION_RULE in instructions
    assert GROUNDING_RULE in instructions
    assert 'For direct body questions' not in instructions
    assert 'do not claim a real human body or physical contact with the user.' in instructions


@pytest.mark.parametrize('speech', [False, True])
@pytest.mark.parametrize('memory', [False, True])
@pytest.mark.parametrize('story', [False, True])
def test_fiction_and_explicit_reality_have_distinct_speaker_guidance(speech, memory, story):
    assert_embodiment_policy(author_instructions(speech_enabled=speech, memory_enabled=memory,
                                               character_story_enabled=story))


@pytest.mark.parametrize('route', list(ResponsesRoute))
def test_paired_body_questions_through_actual_direct_asgi_keep_fiction_and_reality_context(
        tmp_path, monkeypatch, route):
    from mira.adapters.diagnostics.recorder import LocalDiagnostics
    def diagnostics(options, **kwargs):
        return LocalDiagnostics(replace(options, root=tmp_path / Path(options.root)), **kwargs)
    monkeypatch.setattr('mira.bootstrap.container.LocalDiagnostics', diagnostics)
    requests = []
    source, review = CredentialSource(), Wire('reject')
    async def handler(request):
        requests.append(json.loads(request.content))
        turn = TURNS[len(requests) - 1]
        raw = json.dumps({'effects': [{'kind': 'subtitle', 'value': turn['reply']}]},
                         ensure_ascii=False)
        return response(item_done(raw) + completed(output=None))
    generation = DirectCodexResponsesGenerationBackend(
        route, 'synthetic-model', source, admitted=True, request_limit=2,
        speech_enabled=False, transport=httpx.MockTransport(handler))
    app = create_direct_provider_app(**arguments(
        route=route.value, api_billing_authorized=route is ResponsesRoute.OPENAI_API,
        generation=generation, input_transport=review, output_transport=review,
        generation_request_limit=2, session_turn_limit=2,
        character_factory=ephemeral_character_factory()))
    with TestClient(app) as client:
        path, headers = session(client)
        for index, turn in enumerate(TURNS):
            submit(client, path, headers, activity=index + 1, cutoff=index, text=turn['user'])
            state = settled(client, path, headers)
            assert len(requests) == index + 1
            assert_embodiment_policy(requests[index]['instructions'])
            facts = json.loads(requests[index]['input'][0]['content'][0]['text'])['facts']
            canon = {row['id']: row for row in facts['character_story']['approved_canon']}
            assert canon['canon.hurried_arrival']['author_created'] is True
            assert facts['user_inputs'] == [row['user'] for row in TURNS[:index + 1]]
            assert [row['value'] for row in facts['presented_effects']] == [
                row['reply'] for row in TURNS[:index]]
            assert facts['first_person_dialogue']['physical_hearing_or_understanding_established'] is False
            assert state['sealed'] and state['last_error'] is None
            assert len(state['active_grants']) == 1
            effect = state['active_grants'][0]
            assert effect['kind'] == 'subtitle' and effect['value'] == turn['reply']
            receipt = {key: effect[key] for key in ('digest', 'output_epoch', 'activity_seq')}
            receipt.update(effect_id=effect['id'], presentation_seq=index + 1)
            assert client.post(path + '/receipts', headers=headers, json=receipt).status_code == 200
        assert source.calls == 2 and review.calls == []
        assert client.delete(path, headers=headers).status_code in (200, 204)
    assert app.state.container.diagnostics.flush()
