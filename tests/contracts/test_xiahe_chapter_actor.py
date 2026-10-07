"""Compiled-effect bridge and synthetic checkpoint compatibility for WP13."""
from dataclasses import replace
import hashlib
import json
import sqlite3
import pytest

from mira.application.actor_story import SessionCharacterRuntime
from mira.application.compiler import compile_range
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext, generation_context_data
from mira.application.story import StoryRuntime
from mira.adapters.memory.story import StoryCheckpointStore
from mira.bootstrap.character_story import builtin_definition
from mira.domain.models import EffectKind, Receipt
from mira.domain.story import (CapabilityRecord, CapabilityState, ReadinessCatalog,
    StoryNode, PROPOSAL_SIGNAL_BY_TRANSITION, valid_story_projection)
from mira.domain.xiahe_chapter import (CHAPTER_SCENES, CHAPTER_CAPABILITIES, CHAPTER_ASSETS,
    CHAPTER_REVISION, ChapterStage, chapter_projection)


def character(*, ready=True):
    catalog=ReadinessCatalog('synthetic-chapter',tuple(CapabilityRecord(cap,
        CapabilityState.READY if ready else CapabilityState.UNAVAILABLE,
        CHAPTER_REVISION if ready else None,(CHAPTER_ASSETS[value],) if ready else (),
        'synthetic-source-check') for value,cap in CHAPTER_CAPABILITIES.items()))
    return SessionCharacterRuntime(StoryRuntime(builtin_definition(),'synthetic-xiahe-scope'),catalog)


def prepare(c, transition, epoch, text='继续说吧', *, act=None, offer=None):
    projection=c.begin_input('input.'+str(epoch),epoch)
    context=GenerationContext(text,(text,),(),epoch,character_story=projection,character_assets=c.readiness)
    proposal={'transition_id':transition,'signal':PROPOSAL_SIGNAL_BY_TRANSITION[transition].value}
    if transition in CHAPTER_SCENES:proposal['target_capabilities']=[CHAPTER_CAPABILITIES[CHAPTER_SCENES[transition]]]
    if act:proposal['input_act']={'kind':act,'evidence_text':text,'role_name':'夏禾'}
    if offer:proposal['offer_id']=offer
    cue='当轮合成剧情台词'+str(epoch)
    if transition in {'x.story','x.promise'}:proposal['draft_cue']=cue
    candidate=CandidateRange((EffectProposal(EffectKind.SUBTITLE,cue),),'synthetic-chapter',
        story_proposal_json=json.dumps(proposal,ensure_ascii=False))
    candidate=c.prepare_candidate(context,candidate,'input.'+str(epoch))
    effects=compile_range(candidate,epoch=epoch,activity=epoch)
    update=c.prepare_local_chapter_accept(context,candidate,effects,'input.'+str(epoch))
    c.commit(update)
    return context,update.admitted_effects


def complete(c,effects,start=1):
    for seq,effect in enumerate(effects,start):
        c.acknowledge(Receipt(effect.id,effect.digest,effect.output_epoch,effect.activity_seq,seq),effect)


def advance_to_gift(c):
    _context,effects=prepare(c,'x.recognize',1,'我是夏禾，好久不见，你还记得我吗？',act='claim_role')
    assert not c.runtime.story.chapter.role_active
    complete(c,effects)
    for n,transition in enumerate(('x.story','x.story','x.story','x.promise'),2):
        old=c.runtime.story.chapter.milestones
        context,effects=prepare(c,transition,n)
        assert c.runtime.story.chapter.milestones==old
        assert valid_story_projection(context.character_story)
        assert generation_context_data(context)['character_story']['chapter']==chapter_projection(context.character_story.chapter)
        complete(c,effects,2*n)
    # Existing show_photo effect must actually complete. A generated sentence or
    # a chapter promise cannot substitute for this media receipt.
    c.begin_input('input.6',6)
    photo=compile_range(CandidateRange((EffectProposal(EffectKind.MEDIA,'trip_photo'),),'synthetic-photo'),epoch=6,activity=6)[0]
    complete(c,(photo,),12)
    assert c.runtime.story.chapter.stage is ChapterStage.PREVIEWED
    _context,effects=prepare(c,'x.gift_offer',7,offer='offer.synthetic')
    complete(c,effects,14)
    return photo


