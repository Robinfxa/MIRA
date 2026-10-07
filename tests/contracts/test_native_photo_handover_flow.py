"""Recovered synthetic actual-wire tests; no live model/device claim."""
import asyncio
import json
from dataclasses import replace
import pytest

from mira.application.ports.generation_tools import GenerationToolCall
from mira.domain.models import EffectKind
from mira.domain.xiahe_chapter import CHAPTER_CANON, ChapterStage
from tests.contracts.test_native_chapter_wire import WireSession
from tests.contracts.test_native_character_tools import native, story_call
from tests.contracts.test_native_story_dialogue_boundary import dialogue
from tests.contracts.test_luna_tool_actor import ToolTurn, Tools, wait_state, result
from tests.contracts.test_development_review_composition import finish
from tests.contracts.test_authored_photo_events import receipt
from tests.contracts.test_xiahe_chapter_actor import character

MEMORY_OFFER = '夏禾，真的是你。那次挑试印，你问我哪张让我想起按快门的那一秒，我一直记着。这张灯塔照片我终于选好了，送给你，好吗？'
SOLO = '第一次独自去海边，背带老被风吹进镜头。我后来一手按住它，一手拍灯塔，跟风讲道理没用。要看看那张吗？'
PHOTO = GenerationToolCall('preview','show_photo','{"photo_id":"trip_photo"}')


class Flow(WireSession):
    async def handle(self, request):
        self.dialogue = self.spoken
        return await super().handle(request)

    async def say(self,text,plan,spoken='我们接着聊。',**kwargs):
        self.spoken = spoken
        return await self.turn(text,plan,**kwargs)

    async def recognize_offer(self,offer='gift'):
        return await self.say('我是夏he',story_call('x.recognize',act='claim_role',
            text='我是夏he',offer=offer,cue='INERT_CONTROL_SENTINEL'),MEMORY_OFFER)


@pytest.mark.asyncio
async def test_interested_visitor_recognition_offer_one_acceptance_and_actual_handover():
    s=Flow()
    try:
        await s.say('我想了解你',SOLO)
        assert not s.c.runtime.story.chapter.role_active
        r,state=await s.recognize_offer()
        chapter=s.c.runtime.story.chapter
        assert r['status']=='shown' and chapter.role_active
        assert chapter.stage is ChapterStage.GIFT_OFFERED
        assert set(dict(chapter.milestones))=={'recognition','gift_offer'}
        offer=next(e for e in state.presented_effects if e.value==MEMORY_OFFER)
        assert chapter.gift_offer_effect_id==offer.id
        assert not any(e.value=='INERT_CONTROL_SENTINEL' for e in state.issued_effects)
        assert len(s.requests)==3
        assert not s.prompts[-1]['facts']['character_story']['chapter']['completed']
        r,state=await s.say('好，我收下',story_call('x.gift_accept',act='accept_gift',
            text='好，我收下',offer='gift'),'给你。这次不再塞回纸袋了。')
        assert r['status']=='shown'
        assert s.c.runtime.story.chapter.stage is ChapterStage.COMPLETED
        assert s.prompts[-1]['facts']['character_story']['chapter']['completed']
        assert sum(e.value=='xiahe_photo_handover' for e in state.presented_effects)==1
        assert len(s.requests)==5
        for request in s.requests:
            body=json.loads(request.content)
            if any(i.get('type')=='function_call_output' for i in body['input']):
                assert body['tools']==[] and body['tool_choice']=='none'
    finally: await s.close()


@pytest.mark.asyncio
async def test_recognition_alone_releases_shared_canon_without_narration_milestones():
    s=Flow()
    try:
        await s.say('我是夏禾',story_call('x.recognize',act='claim_role',text='我是夏禾'))
        facts=s.prompts[-1]['facts'];raw=json.dumps(facts,ensure_ascii=False)
        assert all(raw.count(text)==1 for _,_,text in CHAPTER_CANON)
        assert set(dict(s.c.runtime.story.chapter.milestones))=={'recognition'}
        assert 'x.gift_offer' in facts['character_story']['chapter']['allowed_next']
        assert facts['first_person_dialogue']['speaker_contract']['real_user_history'] is False
        r,_=await s.say('你是不是有东西要给我',story_call('x.gift_offer',offer='direct'),MEMORY_OFFER)
        assert r['status']=='shown' and s.c.runtime.story.chapter.stage is ChapterStage.GIFT_OFFERED
    finally: await s.close()


