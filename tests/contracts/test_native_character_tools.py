"""Native function requests execute through Actor grants and exact receipts, offline."""
import asyncio
import json
from dataclasses import replace
import pytest
from mira.application.ports.generation_tools import GenerationToolCall
from mira.application.contracts import CandidateRange, EffectProposal
from mira.application.session_actor import SessionActor, RuntimeLimits
from mira.adapters.journal.memory import MemoryEventJournal
from mira.domain.models import SessionState, EffectKind
from mira.domain.story import CapabilityRecord, CapabilityState, ReadinessCatalog
from tests.contracts.test_luna_tool_actor import ToolTurn, Tools, LegacyGeneration, ObservedActor, wait_state, result, text_candidate
from tests.contracts.test_authored_photo_events import receipt
from tests.contracts.test_development_review_composition import finish
from tests.contracts.test_xiahe_chapter_actor import character

class NeverReview:
    async def review(self,*args): raise AssertionError('Native tools must never call JEV')

def native(turn, *, c=None, wait=.02, tools=None):
    from mira.application.character_controls import CHARACTER_CAPABILITIES
    keys=(*CHARACTER_CAPABILITIES.values(),'mira.pose.camera_ready','mira.pose.camera_raise','mira.media.trip_photo','cafe.scene.rain_window')
    ready=ReadinessCatalog('synthetic-native', tuple(CapabilityRecord(k,CapabilityState.READY,'synthetic',
        ('outer.amber','inner.cream','scene.rain_window.composition',k),'synthetic') for k in keys))
    if c is not None: c.readiness=ReadinessCatalog('synthetic-native',(*ready.records,*c.readiness.records))
    return ObservedActor(SessionState('s','c'),LegacyGeneration(),NeverReview(),MemoryEventJournal(200),
        RuntimeLimits(3,20,128),tool_generation=tools or Tools(turn),native_tool_authority=True,
        visual_readiness=ready,character_runtime=c,tool_result_wait_seconds=wait)

@pytest.mark.asyncio
async def test_native_ordinary_dialogue_never_calls_review():
    turn=ToolTurn(call=text_candidate()); a=native(turn)
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text='你好'); s=await finish(a)
        assert s.last_error is None and any(e.kind is EffectKind.SUBTITLE for e in s.active_grants)
        assert not turn.results
    finally: await a.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('name,args,value',[
 ('set_outfit',{'outfit':'amber_raincoat'},'outfit_amber_raincoat'),
 ('set_accessory',{'accessory':'star_clip'},'accessory_star_clip'),
 ('set_emotion',{'emotion':'happy'},'emotion_happy'),
 ('perform_action',{'action':'raise_camera'},'camera_raise'),
 ('perform_action',{'action':'return_camera'},'camera_ready'),
 ('set_scene',{'scene':'rain_window'},'rain_window'),
])
async def test_native_control_waits_for_own_exact_receipt(name,args,value):
    t=ToolTurn(GenerationToolCall('control',name,json.dumps(args))); a=native(t,wait=1)
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text='请执行这个动作')
        s=await wait_state(a,lambda s:any(e.value==value for e in s.active_grants))
        e=next(e for e in s.active_grants if e.value==value)
        assert not t.results
        await a.receipt(receipt(e,1));s=await finish(a)
        assert result(t)['status']=='shown' and result(t)['receipt']['effect_id']==e.id
        assert t.results[0][1].output_epoch==1 and e in t.results[0][1].presented_effects
        assert s.last_error is None
    finally: await a.close()

def story_call(transition,*,act='none',text='',reference='',offer='',cue='',target='none'):
    return GenerationToolCall('story', 'advance_story', json.dumps({'transition_id':transition,
        'input_act':act,'evidence_text':text,'reference_effect_id':reference,'offer_id':offer,
        'draft_cue':cue,'target':target,'scope':'fictional_role_only'},ensure_ascii=False))

async def accept_all(a,start=1):
    s=await a.snapshot()
    for seq,e in enumerate([e for e in s.active_grants if not any(r.effect_id==e.id for r in s.receipts)],start):
        await a.receipt(receipt(e,seq))
    return await a.snapshot()