def test_bridge_completes_only_after_distinct_handover_ack_and_same_version_context():
    c=character();advance_to_gift(c)
    assert c.runtime.story.chapter.stage is ChapterStage.GIFT_OFFERED
    context,effects=prepare(c,'x.gift_accept',8,'我收下这张照片',act='accept_gift',offer='offer.synthetic')
    assert c.runtime.story.chapter.stage is ChapterStage.GIFT_OFFERED
    handover=next(e for e in effects if e.kind is EffectKind.SCENE)
    complete(c,(handover,),16)
    story=c.runtime.story
    assert story.chapter.stage is ChapterStage.COMPLETED
    assert len(story.chapter.milestones)==8
    assert json.loads(c.runtime.project().canonical_json)['last_acknowledged_scene'] is None
    assert story.current_outfit=='black_jacket'
    complete(c,(handover,),16)
    assert c.runtime.story==story
    assert all(dict(e.character_state).get('history_scope')=='fictional_software_presentation' for e in story.episodes)


def test_missing_scene_resource_stays_visible_text_and_does_not_recognize():
    c=character(ready=False)
    _,effects=prepare(c,'x.recognize',1,'我是夏禾',act='claim_role')
    assert effects and all(e.kind is EffectKind.SUBTITLE for e in effects)
    complete(c,effects)
    assert not c.runtime.story.chapter.role_active and not c.runtime.story.chapter.milestones


def test_stop_late_receipt_is_history_only_correction_preserves_provenance():
    c=character();_,effects=prepare(c,'x.recognize',1,'我是夏禾',act='claim_role')
    scene=next(e for e in effects if e.kind is EffectKind.SCENE)
    c.stop(2)
    complete(c,(scene,))
    assert not c.runtime.story.chapter.role_active
    assert dict(c.runtime.story.episodes[-1].character_state)['reconciliation']=='late_pre_fence_no_chapter_advance'
    _,effects=prepare(c,'x.recognize',3,'我是夏禾',act='claim_role');complete(c,effects,3)
    history=c.runtime.story.episodes
    _,effects=prepare(c,'x.exit',4,'我不是夏禾，别把我当成她。',act='exit_role')
    assert not c.runtime.story.chapter.role_active
    assert c.runtime.story.episodes==history
    assert c.runtime.story.scope_id=='synthetic-xiahe-scope'


@pytest.mark.parametrize('schema',[3,4,5])
def test_old_four_node_checkpoint_reads_explicitly_without_disk_mutation(tmp_path,schema):
    c=character();d=c.runtime.definition
    private=tmp_path/'private';private.mkdir(mode=0o700)
    path=private/'synthetic.sqlite3'
    store=StoryCheckpointStore(path,enabled=True,explicitly_authorized=True,authorized_scope_id=c.runtime.story.scope_id)
    state=replace(c.runtime.story,node=StoryNode.RAIN_VIEW,current_outfit='amber_raincoat',revision=7)
    store.save(state,c.runtime.affect)
    with sqlite3.connect(path) as db:
        payload=json.loads(db.execute('select story_json from story_checkpoint').fetchone()[0]);payload.pop('chapter')
        db.execute('update story_checkpoint set schema_version=?,story_json=?',(schema,json.dumps(payload)))
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    loaded,_=store.load(state.scope_id,state.story_id,graph_id=d.graph.graph_id,graph_revision=d.graph.revision,
        canon_revision=d.canon.revision,graph_hash=d.graph.content_hash,canon_hash=d.canon.content_hash)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    assert loaded.node is StoryNode.RAIN_VIEW and loaded.current_outfit=='amber_raincoat'
    assert loaded.chapter.compatibility=='legacy_story_schema_'+str(schema)
    assert loaded.chapter.stage is ChapterStage.STRANGER


