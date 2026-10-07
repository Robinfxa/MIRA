"""Local review size/count bounds must not masquerade as semantic uncertainty."""
import json
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from mira.adapters.diagnostics.recorder import DiagnosticOptions,LocalDiagnostics
from mira.adapters.review import jev,jev_input
from mira.application.decision_contracts import INPUT_QUESTION_SET_V2,mira26_author_policy
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V1
from mira.application.decision_runtime import DecisionSnapshotOwner,SemanticReviewCoordinator
from mira.bootstrap.providers import Providers
from mira.config.settings import Settings
from mira.entrypoints.http.app import create_app
from tests.contracts.test_jev_transport_diagnostics import FixedGeneration,V2InputTransport,_new_session,_await_state,_read_events

@pytest.mark.parametrize('track',['input','output'])
@pytest.mark.parametrize('bound',['size','count'])
def test_review_resource_error_is_local_safe_and_not_semantic(tmp_path,track,bound):
    incoming=V2InputTransport(); outgoing=[]
    async def forbidden_output(*_a,**_k):outgoing.append(True);raise AssertionError('local bound must prevent output dispatch')
    input_backend=jev_input.JevInputDecisionBackend(transport=incoming,model='jev-1.13.0',
        decision_policy=USER_DEVELOPMENT_0_6_V1,question_set_revision=INPUT_QUESTION_SET_V2,
        request_limit=0 if track=='input' and bound=='count' else 1,timeout_seconds=1,
        max_request_bytes=1024 if track=='input' and bound=='size' else jev_input.MAX_REQUEST_BYTES)
    output_backend=jev.JevReviewBackend(transport=forbidden_output,model='jev-1.13.0',
        decision_policy=USER_DEVELOPMENT_0_6_V1,request_limit=0 if track=='output' and bound=='count' else 1,timeout_seconds=1,
        max_request_bytes=1024 if track=='output' and bound=='size' else jev.MAX_REQUEST_BYTES)
    providers=Providers(FixedGeneration(),output_backend,
        semantic_review=SemanticReviewCoordinator(input_backend,output_backend),
        decision_owner=DecisionSnapshotOwner(mira26_author_policy()))
    sink=LocalDiagnostics(DiagnosticOptions(tmp_path),worker=False)
    try:
        with TestClient(create_app(Settings(),providers=providers,diagnostics=sink)) as client:
            path,headers=_new_session(client)
            assert client.post(path+'/inputs',headers=headers,json={'request_id':str(uuid4()),'activity_seq':1,
                'presentation_cutoff':0,'text':'SYNTHETIC_PRIVATE_BOUND_INPUT'}).status_code==202
            state=_await_state(client,path,headers,lambda s:s['phase']=='error')
            assert state['last_error']==('review_request_too_large' if bound=='size' else 'review_budget_exhausted')
            assert state['active_grants']==[] and state['last_error_diagnostic_id']
            assert outgoing==[] and len(incoming.calls)==(1 if track=='output' else 0)
            assert sink.flush(); events=_read_events(tmp_path)
            assert any(e['stage']==track+'_review' and e.get('code')=='limit_reached' for e in events)
            assert 'SYNTHETIC_PRIVATE_BOUND_INPUT' not in json.dumps(events)
    finally:sink.close()
