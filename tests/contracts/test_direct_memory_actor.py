"""Synthetic SQLite, paired direct HTTP, production JEV parser and fake speech seam."""
import hashlib
import json
import time
from uuid import uuid4
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mira.adapters.generation.direct_codex_responses import DirectCodexResponsesGenerationBackend, ResponsesRoute
from mira.adapters.memory.sqlite import SQLiteMemoryStore
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.bootstrap.development_voice import DevelopmentVoiceLimits
from mira.bootstrap.providers import GoogleVoiceProviders
from mira.config.memory import MemoryRecallOptions
from mira.domain.memory import MemoryEntry, MemoryScope, MemorySource
from mira.entrypoints.http.operator_pairing import OperatorPairing
from tests.contracts.test_direct_provider_app import arguments
from tests.contracts.test_development_review_composition import SyntheticJevTransport
from tests.integration.test_voice_http import Tts, Stt, speech_request
from tools.live_provider import ApiCredentialSource

ORIGIN='http://127.0.0.1:8000'
CODE='synthetic-direct-memory-pair-00000000'
STATEMENT='I prefer unsweetened tea.'


@pytest.mark.parametrize('route',['chatgpt_subscription','openai_api'])
@pytest.mark.parametrize('voice',[False,True])
@pytest.mark.parametrize('review_mode',['luna_tools','legacy_jev'])
def test_paired_direct_wire_shares_scoped_memory_with_review_and_only_approved_tts(tmp_path,route,voice,review_mode,monkeypatch):
    private=tmp_path/'private';private.mkdir(mode=0o700)
    database=private/'synthetic.sqlite3'
    scope=MemoryScope('synthetic-user','mira','synthetic-world')
    with SQLiteMemoryStore(database) as writer:
        writer.append(MemoryEntry('tea',scope,MemorySource.USER_STATEMENT,STATEMENT,'manual-tea',1))
        writer.append(MemoryEntry('other',MemoryScope('other-user','mira','synthetic-world'),
            MemorySource.USER_STATEMENT,'OTHER SCOPE SENTINEL','manual-other',1))
    before=hashlib.sha256(database.read_bytes()).hexdigest()
    calls=[];closed=[];tts=Tts();stt=Stt()
    async def close_voice():closed.append(True)
    def voice_factory():return GoogleVoiceProviders(stt,tts,close_voice)
    text=json.dumps({'effects':[
        *([{'kind':'speech','value':'You prefer unsweetened tea.'}] if voice else []),
        {'kind':'subtitle','value':'你喜欢无糖茶。'}]},ensure_ascii=False)
    item={'type':'message','id':'synthetic-item','role':'assistant','status':'completed',
        'content':[{'type':'output_text','text':text,'annotations':[]}]}
    item_wire=('event: response.output_item.done\ndata: '+json.dumps({'type':'response.output_item.done','output_index':0,'item':item},ensure_ascii=False)+'\n\n').encode()
    wire=item_wire+('event: response.completed\ndata: '+json.dumps({'type':'response.completed',
        'response':{'status':'completed','output':[item]}},ensure_ascii=False)+'\n\n').encode()
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):yield wire
        async def aclose(self):pass
    async def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())
    backend=DirectCodexResponsesGenerationBackend(ResponsesRoute(route),'synthetic-model',
        ApiCredentialSource(SecretStr('synthetic-token')),admitted=True,request_limit=1,
        transport=httpx.MockTransport(handler),speech_enabled=voice)
    input_review=SyntheticJevTransport();output_review=SyntheticJevTransport()
    native = review_mode == 'luna_tools'
    if native:
        from mira.bootstrap import development_review
        monkeypatch.setattr(development_review,'create_development_review_providers',
            lambda **_:pytest.fail('native memory cannot construct JEV review'))
    app=create_direct_provider_app(**arguments(generation=backend,route=route,
        action_review_mode=review_mode, tool_generation=backend if native else None,
        api_billing_authorized=route=='openai_api',input_transport=None if native else input_review,
        output_transport=None if native else output_review,
        # This case tests successful SQLite evidence wiring, not a 200ms latency SLA.
        # Keep the production default unchanged; give this positive IO fixture its allowed explicit bound.
        memory_options=MemoryRecallOptions(database,scope,'local',True,timeout_ms=1000),
        operator_pairing=OperatorPairing(CODE,(ORIGIN,'http://localhost:8000')),
        authorize_memory_to_direct_provider_and_jev=True,
        authorize_memory_derived_speech_to_google=voice,
        voice_factory=voice_factory if voice else None,voice_required=voice,
        voice_usage_limits=DevelopmentVoiceLimits(1,1,10,10) if voice else None))
    with TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN}) as client:
        public=client.get('/')
        assert ('Google Cloud TTS' in public.text) is voice
        assert ('TypeSafe/JEV 输出审核' in public.text) is (not native)
        assert calls==[] and tts.calls==[]
        assert client.post('/api/v1/operator/pair',json={'code':CODE}).status_code==204
        created=client.post('/api/v1/sessions',json={'client_instance_id':str(uuid4())}).json()
        path='/api/v1/sessions/'+created['session']['session_id']
        headers={'X-Mira-Session-Token':created['session_token']}
        assert client.post(path+'/inputs',headers=headers,json={'request_id':str(uuid4()),
            'activity_seq':1,'presentation_cutoff':0,'text':'What tea do I prefer?'}).status_code==202
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            state=client.get(path,headers=headers).json()
            if state["phase"]=="error" or state["sealed"]:break
            time.sleep(.005)
        assert state['sealed'] and state['phase']=='ready',state.get('last_error')
        assert len(calls)==1
        prompt=json.loads(calls[0]['input'][0]['content'][0]['text'])
        packet=prompt['facts']['memory_evidence']
        assert packet['past_candidates'][0]['text']==STATEMENT
        assert 'OTHER SCOPE SENTINEL' not in json.dumps(prompt)
        assert 'synthetic-user' not in json.dumps(prompt)
        assert all(STATEMENT not in json.dumps(call[0]) for call in input_review.calls)
        # Plain dialogue has no optional event proposal, so no JEV output grade.
        assert not output_review.calls
        for payload,*_ in output_review.calls:
            assert payload['state']['context']['memory_evidence']==packet
            assert payload['state']['contract']['snapshot']['context']['memory_evidence']==packet
        assert tts.calls==[] and state['presented_effects']==[]
        if voice:
            effect=next(grant for grant in state['active_grants'] if grant['kind']=='speech')
            response=speech_request(client,path,headers,effect)
            assert response.status_code==200
            assert json.loads(response.text.splitlines()[-1])['type']=='complete'
            assert tts.calls==[(effect['value'],effect['id'])]
        assert client.post('/api/v1/operator/revoke').status_code==204
        assert client.get(path,headers=headers).status_code==401
    assert closed==([True] if voice else [])
    assert hashlib.sha256(database.read_bytes()).hexdigest()==before


