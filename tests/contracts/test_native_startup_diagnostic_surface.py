"""Synthetic startup failure crosses the real app/recorder boundary without stderr."""
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.adapters.generation.codex_support.types import CodexGenerationError
from mira.bootstrap.development_app import create_development_app
from mira.config.settings import Settings
from tests.contracts.test_development_app_entry import public_runtime
from tests.contracts.test_jev_response_diagnostics import _new_session, _await_state, _read_events, _hashed


@pytest.mark.parametrize(('reason','wire_code','diagnostic_code'),[
    ('codex_startup_readonly_filesystem','codex_startup_readonly_filesystem','codex_startup_readonly_filesystem'),
    ('codex_transport_eof','generation_failed','unavailable'),
])
def test_native_startup_failure_has_safe_correlated_actionable_surface(tmp_path,monkeypatch,reason,wire_code,diagnostic_code):
    monkeypatch.chdir(tmp_path)
    async def failed_factory(_runtime,_limits):
        raise CodexGenerationError(reason)
    async def no_review(*_args,**_kwargs):
        raise AssertionError('review must not start before generation succeeds')
    app=create_development_app(runtime=public_runtime(),settings=Settings(),route_kind='public',authorized=True,
        input_transport=no_review,output_transport=no_review,codex_transport_factory=failed_factory)
    with TestClient(app) as client:
        path,headers=_new_session(client)
        response=client.post(path+'/inputs',headers=headers,json={'request_id':str(uuid4()),'activity_seq':1,
            'presentation_cutoff':0,'text':'SYNTHETIC_PRIVATE_NATIVE_STARTUP_INPUT'})
        assert response.status_code==202
        state=_await_state(client,path,headers,lambda s:s['phase']=='error')
        assert state['last_error']==wire_code
        assert state['active_grants']==[]
        assert state['last_error_diagnostic_id']==_hashed(response.headers['x-request-id'])
        sink=app.state.container.diagnostics;assert sink.flush()
        events=_read_events(tmp_path/'var/diagnostics')
        assert any(e['stage']=='generation' and e.get('code')==diagnostic_code for e in events)
        assert 'SYNTHETIC_PRIVATE_NATIVE_STARTUP_INPUT' not in json.dumps(events)
