"""Direct-provider application composition; only synthetic provider objects."""
import pytest
from mira.config.settings import Settings
from mira.config.loader import ConfigurationError
from mira.bootstrap.direct_provider_app import create_direct_provider_app

class Generation:
    async def generate(self, context):
        if False:
            yield None

class Review:
    async def __call__(self, payload):
        raise AssertionError('composition must not make review requests')

def arguments(**changes):
    result=dict(settings=Settings(),generation=Generation(),route='chatgpt_subscription',
        model='gpt-6-luna',action_review_mode='legacy_jev',input_transport=Review(),output_transport=Review(),authorized=True)
    result.update(changes)
    return result

def test_direct_composition_needs_no_native_runtime_and_keeps_review_ports():
    app=create_direct_provider_app(**arguments())
    assert app.state.direct_provider_route=='chatgpt_subscription'
    assert app.state.direct_provider_model=='gpt-6-luna'
    assert app.state.usage_declaration.codex_requests==1

@pytest.mark.parametrize('changes', [
    {'route':'silent-fallback'}, {'model':''}, {'model':'not a model'}, {'authorized':False},
    {'route':'openai_api'}, {'api_billing_authorized':'yes'}, {'generation':None},
])
def test_invalid_or_unacknowledged_route_does_not_compose(changes):
    with pytest.raises(ConfigurationError):create_direct_provider_app(**arguments(**changes))

def test_api_route_requires_explicit_billing_and_never_substitutes_subscription():
    app=create_direct_provider_app(**arguments(route='openai_api',model='explicit-api-model',api_billing_authorized=True))
    assert app.state.direct_provider_route=='openai_api'
    assert app.state.direct_provider_model=='explicit-api-model'

@pytest.mark.parametrize('route', ['chatgpt_subscription', 'openai_api'])
def test_direct_asgi_review_and_receipts_work_without_codex_subprocess(route, monkeypatch):
    import asyncio
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from mira.application.contracts import CandidateRange, EffectProposal
    from mira.domain.models import EffectKind
    from tests.contracts.test_development_review_composition import SyntheticJevTransport
    from tests.contracts.test_development_app_entry import wait_ready
    async def forbidden(*_a, **_k):
        raise AssertionError('direct app must not spawn Codex')
    monkeypatch.setattr(asyncio,'create_subprocess_exec',forbidden)
    class Candidate:
        calls=0
        async def generate(self, context):
            self.calls+=1
            yield CandidateRange((EffectProposal(EffectKind.SUBTITLE, '这是直接服务路径的合成测试。'),), 'direct-synthetic-origin')
    generation=Candidate(); input_review=SyntheticJevTransport(); output_review=SyntheticJevTransport()
    app=create_direct_provider_app(**arguments(route=route,api_billing_authorized=route=='openai_api',
        generation=generation,input_transport=input_review,output_transport=output_review))
    with TestClient(app) as client:
        created=client.post('/api/v1/sessions',json={'client_instance_id':str(uuid4())}).json()
        path='/api/v1/sessions/'+created['session']['session_id'];headers={'X-Mira-Session-Token':created['session_token']}
        result=client.post(path+'/inputs',headers=headers,json={'request_id':str(uuid4()),'activity_seq':1,'presentation_cutoff':0,'text':'请写一句新文字。'})
        assert result.status_code==202
        state=wait_ready(client,path,headers)
        assert state['phase']=='ready' and len(state['active_grants'])==1
        assert generation.calls==1 and not input_review.calls and not output_review.calls
        assert state['active_grants'][0]['value']=='这是直接服务路径的合成测试。'
        assert client.delete(path,headers=headers).status_code in (200,204)
    assert app.state.container.sessions._sessions=={}

def test_existing_memory_consent_does_not_authorize_new_direct_transmission():
    with pytest.raises(ConfigurationError,match='new direct-provider'):
        create_direct_provider_app(**arguments(memory_options=object()))

@pytest.mark.parametrize('route', ['chatgpt_subscription', 'openai_api'])
def test_httpx_sse_adapter_through_actual_asgi_actor_and_review(route, monkeypatch):
    """The assembled product path, with synthetic HTTP bytes rather than a fake generator."""
    import asyncio
    import json
    import httpx
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from pydantic import SecretStr
    from mira.adapters.generation.direct_codex_responses import (
        DirectCodexResponsesGenerationBackend, ResponsesRoute,
    )
    from tests.contracts.test_development_review_composition import SyntheticJevTransport
    from tests.contracts.test_development_app_entry import wait_ready
    from tools.live_provider import ApiCredentialSource
    def frame(kind, **body):
        return ('event: '+kind+'\ndata: '+json.dumps({'type':kind,**body},ensure_ascii=False)+'\n\n').encode()
    text=json.dumps({'effects':[{'kind':'subtitle','value':'你好，一起听雨吧。'},
                               {'kind':'pose','value':'look_at_rain'}]},ensure_ascii=False)
    item={'type':'message','id':'synthetic-item','role':'assistant','status':'completed',
          'content':[{'type':'output_text','text':text,'annotations':[]}]}
    wire=frame('response.output_item.done',output_index=0,item=item)+frame(
        'response.completed',response={'status':'completed','output':None})
    calls=[]
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            # Exercise actual streaming consumption, including fragmented UTF-8.
            for i in range(0,len(wire),7):yield wire[i:i+7]
        async def aclose(self):pass
    async def handler(request):
        calls.append(request)
        assert request.url.host==('api.openai.com' if route=='openai_api' else 'chatgpt.com')
        assert json.loads(request.content)['store'] is False
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())
    async def forbidden(*_a,**_k):raise AssertionError('No native process in direct path')
    monkeypatch.setattr(asyncio,'create_subprocess_exec',forbidden)
    backend=DirectCodexResponsesGenerationBackend(ResponsesRoute(route),'synthetic-model',
        ApiCredentialSource(SecretStr('synthetic-direct-token')),admitted=True,request_limit=1,
        transport=httpx.MockTransport(handler),speech_enabled=False)
    reviews=SyntheticJevTransport()
    app=create_direct_provider_app(**arguments(generation=backend,route=route,
        api_billing_authorized=route=='openai_api',input_transport=reviews,output_transport=reviews))
    with TestClient(app) as client:
        created=client.post('/api/v1/sessions',json={'client_instance_id':str(uuid4())}).json()
        path='/api/v1/sessions/'+created['session']['session_id']
        headers={'X-Mira-Session-Token':created['session_token']}
        response=client.post(path+'/inputs',headers=headers,json={'request_id':str(uuid4()),
            'activity_seq':1,'presentation_cutoff':0,'text':'请写一句问候。'})
        assert response.status_code==202
        state=wait_ready(client,path,headers)
        assert state['phase']=='ready' and state['last_error'] is None, (state.get('last_error'), len(calls),len(reviews.calls))
        assert [g['kind'] for g in state['active_grants']]==['subtitle','pose']
        assert len(calls)==1 and len(reviews.calls)==2
        client.delete(path,headers=headers)
    assert not app.state.container.sessions._sessions
