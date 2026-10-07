"""Typed local photo grants with real HTTPX Responses and Actor; synthetic IO only."""
import json
from dataclasses import replace

import pytest

from mira.application.generation_tool_execution import tool_definitions
from mira.domain.models import EffectKind, SessionState
from tests.contracts.test_luna_tool_actor import actor, ToolTurn, submit, wait_state, result
from tests.contracts.test_authored_photo_events import receipt, ready
from tests.contracts.test_development_review_composition import finish


@pytest.mark.asyncio
@pytest.mark.parametrize('review_mode', ['allow', 'unknown', 'reject'])
async def test_fixed_tool_grants_local_asset_without_input_or_output_semantic_calls(review_mode):
    turn = ToolTurn()
    value, _, _, wire = actor(turn, mode=review_mode)
    try:
        await submit(value)
        state = await finish(value)
        assert state.fixed_photo.state == 'granted'
        assert result(turn)['status'] == 'pending' and not result(turn)['shown']
        assert len([e for e in state.active_grants if e.kind is EffectKind.MEDIA]) == 1
        assert wire.calls == [], 'A shipped fixed asset does not require a second semantic decision.'
        assert not state.presented_effects and state.last_error is None
    finally:
        await value.close()


def test_fixed_tool_availability_is_separate_from_generated_image_review():
    from mira.application.contracts import GenerationContext
    from tests.contracts.test_luna_tool_actor import image_actor
    context = GenerationContext('Display the supplied coastal asset.',
        ('Display the supplied coastal asset.',), (), 1, character_assets=ready())
    state = SessionState('s', 'c', output_epoch=1, activity_seq=1)
    available = tool_definitions(context, state, None, review_available=False,
        image_task_count=0, max_effects=64)
    assert [item.name for item in available] == ['show_photo']
    dismissed = replace(state, photo_dismissed_through_activity=1)
    assert not tool_definitions(context, dismissed, None, review_available=False,
        image_task_count=0, max_effects=64)


@pytest.mark.asyncio
async def test_actual_httpx_failed_attempt_retry_uses_fresh_grant_and_exact_receipt():
    from tests.contracts.test_direct_codex_responses import backend, response
    from tests.contracts.test_direct_luna_tools import wire as sse, tool, message
    results = []
    async def handle(request):
        body = json.loads(request.content)
        outputs = [item for item in body['input'] if item.get('type') == 'function_call_output']
        if outputs:
            results.append(json.loads(outputs[0]['output']))
            return response(sse([message('The returned application status is recorded.')]))
        assert body['tool_choice'] == 'auto'
        assert [item['name'] for item in body['tools']] == ['show_photo']
        return response(sse([tool()]))
    backend_instance, _, requests = backend(handle, request_limit=4)
    value, _, _, review_wire = actor(ToolTurn(), tools=backend_instance, mode='unknown', result_wait=1)
    try:
        await submit(value)
        first = await wait_state(value, lambda state: state.fixed_photo.state in ('held', 'granted'))
        assert first.fixed_photo.state == 'granted'
        photo1 = next(effect for effect in first.active_grants if effect.kind is EffectKind.MEDIA)
        progress = dict(effect_id=photo1.id, digest=photo1.digest,
            output_epoch=photo1.output_epoch, activity_seq=photo1.activity_seq)
        await value.fixed_photo_progress(**progress, outcome='preparation_failed')
        first = await finish(value)
        assert results[-1]['status'] == 'failed' and results[-1]['reason'] == 'preparation_failed'
        assert not results[-1]['shown'] and not first.presented_effects
        await submit(value, 2)
        second = await wait_state(value, lambda state: state.fixed_photo.attempt_seq == 2
            and state.fixed_photo.state in ('held', 'granted'))
        assert second.fixed_photo.state == 'granted'
        photo2 = next(effect for effect in second.active_grants if effect.kind is EffectKind.MEDIA)
        assert photo1.id != photo2.id and photo2.output_epoch == 2
        assert await value.fixed_photo_progress(**progress, outcome='presentation_failed') == second
        with pytest.raises(Exception):
            await value.receipt(replace(receipt(photo2, 1), digest='wrong'))
        assert not (await value.snapshot()).presented_effects
        await value.receipt(receipt(photo2, 1))
        final = await finish(value)
        assert results[-1]['status'] == 'shown' and results[-1]['shown'] and results[-1]['visible']
        assert results[-1]['receipt']['effect_id'] == photo2.id
        assert final.presented_effects == (photo2,)
        assert final.fixed_photo.attempt_seq == 2 and final.fixed_photo.state == 'presented'
        assert len(requests) == 4 and len(results) == 2
        assert review_wire.calls == [] and final.last_error is None
    finally:
        await value.close()
