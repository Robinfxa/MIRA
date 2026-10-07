"""R2 reconstruction: exact job/presentation/completion lifecycle, synthetic only."""
import asyncio
from dataclasses import replace
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.application.contracts import EffectProposal
from mira.application.ports.generation_tools import GenerationToolCall
from mira.application.story_images import StoryImageAdmission,StoryImageRuntime
from mira.domain.models import EffectKind
from tests.contracts.test_story_image_lifecycle_audit import (
    Images,Vision,Generation,Decoder,actor_for,app_for,body_for,candidate,image_done,
    receipt,session,settled,submit,wait_until,
)


@pytest.mark.parametrize("session_turn_limit", [8, None])
def test_review_survives_three_turns_and_uses_current_exact_receipt(session_turn_limit):
    vision=Vision(blocked=True,ignore=False)
    app,images,_,generation,_=app_for(vision=vision,timeout=4,session_turn_limit=session_turn_limit)
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);settled(client,path,headers)
        try:
            assert vision.arrived.wait(1);origin=images.calls[0]
            generation.rows=[candidate(image=False)]
            for n in (2,3,4):
                submit(client,path,headers,activity=n);state=settled(client,path,headers)
                assert state['story_image']['state']=='reviewing'
                assert generation.contexts[-1].story_images[0].state=='reviewing'
            vision.release.set();state=image_done(client,path,headers)
            image=next(e for e in state['active_grants'] if e['kind']=='media')
            assert image['output_epoch']==image['activity_seq']==4
            assert images.calls==[origin] and len(vision.calls)==1 and origin.output_epoch==1
            resource,body=body_for(image)
            assert client.post(path+'/story-images/'+resource,headers=headers,json=body).status_code==200
            receipt(client,path,headers,image,1)
            submit(client,path,headers,activity=5,cutoff=1);settled(client,path,headers)
            fact=generation.contexts[-1].story_images[0]
            assert fact.state=='presented' and fact.presented_effect_id==image['id']
        finally:vision.release.set()


@pytest.mark.parametrize("session_turn_limit", [8, None])
def test_qualified_rollover_revokes_old_grant_without_more_image_or_review(session_turn_limit):
    app,images,vision,generation,_=app_for(session_turn_limit=session_turn_limit)
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=image_done(client,path,headers)
        old=next(e for e in state['active_grants'] if e['kind']=='media');resource,body=body_for(old)
        generation.rows=[candidate(image=False)];submit(client,path,headers,activity=2);state=settled(client,path,headers)
        new=next(e for e in state['active_grants'] if e['kind']=='media')
        assert new['id']!=old['id'] and new['value']==old['value']
        assert client.post(path+'/story-images/'+resource,headers=headers,json=body).status_code==409
        forged={k:old[k] for k in ('digest','output_epoch','activity_seq')};forged.update(effect_id=old['id'],presentation_seq=1)
        assert client.post(path+'/receipts',headers=headers,json=forged).status_code==409
        assert client.post(path+'/receipts',headers=headers,json={**forged,'effect_id':new['id']}).status_code==409
        receipt(client,path,headers,new,1);receipt(client,path,headers,new,1)
        submit(client,path,headers,activity=3,cutoff=1);state=settled(client,path,headers)
        assert not any(e['kind']=='media' for e in state['active_grants'])
        assert len(images.calls)==len(vision.calls)==1


def test_reply_stop_preserves_job_global_stop_cancels_and_never_refunds():
    vision=Vision(blocked=True,ignore=False);app,images,_,generation,_=app_for(vision=vision,timeout=4)
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);settled(client,path,headers)
        try:
            assert vision.arrived.wait(1)
            response=client.post(path+'/stop',headers=headers,json={'activity_seq':2,'presentation_cutoff':0,'scope':'reply'})
            assert response.status_code==200 and response.json()['story_image']['state']=='reviewing'
            generation.rows=[candidate(image=False)];submit(client,path,headers,activity=3);settled(client,path,headers)
            state=client.post(path+'/stop',headers=headers,json={'activity_seq':4,'presentation_cutoff':0}).json()
            assert state['story_image']['state']=='cancelled'
            actor=actor_for(app,state,headers);vision.release.set();wait_until(lambda:not actor._image_tasks)
            assert not actor._state.active_grants and actor._story_images.attempts==1
            assert len(images.calls)==len(vision.calls)==1
        finally:vision.release.set()


