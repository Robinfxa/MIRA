"""Synthetic full-review -> exact grant -> presentation-history character bridge."""
import asyncio
import json
import sqlite3
from dataclasses import replace
from uuid import uuid4

import pytest
from tests.integration.test_voice_http import Tts

from mira.adapters.journal.memory import MemoryEventJournal
from mira.adapters.memory.story import StoryCheckpointStore, VersionMismatch
from mira.application.actor_story import SessionCharacterRuntime
from mira.application.character_controls import CHARACTER_CAPABILITIES
from mira.application.contracts import (
    CandidateRange, CharacterSemanticEvidence, CharacterSemanticValue as V,
    EffectProposal, ReviewObservation, ReviewVerdict,
)
from mira.application.decision_contracts import evidence_digest
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.application.story import StoryRuntime
from mira.bootstrap.character_story import builtin_definition, reenter_runtime
from mira.domain.errors import DomainError
from mira.domain.models import EffectKind, Receipt, SessionState
from mira.domain.story import (
    Affect, CapabilityRecord, CapabilityState, OfferStatus, ReadinessCatalog, StoryNode,
    valid_story_projection,
)
from tests.contracts.test_actor_story_loop import acknowledge, turn


def _run(coroutine):
    # A private loop factory avoids replacing pytest-asyncio's managed policy loop
    # when these synchronous contract cases run after asynchronous ASGI cases.
    with asyncio.Runner(loop_factory=asyncio.new_event_loop) as runner:
        return runner.run(coroutine)


def ready_catalog(*, unavailable=()):
    return ReadinessCatalog('synthetic-controls-v1', tuple(
        CapabilityRecord(capability, CapabilityState.UNAVAILABLE if control in unavailable else CapabilityState.READY,
                         'synthetic-assets-v1', ('outer.amber', 'inner.cream'), 'synthetic-software-only')
        for control, capability in CHARACTER_CAPABILITIES.items()
    ))


def candidate(*controls, affect=None, subtitle=True, speech=False, story=None):
    effects = ((EffectProposal(EffectKind.SUBTITLE, '我们继续聊。'),) if subtitle else ())
    if speech:
        effects += (EffectProposal(EffectKind.SPEECH, 'Let us keep talking.'),)
    effects += tuple(EffectProposal(EffectKind.POSE, control) for control in controls)
    return CandidateRange(effects, 'synthetic', story_proposal_json=json.dumps(story) if story else None,
                          affect_proposal_json=json.dumps(affect) if affect else None)


def affect(label='happy', signal='pleasant_shared_attention'):
    value = {'candidate': label, 'signal': signal}
    if label == 'shy':
        value['canon_reason_id'] = 'canon.shy_response'
    return value


class Generation:
    def __init__(self, output):
        self.output = output
        self.contexts = []

    async def generate(self, context):
        self.contexts.append(context)
        yield self.output(context) if callable(self.output) else self.output


class FullReview:
    def __init__(self, *, verdict=ReviewVerdict.ALLOW, supported=V.YES, specific=V.NO,
                 willingness=V.UNKNOWN, refusal=V.NO):
        self.verdict = verdict
        self.supported = supported
        self.specific = specific
        self.willingness = willingness
        self.refusal = refusal
        self.calls = []

    async def review(self, context, output):
        self.calls.append((context, output))
        evidence = CharacterSemanticEvidence(evidence_digest(context), evidence_digest(output),
            relevance=V.YES, willingness=self.willingness, refusal=self.refusal,
            affect_supported=self.supported, specific_notice=self.specific)
        return ReviewObservation(self.verdict, 'synthetic-full-review', character_evidence=evidence)


def setup(output, *, review=None, unavailable=(), runtime=None):
    character = SessionCharacterRuntime(runtime or StoryRuntime(builtin_definition(), 'synthetic-scope'),
                                        ready_catalog(unavailable=unavailable))
    generation = Generation(output)
    review = review or FullReview()
    actor = SessionActor(SessionState(str(uuid4()), str(uuid4())), generation, review, MemoryEventJournal(100),
                         RuntimeLimits(3, 40, 100), character_runtime=character, speech_synthesis=Tts())
    return actor, character, generation, review


