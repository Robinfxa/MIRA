"""Exact subscription-only missing-header compatibility; synthetic streams only."""
import json
import httpx
import pytest
from mira.adapters.generation.direct_codex_responses import DirectResponsesError, ResponsesRoute
from tests.contracts.test_direct_codex_responses import (
    backend, collect, item_done, completed, ByteStream, event,
)
from tests.contracts.test_direct_generation_diagnostics import actor_failure


@pytest.mark.asyncio
async def test_subscription_200_without_mime_parses_original_stream_once():
    wire=item_done()+completed()
    class Once(ByteStream):
        iterations=0
        async def __aiter__(self):
            self.iterations+=1
            assert self.iterations==1
            async for chunk in super().__aiter__():yield chunk
    stream=Once([wire[i:i+7]for i in range(0,len(wire),7)])
    async def handle(_):return httpx.Response(200,headers={},stream=stream)
    instance,_,requests=backend(handle)
    assert len(await collect(instance))==1
    assert len(requests)==1 and stream.iterations==1 and stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [b'<!DOCTYPE html><html>PRIVATE</html>', b'plain PRIVATE text',
    b'{"object":"response","status":"completed","output":[]}',
    b'event: response.completed\ndata: INVALID PRIVATE JSON\n\n', item_done(),
    item_done()+event('response.incomplete',{'type':'response.incomplete'}),
    item_done(item_type='function_call')+completed()])
async def test_missing_mime_never_accepts_html_json_malformed_incomplete_or_tools(body):
    stream=ByteStream([body])
    async def handle(_):return httpx.Response(200,headers={},stream=stream)
    instance,_,requests=backend(handle)
    record=await actor_failure(instance)
    diag=record['generation_diagnostic']
    assert diag.get('header_compatibility')=='subscription_missing_content_type'
    assert diag['header_failure']=='none' and diag['content_type']=='missing'
    assert record['code']=='invalid_response' and len(requests)==1 and stream.closed
    assert 'PRIVATE' not in json.dumps(record)


@pytest.mark.asyncio
@pytest.mark.parametrize('route,status,headers', [
    (ResponsesRoute.OPENAI_API,200,{}),
    (ResponsesRoute.CHATGPT_SUBSCRIPTION,201,{}),
    (ResponsesRoute.CHATGPT_SUBSCRIPTION,200,{'content-type':''}),
    (ResponsesRoute.CHATGPT_SUBSCRIPTION,200,{'content-type':'text/html'}),
    (ResponsesRoute.CHATGPT_SUBSCRIPTION,200,{'content-type':'application/json'}),
])
async def test_missing_mime_compatibility_does_not_expand_to_other_contracts(route,status,headers):
    async def handle(_):return httpx.Response(status,headers=headers,stream=ByteStream([item_done()+completed()]))
    instance,_,requests=backend(handle,route=route)
    with pytest.raises(DirectResponsesError) as raised:await collect(instance)
    assert raised.value.stage=='response_headers'
    assert raised.value.generation_diagnostic.header_compatibility=='none'
    assert len(requests)==1


@pytest.mark.parametrize('route', ['chatgpt_subscription'])
def test_missing_mime_subscription_through_actual_asgi_actor_and_review(route, monkeypatch):
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
        return httpx.Response(200,headers={},stream=Stream())
    async def forbidden(*_a,**_k):raise AssertionError('No native process in direct path')
    monkeypatch.setattr(asyncio,'create_subprocess_exec',forbidden)
    backend=DirectCodexResponsesGenerationBackend(ResponsesRoute(route),'synthetic-model',
        ApiCredentialSource(SecretStr('synthetic-direct-token')),admitted=True,request_limit=1,
        transport=httpx.MockTransport(handler),speech_enabled=False)
    reviews=SyntheticJevTransport()
    from tests.contracts.test_direct_provider_app import arguments
    from mira.bootstrap.direct_provider_app import create_direct_provider_app
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
