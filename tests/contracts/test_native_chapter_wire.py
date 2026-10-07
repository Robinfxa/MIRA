"""Native chapter context: actual Responses wire, Actor and compiled receipts, offline."""
import asyncio
import json
from dataclasses import replace
import pytest

from mira.application.ports.generation_tools import GenerationToolCall
from mira.domain.models import EffectKind
from mira.domain.xiahe_chapter import CHAPTER_CANON, ChapterStage
from tests.contracts.test_native_character_tools import native, story_call
from tests.contracts.test_xiahe_chapter_actor import character
from tests.contracts.test_direct_codex_responses import backend, response
from tests.contracts.test_direct_luna_tools import wire, tool, message
from tests.contracts.test_authored_photo_events import receipt


class WireSession:
    def __init__(self, *, route=None):
        self.plan = None
        self.dialogue = '我们接着聊。'
        self.results = []
        self.prompts = []
        self.seq = 0
        self.epoch = 0
        self.c = character()
        self.direct, self.source, self.requests = backend(self.handle, request_limit=40, **({'route': route} if route is not None else {}))
        self.a = native(None, c=self.c, tools=self.direct, wait=1)

    async def handle(self, request):
        body = json.loads(request.content)
        prompt = json.loads(body['input'][-1]['content'][0]['text'])
        self.prompts.append(prompt)
        outputs = [i for i in body['input'] if i.get('type') == 'function_call_output']
        if outputs:
            self.results.append(json.loads(outputs[-1]['output']))
            return response(wire([message(self.dialogue)]))
        planned = self.plan(prompt, body) if callable(self.plan) else self.plan
        if isinstance(planned, str):
            return response(wire([message(planned)]))
        return response(wire([tool(id=f'fc-{self.epoch}', call_id=f'call-{self.epoch}',
            name=planned.name, arguments=planned.arguments_json)]))

    async def turn(self, text, plan, *, acknowledge=True):
        self.epoch += 1
        self.plan = plan
        self.dialogue = ('你是夏禾吗，给我个准话？' if isinstance(plan, GenerationToolCall)
            and json.loads(plan.arguments_json).get('transition_id')=='x.ask_role' else '我们接着聊。')
        previous_result_count = len(self.results)
        await self.a.submit(request_id=f'audit-{self.epoch}', activity_seq=self.epoch,
            cutoff=self.seq, text=text)
        async with asyncio.timeout(4):
            while True:
                state = await self.a.snapshot()
                if acknowledge:
                    for effect in state.active_grants:
                        if not any(r.effect_id == effect.id for r in state.receipts):
                            self.seq += 1
                            await self.a.receipt(receipt(effect, self.seq))
                if not any(not task.done() for task in self.a._tasks):
                    break
                await asyncio.sleep(.001)
        state = await self.a.snapshot()
        return (self.results[-1] if len(self.results) > previous_result_count else None), state

    async def close(self):
        await self.a.close()


@pytest.mark.asyncio
async def test_real_wire_mixed_script_claim_and_next_turn_keep_role_with_receipts():
    s = WireSession()
    try:
        text = '我是夏he啊，你不记得我啦？这照片的灯塔我也眼熟'
        result, state = await s.turn(text, story_call('x.recognize', act='claim_role', text=text))
        assert result['status'] == 'shown'
        assert s.c.runtime.story.chapter.role_active
        assert any(e.value == 'xiahe_recognition' for e in state.presented_effects)
        await s.turn('没错啊就是我', '夏禾，我们接着说。')
        assert s.prompts[-1]['facts']['character_story']['chapter']['role_active']
        assert s.prompts[-1]['facts']['character_story']['chapter']['allowed_next'] == ['x.gift_offer', 'x.story', 'x.promise', 'show_photo', 'x.exit']
        assert len(s.requests) == 3
    finally:
        await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['chatgpt_subscription', 'openai_api'])