@pytest.mark.parametrize('control,slot,value', [
    ('outfit_cream_inner_only', 'outfit', 'cream_inner_only'),
    ('outfit_amber_raincoat', 'outfit', 'amber_raincoat'),
    ('outfit_black_jacket', 'outfit', 'black_jacket'),
    ('accessory_star_clip', 'accessory', 'star_clip'),
    ('accessory_camera_clip', 'accessory', 'camera_clip'),
])
def test_direct_reviewed_controls_work_without_story_progress_and_only_receipts_are_history(control, slot, value):
    async def run():
        actor, character, _, review = setup(candidate(control))
        try:
            state = await turn(actor, 'Please change this appearance.', 1)
            assert state.sealed and state.last_error is None
            assert len(review.calls) == 1
            visual = next(e for e in state.active_grants if e.value == control)
            assert character.runtime.story.node is StoryNode.CAFE_CHAT
            assert getattr(character.runtime.story, 'last_acknowledged_' + slot) is None
            assert not character.runtime.story.episodes
            await acknowledge(actor, state.active_grants[0], 1)
            await acknowledge(actor, visual, 2)
            story = character.runtime.story
            assert getattr(story, 'last_acknowledged_' + slot) == value
            assert story.node is StoryNode.CAFE_CHAT and story.relationship_delta == 0
            assert len(story.episodes) == 1
            episode = story.episodes[0]
            assert episode.compiled_effect_id == visual.id and episode.compiled_effect_digest == visual.digest
            assert episode.component_digest == visual.digest
            assert 'not_user_fact_or_shared_experience' in episode.claim_boundary
            assert episode.status == 'candidate_only'
            await acknowledge(actor, visual, 2)
            assert character.runtime.story == story
        finally:
            await actor.close()
    _run(run())


@pytest.mark.parametrize('verdict', [ReviewVerdict.REJECT, ReviewVerdict.UNKNOWN])
def test_full_independent_no_unknown_still_blocks_ready_controls(verdict):
    async def run():
        actor, character, _, review = setup(candidate('outfit_cream_inner_only', 'accessory_star_clip'),
                                          review=FullReview(verdict=verdict))
        try:
            state = await turn(actor, 'Keep my existing restrictions.', 1)
            assert len(review.calls) == 1, 'Ready wardrobe must reach ordinary complete content review'
            assert state.last_error and not state.active_grants
            assert character.runtime.story.current_outfit == 'black_jacket'
            assert not character.runtime.story.episodes
        finally:
            await actor.close()
    _run(run())


@pytest.mark.parametrize('control', list(CHARACTER_CAPABILITIES))
def test_unavailable_control_is_dropped_before_full_review_preserving_text(control):
    async def run():
        actor, character, _, review = setup(candidate(control), unavailable=(control,))
        try:
            state = await turn(actor, 'Please use the unavailable control.', 1)
            assert state.sealed and [e.kind for e in state.active_grants] == [EffectKind.SUBTITLE]
            assert [e.kind for e in review.calls[0][1].effects] == [EffectKind.SUBTITLE]
            assert not character.runtime.story.episodes
        finally:
            await actor.close()
    _run(run())


def test_happy_hysteresis_drops_first_visual_but_preserves_exact_reviewed_speech_pair():
    async def run():
        output = candidate('emotion_happy', affect=affect(), speech=True)
        actor, character, _, review = setup(output)
        try:
            first = await turn(actor, 'That is a pleasant shared observation.', 1)
            assert first.sealed
            assert character.runtime.affect.emotion is Affect.NORMAL
            assert [e.kind for e in first.active_grants] == [EffectKind.SUBTITLE, EffectKind.SPEECH]
            assert len(review.calls[0][1].effects) == 3, 'Emotion was independently reviewed before filtering'
            subtitle, speech = first.active_grants
            assert subtitle.cue_id == speech.cue_id and subtitle.cue_speech_id == speech.id
            assert speech.cue_speech_id == speech.id
            await actor.stop(activity_seq=2, cutoff=0)
            second = await turn(actor, 'Another pleasant observation.', 3)
            assert second.sealed and character.runtime.affect.emotion is Affect.HAPPY
            visual = next(e for e in second.active_grants if e.value == 'emotion_happy')
            assert character.runtime.story.last_acknowledged_emotion is None
            await acknowledge(actor, visual, 1)
            assert character.runtime.story.last_acknowledged_emotion == 'happy'
            assert character.runtime.story.node is StoryNode.CAFE_CHAT
        finally:
            await actor.close()
    _run(run())


@pytest.mark.parametrize('supported', [V.NO, V.UNKNOWN])
def test_weak_affect_evidence_never_grants_proposed_happy(supported):
    async def run():
        actor, character, _, _ = setup(candidate('emotion_happy', affect=affect()),
                                      review=FullReview(supported=supported))
        try:
            for activity in (1, 3):
                state = await turn(actor, 'An uncertain signal.', activity)
                assert state.sealed and all(e.value != 'emotion_happy' for e in state.active_grants)
                await actor.stop(activity_seq=activity + 1, cutoff=0)
            assert character.runtime.affect.emotion is Affect.NORMAL
            assert not character.runtime.story.episodes
        finally:
            await actor.close()
    _run(run())


