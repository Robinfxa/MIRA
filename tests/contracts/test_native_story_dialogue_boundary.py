"""Control briefs cannot enter presentation, speech, or receipted history."""
import asyncio
import hashlib
from dataclasses import asdict, replace

import pytest

from mira.application.contracts import CandidateRange, EffectProposal
from mira.domain.models import EffectKind
from tests.contracts.test_authored_photo_events import receipt
from tests.contracts.test_development_review_composition import finish
from tests.contracts.test_luna_tool_actor import ToolTurn, Tools, result
from tests.contracts.test_native_character_tools import native, story_call
from tests.contracts.test_xiahe_chapter_actor import character, prepare, complete


def recognized(*, promise=False):
    c = character()
    _, effects = prepare(c, 'x.recognize', 1, '我是夏禾', act='claim_role')
    complete(c, effects)
    epoch = 1
    if promise:
        for epoch in range(2, 5):
            _, effects = prepare(c, 'x.story', epoch)
            complete(c, effects)
    return c, epoch


def dialogue(text, *, voice=False):
    kinds = (EffectKind.SUBTITLE, EffectKind.SPEECH) if voice else (EffectKind.SUBTITLE,)
    return CandidateRange(tuple(EffectProposal(k, text) for k in kinds), 'synthetic-character-dialogue')


@pytest.mark.asyncio
@pytest.mark.parametrize('transition,brief,spoken', [
    ('x.story', '告诉夏禾，电子照片发过，纸质照片还没交付。', '我一直想把纸质照片交给你。'),
    ('x.story', 'Internal planning data: preserve the first shared memory.', '我记得我们一起挑试印的那次。'),
    ('x.story', '我今晚想把照片送给你。', '我还记得我们挑试印的那个下午。'),
    ('x.promise', '回应夏禾问照片是否要给她；不要暗示已经完成交付。', '我今晚带来了，想把它送给你。'),
    ('x.ask_role', 'Ask for confirmation of the fictional role.', '你是夏禾吗？'),
    ('t.offer', 'Invite the user to the rain window.', '要一起看看窗外的雨吗？'),
])
async def test_control_brief_never_granted_and_dialogue_does_not_wait_for_its_own_receipt(transition, brief, spoken):
    c, epoch = recognized(promise=transition == 'x.promise') if transition in ('x.story', 'x.promise') else (character(), 0)
    user = '你继续说吧'
    call = story_call(transition, cue=brief, offer='rain-current' if transition == 't.offer' else '',
        target='rain_window' if transition == 't.offer' else 'none',
        act='ask_role_confirmation' if transition == 'x.ask_role' else 'none',
        text=user if transition == 'x.ask_role' else '')
    turn = ToolTurn(call, continue_gate=True)
    turn.candidate = dialogue(spoken)
    a = native(turn, c=c, wait=2)
    a._state = replace(a._state, output_epoch=epoch)
    try:
        await a.submit(request_id='dialogue', activity_seq=epoch + 1, cutoff=0, text=user)
        await asyncio.wait_for(turn.continued.wait(), .25)
        before = await a.snapshot()
        assert not before.issued_effects
        assert result(turn)['status'] == 'pending'
        assert result(turn)['phase'] == 'awaiting_dialogue'
        assert not result(turn)['shown']
        turn.release.set()
        state = await finish(a)
        assert state.last_error is None
        assert [e.value for e in state.issued_effects] == [spoken]
        cue = state.active_grants[0]
        if transition in ('x.story', 'x.promise'):
            assert c.runtime.story.chapter.pending.cue_digest == hashlib.sha256(spoken.encode()).hexdigest()
            milestone = 'photo_promise' if transition == 'x.promise' else 'old_friend'
            assert milestone not in dict(c.runtime.story.chapter.milestones)
        await a.receipt(receipt(cue, 1))
        state = await a.snapshot()
        assert [e.value for e in state.presented_effects] == [spoken]
        if transition in ('x.story', 'x.promise'):
            assert milestone in dict(c.runtime.story.chapter.milestones)
        if transition == 't.offer':
            assert c.runtime.story.active_offer_cue == spoken
        if transition == 'x.ask_role':
            assert c._native_role_question[0] == cue.id
    finally:
        turn.release.set()
        await a.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('fence', ['stop', 'new_input', 'close'])