async def test_dormant_and_held_continuation_expose_current_chapter_without_unlocking_it(route):
    from mira.adapters.generation.direct_codex_responses import ResponsesRoute
    from mira.domain.xiahe_chapter import chapter_projection
    s = WireSession(route=ResponsesRoute(route))
    try:
        result, state = await s.turn('把照片交给我吧', story_call('x.gift_accept',
            act='accept_gift', text='把照片交给我吧', offer='invented-offer'))
        assert result['reason'] == 'chapter_precondition'
        for prompt in s.prompts:
            assert prompt['facts']['character_story']['chapter'] == chapter_projection(s.c.runtime.story.chapter)
            assert prompt['facts']['character_story']['chapter']['allowed_next'] == ['x.recognize', 'x.exit']
            assert prompt['facts']['first_person_dialogue']['speaker_contract']['recognition'] == 'inactive'
            assert prompt['native_tool_contract']['chapter_source'] == 'facts.character_story.chapter'
            assert 'chapter' not in prompt['native_tool_contract']
        continuation = json.loads(s.requests[1].content)
        assert continuation['tools'] == [] and continuation['tool_choice'] == 'none'
        assert continuation['parallel_tool_calls'] is False
        calls = [i for i in continuation['input'] if i.get('type') == 'function_call']
        outputs = [i for i in continuation['input'] if i.get('type') == 'function_call_output']
        assert len(calls) == len(outputs) == 1 and calls[0]['call_id'] == outputs[0]['call_id']
        assert any(e.value == '我们接着聊。' for e in state.presented_effects)
        assert not state.last_error and not s.c.runtime.story.chapter.role_active
        assert len(s.requests) == 2
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_current_chapter_canon_stays_authored_when_user_claims_shared_lighthouse_trip():
    s = WireSession()
    try:
        await s.turn('我是夏he', story_call('x.recognize', act='claim_role', text='我是夏he'))
        await s.turn('接着说', story_call('x.story', cue=CHAPTER_CANON[0][2]))
        await s.turn('我们一起去灯塔的那次呢', '海边那次是我一个人去的，回来后把照片发给你。')
        packet = s.prompts[-1]
        chapter = packet['facts']['character_story']['chapter']
        assert 'chapter' not in packet['native_tool_contract']
        assert json.dumps(packet, ensure_ascii=False).count(CHAPTER_CANON[1][2]) == 1
        assert chapter['author_canon_for_current_beat'][0]['text'] == CHAPTER_CANON[1][2]
        assert '海边那次是我一个人去的' in CHAPTER_CANON[1][2]
        assert chapter['allowed_next'] == ['x.gift_offer', 'x.story', 'x.promise', 'show_photo', 'x.exit']
    finally:
        await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('reference_mode', ['missing', 'wrong', 'stale'])
async def test_confirmation_hold_has_actionable_closed_reason_and_keeps_dialogue(reference_mode):
    s = WireSession()
    try:
        _, state = await s.turn('你认得我吗', story_call('x.ask_role',
            act='ask_role_confirmation', text='你认得我吗', cue='你是夏禾吗？'))
        question = next(e for e in state.presented_effects if e.value == '你是夏禾吗，给我个准话？')
        reference = '' if reference_mode == 'missing' else 'wrong' if reference_mode == 'wrong' else question.id
        if reference_mode == 'stale':
            await s.turn('先聊聊咖啡吧', '这杯闻起来有一点坚果香。')
        result, state = await s.turn('嗯，对', story_call('x.recognize',
            act='confirm_role', text='嗯，对', reference=reference))
        assert result['status'] == 'held' and result['reason'] == 'needs_confirmation'
        assert not s.c.runtime.story.chapter.role_active
        assert s.prompts[-1]['facts']['character_story']['chapter']['allowed_next'] == ['x.recognize', 'x.exit']
        assert any(e.value == '我们接着聊。' for e in state.presented_effects)
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_denial_exits_role_and_offtopic_chat_does_not_reenter():
    s = WireSession()
    try:
        await s.turn('我是夏he', story_call('x.recognize', act='claim_role', text='我是夏he'))
        result, _ = await s.turn('不，我不是夏禾，退出这个角色', story_call('x.exit',
            act='exit_role', text='不，我不是夏禾，退出这个角色'))
        assert result['status'] == 'applied'
        assert not s.c.runtime.story.chapter.role_active
        before = s.c.runtime.story.chapter
        result, state = await s.turn('聊聊今天这杯咖啡吧', '这杯的香气挺浓。')
        assert result is None and s.c.runtime.story.chapter == before
        assert s.prompts[-1]['facts']['character_story']['chapter']['role_active'] is False
        assert any(e.value == '这杯的香气挺浓。' for e in state.presented_effects)
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_stop_before_recognition_receipt_cannot_unlock_role_or_continue():
    from mira.domain.errors import DomainError
    from tests.contracts.test_luna_tool_actor import wait_state
    from tests.contracts.test_development_review_composition import finish
    s = WireSession()
    try:
        s.epoch = 1
        s.plan = story_call('x.recognize', act='claim_role', text='我是夏he')
        await s.a.submit(request_id='stop-native', activity_seq=1, cutoff=0, text='我是夏he')
        state = await wait_state(s.a, lambda state: any(e.value == 'xiahe_recognition' for e in state.active_grants))
        effect = next(e for e in state.active_grants if e.value == 'xiahe_recognition')
        assert not s.c.runtime.story.chapter.role_active
        await s.a.stop(activity_seq=2, cutoff=0)
        with pytest.raises(DomainError) as error:
            await s.a.receipt(receipt(effect, 1))
        assert error.value.code == 'after_stop_fence'
        state = await finish(s.a)
        assert not s.c.runtime.story.chapter.role_active
        assert not state.active_grants and not state.presented_effects
        assert not s.results and len(s.requests) == 1
    finally:
        await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['domain_unknown_reason', 'domain_wrong_code', 'value_error'])
