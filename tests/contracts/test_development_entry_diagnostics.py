"""The actual text entry retains sanitized diagnostics and never pre-arms raw capture."""
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.adapters.diagnostics.recorder import LocalDiagnostics, NullDiagnostics
from mira.bootstrap.development_app import create_development_app
from mira.config.settings import Settings
from tests.contracts.test_codex_generation import SyntheticTransport, agent, event, terminal
from tests.contracts.test_development_app_entry import public_runtime
from tests.contracts.test_jev_response_diagnostics import (
    V2InputTransport, AsgiOutputTransport, _new_session, _await_state, _read_events, _hashed,
    PRIVATE_MARKER,
)


def entry(settings, *, outcome='invalid'):
    output = {'effects': [{'kind': 'subtitle', 'value': 'SYNTHETIC_PRIVATE_OUTPUT_9532'}]}
    transport = SyntheticTransport(events=[
        event('item/completed', item=agent(json.dumps(output))), terminal(),
    ])
    async def codex_factory(_runtime, _limits):
        return transport
    return create_development_app(
        runtime=public_runtime(), settings=settings, route_kind='public', authorized=True,
        input_transport=V2InputTransport(), output_transport=AsgiOutputTransport(outcome=outcome),
        codex_transport_factory=codex_factory,
    )


@pytest.mark.parametrize(('outcome', 'expected'), [
    ('invalid', 'invalid_response'), ('reject', 'review_not_allowed'),
    ('unknown', 'review_uncertain'),
])
def test_text_entry_persists_safe_correlated_review_diagnostics(tmp_path, monkeypatch, outcome, expected):
    monkeypatch.chdir(tmp_path)
    app = entry(Settings(), outcome=outcome)
    with TestClient(app) as client:
        sink = app.state.container.diagnostics
        assert isinstance(sink, LocalDiagnostics)
        path, headers = _new_session(client)
        response = client.post(path + '/inputs', headers=headers, json={
            'request_id': str(uuid4()), 'activity_seq': 1, 'presentation_cutoff': 0,
            'text': 'SYNTHETIC_PRIVATE_INPUT_9532',
        })
        assert response.status_code == 202
        state = _await_state(client, path, headers, lambda s: s['phase'] == 'error')
        assert state['last_error'] == expected
        assert state['active_grants'] == []
        assert state['last_error_diagnostic_id'] == _hashed(response.headers['x-request-id'])
        assert sink.flush()
        records = _read_events(tmp_path / 'var/diagnostics')
        reviews = [r for r in records if r['stage'] == 'output_review']
        assert reviews
        assert any(r['context']['request_id'] == state['last_error_diagnostic_id'] for r in reviews)
        if outcome == 'invalid':
            assert any(r.get('response_validation', {}).get('parser_reason') == 'probabilities'
                       for r in reviews)
        encoded = json.dumps(records)
        for secret in (PRIVATE_MARKER, 'SYNTHETIC_PRIVATE_INPUT_9532', 'SYNTHETIC_PRIVATE_OUTPUT_9532'):
            assert secret not in encoded
        assert sink.status().recording_active is False


def test_text_entry_preserves_explicit_disabled_logging(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    settings = settings.model_copy(update={'diagnostics': settings.diagnostics.model_copy(update={'enabled': False})})
    with TestClient(entry(settings)) as client:
        assert isinstance(client.app.state.container.diagnostics, NullDiagnostics)
    assert not (tmp_path / 'var/diagnostics').exists()


def test_text_entry_never_enables_raw_recording_from_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    settings = settings.model_copy(update={'diagnostics': settings.diagnostics.model_copy(update={
        'development_recording': True, 'recording_consent': True,
    })})
    with TestClient(entry(settings)) as client:
        sink = client.app.state.container.diagnostics
        assert isinstance(sink, LocalDiagnostics)
        assert sink.status().recording_active is False
        assert client.app.state.container.settings.diagnostics.recording_consent is False
