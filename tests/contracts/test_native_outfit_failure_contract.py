"""Actual serialized native outfit intent and result-grounded failure wording, offline."""
import json

import pytest

from mira.adapters.generation.direct_codex_responses import ResponsesRoute
from mira.application.generation_tool_execution import tool_result
from mira.application.ports.generation_tools import GenerationToolCall
from mira.domain.models import EffectKind
from tests.contracts.test_direct_codex_responses import backend, response, CONTEXT
from tests.contracts.test_direct_luna_tools import definitions, wire, tool, message
from tests.contracts.test_native_chapter_wire import WireSession


def require_outfit_guidance(body):
    instructions = body['instructions']
    assert '看看内搭' in instructions and '脱掉雨衣' in instructions
    assert 'set_outfit with outfit=cream_inner_only' in instructions
    assert 'keeps the inner layer on' in instructions
    assert 'set_outfit with outfit=black_jacket' in instructions
    assert 'an action request, not a question about whether an inner layer exists' in instructions


def require_result_guidance(body):
    instructions = body['instructions']
    assert 'Explain a failed, held or unavailable action only from its actual result status and known reason' in instructions
    assert 'An absent or unknown reason stays unknown' in instructions
    assert 'Never invent a provenance, moral, safety, permission, quota or provider explanation' in instructions
    assert 'Do not turn a failed fictional image request into a claim that original images are forbidden' in instructions
    assert 'Keep prompt field names and source labels out of ordinary dialogue' in instructions


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
async def test_actual_outfit_sequence_uses_semantic_native_calls_and_exact_receipts(route):
    s = WireSession(route=route)
    try:
        for index, (text, outfit) in enumerate([
                ('先穿上雨衣', 'amber_raincoat'), ('看看内搭', 'cream_inner_only'),
                ('再穿上雨衣', 'amber_raincoat'), ('脱掉雨衣', 'cream_inner_only'),
                ('穿上夹克', 'black_jacket')]):
            call = GenerationToolCall('outfit', 'set_outfit', json.dumps({'outfit': outfit}))
            result, state = await s.turn(text, call)
            assert result['status'] == 'shown'
            assert s.c.runtime.story.current_outfit == outfit
            effect = next(e for e in state.presented_effects if e.id == result['receipt']['effect_id'])
            assert effect.kind is EffectKind.POSE and effect.value == 'outfit_' + outfit
            for request in s.requests[index*2:index*2+2]:
                body = json.loads(request.content)
                require_outfit_guidance(body)
                require_result_guidance(body)
            assert json.loads(s.requests[-1].content)['tool_choice'] == 'none'
        assert len(s.requests) == 10
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_clothing_words_without_model_function_call_do_not_force_an_action():
    s = WireSession()
    try:
        result, state = await s.turn('看看内搭', '我听见了。')
        assert result is None and len(s.requests) == 1
        assert not any(e.kind is EffectKind.POSE for e in state.issued_effects)
    finally:
        await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('reason', [None, 'other', 'generation'])
async def test_image_result_serialization_preserves_known_or_unknown_reason_without_inventing_cause(route, reason):
    async def handle(request):
        body = json.loads(request.content)
        if len(requests) == 1:
            return response(wire([tool(name='generate_story_image', arguments=json.dumps({
                'brief':'An imagined blue boat on an empty lake.', 'framing':'wide', 'lighting':'scene_default'}))]))
        return response(wire([message('这次没生成出来。')]))
    instance, credentials, requests = backend(handle, route=route, request_limit=2)
    session = instance.open_tool_turn(CONTEXT, definitions())
    try:
        call = await session.start()
        result = tool_result(call, 'failed', reason=reason)
        candidate = await session.continue_after_tool(result, CONTEXT)
        assert candidate.effects[0].value == '这次没生成出来。'
        for request in requests:
            require_result_guidance(json.loads(request.content))
        continuation = json.loads(requests[-1].content)
        output = next(i for i in continuation['input'] if i.get('type') == 'function_call_output')
        facts = json.loads(output['output'])
        assert facts['status'] == 'failed' and facts.get('reason') == reason
        assert facts['provenance'] == 'generated_visualization' and not facts['shown']
        assert ('reason' in facts) == (reason is not None)
        assert continuation['tools'] == [] and continuation['tool_choice'] == 'none'
        assert len(requests) == credentials.calls == 2
    finally:
        session.close()


