"""Actual bounded Responses call/output protocol, entirely synthetic and offline."""
import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from mira.adapters.generation.direct_codex_responses import DirectResponsesError, DirectResponsesLimits, ResponsesRoute
from mira.application.contracts import CandidateRange
from tests.contracts.test_direct_codex_responses import backend, CONTEXT, event, completed, response, snapshot_message, collect, BlockingStream


def definitions():
    from mira.application.ports.generation_tools import ToolDefinition
    def define(name, fields):
        schema = {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}
        return ToolDefinition(name, 'A fictional visual action.', json.dumps(schema))
    return (
        define('show_photo', {'photo_id': {'type': 'string', 'enum': ['trip_photo']}}),
        define('generate_story_image', {'brief': {'type': 'string', 'minLength': 1, 'maxLength': 600},
            'framing': {'type': 'string', 'enum': ['wide', 'detail']},
            'lighting': {'type': 'string', 'enum': ['scene_default', 'warm']}}),
    )


def result(call_id='call-demo'):
    from mira.application.ports.generation_tools import GenerationToolResult
    return GenerationToolResult(call_id, json.dumps({'schema': 'mira.tool-result.v1', 'status': 'pending',
        'code': 'receipt_unconfirmed', 'state_revision': 3}))


def tool(**changes):
    return dict({'type': 'function_call', 'id': 'fc-demo', 'call_id': 'call-demo',
        'name': 'show_photo', 'arguments': '{"photo_id":"trip_photo"}', 'status': 'completed'}, **changes)


def done(item, index=0):
    return event('response.output_item.done', {'type': 'response.output_item.done', 'output_index': index, 'item': item})


def wire(items, snapshot=True):
    return b''.join(done(item, index) for index, item in enumerate(items)) + completed(output=items if snapshot else None)


def message(value='这是虚构画面的展示请求，状态还在确认。', **extra):
    return snapshot_message(json.dumps({'effects': [{'kind': 'subtitle', 'value': value}], **extra}, ensure_ascii=False))


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
async def test_actual_call_output_roundtrip_preserves_reasoning_and_fresh_context(route):
    reasoning = {'type': 'reasoning', 'id': 'rs-demo', 'summary': [], 'encrypted_content': 'synthetic-encrypted'}
    async def handle(request):
        body = json.loads(request.content)
        if len(requests) == 1:
            assert body['tools'][0]['strict'] is True
            assert body['tool_choice'] == 'auto' and body['parallel_tool_calls'] is False
            assert body['include'] == ['reasoning.encrypted_content']
            assert 'Never call tools' not in body['instructions']
            return response(wire([reasoning, tool()]))
        assert body['tool_choice'] == 'none' and body['parallel_tool_calls'] is False
        items = body['input']
        assert items[1:3] == [reasoning, tool()]
        assert items[3]['type'] == 'function_call_output' and items[3]['call_id'] == 'call-demo'
        assert json.loads(items[3]['output'])['status'] == 'pending'
        assert json.loads(items[-1]['content'][0]['text'])['tool_turn_state']['photo_visibility_revision'] == 3
        assert body['store'] is False and body['stream'] is True
        return response(wire([message()]))
    instance, source, requests = backend(handle, route=route, request_limit=2)
    session = instance.open_tool_turn(CONTEXT, definitions())
    call = await session.start()
    assert call.call_id == 'call-demo' and call.name == 'show_photo'
    current = replace(CONTEXT, photo_visibility_revision=3)
    candidate = await session.continue_after_tool(result(), current)
    assert type(candidate) is CandidateRange and len(candidate.effects) == 1
    assert len(requests) == source.calls == 2
    with pytest.raises(DirectResponsesError):
        await session.continue_after_tool(result(), current)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_ordinary_text_uses_one_request_and_releases_reserved_slot():
    async def handle(_): return response(wire([message()]))
    instance, source, requests = backend(handle, request_limit=2)
    session = instance.open_tool_turn(CONTEXT, definitions())
    assert type(await session.start()) is CandidateRange
    assert len(await collect(instance)) == 1
    assert len(requests) == source.calls == 2