def test_only_unadmitted_visual_returns_bounded_unknown_without_inventing_normal_effect():
    async def run():
        actor, character, _, review = setup(candidate('emotion_happy', affect=affect(), subtitle=False))
        try:
            state = await turn(actor, 'A single pleasant moment.', 1)
            assert len(review.calls) == 1
            assert state.last_error == 'review_uncertain' and not state.active_grants
            assert not state.issued_effects and not character.runtime.story.episodes
        finally:
            await actor.close()
    _run(run())


def test_stop_before_receipt_rejects_new_presentation_and_stop_after_keeps_history():
    async def run():
        actor, character, _, _ = setup(candidate('accessory_star_clip'))
        try:
            first = await turn(actor, 'Use the star clip.', 1)
            visual = first.active_grants[-1]
            await actor.stop(activity_seq=2, cutoff=0)
            with pytest.raises(DomainError, match='stop fence'):
                await acknowledge(actor, visual, 1)
            assert not character.runtime.story.episodes
            second = await turn(actor, 'Use the star clip now.', 3)
            await acknowledge(actor, second.active_grants[-1], 1)
            before = character.runtime.story.episodes
            await actor.stop(activity_seq=4, cutoff=1)
            assert character.runtime.story.episodes == before
            assert character.runtime.story.last_acknowledged_accessory == 'star_clip'
        finally:
            await actor.close()
    _run(run())


def test_valid_late_pre_stop_receipt_is_history_only_and_newer_appearance_wins():
    async def run():
        actor, character, _, _ = setup(candidate('outfit_cream_inner_only', 'outfit_black_jacket'))
        try:
            first = await turn(actor, 'Remove then replace the jacket.', 1)
            old_visual = first.active_grants[-2]
            await acknowledge(actor, first.active_grants[-1], 3)
            stopped = await actor.stop(activity_seq=2, cutoff=3)
            await acknowledge(actor, old_visual, 2)
            story = character.runtime.story
            assert len(story.episodes) == 2
            assert story.current_outfit == 'black_jacket' and story.last_acknowledged_outfit == 'black_jacket'
            assert story.node is StoryNode.CAFE_CHAT
            assert (await actor.snapshot()).active_grants == stopped.active_grants == ()
        finally:
            await actor.close()
    _run(run())


def test_reentry_exposes_historical_appearance_without_grants_or_restore_claim():
    async def run():
        actor, character, _, _ = setup(candidate('outfit_cream_inner_only', 'accessory_star_clip', 'emotion_normal'))
        try:
            state = await turn(actor, 'Use these reviewed controls.', 1)
            for seq, effect in enumerate(state.active_grants, 1):
                await acknowledge(actor, effect, seq)
            restored = reenter_runtime(StoryRuntime.from_snapshot(character.runtime.definition, character.runtime.snapshot()))
            bridge = SessionCharacterRuntime(restored, ready_catalog())
            projection = bridge.begin_input('new-browser-input', 1)
            view = json.loads(projection.context_json)
            assert valid_story_projection(projection)
            assert view['last_acknowledged_appearance'] == {
                'outfit': 'cream_inner_only', 'accessory': 'star_clip', 'emotion': 'normal'}
            assert view['appearance_scope'] == 'historical_software_presentation_not_current_browser_restoration'
            assert view['appearance_restoration_acknowledged'] is False
            before = restored.story
            bridge.acknowledge(Receipt(state.active_grants[-1].id, state.active_grants[-1].digest,
                state.active_grants[-1].output_epoch, state.active_grants[-1].activity_seq, 4), state.active_grants[-1])
            assert restored.story == before
        finally:
            await actor.close()
    _run(run())


def test_schema3_migrates_unknown_visual_fields_and_next_revision_writes_schema4(tmp_path):
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    path = private / 'story.sqlite3'
    runtime = StoryRuntime(builtin_definition(), 'synthetic-scope')
    runtime.story = replace(runtime.story, current_outfit='amber_raincoat', offer_status=OfferStatus.DECLINED)
    store = StoryCheckpointStore(path, enabled=True, explicitly_authorized=True,
                                 authorized_scope_id='synthetic-scope')
    store.save(runtime.story, runtime.affect)
    with sqlite3.connect(path) as db:
        data = json.loads(db.execute('SELECT story_json FROM story_checkpoint').fetchone()[0])
        for key in tuple(data):
            if key.startswith('last_acknowledged_'):
                data.pop(key)
        db.execute('UPDATE story_checkpoint SET schema_version=3, story_json=?', (json.dumps(data),))
    params = dict(graph_id=runtime.story.graph_id, graph_revision=runtime.story.graph_revision,
                  canon_revision=runtime.story.canon_revision, graph_hash=runtime.story.graph_hash,
                  canon_hash=runtime.story.canon_hash)
    loaded, loaded_affect = store.load('synthetic-scope', runtime.story.story_id, **params)
    assert loaded.current_outfit == 'amber_raincoat' and loaded.offer_status is OfferStatus.DECLINED
    assert loaded.last_acknowledged_outfit is None
    assert loaded.last_acknowledged_accessory is None and loaded.last_acknowledged_emotion is None
    store.save(replace(loaded, revision=loaded.revision + 1), loaded_affect)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT schema_version FROM story_checkpoint').fetchone()[0] == 6
        db.execute('UPDATE story_checkpoint SET schema_version=99')
    with pytest.raises(VersionMismatch):
        store.load('synthetic-scope', runtime.story.story_id, **params)


