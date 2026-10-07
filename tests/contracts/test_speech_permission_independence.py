"""Speech permission through real JEV parsing and ASGI, using synthetic transports."""
import asyncio
import json
import threading
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from mira.adapters.review.jev import JevHttpResponse
from mira.adapters.review.jev_input import JevInputDecisionBackend
from mira.application.choice_wire_policy import (
    CHOICE_WIRE_POLICY_LEGACY_STRICT, CHOICE_WIRE_POLICY_REPORTED_V2,
)
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext
from mira.application.decision_contracts import (
    INPUT_QUESTION_SET, INPUT_QUESTION_SET_V2, ChoiceProbability, DecisionSnapshot,
    DirectiveFact, InputDecisionStatus, PredicateObservation, ReferentObservation,
    ReliableUserInput, ResponseContractProducer, SemanticValue, mira26_author_policy,
)
from mira.application.decision_policy import (
    USER_DEVELOPMENT_0_6_V1, USER_DEVELOPMENT_0_6_V2,
)
from mira.application.decision_runtime import SemanticReviewCoordinator
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.domain.models import EffectKind
from tests.contracts.test_conversation_first import (
    Generation, Wire, session, settled, submit, voice_options,
)
from tests.contracts.test_direct_provider_app import arguments
from tests.integration.test_voice_http import speech_request


def permission_snapshot():
    text = '我们继续聊聊。'
    context = GenerationContext(text, (text,), (), 1)
    return DecisionSnapshot('snapshot-1', 1, 1, 1, 1, 'generation-1', context,
                            (ReliableUserInput('input-1', text),), mira26_author_policy())


def speech_candidate():
    return CandidateRange((EffectProposal(EffectKind.SPEECH, '我们可以慢慢聊。'),), 'speech-1')


async def permission_observation(snapshot=None, *, wire=None, policy=USER_DEVELOPMENT_0_6_V2,
                                 question_set=INPUT_QUESTION_SET_V2,
                                 wire_policy=CHOICE_WIRE_POLICY_REPORTED_V2, calibration=None):
    snapshot = snapshot or permission_snapshot()
    backend = JevInputDecisionBackend(transport=wire or InputWire('capture_restriction'),
        model='jev-1.13.0', decision_policy=policy, calibration_ref=calibration,
        question_set_revision=question_set, choice_wire_policy_version=wire_policy,
        request_limit=1)
    coordinator = SemanticReviewCoordinator(backend, object(), conversation_first=True)
    return snapshot, coordinator, await coordinator.observe(snapshot)


class InputWire(Wire):
    def __init__(self, uncertainty, **kwargs):
        super().__init__(**kwargs)
        self.uncertainty = uncertainty

    async def __call__(self, payload, **kwargs):
        response = await super().__call__(payload, **kwargs)
        request = json.loads(payload)
        if 'contract' in request['state']:
            return response
        document = json.loads(response.body)
        for key in document['answers']:
            if key.endswith(':' + self.uncertainty):
                document['answers'][key] = {'type': 'noul', 'noul': .5}
            if self.uncertainty == 'required_absent_referent':
                if key.endswith(':referent_required'):
                    document['answers'][key] = {'type': 'noul', 'noul': 1.0}
                if key.endswith(':referent'):
                    document['answers'][key] = {
                        'type': 'choice', 'choice': 'ambiguous', 'confidence': 1.0,
                        'probabilities': {option:float(option=='ambiguous')
                            for option in request['questions'][key]['criteria']},
                    }
        return JevHttpResponse(200, json.dumps(document).encode())


@pytest.mark.parametrize('uncertainty', [
    'capture_restriction', 'display_request', 'referent_required', 'required_absent_referent',
])
def test_unrelated_input_uncertainty_allows_only_speech_and_text(uncertainty):
    wire = InputWire(uncertainty)
    generation = Generation([
        ('subtitle', '我们可以慢慢聊。'), ('speech', '我们可以慢慢聊。'),
        ('pose', 'look_at_rain'),
    ])
    app = create_direct_provider_app(**arguments(
        generation=generation, input_transport=wire, output_transport=wire, **voice_options()))
    with TestClient(app) as client:
        path, headers = session(client)
        submit(client, path, headers)
        state = settled(client, path, headers)
        assert state['sealed'] and state['last_error'] is None
        assert [effect['kind'] for effect in state['active_grants']] == ['subtitle', 'speech']
        assert len(wire.calls) == 1  # Uncertain optional actions still have no contract.
        text, speech = state['active_grants']
        assert text['cue_speech_id'] is None
        assert speech_request(client, path, headers, speech).status_code == 200


