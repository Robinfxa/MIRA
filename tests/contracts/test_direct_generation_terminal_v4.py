"""Subscription terminal reconstruction and payload-free complete branch diagnostics."""
import json
import pytest
from mira.adapters.generation.direct_codex_responses import DirectResponsesError, ResponsesRoute
from tests.contracts.test_direct_codex_responses import (
    backend, collect, response, item_done, completed, event, snapshot_message, JSON_OUTPUT,
)
from tests.contracts.test_direct_generation_diagnostics import actor_failure


def done_message(text, *, index=0, phase=None):
    item=snapshot_message(text,item_id=f'msg-{index}')
    if phase is not None:item['phase']=phase
    return event('response.output_item.done',{'type':'response.output_item.done','output_index':index,'item':item}),item


@pytest.mark.asyncio
async def test_subscription_empty_terminal_output_uses_validated_completed_items():
    async def handle(_):return response(item_done()+completed(output=[]))
    instance,_,requests=backend(handle)
    assert len(await collect(instance))==1 and len(requests)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('snapshot', [False,True])
async def test_commentary_is_not_candidate_and_ordered_final_fragments_form_one_json(snapshot):
    first,first_item=done_message('PRIVATE commentary is not an effect',index=0,phase='commentary')
    split=len(JSON_OUTPUT)//2
    a,ai=done_message(JSON_OUTPUT[:split],index=1,phase='final_answer')
    b,bi=done_message(JSON_OUTPUT[split:],index=2,phase='final_answer')
    async def handle(_):return response(first+a+b+completed(output=[first_item,ai,bi]if snapshot else []))
    instance,_,_=backend(handle)
    result=await collect(instance)
    assert len(result)==1 and len(result[0].effects)==3
    assert 'PRIVATE' not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('output,reason', [
    ({},'snapshot_output_shape'),([None],'snapshot_item_shape'),
    ([{'type':'unknown'}],'message_type'),
    ([dict(snapshot_message(),status='in_progress')],'message_status'),
    ([snapshot_message('PRIVATE mismatch')],'snapshot_text_mismatch'),
])
async def test_every_terminal_snapshot_failure_has_specific_safe_reason(output,reason):
    async def handle(_):return response(item_done()+completed(output=output))
    instance,_,_=backend(handle)
    record=await actor_failure(instance)
    diag=record['generation_diagnostic']
    assert diag['reason']==reason
    assert diag.get('completed_message_count')==1
    assert diag.get('snapshot_output_kind') in {'list','other'}
    assert 'PRIVATE' not in json.dumps(record)


@pytest.mark.asyncio
async def test_nonempty_conflict_is_not_overridden_and_equality_is_reported():
    async def handle(_):return response(item_done()+completed(output=[snapshot_message('PRIVATE DIFFERENT')]))
    instance,_,_=backend(handle);record=await actor_failure(instance);diag=record['generation_diagnostic']
    assert diag.get('snapshot_matches_stream') is False
    assert diag.get('snapshot_message_count')==1
    assert diag.get('snapshot_item_types')==['message']
    assert diag.get('snapshot_item_statuses')==['completed']
    assert diag.get('snapshot_text_bytes')==len('PRIVATE DIFFERENT')
    assert diag.get('completed_text_bytes')==len(JSON_OUTPUT.encode())
    assert 'PRIVATE' not in json.dumps(record)


@pytest.mark.asyncio
async def test_empty_snapshot_no_completed_item_and_public_api_remain_rejected():
    delta=event('response.output_text.delta',{'type':'response.output_text.delta','output_index':0,'content_index':0,'delta':JSON_OUTPUT})
    for route,body in [(ResponsesRoute.CHATGPT_SUBSCRIPTION,delta+completed(output=[])),
                       (ResponsesRoute.OPENAI_API,item_done()+completed(output=[]))]:
        async def handle(_):return response(body)
        instance,_,requests=backend(handle,route=route)
        with pytest.raises(DirectResponsesError):await collect(instance)
        assert len(requests)==1