@pytest.mark.asyncio
async def test_last_slot_is_text_only_without_exposing_tools():
    async def handle(request):
        body = json.loads(request.content)
        assert body['tool_choice'] == 'none' and body['tools'] == []
        return response(wire([message()]))
    instance, _, requests = backend(handle, request_limit=1)
    assert type(await instance.open_tool_turn(CONTEXT, definitions()).start()) is CandidateRange
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_dynamic_brief_is_a_real_typed_tool_call():
    args = {'brief': '虚构的雨夜书店，窗台放着一杯热茶。', 'framing': 'wide', 'lighting': 'warm'}
    async def handle(_): return response(wire([tool(name='generate_story_image', arguments=json.dumps(args))]))
    instance, _, _ = backend(handle, request_limit=2)
    session = instance.open_tool_turn(CONTEXT, definitions())
    call = await session.start()
    assert call.name == 'generate_story_image' and json.loads(call.arguments_json) == args
    session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('items', [
    [tool(), tool(id='fc-other', call_id='call-other')],
    [tool(), tool()],
    [tool(name='unknown')],
    [tool(arguments='{"photo_id":"trip_photo","photo_id":"trip_photo"}')],
    [tool(arguments='{"photo_id":"trip_photo","path":"/tmp/secret"}')],
    [tool(arguments='{"photo_id":"wrong"}')],
    [tool(status='in_progress')],
    [tool(arguments='x'*1025)],
    [tool(name='generate_story_image', arguments=json.dumps({'brief':'x'*601,'framing':'wide','lighting':'warm'}))],
    [tool(), message(image_proposal={'scene_id':'cafe'})],
    [tool(), message(story_proposal=None)],
    [tool(), snapshot_message('{"effects":[{"kind":"media","value":"trip_photo"}]}')],
])
async def test_invalid_or_mixed_calls_fail_closed(items):
    async def handle(_): return response(wire(items))
    instance, _, requests = backend(handle, request_limit=2)
    with pytest.raises(DirectResponsesError):
        await instance.open_tool_turn(CONTEXT, definitions()).start()
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [
    done(tool()),
    completed(output=[tool()]),
    done(tool()) + completed(output=[tool(call_id='conflict')]),
    done(tool()) + completed(output=[]),
    done(tool()) + completed() + done(tool()),
    event('response.output_item.added', {'type':'response.output_item.added','output_index':0,'item':tool(status='in_progress')}) + completed(),
    event('response.function_call_arguments.delta', {'type':'response.function_call_arguments.delta','output_index':0,'item_id':'fc-demo','delta':'{}'}) + done(tool()) + completed(),
    done(tool()) + event('response.incomplete', {'type':'response.incomplete'}),
])
async def test_incomplete_conflicting_or_late_protocol_is_rejected(body):
    async def handle(_): return response(body)
    instance, _, _ = backend(handle, request_limit=2, route=ResponsesRoute.OPENAI_API)
    with pytest.raises(DirectResponsesError):
        await instance.open_tool_turn(CONTEXT, definitions()).start()


@pytest.mark.asyncio
@pytest.mark.parametrize('item', [tool(), message(image_proposal=None), message(affect_proposal=None),
    snapshot_message('{"effects":[{"kind":"pose","value":"face_calm"}]}')])
async def test_continuation_rejects_more_tools_and_all_action_proposals(item):
    async def handle(_): return response(wire([tool()] if len(requests)==1 else [item]))
    instance, _, requests = backend(handle, request_limit=3)
    session = instance.open_tool_turn(CONTEXT, definitions())
    await session.start()
    with pytest.raises(DirectResponsesError): await session.continue_after_tool(result(), CONTEXT)
    with pytest.raises(DirectResponsesError): await session.continue_after_tool(result(), CONTEXT)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_wrong_result_id_and_oversized_result_do_not_make_second_request():
    from mira.application.ports.generation_tools import GenerationToolResult
    for output in (result('wrong-id'), GenerationToolResult('call-demo', json.dumps({'value':'x'*2048}))):
        async def handle(_): return response(wire([tool()]))
        instance, _, requests = backend(handle, request_limit=2)
        session = instance.open_tool_turn(CONTEXT, definitions())
        await session.start()
        with pytest.raises(DirectResponsesError): await session.continue_after_tool(output, CONTEXT)
        assert len(requests) == 1


@pytest.mark.asyncio
async def test_reservation_prevents_parallel_consumer_spending_continuation():
    async def handle(_): return response(wire([tool()] if len(requests)==1 else [message()]))
    instance, _, requests = backend(handle, request_limit=2)
    session = instance.open_tool_turn(CONTEXT, definitions())
    await session.start()
    with pytest.raises(DirectResponsesError): await collect(instance)
    await session.continue_after_tool(result(), CONTEXT)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_cancel_clears_state_and_closes_response_stream():
    stream = BlockingStream(done(tool()))
    async def handle(_): return response(b'', stream=stream)
    instance, _, _ = backend(handle, request_limit=2)
    session = instance.open_tool_turn(CONTEXT, definitions())
    task = asyncio.create_task(session.start())
    await stream.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert stream.closed and instance._reserved == 0
    with pytest.raises(DirectResponsesError): await session.continue_after_tool(result(), CONTEXT)


