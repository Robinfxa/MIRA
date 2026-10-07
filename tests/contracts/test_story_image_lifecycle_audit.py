"""Independent offline lifecycle/authority audit; no codec or live-provider claims."""
import asyncio
from dataclasses import replace
import hashlib
import json
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from mira.application.authored_visual_events import visual_facts
from mira.application.compiler import compile_generated_media, compile_range
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext, generation_context_data
from mira.application.ports.media import CanonicalImage, GeneratedImage, MediaReviewObservation, PixelCheck
from mira.application.story_images import StoryImageAdmission, StoryImageRuntime, compile_image_intent
from mira.bootstrap.character_story import ephemeral_character_factory
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.domain import transitions
from mira.domain.errors import DomainError
from mira.domain.models import EffectKind, Receipt, SessionState
from mira.domain.story_images import ImageProposal, ImageReservation, REQUIRED_PIXEL_CHECKS, parse_generated_photo
from tests.contracts.test_conversation_first import session, submit, settled, Wire, voice_options
from tests.contracts.test_direct_provider_app import arguments

PIXELS=b'\x89PNG\r\n\x1a\nindependent synthetic canonical pixels'

def candidate(*, image=True, speech=False, text='Independent synthetic caption.'):
    effects=(EffectProposal(EffectKind.SUBTITLE,text),)
    if speech: effects+=(EffectProposal(EffectKind.SPEECH,text),)
    return CandidateRange(effects,'audit-synthetic',image_proposal_json=json.dumps(ImageProposal('cafe_rain_window').as_dict()) if image else None)

class Generation:
    def __init__(self, rows=None): self.rows=rows or [candidate()]; self.contexts=[]
    async def generate(self,context):
        self.contexts.append(context)
        for row in self.rows: yield row

class Decoder:
    def canonicalize(self,data):
        assert data==PIXELS
        return CanonicalImage(PIXELS,1024,1024)

class Gate:
    def __init__(self,blocked=False,ignore=True):
        self.arrived=threading.Event();self.release=threading.Event();self.done=threading.Event()
        self.blocked=blocked;self.ignore=ignore;self.calls=[]
    async def wait(self):
        self.arrived.set()
        while self.blocked and not self.release.is_set():
            try: await asyncio.sleep(.002)
            except asyncio.CancelledError:
                if not self.ignore: raise

class Images(Gate):
    async def generate(self,request):
        self.calls.append(request);await self.wait();self.done.set()
        return GeneratedImage(PIXELS,'image/png','audit','synthetic')

class Vision(Gate):
    async def review(self,artifact,request):
        self.calls.append((artifact,request));await self.wait();self.done.set()
        return MediaReviewObservation(request.request_id,request.specification_digest,artifact.content_digest,
          request.policy_revision,tuple(PixelCheck(name,'pass') for name in REQUIRED_PIXEL_CHECKS),
          'Fallible synthetic observation of an empty fictional cafe.')

def app_for(*,images=None,vision=None,generation=None,wire=None,enabled=True,timeout=.8,voice=False,admission=None,session_turn_limit=8):
    images=images or Images();vision=vision or Vision();generation=generation or Generation();wire=wire or Wire()
    factory=lambda _:StoryImageRuntime(images,vision,Decoder(),admission or StoryImageAdmission('audit-offline',True,timeout_seconds=timeout))
    app=create_direct_provider_app(**arguments(generation=generation,input_transport=wire,output_transport=wire,
        character_factory=ephemeral_character_factory(),story_image_factory=factory if enabled else None,
        session_turn_limit=session_turn_limit,input_request_limit=8,output_request_limit=8,
        **({"usage_profile":"application"} if session_turn_limit is None else {}),**(voice_options() if voice else {})))
    return app,images,vision,generation,wire

def actor_for(app,state,headers):return app.state.container.sessions.get(state['session_id'],headers['X-Mira-Session-Token'])
def wait_until(fn,detail='condition'):
    until=time.monotonic()+2
    while time.monotonic()<until:
        value=fn()
        if value:return value
        time.sleep(.003)
    pytest.fail('Timed out waiting for '+detail)
def image_done(client,path,headers):
    return wait_until(lambda:(s if (s:=client.get(path,headers=headers).json())['sealed'] and s['story_image']['state'] in ('qualified','failed','held','unavailable','cancelled','presented') else None),'terminal image')
def body_for(effect):
    resource,digest=parse_generated_photo(effect['value'])
    return resource,dict(effect_id=effect['id'],digest=effect['digest'],output_epoch=effect['output_epoch'],activity_seq=effect['activity_seq'],content_digest=digest)
