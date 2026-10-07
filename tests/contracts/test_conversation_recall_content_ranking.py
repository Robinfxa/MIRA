"""Synthetic durable evidence to real native wire; no model quality claim."""
from dataclasses import replace
import json

import pytest

from mira.application.conversation_archive import (
    ConversationRecallPacket, ConversationRecord, ConversationSnapshot, conversation_recall_data,
)
from mira.application.contracts import GenerationContext
from mira.application.story import StoryRuntime
from mira.bootstrap.character_story import builtin_definition
from mira.domain.models import AudioProgress, AudioStatus, EffectKind
from tests.contracts.test_conversation_archive import accepted, displayed, opened, receipt
from tests.contracts.test_direct_codex_responses import backend, ResponsesRoute, response
from tests.contracts.test_direct_luna_tools import definitions, message, wire


def input_record(index, text, *, request_id=None):
    return ConversationRecord(f'row-{index}', f'event-{index}', 1, 'accepted_input',
        json.dumps({'input': {'request_id': request_id or f'request-{index}',
            'output_epoch': index + 1, 'text': text, 'source': 'text',
            'user_input_index': index}}, ensure_ascii=False))


def recall(records, query, max_bytes=8192):
    return conversation_recall_data(ConversationSnapshot('synthetic-old-session', 3, tuple(records)),
                                    request_text=query, max_bytes=max_bytes)


def texts(data):
    return [row['payload']['input']['text'] for row in data['recalled_records']
            if row['evidence_stage'] in ('accepted_input', 'corrected_input')]


def test_chinese_question_retrieves_older_preference_and_episode_before_newer_noise():
    old = ('我喜欢茉莉花茶，咖啡通常不喝。', '上回聊过的灯塔照片，我想要纸质的。')
    records = [input_record(0, old[0]), input_record(1, old[1])]
    records += [input_record(i, f'合成无关天气消息{i}。') for i in range(2, 20)]
    result = recall(records, '还记得我的茉莉花茶和那张灯塔照片吗？')
    assert set(old) <= set(texts(result))
    assert len(result['recalled_records']) == 8 and result['history_omitted'] is True
    assert result['semantic_summary_available'] is False
    assert result['total_eligible_records'] == 20


def test_metadata_and_latin_substrings_do_not_outrank_dialogue():
    records = [input_record(0, 'I like rain and lavender.')]
    records += [input_record(i, 'A brain puzzle.', request_id=f'lavender-{i}') for i in range(1, 12)]
    result = recall(records, 'rain lavender')
    assert texts(result)[0] == 'I like rain and lavender.'
    assert result == recall(records, 'rain lavender')


def test_uncompleted_speech_text_cannot_win_recall_rank(tmp_path):
    archive = opened(tmp_path)
    try:
        archive.append_input('old-session', accepted(0, 'I prefer jasmine tea.'))
        for i in range(1, 10):
            archive.append_input('old-session', accepted(i, f'Synthetic unrelated {i}.'))
            effect = displayed(i, kind=EffectKind.SPEECH, text='jasmine jasmine future speech')
            progress = AudioProgress(effect.id, effect.digest, i + 1, i + 1, i,
                                     24000, 10, AudioStatus.INTERRUPTED)
            archive.append_receipt('old-session', effect, progress)
        result = conversation_recall_data(archive.load_session('old-session'), request_text='jasmine')
        assert 'I prefer jasmine tea.' in texts(result)
        assert 'future speech' not in json.dumps(result)
        assert result['physical_hearing_or_understanding_established'] is False
    finally:
        archive.close()