def test_save_resume_keeps_qualified_finite_history_but_requires_fresh_role(tmp_path):
    c=character();advance_to_gift(c)
    snapshot=c.runtime.snapshot()
    resumed=StoryRuntime.from_snapshot(c.runtime.definition,snapshot)
    assert not resumed.story.chapter.role_active
    assert resumed.story.chapter.stage is ChapterStage.PREVIEWED
    assert resumed.story.chapter.active_gift_offer_id is None
    assert resumed.story.episodes==snapshot.story.episodes
    assert resumed.story.chapter.milestones==snapshot.story.chapter.milestones


def test_explicit_gift_button_compiles_without_generation_guess_and_rejects_stale_identity():
    c=character();advance_to_gift(c)
    current=c.runtime.story.chapter
    args=dict(offer_id=current.active_gift_offer_id,offer_effect_id=current.gift_offer_effect_id,
        offer_effect_digest=current.gift_offer_effect_digest)
    candidate=c.choice_candidate(choice='accept',input_id='button.input',epoch=8,**args)
    text='我收下这张照片'
    p=c.begin_input('button.input',8)
    context=GenerationContext(text,(text,),(),8,character_story=p,character_assets=c.readiness)
    candidate=c.prepare_candidate(context,candidate,'button.input')
    effects=compile_range(candidate,epoch=8,activity=8)
    update=c.prepare_local_chapter_accept(context,candidate,effects,'button.input');c.commit(update)
    assert c.runtime.story.chapter.stage is ChapterStage.GIFT_OFFERED
    complete(c,update.admitted_effects,16)
    assert c.runtime.story.chapter.stage is ChapterStage.COMPLETED
    with pytest.raises(Exception,match='no longer current'):
        c.choice_candidate(choice='accept',input_id='button.retry',epoch=9,**args)


def rain_turn(c,transition,epoch,*,target='wardrobe',refuse=False,reopen=False,text='合成看雨请求'):
    from mira.application.contracts import ReviewObservation,ReviewVerdict,CharacterSemanticEvidence,CharacterSemanticValue as V
    from mira.application.decision_contracts import evidence_digest
    projection=c.begin_input('rain.'+str(epoch),epoch)
    context=GenerationContext(text,(text,),(),epoch,character_story=projection,character_assets=c.readiness)
    cue='合成看雨邀请'+str(epoch)
    proposal={'transition_id':transition,'signal':PROPOSAL_SIGNAL_BY_TRANSITION[transition].value}
    effects=[EffectProposal(EffectKind.SUBTITLE,cue)]
    if transition=='t.offer':
        proposal.update(offer_id='rain.offer.'+str(epoch),draft_cue=cue)
        if target=='window':proposal['target_capabilities']=['cafe.scene.rain_window']
    elif transition in {'t.yes','t.window'}:
        proposal['offer_id']=projection.active_offer_id
        proposal['target_capabilities']=['mira.outfit.amber_raincoat' if transition=='t.yes' else 'cafe.scene.rain_window']
        if transition=='t.window':effects.append(EffectProposal(EffectKind.SCENE,'rain_window'))
    if reopen:
        proposal['reopen_offer']=True
        proposal['input_act']={'kind':'reopen_rain','evidence_text':text,'role_name':'夏禾'}
    candidate=CandidateRange(tuple(effects),'synthetic-rain',story_proposal_json=json.dumps(proposal,ensure_ascii=False))
    candidate=c.prepare_candidate(context,candidate,'rain.'+str(epoch))
    effects=compile_range(candidate,epoch=epoch,activity=epoch)
    review=ReviewObservation(ReviewVerdict.ALLOW,'synthetic',character_evidence=CharacterSemanticEvidence(
        evidence_digest(context),evidence_digest(candidate),relevance=V.YES,willingness=V.NO if refuse else V.YES,
        refusal=V.YES if refuse else V.NO))
    update=c.prepare_accept(context,candidate,review,effects,'rain.'+str(epoch),hold_optional_failures=True)
    c.commit(update)
    return update.admitted_effects


