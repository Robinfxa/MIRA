"""Direct ASGI conversation/effect boundary; all transports are synthetic."""
import asyncio
import json
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.adapters.review.jev import JevHttpResponse
from mira.application.contracts import CandidateRange, EffectProposal
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.domain.models import EffectKind
from tests.contracts.test_direct_provider_app import arguments
from tests.contracts.test_development_review_composition import SyntheticJevTransport


class Generation:
    def __init__(self, effects): self.effects = effects; self.contexts = []
    async def generate(self, context):
        self.contexts.append(context)
        yield CandidateRange(tuple(EffectProposal(EffectKind(kind), value)
                                   for kind, value in self.effects), 'conversation-synthetic')


class Wire(SyntheticJevTransport):
    def __init__(self, mode='allow', *, gate=False, speech=0.0):
        super().__init__(output_choice=mode if mode in ('allow','reject','unknown') else 'allow')
        self.mode=mode; self.gate=gate; self.speech=speech
        self.arrived=threading.Event(); self.resume=threading.Event()
    async def __call__(self, payload, **kwargs):
        request=json.loads(payload)
        if 'contract' in request['state']:
            self.arrived.set()
            if self.gate:
                while not self.resume.is_set():
                    try: await asyncio.sleep(.002)
                    except asyncio.CancelledError: continue
            if self.mode=='invalid': return JevHttpResponse(200,b'{}')
            if self.mode=='transport': raise OSError('synthetic-unavailable')
        response=await super().__call__(payload,**kwargs)
        if 'contract' not in request['state']:
            doc=json.loads(response.body)
            for key in doc['answers']:
                if key.endswith(':speech_restriction'):
                    doc['answers'][key]={'type':'noul','noul':self.speech}
            return JevHttpResponse(200,json.dumps(doc).encode())
        return response


def session(client):
    value=client.post('/api/v1/sessions',json={'client_instance_id':str(uuid4())}).json()
    return '/api/v1/sessions/'+value['session']['session_id'], {'X-Mira-Session-Token':value['session_token']}


def submit(client,path,headers,activity=1,cutoff=0,text='随便聊聊。'):
    result=client.post(path+'/inputs',headers=headers,json={'request_id':str(uuid4()),
        'activity_seq':activity,'presentation_cutoff':cutoff,'text':text})
    assert result.status_code==202,result.text


def settled(client,path,headers):
    until=time.monotonic()+3
    while time.monotonic()<until:
        state=client.get(path,headers=headers).json()
        if state['sealed'] or state['last_error']: return state
        time.sleep(.003)
    pytest.fail('synthetic turn did not settle')


def voice_options():
    from mira.bootstrap.development_voice import DevelopmentVoiceLimits
    from mira.bootstrap.providers import GoogleVoiceProviders
    from tests.integration.test_voice_http import Tts, Stt
    async def close(): pass
    return dict(voice_factory=lambda:GoogleVoiceProviders(Stt(),Tts(),close),
                voice_required=True,voice_usage_limits=DevelopmentVoiceLimits(1,1,10,10))


def test_plain_text_needs_no_jev_grade():
    wire=Wire('reject'); generation=Generation([('subtitle','我们可以慢慢聊。')])
    app=create_direct_provider_app(**arguments(generation=generation,input_transport=wire,output_transport=wire))
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers)
        state=settled(client,path,headers)
        assert state['sealed'] and state['last_error'] is None
        assert [e['kind'] for e in state['active_grants']]==['subtitle']
        assert wire.calls==[]


@pytest.mark.parametrize('mode',['reject','unknown','invalid','transport'])
def test_optional_failure_preserves_text_and_never_grants_controls(mode):
    wire=Wire(mode);generation=Generation([('subtitle','一起听雨吧。'),('pose','look_at_rain')])
    app=create_direct_provider_app(**arguments(generation=generation,input_transport=wire,output_transport=wire))
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers)
        state=settled(client,path,headers)
        assert state['sealed'] and state['last_error'] is None
        assert [e['kind'] for e in state['active_grants']]==['subtitle']


def test_text_is_available_before_optional_review_and_stop_blocks_late_action():
    wire=Wire(gate=True);generation=Generation([('subtitle','一起听雨吧。'),('pose','look_at_rain')])
    app=create_direct_provider_app(**arguments(generation=generation,input_transport=wire,output_transport=wire))
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers)
        try:
            assert wire.arrived.wait(1)
            state=client.get(path,headers=headers).json()
            assert [e['kind'] for e in state['active_grants']]==['subtitle']
            assert state['active_grants'][0]['cue_speech_id'] is None
            stopped=client.post(path+'/stop',headers=headers,json={'activity_seq':2,'presentation_cutoff':0})
            assert stopped.status_code==200,stopped.text
        finally: wire.resume.set()
        time.sleep(.02)
        state=client.get(path,headers=headers).json()
        assert state['phase']=='stopped' and not state['active_grants']
        assert all(e['kind']!='pose' for e in state.get('issued_effects',[]))