@pytest.mark.asyncio
async def test_timeout_covers_application_wait_and_does_not_restart_budget():
    async def handle(_): return response(wire([tool()]))
    instance, _, requests = backend(handle, request_limit=2, limits=DirectResponsesLimits(turn_seconds=.05))
    session = instance.open_tool_turn(CONTEXT, definitions())
    await session.start()
    # Advance the stored deadline directly; no wall-clock sleep manufactures a race.
    session._deadline = asyncio.get_running_loop().time() - 1
    with pytest.raises(DirectResponsesError): await session.continue_after_tool(result(), CONTEXT)
    assert len(requests) == 1 and instance._reserved == 0


@pytest.mark.asyncio
async def test_full_argument_stream_never_returns_before_terminal():
    call = tool()
    prefix = event('response.output_item.added', {'type':'response.output_item.added', 'output_index':0,
        'item':tool(status='in_progress', arguments='')})
    for delta in ('{"photo_id":', '"trip_photo"}'):
        prefix += event('response.function_call_arguments.delta', {'type':'response.function_call_arguments.delta',
            'output_index':0, 'item_id':'fc-demo', 'delta':delta})
    prefix += event('response.function_call_arguments.done', {'type':'response.function_call_arguments.done',
        'output_index':0, 'item_id':'fc-demo', 'arguments':call['arguments']}) + done(call)
    stream = BlockingStream(prefix)
    async def handle(_): return response(b'', stream=stream)
    instance, _, _ = backend(handle, request_limit=2)
    session = instance.open_tool_turn(CONTEXT, definitions())
    task = asyncio.create_task(session.start())
    await stream.entered.wait()
    assert not task.done()
    stream.release.set()
    assert (await task).call_id == 'call-demo'
    session.close()
    assert instance._reserved == 0


@pytest.mark.asyncio
async def test_subscription_empty_terminal_is_supported_only_after_complete_call():
    async def handle(_): return response(done(tool()) + completed(output=[]))
    instance, _, _ = backend(handle, request_limit=2)
    session = instance.open_tool_turn(CONTEXT, definitions())
    assert (await session.start()).call_id == 'call-demo'
    session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('second', [False, True])
async def test_http_error_is_sanitized_consumes_attempt_and_never_retries_or_falls_back(second):
    async def handle(_):
        if second and len(requests) == 1: return response(wire([tool()]))
        return httpx.Response(429, text='secret-provider-payload-do-not-log')
    instance, _, requests = backend(handle, request_limit=3)
    session = instance.open_tool_turn(CONTEXT, definitions())
    with pytest.raises(DirectResponsesError) as error:
        await session.start()
        await session.continue_after_tool(result(), CONTEXT)
    assert error.value.code == 'quota_exhausted'
    assert 'secret-provider' not in str(error.value.generation_diagnostic)
    assert len(requests) == (2 if second else 1)
    assert instance._remaining == (1 if second else 2) and instance._reserved == 0
    with pytest.raises(DirectResponsesError): await session.start()


@pytest.mark.asyncio
async def test_reasoning_carry_is_bounded_before_call_is_released():
    reasoning = {'type':'reasoning', 'id':'rs-large', 'summary':[], 'encrypted_content':'x'*2000}
    async def handle(_): return response(wire([reasoning, tool()]))
    instance, _, requests = backend(handle, request_limit=2, limits=DirectResponsesLimits(max_output_bytes=512))
    session = instance.open_tool_turn(CONTEXT, definitions())
    with pytest.raises(DirectResponsesError) as error: await session.start()
    assert error.value.code == 'output_limit' and len(requests) == 1 and instance._reserved == 0


@pytest.mark.asyncio
async def test_close_fences_pending_continuation_and_releases_only_unused_slot():
    async def handle(_): return response(wire([tool()] if len(requests)==1 else [message()]))
    instance, _, requests = backend(handle, request_limit=2)
    session = instance.open_tool_turn(CONTEXT, definitions())
    await session.start()
    session.close()
    session.close()
    assert instance._remaining == 1 and instance._reserved == 0
    assert session._wire is None and session._context is None and session._call_id is None
    with pytest.raises(DirectResponsesError): await session.continue_after_tool(result(), CONTEXT)
    assert len(await collect(instance)) == 1


@pytest.mark.asyncio
async def test_epoch_changed_context_cannot_continue_an_old_call():
    async def handle(_): return response(wire([tool()]))
    instance, _, requests = backend(handle, request_limit=2)
    session = instance.open_tool_turn(CONTEXT, definitions())
    await session.start()
    with pytest.raises(DirectResponsesError): await session.continue_after_tool(result(), replace(CONTEXT, output_epoch=8))
    assert len(requests) == 1 and instance._reserved == 0


@pytest.mark.asyncio
async def test_request_bound_is_checked_before_credentials_and_counting_attempt():
    async def handle(_): raise AssertionError('not reached')
    instance, source, requests = backend(handle, request_limit=2, limits=DirectResponsesLimits(max_request_bytes=1024))
    with pytest.raises(DirectResponsesError) as error:
        await instance.open_tool_turn(CONTEXT, definitions()).start()
    assert error.value.code == 'input_limit' and source.calls == 0 and requests == []
    assert instance._remaining == 2 and instance._reserved == 0


