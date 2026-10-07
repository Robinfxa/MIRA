"""Photo-only outcome feedback; no provider, image generator, or user database."""
from dataclasses import replace
import pytest
from mira.application.contracts import generation_context_data
from mira.domain.models import EffectKind
from mira.domain.story import ReadinessCatalog
from tests.contracts.test_authored_photo_events import actor, turn, receipt

class Sink:
    def __init__(self): self.events=[]
    def emit(self,event): self.events.append(event)

@pytest.mark.asyncio
@pytest.mark.parametrize('mode,expected,reason', [('allow','granted',None),('unknown','held','review_unknown'),('reject','held','review_rejected')])
async def test_typed_photo_attempt_has_closed_nonfatal_status(mode,expected,reason):
    value,_,_=actor([('media','trip_photo')],mode)
    try:
        state=await turn(value,1)
        status=getattr(state,'fixed_photo',None)
        assert status is not None, 'typed fixed-photo attempt needs outcome feedback'
        assert (status.state,status.reason)==(expected,reason)
        assert not state.presented_effects and state.last_error is None and state.sealed
        assert any(e.kind is EffectKind.SUBTITLE for e in state.active_grants)
    finally: await value.close()

@pytest.mark.asyncio
async def test_prose_without_proposal_is_diagnostic_only_and_unavailable_is_distinct():
    for events,catalog,count,expected in [([],None,0,'idle'),([('media','trip_photo')],ReadinessCatalog('empty'),1,'held')]:
        value,_,_=actor(events,catalog=catalog);sink=Sink();value._diagnostics=sink
        try:
            state=await turn(value,1)
            status=getattr(state,'fixed_photo',None)
            assert status is not None
            assert status.state==expected
            if count: assert status.reason=='unavailable'
            facts=[getattr(e,'fixed_photo',None) for e in sink.events]
            assert any(f and f.phase=='candidate' and f.fixed_photo_count==count for f in facts)
            assert not any(e.kind is EffectKind.MEDIA for e in state.active_grants)
        finally: await value.close()

@pytest.mark.asyncio
async def test_failure_is_exact_nonfatal_and_shared_by_next_generation_and_review():
    value,generation,wire=actor([('media','trip_photo')])
    try:
        state=await turn(value,1);photo=next(e for e in state.active_grants if e.kind is EffectKind.MEDIA)
        assert hasattr(value,'fixed_photo_progress'), 'frontend failure must reach existing session owner'
        progress=dict(effect_id=photo.id,digest=photo.digest,output_epoch=photo.output_epoch,activity_seq=photo.activity_seq)
        await value.fixed_photo_progress(**progress,outcome='preparing')
        failed=await value.fixed_photo_progress(**progress,outcome='preparation_failed')
        assert failed.fixed_photo.state=='failed' and failed.fixed_photo.reason=='preparation_failed'
        assert failed.last_error is None and not failed.presented_effects
        generation.events=[('pose','camera_raise')]
        await turn(value,2)
        generated=generation_context_data(generation.contexts[-1])['authored_visual_events']['trip_photo']
        reviewed=[c[0]['state']['context']['authored_visual_events']['trip_photo'] for c in wire.calls if 'contract' in c[0]['state']][-1]
        assert generated==reviewed
        assert generated['latest_attempt']['state']=='failed' and generated['presented'] is False
        current=await value.snapshot()
        assert await value.fixed_photo_progress(**progress,outcome='presentation_failed')==current
    finally: await value.close()

@pytest.mark.asyncio
async def test_receipt_pending_is_not_failure_and_receipt_dismissal_history_wins():
    value,_,_=actor([('media','trip_photo')])
    try:
        state=await turn(value,1);photo=next(e for e in state.active_grants if e.kind is EffectKind.MEDIA)
        assert hasattr(value,'fixed_photo_progress')
        p=dict(effect_id=photo.id,digest=photo.digest,output_epoch=photo.output_epoch,activity_seq=photo.activity_seq)
        pending=await value.fixed_photo_progress(**p,outcome='receipt_pending')
        assert pending.fixed_photo.state=='receipt_pending' and not pending.presented_effects
        shown=await value.receipt(receipt(photo,1))
        assert shown.fixed_photo.state=='presented' and shown.photo_visible
        assert await value.fixed_photo_progress(**p,outcome='presentation_failed')==shown
        dismissed=await value.dismiss_photo(request_id='dismiss',expected_revision=0,cutoff=1)
        assert dismissed.fixed_photo.state=='dismissed' and not dismissed.photo_visible
        assert dismissed.presented_effects==shown.presented_effects
        assert await value.fixed_photo_progress(**p,outcome='preparing')==dismissed
        assert await value.receipt(receipt(photo,1))==dismissed
        next_state=await turn(value,2,1)
        assert next_state.fixed_photo.state=='granted'
        assert await value.receipt(receipt(photo,1))==next_state
    finally: await value.close()

@pytest.mark.asyncio
async def test_stop_and_new_attempt_reject_old_progress():
    value,_,_=actor([('media','trip_photo')])
    try:
        state=await turn(value,1);photo=next(e for e in state.active_grants if e.kind is EffectKind.MEDIA)
        assert hasattr(value,'fixed_photo_progress')
        stopped=await value.stop(activity_seq=2,cutoff=0)
        assert stopped.fixed_photo.state=='cancelled'
        newer=await turn(value,3)
        assert newer.fixed_photo.state=='granted' and newer.fixed_photo.attempt_seq==2
        assert await value.fixed_photo_progress(effect_id=photo.id,digest=photo.digest,output_epoch=photo.output_epoch,activity_seq=photo.activity_seq,outcome='presentation_failed')==newer
        assert not newer.presented_effects
    finally: await value.close()

