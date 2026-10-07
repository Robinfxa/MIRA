"""Author contract, actual synthetic requests and evidence, not LLM quality scoring."""
import itertools
import json
from dataclasses import replace

import pytest
import httpx

from mira.adapters.generation.codex_support.payload import author_instructions, parse_effects
from mira.adapters.generation.codex_support.types import CodexLimits
from mira.adapters.generation.direct_codex_responses import DirectCodexResponsesGenerationBackend, ResponsesRoute
from mira.application.contracts import CandidateRange
from mira.application.ports.generation_tools import GenerationToolCall, GenerationToolResult
from mira.domain.models import Effect, EffectKind
from tests.contracts.test_direct_codex_responses import CredentialSource, response, snapshot_message
from tests.contracts.test_direct_luna_tools import definitions, tool, wire
from tests.contracts.test_role_canon_speaker import context
from tests.contracts.test_xiahe_chapter_actor import character


RESULT_REASON_RULE = (
    'Explain failure only from the actual tool result; if no cause is supplied, '
    'say it did not complete without guessing. Fictional provenance alone is not a failure cause.'
)
RULES = (
    'Earlier replies are evidence of what was said, not style templates to imitate.',
    'Do not insert rain, the cafe, the lighthouse or clothing into unrelated replies.',
    'Use the current action contract for a requested change;',
    'A clear role claim or confirmation calls for the supplied recognition operation,',
    'Dialogue alone never activates the role.',
    'Every assistant message must be a complete JSON object matching the supplied output schema:',
    'Native function_call items remain separate from dialogue JSON;',
    RESULT_REASON_RULE,
)


def backend(handler, *, route, request_limit, native_character_tools, speech_enabled):
    requests, source = [], CredentialSource()
    async def inspect(request):
        requests.append(request)
        return await handler(request)
    instance = DirectCodexResponsesGenerationBackend(route, 'synthetic-model', source,
        admitted=True, request_limit=request_limit, native_character_tools=native_character_tools,
        speech_enabled=speech_enabled, transport=httpx.MockTransport(inspect))
    return instance, source, requests