async def test_cancelled_dialogue_binding_cannot_revive_story_or_control_text(fence):
    c, epoch = recognized()
    turn = ToolTurn(story_call('x.story', cue='INTERNAL_CONTROL_SENTINEL'),
        continue_gate=True, ignore_cancel=True)
    turn.candidate = dialogue('我记得我们一起挑试印。')
    replacement = ToolTurn(dialogue('我们聊聊咖啡吧。'))
    a = native(turn, c=c, tools=Tools(turn, replacement), wait=.01)
    a._state = replace(a._state, output_epoch=epoch)
    try:
        await a.submit(request_id='first', activity_seq=2, cutoff=0, text='接着说')
        await asyncio.wait_for(turn.continued.wait(), .5)
        if fence == 'stop':
            await a.stop(activity_seq=3, cutoff=0)
        elif fence == 'new_input':
            await a.submit(request_id='second', activity_seq=3, cutoff=0, text='聊聊咖啡')
        else:
            await a.close()
        turn.release.set()
        state = await finish(a)
        assert all(e.value != 'INTERNAL_CONTROL_SENTINEL' for e in state.issued_effects)
        assert 'old_friend' not in dict(c.runtime.story.chapter.milestones)
        assert c.runtime.story.chapter.pending is None
        assert all(e.value != '我记得我们一起挑试印。' for e in state.active_grants)
    finally:
        turn.release.set()
        await a.close()


@pytest.mark.asyncio
async def test_held_story_keeps_ordinary_dialogue_without_handover_or_control_cue():
    turn = ToolTurn(story_call('x.promise', cue='UNMET_STORY_CONTROL_SENTINEL'))
    turn.candidate = dialogue('先陪我聊一会儿吧。')
    c = character(); a = native(turn, c=c)
    try:
        await a.submit(request_id='held', activity_seq=1, cutoff=0, text='继续')
        state = await finish(a)
        assert result(turn)['status'] == 'held'
        assert state.last_error is None
        assert [e.value for e in state.issued_effects] == ['先陪我聊一会儿吧。']
        assert not c.runtime.story.chapter.milestones
    finally:
        await a.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['overlong', 'missing_subtitle', 'empty', 'malformed', 'failure'])
async def test_invalid_or_missing_dialogue_never_advances_optional_story(kind):
    c, epoch = recognized()
    class Continuation(ToolTurn):
        async def continue_after_tool(self, result, context):
            value = await super().continue_after_tool(result, context)
            if kind == 'failure': raise RuntimeError('synthetic continuation failure')
            return value
    turn = Continuation(story_call('x.story', cue='CONTROL_MUST_STAY_INERT'))
    turn.candidate = {
        'overlong': dialogue('长' * 501),
        'missing_subtitle': CandidateRange((EffectProposal(EffectKind.SPEECH,'我想起那回。'),),'synthetic'),
        'empty': CandidateRange((), 'synthetic'),
        'malformed': CandidateRange((EffectProposal(EffectKind.SCENE,'xiahe_photo_handover'),),'synthetic'),
        'failure': dialogue('未生成完成'),
    }[kind]
    a = native(turn,c=c);a._state=replace(a._state,output_epoch=epoch)
    try:
        await a.submit(request_id='bad',activity_seq=2,cutoff=0,text='接着说')
        state=await finish(a)
        for seq,e in enumerate(state.active_grants,1):
            if e.kind is EffectKind.SUBTITLE: await a.receipt(receipt(e,seq))
        assert c.runtime.story.chapter.pending is None
        assert 'old_friend' not in dict(c.runtime.story.chapter.milestones)
        assert all(e.value!='CONTROL_MUST_STAY_INERT' for e in state.issued_effects)
        if kind=='overlong':
            assert state.last_error is None and [e.value for e in state.active_grants]==['长'*501]
    finally:await a.close()


@pytest.mark.asyncio
async def test_fast_own_receipt_before_plan_seal_keeps_dialogue_and_is_idempotent():
    c,epoch=recognized();spoken='我记得我们一起挑试印。'
    turn=ToolTurn(story_call('x.story',cue='CONTROL_BRIEF'));turn.candidate=dialogue(spoken)
    a=native(turn,c=c);a._state=replace(a._state,output_epoch=epoch)
    reached,release=asyncio.Event(),asyncio.Event()
    original=a._ensure_context_current
    async def gate(context):
        if any(e.value==spoken for e in a._state.active_grants) and not a._state.sealed:
            reached.set();await release.wait()
        await original(context)
    a._ensure_context_current=gate
    try:
        await a.submit(request_id='fast',activity_seq=2,cutoff=0,text='接着说')
        await asyncio.wait_for(reached.wait(),.5)
        state=await a.snapshot();assert not state.sealed
        cue=state.active_grants[0];ack=receipt(cue,1)
        await a.receipt(ack)
        revised=c.runtime.story.chapter
        await a.receipt(ack)
        assert c.runtime.story.chapter==revised
        release.set();state=await finish(a)
        assert state.last_error is None and state.sealed
        assert 'old_friend' in dict(c.runtime.story.chapter.milestones)
        assert [e.value for e in state.presented_effects]==[spoken]
    finally:
        release.set();await a.close()


