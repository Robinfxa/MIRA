"""Responses must request structured candidate text without weakening local tool guards."""
from dataclasses import replace
import json

import pytest

from mira.adapters.generation.direct_codex_responses import DirectResponsesError, ResponsesRoute
from mira.application.character_controls import CHARACTER_POSES
from mira.application.ports.generation_tools import GenerationToolCall
from tests.contracts.test_character_candidate_payload import context as story_context
from tests.contracts.test_direct_codex_responses import backend, CONTEXT, response, snapshot_message
from tests.contracts.test_direct_luna_tools import definitions, result, tool, wire


def payload(*, story=False, controls=False, speech=False):
    effects = [{'kind': 'subtitle', 'value': '合成对话。'}]
    if speech:
        effects.append({'kind': 'speech', 'value': '合成对话。'})
    if controls:
        effects.extend([{'kind': 'pose', 'value': CHARACTER_POSES[0]},
                        {'kind': 'scene', 'value': 'rain_window'}])
    value = {'effects': effects}
    if story:
        value.update(story_proposal=None, affect_proposal=None)
    return value


def strict_objects(schema):
    if isinstance(schema, dict):
        if schema.get('type') == 'object':
            assert schema['additionalProperties'] is False
            assert set(schema['required']) == set(schema['properties'])
        for value in schema.values():
            strict_objects(value)
    elif isinstance(schema, list):
        for value in schema:
            strict_objects(value)


def text_schema(body):
    assert 'text' in body, 'The actual Responses request lacks text.format.'
    fmt = body['text']['format']
    assert fmt['type'] == 'json_schema' and fmt['strict'] is True
    assert fmt['name'] == 'mira_tool_cue_v1'
    schema = fmt['schema']
    assert schema['type'] == 'object' and 'anyOf' not in schema
    strict_objects(schema)
    assert len(json.dumps(schema).encode()) < 16384
    assert 'media' not in {v['properties']['kind']['enum'][0]
                          for v in schema['properties']['effects']['items']['anyOf']}
    assert 'image_proposal' not in schema['properties']
    return schema


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('story', [False, True])
@pytest.mark.parametrize('speech', [False, True])
async def test_first_request_has_strict_dialogue_schema_and_tools_own_actions(route, story, speech):
    current = story_context() if story else CONTEXT
    value = payload(speech=speech)
    async def handle(request):
        schema = text_schema(json.loads(request.content))
        alternatives = schema['properties']['effects']['items']['anyOf']
        kinds = {v['properties']['kind']['enum'][0] for v in alternatives}
        assert kinds == ({'subtitle','speech'} if speech else {'subtitle'})
        assert set(schema['properties']) == {'effects'}
        return response(wire([snapshot_message(json.dumps(value))]))
    instance, source, requests = backend(handle, route=route, request_limit=2)
    instance._speech_enabled = speech
    candidate = await instance.open_tool_turn(current, definitions()).start()
    assert [(e.kind.value, e.value) for e in candidate.effects] == [(e['kind'], e['value']) for e in value['effects']]
    assert candidate.story_proposal_json is None and candidate.affect_proposal_json is None
    assert len(requests) == source.calls == 1 and instance._reserved == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
async def test_story_proposals_cannot_bypass_native_function_authority(route):
    current = story_context()
    value = payload(story=True)
    value['story_proposal'] = {'transition_id': 't.chat', 'signal': 'chat', 'offer_id': None,
                              'target_capabilities': [], 'draft_cue': None}
    value['affect_proposal'] = {'candidate': 'happy', 'signal': 'pleasant_shared_attention',
                               'canon_reason_id': None}
    async def handle(request):
        schema = text_schema(json.loads(request.content))
        assert set(schema['properties']) == {'effects'}
        return response(wire([snapshot_message(json.dumps(value))]))
    instance, _, requests = backend(handle, route=route, request_limit=2)
    candidate=await instance.open_tool_turn(current,definitions()).start()
    assert candidate.effects[0].value==value['effects'][0]['value']
    assert candidate.story_proposal_json is candidate.affect_proposal_json is None
    assert candidate.optional_hold.reasons==('native_function_required',)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('speech', [False, True])