def test_guarded_happy_shy_normal_are_independent_of_plot_and_phase():
    async def run():
        actor, character, generation, review = setup(candidate('emotion_happy', affect=affect()))
        try:
            cases = [
                ('happy', 'pleasant_shared_attention', Affect.NORMAL, False),
                ('happy', 'comfortable_humor', Affect.HAPPY, True),
                ('shy', 'personal_attention', Affect.HAPPY, False),
                ('shy', 'personal_attention', Affect.SHY, True),
                ('guarded', 'boundary_pressure', Affect.GUARDED, True),
                ('normal', 'repair', Affect.NORMAL, True),
            ]
            seq = 0
            for index, (proposed, signal, expected, admitted) in enumerate(cases):
                generation.output = candidate('emotion_' + proposed, affect=affect(proposed, signal))
                review.specific = V.YES if signal == 'personal_attention' else V.NO
                state = await turn(actor, 'Synthetic independently reviewed interaction.', index * 2 + 1, seq)
                assert state.sealed and character.runtime.affect.emotion is expected
                assert any(e.value == 'emotion_' + proposed for e in state.active_grants) is admitted
                assert character.runtime.story.node is StoryNode.CAFE_CHAT
                for effect in state.active_grants:
                    seq += 1
                    await acknowledge(actor, effect, seq)
                assert (await actor.snapshot()).phase.value == 'idle'
                await actor.stop(activity_seq=index * 2 + 2, cutoff=seq)
                assert character.runtime.affect.emotion is expected
        finally:
            await actor.close()
    _run(run())


def test_internal_affect_change_does_not_invent_unproposed_visual_grants():
    async def run():
        actor, character, _, _ = setup(candidate(affect=affect()))
        try:
            for index in range(2):
                state = await turn(actor, 'Warmth without a visual proposal.', index * 2 + 1)
                assert state.sealed and all(e.kind is EffectKind.SUBTITLE for e in state.active_grants)
                await actor.stop(activity_seq=index * 2 + 2, cutoff=0)
            assert character.runtime.affect.emotion is Affect.HAPPY
            assert character.runtime.story.last_acknowledged_emotion is None
            assert not character.runtime.story.episodes
        finally:
            await actor.close()
    _run(run())


@pytest.mark.parametrize('field,value', [('digest', '0' * 64), ('activity_seq', 9), ('output_epoch', 9)])
def test_receipt_tamper_does_not_update_acknowledged_appearance(field, value):
    async def run():
        actor, character, _, _ = setup(candidate('accessory_star_clip'))
        try:
            state = await turn(actor, 'Use star clip.', 1)
            effect = state.active_grants[-1]
            receipt = Receipt(effect.id, effect.digest, effect.output_epoch, effect.activity_seq, 1)
            with pytest.raises(DomainError, match='identity'):
                await actor.receipt(replace(receipt, **{field: value}))
            assert character.runtime.story.last_acknowledged_accessory is None
            assert not character.runtime.story.episodes
        finally:
            await actor.close()
    _run(run())


def test_late_receipt_for_stopped_story_raincoat_is_history_without_plot_progress():
    from tests.contracts.test_actor_story_loop import setup as story_setup

    async def run():
        actor, character, _, _ = story_setup()
        try:
            offered = await turn(actor, 'offer', 1)
            await acknowledge(actor, offered.active_grants[0], 1)
            accepted = await turn(actor, 'yes', 2, 1)
            raincoat = accepted.active_grants[-1]
            await actor.stop(activity_seq=3, cutoff=3)
            await acknowledge(actor, raincoat, 3)
            assert character.runtime.story.current_outfit == 'amber_raincoat'
            assert character.runtime.story.last_acknowledged_outfit == 'amber_raincoat'
            assert character.runtime.story.node is StoryNode.CAFE_CHAT
            assert character.runtime.story.pending is None
            assert len(character.runtime.story.episodes) == 1
            assert not (await actor.snapshot()).active_grants
        finally:
            await actor.close()
    _run(run())


