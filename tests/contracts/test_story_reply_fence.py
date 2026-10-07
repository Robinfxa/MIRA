"""Pure/runtime reply fences; actual HTTP/PTT integration belongs to Actor owner."""
from dataclasses import replace
import json
import pytest
from mira.application.compiler import compile_range
from mira.application.contracts import CandidateRange,EffectProposal,GenerationContext
from mira.application.native_character_tools import prepare_native_character
from mira.application.generation_tool_execution import parse_tool_arguments
from mira.domain.models import EffectKind
from mira.domain.errors import DomainError
from tests.contracts.test_xiahe_chapter_actor import character,prepare,complete,advance_to_gift
from tests.contracts.test_native_character_tools import story_call


def asked(*,shown=True):
    c=character();c.begin_input('ask',1)
    question=compile_range(CandidateRange((EffectProposal(EffectKind.SUBTITLE,'你是夏禾吗？'),),'synthetic-question'),epoch=1,activity=1)[0]
    c._native_role_question=(question.id,1,'ask')
    return c,question,(question,) if shown else ()


def confirmation(c,question,epoch,*,reference=None,shown=None):
    c.begin_input('answer.'+str(epoch),epoch)
    context=GenerationContext('是',('你在等我吗','是'),shown if shown is not None else (question,),epoch,
        character_story=c.runtime.project().projection,character_assets=c.readiness)
    call=story_call('x.recognize',act='confirm_role',text='是',reference=reference or question.id,offer='gift')
    return prepare_native_character(c,context,call,parse_tool_arguments(call),'answer.'+str(epoch),epoch)


def test_presented_gift_survives_reply_fence_and_one_current_acceptance():
    c=character();advance_to_gift(c);before=c.runtime.story
    c.reply_fence(8,())
    after=c.runtime.story
    assert after.epoch==8 and after.input_fence_id is None
    assert after.chapter==before.chapter and after.episodes==before.episodes
    assert after.last_input_ids==before.last_input_ids
    _,effects=prepare(c,'x.gift_accept',9,'我收下这张照片',act='accept_gift',offer=after.chapter.active_gift_offer_id)
    assert any(e.value=='xiahe_photo_handover' for e in effects)
    complete(c,effects,30);assert c.runtime.story.chapter.stage.value=='completed'


@pytest.mark.parametrize('transition',['x.recognize','x.gift_offer'])
def test_reply_fence_clears_pending_immediately_without_advancing_late_history(transition):
    c=character()
    if transition=='x.recognize': _,effects=prepare(c,transition,1,'我是夏禾',act='claim_role')
    else:
        _,effects=prepare(c,'x.recognize',1,'我是夏禾',act='claim_role');complete(c,effects)
        _,effects=prepare(c,transition,2,offer='not-yet-presented')
    pending=c.runtime.story.chapter.pending
    c.reply_fence(c.runtime.story.epoch+1,())
    assert c.runtime.story.chapter.pending is None
    complete(c,effects,20)
    assert c.runtime.story.chapter.active_gift_offer_id is None
    assert pending.milestone not in dict(c.runtime.story.chapter.milestones)
    assert c.runtime.story.chapter.role_active is (transition!='x.recognize')


@pytest.mark.parametrize('controls',[1,2,3])
def test_presented_question_crosses_only_recorded_reply_controls_to_one_actual_answer(controls):
    c,q,shown=asked();original=c._native_role_question
    for epoch in range(2,2+controls): c.reply_fence(epoch,shown)
    assert c._native_role_question==original
    update,_=confirmation(c,q,2+controls)
    assert update.story.chapter.pending.transition=='x.recognize'
    assert q.output_epoch==1 and c._native_role_question[1]==1


@pytest.mark.parametrize('case',['unshown','wrong_reference','skipped_epoch','intervening_input','later_subtitle','global_stop','other_runtime'])
def test_reply_fence_does_not_revive_unshown_wrong_consumed_or_cross_session_question(case):
    c,q,shown=asked(shown=case!='unshown')
    if case=='later_subtitle':
        later=compile_range(CandidateRange((EffectProposal(EffectKind.SUBTITLE,'先聊聊咖啡吧。'),),'other-dialogue'),epoch=1,activity=1)[0]
        shown=(*shown,later)
    if case=='global_stop': c.stop(2)
    elif case=='intervening_input':
        c.begin_input('different-input',2);c.reply_fence(3,shown)
    elif case=='other_runtime':
        c=character();c.begin_input('new-session',1);c.reply_fence(2,shown)
    else: c.reply_fence(2,shown)
    target=4 if case in {'skipped_epoch','intervening_input'} else 3
    with pytest.raises(DomainError) as error:
        confirmation(c,q,target,reference='wrong' if case=='wrong_reference' else None,shown=shown)
    assert error.value.code=='tool_held'
    assert not c.runtime.story.chapter.role_active


def test_global_stop_and_decline_suspension_are_never_cleared_by_reply_fence():
    c=character();advance_to_gift(c);c.stop(8)
    c.reply_fence(9,())
    assert c.runtime.story.chapter.suspended and c.runtime.story.chapter.active_gift_offer_id is None


def test_reply_fence_is_idempotent_but_rejects_unrecorded_epoch_gap():
    c,q,shown=asked();c.reply_fence(2,shown);before=c.runtime.story
    c.reply_fence(2,shown);assert c.runtime.story==before
    with pytest.raises(ValueError): c.reply_fence(4,shown)
    assert c.runtime.story==before


def test_role_question_is_bound_to_one_actual_input_id_not_just_epoch():
    c,q,shown=asked();c.reply_fence(2,shown)
    c.begin_input('first-real-answer',3)
    with pytest.raises(DomainError): confirmation(c,q,3)
    assert not c.runtime.story.chapter.role_active


def test_invalid_input_does_not_consume_question_and_same_input_retry_is_idempotent():
    c,q,shown=asked();c.reply_fence(2,shown)
    with pytest.raises(ValueError): c.begin_input('',3)
    c.begin_input('answer.3',3)
    update,_=confirmation(c,q,3)
    assert update.story.chapter.pending.transition=='x.recognize'