def test_ready_job_survives_unrelated_failed_chat_then_presents():
    class Replies(Generation):
        async def generate(self,context):
            if context.output_epoch==2:raise OSError('synthetic unrelated failure')
            async for row in super().generate(context):yield row
    generation=Replies();app,images,vision,_,_=app_for(generation=generation)
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);image_done(client,path,headers)
        generation.rows=[candidate(image=False)];submit(client,path,headers,activity=2)
        wait_until(lambda:client.get(path,headers=headers).json()['phase']=='error')
        assert client.get(path,headers=headers).json()['story_image']['state']=='qualified'
        submit(client,path,headers,activity=3);state=settled(client,path,headers)
        assert any(e['kind']=='media' for e in state['active_grants'])
        assert len(images.calls)==len(vision.calls)==1


def test_failed_job_stays_failed_in_next_context():
    class Failed(Vision):
        async def review(self,artifact,request):raise OSError('synthetic pixel failure')
    app,_,_,generation,_=app_for(vision=Failed())
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);assert image_done(client,path,headers)['story_image']['state']=='failed'
        generation.rows=[candidate(image=False)]
        for n in (2,3):
            submit(client,path,headers,activity=n);state=settled(client,path,headers)
            assert state['story_image']['state']=='failed' and generation.contexts[-1].story_images[0].state=='failed'


def fixed_and_pending_app():
    from mira.bootstrap.direct_provider_app import create_direct_provider_app
    from mira.bootstrap.character_story import ephemeral_character_factory
    from tests.contracts.test_authored_photo_events import ready
    from tests.contracts.test_direct_provider_app import arguments
    from tests.contracts.test_conversation_first import Wire
    images=Images(blocked=True,ignore=False);row=candidate()
    row=replace(row,effects=row.effects+(EffectProposal(EffectKind.MEDIA,'trip_photo'),))
    wire=Wire()
    app=create_direct_provider_app(**arguments(generation=Generation([row]),input_transport=wire,output_transport=wire,
        character_factory=ephemeral_character_factory(readiness=ready()),
        story_image_factory=lambda _:StoryImageRuntime(images,Vision(),Decoder(),StoryImageAdmission('offline',True,timeout_seconds=4)),
        session_turn_limit=8,input_request_limit=8,output_request_limit=8))
    return app,images


@pytest.mark.parametrize('explicit',[True,False])
def test_fixed_display_close_keeps_pending_job_and_future_generated_display(explicit):
    app,images=fixed_and_pending_app()
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=settled(client,path,headers)
        try:
            assert images.arrived.wait(1)
            fixed=next(e for e in state['active_grants'] if e['value']=='trip_photo');receipt(client,path,headers,fixed,1)
            body={'request_id':str(uuid4()),'expected_revision':0,'presentation_cutoff':1}
            if explicit:body.update(target='display',expected_photo_effect_id=fixed['id'])
            response=client.post(path+'/photo-dismissals',headers=headers,json=body)
            assert response.status_code==200 and response.json()['story_image']['state']=='generating'
            assert not response.json()['photo_visible']
            images.release.set();state=image_done(client,path,headers)
            image=next(e for e in state['active_grants'] if e['kind']=='media');receipt(client,path,headers,image,2)
            assert client.get(path,headers=headers).json()['story_image']['state']=='presented'
        finally:images.release.set()


def test_pending_job_cancel_keeps_visible_fixed_photo_and_rejects_wrong_job():
    app,images=fixed_and_pending_app()
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=settled(client,path,headers)
        try:
            assert images.arrived.wait(1)
            fixed=next(e for e in state['active_grants'] if e['value']=='trip_photo');receipt(client,path,headers,fixed,1)
            body={'request_id':str(uuid4()),'expected_revision':0,'presentation_cutoff':1,'target':'image_job','expected_image_request_id':str(uuid4())}
            assert client.post(path+'/photo-dismissals',headers=headers,json=body).status_code==409
            body['expected_image_request_id']=state['story_image']['request_id']
            response=client.post(path+'/photo-dismissals',headers=headers,json=body)
            assert response.status_code==200 and response.json()['photo_visible']
            assert response.json()['story_image']['state']=='cancelled'
        finally:images.release.set()


class CompletionBackend:
    supports_image_completion=True
    def __init__(self,blocked=False,fail=False):
        import threading
        self.calls=[];self.blocked=blocked;self.fail=fail;self.arrived=threading.Event();self.release=threading.Event()
    async def generate_image_completion(self,context):
        self.calls.append(context);self.arrived.set()
        while self.blocked and not self.release.is_set():
            try:await asyncio.sleep(.002)
            except asyncio.CancelledError:pass
        if self.fail:raise OSError('synthetic completion failure')
        return candidate(image=False,text='找到了，给你看看。')


def completion_body(state):
    return dict(request_id=state['story_image']['request_id'],parent_request_id=state['request_id'],
        output_epoch=state['output_epoch'],activity_seq=state['activity_seq'],
        presented_effect_id=next((e['id'] for e in state['presented_effects'] if e['kind']=='media'),None))