def rain_character():
    c=character()
    c.readiness=ReadinessCatalog('synthetic-rain-and-chapter',c.readiness.records+(
        CapabilityRecord('cafe.scene.rain_window',CapabilityState.READY,'scene-v1',('scene.rain_window.composition',),'synthetic'),
        CapabilityRecord('mira.outfit.amber_raincoat',CapabilityState.READY,'outfit-v1',('outer.amber','inner.cream'),'synthetic')))
    return c


@pytest.mark.parametrize('order',[('wardrobe','window'),('window','wardrobe')])
def test_optional_rain_paths_can_run_in_either_order(order):
    c=rain_character();epoch=1
    for branch in order:
        effects=rain_turn(c,'t.offer',epoch,target=branch);complete(c,effects,epoch*3)
        assert c.runtime.story.node is StoryNode.AWAIT_RAIN_CHOICE
        effects=rain_turn(c,'t.yes' if branch=='wardrobe' else 't.window',epoch+1)
        complete(c,effects,epoch*3+1)
        assert c.runtime.story.node is StoryNode.RAIN_VIEW
        epoch+=2
    assert c.runtime.story.current_outfit=='amber_raincoat'
    assert json.loads(c.runtime.project().canonical_json)['last_acknowledged_scene']=='rain_window'
    assert c.runtime.story.chapter.stage is ChapterStage.STRANGER


def test_actor_bridge_passes_only_current_explicit_reopen_after_decline():
    from mira.domain.story import OfferStatus
    c=rain_character()
    complete(c,rain_turn(c,'t.offer',1,target='window'))
    rain_turn(c,'t.chat',2,refuse=True)
    assert c.runtime.story.offer_status is OfferStatus.DECLINED
    effects=rain_turn(c,'t.offer',3,target='window')
    complete(c,effects,4)
    assert c.runtime.story.node is StoryNode.CAFE_CHAT
    effects=rain_turn(c,'t.offer',4,target='window',reopen=True,text='如果现在想去窗边呢')
    complete(c,effects,5)
    assert c.runtime.story.node is StoryNode.CAFE_CHAT
    effects=rain_turn(c,'t.offer',5,target='window',reopen=True,text='现在想去窗边')
    complete(c,effects,6)
    assert c.runtime.story.node is StoryNode.AWAIT_RAIN_CHOICE


def test_stop_revokes_a_presented_gift_offer_then_explicit_reopen_is_possible():
    c=character();advance_to_gift(c)
    offer=c.runtime.story.chapter
    c.stop(8)
    with pytest.raises(Exception,match='no longer current'):
        c.choice_candidate('accept',offer.active_gift_offer_id,offer.gift_offer_effect_id,
            offer.gift_offer_effect_digest,input_id='button.stale',epoch=9)
    assert c.runtime.story.chapter.stage is ChapterStage.PREVIEWED
    assert c.runtime.story.chapter.milestones==offer.milestones
    _,effects=prepare(c,'x.gift_offer',9,'现在我想收下这张照片',act='reopen_gift',offer='offer.reopened')
    complete(c,effects,20)
    assert c.runtime.story.chapter.active_gift_offer_id=='offer.reopened'


def test_dormant_chapter_preserves_legacy_model_wire_and_authored_dialogue_has_no_setup_jargon():
    from mira.domain.xiahe_chapter import CHAPTER_CANON,CHAPTER_SOURCE_HASH
    from importlib.resources import files
    c=character()
    projection=c.runtime.project().projection
    assert valid_story_projection(projection)
    assert 'chapter' not in json.loads(projection.context_json)
    artifact=json.loads(files('mira.adapters.story').joinpath('assets/xiahe-chapter.v1.json').read_text())
    assert artifact['source_hash']==CHAPTER_SOURCE_HASH
    for row,(_,source,text) in zip(artifact['canon'],CHAPTER_CANON):
        assert row['source_id']==source and row['text']==text
        assert not any(word in text for word in ('扮演','设定','模型','系统','真实用户'))


