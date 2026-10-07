"""Offline regression of observed turn26 and camera result contracts, not model proof."""
import json
from dataclasses import replace
import pytest

from mira.application.ports.generation_tools import GenerationToolCall
from mira.domain.models import EffectKind
from mira.domain.xiahe_chapter import ChapterStage, chapter_projection, chapter_from_dict, chapter_to_dict
from tests.contracts.test_native_photo_handover_flow import Flow, PHOTO
from tests.contracts.test_native_character_tools import story_call
from tests.contracts.test_authored_photo_events import receipt

RECONSIDER = '好，懂了。新图也出来了。对了，我刚翻包发现有个文件袋，能挡雨。你刚才说要送我的那张，我现在想收下了，还来得及反悔吗？'


async def declined(s):
    await s.recognize_offer()
    original = s.c.runtime.story.chapter
    await s.say('照片先别送我，我今天没带能防雨的袋子。', story_call('x.gift_decline',
        act='decline_gift', text='照片先别送我，我今天没带能防雨的袋子。', offer='gift'))
    assert s.c.runtime.story.chapter.stage is ChapterStage.GIFT_DECLINED
    return original


def reconsider(original, *, text=RECONSIDER, offer='gift', reference=None, act='reopen_accept_gift'):
    return story_call('x.gift_accept', act=act, text=text, offer=offer,
        reference=original.gift_offer_effect_id if reference is None else reference)


@pytest.mark.asyncio
async def test_receipted_decline_then_present_reconsideration_hands_over_in_one_tool_turn():
    s=Flow()
    try:
        original=await declined(s);affect=s.c.runtime.affect
        await s.say('先聊聊别的','我们接着聊。')
        before=len(s.requests)
        r,state=await s.say(RECONSIDER,reconsider(original),'给你，这次终于轮到你保管了。')
        assert r is not None and r['status']=='shown'
        assert s.c.runtime.story.chapter.stage is ChapterStage.COMPLETED
        assert s.c.runtime.affect==affect
        assert dict(s.c.runtime.story.chapter.milestones)['gift_offer']==dict(original.milestones)['gift_offer']
        assert sum(e.value=='xiahe_photo_handover' for e in state.presented_effects)==1
        assert not any(e.value=='xiahe_gift_offer' for e in state.issued_effects)
        assert r['receipt']['effect_id']!=original.gift_offer_effect_id
        assert s.prompts[-1]['facts']['character_story']['chapter']['completed']
        assert len(s.requests)-before==2
        body=json.loads(s.requests[-1].content)
        assert body['tools']==[] and body['tool_choice']=='none'
        assert len([i for i in body['input'] if i.get('type')=='function_call_output'])==1
    finally: await s.close()


@pytest.mark.asyncio
async def test_declined_reference_is_exposed_only_as_receipted_reconsideration_not_active_offer():
    s=Flow()
    try:
        original=await declined(s)
        chapter=s.c.runtime.story.chapter
        projected=chapter_projection(chapter)
        assert projected['active_gift_offer_id'] is None
        assert projected['declined_gift_offer']==dict(offer_id='gift',effect_id=original.gift_offer_effect_id,
            effect_digest=original.gift_offer_effect_digest,receipt_id=dict(original.milestones)['gift_offer'])
        assert 'x.gift_accept' in projected['allowed_next']
        assert chapter_from_dict(chapter_to_dict(chapter))==chapter
        old=chapter_to_dict(chapter);old.pop('declined_gift_offer')
        assert chapter_from_dict(old).declined_gift_offer is None
    finally: await s.close()


@pytest.mark.asyncio
async def test_reconsideration_waits_for_new_handover_receipt_and_never_reuses_preview():
    s=Flow()
    try:
        preview,_=await s.say('看看灯塔照片',PHOTO)
        original=await declined(s)
        r,state=await s.say(RECONSIDER,reconsider(original),acknowledge=False)
        assert r is not None and r['status']=='pending' and not r['shown']
        assert s.c.runtime.story.chapter.stage is ChapterStage.GIFT_DECLINED
        handover=next(e for e in state.active_grants if e.value=='xiahe_photo_handover')
        assert handover.id not in {preview['receipt']['effect_id'],original.gift_offer_effect_id}
        assert not s.prompts[-1]['facts']['character_story']['chapter']['completed']
        s.seq+=1;await s.a.receipt(receipt(handover,s.seq))
        assert s.c.runtime.story.chapter.stage is ChapterStage.COMPLETED
    finally: await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['wrong_offer','wrong_effect','missing_effect','mismatched_input','plain_accept','reopen_only'])