@pytest.mark.asyncio
async def test_recognition_receipt_precedes_offer_and_offer_needs_own_real_subtitle_receipt():
    t=ToolTurn(story_call('x.recognize',act='claim_role',text='我是夏he',offer='bound',cue='INERT_BRIEF'),continue_gate=True)
    t.candidate=dialogue(MEMORY_OFFER)
    c=character();a=native(t,c=c,wait=1)
    try:
        await a.submit(request_id='claim',activity_seq=1,cutoff=0,text='我是夏he')
        state=await wait_state(a,lambda s:any(e.value=='xiahe_recognition' for e in s.active_grants))
        scene=next(e for e in state.active_grants if e.value=='xiahe_recognition')
        assert not c.runtime.story.chapter.role_active and not t.results
        await a.receipt(receipt(scene,1));await asyncio.wait_for(t.continued.wait(),.5)
        assert c.runtime.story.chapter.role_active and c.runtime.story.chapter.active_gift_offer_id is None
        t.release.set();state=await finish(a)
        cue=next(e for e in state.active_grants if e.value==MEMORY_OFFER)
        assert c.runtime.story.chapter.pending.transition=='x.gift_offer'
        assert c.runtime.story.chapter.active_gift_offer_id is None
        await a.receipt(receipt(cue,2))
        assert c.runtime.story.chapter.active_gift_offer_id=='bound'
        assert c.runtime.story.chapter.gift_offer_effect_id==cue.id
        assert set(dict(c.runtime.story.chapter.milestones))=={'recognition','gift_offer'}
    finally: t.release.set();await a.close()


@pytest.mark.asyncio
async def test_initial_waiting_and_unfulfilled_concern_are_superseded_by_typed_current_receipts():
    s=Flow()
    try:
        original=next(e for e in s.c.runtime.definition.canon.entries if e.entry_id=='canon.waiting')
        await s.recognize_offer()
        memory=s.prompts[-1]['facts']['character_story']['first_person_memory']
        assert not any(r['source_id']=='canon.waiting' for r in memory['current_intentions_and_concerns'])
        row=next(r for r in memory['initial_scene_intentions'] if r['source_id']=='canon.waiting')
        assert row['temporal_type']=='initial_scene_intention'
        assert row['resolved_by_chapter_milestone']=='recognition'
        assert row['text']==original.first_person_text
        assert memory['provenance_groups'][row['provenance_index']]['source_version']==original.source_version
        await s.say('好',story_call('x.gift_accept',act='accept_gift',text='好',offer='gift'),'给你。')
        memory=s.prompts[-1]['facts']['character_story']['first_person_memory']
        row=next(r for r in memory['initial_scene_intentions'] if r['source_id']=='canon.waiting')
        assert row['resolved_by_chapter_milestone']=='photo_handover'
        assert not any(r['source_id'] in {'canon.waiting','canon.personal_stakes'} for r in memory['current_intentions_and_concerns'])
        assert next(e for e in s.c.runtime.definition.canon.entries if e.entry_id=='canon.waiting')==original
    finally: await s.close()


@pytest.mark.parametrize('text,allowed', [('我是夏禾',True),('我不是夏禾',False),('他说“我是夏禾”',False),('如果我是夏禾呢',False),('“我是夏禾”这句台词是什么意思',False)])
def test_existing_legacy_local_role_fallback_has_no_undefined_native_keyword(text,allowed):
    from mira.application.actor_chapter import local_role_proposal
    from mira.domain.story import parse_story_proposal
    proposal=parse_story_proposal({'transition_id':'x.recognize','signal':'recognize_xiahe',
        'target_capabilities':['chapter.xiahe.recognition'],
        'input_act':{'kind':'claim_role','evidence_text':text,'role_name':'夏禾'}},input_id='legacy',epoch=1)
    assert local_role_proposal(proposal,text) is allowed


