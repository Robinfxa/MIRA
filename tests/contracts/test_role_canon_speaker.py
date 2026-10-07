"""Same-source authored role history, real state transitions, synthetic transports.

Replies are injected. These tests do not claim model conversational quality.
"""
from dataclasses import replace
import json

import pytest

from mira.adapters.generation.codex_support.payload import author_instructions
from mira.adapters.generation.direct_codex_responses import ResponsesRoute
from mira.application.contracts import GenerationContext, generation_context_data
from mira.domain.models import Effect, EffectKind
from mira.domain.xiahe_chapter import CHAPTER_CANON
from tests.contracts.test_xiahe_chapter_actor import character, prepare, complete
from tests.contracts.test_direct_codex_responses import backend, collect, response, snapshot_message
from tests.contracts.test_direct_luna_tools import definitions, wire


def context(c, user='以前那件小事，你还记得吗？', *, long=False):
    inputs = tuple(f'合成普通聊天{i}' for i in range(40)) if long else ()
    replies = tuple(Effect(f'synthetic.{i}', EffectKind.SUBTITLE, f'合成普通回复{i}',
        str(i).zfill(64), i + 1, i + 1) for i in range(40)) if long else ()
    return GenerationContext(user, (*inputs, user), replies, 50,
        character_story=c.runtime.project().projection)


def speaker(c):
    return generation_context_data(context(c))['first_person_dialogue']['speaker_contract']


def recognize(c):
    _, effects = prepare(c, 'x.recognize', 1, '我是夏禾', act='claim_role')
    complete(c, effects)


def test_role_address_changes_only_after_matching_receipt_and_stays_inactive_after_exit():
    c = character()
    assert speaker(c) == {'frame': 'unrecognized_visitor', 'recognition': 'inactive'}
    _, effects = prepare(c, 'x.recognize', 1, '我是夏禾', act='claim_role')
    assert speaker(c) == {'frame': 'unrecognized_visitor', 'recognition': 'pending'}
    complete(c, tuple(e for e in effects if e.kind is EffectKind.SUBTITLE))
    assert speaker(c)['frame'] == 'unrecognized_visitor'
    complete(c, tuple(e for e in effects if e.kind is EffectKind.SCENE), 2)
    active = speaker(c)
    assert active['frame'] == 'active_authored_friend' and active['role_name'] == '夏禾'
    assert active['recognition'] == 'presented'
    assert [row['source_id'] for row in active['released_role_canon']] == [source for _, source, _ in CHAPTER_CANON[1:]]
    assert all(not row['narration_receipted_this_session'] for row in active['released_role_canon'])
    assert active['current_beat_reference'] == 'character_story.chapter.author_canon_for_current_beat'
    assert active['real_user_history'] is False
    prepare(c, 'x.exit', 2, '我不是夏禾', act='exit_role')
    assert speaker(c) == {'frame': 'unrecognized_visitor', 'recognition': 'inactive'}


def test_stopped_or_spoken_recognition_never_unlocks_authored_friend_history():
    c = character()
    _, effects = prepare(c, 'x.recognize', 1, '我是夏禾', act='claim_role')
    c.stop(2)
    complete(c, effects)
    assert speaker(c)['frame'] == 'unrecognized_visitor'
    proposal_like_text = '害，我说你这么眼熟呢，我就是夏he啊'
    spoken = Effect('spoken.only', EffectKind.SUBTITLE, '夏禾，原来是你。', 'a' * 64, 2, 2)
    ctx = replace(context(c, '没错啊，就是我'),
        user_inputs=(proposal_like_text, '没错啊，就是我'), presented_effects=(spoken,))
    data = generation_context_data(ctx)
    assert data['first_person_dialogue']['speaker_contract']['frame'] == 'unrecognized_visitor'
    assert all(text not in json.dumps(data, ensure_ascii=False) for _, _, text in CHAPTER_CANON)