@pytest.mark.parametrize('speech',[1.0,.5])
def test_explicit_turn_mute_keeps_independent_subtitle_without_speech_jev(speech):
    wire=Wire(speech=speech);generation=Generation([('subtitle','我会用文字回复。'),('speech','我会用文字回复。')])
    app=create_direct_provider_app(**arguments(generation=generation,input_transport=wire,output_transport=wire,**voice_options()))
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers,text='这次只打字。')
        state=settled(client,path,headers)
        assert state['sealed'] and state['last_error'] is None
        assert [e['kind'] for e in state['active_grants']]==['subtitle']
        assert state['active_grants'][0]['cue_speech_id'] is None
        assert wire.calls==[]


def test_optional_questions_do_not_grade_ordinary_text():
    wire=Wire();generation=Generation([('subtitle','今天想聊电影。'),('pose','look_at_rain')])
    app=create_direct_provider_app(**arguments(generation=generation,input_transport=wire,output_transport=wire))
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers)
        state=settled(client,path,headers)
        assert [e['kind'] for e in state['active_grants']]==['subtitle','pose']
    output=[call[0] for call in wire.calls if 'contract' in call[0]['state']]
    assert len(output)==1
    suffixes={key.rsplit(':',1)[-1] for key in output[0]['questions']}
    assert not suffixes.intersection({'o1','o2','o3','o4','o5','o6','effect_0'})


def test_permitted_speech_is_ready_while_optional_scene_review_waits():
    wire=Wire(gate=True);generation=Generation([
        ('subtitle','我们聊聊雨。'),('speech','我们聊聊雨。'),('scene','rain_window')])
    app=create_direct_provider_app(**arguments(generation=generation,input_transport=wire,
        output_transport=wire,**voice_options()))
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers)
        try:
            assert wire.arrived.wait(1)
            state=client.get(path,headers=headers).json()
            assert [e['kind'] for e in state['active_grants']]==['subtitle','speech']
            text,speech=state['active_grants']
            assert text['cue_speech_id'] is None
            assert speech['cue_speech_id']==speech['id']
            assert text['cue_id']!=speech['cue_id']
        finally:wire.resume.set()
        assert [e['kind'] for e in settled(client,path,headers)['active_grants']]==['subtitle','speech','scene']


def test_own_text_receipt_during_review_preserves_event_and_next_turn_actual_context():
    wire=Wire(gate=True);generation=Generation([('subtitle','我想看看雨。'),('scene','rain_window')])
    app=create_direct_provider_app(**arguments(generation=generation,input_transport=wire,
        output_transport=wire,generation_request_limit=2,session_turn_limit=2))
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers)
        try:
            assert wire.arrived.wait(1)
            text=client.get(path,headers=headers).json()['active_grants'][0]
            receipt={key:text[key] for key in ('digest','output_epoch','activity_seq')}
            receipt.update(effect_id=text['id'],presentation_seq=1)
            assert client.post(path+'/receipts',headers=headers,json=receipt).status_code==200
        finally:wire.resume.set()
        state=settled(client,path,headers)
        assert [e['kind'] for e in state['active_grants']]==['subtitle','scene']
        scene=state['active_grants'][1]
        assert all(e['id']!=scene['id'] for e in state['presented_effects'])
        receipt={key:scene[key] for key in ('digest','output_epoch','activity_seq')}
        receipt.update(effect_id=scene['id'],presentation_seq=2)
        assert client.post(path+'/receipts',headers=headers,json=receipt).status_code==200
        assert client.post(path+'/receipts',headers=headers,json=receipt).status_code==200
        submit(client,path,headers,activity=2,cutoff=2,text='现在窗边怎么样？')
        settled(client,path,headers)
        assert [(e.kind.value,e.value) for e in generation.contexts[1].presented_effects]==[
            ('subtitle','我想看看雨。'),('scene','rain_window')]
        next_output=[call[0] for call in wire.calls if 'contract' in call[0]['state']][-1]
        assert any(e['id']==scene['id'] for e in next_output['state']['context']['presented_effects'])


def test_optional_event_diagnostics_keep_only_fixed_numeric_question_facts():
    from mira.adapters.review.jev_support.diagnostics import summarize_response_validation
    from mira.adapters.diagnostics.privacy import _encode_response_validation
    from mira.application.choice_wire_policy import CHOICE_WIRE_POLICY_REPORTED_V2
    questions={f'synthetic:{suffix}':{'type':'choice'} for suffix in ('event_scope','event_1')}
    answer={'type':'choice','choice':'unknown','confidence':.9,
            'probabilities':{'allow':.03,'reject':.02,'unknown':.95}}
    body=json.dumps({'model':'jev-1.13.0','answers':{key:answer for key in questions},
                     'usage':{'input_tokens':1,'output_tokens':1}}).encode()
    summary=summarize_response_validation(body,questions,None,maximum_response_bytes=65536,
        choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2)
    assert {fact.question_suffix for fact in summary.answer_facts}=={'event_scope','event_1'}
    encoded=_encode_response_validation(summary)
    assert encoded['unexpected_answer_count']==0
    assert {fact['question_suffix'] for fact in encoded['answer_facts']}=={'event_scope','event_1'}
