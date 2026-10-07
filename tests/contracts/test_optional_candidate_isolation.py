"""Synthetic valid dialogue and optional failures; never private user transcript data."""
from dataclasses import replace
import json

import pytest

from mira.adapters.generation.direct_codex_responses import (
    DirectResponsesError, DirectResponsesLimits, _DirectResponseTrace, _payload_error_code,
)
from mira.adapters.generation.direct_tools import _ordinary_candidate
from mira.adapters.generation.codex_support.types import CodexGenerationError
from mira.application.contracts import candidate_data
from mira.domain.models import EffectKind, AudioProgress, AudioStatus
from mira.domain.story import PROPOSAL_SIGNAL_BY_TRANSITION, ReadinessCatalog
from tests.contracts.test_character_candidate_payload import context
from tests.contracts.test_character_control_bridge import ready_catalog
from tests.contracts.test_direct_codex_responses import backend, response, snapshot_message
from tests.contracts.test_direct_luna_tools import wire
from tests.contracts.test_luna_tool_actor import actor, wait_state
from tests.contracts.test_actor_story_loop import acknowledge
from tests.contracts.test_xiahe_chapter_actor import character
from tests.integration.test_voice_http import Tts


TEXT = '这是一条完整的合成回复。'


def body(*, speech=False):
    effects = [{'kind': 'subtitle', 'value': TEXT}]
    if speech:
        effects.append({'kind': 'speech', 'value': TEXT})
    return {'effects': effects, 'story_proposal': None, 'affect_proposal': None}


def role(text):
    return {'transition_id': 'x.recognize',
            'signal': PROPOSAL_SIGNAL_BY_TRANSITION['x.recognize'].value,
            'offer_id': None, 'target_capabilities': ['chapter.xiahe.recognition'], 'draft_cue': None,
            'input_act': {'kind': 'claim_role', 'evidence_text': text, 'role_name': '夏禾'},
            'reopen_offer': False}


def parse(value, *, speech=False, current=None):
    return _ordinary_candidate([json.dumps(value, ensure_ascii=False)], DirectResponsesLimits(),
        current or context(), speech, trace=_DirectResponseTrace())


@pytest.mark.parametrize('broken,reason', [
    ('story', 'story_proposal_invalid'), ('affect', 'affect_proposal_invalid'),
    ('pose', 'visual_controls_invalid'), ('scene', 'visual_controls_invalid'),
])
@pytest.mark.parametrize('speech', [False, True])
def test_bad_optional_preserves_exact_dialogue_and_holds_all_controls(broken, reason, speech):
    value = body(speech=speech)
    value['effects'].append({'kind': 'pose', 'value': 'outfit_amber_raincoat'})
    if broken in ('story', 'affect'):
        value[broken + '_proposal'] = {}
    else:
        value['effects'].append({'kind': broken, 'value': 'not_a_known_control'})
    candidate = parse(value, speech=speech)
    assert [(e.kind.value, e.value) for e in candidate.effects] == [
        (e['kind'], e['value']) for e in body(speech=speech)['effects']]
    assert candidate.story_proposal_json is candidate.affect_proposal_json is None
    assert candidate.optional_hold.reasons == (reason,)
    assert candidate.optional_hold.retained_subtitle_count == 1
    assert candidate.optional_hold.retained_speech_count == int(speech)
    assert 'optional_hold' not in candidate_data(candidate)


@pytest.mark.parametrize('bad', [
    {'effects': []}, {'effects': [{'kind': 'subtitle', 'value': ''}]},
    {'effects': [{'kind': 'subtitle', 'value': 'bad\x00text'}]},
    {'effects': [{'kind': 'speech', 'value': TEXT}]},
    {**body(), 'unknown': None}, {**body(), 'image_proposal': None},
    {**body(), 'image_proposal': {'brief': 'synthetic landscape'}},
    {'effects': [*body()['effects'], {'kind': 'media', 'value': 'trip_photo'}]},
    {'effects': [*body()['effects'], {'kind': 'unknown', 'value': 'x'}]},
    {'effects': [*body()['effects'], {'kind': 'pose', 'value': 'outfit_amber_raincoat', 'grant': True}]},
])
def test_structural_body_and_tool_bypasses_still_reject(bad):
    with pytest.raises(DirectResponsesError):
        parse(bad, speech=True)


@pytest.mark.parametrize('raw', ['{"effects":', '{"effects":[],"effects":[]}', '[]', 'not json'])
def test_no_recovery_from_broken_json_or_wrong_outer_shape(raw):
    with pytest.raises(DirectResponsesError):
        _ordinary_candidate([raw], DirectResponsesLimits(), context(), True, trace=_DirectResponseTrace())


def test_character_error_code_is_not_collapsed_and_valid_role_stays_typed():
    assert _payload_error_code(CodexGenerationError('codex_character_proposal_invalid')) == 'codex_character_proposal_invalid'
    current = replace(context(), user_text='我是夏禾', user_inputs=('我是夏禾',))
    value = body(); value['story_proposal'] = role(current.user_text)
    candidate = parse(value, current=current)
    assert candidate.story_proposal_json and candidate.optional_hold is None