def receipt(client,path,headers,effect,seq):
    body={key:effect[key] for key in ('digest','output_epoch','activity_seq')}
    body.update(effect_id=effect['id'],presentation_seq=seq)
    result=client.post(path+'/receipts',headers=headers,json=body)
    assert result.status_code==200,result.text

def test_configured_intent_exposes_pending_while_jev_waits():
    wire=Wire(gate=True);app,images,_,_,_=app_for(wire=wire)
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers)
        try:
            assert wire.arrived.wait(1)
            state=client.get(path,headers=headers).json()
            assert [e['kind'] for e in state['active_grants']]==['subtitle']
            assert images.calls==[]
            assert state['story_image']['state']=='pending'
        finally:wire.resume.set()

def test_ordinary_caption_and_speech_granted_before_image_intent_review():
    wire=Wire(gate=True);app,images,_,_,_=app_for(wire=wire,generation=Generation([candidate(speech=True)]),voice=True)
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers)
        try:
            assert wire.arrived.wait(1)
            state=client.get(path,headers=headers).json()
            assert sorted(e['kind'] for e in state['active_grants'])==['speech','subtitle']
            assert state['last_error'] is None and not images.calls
        finally:wire.resume.set()

@pytest.mark.parametrize('enabled',[True,False])
def test_plain_chat_does_not_create_image_work(enabled):
    app,images,vision,_,wire=app_for(enabled=enabled,generation=Generation([candidate(image=False)]))
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=settled(client,path,headers)
        assert state['story_image']['state']==('idle' if enabled else 'unavailable')
        assert not images.calls and not vision.calls and not wire.calls

@pytest.mark.parametrize('review',['reject','unknown'])
def test_one_intent_is_not_repeatedly_reviewed_across_duplicate_candidates(review):
    app,images,_,_,wire=app_for(wire=Wire(review),generation=Generation([candidate(),candidate()]))
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=settled(client,path,headers)
        calls=[request for request,_,_ in wire.calls if 'contract' in request['state']]
        assert not images.calls and len(state['active_grants'])==2
        assert len(calls)==1

def test_duplicate_candidate_preserves_inflight_image_status():
    images=Images(blocked=True);app,_,_,_,wire=app_for(images=images,generation=Generation([candidate(),candidate()]))
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers)
        try:
            state=settled(client,path,headers);assert images.arrived.wait(1)
            assert len(images.calls)==1
            assert len([r for r,_,_ in wire.calls if 'contract' in r['state']])==1
            assert state['story_image']['state']=='generating'
        finally:images.release.set()

@pytest.mark.parametrize('stage',['image','vision'])
@pytest.mark.parametrize('fence',['stop','accepted_input','history_pending','dismiss','close'])
def test_uncooperative_backend_cannot_grant_or_update_wrong_epoch(stage,fence):
    images=Images(blocked=stage=='image');vision=Vision(blocked=stage=='vision')
    app,_,_,generation,_=app_for(images=images,vision=vision)
    gate=images if stage=='image' else vision
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=settled(client,path,headers)
        actor=actor_for(app,state,headers)
        try:
            assert gate.arrived.wait(1)
            if fence=='stop':
                result=client.post(path+'/stop',headers=headers,json={'activity_seq':2,'presentation_cutoff':0});assert result.status_code==200
            elif fence=='accepted_input':
                generation.rows=[candidate(image=False,text='New branch')];submit(client,path,headers,activity=2);settled(client,path,headers)
            elif fence=='history_pending':
                result=client.post(path+'/inputs',headers=headers,json={'request_id':str(uuid4()),'activity_seq':2,'presentation_cutoff':1,'text':'not accepted'})
                assert result.status_code==409 and result.json()['code']=='history_pending'
            elif fence=='dismiss':
                result=client.post(path+'/photo-dismissals',headers=headers,json={'request_id':str(uuid4()),'expected_revision':0,'presentation_cutoff':0,'target':'all_photos'});assert result.status_code==200
            else:assert client.delete(path,headers=headers).status_code==204
            expected=actor._state
        finally:gate.release.set()
        wait_until(lambda:not actor._image_tasks,'tracked image tasks drained')
        if fence in ('accepted_input','history_pending'):
            assert actor._state.story_image.state=='qualified'
            media=[e for e in actor._state.active_grants if e.kind is EffectKind.MEDIA]
            assert (len(media)==1 and media[0].output_epoch==2) if fence=='accepted_input' else not media
        else:
            assert actor._state==expected
            assert not any(e.kind is EffectKind.MEDIA for e in actor._state.issued_effects)
            if stage=='image':assert not vision.calls
        assert actor._story_images.attempts==1 and actor._story_images.reserved_bytes==0
        if fence=='history_pending':assert actor._state.user_inputs==('随便聊聊。',)