@pytest.mark.asyncio
async def test_unfinished_text_deltas_and_conflicting_done_text_fail_closed():
    delta=event('response.output_text.delta',{'type':'response.output_text.delta','output_index':1,'content_index':0,'delta':'PRIVATE'})
    async def unfinished(_):return response(item_done()+delta+completed(output=[]))
    instance,_,_=backend(unfinished);record=await actor_failure(instance);diag=record['generation_diagnostic']
    assert diag['reason']=='unmatched_delta' and diag['unmatched_delta_count']==1
    assert diag['snapshot_output_kind']=='empty'
    delta=event('response.output_text.delta',{'type':'response.output_text.delta','output_index':0,'content_index':0,'delta':'PRIVATE'})
    async def conflict(_):return response(delta+item_done()+completed(output=[]))
    instance,_,_=backend(conflict);record=await actor_failure(instance)
    assert record['generation_diagnostic']['reason']=='delta_done_text_mismatch'


@pytest.mark.asyncio
async def test_commentary_only_does_not_become_candidate_and_unknown_phase_is_rejected():
    for phase,reason in [('commentary','candidate_missing'),('PRIVATE','message_phase')]:
        frame,_=done_message(JSON_OUTPUT,phase=phase)
        async def handle(_):return response(frame+completed(output=[]))
        instance,_,_=backend(handle);record=await actor_failure(instance)
        assert record['generation_diagnostic']['reason']==reason
        assert 'PRIVATE' not in json.dumps(record)


def test_terminal_metadata_allowlists_and_export_revalidation_reject_payloads():
    from dataclasses import replace
    from mira.application.generation_diagnostics import SafeGenerationDiagnostic
    from mira.application.diagnostic_events import DiagnosticEvent,DiagnosticStage,DiagnosticOutcome
    from mira.adapters.diagnostics.privacy import encode_event,validate_event_record
    value=SafeGenerationDiagnostic(phase='terminal_output',reason='snapshot_text_mismatch')
    for changes in ({'snapshot_output_kind':'PRIVATE'}, {'snapshot_item_types':('PRIVATE',)},
                    {'snapshot_item_statuses':('PRIVATE',)}, {'snapshot_message_phases':('PRIVATE',)},
                    {'snapshot_matches_stream':'PRIVATE'}, {'snapshot_text_bytes':4194306},
                    {'completed_message_count':True}):
        with pytest.raises(ValueError):replace(value,**changes)
    record=encode_event(DiagnosticEvent(DiagnosticStage.GENERATION,DiagnosticOutcome.FAILED,generation_diagnostic=value),1)
    assert validate_event_record(record)==record
    record['generation_diagnostic']['snapshot_message_phases']=['PRIVATE']
    with pytest.raises(ValueError):validate_event_record(record)


@pytest.mark.parametrize('route', ['chatgpt_subscription'])
def test_missing_mime_and_empty_snapshot_through_actual_asgi_actor_and_review(route, monkeypatch):
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
        'response.completed',response={'status':'completed','output':[]})
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


@pytest.mark.asyncio
async def test_late_delta_and_duplicate_announced_index_cannot_mutate_completed_message():
    late=event('response.output_text.delta',{'type':'response.output_text.delta','output_index':0,'content_index':0,'item_id':'different-id','delta':'PRIVATE'})
    added=event('response.output_item.added',{'type':'response.output_item.added','output_index':0,'item':{'type':'message'}})
    for body,reason in [(item_done()+late+completed(output=[]),'late_delta_after_done'),
                        (added+added+item_done()+completed(output=[]),'duplicate_output_item')]:
        async def handle(_):return response(body)
        instance,_,_=backend(handle)
        with pytest.raises(DirectResponsesError) as raised:await collect(instance)
        assert raised.value.reason==reason


@pytest.mark.asyncio
async def test_completed_item_identity_cannot_be_reused_at_another_index():
    split=len(JSON_OUTPUT)//2
    async def handle(_):return response(item_done(JSON_OUTPUT[:split],item_id='same',index=0)+item_done(JSON_OUTPUT[split:],item_id='same',index=1)+completed(output=[]))
    instance,_,_=backend(handle)
    with pytest.raises(DirectResponsesError) as raised:await collect(instance)
    assert raised.value.reason=='message_id_reused'


@pytest.mark.asyncio
async def test_optional_message_phase_metadata_is_not_made_mandatory():
    added=event('response.output_item.added',{'type':'response.output_item.added','output_index':0,'item':{'type':'message'}})
    commentary,ci=done_message('PRIVATE commentary',index=0,phase='commentary')
    final,fi=done_message(JSON_OUTPUT,index=1,phase='final_answer')
    ci.pop('phase');fi.pop('phase')
    async def handle(_):return response(added+commentary+final+completed(output=[ci,fi]))
    instance,_,_=backend(handle)
    assert len(await collect(instance))==1