@pytest.mark.asyncio
async def test_native_mixed_script_role_claim_uses_typed_semantics_and_real_scene_receipt():
    text='我就是夏he啊';t=ToolTurn(story_call('x.recognize',act='claim_role',text=text));c=character();a=native(t,c=c,wait=1)
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text=text)
        s=await wait_state(a,lambda s:any(e.value=='xiahe_recognition' for e in s.active_grants))
        assert not c.runtime.story.chapter.role_active
        e=next(e for e in s.active_grants if e.value=='xiahe_recognition')
        await a.receipt(receipt(e,1));await finish(a)
        assert c.runtime.story.chapter.role_active and result(t)['status']=='shown'
        assert t.results[0][1].character_story.chapter.role_active
    finally:await a.close()

@pytest.mark.asyncio
async def test_native_confirmation_requires_own_immediately_previous_presented_question():
    ask=ToolTurn(story_call('x.ask_role',act='ask_role_confirmation',text='你说的是我吗',cue='你是说，在这里你就是夏禾，对吗？'))
    ask.candidate=CandidateRange((EffectProposal(EffectKind.SUBTITLE,'你是说，在这里你就是夏禾，对吗？'),),'synthetic-question')
    confirm=ToolTurn();tools=Tools(ask,confirm);c=character();a=native(ask,c=c,tools=tools)
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text='你说的是我吗');s=await finish(a)
        question=next(e for e in s.active_grants if '你是说' in e.value)
        await a.receipt(receipt(question,1))
        confirm.call=story_call('x.recognize',act='confirm_role',text='嗯，对',reference=question.id)
        await a.submit(request_id='i2',activity_seq=2,cutoff=1,text='嗯，对');s=await finish(a)
        scene=next(e for e in s.active_grants if e.value=='xiahe_recognition')
        assert not c.runtime.story.chapter.role_active and result(confirm)['status']=='pending'
        await a.receipt(receipt(scene,3));assert c.runtime.story.chapter.role_active
    finally:await a.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('act,text,evidence,reference',[
 ('claim_role','他说“我是夏禾”','我是夏禾',''),
 ('confirm_role','对','对','made-up-reference'),
 ('claim_role','我不是夏禾','我就是夏禾',''),
])
async def test_native_role_cannot_derive_authority_from_other_text_or_unknown_confirmation(act,text,evidence,reference):
    t=ToolTurn(story_call('x.recognize',act=act,text=evidence,reference=reference));c=character();a=native(t,c=c)
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text=text);s=await finish(a)
        assert result(t)['status']=='held' and not c.runtime.story.chapter.role_active
        assert not any(e.kind is EffectKind.SCENE for e in s.issued_effects)
        assert any(e.kind is EffectKind.SUBTITLE for e in s.active_grants)
    finally:await a.close()

@pytest.mark.asyncio
async def test_native_story_continuation_unlocks_only_on_its_actual_receipt():
    c=character();from tests.contracts.test_xiahe_chapter_actor import prepare,complete
    _,effects=prepare(c,'x.recognize',1,'我是夏禾',act='claim_role');complete(c,effects)
    cue='我想起我们在这家店一起挑试印的那一回。'
    t=ToolTurn(story_call('x.story',cue='Tell the shared print memory.'))
    t.candidate=CandidateRange((EffectProposal(EffectKind.SUBTITLE,cue),),'synthetic-story')
    a=native(t,c=c,wait=1);a._state=replace(a._state,output_epoch=1)
    try:
        await a.submit(request_id='i2',activity_seq=2,cutoff=0,text='你接着说')
        s=await finish(a)
        assert result(t)['status']=='pending' and result(t)['phase']=='awaiting_dialogue'
        assert 'old_friend' not in dict(c.runtime.story.chapter.milestones)
        assert [e.value for e in s.active_grants]==[cue]
        await a.receipt(receipt(s.active_grants[0],1))
        assert 'old_friend' in dict(c.runtime.story.chapter.milestones)
    finally:await a.close()