@pytest.mark.parametrize('stage',['image','vision'])
def test_timeout_releases_authority_and_never_refunds_attempt(stage):
    images=Images(blocked=stage=='image');vision=Vision(blocked=stage=='vision')
    app,_,_,_,_=app_for(images=images,vision=vision,timeout=.04);gate=images if stage=='image' else vision
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers)
        try:
            assert gate.arrived.wait(1);state=image_done(client,path,headers)
            assert state['story_image']['failure_code']=='timeout' and state['last_error'] is None
            actor=actor_for(app,state,headers);before=actor._state
        finally:gate.release.set()
        wait_until(lambda:not actor._image_tasks)
        assert actor._state==before and actor._story_images.attempts==1 and actor._story_images.reserved_bytes==0

@pytest.mark.parametrize('mutation',['effect_id','digest','output_epoch','activity_seq','content_digest','resource','cross_session'])
def test_authenticated_resource_rejects_forged_grant(mutation):
    app,_,_,_,_=app_for()
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=image_done(client,path,headers)
        effect=next(e for e in state['active_grants'] if e['kind']=='media');resource,body=body_for(effect)
        if mutation=='resource':resource=str(uuid4())
        elif mutation=='cross_session':
            other,_,_,_,_=app_for()
            with TestClient(other) as other_client:
                other_path,other_headers=session(other_client)
                result=other_client.post(other_path+'/story-images/'+resource,headers=other_headers,json=body)
                assert result.status_code==409
                assert client.post(path+'/story-images/'+resource,headers=other_headers,json=body).status_code==404
            return
        else:body[mutation]=(body[mutation]+1 if mutation in ('output_epoch','activity_seq') else str(uuid4()) if mutation=='effect_id' else 'f'*64)
        result=client.post(path+'/story-images/'+resource,headers=headers,json=body)
        assert result.status_code==409

def test_pixels_are_exact_and_fetch_is_not_presentation():
    app,images,vision,_,wire=app_for()
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers,text='PRIVATE_AUDIT_SENTINEL');state=image_done(client,path,headers)
        actor=actor_for(app,state,headers)
        effect=next(e for e in state['active_grants'] if e['kind']=='media');resource,body=body_for(effect)
        response=client.post(path+'/story-images/'+resource,headers=headers,json=body)
        assert response.content==PIXELS==vision.calls[0][0].png
        assert response.headers['cache-control']=='no-store'
        assert hashlib.sha256(response.content).hexdigest()==body['content_digest']
        assert actor._state.presented_effects==() and not actor._state.photo_visible
        request=images.calls[0];assert 'PRIVATE_AUDIT_SENTINEL' not in request.specification
        reviewed=next(r for r,_,_ in wire.calls if 'contract' in r['state'])['state']['candidate']['image_intent']
        assert reviewed['specification']==request.specification
        assert reviewed['specification_digest']==request.specification_digest==hashlib.sha256(request.specification.encode()).hexdigest()
        assert reviewed['dependency_digest']==request.dependency_digest and reviewed['policy_revision']==request.policy_revision

def test_receipt_dismissal_and_next_context_have_one_shared_current_fact():
    app,_,_,generation,wire=app_for()
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=image_done(client,path,headers)
        for seq,effect in enumerate(state['active_grants'],1):receipt(client,path,headers,effect,seq)
        actor=actor_for(app,state,headers);assert actor._state.story_image_facts[0].visible
        result=client.post(path+'/photo-dismissals',headers=headers,json={'request_id':str(uuid4()),'expected_revision':0,'presentation_cutoff':2});assert result.status_code==200
        generation.rows=[replace(candidate(image=False),effects=(EffectProposal(EffectKind.SUBTITLE,'What was shown?'),EffectProposal(EffectKind.POSE,'look_at_rain')))]
        submit(client,path,headers,activity=2,cutoff=2);settled(client,path,headers)
        generated=generation_context_data(generation.contexts[-1])['story_images']
        reviewed=[r for r,_,_ in wire.calls if 'contract' in r['state']][-1]['state']['context']['story_images']
        assert json.loads(json.dumps(generated))==reviewed
        assert generated[0]['state']=='presented' and not generated[0]['visible']
        assert generated[0]['provenance']=='generated_visualization'
        assert 'never a real event or user memory' in generated[0]['interpretation']
        story=json.loads(generation.contexts[-1].character_story.context_json)
        assert 'Fallible synthetic observation' not in json.dumps(story)

