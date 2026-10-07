"""Offline error-to-log correlation through real Actor, HTTP DTO and media streams."""
import asyncio
import hashlib
import json
import time
from uuid import uuid4

import pytest
from tests.integration.test_voice_http import Tts
from fastapi.testclient import TestClient

from mira.adapters.diagnostics.privacy import encode_event
from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.contracts import CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict
from mira.application.diagnostic_events import request_correlation
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.bootstrap.providers import Providers
from mira.config.settings import Settings
from mira.domain.models import AudioProgress, AudioStatus, EffectKind, SessionState
from mira.entrypoints.http.app import create_app
from mira.entrypoints.http.mappers import session_view

PRIVATE = "SYNTHETIC_PRIVATE_BODY authorization=not-a-real-secret"


def hashed(value):
    return "h_" + hashlib.sha256(value.encode()).hexdigest()[:32]


class Events:
    def __init__(self):
        self.records = []

    def emit(self, event):
        self.records.append(encode_event(event, 1))
        return True

    def close(self):
        pass


class Generate:
    async def generate(self, context):
        yield CandidateRange((EffectProposal(EffectKind.SPEECH, "Synthetic approved speech"),), "test")


class Allow:
    async def review(self, context, candidate):
        return ReviewObservation(ReviewVerdict.ALLOW, "test")


class FailGeneration:
    async def generate(self, context):
        raise TimeoutError(PRIVATE)
        yield


class FailReview:
    async def review(self, context, candidate):
        raise RuntimeError(PRIVATE)


class RejectReview:
    async def review(self, context, candidate):
        return ReviewObservation(ReviewVerdict.REJECT, PRIVATE)


class FailTts:
    async def synthesize(self, text, stream_id):
        raise TimeoutError(PRIVATE)
        yield


class FailStt:
    async def transcribe(self, packets):
        raise TimeoutError(PRIVATE)
        yield


def create(client):
    response = client.post('/api/v1/sessions', json={'client_instance_id': str(uuid4())}).json()
    return '/api/v1/sessions/' + response['session']['session_id'], {'X-Mira-Session-Token': response['session_token']}


