"""Synthetic continuous recognition diagnostics, not provider/device evidence."""
import asyncio
from uuid import uuid4

import pytest

from mira.adapters.speech.errors import SpeechProviderError
from mira.application.continuous_listening import ContinuousListeningRegistry
from mira.application.diagnostic_events import (
    CancellationReason, DiagnosticCode, DiagnosticOutcome, DiagnosticStage,
    correlation_hash, request_correlation,
)
from mira.application.ports.continuous_speech import ContinuousTranscriptResult
from tests.contracts.test_diagnostics_runtime import CollectDiagnostics


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['unauthenticated', 'permission_denied', 'quota_exhausted', 'timeout'])
async def test_safe_speech_failure_keeps_code_instead_of_generic_unavailable(code):
    class Failed:
        async def transcribe_events(self, packets):
            raise SpeechProviderError(code)
            yield
    registry = ContinuousListeningRegistry()
    lease = await registry.start(str(uuid4()), str(uuid4()))
    await lease.recognize(Failed(), is_current=registry.is_current,
                          register_utterance=registry.register_utterance)
    assert lease.reason == code
    stopped = await lease.events.get()
    assert stopped.type == 'stopped' and stopped.reason == code
    await registry.aclose()


@pytest.mark.asyncio
async def test_continuous_timing_and_error_locator_are_correlated_without_content():
    class Failed:
        async def transcribe_events(self, packets):
            await anext(packets)
            yield ContinuousTranscriptResult('synthetic-private-dialogue', False, 100)
            yield ContinuousTranscriptResult('synthetic-private-dialogue', True, 200)
            raise SpeechProviderError('timeout')
    sink = CollectDiagnostics()
    request_id, session_id = str(uuid4()), str(uuid4())
    token = request_correlation.set(request_id)
    try:
        registry = ContinuousListeningRegistry(diagnostics=sink)
        lease = await registry.start(session_id, str(uuid4()))
        lease.audio.push(lease_id=lease.lease_id, sequence=1, first_sample=0, pcm=b"\0\0" * 200)
        await lease.recognize(Failed(), is_current=registry.is_current,
                              register_utterance=registry.register_utterance)
    finally:
        request_correlation.reset(token)
    assert lease.diagnostic_id == correlation_hash(request_id)
    stopped = [item for item in list(lease.events._queue) if item.type == 'stopped']
    assert stopped and stopped[-1].diagnostic_id == lease.diagnostic_id
    for stage in (DiagnosticStage.STT_FIRST_REVISION, DiagnosticStage.STT_FIRST_FINAL_REVISION,
                  DiagnosticStage.STT_STREAM_END):
        events = [event for event in sink.events if event.stage == stage]
        assert len(events) == 1 and events[0].duration_ms >= 0
    failed = [event for event in sink.events if event.stage == DiagnosticStage.STT
              and event.outcome == DiagnosticOutcome.FAILED]
    assert len(failed) == 1 and failed[0].code == DiagnosticCode.TIMEOUT
    assert all(event.context.session_id == session_id for event in sink.events)
    assert all(event.context.request_id == request_id for event in sink.events)
    assert 'synthetic-private-dialogue' not in repr(sink.events)
    await registry.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(('reason', 'expected'), [('user_stop', CancellationReason.USER_STOP),
                                                  ('disconnect', CancellationReason.DISCONNECT)])
async def test_continuous_cancel_cause_is_distinct_and_end_milestone_is_once(reason, expected):
    entered, closed = asyncio.Event(), asyncio.Event()
    class Waiting:
        async def transcribe_events(self, packets):
            try:
                entered.set()
                await asyncio.Event().wait()
                yield
            finally:
                closed.set()
    sink = CollectDiagnostics()
    registry = ContinuousListeningRegistry(diagnostics=sink)
    lease = await registry.start(str(uuid4()), str(uuid4()))
    task = asyncio.create_task(lease.recognize(Waiting(), is_current=registry.is_current,
                                               register_utterance=registry.register_utterance))
    lease._recognition_task = task
    await entered.wait()
    await registry.stop_lease(lease, reason)
    await asyncio.gather(task, return_exceptions=True)
    assert closed.is_set()
    cancelled = [event for event in sink.events if event.stage == DiagnosticStage.STT
                 and event.outcome == DiagnosticOutcome.CANCELLED]
    assert len(cancelled) == 1 and cancelled[0].cancellation_reason == expected
    assert len([event for event in sink.events if event.stage == DiagnosticStage.STT_STREAM_END]) == 1
    await registry.aclose()


@pytest.mark.asyncio
async def test_broken_sink_and_arbitrary_exception_text_do_not_escape_or_change_failure():
    class Broken(CollectDiagnostics):
        def emit(self, event):
            raise OSError('synthetic-secret-log-detail')
    class Failed:
        async def transcribe_events(self, packets):
            raise RuntimeError('synthetic-secret-provider-detail')
            yield
    registry = ContinuousListeningRegistry(diagnostics=Broken())
    lease = await registry.start(str(uuid4()), str(uuid4()))
    await lease.recognize(Failed(), is_current=registry.is_current,
                          register_utterance=registry.register_utterance)
    assert lease.reason == 'unavailable'
    assert 'synthetic-secret' not in repr(list(lease.events._queue))
    await registry.aclose()


