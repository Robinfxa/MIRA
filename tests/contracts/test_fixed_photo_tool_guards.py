"""Scope and lifecycle negative controls for local fixed-asset admission."""
from dataclasses import replace

import pytest

from mira.application.generation_tool_execution import tool_definitions
from mira.application.ports.generation_tools import GenerationToolCall
from mira.domain.errors import DomainError
from mira.domain.models import EffectKind
from tests.contracts.test_luna_tool_actor import (actor, image_actor, ToolTurn, Tools, submit,
    wait_state, result)
from tests.contracts.test_authored_photo_events import ready, receipt
from tests.contracts.test_development_review_composition import finish


@pytest.mark.asyncio
async def test_fixed_photo_is_independent_of_camera_readiness_and_does_not_raise_camera():
    catalog = ready()
    catalog = replace(catalog, records=tuple(item for item in catalog.records
        if item.capability_id == 'mira.media.trip_photo'))
    turn = ToolTurn()
    value, _, _, wire = actor(turn, catalog=catalog, mode='unknown')
    try:
        await submit(value)
        state = await finish(value)
        assert state.fixed_photo.state == 'granted'
        assert [(effect.kind.value, effect.value) for effect in state.issued_effects
            if effect.kind is not EffectKind.SUBTITLE] == [('media', 'trip_photo')]
        assert wire.calls == []
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_no_generated_image_tool_without_semantic_review_availability():
    value, turn, _, _, tools, _ = image_actor()
    try:
        await submit(value)
        await finish(value)
        context = tools.opens[0][0]
        state = await value.snapshot()
        available = tool_definitions(context, state, value._story_images,
            review_available=False, image_task_count=0, max_effects=64)
        assert [item.name for item in available] == ['show_photo']
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_fixed_photo_arguments_cannot_add_camera_controls():
    call = GenerationToolCall('fixed', 'show_photo', '{"photo_id":"trip_photo","pose":"camera_raise"}')
    turn = ToolTurn(call)
    value, _, _, wire = actor(turn)
    try:
        await submit(value)
        state = await finish(value)
        assert result(turn)['status'] == 'held' and result(turn)['reason'] == 'invalid_arguments'
        assert not any(effect.kind in (EffectKind.MEDIA, EffectKind.POSE) for effect in state.issued_effects)
        assert wire.calls == []
    finally:
        await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('fence', ['stop', 'dismiss', 'close'])
async def test_fixed_photo_wait_is_cancelled_before_late_preparation_or_receipt(fence):
    turn = ToolTurn()
    value, _, _, wire = actor(turn, mode='unknown', result_wait=1)
    try:
        await submit(value)
        state = await wait_state(value, lambda current: current.fixed_photo.state in ('granted', 'held'))
        assert state.fixed_photo.state == 'granted'
        effect = next(effect for effect in state.active_grants if effect.kind is EffectKind.MEDIA)
        if fence == 'stop':
            await value.stop(activity_seq=2, cutoff=0)
        elif fence == 'dismiss':
            await value.dismiss_photo(request_id='dismiss-local-photo', expected_revision=0, cutoff=0)
        else:
            await value.close()
        await finish(value)
        with pytest.raises(DomainError):
            await value.receipt(receipt(effect, 1))
        current = await value.snapshot()
        assert not current.presented_effects and not current.photo_visible
        assert not turn.results
        if fence != 'close':
            assert not current.active_grants
        else:
            assert value._closed  # Closed Actor rejects receipts; terminal snapshot is historical.
        assert wire.calls == []
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_fixed_photo_exhausted_effect_capacity_cannot_create_a_new_attempt():
    first, second = ToolTurn(), ToolTurn()
    value, _, _, wire = actor(first, tools=Tools(first, second))
    value._limits = replace(value._limits, max_effects=2)
    try:
        await submit(value)
        state = await finish(value)
        assert len(state.issued_effects) == 2 and state.fixed_photo.attempt_seq == 1
        await submit(value, 2)
        state = await finish(value)
        assert result(second)['status'] == 'unavailable'
        assert state.fixed_photo.attempt_seq == 1
        assert len([effect for effect in state.issued_effects if effect.kind is EffectKind.MEDIA]) == 1
        assert wire.calls == []
    finally:
        await value.close()