def state_when(client, path, headers, predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        state = client.get(path, headers=headers).json()
        if predicate(state):
            return state
        time.sleep(.002)
    raise AssertionError('Synthetic operation did not reach its barrier')


@pytest.mark.parametrize(('generation', 'review', 'stage'), [
    (FailGeneration(), Allow(), 'generation'), (Generate(), FailReview(), 'output_review'),
    (Generate(), RejectReview(), 'output_review'),
])
def test_async_http_error_locator_matches_origin_log_not_poll_or_active_request(generation, review, stage):
    sink = Events()
    app = create_app(Settings(), providers=Providers(generation, review), diagnostics=sink)
    with TestClient(app) as client:
        path, headers = create(client)
        input_id = str(uuid4())
        accepted = client.post(path + '/inputs', headers=headers, json={'request_id': input_id,
            'activity_seq': 1, 'presentation_cutoff': 0, 'text': 'Synthetic input'})
        state = state_when(client, path, headers, lambda s: s['phase'] == 'error')
        locator = state.get('last_error_diagnostic_id')
        assert locator == hashed(accepted.headers['x-request-id'])
        assert locator != hashed(input_id)
        assert state['request_id'] is None and state['active_grants'] == []
        failed = [r for r in sink.records if r['stage'] == stage and r['outcome'] == 'failed']
        assert any(r['context']['request_id'] == locator for r in failed)
        assert PRIVATE not in json.dumps(state) + json.dumps(sink.records)
        stopped = client.post(path + '/stop', headers=headers, json={'activity_seq': 2, 'presentation_cutoff': 0}).json()
        assert stopped['last_error'] is None and stopped['last_error_diagnostic_id'] is None


def test_tts_stream_and_snapshot_keep_same_logged_locator():
    sink = Events()
    app = create_app(Settings(), providers=Providers(Generate(), Allow()), speech_synthesis=FailTts(), diagnostics=sink)
    with TestClient(app) as client:
        path, headers = create(client)
        client.post(path + '/inputs', headers=headers, json={'request_id': str(uuid4()), 'activity_seq': 1,
            'presentation_cutoff': 0, 'text': 'Synthetic speech'})
        ready = state_when(client, path, headers, lambda s: s['sealed'])
        effect = ready['active_grants'][0]
        response = client.post(path + '/speech/' + effect['id'] + '/stream', headers=headers,
            json={k: effect[k] for k in ('digest', 'output_epoch', 'activity_seq')})
        error = json.loads(response.text.strip())
        assert error['type'] == 'error'
        locator = error.get('diagnostic_id')
        assert locator == hashed(response.headers['x-request-id'])
        state = client.get(path, headers=headers).json()
        assert state['last_error_diagnostic_id'] == locator and state['request_id'] is None
        assert any(r['stage'] == 'tts' and r['outcome'] == 'failed' and r['context']['request_id'] == locator for r in sink.records)
        assert PRIVATE not in response.text + json.dumps(state) + json.dumps(sink.records)


def test_microphone_error_retains_safe_locator_from_actual_logged_context():
    sink = Events()
    app = create_app(Settings(), speech_recognition=FailStt(), diagnostics=sink)
    with TestClient(app) as client:
        path, headers = create(client)
        with client.websocket_connect(path + '/microphone', headers={'Origin': 'http://localhost:8000'}) as ws:
            ws.send_json({'type': 'start', 'session_token': headers['X-Mira-Session-Token'],
                'stream_id': str(uuid4()), 'activity_seq': 0, 'input_epoch': 0, 'sample_rate_hz': 16000})
            assert ws.receive_json()['type'] == 'ready'
            error = ws.receive_json()
            assert error['type'] == 'error' and error['code'] == 'timeout'
            locator = error.get('diagnostic_id')
            assert isinstance(locator, str) and locator.startswith('h_')
        assert any(r['stage'] == 'microphone' and r['outcome'] == 'failed' and r['context']['request_id'] == locator for r in sink.records)
        assert PRIVATE not in json.dumps(error) + json.dumps(sink.records)


def actor(generation, sink=None):
    return SessionActor(SessionState(str(uuid4()), str(uuid4())), generation, Allow(),
        MemoryEventJournal(100), RuntimeLimits(2, 64, 128), diagnostics=sink)


async def submit(value, activity, correlation):
    token = request_correlation.set(correlation)
    try:
        await value.submit(request_id=str(uuid4()), activity_seq=activity, cutoff=0, text='Synthetic')
        return tuple(value._tasks)
    finally:
        request_correlation.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize('origin', [None, 'constructor', '__proto__', 'private\nheader', 'h_' + 'a' * 32, str(uuid4()) + '\n'])
async def test_missing_or_malformed_origins_never_create_fabricated_locator(origin):
    value = actor(FailGeneration())
    try:
        tasks = await submit(value, 1, origin)
        await asyncio.gather(*tasks)
        view = session_view(await value.snapshot()).model_dump()
        assert view['last_error'] == 'generation_timeout'
        assert 'last_error_diagnostic_id' in view and view['last_error_diagnostic_id'] is None
    finally:
        await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['stop', 'new_input'])
async def test_late_failure_cannot_replace_cleared_or_new_turn_locator(action):
    entered, release = asyncio.Event(), asyncio.Event()
    class Resistant:
        async def generate(self, context):
            if context.output_epoch == 1:
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
            raise TimeoutError(PRIVATE)
            yield
    value = actor(Resistant(), Events())
    old_id, new_id = str(uuid4()), str(uuid4())
    try:
        old = await submit(value, 1, old_id)
        await entered.wait()
        if action == 'stop':
            await value.stop(activity_seq=2, cutoff=0)
        else:
            await submit(value, 2, new_id)
            await asyncio.gather(*(task for task in value._tasks if task not in old))
        release.set()
        # A superseded generation is cancelled even if its provider catches the
        # first cancellation and later throws another exception. It cannot publish
        # that late exception as the new turn's failure or locator.
        outcomes = await asyncio.gather(*old, return_exceptions=True)
        assert all(result is None or isinstance(result, asyncio.CancelledError) for result in outcomes)
        state = session_view(await value.snapshot()).model_dump()
        assert state['last_error_diagnostic_id'] == (None if action == 'stop' else hashed(new_id))
        assert state['request_id'] is None
    finally:
        release.set()
        await value.close()


