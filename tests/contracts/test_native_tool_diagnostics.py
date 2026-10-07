"""Payload-free native tool observations through the existing export chain."""
import asyncio
import json
import zipfile
from dataclasses import replace

import pytest

from mira.adapters.diagnostics.privacy import encode_event, validate_event_record
from mira.adapters.diagnostics.export import export_diagnostics
from mira.application.diagnostic_events import DiagnosticEvent, DiagnosticStage, DiagnosticOutcome
from tests.contracts.test_native_chapter_wire import WireSession
from tests.contracts.test_native_character_tools import story_call
from tests.contracts.test_authored_photo_events import receipt
from tests.contracts.test_luna_tool_actor import wait_state
from tests.contracts.test_development_review_composition import finish


class Sink:
    def __init__(self): self.events = []
    def emit(self, event): self.events.append(event)


def rows(sink):
    return [e for e in sink.events if getattr(e, 'native_tool', None) is not None]


@pytest.mark.asyncio
async def test_actual_held_and_shown_tools_export_closed_facts_without_input_or_arguments(tmp_path):
    s = WireSession(); sink = Sink(); s.a._diagnostics = sink
    try:
        text = 'SYNTHETIC_PRIVATE_NATIVE_INPUT'
        result, _ = await s.turn(text, story_call('x.gift_accept', act='accept_gift',
            text=text, offer='PRIVATE_OFFER_ID'))
        result, _ = await s.turn('我是夏he', story_call('x.recognize', act='claim_role', text='我是夏he'))
        values = [e.native_tool for e in rows(sink)]
        assert [v.status for v in values] == ['requested', 'held', 'requested', 'shown']
        assert all(v.tool == 'advance_story' for v in values)
        assert values[1].reason == 'chapter_precondition' and values[1].transition == 'x.gift_accept'
        assert values[1].chapter_before == values[1].chapter_after == 'stranger_cafe'
        assert values[1].role_before is values[1].role_after is False
        assert values[-1].transition == 'x.recognize' and values[-1].receipt_kind == 'scene'
        assert values[-1].chapter_before == 'stranger_cafe' and values[-1].chapter_after == 'recognized'
        assert values[-1].role_before is False and values[-1].role_after is True
        records = [encode_event(e, 1000) for e in rows(sink)]
        records.append(encode_event(DiagnosticEvent(DiagnosticStage.HTTP, DiagnosticOutcome.SUCCEEDED), 999))
        assert all(validate_event_record(json.loads(json.dumps(r))) == r for r in records)
        root = tmp_path / 'logs'; (root / 'events').mkdir(parents=True)
        (root / 'events' / 'events-synthetic.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
        summary = export_diagnostics(root, tmp_path / 'export.zip')
        assert summary['skipped_records'] == 0 and summary['event_count'] == len(records)
        with zipfile.ZipFile(tmp_path / 'export.zip') as bundle:
            data = bundle.read('events.jsonl')
        for forbidden in (text, 'PRIVATE_OFFER_ID', '我是夏he', 'arguments', 'draft_cue', 'call_id', 'digest'):
            assert forbidden.encode() not in data
        assert all('native_tool' not in p['facts'] for p in s.prompts)
    finally:
        await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('fence', ['stop', 'new_input'])
async def test_cancelled_native_operation_never_borrows_new_epoch_chapter(fence):
    s = WireSession(); sink = Sink(); s.a._diagnostics = sink
    try:
        s.epoch = 1; s.plan = story_call('x.recognize', act='claim_role', text='我是夏he')
        await s.a.submit(request_id='first', activity_seq=1, cutoff=0, text='我是夏he')
        await wait_state(s.a, lambda state: any(e.value == 'xiahe_recognition' for e in state.active_grants))
        if fence == 'stop':
            await s.a.stop(activity_seq=2, cutoff=0)
        else:
            s.epoch = 2; s.plan = '聊咖啡吧。'
            await s.a.submit(request_id='second', activity_seq=2, cutoff=0, text='聊咖啡吧')
        await finish(s.a)
        values = [e.native_tool for e in rows(sink)]
        assert [v.status for v in values] == ['requested', 'cancelled']
        assert values[-1].output_epoch == values[-1].activity_seq == 1
        assert values[-1].chapter_before == 'stranger_cafe' and values[-1].role_before is False
        assert values[-1].chapter_after is values[-1].role_after is values[-1].receipt_kind is None
        assert not s.c.runtime.story.chapter.role_active
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_missing_receipt_is_pending_not_shown_and_broken_sink_does_not_block_body():
    s = WireSession(); sink = Sink(); s.a._diagnostics = sink
    try:
        s.a._tool_result_wait_seconds = .01
        result, _ = await s.turn('我是夏he', story_call('x.recognize', act='claim_role', text='我是夏he'), acknowledge=False)
        assert result['status'] == 'pending'
        values = [e.native_tool for e in rows(sink)]
        assert len(values) == 2 and values[-1].status == 'pending'
        assert values[-1].receipt_kind is None and values[-1].role_after is False
        class Broken:
            def emit(self, event): raise ValueError('SYNTHETIC_PRIVATE_SINK_ERROR')
        s.a._diagnostics = Broken()
        result, state = await s.turn('请给我照片', story_call('x.gift_accept', act='accept_gift', text='请给我照片', offer='bad'))
        assert result['status'] == 'held' and not state.last_error
        assert any(e.value == '我们接着聊。' for e in state.presented_effects)
    finally:
        await s.close()


@pytest.mark.parametrize('field,value', [
    ('tool','PRIVATE_TOOL'), ('status','PRIVATE_STATUS'), ('reason','PRIVATE_REASON'),
    ('transition','PRIVATE_TRANSITION'), ('chapter_before','PRIVATE_STAGE'),
    ('chapter_after','PRIVATE_STAGE'), ('role_before','yes'), ('role_after',1),
    ('receipt_kind','PRIVATE_RECEIPT'), ('output_epoch',True), ('activity_seq',-1),
    ('arguments','PRIVATE_ARGUMENTS'), ('draft_cue','PRIVATE_CUE'), ('input','PRIVATE_INPUT'),
    ('digest','a'*64), ('raw','PRIVATE_RAW'),
])
def test_native_diagnostic_export_rejects_unknown_fields_and_nonfinite_values(field, value):
    assert hasattr(DiagnosticStage, 'NATIVE_TOOL'), 'Native operations need closed diagnostic observations'
    from mira.application.native_tool_diagnostics import SafeNativeToolDiagnostic
    event = DiagnosticEvent(DiagnosticStage.NATIVE_TOOL, DiagnosticOutcome.SUCCEEDED,
        native_tool=SafeNativeToolDiagnostic('advance_story','held',1,1,
            transition='x.gift_accept', reason='chapter_precondition',
            chapter_before='stranger_cafe', chapter_after='stranger_cafe', role_before=False, role_after=False))
    row = encode_event(event,1000); row['native_tool'][field] = value
    with pytest.raises(ValueError): validate_event_record(row)


def test_native_diagnostic_cannot_attach_to_unrelated_stage_or_mutate_after_validation():
    assert hasattr(DiagnosticStage, 'NATIVE_TOOL')
    from mira.application.native_tool_diagnostics import SafeNativeToolDiagnostic
    value = SafeNativeToolDiagnostic('show_photo','pending',1,1)
    with pytest.raises(ValueError):
        encode_event(DiagnosticEvent(DiagnosticStage.HTTP, DiagnosticOutcome.SUCCEEDED, native_tool=value), 1000)
    object.__setattr__(value, 'tool', 'PRIVATE_FORGED_TOOL')
    with pytest.raises(ValueError):
        encode_event(DiagnosticEvent(DiagnosticStage.NATIVE_TOOL, DiagnosticOutcome.SUCCEEDED, native_tool=value), 1000)


@pytest.mark.parametrize('tool', ['show_photo', 'generate_story_image', 'cancel_story_image', 'set_outfit', 'set_accessory',
    'set_emotion', 'perform_action', 'set_scene', 'advance_story'])
def test_exact_nine_tool_names_roundtrip_without_adding_arbitrary_metadata(tool):
    assert hasattr(DiagnosticStage, 'NATIVE_TOOL')
    from mira.application.native_tool_diagnostics import SafeNativeToolDiagnostic, TOOL_NAMES
    from mira.application.ports.generation_tools import TOOL_FIELDS
    assert TOOL_NAMES == set(TOOL_FIELDS) and len(TOOL_NAMES) == 9
    event = DiagnosticEvent(DiagnosticStage.NATIVE_TOOL, DiagnosticOutcome.STARTED,
        native_tool=SafeNativeToolDiagnostic(tool, 'requested', 2, 3))
    row = encode_event(event, 1000)
    assert validate_event_record(row) == row


@pytest.mark.asyncio
async def test_actual_photo_result_is_media_receipt_without_gift_transition():
    from mira.application.ports.generation_tools import GenerationToolCall
    s = WireSession(); sink = Sink(); s.a._diagnostics = sink
    try:
        await s.turn('看看照片', GenerationToolCall('photo', 'show_photo', '{"photo_id":"trip_photo"}'))
        value = rows(sink)[-1].native_tool
        assert value.tool == 'show_photo' and value.status == 'shown' and value.receipt_kind == 'media'
        assert value.transition is None
        assert value.chapter_before == value.chapter_after == 'stranger_cafe'
        assert not value.role_after
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_awaiting_dialogue_reason_survives_actual_actor_privacy_export_and_read(tmp_path):
    s=WireSession();sink=Sink();s.a._diagnostics=sink
    try:
        await s.turn('我是夏he',story_call('x.recognize',act='claim_role',text='我是夏he'))
        result,state=await s.turn('继续说吧',story_call('x.story',cue='PRIVATE_CONTROL_SENTINEL'))
        assert result['status']=='pending' and result['phase']=='awaiting_dialogue'
        event=rows(sink)[-1]
        assert event.native_tool.status=='pending'
        assert event.native_tool.reason=='awaiting_dialogue'
        assert event.native_tool.receipt_kind is None
        record=encode_event(event,1000)
        root=tmp_path/'metadata';(root/'events').mkdir(parents=True)
        (root/'events'/'events-synthetic.jsonl').write_text(json.dumps(record)+'\n')
        summary=export_diagnostics(root,tmp_path/'diagnostic.zip')
        assert summary['event_count']==1 and summary['skipped_records']==0
        with zipfile.ZipFile(tmp_path/'diagnostic.zip') as z:
            raw=z.read('events.jsonl');saved=json.loads(raw)
        assert validate_event_record(saved)==record
        assert saved['native_tool']['reason']=='awaiting_dialogue'
        assert b'PRIVATE_CONTROL_SENTINEL' not in raw
        assert 'draft_cue' not in saved['native_tool'] and 'phase' not in saved['native_tool']
    finally:await s.close()


def test_old_pending_diagnostic_without_dialogue_reason_stays_compatible():
    from mira.application.native_tool_diagnostics import SafeNativeToolDiagnostic
    event=DiagnosticEvent(DiagnosticStage.NATIVE_TOOL,DiagnosticOutcome.SUCCEEDED,
        native_tool=SafeNativeToolDiagnostic('advance_story','pending',1,1,
            transition='x.recognize',chapter_before='stranger_cafe',chapter_after='stranger_cafe',
            role_before=False,role_after=False))
    record=encode_event(event,1000)
    assert validate_event_record(json.loads(json.dumps(record)))==record
    assert record['native_tool']['reason'] is None


@pytest.mark.parametrize('reason', ['awaiting_dialogue PRIVATE_CONTROL_SENTINEL',
    'PRIVATE_CONTROL_SENTINEL', {'phase':'awaiting_dialogue'}, ['awaiting_dialogue']])
def test_dialogue_diagnostic_still_rejects_arbitrary_original_text(reason):
    from mira.application.native_tool_diagnostics import SafeNativeToolDiagnostic
    record=encode_event(DiagnosticEvent(DiagnosticStage.NATIVE_TOOL,DiagnosticOutcome.SUCCEEDED,
        native_tool=SafeNativeToolDiagnostic('advance_story','pending',1,1)),1000)
    record['native_tool']['reason']=reason
    with pytest.raises(ValueError):validate_event_record(record)