@pytest.mark.asyncio
async def test_native_rain_offer_then_exact_accept_advances_only_on_wardrobe_receipt():
    offer=ToolTurn(story_call('t.offer',offer='rain-1',cue='要看看我的雨衣吗？',target='amber_raincoat'))
    offer.candidate=CandidateRange((EffectProposal(EffectKind.SUBTITLE,'要看看我的雨衣吗？'),),'synthetic-offer')
    accept=ToolTurn(story_call('t.yes',act='accept_rain',text='看看',offer='rain-1',target='amber_raincoat'))
    c=character();a=native(offer,c=c,tools=Tools(offer,accept))
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text='聊聊你的雨衣');s=await finish(a)
        question=next(e for e in s.active_grants if '雨衣吗' in e.value)
        await a.receipt(receipt(question,1))
        await a.submit(request_id='i2',activity_seq=2,cutoff=1,text='看看');s=await finish(a)
        outfit=next(e for e in s.active_grants if e.value=='outfit_amber_raincoat')
        assert c.runtime.story.current_outfit!='amber_raincoat' and result(accept)['status']=='pending'
        await a.receipt(receipt(outfit,2));assert c.runtime.story.current_outfit=='amber_raincoat'
        assert not any(e.kind is EffectKind.MEDIA for e in s.issued_effects)
    finally:await a.close()

@pytest.mark.asyncio
async def test_native_missing_receipt_returns_pending_without_changing_displayed_outfit():
    t=ToolTurn(GenerationToolCall('x','set_outfit','{"outfit":"amber_raincoat"}'));c=character();a=native(t,c=c)
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text='我想看看雨衣');s=await finish(a)
        assert result(t)['status']=='pending' and not result(t)['shown']
        assert c.runtime.story.current_outfit!='amber_raincoat'
        assert any(e.kind is EffectKind.SUBTITLE for e in s.active_grants)
    finally:await a.close()

@pytest.mark.asyncio
async def test_native_commentary_is_available_before_optional_render_and_continuation():
    call=replace(GenerationToolCall('x','set_outfit','{"outfit":"amber_raincoat"}'),commentary=text_candidate())
    t=ToolTurn(call);a=native(t,wait=1)
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text='我想看看雨衣')
        s=await wait_state(a,lambda s:any(e.kind is EffectKind.POSE for e in s.active_grants))
        assert any(e.kind is EffectKind.SUBTITLE for e in s.active_grants) and not t.results
        await a.stop(activity_seq=2,cutoff=0);await finish(a)
        assert not t.results and not (await a.snapshot()).active_grants
    finally:await a.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('fence',['stop','new_input','close'])
@pytest.mark.parametrize('phase',['start','continuation'])
async def test_native_uncooperative_model_is_fenced(fence,phase):
    t=ToolTurn(GenerationToolCall('x','set_outfit','{"outfit":"amber_raincoat"}'),
        start_gate=phase=='start',continue_gate=phase=='continuation',ignore_cancel=True)
    second=ToolTurn(call=text_candidate());a=native(t,tools=Tools(t,second))
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text='看看雨衣')
        await asyncio.wait_for((t.started if phase=='start' else t.continued).wait(),1)
        if fence=='stop':await a.stop(activity_seq=2,cutoff=0)
        elif fence=='new_input':await a.submit(request_id='i2',activity_seq=2,cutoff=0,text='换个话题')
        else:await a.close()
        t.release.set();s=await finish(a)
        assert not any(e.kind is EffectKind.SUBTITLE and e.output_epoch==1 for e in s.issued_effects)
        assert len(t.results)==(1 if phase=='continuation' else 0)
    finally:t.release.set();await a.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('shown',[False,True])
async def test_native_photo_dismiss_preserves_dialogue_continuation_and_actual_history(shown):
    t=ToolTurn();a=native(t,wait=1)
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text='看看照片')
        s=await wait_state(a,lambda s:s.fixed_photo.state=='granted');photo=next(e for e in s.active_grants if e.kind is EffectKind.MEDIA)
        if shown:await a.receipt(receipt(photo,1))
        await a.dismiss_photo(request_id='close-photo',expected_revision=0,cutoff=int(shown));s=await finish(a)
        assert len(t.results)==1 and result(t)['status']==('shown' if shown else 'cancelled')
        assert result(t)['shown'] is shown and result(t)['visible'] is False
        assert not s.photo_visible and any(e.kind is EffectKind.SUBTITLE for e in s.active_grants)
        assert sum(e.kind is EffectKind.MEDIA for e in s.issued_effects)==1
    finally:await a.close()