@pytest.mark.asyncio
async def test_playback_failure_snapshot_matches_its_logged_receipt_context():
    sink = Events()
    value = actor(Generate(), sink)
    value._speech_synthesis = Tts()  # Explicit synthetic voice capability for this audio-fact test.
    try:
        await asyncio.gather(*await submit(value, 1, str(uuid4())))
        effect = (await value.snapshot()).active_grants[0]
        receipt_id = str(uuid4())
        token = request_correlation.set(receipt_id)
        try:
            state = await value.audio_progress(AudioProgress(effect.id, effect.digest, 1, 1, 1, 24000, 0, AudioStatus.FAILED))
        finally:
            request_correlation.reset(token)
        locator = session_view(state).model_dump()['last_error_diagnostic_id']
        assert locator == hashed(receipt_id) and state.request_id is None
        assert any(r['stage'] == 'playback' and r['outcome'] == 'failed' and r['context']['request_id'] == locator for r in sink.records)
        await value.submit(request_id=str(uuid4()), activity_seq=2, cutoff=1, text='Synthetic new input')
        assert session_view(await value.snapshot()).model_dump()['last_error_diagnostic_id'] is None
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_semantic_input_review_exception_keeps_actual_origin_locator():
    from mira.application.decision_contracts import mira26_author_policy
    from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
    class Input:
        async def observe(self, snapshot):
            raise TimeoutError(PRIVATE)
    class Output:
        async def review_contract(self, *args):
            raise AssertionError('Failed input review must never reach output review')
    sink, origin = Events(), str(uuid4())
    value = SessionActor(SessionState(str(uuid4()), str(uuid4())), Generate(), Allow(),
        MemoryEventJournal(100), RuntimeLimits(2, 64, 128), diagnostics=sink,
        semantic_review=SemanticReviewCoordinator(Input(), Output()),
        decision_owner=DecisionSnapshotOwner(mira26_author_policy()))
    try:
        await asyncio.gather(*await submit(value, 1, origin))
        view = session_view(await value.snapshot()).model_dump()
        assert view['last_error_diagnostic_id'] == hashed(origin) and view['request_id'] is None
        assert any(r['stage'] == 'input_review' and r['outcome'] == 'failed'
                   and r['context']['request_id'] == view['last_error_diagnostic_id'] for r in sink.records)
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_stale_media_failure_never_overwrites_new_generation_locator():
    class Generation:
        async def generate(self, context):
            if context.output_epoch == 1:
                async for candidate in Generate().generate(context):
                    yield candidate
            else:
                raise TimeoutError(PRIVATE)
    sink = Events()
    value = SessionActor(SessionState(str(uuid4()), str(uuid4())), Generation(), Allow(),
        MemoryEventJournal(100), RuntimeLimits(2, 64, 128), diagnostics=sink,
        speech_synthesis=FailTts())
    operation = None
    try:
        await asyncio.gather(*await submit(value, 1, str(uuid4())))
        effect = (await value.snapshot()).active_grants[0]
        origin = request_correlation.set(str(uuid4()))
        try:
            operation = await value.open_speech(effect_id=effect.id, digest=effect.digest,
                output_epoch=1, activity_seq=1)
        finally:
            request_correlation.reset(origin)
        newer = str(uuid4())
        await asyncio.gather(*await submit(value, 2, newer))
        before = await value.snapshot()
        assert session_view(before).last_error_diagnostic_id == hashed(newer)
        await value.media_failed(operation, 'unavailable')
        assert await value.snapshot() is before
    finally:
        if operation is not None:
            await value.close_media(operation)
        await value.close()


@pytest.mark.parametrize('bad', ['constructor', '__proto__', PRIVATE, 'h_' + 'a' * 32 + '\n', 123])
def test_public_mapper_discards_malformed_error_metadata(bad):
    state = SessionState('s', 'c', last_error=PRIVATE, last_error_diagnostic_id=bad)
    view = session_view(state).model_dump()
    assert view['last_error'] == 'unknown'
    assert view['last_error_diagnostic_id'] is None
    assert PRIVATE not in json.dumps(view)