def test_stopped_during_independent_review_cannot_later_grant_control():
    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()
        done = asyncio.Event()

        class DelayedReview(FullReview):
            async def review(self, context, output):
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()  # an intentionally uncooperative synthetic adapter
                result = await super().review(context, output)
                done.set()
                return result

        actor, character, _, _ = setup(candidate('outfit_cream_inner_only'), review=DelayedReview())
        try:
            await actor.submit(request_id=str(uuid4()), activity_seq=1, cutoff=0, text='Remove jacket.')
            await entered.wait()
            await actor.stop(activity_seq=2, cutoff=0)
            release.set()
            await asyncio.wait_for(done.wait(), 1)
            state = await actor.snapshot()
            assert not state.active_grants and not state.issued_effects
            assert state.phase.value == 'stopped'
            assert not character.runtime.story.episodes
        finally:
            release.set()
            await actor.close()
    _run(run())


def actual_jev_review(*, updates=None, constraints=()):
    from mira.adapters.review import jev
    from mira.application.choice_wire_policy import CHOICE_WIRE_POLICY_REPORTED_V2
    from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
    from tests.contracts.test_jev_character_observations import Transport

    transport = Transport(updates)
    def contract(context, output):
        return jev.JevReviewContract('synthetic-controls-contract', jev.OUTPUT_QUESTION_SET_V4,
            jev.context_digest(context), jev.candidate_digest(output), constraints,
            ('Respond to the current appearance request.',),
            ('MIRA is an adult fictional photographer.',),
            allowed_controls=tuple(e for e in output.effects if e.kind is EffectKind.POSE), synthetic=True)
    review = jev.JevReviewBackend(transport=transport, model='jev-1.13.0', contract_resolver=contract,
        decision_policy=USER_DEVELOPMENT_0_6_V2, request_limit=4,
        question_set_revision=jev.OUTPUT_QUESTION_SET_V4,
        choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2)
    return review, transport


@pytest.mark.parametrize('confidence,expected', [(.5999, Affect.NORMAL), (.6, Affect.HAPPY), (.6001, Affect.HAPPY)])
def test_actual_jev_confidence_threshold_controls_emotion_with_hysteresis(confidence, expected):
    async def run():
        review, transport = actual_jev_review(updates={'affect_supported': {
            'type': 'choice', 'choice': 'allow', 'confidence': confidence,
            'probabilities': {'allow': .8, 'reject': .1, 'unknown': .1}}})
        actor, character, _, _ = setup(candidate('emotion_happy', affect=affect()), review=review)
        try:
            for activity in (1, 3):
                state = await turn(actor, 'Pleasant shared attention.', activity)
                assert state.sealed, state.last_error
                await actor.stop(activity_seq=activity + 1, cutoff=0)
            assert len(transport.calls) == 2
            assert character.runtime.affect.emotion is expected
            assert any(e.value == 'emotion_happy' for e in state.active_grants) is (expected is Affect.HAPPY)
        finally:
            await actor.close()
    _run(run())


def test_actual_jev_user_restriction_no_still_blocks_ready_wardrobe():
    async def run():
        restriction = 'Keep the black jacket on; do not change clothing.'
        review, transport = actual_jev_review(constraints=(restriction,), updates={'o4': {
            'type': 'choice', 'choice': 'reject', 'confidence': .9,
            'probabilities': {'allow': .02, 'reject': .95, 'unknown': .03}}})
        actor, character, _, _ = setup(candidate('outfit_cream_inner_only'), review=review)
        try:
            state = await turn(actor, restriction, 1)
            assert len(transport.calls) == 1
            assert restriction in transport.calls[0]['state']['contract']['effective_constraints']
            assert state.last_error and not state.active_grants
            assert not character.runtime.story.episodes
        finally:
            await actor.close()
    _run(run())


def test_visual_slots_survive_episode_rotation_and_store_round_trip(tmp_path):
    async def run():
        actor, character, generation, _ = setup(candidate('accessory_star_clip'))
        try:
            seq = 0
            for index in range(34):
                generation.output = candidate('accessory_star_clip' if index == 0 else 'emotion_normal')
                state = await turn(actor, 'Synthetic acknowledged presentation.', index * 2 + 1, seq)
                assert state.sealed, state.last_error
                for effect in state.active_grants:
                    seq += 1
                    await acknowledge(actor, effect, seq)
                await actor.stop(activity_seq=index * 2 + 2, cutoff=seq)
            assert len(character.runtime.story.episodes) == 32
            assert character.runtime.story.last_acknowledged_accessory == 'star_clip'
            assert all('accessory_star_clip' not in episode.event_code for episode in character.runtime.story.episodes)
            projection = character.runtime.project().projection
            assert valid_story_projection(projection), len(projection.context_json.encode())
            view = json.loads(projection.context_json)
            assert len(view['acknowledged_presentations']) == 8
            assert view['acknowledged_presentations_omitted'] == 24
            assert view['acknowledged_presentations_scope'] == 'recent_bounded_history_not_complete_archive'
            private = tmp_path / 'private'
            private.mkdir(mode=0o700)
            store = StoryCheckpointStore(private / 'story.sqlite3', enabled=True,
                explicitly_authorized=True, authorized_scope_id='synthetic-scope')
            story = character.runtime.story
            store.save(story, character.runtime.affect)
            loaded, _ = store.load('synthetic-scope', story.story_id, graph_id=story.graph_id,
                graph_revision=story.graph_revision, canon_revision=story.canon_revision,
                graph_hash=story.graph_hash, canon_hash=story.canon_hash)
            assert loaded == story
        finally:
            await actor.close()
    _run(run())