@pytest.mark.asyncio
async def test_native_two_actors_never_accept_each_others_receipts():
    from mira.domain.errors import DomainError
    t1=ToolTurn(GenerationToolCall('same','set_outfit','{"outfit":"amber_raincoat"}'))
    t2=ToolTurn(GenerationToolCall('same','set_outfit','{"outfit":"black_jacket"}'))
    a,b=native(t1,wait=1),native(t2,wait=1)
    try:
        await asyncio.gather(a.submit(request_id='i1',activity_seq=1,cutoff=0,text='雨衣'),
            b.submit(request_id='i1',activity_seq=1,cutoff=0,text='外套'))
        sa,sb=await asyncio.gather(wait_state(a,lambda s:bool(s.active_grants)),wait_state(b,lambda s:bool(s.active_grants)))
        ea,eb=sa.active_grants[0],sb.active_grants[0]
        assert ea.id!=eb.id
        with pytest.raises(DomainError):await b.receipt(receipt(ea,1))
        await asyncio.gather(a.receipt(receipt(ea,1)),b.receipt(receipt(eb,1)))
        await asyncio.gather(finish(a),finish(b))
        assert result(t1)['receipt']['effect_id']==ea.id and result(t2)['receipt']['effect_id']==eb.id
    finally:await asyncio.gather(a.close(),b.close())

@pytest.mark.asyncio
async def test_native_chapter_preview_and_handover_are_distinct_complete_receipt_steps():
    from mira.domain.xiahe_chapter import ChapterStage
    calls=[story_call('x.recognize',act='claim_role',text='我就是夏he啊')]
    calls += [story_call('x.story',cue=cue) for cue in ('我记得我们一起挑试印。','那次灯塔是我自己去拍的。','后来你帮我把咖啡杯挪开。')]
    calls += [story_call('x.promise',cue='我答应给你的那张旅行照片，今晚带来了。'),
        GenerationToolCall('preview','show_photo','{"photo_id":"trip_photo"}'),
        story_call('x.gift_offer',offer='gift1'),
        story_call('x.gift_accept',act='accept_gift',text='我收下啦',offer='gift1')]
    turns=[ToolTurn(call) for call in calls];c=character();a=native(turns[0],c=c,tools=Tools(*turns),wait=1)
    seq=0
    try:
        for i,t in enumerate(turns,1):
            text='我就是夏he啊' if i==1 else '我收下啦' if i==8 else '继续吧'
            await a.submit(request_id=f'i{i}',activity_seq=i,cutoff=seq,text=text)
            s=await wait_state(a,lambda s:bool(s.active_grants));e=s.active_grants[0]
            seq+=1;await a.receipt(receipt(e,seq));s=await finish(a)
            for cue in s.active_grants:
                if cue.id!=e.id:seq+=1;await a.receipt(receipt(cue,seq))
            assert result(t)['status']==('pending' if i in (2,3,4,5) else 'shown')
            if i==6:
                assert c.runtime.story.chapter.stage is ChapterStage.PREVIEWED
                assert 'photo_handover' not in dict(c.runtime.story.chapter.milestones)
        assert c.runtime.story.chapter.stage is ChapterStage.COMPLETED
        milestones=dict(c.runtime.story.chapter.milestones)
        assert milestones['photo_preview']!=milestones['photo_handover']
        assert any(e.value=='xiahe_photo_handover' for e in (await a.snapshot()).presented_effects)
    finally:await a.close()

@pytest.mark.asyncio
async def test_native_decline_chat_reinvite_requires_explicit_current_reopen():
    plans=[story_call('t.offer',offer='rain1',cue='要去窗边看雨吗？',target='rain_window'),
        story_call('t.no',act='decline_rain',text='先不去',offer='rain1'),
        text_candidate(),story_call('t.offer',offer='rain2',cue='再去看雨吗？',target='rain_window'),
        story_call('t.offer',act='reopen_rain',text='现在想去看看雨',offer='rain3',cue='那我们去窗边？',target='rain_window'),
        story_call('t.window',act='accept_rain',text='好',offer='rain3',target='rain_window')]
    turns=[ToolTurn(call) for call in plans];c=character();a=native(turns[0],c=c,tools=Tools(*turns));seq=0
    try:
        for i,(t,text) in enumerate(zip(turns,['聊聊下雨','先不去','聊杯咖啡','你继续说','现在想去看看雨','好']),1):
            await a.submit(request_id=f'i{i}',activity_seq=i,cutoff=seq,text=text);s=await finish(a)
            for e in s.active_grants:
                seq+=1;await a.receipt(receipt(e,seq))
            if i==2:assert result(t)['status']=='applied'
            if i==4:assert result(t)['status']=='held' and c.runtime.story.active_offer_id is None
        assert any(e.value=='rain_window' for e in (await a.snapshot()).presented_effects)
    finally:await a.close()

