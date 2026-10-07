"""Closed local wardrobe evidence, independent of dialogue and presentation authority."""
import asyncio
import json
import zipfile
from dataclasses import replace

import pytest

from mira.adapters.diagnostics.privacy import encode_event, validate_event_record
from mira.adapters.diagnostics.export import export_diagnostics
from mira.application.contracts import generation_context_data, ReviewVerdict
from mira.application.diagnostic_events import DiagnosticEvent, DiagnosticStage, DiagnosticOutcome
from mira.domain.errors import DomainError
from mira.domain.models import EffectKind, Receipt
from tests.contracts.test_actor_story_loop import turn, acknowledge
from tests.contracts.test_character_control_bridge import setup, candidate, FullReview


class Sink:
    def __init__(self): self.events = []
    def emit(self, event): self.events.append(event)


def wardrobe(sink):
    return [e for e in sink.events if getattr(e, 'wardrobe', None) is not None]


def facts(sink):
    return [e.wardrobe for e in wardrobe(sink)]


@pytest.mark.asyncio
async def test_absent_and_unavailable_proposals_are_distinct_before_review():
    for controls, unavailable, expected in [((), (), 'absent'),
            (('outfit_cream_inner_only',), ('outfit_cream_inner_only',), 'held')]:
        actor, _, _, _ = setup(candidate(*controls), unavailable=unavailable)
        sink = Sink(); actor._diagnostics = sink
        try:
            state = await turn(actor, 'Synthetic private wardrobe intent.', 1)
            raw = [f for f in facts(sink) if f.phase == 'candidate']
            assert raw, 'Wardrobe diagnostics must precede character readiness filtering'
            assert raw[0].count == len(controls)
            ready = [f for f in facts(sink) if f.phase == 'readiness']
            assert ready[-1].state == expected
            assert ready[-1].reason == ('unavailable' if controls else 'no_proposal')
            assert not any(e.kind is EffectKind.POSE for e in state.active_grants)
        finally: await actor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('control', ['outfit_black_jacket', 'outfit_cream_inner_only', 'outfit_amber_raincoat'])
async def test_exact_receipt_next_context_and_same_outfit_are_not_failures(control):
    actor, character, generation, _ = setup(candidate(control))
    sink = Sink(); actor._diagnostics = sink
    try:
        state = await turn(actor, 'Synthetic intent.', 1)
        pose = next(e for e in state.active_grants if e.kind is EffectKind.POSE)
        assert any(f.phase == 'grant' and f.state == 'granted' for f in facts(sink))
        assert not any(f.state == 'presented' for f in facts(sink))
        with pytest.raises(DomainError):
            await actor.receipt(replace(Receipt(
                pose.id, pose.digest, pose.output_epoch, pose.activity_seq, 1), digest='wrong'))
        assert not any(f.state == 'presented' for f in facts(sink))
        await acknowledge(actor, pose, 1)
        await acknowledge(actor, pose, 1)
        presented = [e for e in wardrobe(sink) if e.wardrobe.state == 'presented']
        assert len(presented) == 1 and presented[0].context.effect_id == pose.id
        assert presented[0].wardrobe.acknowledged_outfit == control
        await turn(actor, 'Synthetic next request.', 2, 1)
        context = [f for f in facts(sink) if f.phase == 'context'][-1]
        assert context.outfit == control and context.acknowledged_outfit == control
        assert all(e.outcome is not DiagnosticOutcome.FAILED for e in wardrobe(sink))
        data = json.dumps(generation_context_data(generation.contexts[-1]))
        assert 'wardrobe_diagnostic' not in data and 'no_proposal' not in data
        assert character.runtime.story.current_outfit == control.removeprefix('outfit_')
    finally: await actor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('verdict,reason', [(ReviewVerdict.UNKNOWN, 'review_unknown'),
                                         (ReviewVerdict.REJECT, 'review_rejected')])
async def test_legacy_review_hold_has_no_wardrobe_grant(verdict, reason):
    actor, _, _, _ = setup(candidate('outfit_cream_inner_only'), review=FullReview(verdict=verdict))
    sink = Sink(); actor._diagnostics = sink
    try:
        await turn(actor, 'Synthetic private intent.', 1)
        assert any(f.phase == 'review' and f.state == 'held' and f.reason == reason for f in facts(sink))
        assert not any(f.phase in ('grant', 'receipt') for f in facts(sink))
    finally: await actor.close()


