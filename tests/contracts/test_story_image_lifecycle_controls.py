"""Legacy presentation ordering and bounded image-intent controls; synthetic only."""
from dataclasses import replace
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.application.compiler import compile_generated_media, compile_range
from mira.application.contracts import CandidateRange, EffectProposal
from mira.application.decision_contracts import ReliableUserInput, mira26_author_policy, valid_snapshot
from mira.application.decision_runtime import DecisionSnapshotOwner
from mira.domain import transitions
from mira.domain.models import AudioProgress, AudioStatus, EffectKind, Receipt, SessionState
from tests.contracts.test_story_image_lifecycle_audit import (
    Images, Generation, app_for, actor_for, candidate, image_done, session, settled, submit, Wire,
)


def presentation_state(include_generated):
    state=transitions.begin_input(SessionState('s','c'),activity_seq=1,cutoff=0,request_id='turn',text='show')
    fixed,caption,speech=compile_range(CandidateRange((EffectProposal(EffectKind.MEDIA,'trip_photo'),
        EffectProposal(EffectKind.SUBTITLE,'Caption'),EffectProposal(EffectKind.SPEECH,'Speech')),'control'),epoch=1,activity=1)
    tail=(compile_generated_media(str(uuid4()),'a'*64,epoch=1,activity=1) if include_generated else
          compile_range(CandidateRange((EffectProposal(EffectKind.MEDIA,'trip_photo'),),'reshow'),epoch=1,activity=1)[0])
    state=transitions.accept_range(state,output_epoch=1,effects=(fixed,caption,speech,tail))
    for seq,effect in enumerate((tail,fixed,caption),1):
        state=transitions.record_receipt(state,Receipt(effect.id,effect.digest,1,1,seq))
    state=transitions.record_audio_progress(state,AudioProgress(speech.id,speech.digest,1,1,4,16000,16000,AudioStatus.COMPLETED))
    return state,(fixed,caption,speech,tail)


def test_mixed_photo_projection_preserves_caption_audio_positions_and_snapshot_binding():
    state,(fixed,caption,speech,generated)=presentation_state(True)
    assert state.presented_effects==(generated,caption,speech,fixed)
    assert state.issued_effects==(fixed,caption,speech,generated)
    snapshot=DecisionSnapshotOwner(mira26_author_policy()).snapshot(state,(ReliableUserInput('turn','show','text'),))
    assert snapshot is not None and valid_snapshot(snapshot)
    assert tuple(f.effect for f in snapshot.presentation_facts if f.status=='presented')==state.presented_effects


def test_fixed_only_legacy_caption_audio_and_photo_order_stays_unchanged():
    state,effects=presentation_state(False)
    assert state.presented_effects==effects
    assert [receipt.presentation_seq for receipt in state.receipts]==[1,2,3]
    assert state.audio_progress[0].presentation_seq==4


def test_rejected_intent_dedupes_within_input_but_is_reviewed_again_next_epoch():
    app,images,_,_,wire=app_for(wire=Wire('reject'),generation=Generation([candidate(),candidate()]))
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);settled(client,path,headers)
        submit(client,path,headers,activity=2);state=settled(client,path,headers)
        outputs=[request for request,_,_ in wire.calls if 'contract' in request['state']]
        assert len(outputs)==2 and not images.calls and state['last_error'] is None


def test_pending_request_identity_survives_intent_review_and_dispatch():
    wire=Wire(gate=True);images=Images(blocked=True);app,_,_,_,_=app_for(wire=wire,images=images)
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers)
        try:
            assert wire.arrived.wait(1)
            pending=client.get(path,headers=headers).json()['story_image']
            assert pending['state']=='pending' and pending['request_id'] is not None
            wire.resume.set();settled(client,path,headers);assert images.arrived.wait(1)
            assert images.calls[0].request_id==pending['request_id']
        finally:
            wire.resume.set();images.release.set()


@pytest.mark.parametrize('mode',['transport','invalid'])
def test_held_review_paths_terminate_pending_status_without_chat_failure(mode):
    app,images,_,_,_=app_for(wire=Wire(mode))
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);state=settled(client,path,headers)
        assert state['story_image']['state']=='held' and state['last_error'] is None and not images.calls


def test_invalid_duplicate_does_not_relabel_a_running_approved_image():
    images=Images(blocked=True)
    invalid=replace(candidate(),image_proposal_json=json.dumps({'prompt':'not allowed'}))
    app,_,_,_,wire=app_for(images=images,generation=Generation([candidate(),invalid]))
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers)
        try:
            state=settled(client,path,headers);assert images.arrived.wait(1)
            assert state['story_image']['state']=='generating'
            assert len([request for request,_,_ in wire.calls if 'contract' in request['state']])==1
        finally:images.release.set()


def test_mixed_photo_serialization_and_archive_replay_keep_exact_receipt_identity(tmp_path):
    from dataclasses import asdict
    from mira.application.contracts import generation_context_data
    from mira.application.interrupted_intent import AcceptedInput
    from mira.entrypoints.http.mappers import session_view
    from tests.contracts.test_conversation_archive import opened
    state,effects=presentation_state(True)
    original={receipt.effect_id:asdict(receipt) for receipt in state.receipts}
    view=session_view(state).model_dump(mode='json')
    assert [e['id'] for e in view['presented_effects']]==[e.id for e in state.presented_effects]
    archive=opened(tmp_path)
    try:
        archive.capture('s',(AcceptedInput('turn',1,'show','text',0),),state.issued_effects,state.receipts,state.audio_progress)
        snapshot=archive.load_session('s')
        persisted={row.payload()['effect']['id']:row.payload()['receipt']
                   for row in snapshot.records if row.stage=='presented_effect'}
        assert persisted==original
        replay=replace(state,receipts=tuple(Receipt(**data) for data in persisted.values()))
        assert replay.presented_effects==state.presented_effects and replay.issued_effects==effects
        for effect in replay.presented_effects:
            assert effect is next(item for item in effects if item.id==effect.id)
    finally:archive.close()