@pytest.mark.parametrize('complete_handover',[False,True])
def test_new_checkpoint_roundtrip_preserves_chapter_receipts_without_replaying_pending(tmp_path,complete_handover):
    c=character();advance_to_gift(c)
    _,effects=prepare(c,'x.gift_accept',8,'我收下这张照片',act='accept_gift',offer='offer.synthetic')
    if complete_handover:complete(c,effects,16)
    private=tmp_path/'chapter-private';private.mkdir(mode=0o700)
    path=private/'chapter.sqlite3'
    store=StoryCheckpointStore(path,enabled=True,explicitly_authorized=True,authorized_scope_id=c.runtime.story.scope_id)
    c.runtime.save_explicitly(store);d=c.runtime.definition
    story,affect=store.load(c.runtime.story.scope_id,c.runtime.story.story_id,graph_id=d.graph.graph_id,
        graph_revision=d.graph.revision,canon_revision=d.canon.revision,graph_hash=d.graph.content_hash,canon_hash=d.canon.content_hash)
    assert story==c.runtime.story and affect==c.runtime.affect
    snapshot=replace(c.runtime.snapshot(),story=story,affect=affect)
    resumed=StoryRuntime.from_snapshot(d,snapshot)
    assert resumed.story.chapter.pending is None and not resumed.story.chapter.role_active
    assert resumed.story.episodes==story.episodes and resumed.story.receipt_ids==story.receipt_ids
    assert resumed.story.chapter.stage is (ChapterStage.COMPLETED if complete_handover else ChapterStage.PREVIEWED)
    assert resumed.story.chapter.active_gift_offer_id is None
    with sqlite3.connect(path) as db:
        assert db.execute('select schema_version from story_checkpoint').fetchone()[0]==6
        assert db.execute('select count(*) from story_qualified_episode').fetchone()[0]==len(story.episodes)
        raw=db.execute('select story_json from story_checkpoint').fetchone()[0]
        assert 'evidence_text' not in raw and '我收下这张照片' not in raw


def test_explicit_visible_photo_reuse_unlocks_preview_without_fabricating_new_presentation():
    c=character()
    photo=compile_range(CandidateRange((EffectProposal(EffectKind.MEDIA,'trip_photo'),),'early-photo'),epoch=0,activity=1)[0]
    receipt=Receipt(photo.id,photo.digest,0,1,1)
    _,effects=prepare(c,'x.recognize',1,'我是夏禾',act='claim_role');complete(c,effects,2)
    for epoch,transition in enumerate(('x.story','x.story','x.story','x.promise'),2):
        _,effects=prepare(c,transition,epoch);complete(c,effects,epoch+2)
    before=c.runtime.story
    c.begin_input('explicit.photo.reuse',6)
    assert not c.reconcile_visible_preview(photo,receipt,'explicit.photo.reuse',6,visible=False)
    assert not c.reconcile_visible_preview(photo,replace(receipt,digest='b'*64),'explicit.photo.reuse',6,visible=True)
    assert c.reconcile_visible_preview(photo,receipt,'explicit.photo.reuse',6,visible=True)
    after=c.runtime.story
    assert after.chapter.stage is ChapterStage.PREVIEWED
    assert after.episodes==before.episodes and after.receipt_ids==before.receipt_ids
    assert after.chapter.preview_reference.mode=='reused_visible'
    assert after.chapter.preview_reference.output_epoch==0
    assert dict(after.chapter.milestones)['photo_preview']=='visual.'+photo.id+'.1'
    assert not c.reconcile_visible_preview(photo,receipt,'explicit.photo.reuse',6,visible=True)
    assert c.runtime.story==after
    _,effects=prepare(c,'x.gift_offer',7,offer='offer.after_reuse');complete(c,effects,20)
    assert c.runtime.story.chapter.stage is ChapterStage.GIFT_OFFERED