@pytest.mark.asyncio
async def test_stop_during_review_drops_late_result_without_diagnostic_revival():
    class Delayed(FullReview):
        def __init__(self): super().__init__(); self.arrived = asyncio.Event(); self.resume = asyncio.Event()
        async def review(self, context, output):
            self.arrived.set()
            try: await self.resume.wait()
            except asyncio.CancelledError: await self.resume.wait()
            return await super().review(context, output)
    review = Delayed()
    actor, _, _, _ = setup(candidate('outfit_amber_raincoat'), review=review)
    sink = Sink(); actor._diagnostics = sink
    try:
        await actor.submit(request_id='synthetic', activity_seq=1, cutoff=0, text='Synthetic private intent.')
        await asyncio.wait_for(review.arrived.wait(), 1)
        await actor.stop(activity_seq=2, cutoff=0)
        assert any(f.phase == 'cancel' and f.state == 'cancelled' for f in facts(sink))
        count = len(wardrobe(sink)); review.resume.set()
        await asyncio.gather(*tuple(actor._tasks), return_exceptions=True)
        assert len(wardrobe(sink)) == count
        assert not any(f.phase in ('grant', 'receipt') for f in facts(sink))
    finally: review.resume.set(); await actor.close()


@pytest.mark.asyncio
async def test_invalid_post_stop_receipt_and_valid_late_history_are_distinct():
    actor, _, _, _ = setup(candidate('outfit_cream_inner_only', 'outfit_black_jacket'))
    sink = Sink(); actor._diagnostics = sink
    try:
        state = await turn(actor, 'Synthetic change sequence.', 1)
        older, newer = state.active_grants[-2:]
        await acknowledge(actor, newer, 3)
        await actor.stop(activity_seq=2, cutoff=3)
        with pytest.raises(DomainError): await acknowledge(actor, older, 4)
        prior = len([f for f in facts(sink) if f.phase == 'receipt'])
        await acknowledge(actor, older, 2)
        rows = [f for f in facts(sink) if f.phase == 'receipt']
        assert len(rows) == prior + 1
        assert rows[-1].reason == 'historical_receipt'
        assert rows[-1].acknowledged_outfit == 'outfit_black_jacket'
        assert not (await actor.snapshot()).active_grants
    finally: await actor.close()


@pytest.mark.asyncio
async def test_export_roundtrip_keeps_old_records_and_excludes_private_text(tmp_path):
    actor, _, _, _ = setup(candidate('outfit_cream_inner_only'))
    sink = Sink(); actor._diagnostics = sink
    try:
        await turn(actor, 'SYNTHETIC_PRIVATE_SECRET_TEXT', 1)
        rows = [encode_event(e, 1000) for e in wardrobe(sink)]
        assert rows, 'Wardrobe metadata must survive the existing export pipeline'
        rows.append(encode_event(DiagnosticEvent(DiagnosticStage.HTTP, DiagnosticOutcome.SUCCEEDED), 999))
        assert all(validate_event_record(json.loads(json.dumps(r))) == r for r in rows)
        root = tmp_path / 'logs'; (root / 'events').mkdir(parents=True)
        (root / 'events' / 'events-synthetic.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        result = export_diagnostics(root, tmp_path / 'export.zip')
        assert result['skipped_records'] == 0 and result['event_count'] == len(rows)
        with zipfile.ZipFile(tmp_path / 'export.zip') as bundle:
            data = bundle.read('events.jsonl')
        assert b'SYNTHETIC_PRIVATE' not in data and '我们继续聊'.encode() not in data
        assert b'candidate_digest' not in data and b'prompt' not in data
    finally: await actor.close()


@pytest.mark.parametrize('field,value', [('phase','arbitrary-secret'), ('state','arbitrary-secret'),
    ('reason','arbitrary-secret'), ('outfit','emotion_happy'), ('outfit','arbitrary-secret'),
    ('acknowledged_outfit','camera_raise'), ('count',True), ('count',9), ('output_epoch',True),
    ('activity_seq',-1), ('caption','arbitrary-secret'), ('digest','a'*64)])
def test_closed_wardrobe_export_rejects_unexpected_values(field, value):
    import mira.application.diagnostic_events as contracts
    assert hasattr(contracts.DiagnosticStage, 'WARDROBE'), 'Closed wardrobe event stage is required'
    from mira.application.wardrobe_diagnostics import SafeWardrobeDiagnostic
    event = DiagnosticEvent(DiagnosticStage.WARDROBE, DiagnosticOutcome.SUCCEEDED,
        wardrobe=SafeWardrobeDiagnostic('candidate','proposed',1,1,'outfit_black_jacket',1))
    row = encode_event(event,1000); row['wardrobe'][field] = value
    with pytest.raises(ValueError): validate_event_record(row)


def conversation_actor(mode='allow', *, wire=None):
    from mira.bootstrap.development_review import create_development_review_providers
    from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V1
    from tests.contracts.test_conversation_first import Wire
    actor, character, generation, _ = setup(candidate('outfit_cream_inner_only'))
    wire = wire or Wire(mode)
    providers = create_development_review_providers(generation=generation,
        input_transport=wire,output_transport=wire,authorized=True,
        decision_policy=USER_DEVELOPMENT_0_6_V1,input_request_limit=8,output_request_limit=8,
        conversation_first=True)
    actor._semantic_review = providers.semantic_review
    actor._decision_owner = providers.decision_owner
    sink = Sink(); actor._diagnostics = sink
    return actor, character, generation, wire, sink


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,expected,reason', [('allow','granted',None),
    ('unknown','held','review_unknown'), ('reject','held','review_rejected'),
    ('invalid','held','review_failed'), ('transport','held','review_failed')])