def test_dismiss_immediately_updates_stored_current_visibility_fact():
    app,_,_,_,_=app_for()
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=image_done(client,path,headers)
        for seq,effect in enumerate(state['active_grants'],1):receipt(client,path,headers,effect,seq)
        actor=actor_for(app,state,headers)
        result=client.post(path+'/photo-dismissals',headers=headers,json={'request_id':str(uuid4()),'expected_revision':0,'presentation_cutoff':2});assert result.status_code==200
        assert actor._state.photo_visible is False
        assert actor._state.story_image_facts[0].visible is False

def test_fixed_vs_generated_visibility_uses_receipt_sequence():
    fixed=compile_range(CandidateRange((EffectProposal(EffectKind.MEDIA,'trip_photo'),),'audit'),epoch=1,activity=1)[0]
    generated=compile_generated_media(str(uuid4()),'a'*64,epoch=1,activity=1)
    state=transitions.begin_input(SessionState('s','c'),activity_seq=1,cutoff=0,request_id='turn',text='show')
    state=transitions.accept_range(state,output_epoch=1,effects=(fixed,generated))
    state=transitions.record_receipt(state,Receipt(generated.id,generated.digest,1,1,1))
    state=transitions.record_receipt(state,Receipt(fixed.id,fixed.digest,1,1,2))
    context=GenerationContext('next',('next',),state.presented_effects,1,photo_visible=state.photo_visible)
    assert visual_facts(context)['trip_photo']['visible'] is True

@pytest.mark.parametrize('kind',[kind for kind in EffectKind if kind is not EffectKind.MEDIA])
def test_postseal_reservation_cannot_mint_non_image_effect(kind):
    state=transitions.begin_input(SessionState('s','c'),activity_seq=1,cutoff=0,request_id='turn',text='show')
    reservation=ImageReservation('i','turn',1,1,0,'a'*64,'b'*64,'policy',session_id='s')
    state=transitions.reserve_generated_media(state,reservation);state=transitions.seal(state,output_epoch=1)
    resource=str(uuid4());state=transitions.qualify_generated_media(state,reservation=reservation,resource_id=resource,content_digest='c'*64,specification_digest='a'*64,policy_revision='policy')
    effect=compile_range(CandidateRange((EffectProposal(kind,'arbitrary payload'),),'audit'),epoch=1,activity=1)[0]
    with pytest.raises(DomainError,match='Invalid reserved image effect'):
        transitions.accept_generated_media(state,reservation=state.image_reservations[0],effect=effect)

def test_attempt_cost_byte_budget_and_close_are_bounded():
    runtime=StoryImageRuntime(Images(),Vision(),Decoder(),StoryImageAdmission('audit',True,max_cost_microunits=15,cost_per_attempt_microunits=7,max_output_bytes=1024,max_total_bytes=2048))
    state=transitions.begin_input(SessionState('s','c'),activity_seq=1,cutoff=0,request_id='turn',text='show')
    runtime.bind_session('s');story=ephemeral_character_factory()(state).begin_input('turn',1)
    intent=compile_image_intent(ImageProposal('cafe_rain_window'),story)
    first=runtime.reserve(intent,state);second=runtime.reserve(intent,state)
    assert runtime.attempts==2 and runtime.reserved_bytes==2048 and runtime.cost_reserved==14
    with pytest.raises(ValueError,match='budget'):runtime.reserve(intent,state)
    runtime.release(first.request_id);runtime.release(second.request_id)
    with pytest.raises(ValueError,match='budget'):runtime.reserve(intent,state)
    assert runtime.attempts==2 and runtime.cost_reserved==14 and runtime.reserved_bytes==0
    runtime.close();assert not runtime._artifacts and runtime.used_bytes==0

@pytest.mark.parametrize('part',['request','spec','policy','pixels','checks','duplicates'])
def test_review_result_binding_mutations_fail_closed(part):
    class MutatedVision(Vision):
        async def review(self,artifact,request):
            value=await super().review(artifact,request)
            if part=='request':return replace(value,request_id=str(uuid4()))
            if part=='spec':return replace(value,specification_digest='0'*64)
            if part=='policy':return replace(value,policy_revision='old')
            if part=='pixels':return replace(value,checked_content_digest='0'*64)
            if part=='checks':return replace(value,checks=value.checks[:-1])
            return replace(value,checks=(value.checks[0],)*len(value.checks))
    app,_,_,_,_=app_for(vision=MutatedVision())
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=image_done(client,path,headers)
        assert state['story_image']['state']=='failed' and state['last_error'] is None
        assert [e['kind'] for e in state['active_grants']]==['subtitle']