@pytest.mark.parametrize('policy', [USER_DEVELOPMENT_0_6_V1, USER_DEVELOPMENT_0_6_V2])
@pytest.mark.parametrize('question_set', [INPUT_QUESTION_SET, INPUT_QUESTION_SET_V2])
@pytest.mark.parametrize('wire_policy', [CHOICE_WIRE_POLICY_LEGACY_STRICT, CHOICE_WIRE_POLICY_REPORTED_V2])
@pytest.mark.asyncio
async def test_speech_consumes_original_evidence_without_creating_event_authority(policy, question_set, wire_policy):
    snapshot, coordinator, observation = await permission_observation(
        policy=policy, question_set=question_set, wire_policy=wire_policy)
    original = repr(observation)
    assert observation.status is InputDecisionStatus.UNKNOWN
    assert next(item for item in observation.predicates
                if item.predicate == 'capture_restriction').probability == .5
    assert coordinator.speech_allowed(snapshot, speech_candidate(), observation)
    assert repr(observation) == original
    event = CandidateRange((EffectProposal(EffectKind.POSE, 'look_at_rain'),), 'event-1')
    assert ResponseContractProducer().produce(snapshot.context, event, snapshot=snapshot,
                                              observation=observation) is None
    assert not coordinator.speech_allowed(snapshot, event, observation)


@pytest.mark.parametrize('probability,allowed', [(0.0, True), (.4, True), (.40001, False),
                                              (.5, False), (.6, False), (1.0, False)])
@pytest.mark.asyncio
async def test_exact_development_noul_speech_boundary_is_unchanged(probability, allowed):
    snapshot, coordinator, observation = await permission_observation(
        wire=InputWire('capture_restriction', speech=probability))
    speech = next(item for item in observation.predicates if item.predicate == 'speech_restriction')
    assert speech.probability == probability
    assert coordinator.speech_allowed(snapshot, speech_candidate(), observation) is allowed


@pytest.mark.parametrize('probability,allowed', [(.01, True), (.01001, False), (.4, False), (.99, False)])
@pytest.mark.asyncio
async def test_calibrated_speech_boundary_is_unchanged(probability, allowed):
    snapshot, coordinator, observation = await permission_observation(
        wire=InputWire('capture_restriction', speech=probability), policy=None,
        calibration='synthetic-calibration')
    assert coordinator.speech_allowed(snapshot, speech_candidate(), observation) is allowed


@pytest.mark.parametrize('change', [
    {'status': InputDecisionStatus.INVALID}, {'status': InputDecisionStatus.STALE},
    {'status': InputDecisionStatus.UNAVAILABLE}, {'status': 'unknown'},
    {'status': InputDecisionStatus.OBSERVED}, {'reason_code': 'jev_input_response_invalid'},
    {'reason_code': 'jev_input_not_calibrated'}, {'snapshot_id': 'another'},
    {'snapshot_digest': '0' * 64}, {'request_digest': None}, {'request_digest': '0' * 64},
    {'decision_policy_ref': 'user-development-0.6-v2'}, {'decision_policy_ref': None},
    {'decision_policy_ref': 'unrecognized'}, {'calibration_ref': 'mixed-provenance'},
    {'question_set_revision': 'unsupported'}, {'choice_wire_policy_version': 'unsupported'},
    {'predicates': ()}, {'predicates': []}, {'referent': None},
    {'referent': ReferentObservation('unknown', None,
         (ChoiceProbability('none', 1.0), ChoiceProbability('ambiguous', 0.0)), 1.0)},
    {'referent': ReferentObservation('none', None,
         (ChoiceProbability('none', .5), ChoiceProbability('ambiguous', .5)), .5)},
    {'referent': ReferentObservation('resolved', 'invented',
         (ChoiceProbability('none', 0.0), ChoiceProbability('invented', 1.0)), 1.0)},
    {'referent': ReferentObservation('none', None,
         (ChoiceProbability('none', 1.0), ChoiceProbability('none', 0.0)), 1.0)},
    {'unresolved_items': ()}, {'unresolved_items': ('wrong-source',)},
    {'model': None}, {'model': 'wrong-model'}, {'input_tokens': True}, {'output_tokens': 64_001},
])
@pytest.mark.asyncio
async def test_invalid_permission_evidence_never_allows_speech(change):
    snapshot, coordinator, observation = await permission_observation()
    assert not coordinator.speech_allowed(snapshot, speech_candidate(), replace(observation, **change))
    assert not coordinator.speech_allowed(snapshot, speech_candidate(), None)


@pytest.mark.parametrize('value,probability', [(SemanticValue.NO, .5), (SemanticValue.UNKNOWN, 0.0),
                                           (SemanticValue.NO, True), (SemanticValue.NO, float('nan')),
                                           (SemanticValue.NO, -1), (SemanticValue.NO, 10 ** 500)])