@pytest.mark.asyncio
async def test_one_natural_question_then_exact_confirmation_can_recognize_and_offer():
    s=Flow()
    try:
        _,state=await s.say('你觉得我是夏he吗',story_call('x.ask_role',act='ask_role_confirmation',
            text='你觉得我是夏he吗'),'夏禾？真的是你？')
        question=next(e for e in state.presented_effects if e.value=='夏禾？真的是你？')
        assert not s.c.runtime.story.chapter.role_active
        await s.say('对，是我',story_call('x.recognize',act='confirm_role',text='对，是我',
            reference=question.id,offer='confirmed'),MEMORY_OFFER)
        assert s.c.runtime.story.chapter.active_gift_offer_id=='confirmed'
        r,_=await s.say('好啊',story_call('x.gift_accept',act='accept_gift',text='好啊',offer='confirmed'),'给你。')
        assert r['status']=='shown' and s.c.runtime.story.chapter.stage is ChapterStage.COMPLETED
        assert len(s.requests)==6
    finally: await s.close()


@pytest.mark.asyncio
async def test_early_visible_preview_reuse_is_optional_and_never_gift_evidence():
    s=Flow()
    try:
        r,_=await s.say('看看灯塔照片',PHOTO,'就是这张。');old_id=r['receipt']['effect_id']
        assert not s.c.runtime.story.chapter.milestones
        await s.recognize_offer()
        r,state=await s.say('让我再看看那张',PHOTO,'这张可以慢慢看。')
        chapter=s.c.runtime.story.chapter
        assert r['status']=='reused' and r['receipt']['effect_id']==old_id
        assert chapter.preview_reference.mode=='reused_visible' and chapter.preview_reference.effect_id==old_id
        assert chapter.stage is ChapterStage.GIFT_OFFERED
        assert 'photo_handover' not in dict(chapter.milestones)
        assert sum(e.kind is EffectKind.MEDIA for e in state.issued_effects)==1
        r,_=await s.say('好',story_call('x.gift_accept',act='accept_gift',text='好',offer='gift'),'给你。')
        assert r['receipt']['effect_id']!=old_id and s.c.runtime.story.chapter.stage is ChapterStage.COMPLETED
    finally: await s.close()


@pytest.mark.asyncio
async def test_detour_back_raincoat_before_and_window_after_preserve_finite_gift():
    s=Flow()
    try:
        await s.say('穿上雨衣',GenerationToolCall('coat','set_outfit','{"outfit":"amber_raincoat"}'),'穿好了。')
        await s.recognize_offer();before=s.c.runtime.story.chapter
        await s.say('先聊聊咖啡','这杯闻起来有一点坚果香。')
        assert s.c.runtime.story.chapter==before
        await s.say('回到照片，我收下',story_call('x.gift_accept',act='accept_gift',text='回到照片，我收下',offer='gift'),'给你。')
        await s.say('还想看看雨',story_call('t.offer',offer='rain-after',target='rain_window'),'要一起看看窗外的雨吗？')
        r,state=await s.say('好',story_call('t.window',act='accept_rain',text='好',offer='rain-after',target='rain_window'),'窗上的雨线把灯光拉得好长。')
        assert r['status']=='shown' and s.c.runtime.story.current_outfit=='amber_raincoat'
        assert s.c.runtime.story.chapter.stage is ChapterStage.COMPLETED
        assert any(e.value=='rain_window' for e in state.presented_effects)
    finally: await s.close()


@pytest.mark.asyncio
async def test_refusal_no_penalty_and_explicit_reopen_before_current_acceptance():
    s=Flow()
    try:
        await s.recognize_offer();affect=s.c.runtime.affect
        r,_=await s.say('暂时不要',story_call('x.gift_decline',act='decline_gift',text='暂时不要',offer='gift'),'好，那我先留着。')
        assert r['status']=='applied' and s.c.runtime.story.chapter.stage is ChapterStage.GIFT_DECLINED
        await s.say('聊聊别的','窗上的雨点越来越密了。')
        r,_=await s.say('继续说',story_call('x.gift_offer',offer='uninvited'))
        assert r['status']=='held' and s.c.runtime.story.chapter.active_gift_offer_id is None
        r,_=await s.say('现在我想收下照片',story_call('x.gift_offer',act='reopen_gift',text='现在我想收下照片',offer='reopened'),'那送给你，好吗？')
        assert r['status']=='shown'
        r,_=await s.say('好',story_call('x.gift_accept',act='accept_gift',text='好',offer='reopened'),'给你。')
        assert r['status']=='shown' and s.c.runtime.story.chapter.stage is ChapterStage.COMPLETED
        assert s.c.runtime.affect==affect
    finally: await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['我不是夏禾','他说“我是夏he”','如果我是夏禾呢','“我是夏禾”这句台词是什么意思'])