@pytest.mark.asyncio
@pytest.mark.parametrize('speech', [False, True])
@pytest.mark.parametrize('second_role', [False, True])
async def test_real_wire_actor_two_turns_keep_dialogue_without_false_role_or_controls(speech, second_role):
    c = character()
    c.readiness = ReadinessCatalog('synthetic-all', ready_catalog().records + c.readiness.records)
    seen = []
    async def handle(request):
        sent = json.loads(request.content)
        user = json.loads(sent['input'][-1]['content'][0]['text'])['facts']['user_text']
        seen.append(user)
        value = body(speech=speech)
        if len(seen) == 1:
            value['story_proposal'] = role(user)
            value['effects'].append({'kind': 'pose', 'value': 'outfit_amber_raincoat'})
        elif second_role:
            value['story_proposal'] = role(user)
            value['effects'].append({'kind': 'scene', 'value': 'xiahe_recognition'})
        return response(wire([snapshot_message(json.dumps(value, ensure_ascii=False))]))
    direct, source, requests = backend(handle, native_character_tools=False, request_limit=4)
    value, _, legacy, review = actor(None, tools=direct, character=c)
    tts = Tts()
    if speech:
        value._speech_synthesis = tts
    class Sink:
        def __init__(self): self.events = []
        def emit(self, event): self.events.append(event)
    sink = Sink(); value._diagnostics = sink
    try:
        cutoff = 0
        for turn_number, text in enumerate(('合成的普通问候。', '我是夏禾' if second_role else '合成的后续话题。'), 1):
            await value.submit(request_id=f'synthetic-{turn_number}', activity_seq=turn_number,
                               cutoff=cutoff, text=text)
            state = await wait_state(value, lambda s: s.sealed or s.last_error is not None)
            assert state.last_error is None and state.sealed
            expected_kinds = {EffectKind.SUBTITLE, EffectKind.SPEECH} if speech else {EffectKind.SUBTITLE}
            if second_role and turn_number == 2:
                expected_kinds.add(EffectKind.SCENE)
            assert {e.kind for e in state.active_grants} == expected_kinds
            assert not c.runtime.story.chapter.role_active
            for effect in state.active_grants:
                if effect.kind is EffectKind.SPEECH:
                    operation = await value.open_speech(effect_id=effect.id, digest=effect.digest,
                        output_epoch=effect.output_epoch, activity_seq=effect.activity_seq)
                    packets = [p async for p in operation.values()]
                    assert packets and any(p.pcm for p in packets)
                    await value.close_media(operation)
                cutoff += 1
                if effect.kind is EffectKind.SPEECH:
                    await value.audio_progress(AudioProgress(effect.id, effect.digest,
                        effect.output_epoch, effect.activity_seq, cutoff, 24000,
                        sum(len(p.pcm) // 2 for p in packets), AudioStatus.COMPLETED))
                else:
                    await acknowledge(value, effect, cutoff)
            assert c.runtime.story.chapter.role_active == (second_role and turn_number == 2)
            assert c.runtime.story.current_outfit == 'black_jacket'
            assert all(e.kind in expected_kinds for e in (await value.snapshot()).presented_effects)
        held = [e.optional_candidate_hold for e in sink.events if getattr(e, 'optional_candidate_hold', None)]
        assert len(held) == 1 and held[0].reasons == ('story_proposal_invalid',)
        from mira.adapters.diagnostics.privacy import encode_event, validate_event_record
        held_event = next(e for e in sink.events if getattr(e, 'optional_candidate_hold', None))
        record = json.loads(json.dumps(encode_event(held_event, 1.0)))
        assert validate_event_record(record) == record
        assert TEXT not in json.dumps(record, ensure_ascii=False)
        assert len(requests) == source.calls == 2 and legacy.calls == 0
        assert direct._reserved == 0
    finally:
        await value.close()


def test_optional_diagnostic_is_closed_and_export_rejects_unknown_reason():
    from mira.application.optional_candidate_diagnostics import SafeOptionalCandidateDiagnostic
    for reasons in (('private text',), ('story_proposal_invalid', 'story_proposal_invalid'), ([],), ()):
        with pytest.raises(ValueError):
            SafeOptionalCandidateDiagnostic(reasons, 1, 0, 0)
    from mira.application.diagnostic_events import DiagnosticEvent, DiagnosticStage, DiagnosticOutcome
    from mira.adapters.diagnostics.privacy import encode_event
    hold = SafeOptionalCandidateDiagnostic(('story_proposal_invalid',), 1, 0, 0)
    with pytest.raises(ValueError):
        encode_event(DiagnosticEvent(DiagnosticStage.GENERATION, DiagnosticOutcome.SUCCEEDED,
                                   optional_candidate_hold=hold), 1.0)


def test_unknown_parser_exception_is_never_salvaged(monkeypatch):
    import mira.adapters.generation.codex_support.character_payload as payload
    def unknown(*args, **kwargs):
        raise RuntimeError('synthetic_unknown_failure')
    monkeypatch.setattr(payload, 'parse_character_candidate', unknown)
    value = body(); value['story_proposal'] = {}
    with pytest.raises(DirectResponsesError):
        parse(value)


def test_story_disabled_bad_pose_can_hold_without_enabling_proposal_slots():
    current = replace(context(), character_story=None)
    value = {'effects': [*body()['effects'], {'kind': 'pose', 'value': 'unknown_pose'}]}
    candidate = parse(value, current=current)
    assert [e.kind for e in candidate.effects] == [EffectKind.SUBTITLE]
    assert candidate.optional_hold.reasons == ('visual_controls_invalid',)
    with pytest.raises(DirectResponsesError):
        parse({**value, 'story_proposal': None}, current=current)