def test_completion_requires_display_is_one_shot_and_receipt_distinct():
    backend=CompletionBackend();app,_,_,_,_=app_for()
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=image_done(client,path,headers)
        actor=actor_for(app,state,headers);actor._tool_generation=backend
        prior={e['id'] for e in state['active_grants']}
        assert client.post(path+'/story-image-completions',headers=headers,json=completion_body(state)).status_code==409
        for seq,e in enumerate(state['active_grants'],1):receipt(client,path,headers,e,seq)
        state=client.get(path,headers=headers).json();body=completion_body(state)
        assert state['story_image']['completion_state']=='pending'
        assert client.post(path+'/story-image-completions',headers=headers,json=body).status_code==202
        state=wait_until(lambda:s if (s:=client.get(path,headers=headers).json())['story_image']['completion_state']=='granted' else None)
        assert len(backend.calls)==1 and state['sealed']
        extra=[e for e in state['active_grants'] if e['id'] not in prior]
        assert len(extra)==1 and extra[0]['value']=='找到了，给你看看。'
        assert client.post(path+'/story-image-completions',headers=headers,json=body).status_code==202
        assert len(backend.calls)==1
        receipt(client,path,headers,extra[0],len(prior)+1)
        assert client.get(path,headers=headers).json()['story_image']['completion_state']=='presented'
        assert backend.calls[0].story_image_completions[0].presented_effect_id==body['presented_effect_id']


@pytest.mark.parametrize('event',['new_input','stop','failure','admission'])
def test_completion_abort_or_failure_keeps_picture_and_never_retries(event):
    backend=CompletionBackend(blocked=event!='failure',fail=event=='failure');app,_,_,generation,_=app_for()
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=image_done(client,path,headers)
        actor=actor_for(app,state,headers);actor._tool_generation=backend
        try:
            for seq,e in enumerate(state['active_grants'],1):receipt(client,path,headers,e,seq)
            state=client.get(path,headers=headers).json();body=completion_body(state)
            assert client.post(path+'/story-image-completions',headers=headers,json=body).status_code==202
            assert backend.arrived.wait(1)
            if event=='new_input':
                actor._tool_generation=None;generation.rows=[candidate(image=False)];submit(client,path,headers,activity=2,cutoff=2);settled(client,path,headers)
            elif event=='stop':assert client.post(path+'/stop',headers=headers,json={'activity_seq':2,'presentation_cutoff':2}).status_code==200
            elif event=='admission':actor._story_images.admission=replace(actor._story_images.admission,reference='revoked')
            backend.release.set();wait_until(lambda:not actor._tasks)
            state=client.get(path,headers=headers).json()
            assert state['story_image']['state']=='presented' and state['story_image']['completion_state'] in ('failed','cancelled')
            assert len(backend.calls)==1 and not any(e['value']=='找到了，给你看看。' for e in state['active_grants'])
        finally:backend.release.set()


def test_next_ordinary_context_consumes_event_without_claiming_notification():
    app,_,_,generation,_=app_for()
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=image_done(client,path,headers)
        for seq,e in enumerate(state['active_grants'],1):receipt(client,path,headers,e,seq)
        generation.rows=[candidate(image=False)];submit(client,path,headers,activity=2,cutoff=2);state=settled(client,path,headers)
        assert len(generation.contexts[-1].story_image_completions)==1
        assert state['story_image']['completion_state']=='context_consumed' and state['story_image']['completion_effect_id'] is None
        submit(client,path,headers,activity=3,cutoff=2);settled(client,path,headers)
        assert not generation.contexts[-1].story_image_completions
        assert generation.contexts[-1].story_images[0].state=='presented'


@pytest.mark.asyncio
async def test_completion_adapter_subscription_only_and_exact_existing_ledger():
    from mira.adapters.generation.direct_codex_responses import ResponsesRoute,DirectResponsesError
    from tests.contracts.test_direct_luna_tools import backend,CONTEXT,response,wire,message
    async def handle(request):
        body=json.loads(request.content);assert body['tools']==[] and body['tool_choice']=='none'
        return response(wire([message('找到了，给你看看。')]))
    instance,source,requests=backend(handle,route=ResponsesRoute.CHATGPT_SUBSCRIPTION,request_limit=1)
    assert instance.supports_image_completion
    await instance.generate_image_completion(CONTEXT)
    assert len(requests)==source.calls==1 and instance._remaining==0
    with pytest.raises(DirectResponsesError):await instance.generate_image_completion(CONTEXT)
    assert len(requests)==1
    api,source,requests=backend(handle,route=ResponsesRoute.OPENAI_API,request_limit=1)
    assert not api.supports_image_completion
    with pytest.raises(DirectResponsesError):await api.generate_image_completion(CONTEXT)
    assert not requests and source.calls==0 and api._remaining==1