async def test_negation_or_quotation_without_typed_model_claim_never_auto_recognizes(text):
    s=Flow()
    try:
        r,state=await s.say(text,'我们接着聊。')
        assert r is None and not s.c.runtime.story.chapter.role_active and not s.c.runtime.story.chapter.milestones
        assert not any(e.kind is EffectKind.SCENE for e in state.issued_effects)
        body=json.loads(s.requests[0].content)
        desc=next(t['description'] for t in body['tools'] if t['name']=='advance_story')
        assert 'Quoted' in desc and 'negated' in desc
        assert 'Interest never assigns the friend role' in body['instructions']
    finally: await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('phase',['before_recognition','before_continuation','before_offer_receipt'])
async def test_stop_each_compound_boundary_cannot_revive_offer(phase):
    from mira.domain.errors import DomainError
    t=ToolTurn(story_call('x.recognize',act='claim_role',text='我是夏禾',offer='stopped'),continue_gate=True)
    t.candidate=dialogue(MEMORY_OFFER);c=character();a=native(t,c=c,wait=1);cutoff=0;late=None
    try:
        await a.submit(request_id='claim',activity_seq=1,cutoff=0,text='我是夏禾')
        state=await wait_state(a,lambda s:any(e.value=='xiahe_recognition' for e in s.active_grants))
        scene=next(e for e in state.active_grants if e.value=='xiahe_recognition')
        if phase!='before_recognition':
            cutoff=1;await a.receipt(receipt(scene,cutoff));await asyncio.wait_for(t.continued.wait(),.5)
        else: late=scene
        if phase=='before_offer_receipt':
            t.release.set();state=await finish(a);late=next(e for e in state.active_grants if e.value==MEMORY_OFFER)
        await a.stop(activity_seq=2,cutoff=cutoff);t.release.set();state=await finish(a)
        assert c.runtime.story.chapter.active_gift_offer_id is None and c.runtime.story.chapter.pending is None
        assert 'gift_offer' not in dict(c.runtime.story.chapter.milestones)
        assert 'photo_handover' not in dict(c.runtime.story.chapter.milestones)
        assert c.runtime.story.chapter.role_active is (phase!='before_recognition')
        assert not state.active_grants
        if late is not None:
            with pytest.raises(DomainError): await a.receipt(receipt(late,cutoff+1))
    finally: t.release.set();await a.close()


@pytest.mark.asyncio
async def test_missing_recognition_receipt_does_not_retroactively_promote_prior_subtitle():
    t=ToolTurn(story_call('x.recognize',act='claim_role',text='我是夏禾',offer='late'))
    t.candidate=dialogue('让我再看看你。');c=character();a=native(t,c=c)
    try:
        await a.submit(request_id='claim',activity_seq=1,cutoff=0,text='我是夏禾');state=await finish(a)
        assert result(t)['status']=='pending' and not c.runtime.story.chapter.role_active
        cue=next(e for e in state.active_grants if e.kind is EffectKind.SUBTITLE)
        scene=next(e for e in state.active_grants if e.value=='xiahe_recognition')
        await a.receipt(receipt(cue,1));await a.receipt(receipt(scene,2))
        assert c.runtime.story.chapter.role_active and c.runtime.story.chapter.active_gift_offer_id is None
        assert set(dict(c.runtime.story.chapter.milestones))=={'recognition'}
    finally: await a.close()


@pytest.mark.asyncio
async def test_failed_continuation_keeps_only_actual_recognition():
    class Failed(ToolTurn):
        async def continue_after_tool(self,result,current_context):
            self.results.append((result,current_context));raise RuntimeError('synthetic failure')
    t=Failed(story_call('x.recognize',act='claim_role',text='我是夏禾',offer='failed'));c=character();a=native(t,c=c,wait=1)
    try:
        await a.submit(request_id='claim',activity_seq=1,cutoff=0,text='我是夏禾')
        state=await wait_state(a,lambda s:bool(s.active_grants))
        await a.receipt(receipt(next(e for e in state.active_grants if e.value=='xiahe_recognition'),1))
        state=await finish(a)
        assert state.last_error=='generation_failed'
        assert c.runtime.story.chapter.active_gift_offer_id is None
        assert 'gift_offer' not in dict(c.runtime.story.chapter.milestones)
    finally: await a.close()