def test_native_memory_timeout_is_explicit_absence_and_does_not_block_body(tmp_path, monkeypatch):
    from mira.application.actor_memory import SessionMemoryBinding
    assert MemoryRecallOptions(Path('/not-read'), MemoryScope('u', 'm', 'w'), 'local', True).timeout_ms == 200
    private = tmp_path / 'private'; private.mkdir(mode=0o700)
    database = private / 'synthetic.sqlite3'
    scope = MemoryScope('synthetic-user', 'mira', 'synthetic-world')
    with SQLiteMemoryStore(database) as writer:
        writer.append(MemoryEntry('tea', scope, MemorySource.USER_STATEMENT, STATEMENT, 'manual-tea', 1))
    async def unavailable(*_args, **_kwargs):
        raise TimeoutError('synthetic local read deadline')
    monkeypatch.setattr(SessionMemoryBinding, 'build_packet', unavailable)
    requests = []
    text = json.dumps({'effects': [{'kind': 'subtitle', 'value': '先聊现在这件事。'}]}, ensure_ascii=False)
    item = {'type': 'message', 'id': 'synthetic-timeout-item', 'role': 'assistant', 'status': 'completed',
        'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}
    events = [('response.output_item.done', {'output_index': 0, 'item': item}),
              ('response.completed', {'response': {'status': 'completed', 'output': [item]}})]
    wire = ''.join('event: '+name+'\ndata: '+json.dumps({'type': name, **body}, ensure_ascii=False)+'\n\n' for name, body in events).encode()
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self): yield wire
    async def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Stream())
    backend = DirectCodexResponsesGenerationBackend(ResponsesRoute.OPENAI_API, 'synthetic-model',
        ApiCredentialSource(SecretStr('synthetic-token')), admitted=True, request_limit=1,
        transport=httpx.MockTransport(handler))
    app = create_direct_provider_app(**arguments(generation=backend, route='openai_api',
        action_review_mode='luna_tools', tool_generation=backend, api_billing_authorized=True,
        input_transport=None, output_transport=None,
        memory_options=MemoryRecallOptions(database, scope, 'local', True),
        operator_pairing=OperatorPairing(CODE, (ORIGIN, 'http://localhost:8000')),
        authorize_memory_to_direct_provider_and_jev=True))
    with TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}) as client:
        assert client.post('/api/v1/operator/pair', json={'code': CODE}).status_code == 204
        created = client.post('/api/v1/sessions', json={'client_instance_id': str(uuid4())}).json()
        path = '/api/v1/sessions/' + created['session']['session_id']
        headers = {'X-Mira-Session-Token': created['session_token']}
        assert client.post(path+'/inputs', headers=headers, json={'request_id': str(uuid4()),
            'activity_seq': 1, 'presentation_cutoff': 0, 'text': '现在聊什么？'}).status_code == 202
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            state = client.get(path, headers=headers).json()
            if state['sealed'] or state['phase'] == 'error': break
            time.sleep(.005)
        assert state['sealed'] and state['phase'] == 'ready'
        assert len(requests) == 1
        facts = json.loads(requests[0]['input'][0]['content'][0]['text'])['facts']
        assert facts['memory_recall_status'] == 'unavailable' and 'memory_evidence' not in facts
        assert STATEMENT not in json.dumps(requests, ensure_ascii=False)
        assert any(e['value'] == '先聊现在这件事。' for e in state['active_grants'])
