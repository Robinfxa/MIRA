"""Synthetic exact-branch diagnostics for 200/non-SSE replies; no provider calls."""
import json
import pytest
from tests.contracts.test_direct_codex_responses import backend, response
from tests.contracts.test_direct_generation_diagnostics import actor_failure


@pytest.mark.asyncio
@pytest.mark.parametrize('headers,body,content_type,length,header_failure,body_kind,code', [
    ({'content-type':'application/json'}, b'{"error":{"code":"model_not_found","message":"PRIVATE"}}', 'application/json','missing','content_type_unsupported','json_error','model_not_found'),
    ({'content-type':'text/html; charset=utf-8'}, b'<!DOCTYPE html><html>PRIVATE</html>', 'text/html','missing','content_type_unsupported','html','none'),
    ({'content-type':'application/json'}, b'{"object":"response","status":"completed","output":[]}', 'application/json','missing','content_type_unsupported','json_response','none'),
    ({'content-type':'text/event-stream; broken'}, b'data: {"type":"response.created"}\n\n', 'text/event-stream','missing','content_type_parameters','sse_like','none'),
    ({'content-type':'text/event-stream','content-length':'12, 12'}, b'PRIVATE', 'text/event-stream','duplicate_identical','content_length_invalid','other','none'),
    ({'content-type':'text/event-stream','content-length':'12, 13'}, b'PRIVATE', 'text/event-stream','duplicate_conflicting','content_length_invalid','other','none'),
    ({'x-private':'PRIVATE','content-type':''}, b'PRIVATE', 'missing','missing','content_type_missing','other','none'),
])
async def test_header_gate_and_safe_body_shape_are_identified(headers,body,content_type,length,header_failure,body_kind,code):
    async def handle(_):return response(body,headers=headers)
    instance,_,requests=backend(handle)
    record=await actor_failure(instance)
    diag=record['generation_diagnostic']
    assert diag.get('content_type')==content_type
    assert diag.get('content_length_kind')==length
    assert diag.get('header_failure')==header_failure
    assert diag.get('body_kind')==body_kind
    assert diag['provider_error_code']==code
    assert record['http_status']==200 and record['code']=='invalid_response'
    assert len(requests)==1 and 'PRIVATE' not in json.dumps(record)


def test_old_v1_generation_diagnostic_remains_exportable():
    from mira.adapters.diagnostics.privacy import validate_event_record
    old={'schema':1,'record_type':'event','timestamp':1,'stage':'generation','kind':'finished',
         'outcome':'failed','context':{},'generation_diagnostic':{
        'phase':'response_headers','reason':'response_headers','http_status':200,
        'content_encoding':'identity','event_types':[],'event_count':0,'terminal_status':'none',
        'provider_error_code':'none','wire_bytes':0,'decoded_bytes':0}}
    result=validate_event_record(old)
    assert result['generation_diagnostic'].get('content_type')=='unobserved'


@pytest.mark.asyncio
async def test_rejected_header_body_read_has_hard_cap_timeout_and_cancellation():
    import asyncio,gzip
    from mira.adapters.generation.direct_codex_responses import DirectResponsesError
    from tests.contracts.test_direct_codex_responses import collect,BlockingStream
    async def too_large(_):
        return response(gzip.compress(b'PRIVATE'*4000),headers={'content-type':'application/json','content-encoding':'gzip'})
    instance,_,_=backend(too_large)
    record=await actor_failure(instance)
    assert record['generation_diagnostic']['body_kind']=='truncated'
    assert record['generation_diagnostic']['decoded_bytes']<=16385
    for cancel in (False,True):
        stream=BlockingStream(b'{"PRIVATE":')
        async def held(_):return response(b'',headers={'content-type':'application/json'},stream=stream)
        instance,_,_=backend(held)
        task=asyncio.create_task(collect(instance));await stream.entered.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        else:
            with pytest.raises(DirectResponsesError) as raised:await task
            assert raised.value.generation_diagnostic.body_kind=='read_timeout'
            assert raised.value.stage=='response_headers'
        assert stream.closed


def test_new_header_diagnostic_fields_are_closed_allowlists():
    from mira.application.generation_diagnostics import SafeGenerationDiagnostic
    for field in ('content_type','content_length_kind','header_failure','body_kind'):
        with pytest.raises(ValueError):
            SafeGenerationDiagnostic(phase='response_headers',reason='content_type_unsupported',**{field:'PRIVATE'})