@pytest.mark.asyncio
async def test_fixed_photo_metadata_roundtrip_export_has_no_candidate_text(tmp_path):
    import json,zipfile
    from mira.adapters.diagnostics.privacy import encode_event,validate_event_record
    from mira.adapters.diagnostics.export import export_diagnostics
    value,_,_=actor([('media','trip_photo')],'unknown');sink=Sink();value._diagnostics=sink
    try:
        await turn(value,1)
        records=[encode_event(e,1) for e in sink.events if getattr(e,'fixed_photo',None)]
        assert records and all(validate_event_record(r)==r for r in records)
        root=tmp_path/'logs';(root/'events').mkdir(parents=True)
        (root/'events'/'events-photo.jsonl').write_text('\n'.join(json.dumps(r) for r in records)+'\n')
        output=tmp_path/'photo.zip';manifest=export_diagnostics(root,output)
        assert manifest['event_count']==len(records) and not manifest['raw_included']
        with zipfile.ZipFile(output) as bundle:
            data=bundle.read('events.jsonl').decode()
        assert '原创海岸' not in data and '请展示' not in data and 'authored-synthetic' not in data
        assert 'review_unknown' in data and 'fixed_photo_count' in data
        hostile=json.loads(json.dumps(records[0]));hostile['fixed_photo']['caption']='private text'
        with pytest.raises(ValueError):validate_event_record(hostile)
        for field,bad_value in [('phase','https://private.invalid'),('reason','raw-secret'),('media_count',True),('pose_count',9)]:
            hostile=json.loads(json.dumps(records[0]));hostile['fixed_photo'][field]=bad_value
            with pytest.raises(ValueError):validate_event_record(hostile)
    finally:await value.close()

@pytest.mark.parametrize('mode',['transport','invalid'])
def test_review_failure_keeps_text_and_exposes_fixed_photo_hold(mode):
    from fastapi.testclient import TestClient
    from tests.contracts.test_response_preference import app_for
    from tests.contracts.test_conversation_first import Generation,Wire,session,settled,submit
    with TestClient(app_for(Generation([('subtitle','ordinary prose'),('media','trip_photo')]),Wire(mode))) as client:
        path,headers=session(client);submit(client,path,headers)
        state=settled(client,path,headers)
        assert state['fixed_photo']['state']=='held'
        assert state['fixed_photo']['reason']=='review_failed'
        assert [e['kind'] for e in state['active_grants']]==['subtitle']
        assert state['last_error'] is None and not state['presented_effects']


def test_authenticated_http_progress_is_closed_and_exact_grant_bound():
    from fastapi.testclient import TestClient
    from tests.contracts.test_response_preference import app_for
    from tests.contracts.test_conversation_first import Generation,Wire,session,settled,submit
    from uuid import uuid4
    with TestClient(app_for(Generation([('subtitle','ordinary prose'),('media','trip_photo')]),Wire())) as client:
        path,headers=session(client);submit(client,path,headers)
        state=settled(client,path,headers);photo=next(e for e in state['active_grants'] if e['kind']=='media')
        body={'effect_id':photo['id'],'digest':photo['digest'],'output_epoch':photo['output_epoch'],'activity_seq':photo['activity_seq'],'outcome':'preparing'}
        assert client.post(path+'/fixed-photo-progress',json=body).status_code==422
        assert client.post(path+'/fixed-photo-progress',json=body,headers={'X-Mira-Session-Token':'wrong'}).status_code==404
        for patch in ({'outcome':'presented'},{'raw_error':'private'},{'activity_seq':True},{'digest':'wrong'}):
            assert client.post(path+'/fixed-photo-progress',json=body|patch,headers=headers).status_code==422
        for patch in ({'effect_id':str(uuid4())},{'digest':'0'*64},{'output_epoch':0},{'activity_seq':0}):
            result=client.post(path+'/fixed-photo-progress',json=body|patch,headers=headers)
            assert result.status_code==200 and result.json()['fixed_photo']==state['fixed_photo']
        result=client.post(path+'/fixed-photo-progress',json=body|{'outcome':'preparation_failed'},headers=headers)
        assert result.status_code==200 and result.json()['fixed_photo']['state']=='failed'
        assert result.json()['last_error'] is None and not result.json()['presented_effects']
        assert client.post(path+'/fixed-photo-progress',json=body,headers=headers).json()['fixed_photo']['state']=='failed'

@pytest.mark.asyncio
async def test_new_late_receipt_resolves_latest_attempt_under_existing_stop_fence():
    value,_,_=actor([('media','trip_photo')])
    try:
        state=await turn(value,1);photo=next(e for e in state.active_grants if e.kind is EffectKind.MEDIA)
        await value.fixed_photo_progress(effect_id=photo.id,digest=photo.digest,
            output_epoch=photo.output_epoch,activity_seq=photo.activity_seq,outcome='receipt_pending')
        stopped=await value.stop(activity_seq=2,cutoff=1)
        assert stopped.fixed_photo.state=='receipt_pending' and not stopped.presented_effects
        saved=await value.receipt(receipt(photo,1))
        assert saved.fixed_photo.state=='presented' and photo in saved.presented_effects
        assert await value.receipt(receipt(photo,1))==saved
    finally:await value.close()