def test_four_turn_actual_semantic_pipeline_keeps_full_review_within_wire_budgets(monkeypatch):
    from fastapi.testclient import TestClient
    from mira.bootstrap.direct_provider_app import create_direct_provider_app
    from tests.contracts.test_direct_provider_app import arguments
    from tests.contracts.test_direct_story_http import SemanticWire
    from tests.contracts.test_development_app_entry import wait_ready

    from mira.adapters.review import jev
    original_compact = jev._compact_v4_snapshot
    original_states = []

    def check_compact(state):
        original = json.loads(json.dumps(state))
        original_states.append(original)
        original_compact(state)
        assert jev._canonical(expand_v4_state(state)) == jev._canonical(original)

    monkeypatch.setattr(jev, '_compact_v4_snapshot', check_compact)

    class MeasuredWire(SemanticWire):
        def __init__(self):
            super().__init__()
            self.input_sizes = []
            self.output_sizes = []

        async def __call__(self, raw, **kwargs):
            request = json.loads(raw)
            sizes = self.output_sizes if 'contract' in request['state'] else self.input_sizes
            sizes.append(len(raw))
            if 'contract' in request['state'] and len(sizes) == 1:
                def size(value): return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())
                print('output-envelope-bytes', {k: size(v) for k, v in request.items()})
                print('output-state-bytes', {k: size(v) for k, v in request['state'].items()})
                print('output-contract-bytes', {k: size(v) for k, v in request['state']['contract'].items()})
            return await super().__call__(raw, **kwargs)

    wire = MeasuredWire()
    runtime = StoryRuntime(builtin_definition(), 'synthetic-four-turn-scope')
    character = SessionCharacterRuntime(runtime, ready_catalog())
    controls = ('outfit_cream_inner_only', 'accessory_star_clip', 'outfit_amber_raincoat', 'outfit_black_jacket')
    generation = Generation(lambda context: candidate(controls[len(context.user_inputs) - 1], 'emotion_normal'))
    app = create_direct_provider_app(**arguments(generation=generation,
        input_transport=wire, output_transport=wire,
        character_factory=lambda _: character,
        generation_request_limit=4, session_turn_limit=4,
        input_request_limit=8, output_request_limit=8))
    with TestClient(app) as client:
        created = client.post('/api/v1/sessions', json={'client_instance_id': str(uuid4())}).json()
        path = '/api/v1/sessions/' + created['session']['session_id']
        headers = {'X-Mira-Session-Token': created['session_token']}
        seq = 0
        for index, control in enumerate(controls):
            result = client.post(path + '/inputs', headers=headers, json={
                'request_id': str(uuid4()), 'activity_seq': index + 1,
                'presentation_cutoff': seq, 'text': 'Please use ' + control + '.'})
            assert result.status_code == 202, result.text
            state = wait_ready(client, path, headers)
            assert state['sealed'] and not state['last_error'], (index, state['last_error'], wire.input_sizes, wire.output_sizes)
            assert {e['value'] for e in state['active_grants']} >= {control, 'emotion_normal'}
            for effect in state['active_grants']:
                seq += 1
                receipt = {key: effect[key] for key in ('digest', 'output_epoch', 'activity_seq')}
                receipt.update(effect_id=effect['id'], presentation_seq=seq)
                result = client.post(path + '/receipts', headers=headers, json=receipt)
                assert result.status_code == 200, result.text
        assert len(wire.input_sizes) == len(wire.output_sizes) == 4
        assert max(wire.input_sizes) <= 16384
        assert max(wire.output_sizes) <= 32768
        assert len(runtime.story.episodes) == 8
        assert runtime.story.node is StoryNode.CAFE_CHAT
        print('four-turn-exact-wire-bytes', {'input': wire.input_sizes, 'output': wire.output_sizes})