async def test_tool_call_keeps_ordinary_commentary_and_continuation_is_text_only(route, speech):
    current = story_context()
    first = payload()
    final = payload(speech=speech)
    async def handle(request):
        body = json.loads(request.content)
        schema = text_schema(body)
        if len(requests) == 1:
            assert body['tool_choice'] == 'auto' and len(body['tools']) == 2
            return response(wire([snapshot_message(json.dumps(first)), tool()]))
        assert body['tool_choice'] == 'none' and body['tools'] == []
        assert set(schema['properties']) == {'effects'}
        kinds = {v['properties']['kind']['enum'][0] for v in schema['properties']['effects']['items']['anyOf']}
        assert kinds == ({'subtitle', 'speech'} if speech else {'subtitle'})
        assert any(item.get('type') == 'function_call_output' for item in body['input'])
        return response(wire([snapshot_message(json.dumps(final))]))
    instance, source, requests = backend(handle, route=route, request_limit=2)
    instance._speech_enabled = speech
    turn = instance.open_tool_turn(current, definitions())
    first_call=await turn.start()
    assert type(first_call) is GenerationToolCall and first_call.commentary.effects[0].value==first['effects'][0]['value']
    candidate = await turn.continue_after_tool(result(), current)
    assert len(candidate.effects) == len(final['effects'])
    assert len(requests) == source.calls == 2 and instance._reserved == 0
    with pytest.raises(DirectResponsesError):
        await turn.continue_after_tool(result(), current)
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [
    ('story_proposal', {'transition_id': 't.chat', 'signal': 'chat'}),
    ('affect_proposal', {'candidate': 'happy', 'signal': 'pleasant_shared_attention'}),
    ('image_proposal', None), ('unknown', None),
])
async def test_call_commentary_never_discards_nonnull_proposals_or_unknown_fields(field, value):
    candidate = payload(story=True)
    candidate[field] = value
    async def handle(_):
        return response(wire([snapshot_message(json.dumps(candidate)), tool()]))
    instance, _, requests = backend(handle, request_limit=2)
    with pytest.raises(DirectResponsesError):
        await instance.open_tool_turn(story_context(), definitions()).start()
    assert len(requests) == 1 and instance._reserved == 0


@pytest.mark.asyncio
async def test_story_disabled_call_commentary_still_rejects_nullable_proposal_slots():
    async def handle(_):
        return response(wire([snapshot_message(json.dumps(payload(story=True))), tool()]))
    instance, _, requests = backend(handle, request_limit=2)
    with pytest.raises(DirectResponsesError):
        await instance.open_tool_turn(CONTEXT, definitions()).start()
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_last_request_slot_still_sends_schema_with_tools_disabled():
    async def handle(request):
        body = json.loads(request.content)
        text_schema(body)
        assert body['tools'] == [] and body['tool_choice'] == 'none'
        return response(wire([snapshot_message(json.dumps(payload()))]))
    instance, _, requests = backend(handle, request_limit=1)
    await instance.open_tool_turn(CONTEXT, definitions()).start()
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['provider-rejects', 'provider-returns-plain'])
async def test_unsupported_format_or_noncompliant_text_never_retries_or_falls_back(mode):
    async def handle(request):
        text_schema(json.loads(request.content))
        if mode == 'provider-rejects':
            return response(b'{"error":{"code":"invalid_request_error","param":"text.format","message":"PRIVATE_PROVIDER"}}', status=400)
        return response(wire([snapshot_message('Synthetic non-JSON text.')]))
    instance, source, requests = backend(handle, request_limit=2)
    with pytest.raises(DirectResponsesError) as raised:
        await instance.open_tool_turn(CONTEXT, definitions()).start()
    error = raised.value
    assert error.stage == ('http_status' if mode == 'provider-rejects' else 'validation')
    assert len(requests) == source.calls == 1 and instance._reserved == 0
    assert 'PRIVATE_PROVIDER' not in repr(error) + repr(error.generation_diagnostic)