async def test_conversation_first_closes_optional_outcome_without_blocking_text(mode, expected, reason):
    actor, _, generation, wire, sink = conversation_actor(mode)
    try:
        state = await turn(actor, 'SYNTHETIC_PRIVATE_WARDROBE', 1)
        assert state.sealed and state.last_error is None
        assert any(e.kind is EffectKind.SUBTITLE for e in state.active_grants)
        assert any(f.state == expected and (reason is None or f.reason == reason) for f in facts(sink))
        assert any(e.kind is EffectKind.POSE for e in state.active_grants) == (mode == 'allow')
        # These diagnostics never enter either provider's fact envelope.
        provider_data = json.dumps([generation_context_data(generation.contexts[-1]), wire.calls])
        for key in ('wardrobe_diagnostic', 'acknowledged_outfit', 'no_proposal', 'review_failed'):
            assert key not in provider_data
    finally: await actor.close()


@pytest.mark.asyncio
async def test_conversation_stop_during_output_review_preserves_local_cancel_only():
    from tests.contracts.test_conversation_first import Wire
    wire = Wire(gate=True)
    actor, _, _, _, sink = conversation_actor(wire=wire)
    try:
        await actor.submit(request_id='synthetic',activity_seq=1,cutoff=0,text='Synthetic private intent.')
        async with asyncio.timeout(1):
            while not wire.arrived.is_set(): await asyncio.sleep(.001)
        await actor.stop(activity_seq=2,cutoff=0)
        assert any(f.state == 'cancelled' for f in facts(sink))
        count = len(wardrobe(sink)); wire.resume.set()
        await asyncio.gather(*tuple(actor._tasks),return_exceptions=True)
        assert len(wardrobe(sink)) == count
        assert not any(f.phase in ('grant','receipt') for f in facts(sink))
    finally: wire.resume.set(); await actor.close()


@pytest.mark.asyncio
async def test_arbitrary_pose_cannot_leak_into_wardrobe_metadata():
    actor, _, _, _ = setup(candidate('accessory_star_clip'))
    sink = Sink(); actor._diagnostics = sink
    try:
        state = await turn(actor,'Synthetic private intent.',1)
        assert any(e.value == 'accessory_star_clip' for e in state.active_grants)
        encoded = json.dumps([encode_event(e,1000) for e in wardrobe(sink)])
        assert 'accessory_star_clip' not in encoded
        assert all(f.count == 0 for f in facts(sink))
    finally: await actor.close()


@pytest.mark.asyncio
async def test_stale_candidate_observation_cannot_reopen_cancelled_diagnostics():
    actor, _, generation, _ = setup(candidate('outfit_black_jacket'))
    sink = Sink(); actor._diagnostics = sink
    try:
        await turn(actor,'Synthetic intent.',1)
        stale = generation.contexts[-1]
        await actor.stop(activity_seq=2,cutoff=0)
        count = len(wardrobe(sink))
        async with actor._lock:
            actor._wardrobe_candidate(stale,1,candidate('outfit_amber_raincoat'))
        assert len(wardrobe(sink)) == count
        assert actor._wardrobe_waiting == (0,0,())
    finally: await actor.close()


@pytest.mark.asyncio
async def test_story_compiled_raincoat_is_distinct_from_a_generated_pose():
    from tests.contracts.test_actor_story_loop import setup as story_setup
    actor, _, _, _ = story_setup()
    sink = Sink(); actor._diagnostics = sink
    try:
        first = await turn(actor,'offer',1)
        await acknowledge(actor,first.active_grants[0],1)
        second = await turn(actor,'yes',2,1)
        assert any(e.value == 'outfit_amber_raincoat' for e in second.active_grants)
        rows = [f for f in facts(sink) if f.output_epoch == 2]
        assert any(f.phase == 'candidate' and f.state == 'absent' for f in rows)
        assert any(f.phase == 'readiness' and f.state == 'ready' and
                   f.outfit == 'outfit_amber_raincoat' and f.reason == 'story_compiled' for f in rows)
    finally: await actor.close()


@pytest.mark.asyncio
async def test_broken_diagnostic_sink_cannot_change_grants():
    class Broken:
        def emit(self, _): raise RuntimeError('SYNTHETIC_PRIVATE_SINK_ERROR')
    actor, _, _, _ = setup(candidate('outfit_black_jacket')); actor._diagnostics = Broken()
    try:
        state = await turn(actor,'Synthetic private intent.',1)
        assert state.sealed and state.last_error is None
        assert any(e.value == 'outfit_black_jacket' for e in state.active_grants)
    finally: await actor.close()