def test_released_same_source_canon_survives_history_cutback_without_future_layers():
    c = character(); recognize(c)
    for epoch in (2, 3):
        _, effects = prepare(c, 'x.story', epoch)
        complete(c, effects, epoch * 2)
    data = generation_context_data(context(c, long=True))
    assert data['conversation_history']['historical_detail_omitted'] is True
    frame = data['first_person_dialogue']['speaker_contract']
    assert frame['released_role_canon'] == [
        {'source_id': source, 'text': text, 'availability': 'active_authored_role',
         'narration_receipted_this_session': beat in ('old_friend','old_friend_2')}
        for beat, source, text in CHAPTER_CANON if beat != 'old_friend_3']
    current = data['character_story']['chapter']['author_canon_for_current_beat']
    assert [(row['source_id'], row['text']) for row in current] == [CHAPTER_CANON[2][1:]]
    encoded = json.dumps(data, ensure_ascii=False)
    assert all(encoded.count(text) == 1 for _, _, text in CHAPTER_CANON[:3])
    assert encoded.count(CHAPTER_CANON[3][2]) == 1
    assert frame['canon_source_reference'] == 'character_story.chapter'
    assert not data['first_person_dialogue']['physical_hearing_or_understanding_established']


def test_short_visual_followup_retains_latest_outfit_evidence_and_excludes_pending_photo():
    c = character()
    ctx = context(c, '看看', long=True)
    outfit = Effect('raincoat.reply', EffectKind.SUBTITLE, '那件雨衣的袖口能收紧。', 'b' * 64, 49, 49)
    pending = Effect('photo.draft', EffectKind.SUBTITLE, '给你看看灯塔照片。', 'c' * 64, 50, 50)
    ctx = replace(ctx, user_inputs=(*ctx.user_inputs[:-1], '刚才那件雨衣是什么样？', '看看'),
        presented_effects=(*ctx.presented_effects, outfit), accepted_prefix=(pending,))
    data = generation_context_data(ctx)
    dialogue = data['first_person_dialogue']
    inputs = [data['user_inputs'][int(row['quoted_text_reference'][12:-1])]
              for row in dialogue['user_statements']]
    replies = [data['presented_effects'][int(row['quoted_text_reference'][18:-7])]['value']
               for row in dialogue['presented_replies']]
    assert inputs[-2:] == ['刚才那件雨衣是什么样？', '看看']
    assert replies[-1] == outfit.value and pending.value not in replies
    assert ctx.presented_effects[-1] == outfit and ctx.accepted_prefix == (pending,)


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('use_tools', [False, True])
async def test_actual_serialized_requests_keep_role_canon_after_history_cutback(route, use_tools, tmp_path):
    c = character(); recognize(c)
    _, effects = prepare(c, 'x.story', 2); complete(c, effects, 3)
    ctx = context(c, long=True)
    async def handle(_):
        return response(wire([snapshot_message(json.dumps({'effects': [
            {'kind': 'subtitle', 'value': '合成传输回复。'}]}))]))
    direct, source, requests = backend(handle, route=route, request_limit=2)
    if use_tools:
        turn = direct.open_tool_turn(ctx, definitions()[:1])
        try:
            await turn.start()
        finally:
            turn.close()
    else:
        assert len(await collect(direct, ctx)) == 1
    body = json.loads(requests[0].content)
    facts = json.loads(body['input'][0]['content'][0]['text'])['facts']
    assert facts['first_person_dialogue']['speaker_contract']['released_role_canon'] == [
        {'source_id': source, 'text': text, 'availability': 'active_authored_role',
         'narration_receipted_this_session': beat == 'old_friend'}
        for beat, source, text in CHAPTER_CANON if beat != 'old_friend_2']
    assert facts['conversation_history']['historical_detail_omitted'] is True
    assert len(requests) == source.calls == 1 and body['store'] is False
    assert len(requests[0].content) < 65_536
    instructions = body['instructions']
    assert 'first_person_dialogue.speaker_contract' in instructions
    assert 'Shared history needs reliable dialogue or qualified receipts.' not in instructions
    assert 'truthfully identify as an AI portraying the fictional character Mira' in instructions
    (tmp_path / 'serialized-request.json').write_text(json.dumps(body, ensure_ascii=False, indent=2))