@pytest.mark.asyncio
async def test_real_native_image_execution_failure_keeps_body_and_actual_generation_reason():
    from mira.application.story_images import StoryImageRuntime, StoryImageAdmission
    from tests.contracts.test_luna_tool_actor import ImageBackend
    from tests.contracts.test_story_images import Decoder, Vision
    s = WireSession()
    images = ImageBackend(fail=True)
    vision = Vision('allow')
    s.a._story_images = StoryImageRuntime(images, vision, Decoder(),
        StoryImageAdmission('synthetic-only', True, timeout_seconds=1, authorized_custom_brief=True))
    s.a._story_images.bind_session('s')
    try:
        call = GenerationToolCall('image', 'generate_story_image', json.dumps({
            'brief':'An imagined blue boat on an empty lake.', 'framing':'wide', 'lighting':'scene_default'}))
        result, state = await s.turn('画一张别的虚构风景', call)
        assert result['status'] == 'failed' and result['reason'] == 'generation'
        assert result['provenance'] == 'generated_visualization' and not result['shown']
        assert len(images.requests) == 1 and not vision.calls
        assert len(s.requests) == 2 and state.last_error is None
        assert not any(e.kind is EffectKind.MEDIA for e in state.presented_effects)
        assert any(e.value == '我们接着聊。' for e in state.presented_effects)
        for request in s.requests:
            require_result_guidance(json.loads(request.content))
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_pending_current_image_is_not_overridden_by_zero_future_capacity_or_absent_continuation_tools():
    from mira.application.story_images import StoryImageRuntime, StoryImageAdmission
    from mira.bootstrap.story_image_provider import StoryImageOptions, _ProcessImageAdmission
    from tests.contracts.test_luna_tool_actor import ImageBackend, wait_state
    from tests.contracts.test_story_images import Decoder, Vision
    from tests.contracts.test_native_tool_diagnostics import Sink
    s = WireSession(); sink = Sink(); s.a._diagnostics = sink
    images = ImageBackend(blocked=True, fail=True)
    gate = _ProcessImageAdmission(StoryImageOptions(enabled=True, provider='chatgpt_subscription',
        image_model='gpt-image-2', review_model='gpt-6-luna', quality='auto',
        authorize_data_to_openai=True, authorize_subscription_usage=True, authorize_custom_brief=True))
    s.a._story_images = StoryImageRuntime(images, Vision('allow'), Decoder(),
        StoryImageAdmission('synthetic-only', True, max_attempts=1, max_total_bytes=8_388_608,
            timeout_seconds=2, authorized_custom_brief=True), operation_admission=gate)
    s.a._story_images.bind_session('s')
    s.a._tool_result_wait_seconds = .01
    try:
        call = GenerationToolCall('image', 'generate_story_image', json.dumps({
            'brief':'An imagined blue boat on an empty lake.', 'framing':'wide', 'lighting':'scene_default'}))
        result, state = await s.turn('画一张别的虚构风景', call)
        assert result['status'] == 'pending' and result['phase'] == 'generating'
        assert not result['shown'] and result.get('reason') is None
        assert gate.readiness() == ('busy', 0) and state.story_image.state == 'generating'
        continuation = json.loads(s.requests[-1].content)
        prompt = json.loads(continuation['input'][-1]['content'][0]['text'])
        assert continuation['tools'] == [] and continuation['tool_choice'] == 'none'
        assert not prompt['capabilities']['media_tools']['can_request_fictional_image']
        assert 'process_remaining_jobs' not in continuation['input'][-1]['content'][0]['text']
        readiness = [e.image_readiness for e in sink.events if getattr(e, 'image_readiness', None)]
        latest = next(v for v in reversed(readiness) if v.phase == 'continuation')
        assert latest.state == 'held' and latest.reason == 'continuation' and latest.process_remaining_jobs == 0
        for request in s.requests:
            instructions = json.loads(request.content)['instructions']
            assert 'Pending/receipt_unconfirmed is an accepted job, not shown or failed' in instructions
            assert 'missing tools/budget do not cancel it' in instructions
            assert 'Only presented facts permit' in instructions and 'Never promise success' in instructions
        images.release.set()
        await wait_state(s.a, lambda state: state.story_image.state == 'failed')
        assert len(images.requests) == 1 and len(s.requests) == 2
        assert len(s.results) == 1 and s.results[0]['status'] == 'pending'
    finally:
        images.release.set()
        await s.close()