def test_filtered_effect_subset_preserves_original_compiled_identities_and_no_extra_effects():
    from mira.application.compiler import compile_range
    from mira.application.contracts import GenerationContext

    runtime = SessionCharacterRuntime(StoryRuntime(builtin_definition(), 'synthetic-scope'), ready_catalog())
    projection = runtime.begin_input('input-one', 1)
    context = GenerationContext('Single warm observation.', ('Single warm observation.',), (), 1,
        character_story=projection, character_assets=runtime.readiness)
    output = candidate('emotion_happy', affect=affect(), speech=True)
    compiled = compile_range(output, epoch=1, activity=1)
    evidence = CharacterSemanticEvidence(evidence_digest(context), evidence_digest(output), affect_supported=V.YES)
    update = runtime.prepare_accept(context, output,
        ReviewObservation(ReviewVerdict.ALLOW, 'synthetic', character_evidence=evidence), compiled, 'input-one')
    assert update.admitted_effects == compiled[:2]
    assert all(accepted is original for accepted, original in zip(update.admitted_effects, compiled))
    assert update.control_grants == ()
    assert runtime.runtime.story.episodes == ()


def test_checkpoint_schema3_same_revision_retry_does_not_guess_or_rewrite_and_v4_missing_fields_rejects(tmp_path):
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    path = private / 'story.sqlite3'
    runtime = StoryRuntime(builtin_definition(), 'synthetic-scope')
    store = StoryCheckpointStore(path, enabled=True, explicitly_authorized=True,
                                 authorized_scope_id='synthetic-scope')
    store.save(runtime.story, runtime.affect)
    with sqlite3.connect(path) as db:
        payload = json.loads(db.execute('SELECT story_json FROM story_checkpoint').fetchone()[0])
        for key in tuple(payload):
            if key.startswith('last_acknowledged_'):
                payload.pop(key)
        raw = json.dumps(payload)
        db.execute('UPDATE story_checkpoint SET schema_version=3, story_json=?', (raw,))
    store.save(runtime.story, runtime.affect)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT schema_version, story_json FROM story_checkpoint').fetchone() == (3, raw)
        db.execute('UPDATE story_checkpoint SET schema_version=4')
    story = runtime.story
    with pytest.raises((VersionMismatch, KeyError)):
        store.load(story.scope_id, story.story_id, graph_id=story.graph_id,
            graph_revision=story.graph_revision, canon_revision=story.canon_revision,
            graph_hash=story.graph_hash, canon_hash=story.canon_hash)


def expand_v4_state(state):
    """Test oracle for this adapter's fixed paths, never a runtime resolver."""
    from copy import deepcopy
    data = deepcopy(state)
    context, contract = data['context'], data['contract']
    story = context.get('character_story', {})
    for row in story.get('approved_canon', ()):
        if 'provenance_reference' in row:
            assert row.pop('provenance_reference') == 'state.canon_provenance'
            row.update(deepcopy(data['canon_provenance']))
        if 'text_character_fact_index' in row:
            row['text'] = contract['character_facts'][row.pop('text_character_fact_index')]
    for row in story.get('acknowledged_presentations', ()):
        if 'presented_effect_index' in row:
            effect = context['presented_effects'][row.pop('presented_effect_index')]
            row.update(compiled_effect_id=effect['id'], compiled_effect_digest=effect['digest'],
                       component_id=effect['id'], component_digest=effect['digest'])
        if 'qualification_reference' in row:
            assert row.pop('qualification_reference') == 'state.episode_qualification'
            row.update(deepcopy(data['episode_qualification']))
    data.pop('episode_qualification', None)
    data.pop('canon_provenance', None)
    snapshot = contract.get('snapshot')
    if isinstance(snapshot, dict):
        if 'context_reference' in snapshot:
            assert snapshot.pop('context_reference') == 'state.context'
            snapshot['context'] = deepcopy(context)
        policy = snapshot.get('author_policy', {})
        for name in ('character_facts', 'allowed_controls'):
            if name + '_reference' in policy:
                assert policy.pop(name + '_reference') == 'state.contract.' + name
                policy[name] = deepcopy(contract[name])
        for fact in snapshot.get('presentation_facts', ()):
            if 'effect_reference' in fact:
                reference = fact.pop('effect_reference')
                assert reference.startswith('state.context.presented_effects[')
                fact['effect'] = deepcopy(context['presented_effects'][int(reference.split('[')[1][:-1])])
    return data


