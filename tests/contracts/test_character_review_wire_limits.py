"""Bounded configurable application envelopes; synthetic ports only."""
import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.adapters.review.jev import JevReviewBackend
from mira.adapters.review.jev_input import JevInputDecisionBackend
from mira.application.actor_story import SessionCharacterRuntime
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
from mira.application.story import StoryRuntime
from mira.bootstrap.character_story import builtin_definition
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.config.loader import ConfigurationError
from mira.domain.story import StoryNode
from tests.contracts.test_character_control_bridge import Generation, candidate, ready_catalog
from tests.contracts.test_direct_provider_app import arguments
from tests.contracts.test_direct_story_http import SemanticWire
from tests.contracts.test_development_app_entry import wait_ready


@pytest.mark.parametrize('backend', [JevInputDecisionBackend, JevReviewBackend])
@pytest.mark.parametrize('value', [True, 0, -1, 1023, 131073, 16384.0, float('inf'), float('nan'), '32768'])
def test_backend_envelope_rejects_invalid_configuration(backend, value):
    with pytest.raises(ValueError):
        backend(transport=SemanticWire(), model='jev-1.13.0', max_request_bytes=value)


@pytest.mark.parametrize('profile,character,expected', [
    ('probe', False, (16384, 32768)), ('probe', True, (16384, 32768)),
    ('application', False, (16384, 32768)), ('application', True, (32768, 65536)),
])
def test_factory_selects_explicit_bounded_character_application_envelopes(profile, character, expected):
    from mira.bootstrap.development_review import create_development_review_providers, resolve_review_request_limits
    providers = create_development_review_providers(generation=Generation(candidate()),
        input_transport=SemanticWire(), output_transport=SemanticWire(), authorized=True,
        decision_policy=USER_DEVELOPMENT_0_6_V2, usage_profile=profile,
        character_observations=character)
    assert resolve_review_request_limits(usage_profile=profile, character_observations=character) == expected
    assert providers.semantic_review._input_decision._max_request_bytes == expected[0]
    assert providers.review._max_request_bytes == expected[1]
    assert resolve_review_request_limits(usage_profile=profile, character_observations=character,
        input_max_request_bytes=4096, output_max_request_bytes=131072) == (4096, 131072)
    with pytest.raises(ConfigurationError):
        resolve_review_request_limits(usage_profile=profile, character_observations=character,
                                     output_max_request_bytes=True)


class MeasuredWire(SemanticWire):
    def __init__(self):
        super().__init__()
        self.input_sizes, self.output_sizes = [], []

    async def __call__(self, raw, **kwargs):
        request = json.loads(raw)
        sizes = self.output_sizes if 'contract' in request['state'] else self.input_sizes
        sizes.append(len(raw))
        return await super().__call__(raw, **kwargs)


@pytest.mark.parametrize('turns', [5, 10, 20])
def test_character_application_five_ten_twenty_turns_keep_full_semantic_review(turns):
    wire = MeasuredWire()
    runtime = StoryRuntime(builtin_definition(), 'synthetic-application-scope')
    character = SessionCharacterRuntime(runtime, ready_catalog())
    controls = ('outfit_cream_inner_only', 'accessory_star_clip', 'outfit_amber_raincoat', 'outfit_black_jacket')
    def output(context):
        index = len(context.user_inputs) - 1
        return candidate(controls[(index // 2) % len(controls)], 'emotion_normal') if index % 2 == 0 else candidate()
    generation = Generation(output)
    app = create_direct_provider_app(**arguments(generation=generation,
        input_transport=wire, output_transport=wire, usage_profile='application',
        character_factory=lambda _: character, generation_request_limit=turns,
        session_turn_limit=turns, input_request_limit=turns * 2, output_request_limit=turns * 2))
    with TestClient(app) as client:
        created = client.post('/api/v1/sessions', json={'client_instance_id': str(uuid4())}).json()
        path = '/api/v1/sessions/' + created['session']['session_id']
        headers = {'X-Mira-Session-Token': created['session_token']}
        seq = 0
        for index in range(turns):
            text = 'Please use ' + controls[(index // 2) % len(controls)] + '.' if index % 2 == 0 else 'Let us chat about the cafe.'
            assert client.post(path + '/inputs', headers=headers, json={
                'request_id': str(uuid4()), 'activity_seq': index + 1,
                'presentation_cutoff': seq, 'text': text}).status_code == 202
            state = wait_ready(client, path, headers)
            assert state['sealed'] and not state['last_error'], (index, state['last_error'], wire.input_sizes, wire.output_sizes)
            for effect in state['active_grants']:
                seq += 1
                receipt = {key: effect[key] for key in ('digest', 'output_epoch', 'activity_seq')}
                receipt.update(effect_id=effect['id'], presentation_seq=seq)
                response = client.post(path + '/receipts', headers=headers, json=receipt)
                assert response.status_code == 200, response.text
        assert len(wire.input_sizes) == len(wire.output_sizes) == (turns + 1) // 2
        assert max(wire.input_sizes) <= 32768
        assert max(wire.output_sizes) <= 65536
        assert runtime.story.node is StoryNode.CAFE_CHAT
        view = json.loads(runtime.project().projection.context_json)
        assert len(view['acknowledged_presentations']) <= 8
        assert len(runtime.story.episodes) == (turns + 1) // 2 * 2
        print('application-wire-bytes', turns, {'input_max': max(wire.input_sizes), 'output_max': max(wire.output_sizes)})


@pytest.mark.parametrize('track', ['input', 'output'])
def test_explicit_small_envelope_fails_closed_in_real_asgi_and_does_not_call_oversized_track(track):
    wire = MeasuredWire()
    character = SessionCharacterRuntime(StoryRuntime(builtin_definition(), 'synthetic-small-bound'), ready_catalog())
    kwargs = {track + '_max_request_bytes': 1024}
    app = create_direct_provider_app(**arguments(generation=Generation(candidate('emotion_normal')),
        input_transport=wire, output_transport=wire, usage_profile='application',
        character_factory=lambda _: character, **kwargs))
    with TestClient(app) as client:
        created = client.post('/api/v1/sessions', json={'client_instance_id': str(uuid4())}).json()
        path = '/api/v1/sessions/' + created['session']['session_id']
        headers = {'X-Mira-Session-Token': created['session_token']}
        assert client.post(path + '/inputs', headers=headers, json={
            'request_id': str(uuid4()), 'activity_seq': 1,
            'presentation_cutoff': 0, 'text': 'An ordinary fictional conversation.'}).status_code == 202
        state = wait_ready(client, path, headers)
        assert state['sealed'] and [item['kind'] for item in state['active_grants']] == ['subtitle']
        assert state['last_error'] is None
        assert not character.runtime.story.episodes
        assert not wire.output_sizes
        assert len(wire.input_sizes) == (0 if track == 'input' else 1)
