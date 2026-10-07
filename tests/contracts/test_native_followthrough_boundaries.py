"""Additional authority and production-consumer boundaries for refusal recovery."""
import json
from dataclasses import replace
import pytest

from mira.application.story import StoryRuntime
from mira.domain.models import EffectKind
from mira.domain.errors import DomainError
from mira.domain.xiahe_chapter import ChapterStage, NativeChapterAct, stage_chapter, chapter_projection
from tests.contracts.test_native_photo_handover_flow import Flow
from tests.contracts.test_native_character_tools import story_call
from tests.contracts.test_native_followthrough import declined, reconsider, RECONSIDER
from tests.contracts.test_authored_photo_events import receipt


@pytest.mark.asyncio
async def test_declined_identity_and_new_typed_act_reach_production_selection_request():
    s=Flow()
    try:
        original=await declined(s)
        await s.say(RECONSIDER,reconsider(original))
        body=json.loads(s.requests[-2].content)
        packet=json.loads(body['input'][-1]['content'][0]['text'])
        chapter=packet['facts']['character_story']['chapter']
        assert packet['native_tool_contract']['chapter_source']=='facts.character_story.chapter'
        assert chapter['declined_gift_offer']['offer_id']=='gift'
        assert chapter['declined_gift_offer']['effect_id']==original.gift_offer_effect_id
        assert chapter['declined_gift_offer']['effect_digest']==original.gift_offer_effect_digest
        assert chapter['declined_gift_offer']['receipt_id']==dict(original.milestones)['gift_offer']
        assert chapter['allowed_next'].count('x.gift_accept')==1
        definition=next(t for t in body['tools'] if t['name']=='advance_story')
        assert 'reopen_accept_gift' in definition['parameters']['properties']['input_act']['enum']
        assert 'reference_effect_id' in definition['description']
        assert 'current user clearly reconsiders AND accepts' in definition['description']
        assert 'hypothetical' in definition['description'] and 'negation' in definition['description']
        assert chapter['active_gift_offer_id'] is None and not chapter['completed']
    finally: await s.close()


@pytest.mark.asyncio
async def test_reply_interruption_keeps_declined_offer_but_checkpoint_reentry_drops_authority():
    s=Flow()
    try:
        original=await declined(s);chapter=s.c.runtime.story.chapter
        saved=s.c.runtime.snapshot()
        restored=StoryRuntime.from_snapshot(s.c.runtime.definition,saved)
        assert restored.story.chapter.milestones==chapter.milestones
        assert restored.story.chapter.declined_gift_offer is None
        assert restored.story.chapter.active_gift_offer_id is None
        assert not restored.story.chapter.role_active and restored.story.chapter.suspended
        s.epoch+=1;await s.a.stop(activity_seq=s.epoch,cutoff=s.seq,scope='reply')
        assert s.c.runtime.story.chapter.declined_gift_offer==chapter.declined_gift_offer
        r,_=await s.say(RECONSIDER,reconsider(original))
        assert r['status']=='shown' and s.c.runtime.story.chapter.stage is ChapterStage.COMPLETED
    finally: await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('alter',['receipt','role','reference','input','epoch'])
async def test_domain_reconsideration_requires_exact_current_authority(alter):
    s=Flow()
    try:
        original=await declined(s);chapter=s.c.runtime.story.chapter
        act=NativeChapterAct('reopen_accept_gift',RECONSIDER,'current',4,original.gift_offer_effect_id)
        if alter=='receipt':chapter=replace(chapter,milestones=tuple((k,'stale-receipt' if k=='gift_offer' else v) for k,v in chapter.milestones))
        elif alter=='role':chapter=replace(chapter,role_active=False)
        elif alter=='reference':act=replace(act,offer_effect_id='stale-effect')
        elif alter=='input':act=replace(act,input_id='old-input')
        else:act=replace(act,epoch=3)
        assert stage_chapter(chapter,transition='x.gift_accept',input_id='current',epoch=4,
            user_text=RECONSIDER,native_act=act,offer_id='gift',ready=True,scope_binding='scope')==chapter
    finally: await s.close()


@pytest.mark.asyncio
async def test_never_presented_offer_and_unrecognized_role_cannot_reconsider():
    s=Flow()
    try:
        raw=story_call('x.gift_accept',act='reopen_accept_gift',text=RECONSIDER,
            offer='never-presented',reference='never-presented-effect')
        r,state=await s.say(RECONSIDER,raw)
        assert r['status']=='held' and not s.c.runtime.story.chapter.role_active
        await s.recognize_offer()
        # An offered gift has not been declined, so this special intent does not replace accept_gift.
        r,state=await s.say(RECONSIDER,raw)
        assert r['status']=='held'
        assert not any(e.value=='xiahe_photo_handover' for e in state.issued_effects)
    finally: await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary',['duplicate','stop_pending','new_input_pending'])
async def test_handover_reconsideration_is_finite_and_late_receipt_cannot_revive_it(boundary):
    s=Flow()
    try:
        original=await declined(s)
        r,state=await s.say(RECONSIDER,reconsider(original),acknowledge=boundary=='duplicate')
        assert r['status']==('shown' if boundary=='duplicate' else 'pending')
        if boundary=='duplicate':
            r,state=await s.say(RECONSIDER,reconsider(original))
            assert r['status']=='held'
            assert sum(e.value=='xiahe_photo_handover' for e in state.issued_effects)==1
            assert s.c.runtime.story.chapter.stage is ChapterStage.COMPLETED
        else:
            handover=next(e for e in state.active_grants if e.value=='xiahe_photo_handover')
            if boundary=='stop_pending':
                s.epoch+=1;await s.a.stop(activity_seq=s.epoch,cutoff=s.seq)
            else:await s.say('先不收了','好。')
            with pytest.raises(DomainError):await s.a.receipt(receipt(handover,s.seq+1))
            assert 'photo_handover' not in dict(s.c.runtime.story.chapter.milestones)
            assert s.c.runtime.story.chapter.pending is None
    finally: await s.close()
