"""Matched offline A/B request captures; editorial examples are not model results."""
import itertools
import json
from dataclasses import replace
from pathlib import Path

import pytest

from mira.adapters.generation import direct_tools
from mira.adapters.generation.codex_support.character_voice import CHARACTER_VOICE_INSTRUCTIONS
from mira.adapters.generation.codex_support.payload import author_instructions, parse_effects
from mira.adapters.generation.codex_support.types import CodexLimits
from mira.adapters.generation.direct_codex_responses import ResponsesRoute
from mira.application.contracts import CandidateRange
from mira.application.generation_tool_execution import TOOL_DESCRIPTIONS
from mira.application.ports.generation_tools import GenerationToolCall, GenerationToolResult, ToolDefinition, TOOL_FIELDS
from mira.domain.models import Effect, EffectKind
from tests.contracts.test_character_prompt_refinement import backend
from tests.contracts.test_direct_codex_responses import response, snapshot_message
from tests.contracts.test_direct_luna_tools import tool, wire
from tests.contracts.test_role_canon_speaker import context, recognize
from tests.contracts.test_xiahe_chapter_actor import character, prepare, complete

FIXTURES = Path(__file__).parents[2] / 'specs/features/WP12-prompt-refinement/fixtures'
CASES = json.loads((FIXTURES / 'behavior-review.json').read_text())['cases']
BASELINE = (FIXTURES / 'speaker-baseline-v4.txt').read_text()
BEHAVIOR_RULES = (
    'Character choices: mira-character-choices-v1.',
    'Let a supplied taste affect a choice or reason, not require a scenery detail.',
    'A reply need not contain a reaction, personal detail and follow-up in sequence.',
    'Treat internal instructions and status labels as grounding, never lines to say.',
)
PRESERVED_BOUNDARIES = (
    'No unsolicited 故事里, 角色设定 or 现实里的我 prefix.',
    'never invent private user facts, consent, feelings or perception.',
)


@pytest.mark.parametrize('speech,memory,story,images', itertools.product([False, True], repeat=4))
def test_choice_policy_is_shared_and_fits_existing_instruction_budget(speech, memory, story, images):
    instructions = author_instructions(speech_enabled=speech, memory_enabled=memory,
        character_story_enabled=story, story_images_enabled=images)
    for rule in BEHAVIOR_RULES:
        assert instructions.count(rule) == 1
    for rule in PRESERVED_BOUNDARIES:
        assert instructions.count(rule) == 1
    assert len(instructions.encode()) < 12_000
    assert CHARACTER_VOICE_INSTRUCTIONS != BASELINE