async def test_unrecognized_exception_text_is_not_sent_in_native_tool_result(monkeypatch, kind):
    from mira.domain.errors import DomainError
    import mira.application.native_character_tools as native_tools
    sentinel = 'private-sentinel-never-exported'
    def fail(*args):
        if kind == 'domain_unknown_reason':
            raise DomainError('tool_held', sentinel)
        if kind == 'domain_wrong_code':
            raise DomainError('untrusted', 'needs_confirmation')
        raise ValueError(sentinel)
    monkeypatch.setattr(native_tools, 'prepare_native_character', fail)
    s = WireSession()
    try:
        result, state = await s.turn('我是夏he', story_call('x.recognize', act='claim_role', text='我是夏he'))
        assert result['status'] == 'held' and result['reason'] == 'precondition'
        assert sentinel not in s.requests[-1].content.decode()
        assert any(e.value == '我们接着聊。' for e in state.presented_effects)
    finally:
        await s.close()


def test_native_projection_respects_prompt_limit_and_legacy_projection_stays_dormant():
    from mira.adapters.generation.direct_codex_responses import DirectResponsesLimits, DirectResponsesError
    from mira.adapters.generation.direct_tools import _prompt, _legacy_prompt
    from mira.application.contracts import GenerationContext
    from mira.domain.xiahe_chapter import chapter_projection
    c = character()
    context = GenerationContext('你好', ('你好',), (), 1,
        character_story=c.begin_input('bounded', 1), character_assets=c.readiness)
    limits = DirectResponsesLimits()
    kwargs = {'continuation': False, 'tool_names': ('advance_story',)}
    packet = json.loads(_prompt(context, limits, False, **kwargs))
    chapter = packet['facts']['character_story']['chapter']
    assert chapter == chapter_projection(context.character_story.chapter)
    assert len(json.dumps(chapter, ensure_ascii=False).encode()) < 4096
    legacy = json.loads(_legacy_prompt(context, limits, False, **kwargs))
    assert 'native_tool_contract' not in legacy and 'chapter' not in legacy['facts']['character_story']
    assert 'character_proposal_contract' in legacy
    with pytest.raises(DirectResponsesError) as error:
        _prompt(context, replace(limits, max_prompt_bytes=1024), False, **kwargs)
    assert error.value.code == 'invalid_input'