async def test_reconsideration_rejects_missing_exact_authority(change):
    s=Flow()
    try:
        original=await declined(s)
        kwargs={
            'wrong_offer':{'offer':'never-presented'},'wrong_effect':{'reference':'other-effect'},
            'missing_effect':{'reference':''},'mismatched_input':{'text':'我收下'},
            'plain_accept':{'act':'accept_gift'},'reopen_only':{'act':'reopen_gift'},
        }[change]
        r,state=await s.say(RECONSIDER,reconsider(original,**kwargs))
        assert r is not None and r['status']=='held'
        assert s.c.runtime.story.chapter.stage is ChapterStage.GIFT_DECLINED
        assert not any(e.value=='xiahe_photo_handover' for e in state.issued_effects)
    finally: await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['你刚才说照片', '如果我现在想收下呢？', '我没有说现在收下', '他说“我现在收下”', '还能重新问我一次吗？'])
async def test_nonaccepting_dialogue_does_not_infer_acceptance_from_words(text):
    s=Flow()
    try:
        await declined(s)
        r,state=await s.say(text,'好，我们慢慢聊。')
        assert r is None and s.c.runtime.story.chapter.stage is ChapterStage.GIFT_DECLINED
        assert not any(e.value=='xiahe_photo_handover' for e in state.issued_effects)
    finally: await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('fence',['stop','exit','new_offer'])
async def test_fences_or_replaced_offer_revoke_declined_reference(fence):
    s=Flow()
    try:
        original=await declined(s)
        if fence=='stop':
            s.epoch+=1;await s.a.stop(activity_seq=s.epoch,cutoff=s.seq)
        elif fence=='exit':
            await s.say('退出角色',story_call('x.exit',act='exit_role',text='退出角色'))
            await s.say('我是夏禾',story_call('x.recognize',act='claim_role',text='我是夏禾'))
        else:
            await s.say('重新问我一次吧',story_call('x.gift_offer',act='reopen_gift',
                text='重新问我一次吧',offer='new-offer'))
        reference=chapter_projection(s.c.runtime.story.chapter).get('declined_gift_offer')
        assert (reference is not None) is (fence=='stop')
        r,state=await s.say(RECONSIDER,reconsider(original,act='accept_gift' if fence=='stop' else 'reopen_accept_gift'))
        assert r is not None and r['status']=='held'
        assert not any(e.value=='xiahe_photo_handover' for e in state.issued_effects)
        if fence=='stop':
            r,_=await s.say('重新邀请我收照片吧',story_call('x.gift_offer',act='reopen_gift',
                text='重新邀请我收照片吧',offer='after-stop'))
            assert r['status']=='shown' and s.c.runtime.story.chapter.active_gift_offer_id=='after-stop'
    finally: await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('acknowledge',[True,False])
async def test_return_camera_wire_and_result_truthfully_keep_camera_held(acknowledge):
    s=Flow()
    try:
        r,state=await s.say('把相机放一会儿',GenerationToolCall('camera','perform_action',
            '{"action":"return_camera"}'),acknowledge=acknowledge)
        definition=next(t for t in json.loads(s.requests[0].content)['tools'] if t['name']=='perform_action')
        assert 'remains held' in definition['description'] and 'table' in definition['description']
        if acknowledge:
            assert r['status']=='shown'
            assert r['action_outcome']=={'pose':'camera_ready','camera_held':True,'placed_on_table':False}
            assert any(e.value=='camera_ready' for e in state.presented_effects)
        else:
            assert r['status']=='pending' and 'action_outcome' not in r
    finally: await s.close()