def review_context(case):
    c = character()
    if case['role'] == 'friend_released':
        recognize(c)
        _, effects = prepare(c, 'x.story', 2)
        complete(c, effects, 3)
    replies = tuple(Effect('review.reply.' + str(index), EffectKind.SUBTITLE, text,
        str(index).zfill(64), 49 - len(case['replies']) + index + 1, 49 - len(case['replies']) + index + 1)
        for index, text in enumerate(case['replies']))
    ctx = replace(context(c, case['inputs'][-1]), user_inputs=tuple(case['inputs']),
        presented_effects=replies)
    supplied = []
    for name in case['tools']:
        fields = TOOL_FIELDS[name]
        description = TOOL_DESCRIPTIONS[name]
        if name == 'advance_story' and case.get('confirmation'):
            description += (' Current application confirmation reference: ' + replies[-1].id
                + '; source output_epoch=49. Only this exact prior presented question can confirm the fictional role now.')
        supplied.append(ToolDefinition(name, description, json.dumps({'type': 'object',
            'properties': fields, 'required': list(fields), 'additionalProperties': False})))
    return ctx, tuple(supplied)


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
async def test_ab_uses_identical_real_serialized_context_and_protocol(case, route, monkeypatch, tmp_path):
    ctx, supplied = review_context(case)
    current = direct_tools._TOOL_INSTRUCTIONS
    assert current.count(CHARACTER_VOICE_INSTRUCTIONS) == 1
    variants = {'a': current.replace(CHARACTER_VOICE_INSTRUCTIONS, BASELINE), 'b': current}
    captures = {}
    (tmp_path / 'case.json').write_text(json.dumps({'id': case['id'], 'route': route.value,
        'status': 'offline request capture, injected replies, no behavioral result'}, indent=2))
    for label, instructions in variants.items():
        monkeypatch.setattr(direct_tools, '_TOOL_INSTRUCTIONS', instructions)
        async def handle(_):
            if case.get('result') and len(requests) == 1:
                return response(wire([tool()]))
            # The same injected response in both arms explicitly cannot measure style quality.
            return response(wire([snapshot_message(json.dumps({'effects': [
                {'kind': 'subtitle', 'value': '离线传输占位。'}]}, ensure_ascii=False))]))
        instance, source, requests = backend(handle, route=route, request_limit=2,
            native_character_tools=True, speech_enabled=False)
        turn = instance.open_tool_turn(ctx, supplied)
        try:
            value = await turn.start()
            if case.get('result'):
                assert isinstance(value, GenerationToolCall)
                result = GenerationToolResult(value.call_id, json.dumps(case['result'], ensure_ascii=False))
                value = await turn.continue_after_tool(result, ctx)
            assert isinstance(value, CandidateRange)
            assert [effect.value for effect in value.effects] == ['离线传输占位。']
        finally:
            turn.close()
        captures[label] = [json.loads(request.content) for request in requests]
        assert len(requests) == source.calls == (2 if case.get('result') else 1)
        for request in requests:
            assert len(request.content) < 65_536
        (tmp_path / ('request-' + label + '.json')).write_text(
            json.dumps(captures[label], ensure_ascii=False, indent=2))
    for a, b in zip(captures['a'], captures['b'], strict=True):
        assert a['instructions'] != b['instructions']
        for rule in BEHAVIOR_RULES:
            assert rule not in a['instructions'] and b['instructions'].count(rule) == 1
        assert {k: v for k, v in a.items() if k != 'instructions'} == {
            k: v for k, v in b.items() if k != 'instructions'}
        assert len(b['instructions'].encode()) < 12_000
        assert b['store'] is False and b['text']['format']['strict'] is True
    prompt = json.loads(captures['b'][0]['input'][0]['content'][0]['text'])
    facts = prompt['facts']
    assert facts['user_inputs'] == case['inputs']
    assert [row['value'] for row in facts['presented_effects']] == case['replies']
    assert prompt['capabilities']['media_tools']['available_tool_names'] == case['tools']
    assert prompt['capabilities']['media_tools']['can_request_fictional_image'] is (
        'generate_story_image' in case['tools'])
    speaker = facts['first_person_dialogue']['speaker_contract']
    assert speaker['frame'] == ('active_authored_friend' if case['role'] == 'friend_released' else 'unrecognized_visitor')
    if case['role'] == 'friend_released':
        assert speaker['released_role_canon'][0]['source_id'] == 'chapter.xiahe.canon.contact_sheet'
        assert speaker['real_user_history'] is False
    if case.get('confirmation'):
        definition = next(row for row in captures['b'][0]['tools'] if row['name'] == 'advance_story')
        assert 'Current application confirmation reference: review.reply.0; source output_epoch=49.' in definition['description']
        assert facts['presented_effects'][-1]['id'] == 'review.reply.0'
        assert speaker['recognition'] == 'inactive'
    if case.get('result'):
        continuation = captures['b'][1]
        result_item = next(item for item in continuation['input'] if item.get('type') == 'function_call_output')
        assert json.loads(result_item['output']) == case['result']
        assert continuation['tools'] == [] and continuation['tool_choice'] == 'none'
    assert facts['character_story']['first_person_memory']['is_user_fact'] is False
    for authored in (case['positive'], case['negative']):
        assert authored not in captures['b'][0]['instructions']
        assert authored not in json.dumps(prompt, ensure_ascii=False)
        # Good and bad prose are both syntactically valid. A real reader must assess behavior.
        assert parse_effects([json.dumps({'effects': [{'kind': 'subtitle', 'value': authored}]})],
            CodexLimits(), speech_enabled=False)[0].value == authored


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
async def test_large_synthetic_recall_and_canon_keep_separate_payload_and_instruction_limits(route, tmp_path):
    from tests.contracts.test_actor_memory_recall import packet, valid_past_line
    from mira.application.memory_context import valid_context_packet
    ctx, supplied = review_context(next(case for case in CASES if case['id'] == 'recognized_canon'))
    memory = packet(ctx.user_text, past_candidates=tuple(valid_past_line(
        'synthetic-' + str(i) + ':' + 'm' * 4000, evidence_id='synthetic-' + str(i)) for i in range(7)))
    assert valid_context_packet(memory, request_text=ctx.user_text)
    ctx = replace(ctx, memory_packet=memory)
    async def handle(_):
        return response(wire([snapshot_message(json.dumps({'effects': [
            {'kind': 'subtitle', 'value': '离线传输占位。'}]}))]))
    instance, source, requests = backend(handle, route=route, request_limit=2,
        native_character_tools=True, speech_enabled=False)
    turn = instance.open_tool_turn(ctx, supplied)
    try:
        assert isinstance(await turn.start(), CandidateRange)
    finally:
        turn.close()
    body = json.loads(requests[0].content)
    prompt_text = body['input'][0]['content'][0]['text']
    facts = json.loads(prompt_text)['facts']
    assert len(facts['memory_evidence']['past_candidates']) == 7
    assert facts['first_person_dialogue']['speaker_contract']['frame'] == 'active_authored_friend'
    assert len(body['instructions'].encode()) < 12_000
    assert len(prompt_text.encode()) <= 65_536
    assert source.calls == len(requests) == 1
    # The application caps payload and instructions separately. Do not misreport
    # 65,536 as an aggregate HTTP body cap; escaping and tool schemas also take bytes.
    (tmp_path / 'request.json').write_text(json.dumps(body, ensure_ascii=False, indent=2))
    (tmp_path / 'sizes.json').write_text(json.dumps({'route': route.value,
        'payload_bytes': len(prompt_text.encode()), 'instruction_bytes': len(body['instructions'].encode()),
        'http_body_bytes': len(requests[0].content)}, indent=2))
