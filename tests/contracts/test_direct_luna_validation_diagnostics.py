"""Tool-path candidate diagnostics keep closed facts without retaining provider text."""
from dataclasses import asdict
import json

import httpx
import pytest

from mira.adapters.generation.direct_codex_responses import DirectResponsesError
from tests.contracts.test_direct_codex_responses import (
    ByteStream, CONTEXT, backend, completed, event, response, snapshot_message,
)
from tests.contracts.test_direct_luna_tools import definitions, done, result, tool, wire


BAD_TEXT = [
    pytest.param('{"PRIVATE_CANDIDATE":', 'codex_json_invalid', 'syntax', 'bare_object', id='syntax'),
    pytest.param('```json\n{"PRIVATE_CANDIDATE":1}\n```', 'codex_json_invalid', 'syntax',
                 'markdown_fence', id='markdown'),
    pytest.param('{"PRIVATE_CANDIDATE":1,"PRIVATE_CANDIDATE":2}', 'codex_json_invalid',
                 'duplicate_key', 'bare_object', id='duplicate'),
    pytest.param('{"PRIVATE_CANDIDATE":NaN}', 'codex_json_invalid', 'nonfinite',
                 'bare_object', id='nonfinite'),
    pytest.param('{"PRIVATE_CANDIDATE":1}', 'codex_effects_invalid', None, None, id='schema'),
    pytest.param('{"effects":[{"kind":"PRIVATE_CANDIDATE","value":"synthetic"}]}',
                 'codex_effects_unsupported', None, None, id='unsupported'),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['ordinary', 'continuation', 'call-commentary'])
@pytest.mark.parametrize('text,reason,json_kind,shape', BAD_TEXT)
async def test_tool_candidate_validation_retains_safe_reason_and_json_classes(
        mode, text, reason, json_kind, shape):
    streams = []
    async def handle(_):
        if mode == 'continuation' and len(requests) == 1:
            body = wire([tool()])
        else:
            # Same accepted subscription compatibility forms as the user metadata.
            body = event('response.output_text.delta', {
                'type': 'response.output_text.delta', 'output_index': 0,
                'content_index': 0, 'item_id': 'msg-1', 'delta': text,
            }) + done(snapshot_message(text))
            if mode == 'call-commentary':
                body += done(tool(), 1)
            body += completed(output=[])
        stream = ByteStream([body])
        streams.append(stream)
        return httpx.Response(200, stream=stream)
    instance, source, requests = backend(handle, request_limit=2)
    turn = instance.open_tool_turn(CONTEXT, definitions())
    with pytest.raises(DirectResponsesError) as raised:
        if mode == 'continuation':
            await turn.start()
            await turn.continue_after_tool(result(), CONTEXT)
        else:
            await turn.start()
    error = raised.value
    diagnostic = error.generation_diagnostic
    assert error.code == 'invalid_response'
    assert diagnostic.phase == 'validation' and diagnostic.reason == reason
    assert diagnostic.json_failure_kind == json_kind and diagnostic.wrapper_shape == shape
    assert diagnostic.http_status == 200 and diagnostic.terminal_status == 'completed'
    assert diagnostic.header_compatibility == 'subscription_missing_content_type'
    assert diagnostic.terminal_compatibility == 'subscription_empty_output'
    assert diagnostic.completed_message_count == diagnostic.delta_message_count == 1
    assert 'PRIVATE_CANDIDATE' not in json.dumps(asdict(diagnostic)) + repr(error)
    assert all(stream.closed for stream in streams)
    assert len(requests) == source.calls == (2 if mode == 'continuation' else 1)
    assert instance._reserved == 0
    with pytest.raises(DirectResponsesError):
        await turn.continue_after_tool(result(), CONTEXT)
    assert len(requests) == (2 if mode == 'continuation' else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['ordinary', 'continuation'])
@pytest.mark.parametrize('exception,reason,code', [
    pytest.param(ValueError('PRIVATE_VALUE'), 'candidate_value_invalid', 'invalid_response', id='value'),
    pytest.param(TypeError('PRIVATE_TYPE'), 'candidate_value_invalid', 'invalid_response', id='type'),
    pytest.param(RuntimeError('PRIVATE_UNKNOWN'), 'validation', 'invalid_response', id='unknown'),
    pytest.param(RuntimeError('codex_output_limit'), 'codex_output_limit', 'output_limit', id='limit'),
])
async def test_tool_candidate_error_boundary_never_copies_arbitrary_exception_text(
        monkeypatch, mode, exception, reason, code):
    async def handle(_):
        return response(wire([tool()] if mode == 'continuation' and len(requests) == 1 else [
            snapshot_message('{"effects":[{"kind":"subtitle","value":"synthetic"}]}')]))
    instance, source, requests = backend(handle, request_limit=2)
    turn = instance.open_tool_turn(CONTEXT, definitions())
    if mode == 'continuation':
        await turn.start()
    def fail(*_args, **_kwargs):
        raise exception
    parser = 'parse_conversation_character_candidate' if mode == 'ordinary' else 'parse_effects'
    monkeypatch.setattr('mira.adapters.generation.direct_tools.' + parser, fail)
    with pytest.raises(DirectResponsesError) as raised:
        if mode == 'continuation':
            await turn.continue_after_tool(result(), CONTEXT)
        else:
            await turn.start()
    error = raised.value
    diagnostic = error.generation_diagnostic
    assert error.code == code and diagnostic.reason == reason and diagnostic.phase == 'validation'
    assert diagnostic.json_failure_kind is None and diagnostic.wrapper_shape is None
    assert 'PRIVATE_' not in repr(error) + json.dumps(asdict(diagnostic))
    assert len(requests) == source.calls == (2 if mode == 'continuation' else 1)
    assert instance._reserved == 0