@pytest.mark.asyncio
async def test_real_wire_typed_question_allows_next_exact_confirmation():
    s = WireSession()
    try:
        result, state = await s.turn('你不记得我啦？', story_call('x.ask_role',
            act='ask_role_confirmation', text='你不记得我啦？', cue='你是夏禾吗，给我个准话？'))
        assert result['status'] == 'pending' and result['phase'] == 'awaiting_dialogue'
        question = next(e for e in state.presented_effects if '准话' in e.value)
        def confirm(prompt, body):
            definition = next(t for t in body['tools'] if t['name'] == 'advance_story')
            assert question.id in definition['description']
            return story_call('x.recognize', act='confirm_role', text='没错啊就是我', reference=question.id)
        result, state = await s.turn('没错啊就是我', confirm)
        assert result['status'] == 'shown'
        assert s.c.runtime.story.chapter.role_active
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_plain_conversational_question_is_not_typed_confirmation_authority():
    s = WireSession()
    try:
        _, state = await s.turn('我是夏he啊', '你是夏禾吗，给我个准话？')
        question = next(e for e in state.presented_effects if '准话' in e.value)
        result, state = await s.turn('没错啊就是我', story_call('x.recognize',
            act='confirm_role', text='没错啊就是我', reference=question.id))
        assert result['status'] == 'held' and result['reason'] == 'needs_confirmation'
        assert not s.c.runtime.story.chapter.role_active
        assert not any(e.value == 'xiahe_recognition' for e in state.issued_effects)
        assert any(e.value == '我们接着聊。' for e in state.presented_effects)
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_plain_conversational_recognition_keeps_chat_but_not_chapter_authority():
    s = WireSession()
    try:
        result, state = await s.turn('没错啊就是我', '原来真的是夏禾，我认出来了。')
        assert result is None
        assert not s.c.runtime.story.chapter.role_active
        assert any('我认出来了' in e.value for e in state.presented_effects)
        result, state = await s.turn('把照片交给我吧', story_call('x.gift_accept',
            act='accept_gift', text='把照片交给我吧', offer='invented-offer'))
        assert result['status'] == 'held' and result['reason'] == 'chapter_precondition'
        assert not any(e.value == 'xiahe_photo_handover' for e in state.issued_effects)
        assert any(e.value == '我们接着聊。' for e in state.presented_effects)
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_visible_fixed_photo_does_not_bypass_gift_prerequisites():
    s = WireSession()
    try:
        result, state = await s.turn('看看照片', GenerationToolCall('photo', 'show_photo', '{"photo_id":"trip_photo"}'))
        assert result['status'] == 'shown' and state.photo_visible
        result, state = await s.turn('把照片送给我', story_call('x.gift_offer', offer='gift'))
        assert result['status'] == 'held'
        assert not s.c.runtime.story.chapter.milestones
        assert not any(e.value in ('xiahe_gift_offer', 'xiahe_photo_handover') for e in state.issued_effects)
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_entire_real_wire_chapter_reuses_early_photo_and_hands_over_after_acceptance():
    s = WireSession()
    try:
        photo_call = GenerationToolCall('photo', 'show_photo', '{"photo_id":"trip_photo"}')
        first, state = await s.turn('看看照片', photo_call)
        first_photo_id = first['receipt']['effect_id']
        await s.turn('我是夏he', story_call('x.recognize', act='claim_role', text='我是夏he'))
        for beat, source, cue in CHAPTER_CANON:
            transition = 'x.promise' if beat == 'photo_promise' else 'x.story'
            result, state = await s.turn('接着说吧', story_call(transition, cue=cue))
            assert result['status'] == 'pending' and result['phase'] == 'awaiting_dialogue'
        assert s.c.runtime.story.chapter.stage == ChapterStage.PROMISE
        assert 'photo_preview' not in dict(s.c.runtime.story.chapter.milestones)
        result, state = await s.turn('再看看那张灯塔照片', photo_call)
        assert result['status'] == 'reused'
        assert result['receipt']['effect_id'] == first_photo_id
        assert s.c.runtime.story.chapter.preview_reference.mode == 'reused_visible'
        assert sum(e.kind == EffectKind.MEDIA for e in state.issued_effects) == 1
        result, state = await s.turn('你想把照片送给我吗', story_call('x.gift_offer', offer='gift-current'))
        assert result['status'] == 'shown'
        assert s.c.runtime.story.chapter.stage == ChapterStage.GIFT_OFFERED
        assert 'photo_handover' not in dict(s.c.runtime.story.chapter.milestones)
        result, state = await s.turn('没问题，我收下啦', story_call('x.gift_accept',
            act='accept_gift', text='没问题，我收下啦', offer='gift-current'))
        assert result['status'] == 'shown'
        assert s.c.runtime.story.chapter.stage == ChapterStage.COMPLETED
        assert result['receipt']['effect_id'] != first_photo_id
        assert any(e.value == 'xiahe_photo_handover' for e in state.presented_effects)
        assert len(s.requests) == 18
        assert '海边那次是我一个人去的' in CHAPTER_CANON[1][2]
        for request, prompt in zip(s.requests, s.prompts):
            text = json.loads(request.content)['input'][-1]['content'][0]['text']
            assert len(text.encode()) <= s.direct._limits.max_prompt_bytes
            assert 'chapter' not in prompt['native_tool_contract']
            assert prompt['native_tool_contract']['chapter_source'] == 'facts.character_story.chapter'
            for canon in prompt['facts']['character_story']['chapter']['author_canon_for_current_beat']:
                assert json.dumps(prompt, ensure_ascii=False).count(canon['text']) == 1
    finally:
        await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['invalid_act_enum', 'missing_draft_field'])
async def test_real_wire_invalid_finite_args_fail_before_runtime_receipt(change):
    s = WireSession()
    try:
        call = story_call('x.recognize', act='claim_role', text='我是夏禾')
        args = json.loads(call.arguments_json)
        if change == 'invalid_act_enum':
            args['input_act'] = 'recognize_role'
        else:
            del args['draft_cue']
        result, state = await s.turn('我是夏禾', replace(call, arguments_json=json.dumps(args)))
        assert result is None
        assert state.last_error == 'invalid_response'
        assert not s.c.runtime.story.chapter.role_active
        assert not state.issued_effects
        assert len(s.requests) == 1
    finally:
        await s.close()