@pytest.mark.asyncio
async def test_only_real_dialogue_reaches_tts_archive_and_next_turn_context(tmp_path):
    from mira.application.actor_conversation import SessionConversationBinding
    from mira.application.ports.media import AudioPacket
    from tests.contracts.test_actor_conversation_archive import archive
    c,epoch=recognized();spoken='我记得我们一起挑试印。';control='INTERNAL_BRIEF_NEVER_SPOKEN'
    turn=ToolTurn(story_call('x.story',cue=control));turn.candidate=dialogue(spoken,voice=True)
    next_turn=ToolTurn(dialogue('继续聊吧。'));tools=Tools(turn,next_turn)
    a=native(turn,c=c,tools=tools);a._state=replace(a._state,output_epoch=epoch)
    store=await archive(tmp_path/'synthetic.sqlite')
    binding=SessionConversationBinding(store,authorize_transcript_persistence=True,close_archive_on_actor_close=True)
    a._conversation_binding=binding
    class Speech:
        def __init__(self):self.texts=[]
        async def synthesize(self,text,stream_id):
            self.texts.append(text)
            yield AudioPacket(stream_id,0,24000,b'\x00\x00'*24)
    speech=Speech();a._speech_synthesis=speech
    try:
        await a.submit(request_id='voice',activity_seq=2,cutoff=0,text='接着说')
        state=await finish(a)
        cue=next(e for e in state.active_grants if e.kind is EffectKind.SUBTITLE)
        audio=next(e for e in state.active_grants if e.kind is EffectKind.SPEECH)
        await a.receipt(receipt(cue,1))
        operation=await a.open_speech(effect_id=audio.id,digest=audio.digest,
            output_epoch=audio.output_epoch,activity_seq=audio.activity_seq)
        assert [p async for p in operation.values()]
        assert speech.texts==[spoken]
        await binding.flush()
        saved=await store.load_session('s')
        assert control not in repr(asdict(saved)) and spoken in repr(asdict(saved))
        await a.submit(request_id='next',activity_seq=3,cutoff=1,text='继续')
        state=await finish(a)
        assert control not in repr(asdict(tools.opens[-1][0]))
        assert spoken in repr(asdict(tools.opens[-1][0]))
        assert control not in repr(state.presented_effects)
    finally:await a.close()


@pytest.mark.asyncio
async def test_real_wire_control_and_dialogue_have_separate_channels_and_two_requests():
    import json
    from tests.contracts.test_direct_codex_responses import backend,response
    from tests.contracts.test_direct_luna_tools import wire,tool,message
    c,epoch=recognized();brief='回应夏禾感谢照片，温和接住她的谢意；继续当前纸样回忆。'
    spoken='别客气，我也一直记得我们挑纸样的时候。'
    call=story_call('x.story',cue=brief)
    observed=[]
    async def handle(request):
        body=json.loads(request.content);outputs=[i for i in body['input'] if i.get('type')=='function_call_output']
        if not outputs:return response(wire([tool(name=call.name,arguments=call.arguments_json)]))
        observed.append(json.loads(outputs[-1]['output']))
        assert observed[-1]['phase']=='awaiting_dialogue' and not observed[-1]['shown']
        assert not body['tools'] and body['tool_choice']=='none'
        prompt=json.loads(body['input'][-1]['content'][0]['text'])
        assert brief not in json.dumps(prompt,ensure_ascii=False)
        return response(wire([message(spoken)]))
    direct,source,requests=backend(handle,request_limit=2)
    a=native(None,c=c,tools=direct,wait=2);a._state=replace(a._state,output_epoch=epoch)
    class RejectChunking:
        async def expand(self,*args):
            raise AssertionError('Story receipt must bind its complete continuation')
            yield
    a._tool_caption_chunker=RejectChunking()
    try:
        await a.submit(request_id='wire',activity_seq=2,cutoff=0,text='谢谢你，接着说吧')
        state=await finish(a)
        assert state.last_error is None
        assert len(requests)==source.calls==2
        assert [e.value for e in state.issued_effects]==[spoken]
        assert 'old_friend' not in dict(c.runtime.story.chapter.milestones)
        await a.receipt(receipt(state.active_grants[0],1))
        assert 'old_friend' in dict(c.runtime.story.chapter.milestones)
    finally:await a.close()