@pytest.mark.asyncio
async def test_checkpoint_reentry_keeps_history_but_needs_current_role_and_offer():
    from mira.application.story import StoryRuntime
    from mira.application.actor_story import SessionCharacterRuntime
    s=Flow()
    try:
        await s.recognize_offer();saved=s.c.runtime.snapshot()
        restored=StoryRuntime.from_snapshot(s.c.runtime.definition,saved)
        assert not restored.story.chapter.role_active and restored.story.chapter.active_gift_offer_id is None
        assert restored.story.chapter.stage is ChapterStage.RECOGNIZED
        assert restored.story.chapter.milestones==saved.story.chapter.milestones
        assert restored.story.episodes==saved.story.episodes
        assert 'photo_preview' not in dict(restored.story.chapter.milestones)
        t=ToolTurn(story_call('x.gift_accept',act='accept_gift',text='好',offer='gift'))
        c=SessionCharacterRuntime(restored,character().readiness);a=native(t,c=c)
        a._state=replace(a._state,output_epoch=restored.story.epoch)
        try:
            await a.submit(request_id='new-visit',activity_seq=1,cutoff=0,text='好');state=await finish(a)
            assert result(t)['status']=='held' and 'photo_handover' not in dict(c.runtime.story.chapter.milestones)
            assert not any(e.value=='xiahe_photo_handover' for e in state.issued_effects)
        finally: await a.close()
    finally: await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('optional',['x.story','x.promise','show_photo'])
async def test_optional_recall_preview_cannot_clear_stop_suspension(optional):
    s=Flow()
    try:
        await s.recognize_offer();s.epoch+=1;await s.a.stop(activity_seq=s.epoch,cutoff=s.seq)
        assert s.c.runtime.story.chapter.suspended
        await s.say('先聊往事',PHOTO if optional=='show_photo' else story_call(optional),'那次我们把试印按明暗排了一遍。')
        assert s.c.runtime.story.chapter.suspended and s.c.runtime.story.chapter.active_gift_offer_id is None
        r,_=await s.say('接着聊吧',story_call('x.gift_offer',offer='not-reopened'))
        assert r['status']=='held'
        r,_=await s.say('现在想收下照片',story_call('x.gift_offer',act='reopen_gift',text='现在想收下照片',offer='reopened'),'送给你，好吗？')
        assert r['status']=='shown' and not s.c.runtime.story.chapter.suspended
    finally: await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('completed',[False,True])
@pytest.mark.parametrize('optional',['x.story','x.promise','show_photo'])
async def test_optional_recall_preview_preserves_offered_completed_state(completed,optional):
    s=Flow()
    try:
        await s.recognize_offer()
        if completed: await s.say('好',story_call('x.gift_accept',act='accept_gift',text='好',offer='gift'),'给你。')
        before=s.c.runtime.story.chapter
        await s.say('刚才的往事呢',PHOTO if optional=='show_photo' else story_call(optional),'我们把试印按明暗排了一遍。')
        after=s.c.runtime.story.chapter
        assert after.stage is (ChapterStage.COMPLETED if completed else ChapterStage.GIFT_OFFERED)
        assert (after.active_gift_offer_id,after.gift_offer_effect_id,after.gift_offer_effect_digest)==(before.active_gift_offer_id,before.gift_offer_effect_id,before.gift_offer_effect_digest)
        assert dict(after.milestones).get('photo_handover')==dict(before.milestones).get('photo_handover')
    finally: await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('malformed',['too_long','split'])
async def test_only_one_complete_bounded_subtitle_can_bind_compound_offer(malformed):
    from mira.application.contracts import CandidateRange,EffectProposal
    t=ToolTurn(story_call('x.recognize',act='claim_role',text='我是夏禾',offer='invalid'))
    t.candidate=dialogue('字'*501) if malformed=='too_long' else CandidateRange((
        EffectProposal(EffectKind.SUBTITLE,'夏禾，真的是你。'),EffectProposal(EffectKind.SUBTITLE,'送给你好吗？')),'synthetic-split')
    c=character();a=native(t,c=c,wait=1)
    try:
        await a.submit(request_id='claim',activity_seq=1,cutoff=0,text='我是夏禾')
        state=await wait_state(a,lambda s:bool(s.active_grants))
        await a.receipt(receipt(next(e for e in state.active_grants if e.value=='xiahe_recognition'),1))
        state=await finish(a)
        for seq,e in enumerate((e for e in state.active_grants if e.kind is EffectKind.SUBTITLE),2): await a.receipt(receipt(e,seq))
        assert c.runtime.story.chapter.role_active and c.runtime.story.chapter.active_gift_offer_id is None
        assert c.runtime.story.chapter.pending is None and 'gift_offer' not in dict(c.runtime.story.chapter.milestones)
    finally: await a.close()