@pytest.mark.asyncio
async def test_text_only_continuation_cannot_reenable_speech():
    async def handle(_):
        value = tool() if len(requests)==1 else snapshot_message('{"effects":[{"kind":"speech","value":"你好"},{"kind":"subtitle","value":"你好"}]}')
        return response(wire([value]))
    instance, _, requests = backend(handle, request_limit=2)
    session = instance.open_tool_turn(CONTEXT, definitions())
    await session.start()
    with pytest.raises(DirectResponsesError):
        await session.continue_after_tool(result(), replace(CONTEXT, response_mode='text_only'))
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(('brief', 'ensure_ascii'), [('雨'*600, False), ('雨'*600, True), ('📷'*600, True)], ids=['chinese-utf8','chinese-escaped','emoji-escaped'])
async def test_full_advertised_brief_length_accepts_unicode_and_escaped_json(brief, ensure_ascii):
    args = json.dumps({'brief': brief, 'framing': 'wide', 'lighting': 'warm'}, ensure_ascii=ensure_ascii)
    async def handle(_): return response(wire([tool(name='generate_story_image', arguments=args)]))
    instance, _, _ = backend(handle, request_limit=2)
    session = instance.open_tool_turn(CONTEXT, definitions())
    call = await session.start()
    assert json.loads(call.arguments_json)['brief'] == brief
    session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments', [
    json.dumps({'brief':'雨'*601, 'framing':'wide', 'lighting':'warm'}),
    ('{"brief":"x","framing":"wide","lighting":"warm"}').ljust(8193),
    '{"brief":"\\ud800","framing":"wide","lighting":"warm"}',
], ids=['too-many-characters','8193-wire-bytes','unpaired-surrogate'])
async def test_brief_character_scalar_and_wire_envelope_limits(arguments):
    async def handle(_): return response(wire([tool(name='generate_story_image', arguments=arguments)]))
    instance, _, _ = backend(handle, request_limit=2)
    with pytest.raises(DirectResponsesError): await instance.open_tool_turn(CONTEXT, definitions()).start()


@pytest.mark.asyncio
@pytest.mark.parametrize(('kind','value'), [('pose','camera_raise'), ('scene','rain_window')])
async def test_first_ordinary_candidate_requires_native_tools_for_authored_controls(kind, value):
    payload = {'effects':[{'kind':'subtitle','value':'我先抬起相机。'},{'kind':kind,'value':value}]}
    async def handle(request):
        prompt = json.loads(json.loads(request.content)['input'][0]['content'][0]['text'])
        assert 'authored_controls' not in prompt
        assert prompt['native_tool_contract']['fiction_only'] is True
        return response(wire([snapshot_message(json.dumps(payload))]))
    instance, _, requests = backend(handle, request_limit=2)
    candidate=await instance.open_tool_turn(CONTEXT,definitions()).start()
    assert [(e.kind.value,e.value) for e in candidate.effects]==[('subtitle',payload['effects'][0]['value'])]
    assert candidate.optional_hold.reasons==('native_function_required',)
    assert instance._reserved == 0 and len(requests) == 1


@pytest.mark.asyncio
async def test_first_ordinary_candidate_holds_legacy_story_and_affect_proposals():
    from tests.contracts.test_character_candidate_payload import context
    current = context()
    payload = {'effects':[{'kind':'subtitle','value':'我们继续听雨吧。'}],
        'story_proposal':{'transition_id':'t.chat','signal':'chat'},
        'affect_proposal':{'candidate':'happy','signal':'pleasant_shared_attention'}}
    async def handle(request):
        prompt = json.loads(json.loads(request.content)['input'][0]['content'][0]['text'])
        assert 'character_proposal_contract' not in prompt
        assert 'image_proposal_contract' not in prompt
        return response(wire([snapshot_message(json.dumps(payload))]))
    instance, _, _ = backend(handle, request_limit=2)
    candidate=await instance.open_tool_turn(current,definitions()).start()
    assert candidate.story_proposal_json is candidate.affect_proposal_json is None
    assert candidate.effects[0].value==payload['effects'][0]['value']
    assert candidate.optional_hold.reasons==('native_function_required',)


@pytest.mark.asyncio
@pytest.mark.parametrize('item', [
    snapshot_message('{"effects":[{"kind":"media","value":"trip_photo"}]}'),
    message(image_proposal=None),
])
async def test_first_ordinary_candidate_cannot_bypass_covered_image_tools(item):
    async def handle(_): return response(wire([item]))
    instance, _, _ = backend(handle, request_limit=2)
    with pytest.raises(DirectResponsesError): await instance.open_tool_turn(CONTEXT, definitions()).start()