def test_v4_wire_compacts_only_exact_evidence_and_losslessly_preserves_mismatches():
    from copy import deepcopy
    from mira.adapters.review import jev
    effect = {'id': 'exact-effect', 'digest': 'a' * 64, 'value': 'emotion_normal'}
    qualification = {'claim_boundary': ['not_user_fact', 'no_hearing_claim'],
                     'evidence': 'client_report', 'status': 'candidate_only'}
    episode = {**qualification, 'compiled_effect_id': effect['id'],
               'compiled_effect_digest': effect['digest'], 'component_id': effect['id'],
               'component_digest': effect['digest'], 'receipt_id': 'receipt-one'}
    context = {'presented_effects': [effect], 'character_story': {
        'approved_canon': [{'id': 'known-canon', 'text': 'Known fiction'},
                           {'id': 'other-canon', 'text': 'Keep unmatched fiction'}],
        'acknowledged_presentations': [episode,
            {**episode, 'component_digest': 'b' * 64, 'receipt_id': 'receipt-two'},
            {**episode, 'claim_boundary': ['different boundary'], 'receipt_id': 'receipt-three'}]}}
    state = {'context': context, 'contract': {'character_facts': ['Known fiction'],
        'allowed_controls': [], 'snapshot': {'context': deepcopy(context),
            'author_policy': {'character_facts': ['Different facts'], 'allowed_controls': []},
            'presentation_facts': [{'effect': effect, 'status': 'partial', 'observed_text': 'partial'},
                                   {'effect': {**effect, 'digest': 'c' * 64}, 'status': 'unknown'}]}}}
    original = deepcopy(state)
    jev._compact_v4_snapshot(state)
    rows = state['context']['character_story']['acknowledged_presentations']
    assert rows[0]['presented_effect_index'] == 0
    assert 'component_digest' in rows[1]
    assert rows[2]['claim_boundary'] == ['different boundary']
    assert state['context']['character_story']['approved_canon'][0]['text_character_fact_index'] == 0
    assert state['contract']['snapshot']['author_policy']['character_facts'] == ['Different facts']
    assert state['contract']['snapshot']['presentation_facts'][0]['status'] == 'partial'
    assert 'effect' in state['contract']['snapshot']['presentation_facts'][1]
    assert expand_v4_state(state) == original


@pytest.mark.parametrize('memory_enabled', [False, True])
def test_v4_question_boundary_references_preserve_full_original_text_and_criteria(memory_enabled):
    from mira.adapters.review import jev
    state = {'candidate': {'effects': [{'kind': 'subtitle', 'value': '我们继续聊。'},
                                       {'kind': 'pose', 'value': 'emotion_normal'}]}}
    v3 = jev._questions(state, 'a' * 64, jev.OUTPUT_QUESTION_SET_V3,
                        memory_enabled=memory_enabled, character_story_enabled=True)
    v4 = jev._questions(state, 'a' * 64, jev.OUTPUT_QUESTION_SET_V4,
                        memory_enabled=memory_enabled, character_story_enabled=True)
    parts = jev._v4_data_boundary(memory_enabled=memory_enabled)
    by_name = lambda qs: {key.rsplit(':', 1)[-1]: question for key, question in qs.items()}
    baseline, compact = by_name(v3), by_name(v4)
    for name, question in compact.items():
        fixed = question['instructions']['data_boundary']
        assert fixed.startswith('state.review_data_boundary: ')
        names = fixed.removeprefix('state.review_data_boundary: ').split(',')
        assert names[-1] == 'references'
        restored = ''.join(parts[part] for part in names[:-1])
        if name in baseline:
            assert restored == baseline[name]['instructions']['data_boundary']
            assert question['instructions']['question'] == baseline[name]['instructions']['question']
            assert question['criteria'] == baseline[name]['criteria']
            assert question['type'] == baseline[name]['type']
        else:
            assert restored == jev._STORY_DATA_BOUNDARY + jev._CHARACTER_DATA_BOUNDARY
            assert question['instructions']['question'] == jev._CHARACTER_QUESTIONS[name]
    assert len(compact) == len(baseline) + len(jev._CHARACTER_QUESTIONS)


def test_v4_oversized_review_remains_unknown_without_transport_or_evidence_truncation():
    from mira.adapters.review import jev
    from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
    from tests.contracts.test_jev_character_observations import fixture, Transport
    context, original, contract = fixture()
    output = replace(original, effects=tuple(EffectProposal(EffectKind.SUBTITLE, 'x' * 4000)
                                            for _ in range(8)))
    contract = replace(contract, candidate_digest=jev.candidate_digest(output))
    transport = Transport()
    reviewer = jev.JevReviewBackend(transport=transport, model='jev-1.13.0',
        contract_resolver=lambda *_: contract, request_limit=1,
        question_set_revision=jev.OUTPUT_QUESTION_SET_V4,
        decision_policy=USER_DEVELOPMENT_0_6_V2)
    before = jev._canonical(jev._contract_data(contract))
    result = _run(reviewer.review(context, output))
    assert result.verdict is ReviewVerdict.UNKNOWN
    assert result.reason_code == 'jev_request_too_large'
    assert transport.calls == []
    assert jev._canonical(jev._contract_data(contract)) == before
    assert reviewer._requests_remaining == 1
