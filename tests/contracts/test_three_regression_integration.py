"""Independent merged-slice counterexamples; synthetic transports and state only."""
import asyncio
import json

import pytest

from mira.application.contracts import CandidateRange
from mira.adapters.generation.direct_codex_responses import DirectResponsesError, ResponsesRoute
from tests.contracts.test_character_control_bridge import setup, candidate
from tests.contracts.test_character_clothing_dialogue import assert_clothing_policy
from tests.contracts.test_direct_codex_responses import backend, response
from tests.contracts.test_direct_luna_tools import message, result, tool, wire
from tests.contracts.test_image_tool_capability_projection import fixture, capabilities, prompt
from tests.contracts.test_wardrobe_diagnostics import Sink, wardrobe


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('remaining', [1, 2])
async def test_consumed_budget_projects_remaining_authority_on_actual_wire(route, remaining):
    context, definitions = fixture()
    bodies = []

    async def handle(request):
        bodies.append(json.loads(request.content))
        return response(wire([tool()] if len(bodies) == 2 and remaining == 2 else [message()]))

    generator, credentials, requests = backend(handle, route=route, request_limit=remaining + 1)
    # Consume one slot first: the advertised capability must follow remaining,
    # not the original configured allowance or the supplied definitions alone.
    assert type(await generator.open_tool_turn(context, definitions).start()) is CandidateRange
    turn = generator.open_tool_turn(context, definitions)
    value = await turn.start()
    expected = ['show_photo', 'generate_story_image'] if remaining == 2 else []
    assert capabilities(bodies[1])['available_tool_names'] == expected
    assert [row['name'] for row in bodies[1]['tools']] == expected
    assert capabilities(bodies[1])['can_request_fictional_image'] == (remaining == 2)
    if remaining == 2:
        await turn.continue_after_tool(result(value.call_id), context)
        assert capabilities(bodies[2])['available_tool_names'] == bodies[2]['tools'] == []
        assert 'no pose, scene, media' in bodies[2]['instructions']
        assert_clothing_policy(bodies[2]['instructions'])
    for body in bodies:
        assert_clothing_policy(body['instructions'])
        assert body['text']['format']['strict'] is True
        assert 'story_image_scenes' not in prompt(body)['facts']
    assert len(requests) == credentials.calls == remaining + 1
    with pytest.raises(DirectResponsesError):
        await generator.open_tool_turn(context, definitions).start()
    assert len(requests) == remaining + 1


@pytest.mark.asyncio
async def test_reserved_continuation_slot_is_not_advertised_to_another_turn():
    context, definitions = fixture()
    bodies = []

    async def handle(request):
        bodies.append(json.loads(request.content))
        return response(wire([tool()] if len(bodies) == 1 else [message()]))

    generator, credentials, requests = backend(handle, request_limit=3)
    pending = generator.open_tool_turn(context, definitions)
    call = await pending.start()
    # Two slots physically remain, but one belongs to the pending continuation.
    assert type(await generator.open_tool_turn(context, definitions).start()) is CandidateRange
    assert bodies[1]['tools'] == capabilities(bodies[1])['available_tool_names'] == []
    assert capabilities(bodies[1])['can_request_fictional_image'] is False
    assert type(await pending.continue_after_tool(result(call.call_id), context)) is CandidateRange
    assert bodies[2]['tools'] == capabilities(bodies[2])['available_tool_names'] == []
    assert len(requests) == credentials.calls == 3


@pytest.mark.asyncio
async def test_real_late_generator_cannot_publish_wardrobe_after_stop():
    arrived, release = asyncio.Event(), asyncio.Event()

    class Uncooperative:
        async def generate(self, context):
            arrived.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            yield candidate('outfit_amber_raincoat')

    actor, _, _, _ = setup(candidate())
    actor._generation = Uncooperative()
    sink = Sink()
    actor._diagnostics = sink
    try:
        await actor.submit(request_id='synthetic-late', activity_seq=1, cutoff=0,
                           text='SYNTHETIC_PRIVATE_LATE_WARDROBE')
        await asyncio.wait_for(arrived.wait(), 1)
        assert any(event.wardrobe.phase == 'context' for event in wardrobe(sink))
        await actor.stop(activity_seq=2, cutoff=0)
        before = list(wardrobe(sink))
        release.set()
        await asyncio.gather(*tuple(actor._tasks), return_exceptions=True)
        assert wardrobe(sink) == before
        assert actor._wardrobe_waiting == (0, 0, ())
        state = await actor.snapshot()
        assert not state.active_grants
        assert not any(effect.value == 'outfit_amber_raincoat' for effect in state.issued_effects)
    finally:
        release.set()
        await actor.close()