@pytest.mark.asyncio
@pytest.mark.parametrize('correct',[True,False])
async def test_native_cancel_tool_uses_exact_job_and_no_image_retry(correct):
    from tests.contracts.test_image_operation_diagnostics import native_actor,image_turn
    from tests.contracts.test_luna_tool_actor import ToolTurn,wait_state
    from tests.contracts.test_development_review_composition import finish
    images=Images(blocked=True,ignore=False);vision=Vision()
    runtime=StoryImageRuntime(images,vision,Decoder(),StoryImageAdmission('offline',True,timeout_seconds=4,authorized_custom_brief=True))
    actor=native_actor(runtime,[image_turn('start')])
    try:
        await actor.submit(request_id='turn1',activity_seq=1,cutoff=0,text='想看看别的画面')
        state=await wait_state(actor,lambda s:s.story_image.state=='generating')
        while not images.arrived.is_set():await asyncio.sleep(.001)
        turn=ToolTurn(GenerationToolCall('cancel','cancel_story_image',json.dumps({'request_id':state.story_image.request_id if correct else str(uuid4())})))
        actor._tool_generation.turns.append(turn)
        await actor.submit(request_id='turn2',activity_seq=2,cutoff=0,text='别找这张了')
        await finish(actor);state=await actor.snapshot()
        assert 'cancel_story_image' in {t.name for t in actor._tool_generation.opens[-1][1]}
        assert state.story_image.state==('cancelled' if correct else 'generating')
        assert len(images.calls)==1 and not vision.calls and runtime.attempts==1
    finally:images.release.set();await actor.close()


def test_actual_audio_interruption_keeps_qualified_image_under_fresh_current_grant():
    app,images,vision,_,_=app_for(generation=Generation([candidate(speech=True)]),voice=True)
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=image_done(client,path,headers)
        old=next(e for e in state['active_grants'] if e['kind']=='media')
        speech=next(e for e in state['active_grants'] if e['kind']=='speech')
        body={k:speech[k] for k in ('digest','output_epoch','activity_seq')}
        body.update(effect_id=speech['id'],presentation_seq=1,sample_rate_hz=16000,rendered_samples=0,status='interrupted')
        response=client.post(path+'/audio-progress',headers=headers,json=body)
        assert response.status_code==200
        state=response.json();assert state['story_image']['state']=='qualified'
        current=next(e for e in state['active_grants'] if e['kind']=='media')
        assert current['id']!=old['id'] and current['value']==old['value']
        stale={k:old[k] for k in ('digest','output_epoch','activity_seq')}
        stale.update(effect_id=old['id'],presentation_seq=2)
        assert client.post(path+'/receipts',headers=headers,json=stale).status_code==409
        resource,grant=body_for(old)
        assert client.post(path+'/story-images/'+resource,headers=headers,json=grant).status_code==409
        resource,grant=body_for(current)
        assert client.post(path+'/story-images/'+resource,headers=headers,json=grant).status_code==200
        assert len(images.calls)==len(vision.calls)==1


@pytest.mark.parametrize("phase", ["pending", "generating", "reviewing", "qualified", "presented", "failed", "held", "cancelled"])
@pytest.mark.parametrize("fence", ["ordinary", "reply", "stop", "scope", "wrong_session"])
def test_history_retention_keeps_only_current_live_image_identity(phase, fence):
    from mira.domain import transitions
    from mira.domain.models import SessionState
    from mira.domain.story_images import ImageReservation, StoryImageStatus
    current=ImageReservation('job', 'origin', 1, 1, 0, 'spec', 'dependency', 'policy',
        session_id='session', current_effect_id='exact-current-grant')
    old=replace(current, request_id='replaced-job', parent_request_id='older-origin')
    state=replace(SessionState('session','code'),output_epoch=10,activity_seq=10,
        story_image=StoryImageStatus('bounded_fiction',phase,'job'),
        image_reservations=(old,current))
    if fence in ('reply','stop'):
        state=transitions.stop(state,activity_seq=11,cutoff=0,cancel_images=fence=='stop')
    elif fence=='scope':state=replace(state,image_cancellation_generation=1)
    elif fence=='wrong_session':state=replace(state,session_id='different-session')
    compacted=transitions.retain_recent_history(state)
    eligible=phase in ('pending','generating','reviewing','qualified') and fence in ('ordinary','reply')
    assert compacted.image_reservations == ((current,) if eligible else ())
    assert compacted.active_grants == state.active_grants
    assert compacted.story_image == state.story_image
