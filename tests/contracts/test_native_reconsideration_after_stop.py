"""Full observed refusal -> global Stop -> fresh current acceptance; offline fixtures."""
import pytest

from mira.domain.models import EffectKind
from mira.domain.errors import DomainError
from mira.domain.xiahe_chapter import ChapterStage
from tests.contracts.test_native_photo_handover_flow import Flow
from tests.contracts.test_native_followthrough import declined, reconsider, RECONSIDER
from tests.contracts.test_authored_photo_events import receipt


@pytest.mark.asyncio
async def test_observed_decline_global_stop_then_explicit_reconsideration_is_one_new_handover():
    s=Flow()
    try:
        original=await declined(s)
        s.epoch+=1;await s.a.stop(activity_seq=s.epoch,cutoff=s.seq)
        chapter=s.c.runtime.story.chapter
        assert chapter.stage is ChapterStage.GIFT_DECLINED and chapter.role_active
        assert chapter.suspended and chapter.active_gift_offer_id is None and chapter.pending is None
        assert chapter.declined_gift_offer is not None
        assert chapter.declined_gift_offer.receipt_id==dict(original.milestones)['gift_offer']
        await s.say('嗯，停了就好。聊点别的。','好，我们接着聊。')
        before=len(s.requests)
        r,state=await s.say(RECONSIDER,reconsider(original))
        assert r['status']=='shown'
        assert s.c.runtime.story.chapter.stage is ChapterStage.COMPLETED
        assert not s.c.runtime.story.chapter.suspended
        assert len(s.requests)-before==2
        assert sum(e.value=='xiahe_photo_handover' for e in state.presented_effects)==1
        assert r['receipt']['effect_id']!=original.gift_offer_effect_id
        assert not any(e.value=='xiahe_gift_offer' for e in state.issued_effects)
        assert dict(s.c.runtime.story.chapter.milestones)['gift_offer']==dict(original.milestones)['gift_offer']
    finally:await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('fence',['global_stop','ordinary_input'])
async def test_cancelled_reconsideration_keeps_history_but_requires_new_input_and_new_handover_receipt(fence):
    s=Flow()
    try:
        original=await declined(s)
        r,state=await s.say(RECONSIDER,reconsider(original),acknowledge=False)
        assert r['status']=='pending'
        old=next(e for e in state.active_grants if e.value=='xiahe_photo_handover')
        if fence=='global_stop':
            s.epoch+=1;await s.a.stop(activity_seq=s.epoch,cutoff=s.seq)
        else:await s.say('等一下先说另一件事','好。')
        with pytest.raises(DomainError):await s.a.receipt(receipt(old,s.seq+1))
        assert 'photo_handover' not in dict(s.c.runtime.story.chapter.milestones)
        r,state=await s.say(RECONSIDER,reconsider(original),acknowledge=False)
        assert r['status']=='pending'
        new=next(e for e in state.active_grants if e.value=='xiahe_photo_handover')
        assert new.id!=old.id and new.output_epoch>old.output_epoch
        assert s.c.runtime.story.chapter.stage is ChapterStage.GIFT_DECLINED
        s.seq+=1;await s.a.receipt(receipt(new,s.seq))
        assert s.c.runtime.story.chapter.stage is ChapterStage.COMPLETED
        assert sum(e.value=='xiahe_photo_handover' for e in state.presented_effects)==0
        assert sum(e.value=='xiahe_photo_handover' for e in (await s.a.snapshot()).presented_effects)==1
    finally:await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['plain_accept','mention','negation','hypothesis'])
async def test_stop_never_automatically_reauthorizes_a_historical_declined_offer(mode):
    s=Flow()
    try:
        original=await declined(s)
        s.epoch+=1;await s.a.stop(activity_seq=s.epoch,cutoff=s.seq)
        text={'plain_accept':'好','mention':'刚才说过那张照片','negation':'我现在还是不收','hypothesis':'如果我想收下呢？'}[mode]
        plan=reconsider(original,text=text,act='accept_gift') if mode=='plain_accept' else '我们接着聊。'
        r,state=await s.say(text,plan)
        assert r is None if mode!='plain_accept' else r['status']=='held'
        assert not any(e.value=='xiahe_photo_handover' for e in state.issued_effects)
        assert s.c.runtime.story.chapter.stage is ChapterStage.GIFT_DECLINED
        assert s.c.runtime.story.chapter.suspended
    finally:await s.close()