@pytest.mark.asyncio
async def test_native_ready_control_runtime_receipt_updates_actual_appearance_without_fake_review():
    calls=[GenerationToolCall('camera','perform_action','{"action":"raise_camera"}'),
        GenerationToolCall('emotion','set_emotion','{"emotion":"happy"}'),
        GenerationToolCall('scene','set_scene','{"scene":"cafe"}')]
    turns=[ToolTurn(x) for x in calls];c=character();a=native(turns[0],c=c,tools=Tools(*turns));seq=0
    try:
        for i,t in enumerate(turns,1):
            await a.submit(request_id=f'i{i}',activity_seq=i,cutoff=seq,text='继续');s=await finish(a)
            for e in s.active_grants:seq+=1;await a.receipt(receipt(e,seq))
        assert c.runtime.story.last_acknowledged_emotion=='happy'
        assert dict(c.runtime.story.episodes[-1].character_state)['scene_after']=='cafe'
    finally:await a.close()

@pytest.mark.asyncio
async def test_native_optional_continuation_error_keeps_issued_independent_commentary():
    class FailingContinuation(ToolTurn):
        async def continue_after_tool(self,result,current_context):
            self.results.append((result,current_context));raise RuntimeError('synthetic continuation failure')
    t=FailingContinuation(replace(GenerationToolCall('x','set_outfit','{"outfit":"amber_raincoat"}'),
        commentary=text_candidate()));a=native(t)
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text='看看雨衣');s=await finish(a)
        assert s.last_error=='generation_failed' and s.sealed
        assert any(e.kind is EffectKind.SUBTITLE for e in s.active_grants)
        assert len(t.results)==1 and result(t)['status']=='pending'
        await a.stop(activity_seq=2,cutoff=0);assert not (await a.snapshot()).active_grants
    finally:await a.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('optional',[{'story_proposal':{}},{'affect_proposal':{}},
    {'pose':'not_a_known_control'},{'scene':'rain_window'}])
async def test_native_real_wire_known_optional_fields_hold_without_losing_dialogue(optional):
    from tests.contracts.test_direct_codex_responses import backend,response,snapshot_message
    from tests.contracts.test_direct_luna_tools import wire
    payload={'effects':[{'kind':'subtitle','value':'继续聊吧。'}], 'story_proposal':None,'affect_proposal':None}
    if 'pose' in optional or 'scene' in optional:
        kind=next(iter(optional));payload['effects'].append({'kind':kind,'value':optional[kind]})
    else:payload.update(optional)
    async def handle(_):return response(wire([snapshot_message(json.dumps(payload,ensure_ascii=False))]))
    direct,source,requests=backend(handle,request_limit=2);a=native(None,c=character(),tools=direct)
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text='随便聊聊');s=await finish(a)
        assert s.last_error is None and [e.value for e in s.active_grants]==['继续聊吧。']
        assert len(requests)==source.calls==1 and not a._character_runtime.runtime.story.chapter.role_active
    finally:await a.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('choice',['ordinary','exit'])
async def test_native_unused_confirmation_is_consumed_by_next_dialogue_or_explicit_exit(choice):
    ask=ToolTurn(story_call('x.ask_role',act='ask_role_confirmation',text='我是谁呀',cue='你想在这段相处里做夏禾吗？'))
    second=ToolTurn(text_candidate() if choice=='ordinary' else story_call('x.exit',act='exit_role',text='退出角色'))
    c=character();a=native(ask,c=c,tools=Tools(ask,second));seq=0
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text='我是谁呀');s=await finish(a)
        for e in s.active_grants:seq+=1;await a.receipt(receipt(e,seq))
        assert c._native_role_question is not None
        await a.submit(request_id='i2',activity_seq=2,cutoff=seq,text='咖啡真香' if choice=='ordinary' else '退出角色')
        await finish(a);assert c._native_role_question is None and not c.runtime.story.chapter.role_active
    finally:await a.close()