@pytest.mark.asyncio
async def test_stop_is_diagnosed_before_slow_provider_cleanup_finishes():
    entered, cleanup_started, allow_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class SlowCleanup:
        async def transcribe_events(self, packets):
            try:
                entered.set()
                await asyncio.Event().wait()
                yield
            finally:
                cleanup_started.set()
                await allow_cleanup.wait()
    sink = CollectDiagnostics()
    registry = ContinuousListeningRegistry(diagnostics=sink)
    lease = await registry.start(str(uuid4()), str(uuid4()))
    task = asyncio.create_task(lease.recognize(SlowCleanup(), is_current=registry.is_current,
                                               register_utterance=registry.register_utterance))
    lease._recognition_task = task
    try:
        await entered.wait()
        await registry.stop_lease(lease, 'user_stop')
        await asyncio.wait_for(cleanup_started.wait(), 1)
        assert not task.done()
        assert any(event.stage == DiagnosticStage.STT and event.outcome == DiagnosticOutcome.CANCELLED
                   and event.cancellation_reason == CancellationReason.USER_STOP for event in sink.events)
        assert not any(event.stage == DiagnosticStage.STT_STREAM_END for event in sink.events)
    finally:
        allow_cleanup.set()
        await asyncio.gather(task, return_exceptions=True)
        await registry.aclose()


@pytest.mark.asyncio
async def test_declared_duration_limit_is_not_reported_as_a_user_click():
    entered = asyncio.Event()
    class Waiting:
        async def transcribe_events(self, packets):
            entered.set()
            await asyncio.Event().wait()
            yield
    sink = CollectDiagnostics()
    registry = ContinuousListeningRegistry(diagnostics=sink)
    lease = await registry.start(str(uuid4()), str(uuid4()))
    task = asyncio.create_task(lease.recognize(Waiting(), is_current=registry.is_current,
                                               register_utterance=registry.register_utterance))
    lease._recognition_task = task
    await entered.wait()
    await registry.stop_lease(lease, 'max_duration')
    await asyncio.gather(task, return_exceptions=True)
    finished = [event for event in sink.events if event.stage == DiagnosticStage.STT
                and event.outcome != DiagnosticOutcome.STARTED]
    assert len(finished) == 1
    assert finished[0].outcome == DiagnosticOutcome.SUCCEEDED
    assert finished[0].code == DiagnosticCode.LIMIT_REACHED
    assert finished[0].cancellation_reason is None
    await registry.aclose()


@pytest.mark.parametrize('code', ['unauthenticated', 'permission_denied', 'quota_exhausted', 'timeout'])
def test_actual_websocket_terminal_keeps_safe_reason_and_logged_locator(code):
    import base64
    import json
    from fastapi.testclient import TestClient
    from mira.bootstrap.providers import Providers
    from mira.config.settings import Settings
    from mira.entrypoints.http.app import create_app
    from tests.integration.test_continuous_listening_http import _Generate, _Review
    class Failed:
        endpoint_mode = 'google_vad_offsets'
        max_stream_seconds = 2
        async def transcribe_events(self, packets):
            await anext(packets)
            raise SpeechProviderError(code)
            yield
    sink = CollectDiagnostics()
    settings = Settings().model_copy(update={'environment': 'test',
        'http': Settings().http.model_copy(update={'allowed_origins': ('http://testserver',)})})
    app = create_app(settings, providers=Providers(_Generate(), _Review()),
                     continuous_speech_recognition=Failed(), diagnostics=sink)
    with TestClient(app) as client:
        created = client.post('/api/v1/sessions', json={'client_instance_id': str(uuid4())}).json()
        sid, token = created['session']['session_id'], created['session_token']
        lid = str(uuid4())
        with client.websocket_connect(f'/api/v1/sessions/{sid}/continuous-listening',
                                      headers={'origin': 'http://testserver'}) as ws:
            ws.send_json({'type': 'start', 'session_token': token, 'lease_id': lid})
            assert ws.receive_json()['type'] == 'ready'
            ws.send_json({'type': 'audio', 'lease_id': lid, 'sequence': 1, 'first_sample': 0,
                          'pcm_base64': base64.b64encode(b'\0\0' * 80).decode('ascii')})
            ended = ws.receive_json()
            if ended['type'] == 'recognition_status':
                assert ended['stream_index'] == 1 and ended['state'] == 'opening'
                ended = ws.receive_json()
            assert ended['type'] == 'stopped' and ended['reason'] == code
            assert ended['diagnostic_id'].startswith('h_') and len(ended['diagnostic_id']) == 34
            assert token not in json.dumps(ended)
    failures = [event for event in sink.events if event.stage == DiagnosticStage.STT
                and event.outcome == DiagnosticOutcome.FAILED]
    assert len(failures) == 1
    assert failures[0].code.value == code
    assert correlation_hash(failures[0].context.request_id) == ended['diagnostic_id']
    assert failures[0].context.session_id == sid
    assert token not in repr(sink.events)
