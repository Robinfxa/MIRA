"""Self-authored synthetic roleplay; no actual user corpus or provider calls."""
from dataclasses import replace
import pytest
from mira.domain.xiahe_chapter import (
    ChapterState, ChapterStage, ChapterInputAct, validate_input_act,
    stage_chapter, bind_chapter_effect, acknowledge_chapter, cancel_chapter,
    chapter_projection, chapter_from_dict, chapter_to_dict,
)


def act(kind, text, role='夏禾'):
    return ChapterInputAct(kind, text, role)


def stage(state, transition, text='继续说吧', *, input_act=None, offer=None, ready=True, will='YES', epoch=1):
    if transition == 'x.gift_accept' and input_act is None:
        text='我收下这张照片';input_act=act('accept_gift',text)
    if transition == 'x.gift_decline' and input_act is None:
        text='暂时不收照片';input_act=act('decline_gift',text)
    return stage_chapter(state, transition=transition, input_id='input.'+str(epoch), epoch=epoch,
        user_text=text, input_act=input_act, offer_id=offer, draft_cue='合成章节台词',
        reviewed=True, relevant=True, willingness=will, refusal=will=='NO', ready=ready,
        scope_binding='scope.test')


def ack(state, epoch=1):
    state=bind_chapter_effect(state,effect_id='effect.'+str(epoch),digest='a'*64,epoch=epoch)
    return acknowledge_chapter(state,receipt_id='receipt.'+str(epoch),effect_id='effect.'+str(epoch),
        digest='a'*64,epoch=epoch,scope_binding='scope.test')


def recognized():
    s=stage(ChapterState(),'x.recognize','我是夏禾',input_act=act('claim_role','我是夏禾'))
    assert not s.role_active
    return ack(s)


@pytest.mark.parametrize('text',['我不是夏禾','她说“我是夏禾”','你是夏禾吗？','如果我是夏禾呢',
    '夏禾是谁','他说他是夏禾','“我是夏禾”','我叫夏阖','我是夏禾吗','假设我是夏禾','我可能是夏禾'])
def test_ambiguous_mentions_do_not_recognize(text):
    assert not validate_input_act(act('claim_role',text),text,'claim_role')
    assert stage(ChapterState(),'x.recognize',text,input_act=act('claim_role',text)).pending is None


def test_current_typed_assertion_and_ack_are_both_required():
    assert stage(ChapterState(),'x.recognize','我是夏禾').pending is None
    s=stage(ChapterState(),'x.recognize','我是夏禾',input_act=act('claim_role','我是夏禾'))
    assert s.pending and not s.role_active
    assert acknowledge_chapter(s,receipt_id='bad',effect_id='x',digest='a'*64,epoch=1,scope_binding='scope.test')==s
    s=ack(s)
    assert s.role_active and s.stage is ChapterStage.RECOGNIZED
    assert stage(s,'x.recognize','我是夏禾',input_act=act('claim_role','我是夏禾'),epoch=2).pending is None


def test_finite_receipted_chapter_decline_reopen_and_no_autoadvance():
    s=recognized()
    for n,t in [(2,'x.story'),(3,'x.story'),(4,'x.story'),(5,'x.promise'),(6,'x.preview')]:
        before=s.stage;s=stage(s,t,epoch=n);assert s.stage is before;s=ack(s,n)
    s=ack(stage(s,'x.gift_offer',offer='offer.one',epoch=7),7)
    assert s.stage is ChapterStage.GIFT_OFFERED
    s=stage(s,'x.gift_decline',will='NO',offer='offer.one',epoch=8)
    assert s.stage is ChapterStage.GIFT_DECLINED
    assert stage(s,'x.gift_offer',offer='offer.two',epoch=9).pending is None
    s=stage(s,'x.gift_offer','现在可以把照片给我了',offer='offer.two',epoch=10,
        input_act=act('reopen_gift','现在可以把照片给我了'))
    s=ack(s,10)
    assert stage(s,'x.gift_accept',offer='wrong',epoch=11).pending is None
    s=stage(s,'x.gift_accept',offer='offer.two',epoch=12)
    assert s.stage is ChapterStage.GIFT_OFFERED
    s=ack(s,12)
    assert s.stage is ChapterStage.COMPLETED
    assert chapter_projection(s)['completed'] is True


def test_stop_correction_and_failed_resource_preserve_only_actual_facts():
    s=recognized();pending=stage(s,'x.story',epoch=2)
    stopped=cancel_chapter(pending)
    assert stopped.milestones==s.milestones and stopped.pending is None
    assert acknowledge_chapter(stopped,receipt_id='old',effect_id='effect.2',digest='a'*64,
        epoch=2,scope_binding='scope.test')==stopped
    assert stage(s,'x.story',ready=False,epoch=3).pending is None
    exited=stage(s,'x.exit','我不是夏禾',input_act=act('exit_role','我不是夏禾'),epoch=4)
    assert not exited.role_active and exited.milestones==s.milestones
    assert stage(exited,'x.story',epoch=5).pending is None
    restored=chapter_from_dict(chapter_to_dict(exited))
    assert restored==exited
    with pytest.raises(ValueError):chapter_from_dict({'schema':'unknown'})


def test_old_friend_history_reveals_three_layers_without_dumping_or_skipping():
    s=recognized()
    assert stage(s,'x.promise',epoch=2).pending.transition == 'x.promise'
    for n in (2,3,4):
        view=chapter_projection(s)
        assert len(view['author_canon_for_current_beat']) == 1
        s=stage(s,'x.story',epoch=n)
        assert s.pending is not None
        s=ack(s,n)
    assert stage(s,'x.story',epoch=5).pending is None
    assert stage(s,'x.promise',epoch=6).pending is not None


@pytest.mark.parametrize('text',['我是夏禾，好久不见，你还记得我吗？','你好，我就是夏禾。今天过得怎么样？',
    '我来扮演夏禾，我们接着聊吧。','没错，我是夏禾。','我就是夏禾呀，你好！'])
def test_unambiguous_role_clause_is_not_a_magic_phrase(text):
    assert validate_input_act(act('claim_role',text),text,'claim_role')
    assert stage(ChapterState(),'x.recognize',text,input_act=act('claim_role',text)).pending is not None


@pytest.mark.parametrize('text',['她说，我是夏禾。','请跟我说，我是夏禾。','我是夏禾，骗你的。'])
def test_reported_or_retracted_multiclause_claim_is_not_current_role(text):
    assert not validate_input_act(act('claim_role',text),text,'claim_role')


@pytest.mark.parametrize('text',['好，不过不用给我照片。','好，我不接受。','好，先等等，我还没决定。'])
def test_contradictory_gift_reply_does_not_accept(text):
    assert not validate_input_act(act('accept_gift',text),text,'accept_gift')


def test_same_input_cannot_advance_two_revelation_beats():
    s=recognized();s=ack(stage(s,'x.story',epoch=2),2)
    assert stage(s,'x.story',epoch=2).pending is None
    assert stage(s,'x.story',epoch=3).pending is not None