def test_resource_detects_post_review_storage_corruption():
    app,_,_,_,_=app_for()
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=image_done(client,path,headers)
        effect=next(e for e in state['active_grants'] if e['kind']=='media');resource,body=body_for(effect)
        actor=actor_for(app,state,headers);original=actor._story_images._artifacts[resource]
        actor._story_images._artifacts[resource]=replace(original,png=original.png+b'corruption')
        assert client.post(path+'/story-images/'+resource,headers=headers,json=body).status_code==409

@pytest.mark.parametrize('mutate',['digest','epoch','activity','unknown'])
def test_bad_receipts_cannot_promote_qualified_to_presented(mutate):
    app,_,_,_,_=app_for()
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=image_done(client,path,headers)
        effect=next(e for e in state['active_grants'] if e['kind']=='media')
        body={key:effect[key] for key in ('digest','output_epoch','activity_seq')};body.update(effect_id=effect['id'],presentation_seq=1)
        key={'digest':'digest','epoch':'output_epoch','activity':'activity_seq','unknown':'effect_id'}[mutate]
        body[key]=body[key]+1 if mutate in ('epoch','activity') else '0'*64 if mutate=='digest' else str(uuid4())
        assert client.post(path+'/receipts',headers=headers,json=body).status_code in (400,409)
        actor=actor_for(app,state,headers)
        assert actor._state.story_image.state=='qualified' and not actor._state.presented_effects

def test_duplicate_input_and_receipt_do_not_repeat_generation_or_grants():
    app,images,vision,_,wire=app_for()
    with TestClient(app) as client:
        path,headers=session(client);body={'request_id':str(uuid4()),'activity_seq':1,'presentation_cutoff':0,'text':'draw'}
        assert client.post(path+'/inputs',headers=headers,json=body).status_code==202
        state=image_done(client,path,headers);actor=actor_for(app,state,headers)
        assert client.post(path+'/inputs',headers=headers,json=body).status_code==202
        for seq,effect in enumerate(state['active_grants'],1):
            receipt(client,path,headers,effect,seq);receipt(client,path,headers,effect,seq)
        assert len(images.calls)==len(vision.calls)==1 and len(actor._state.image_reservations)==1
        assert len(actor._state.issued_effects)==2 and len(actor._state.receipts)==2
        assert len([r for r,_,_ in wire.calls if 'contract' in r['state']])==1

def test_image_failure_and_pixel_description_are_not_raw_diagnostics(tmp_path):
    from mira.adapters.diagnostics.recorder import DiagnosticOptions,LocalDiagnostics
    class SecretVision(Vision):
        async def review(self,artifact,request):raise ValueError('PIXEL_RAW_DIAGNOSTIC_SENTINEL')
    sink=LocalDiagnostics(DiagnosticOptions(tmp_path),worker=False);assert sink.set_recording(True,consent=True)
    app,_,_,_,_=app_for(vision=SecretVision())
    with TestClient(app) as client:
        path,headers=session(client);state=client.get(path,headers=headers).json();actor=actor_for(app,state,headers)
        actor._diagnostics=sink;submit(client,path,headers);state=image_done(client,path,headers)
        assert state['last_error'] is None and 'PIXEL_RAW_DIAGNOSTIC_SENTINEL' not in json.dumps(state)
    assert sink.flush();sink.close()
    raw=[json.loads(line) for file in (tmp_path/'raw').glob('raw-*.jsonl') for line in file.read_text().splitlines()]
    assert [record['kind'] for record in raw]==['dialogue']
    all_text=''.join(file.read_text() for file in tmp_path.rglob('*.jsonl'))
    assert 'PIXEL_RAW_DIAGNOSTIC_SENTINEL' not in all_text
    assert 'independent synthetic canonical pixels' not in all_text

def test_generation_failure_does_not_leave_image_permanently_generating():
    images=Images(blocked=True)
    class BrokenGeneration(Generation):
        async def generate(self,context):
            yield candidate()
            while not images.arrived.is_set():await asyncio.sleep(.002)
            raise ValueError('synthetic trailing text failure')
    app,_,_,_,_=app_for(images=images,generation=BrokenGeneration())
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers)
        try:
            state=settled(client,path,headers);actor=actor_for(app,state,headers)
            assert state['last_error']=='generation_failed'
        finally:images.release.set()
        wait_until(lambda:not actor._image_tasks)
        assert not any(e.kind is EffectKind.MEDIA for e in actor._state.issued_effects)
        assert actor._state.story_image.state=='qualified'