def test_canon_speaker_policy_has_one_shared_consumer_and_preserves_budget():
    instructions = author_instructions(speech_enabled=False, memory_enabled=True, character_story_enabled=True)
    assert 'first_person_dialogue.speaker_contract' in instructions
    assert 'Only source-backed dialogue and receipts support shared history.' not in instructions
    assert 'released_role_canon' in instructions
    assert len(instructions.encode()) < 12_000


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
async def test_tool_wire_tracks_stranger_pending_receipt_and_exit_without_dialogue_identity(route, tmp_path):
    c = character()
    states = [context(c, '记得我吗？')]
    _, effects = prepare(c, 'x.recognize', 1, '我是夏禾', act='claim_role')
    states.append(context(c, '我刚刚不是已经说了嘛？'))
    complete(c, effects)
    states.append(context(c, '以前的事呢？'))
    prepare(c, 'x.exit', 2, '我不是夏禾', act='exit_role')
    states.append(context(c, '我们先聊别的。'))
    expected = [('unrecognized_visitor', 'inactive'), ('unrecognized_visitor', 'pending'),
                ('active_authored_friend', 'presented'), ('unrecognized_visitor', 'inactive')]
    async def handle(_):
        return response(wire([snapshot_message(json.dumps({'effects': [
            {'kind': 'subtitle', 'value': '合成传输回复。'}]}))]))
    direct, source, requests = backend(handle, route=route, request_limit=5)
    bodies = []
    for ctx, (frame, recognition) in zip(states, expected):
        turn = direct.open_tool_turn(ctx, definitions()[:1])
        try:
            await turn.start()
        finally:
            turn.close()
        body = json.loads(requests[-1].content); bodies.append(body)
        facts = json.loads(body['input'][0]['content'][0]['text'])['facts']
        speaker = facts['first_person_dialogue']['speaker_contract']
        assert (speaker['frame'], speaker['recognition']) == (frame, recognition)
        assert speaker.get('role_name') == ('夏禾' if frame == 'active_authored_friend' else None)
        assert not facts['presented_effects']
        if frame != 'active_authored_friend':
            assert all(text not in json.dumps(facts, ensure_ascii=False) for _, _, text in CHAPTER_CANON)
    assert len(requests) == source.calls == len(states)
    (tmp_path / 'serialized-state-sequence.json').write_text(json.dumps(bodies, ensure_ascii=False, indent=2))


@pytest.mark.asyncio
async def test_native_speaker_serializes_same_released_canon_contract(tmp_path):
    from tests.contracts.test_codex_generation import SyntheticTransport, agent, collect, event, make, terminal
    c = character(); recognize(c)
    _, effects = prepare(c, 'x.story', 2); complete(c, effects, 3)
    ctx = context(c, long=True)
    raw = json.dumps({'effects': [{'kind': 'subtitle', 'value': '合成传输回复。'}]})
    transport = SyntheticTransport(events=[event('item/completed', item=agent(raw)), terminal()])
    generation, _, factory = make(transport, speech_enabled=False)
    assert len(await collect(generation, ctx)) == 1
    start = next(call['params'] for call in transport.sent if call['method'] == 'thread/start')
    turn = next(call['params'] for call in transport.sent if call['method'] == 'turn/start')
    facts = json.loads(turn['input'][0]['text'])['facts']
    assert facts['first_person_dialogue']['speaker_contract'] == speaker(c)
    assert facts['conversation_history']['historical_detail_omitted'] is True
    assert 'first_person_dialogue.speaker_contract' in start['baseInstructions']
    assert len(factory.calls) == 1 and transport.closed
    (tmp_path / 'serialized-native-request.json').write_text(json.dumps(
        {'start': start, 'turn': turn}, ensure_ascii=False, indent=2))