@pytest.mark.parametrize('speech,memory,story,images', itertools.product([False, True], repeat=4))
def test_all_author_capabilities_fit_unchanged_instruction_bound(speech, memory, story, images):
    instructions = author_instructions(speech_enabled=speech, memory_enabled=memory,
        character_story_enabled=story, story_images_enabled=images)
    assert len(instructions.encode()) < 12_000
    for rule in RULES:
        assert instructions.count(rule) == 1
    assert 'Use one relevant authored detail naturally.' not in instructions
    assert 'include its available authored pose in the same cue' not in instructions
    assert 'with intended wording and independent review' not in instructions


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('speech', [False, True])
async def test_serialized_native_and_legacy_keep_latest_referent_without_old_action_instruction(
        route, native, speech, tmp_path):
    c = character()
    ctx = context(c, '看看', long=True)
    # Deliberately awkward earlier prose stays as evidence; do not clean real history.
    old = Effect('old.photo', EffectKind.SUBTITLE, '灯塔照片一直在等你看。', 'a' * 64, 47, 47)
    latest = Effect('recent.outfit', EffectKind.SUBTITLE, '要去门口的话，可以加件雨衣。', 'b' * 64, 49, 49)
    ctx = replace(ctx, user_inputs=(*ctx.user_inputs[:-1], '门口会不会冷？', '看看'),
        presented_effects=(*ctx.presented_effects, old, latest))
    effects = [{'kind': 'subtitle', 'value': '合成传输回复。'}]
    if speech:
        effects.append({'kind': 'speech', 'value': '合成传输回复。'})
    async def handle(_):
        return response(wire([snapshot_message(json.dumps({'effects': effects}))]))
    instance, source, requests = backend(handle, route=route, request_limit=2,
        native_character_tools=native, speech_enabled=speech)
    turn = instance.open_tool_turn(ctx, definitions()[:1])
    try:
        assert isinstance(await turn.start(), CandidateRange)
    finally:
        turn.close()
    body = json.loads(requests[0].content)
    prompt = json.loads(body['input'][0]['content'][0]['text'])
    instructions = body['instructions']
    for rule in RULES:
        assert instructions.count(rule) == 1
    assert 'include its available authored pose in the same cue' not in instructions
    assert len(instructions.encode()) < 12_000 and len(requests[0].content) < 65_536
    facts = prompt['facts']
    assert facts['user_inputs'][-2:] == ['门口会不会冷？', '看看']
    assert facts['presented_effects'][-1]['value'] == latest.value
    assert any(row['value'] == old.value for row in facts['presented_effects'])
    assert facts['first_person_dialogue']['speaker_contract']['frame'] == 'unrecognized_visitor'
    assert facts['first_person_dialogue']['trust'] == 'untrusted_quoted_evidence'
    assert facts['character_story']['first_person_memory']['is_user_fact'] is False
    assert body['text']['format']['strict'] is True
    assert body['tools'][0]['name'] == 'show_photo'
    assert ('native_tool_contract' in prompt) is native
    assert ('authored_controls' in prompt) is (not native)
    assert ('character_proposal_contract' in prompt) is (not native)
    assert len(requests) == source.calls == 1
    (tmp_path / 'serialized-request.json').write_text(json.dumps(body, ensure_ascii=False, indent=2))


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('status', ['shown', 'pending', 'failed', 'unavailable'])
async def test_function_call_is_not_json_dialogue_and_continuation_receives_exact_result(
        route, native, status, tmp_path):
    c = character()
    ctx = context(c, '看看那张照片')
    async def handle(_):
        if len(requests) == 1:
            return response(wire([tool()]))
        return response(wire([snapshot_message(json.dumps({'effects': [
            {'kind': 'subtitle', 'value': '合成结果续答。'}]}))]))
    instance, source, requests = backend(handle, route=route, request_limit=2,
        native_character_tools=native, speech_enabled=False)
    turn = instance.open_tool_turn(ctx, definitions()[:1])
    call = await turn.start()
    assert isinstance(call, GenerationToolCall)
    result = GenerationToolResult(call.call_id, json.dumps({
        'schema': 'mira.tool-result.v1', 'status': status, 'shown': status == 'shown',
        'code': 'receipt_unconfirmed' if status == 'pending' else status,
    }))
    fresh = replace(ctx, photo_visible=status == 'shown', photo_visibility_revision=1)
    try:
        assert isinstance(await turn.continue_after_tool(result, fresh), CandidateRange)
    finally:
        turn.close()
    bodies = [json.loads(request.content) for request in requests]
    output = next(row for row in bodies[1]['input'] if row.get('type') == 'function_call_output')
    assert output['call_id'] == call.call_id and output['output'] == result.output_json
    assert bodies[1]['tools'] == [] and bodies[1]['tool_choice'] == 'none'
    assert 'This is the final continuation' in bodies[1]['instructions']
    assert 'Native function_call items remain separate from dialogue JSON;' in bodies[1]['instructions']
    assert bodies[1]['instructions'].count(RESULT_REASON_RULE) == 1
    assert json.loads(bodies[1]['input'][-1]['content'][0]['text'])['tool_turn_state']['photo_visible'] is (status == 'shown')
    assert all(len(body['instructions'].encode()) < 12_000 for body in bodies)
    assert all(len(request.content) < 65_536 for request in requests)
    assert len(requests) == source.calls == 2
    (tmp_path / 'serialized-requests.json').write_text(json.dumps(bodies, ensure_ascii=False, indent=2))


@pytest.mark.parametrize('raw', [
    '合成普通正文。',
    '```json\n{"effects":[{"kind":"subtitle","value":"合成。"}]}\n```',
    '{"effects":[{"kind":"subtitle","value":"合成。"}]} 后缀',
    '{"effects":[{"kind":"subtitle","value":"合成。"}],"effects":[]}',
])
def test_strict_output_failures_remain_failures_without_guessing_live_output(raw):
    with pytest.raises(RuntimeError):
        parse_effects([raw], CodexLimits(), speech_enabled=False)