def test_corrected_forgotten_and_recent_denial_keep_source_precedence(tmp_path):
    archive = opened(tmp_path)
    try:
        old = archive.append_input('old-session', accepted(0, '我喜欢茉莉花茶。'))
        archive.append_receipt('old-session', displayed(0, text='记住了，你喜欢茉莉花茶。'),
                               receipt(displayed(0, text='记住了，你喜欢茉莉花茶。')))
        for i in range(1, 12):
            archive.append_input('old-session', accepted(i, f'合成无关消息{i}。'))
        archive.correct_input('old-session', old.entry_id, '更正：我不喜欢茉莉花茶。')
        snapshot = archive.load_session('old-session')
        result = conversation_recall_data(snapshot, request_text='还记得茉莉花茶吗？')
        assert '更正：我不喜欢茉莉花茶。' in texts(result)
        assert '我喜欢茉莉花茶。' not in texts(result)
        assert '记住了' not in json.dumps(result, ensure_ascii=False)
        corrected = next(row for row in snapshot.records if row.stage == 'corrected_input')
        archive.forget_input('old-session', corrected.entry_id)
        hidden = conversation_recall_data(archive.load_session('old-session'), request_text='茉莉花茶')
        assert '茉莉花茶' not in json.dumps(hidden, ensure_ascii=False)
    finally:
        archive.close()
    # Lexical matching alone cannot infer supersession; when otherwise tied,
    # the latest exact denial stays selected, still an untrusted statement.
    records = [input_record(i, 'I like jasmine.') for i in range(9)]
    records.append(input_record(9, 'I do not like jasmine.'))
    newest = recall(records, 'jasmine')
    assert 'I do not like jasmine.' in texts(newest)
    assert newest['recalled_records'][-1]['historical_record_index'] == 9


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
async def test_durable_reopen_to_native_wire_keeps_old_role_and_plan_historical(tmp_path, route):
    archive = opened(tmp_path)
    old_text = '我是夏禾；我喜欢茉莉花茶，明天想去灯塔拍照。'
    try:
        archive.append_input('prior-synthetic', accepted(0, old_text))
        for i in range(1, 13):
            archive.append_input('prior-synthetic', accepted(i, f'合成无关消息{i}。'))
        archive.close()
        archive.open(pairing_confirmed=True)
        query = '还记得我的茉莉花茶吗？'
        snapshot = archive.load_session('prior-synthetic')
        data = conversation_recall_data(snapshot, request_text=query)
        assert old_text in texts(data)
        assert not archive.load_session('another-synthetic').records
        packet = ConversationRecallPacket('prior-synthetic', snapshot.snapshot_revision,
                                          json.dumps(data, ensure_ascii=False))
        story = StoryRuntime(builtin_definition(), 'private-synthetic-character-scope')
        context = GenerationContext(query, (query,), (), 1,
            character_story=story.project().projection, conversation_recall=packet)
        async def handle(_request):
            return response(wire([message('你提过茉莉花茶。')]))
        instance, _, requests = backend(handle, route=route, request_limit=2)
        await instance.open_tool_turn(context, definitions()).start()
        body = json.loads(requests[0].content)
        facts = json.loads(body['input'][0]['content'][0]['text'])['facts']
        assert old_text in texts(facts['conversation_recall'])
        assert facts['first_person_dialogue']['speaker_contract']['frame'] == 'unrecognized_visitor'
        assert facts['character_story'].get('chapter', {}).get('role_active', False) is False
        assert story.story.chapter.role_active is False
        assert 'released_role_canon' not in facts['first_person_dialogue']['speaker_contract']
        assert facts['character_story']['acknowledged_presentations'] == []
        assert facts['presented_effects'] == []
        assert facts['conversation_recall']['semantic_summary_available'] is False
        assert 'private-synthetic-character-scope' not in requests[0].content.decode()
        assert 'prior-synthetic' not in requests[0].content.decode()
        assert body['store'] is False and len(requests) == 1
        await instance.open_tool_turn(replace(context, conversation_recall_status='unavailable'), ()).start()
        assert old_text not in requests[1].content.decode()
    finally:
        archive.close()


def test_whole_rows_and_byte_bound_remain_explicit():
    records = [input_record(0, '茉莉花茶' + '甲' * 8000)]
    records += [input_record(i, f'合成茉莉花茶消息{i}。') for i in range(1, 40)]
    result = recall(records, '茉莉花茶', max_bytes=1024)
    assert len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()) <= 1024
    assert len(result['recalled_records']) <= 8
    assert result['history_omitted'] is True
    for row in result['recalled_records']:
        original = records[row['historical_record_index']]
        assert row['payload'] == original.payload()
        assert row['source_version'] == original.source_version


def test_receipted_first_person_character_dialogue_remains_recallable(tmp_path):
    archive = opened(tmp_path)
    own_text = '我喜欢灰蓝里的暖光，线条稍歪也没关系。'
    try:
        archive.append_input('old-session', accepted(0, '你喜欢什么样的光？'))
        subtitle = displayed(0, text=own_text)
        archive.append_receipt('old-session', subtitle, receipt(subtitle))
        speech = replace(displayed(0, kind=EffectKind.SPEECH, text=own_text), id='speech-0')
        archive.append_receipt('old-session', speech, AudioProgress(speech.id, speech.digest,
            1, 1, 2, 24000, 24000, AudioStatus.COMPLETED))
        for i in range(1, 13):
            archive.append_input('old-session', accepted(i, f'合成无关消息{i}。'))
        archive.close()
        archive.open(pairing_confirmed=True)
        result = conversation_recall_data(archive.load_session('old-session'),
                                           request_text='你说过灰蓝里的暖光对吗？')
        dialogue = [row for row in result['recalled_records']
                    if row['evidence_stage'] in ('presented_effect', 'audio_progress')]
        assert {row['evidence_stage'] for row in dialogue} == {'presented_effect', 'audio_progress'}
        assert all(row['payload']['effect']['value'] == own_text for row in dialogue)
        assert result['physical_hearing_or_understanding_established'] is False
        assert result['semantic_summary_available'] is False
    finally:
        archive.close()