@pytest.mark.asyncio
async def test_malformed_speech_scores_are_closed(value, probability):
    snapshot, coordinator, observation = await permission_observation()
    predicates = tuple(PredicateObservation(item.predicate, value, probability)
                       if item.predicate == 'speech_restriction' else item
                       for item in observation.predicates)
    assert not coordinator.speech_allowed(snapshot, speech_candidate(), replace(observation, predicates=predicates))


@pytest.mark.parametrize('field', ['author_constraints', 'effective_constraints', 'response_obligations'])
@pytest.mark.parametrize('interpretation', ['authoritative', 'observed', 'unknown'])
@pytest.mark.asyncio
async def test_current_no_cannot_erase_retained_raw_directive(field, interpretation):
    snapshot = permission_snapshot()
    directive = DirectiveFact('persistent-boundary', '整个会话都不要出声。', 'input-before',
                               'session', interpretation)
    snapshot = (replace(snapshot, author_policy=replace(snapshot.author_policy, constraints=(directive,)))
                if field == 'author_constraints' else replace(snapshot, **{field: (directive,)}))
    snapshot, coordinator, observation = await permission_observation(snapshot, wire=InputWire('none'))
    assert observation.status is InputDecisionStatus.OBSERVED
    assert not coordinator.speech_allowed(snapshot, speech_candidate(), observation)


@pytest.mark.asyncio
async def test_local_stop_changed_snapshot_and_invalid_candidate_remain_closed():
    snapshot, coordinator, observation = await permission_observation()
    candidate = speech_candidate()
    for changed in (None, replace(snapshot, local_stop=True), replace(snapshot, input_epoch=2)):
        assert not coordinator.speech_allowed(changed, candidate, observation)
    for changed in (None, replace(candidate, effects=()), replace(candidate, fixture_id=''),
                    replace(candidate, story_proposal_json='{}'), replace(candidate, affect_proposal_json='{}'),
                    replace(candidate, effects=(*candidate.effects, EffectProposal(EffectKind.MEDIA, 'photo')))):
        assert not coordinator.speech_allowed(snapshot, changed, observation)


def test_absent_voice_capability_does_not_become_a_speech_grant():
    wire = InputWire('capture_restriction')
    generation = Generation([('subtitle', '文字仍然可用。'), ('speech', '文字仍然可用。')])
    app = create_direct_provider_app(**arguments(
        generation=generation, input_transport=wire, output_transport=wire))
    with TestClient(app) as client:
        path, headers = session(client)
        submit(client, path, headers)
        state = settled(client, path, headers)
        assert [effect['kind'] for effect in state['active_grants']] == ['subtitle']
        assert wire.calls == []


@pytest.mark.parametrize('interrupt', ['stop', 'new_input', 'close'])
def test_late_input_permission_cannot_revive_cancelled_speech(interrupt):
    class DelayedInput(InputWire):
        def __init__(self):
            super().__init__('capture_restriction')
            self.entered = threading.Event()
            self.release = threading.Event()

        async def __call__(self, payload, **kwargs):
            first = not self.entered.is_set()
            if first:
                self.entered.set()
                while not self.release.is_set():
                    try:
                        await asyncio.sleep(.002)
                    except asyncio.CancelledError:
                        continue
            return await super().__call__(payload, **kwargs)

    wire = DelayedInput()
    generation = Generation([('subtitle', '文字先呈现。'), ('speech', '文字先呈现。'), ('pose', 'look_at_rain')])
    app = create_direct_provider_app(**arguments(
        generation=generation, input_transport=wire, output_transport=wire,
        generation_request_limit=2, session_turn_limit=2, **voice_options()))
    with TestClient(app) as client:
        path, headers = session(client)
        submit(client, path, headers)
        try:
            assert wire.entered.wait(1)
            before = client.get(path, headers=headers).json()
            old_epoch = before['output_epoch']
            assert [effect['kind'] for effect in before['active_grants']] == ['subtitle', 'speech']
            if interrupt == 'stop':
                response = client.post(path + '/stop', headers=headers,
                    json={'activity_seq': 2, 'presentation_cutoff': 0})
                assert response.status_code == 200
            elif interrupt == 'new_input':
                submit(client, path, headers, activity=2, text='新的话题。')
            else:
                assert client.delete(path, headers=headers).status_code in (200, 204)
        finally:
            wire.release.set()
        if interrupt == 'close':
            assert client.get(path, headers=headers).status_code == 404
        elif interrupt == 'stop':
            state = client.get(path, headers=headers).json()
            assert state['phase'] == 'stopped' and not state['active_grants']
        else:
            state = settled(client, path, headers)
            assert [effect['kind'] for effect in state['active_grants']] == ['subtitle', 'speech']
            assert all(effect['output_epoch'] > old_epoch for effect in state['active_grants'])