class OperationAdmission:
    def __init__(self,fail=False):self.events=[];self.fail=fail
    def reserve(self,request):
        self.events.append(('reserve',request.request_id))
        if self.fail:raise ValueError('synthetic_admission_reject')
    def release(self,request_id):self.events.append(('release',request_id))


def operation_runtime(images,vision,gate,decoder=None):
    from mira.application.story_images import StoryImageAdmission, StoryImageRuntime, compile_image_intent
    from mira.bootstrap.character_story import ephemeral_character_factory
    from mira.domain.story_images import ImageProposal
    from tests.contracts.test_story_image_lifecycle_audit import Decoder
    runtime=StoryImageRuntime(images,vision,decoder or Decoder(),StoryImageAdmission('control',True),
        operation_admission=gate)
    state=transitions.begin_input(SessionState('s','c'),activity_seq=1,cutoff=0,request_id='turn',text='show')
    runtime.bind_session('s')
    story=ephemeral_character_factory()(state).begin_input('turn',1)
    request=runtime.reserve(compile_image_intent(ImageProposal('cafe_rain_window'),story),state)
    return runtime,request


@pytest.mark.asyncio
async def test_operation_admission_rejection_calls_no_provider_and_does_not_release():
    from tests.contracts.test_story_image_lifecycle_audit import Vision
    gate=OperationAdmission(fail=True);images=Images();vision=Vision()
    runtime,request=operation_runtime(images,vision,gate)
    async def phase(_):return True
    with pytest.raises(ValueError,match='synthetic_admission_reject'):
        await runtime.generate_and_review(request,phase)
    assert not images.calls and not vision.calls and gate.events==[('reserve',request.request_id)]


@pytest.mark.asyncio
@pytest.mark.parametrize('terminal',['success','image_failure','decode_failure','review_failure'])
async def test_operation_admission_releases_once_after_every_terminal_path(terminal):
    from tests.contracts.test_story_image_lifecycle_audit import Vision, Decoder
    gate=OperationAdmission()
    class Image(Images):
        async def generate(self,request):
            assert gate.events==[('reserve',request.request_id)]
            if terminal=='image_failure':raise ValueError('synthetic_image_failure')
            return await super().generate(request)
    class Decode(Decoder):
        def canonicalize(self,data):
            if terminal=='decode_failure':raise ValueError('synthetic_decode_failure')
            return super().canonicalize(data)
    class Review(Vision):
        async def review(self,artifact,request):
            if terminal=='review_failure':raise ValueError('synthetic_review_failure')
            return await super().review(artifact,request)
    runtime,request=operation_runtime(Image(),Review(),gate,Decode())
    async def phase(_):return True
    if terminal=='success':await runtime.generate_and_review(request,phase)
    else:
        with pytest.raises(ValueError):await runtime.generate_and_review(request,phase)
    assert gate.events==[('reserve',request.request_id),('release',request.request_id)]


@pytest.mark.asyncio
@pytest.mark.parametrize('stage',['image','vision'])
async def test_operation_admission_waits_for_cancellation_ignoring_backend_to_settle(stage):
    import asyncio
    from tests.contracts.test_story_image_lifecycle_audit import Vision
    arrived=asyncio.Event();cancelled=asyncio.Event();resume=asyncio.Event()
    gate=OperationAdmission()
    async def blocked():
        arrived.set()
        try:await resume.wait()
        except asyncio.CancelledError:
            cancelled.set();await resume.wait()
    class Image(Images):
        async def generate(self,request):
            if stage=='image':await blocked()
            return await super().generate(request)
    class Review(Vision):
        async def review(self,artifact,request):
            if stage=='vision':await blocked()
            return await super().review(artifact,request)
    runtime,request=operation_runtime(Image(),Review(),gate)
    async def phase(_):return True
    task=asyncio.create_task(runtime.generate_and_review(request,phase))
    await asyncio.wait_for(arrived.wait(),1);task.cancel();await asyncio.wait_for(cancelled.wait(),1)
    assert gate.events==[('reserve',request.request_id)] and not task.done()
    resume.set();await asyncio.wait_for(task,1)
    assert gate.events==[('reserve',request.request_id),('release',request.request_id)]


def test_late_old_intent_review_error_cannot_hold_new_epoch_pending_image():
    import asyncio
    import threading
    app,_,_,_,_=app_for()
    old_arrived=threading.Event();old_release=threading.Event()
    new_arrived=threading.Event();new_release=threading.Event()
    with TestClient(app) as client:
        path,headers=session(client)
        state=client.get(path,headers=headers).json();actor=actor_for(app,state,headers)
        original=actor._semantic_review.review
        async def delayed(snapshot,candidate,observation,**kwargs):
            arrived,release=(old_arrived,old_release) if snapshot.context.output_epoch==1 else (new_arrived,new_release)
            arrived.set()
            while not release.is_set():
                try:await asyncio.sleep(.002)
                except asyncio.CancelledError:pass
            if snapshot.context.output_epoch==1:raise OSError('synthetic_late_review_error')
            return await original(snapshot,candidate,observation,**kwargs)
        actor._semantic_review.review=delayed
        try:
            submit(client,path,headers);assert old_arrived.wait(1)
            submit(client,path,headers,activity=2)
            old_release.set();assert new_arrived.wait(1)
            state=client.get(path,headers=headers).json()
            assert state['output_epoch']==2 and state['story_image']['state']=='pending'
        finally:old_release.set();new_release.set()