@pytest.mark.asyncio
async def test_handover_pending_is_not_completed_and_duplicate_acceptance_cannot_repeat_gift():
    s=Flow()
    try:
        await s.recognize_offer()
        r,state=await s.say('收下',story_call('x.gift_accept',act='accept_gift',text='收下',offer='gift'),'我把照片递过来。',acknowledge=False)
        assert r['status']=='pending' and not s.prompts[-1]['facts']['character_story']['chapter']['completed']
        e=next(e for e in state.active_grants if e.value=='xiahe_photo_handover');s.seq+=1;await s.a.receipt(receipt(e,s.seq))
        assert s.c.runtime.story.chapter.stage is ChapterStage.COMPLETED
        r,state=await s.say('再给我',story_call('x.gift_accept',act='accept_gift',text='再给我',offer='gift'),'照片已经交给你了。')
        assert r['status']=='held' and sum(e.value=='xiahe_photo_handover' for e in state.issued_effects)==1
    finally: await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('route_name',['chatgpt_subscription','openai_api'])
async def test_all_shared_canon_recent_dialogue_and_large_recall_fit_real_tool_continuation_wire(route_name,tmp_path):
    from mira.adapters.generation.direct_codex_responses import ResponsesRoute,DirectResponsesLimits
    from mira.application.generation_tool_execution import tool_definitions,tool_result
    from mira.application.memory_context import valid_context_packet
    from mira.domain.models import SessionState
    from tests.contracts.test_role_canon_speaker import context,recognize
    from tests.contracts.test_xiahe_chapter_actor import prepare,complete
    from tests.contracts.test_actor_memory_recall import packet,valid_past_line
    from tests.contracts.test_character_prompt_refinement import backend
    from tests.contracts.test_direct_codex_responses import response
    from tests.contracts.test_direct_luna_tools import wire,tool,message
    c=character();recognize(c)
    for epoch in (2,3,4):
        _,effects=prepare(c,'x.story',epoch);complete(c,effects,epoch*2)
    ctx=replace(context(c,long=True),character_assets=c.readiness)
    memory=packet(ctx.user_text,past_candidates=tuple(valid_past_line('synthetic-'+str(i)+':'+'m'*4000,
        evidence_id='synthetic-'+str(i)) for i in range(7)))
    assert valid_context_packet(memory,request_text=ctx.user_text)
    ctx=replace(ctx,memory_packet=memory)
    defs=tool_definitions(ctx,SessionState('capacity','client'),None,review_available=True,image_task_count=0,max_effects=128,native_authority=True)
    planned=story_call('x.gift_offer',offer='capacity-offer')
    async def handle(request):
        body=json.loads(request.content)
        if any(i.get('type')=='function_call_output' for i in body['input']): return response(wire([message('这张照片，送给你好吗？')]))
        return response(wire([tool(name=planned.name,arguments=planned.arguments_json)]))
    direct,source,requests=backend(handle,route=ResponsesRoute(route_name),request_limit=2,native_character_tools=True,speech_enabled=False)
    turn=direct.open_tool_turn(ctx,defs)
    try:
        call=await turn.start();await turn.continue_after_tool(tool_result(call,'pending'),ctx)
    finally: turn.close()
    sizes=[]
    for request in requests:
        body=json.loads(request.content);payloads=[i['content'][0]['text'] for i in body['input'] if i.get('role')=='user']
        facts=json.loads(payloads[-1])['facts']
        assert len(facts['memory_evidence']['past_candidates'])==7
        assert all(json.dumps(facts,ensure_ascii=False).count(text)==1 for _,_,text in CHAPTER_CANON)
        assert len(body['instructions'].encode())<12000
        assert all(len(p.encode())<=DirectResponsesLimits().max_prompt_bytes==65536 for p in payloads)
        assert len(request.content)<=131072
        sizes.append({'instructions':len(body['instructions'].encode()),'payloads':[len(p.encode()) for p in payloads],'http_body':len(request.content)})
    assert len(requests)==source.calls==2
    (tmp_path/'wire-sizes.json').write_text(json.dumps(sizes,indent=2))
