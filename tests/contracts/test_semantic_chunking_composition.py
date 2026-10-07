"""Public direct-entry configuration and actual ASGI consumer; synthetic only."""
import json

import pytest
from fastapi.testclient import TestClient

from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.config.loader import ConfigurationError
from tests.contracts.test_direct_provider_app import arguments
from tests.contracts.test_conversation_first import session, submit, settled
from tests.contracts.test_jev_chunking import Wire
from tests.contracts.test_semantic_chunking import Source, TEXT
from tests.contracts.test_live_provider_launcher import env, arguments as cli_arguments
from tools import live_provider as cli


def test_direct_factory_enables_real_chunk_consumer_with_one_bounded_output_transport_call():
    wire = Wire()
    app = create_direct_provider_app(**arguments(generation=Source(), output_transport=wire,
        boundary_request_limit=1))
    with TestClient(app) as client:
        path, headers = session(client); submit(client, path, headers)
        state = settled(client, path, headers)
        assert state['sealed'] and state['last_error'] is None
        assert len(state['active_grants']) == 4 and len(wire.calls) == 1
        assert ''.join(e['value'] for e in state['active_grants']) == TEXT
        assert [e['caption_chunk']['index'] for e in state['active_grants']] == [0, 1, 2, 3]
    assert app.state.usage_declaration.boundary_jev_requests == 1


def test_direct_factory_default_zero_preserves_whole_cue_without_boundary_dispatch():
    wire = Wire()
    app = create_direct_provider_app(**arguments(generation=Source(), output_transport=wire))
    with TestClient(app) as client:
        path, headers = session(client); submit(client, path, headers)
        state = settled(client, path, headers)
        assert [e['value'] for e in state['active_grants']] == [TEXT] and wire.calls == []
    assert app.state.usage_declaration.boundary_jev_requests == 0


@pytest.mark.parametrize('changes', [
    {'boundary_request_limit': -1}, {'boundary_request_limit': True},
    {'boundary_request_limit': 9}, {'boundary_request_limit': float('inf')},
    {'boundary_timeout_seconds': 0}, {'boundary_timeout_seconds': 2.01},
    {'boundary_timeout_seconds': float('nan')}, {'boundary_timeout_seconds': True},
])
def test_invalid_boundary_allowance_or_deadline_is_rejected_before_dispatch(changes):
    with pytest.raises(ConfigurationError): create_direct_provider_app(**arguments(**changes))


@pytest.mark.parametrize('allowance', [0, 3])
def test_check_declares_separate_finite_boundary_and_total_jev_allowances(tmp_path, capsys, allowance):
    assert cli.main(cli_arguments(env(tmp_path)) + ['--action-review-mode', 'legacy_jev'] + ['--boundary-max-requests', str(allowance)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['semantic_chunking']['boundary_max_requests'] == allowance
    assert result['semantic_chunking']['eligible_content'] == 'text_only_complete_candidates'
    assert result['semantic_chunking']['google_request_increase'] == 0
    assert result['review_request_limits']['total_max_requests'] == 80 + allowance
    assert result['inference'] == 'not_run' and result['live_ready'] is False


@pytest.mark.parametrize('options', [
    ['--boundary-max-requests', '-1'], ['--boundary-max-requests', '101'],
    ['--boundary-timeout-seconds', 'nan'], ['--boundary-timeout-seconds', 'inf'],
    ['--boundary-timeout-seconds', '0'], ['--boundary-timeout-seconds', '2.01'],
])
def test_check_rejects_invalid_boundary_configuration(tmp_path, capsys, options):
    assert cli.main(cli_arguments(env(tmp_path)) + ['--action-review-mode', 'legacy_jev'] + options) == 2
    assert json.loads(capsys.readouterr().err)['status'] == 'blocked'


def test_enabled_boundary_configuration_still_keeps_voice_candidate_whole():
    from tests.contracts.test_conversation_first import Wire as InputWire, voice_options
    boundary, permissions = Wire(), InputWire()
    app = create_direct_provider_app(**arguments(generation=Source(speech=True),
        output_transport=boundary, input_transport=permissions, boundary_request_limit=1, **voice_options()))
    with TestClient(app) as client:
        path, headers = session(client); submit(client, path, headers)
        state = settled(client, path, headers)
        assert [e['kind'] for e in state['active_grants']] == ['subtitle', 'speech']
        assert state['active_grants'][0]['value'] == TEXT and boundary.calls == []
        assert all(e['caption_chunk'] is None for e in state['active_grants'])


def test_boundary_budget_exhaustion_retains_text_across_two_actual_turns():
    wire = Wire()
    app = create_direct_provider_app(**arguments(generation=Source(), output_transport=wire,
        generation_request_limit=2, session_turn_limit=2, boundary_request_limit=1))
    with TestClient(app) as client:
        path, headers = session(client); submit(client, path, headers)
        first = settled(client, path, headers)
        assert len(first['active_grants']) == 4
        submit(client, path, headers, activity=2, text='第二轮')
        second = settled(client, path, headers)
        assert len(second['active_grants']) == 2
        assert ''.join(e['value'] for e in second['active_grants']) == TEXT
        assert len(wire.calls) == 1
