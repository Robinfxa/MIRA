import asyncio
from dataclasses import replace

import pytest

from mira.adapters.generation.mock import MockGenerationBackend
from mira.adapters.journal.memory import MemoryEventJournal
from mira.adapters.review.mock import FixtureReviewBackend
from mira.application.continuous_listening import ContinuousListeningRegistry, ListeningLimits, SAMPLE_RATE_HZ
from mira.application.ports.continuous_speech import ContinuousTranscriptResult
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.domain.errors import DomainError
from mira.domain.models import SessionState


def uid(n):
    return f'00000000-0000-4000-8000-{n:012x}'


def unlimited():
    return ListeningLimits(max_seconds=None, max_samples=None, max_utterances=None,
                           max_streams_per_session=None, max_total_streams=None,
                           max_recognition_streams=None)


def drain(lease):
    while not lease.events.empty():
        lease.events.get_nowait()


@pytest.mark.asyncio
async def test_local_none_accepts_more_than_twenty_turns_with_bounded_reliable_history():
    actor = SessionActor(SessionState('one', 'desktop'), MockGenerationBackend(0),
                         FixtureReviewBackend(), MemoryEventJournal(100), RuntimeLimits(1, None, 128))
    for i in range(1, 100):
        await actor.submit(request_id=uid(i), activity_seq=i, cutoff=0, text=f'hello {i}')
        async with asyncio.timeout(2):
            while actor._tasks:
                await asyncio.sleep(0)
    state = await actor.snapshot()
    assert state.input_epoch == 99
    assert len(state.user_inputs) <= 64
    assert state.user_inputs[-1] == 'hello 99'
    assert state.retired_user_inputs > 0
    assert len(actor._request_fingerprints) <= 64
    assert len(actor._decision_inputs) == len(state.user_inputs)
    assert len(state.issued_effects) <= 128
    with pytest.raises(DomainError) as expired:
        await actor.submit(request_id=uid(1), activity_seq=1, cutoff=0, text='hello 1')
    assert expired.value.code == 'stale_activity'
    await actor.close()


@pytest.mark.asyncio
async def test_finite_actor_limit_remains_irreversible():
    actor = SessionActor(SessionState('one', 'desktop'), MockGenerationBackend(0),
                         FixtureReviewBackend(), MemoryEventJournal(100), RuntimeLimits(1, 2, 128))
    for i in (1, 2):
        await actor.submit(request_id=uid(i), activity_seq=i * 2 - 1, cutoff=0, text='hello')
        await actor.stop(activity_seq=i * 2, cutoff=0)
    with pytest.raises(DomainError) as error:
        await actor.submit(request_id=uid(3), activity_seq=30, cutoff=0, text='hello')
    assert error.value.code == 'session_capacity'
    await actor.close()


@pytest.mark.asyncio
async def test_none_lease_passes_old_duration_with_finite_audio_backpressure(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr('mira.application.continuous_listening.time.monotonic', lambda: now[0])
    registry = ContinuousListeningRegistry(limits=unlimited())
    lease = await registry.start('desktop', uid(1))
    now[0] += 121
    assert lease.audio.remaining_seconds is None
    lease.audio._samples = SAMPLE_RATE_HZ * 120
    lease.audio.push(lease_id=uid(1), sequence=1, first_sample=SAMPLE_RATE_HZ * 120, pcm=b'\x00\x00' * 320)
    assert lease.active
    with pytest.raises(DomainError):
        lease.audio.push(lease_id=uid(1), sequence=2, first_sample=lease.audio.samples, pcm=b'\x00' * 12002)
    await registry.aclose()


@pytest.mark.asyncio
async def test_none_commits_and_restarts_keep_bounded_records_and_isolate_sessions():
    registry = ContinuousListeningRegistry(limits=unlimited())
    other = await registry.start('phone', uid(2000))
    await other._on_transcript(ContinuousTranscriptResult('phone only', True, 100))
    for n in range(1, 81):
        lease = await registry.start('desktop', uid(n))
        for i in range(13):
            await lease._on_transcript(ContinuousTranscriptResult(f'desktop {n}/{i}', True, (i + 1) * 100))
            drain(lease)
            commit = uid(n * 100 + i + 10000)
            result = await lease.manual_commit(commit_id=commit, revision=lease.revision, registry=registry)
            await registry.mark_delivered('desktop', lease.lease_id, commit)
            await registry.validate_submission('desktop', commit, commit, result.text)
            await registry.mark_accepted('desktop', commit, commit, result.text)
            drain(lease)
        assert lease.active
        assert len(lease._commit_results) <= 64 and len(lease._finals) <= 32
        assert len(lease._late_revision_events) <= 64 and len(lease._client_endpoints) <= 64
    assert other.stable_text == 'phone only'
    assert registry.total_lease_starts == 81
    assert len(registry._utterances) <= 129
    assert len(registry._used_lease_ids) <= 129
    assert len(registry._lease_count) == 2
    await registry.close_session("desktop")
    assert set(registry._lease_count) == {"phone"}
    assert all(key[0] == "phone" for key in registry._used_lease_ids)
    assert all(key[0] == "phone" for key in registry._utterances)
    assert other.active and other.stable_text == "phone only"
    await registry.aclose()
    assert not registry._lease_count and not registry._used_lease_ids and not registry._utterances


@pytest.mark.asyncio
async def test_duration_rollover_keeps_every_sample_and_final_then_stops_at_shared_service_budget():
    from mira.bootstrap.development_voice import _AttemptBudget, _BoundedRecognitionEvents
    captured = []
    class Provider:
        endpoint_mode = 'google_vad_offsets'
        max_stream_seconds = .02
        async def transcribe_events(self, packets):
            seen = []
            async for packet in packets:
                seen.append(packet)
            captured.append(tuple(seen))
            if seen:
                yield ContinuousTranscriptResult(f'final {len(captured)}.', True,
                    seen[-1].first_sample + len(seen[-1].pcm) // 2)
    budget = _AttemptBudget(2, 'input_limit')
    backend = _BoundedRecognitionEvents(Provider(), attempts=budget, max_seconds=.02)
    registry = ContinuousListeningRegistry(limits=unlimited())
    lease = await registry.start('desktop', uid(1), natural_mode=True)
    # One packet crosses the exact first RPC boundary; its tail belongs to RPC two.
    original = bytes(range(256)) * 5
    lease.audio.push(lease_id=uid(1), sequence=1, first_sample=0, pcm=original)
    await asyncio.wait_for(lease.recognize(backend, is_current=registry.is_current,
        register_utterance=registry.register_utterance, request_budget=budget), 1)
    assert budget.snapshot().used == 2
    assert [sum(len(p.pcm) // 2 for p in stream) for stream in captured] == [320, 320]
    assert b''.join(p.pcm for stream in captured for p in stream) == original
    assert lease.reason == 'service_budget_exhausted'
    assert lease.terminal_preview.text == 'final 1.final 2.'
    assert any(event.type == 'stopped' and event.reason == 'service_budget_exhausted' for event in list(lease.events._queue))
    # A fresh local lease never resets paid service accounting.
    restarted = await registry.start('desktop', uid(2), natural_mode=True)
    restarted.audio.push(lease_id=uid(2), sequence=1, first_sample=0, pcm=b'\x00\x00' * 320)
    await restarted.recognize(backend, is_current=registry.is_current,
        register_utterance=registry.register_utterance, request_budget=budget)
    assert restarted.reason == 'service_budget_exhausted'
    assert len(captured) == 2 and budget.snapshot().used == 2
    await registry.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("request_limit", [2, None])
async def test_two_clients_share_attempts_cancel_and_failure_never_refund_or_retry(request_limit):
    from mira.bootstrap.development_voice import _AttemptBudget, _BoundedRecognitionEvents
    from mira.adapters.speech.errors import SpeechProviderError
    entered = asyncio.Event()
    calls = []
    class Provider:
        endpoint_mode = 'google_vad_offsets'
        max_stream_seconds = 120
        async def transcribe_events(self, packets):
            await anext(packets)
            calls.append(1)
            entered.set()
            if len(calls) == 1:
                await asyncio.Event().wait()
            raise SpeechProviderError('unavailable')
            yield
    budget = _AttemptBudget(request_limit, 'input_limit')
    backend = _BoundedRecognitionEvents(Provider(), attempts=budget, max_seconds=120)
    registry = ContinuousListeningRegistry(limits=unlimited())
    desktop = await registry.start('desktop', uid(1), natural_mode=True)
    desktop.audio.push(lease_id=uid(1), sequence=1, first_sample=0, pcm=b'\x00\x00' * 320)
    desktop._recognition_task = asyncio.create_task(desktop.recognize(backend,
        is_current=registry.is_current, register_utterance=registry.register_utterance, request_budget=budget))
    await entered.wait()
    await registry.stop_session('desktop')
    await asyncio.gather(desktop._recognition_task, return_exceptions=True)
    assert budget.snapshot().used == 1
    phone = await registry.start('phone', uid(2), natural_mode=True)
    phone.audio.push(lease_id=uid(2), sequence=1, first_sample=0, pcm=b'\x00\x00' * 320)
    await phone.recognize(backend, is_current=registry.is_current,
        register_utterance=registry.register_utterance, request_budget=budget)
    assert phone.reason == 'unavailable'
    assert len(calls) == 2 and budget.snapshot().used == 2
    await registry.aclose()


def test_retired_receipts_cannot_reuse_sequence_and_remaining_facts_keep_provenance():
    from mira.domain import transitions
    from mira.domain.models import Effect, EffectKind, Receipt
    state = SessionState('s', 'c')
    receipts = []
    for i in range(1, 151):
        state = transitions.begin_input(state, request_id=uid(i), activity_seq=i, cutoff=i-1, text=f'input {i}')
        state = transitions.retain_recent_history(state, max_inputs=64, max_effects=16)
        effect = Effect(uid(i), EffectKind.SUBTITLE, f'output {i}', f'digest-{i}', state.output_epoch, i)
        state = transitions.accept_range(state, output_epoch=state.output_epoch, effects=(effect,))
        receipt = Receipt(effect.id, effect.digest, state.output_epoch, i, i)
        receipts.append(receipt)
        state = transitions.record_receipt(state, receipt)
    assert len(state.issued_effects) == 17 and len(state.receipts) == 17
    assert state.receipts[-1] == receipts[-1]
    assert state.presentation_floor == 149
    with pytest.raises(DomainError):
        transitions.record_receipt(state, receipts[0])
    with pytest.raises(DomainError) as reused:
        transitions.record_receipt(state, replace(receipts[-1], presentation_seq=1))
    assert reused.value.code == 'receipt_conflict'
    state = transitions.begin_input(state, request_id='next', activity_seq=151, cutoff=150, text='still works')
    assert state.input_epoch == 151


@pytest.mark.asyncio
async def test_rollover_mid_utterance_commits_both_final_pieces_exactly_once():
    from mira.bootstrap.development_voice import _AttemptBudget, _BoundedRecognitionEvents
    second_audio = asyncio.Event()
    class Provider:
        endpoint_mode = 'google_vad_offsets'
        max_stream_seconds = .02
        calls = 0
        async def transcribe_events(self, packets):
            self.calls += 1
            count = self.calls
            last = None
            async for packet in packets:
                last = packet
                if count == 2:
                    second_audio.set()
            if last:
                yield ContinuousTranscriptResult('before ' if count == 1 else 'after', True,
                    last.first_sample + len(last.pcm) // 2)
    provider = Provider()
    budget = _AttemptBudget(3, 'input_limit')
    backend = _BoundedRecognitionEvents(provider, attempts=budget, max_seconds=.02)
    registry = ContinuousListeningRegistry(limits=unlimited())
    lease = await registry.start('desktop', uid(3), natural_mode=True, client_endpointing=True)
    lease.audio.push(lease_id=uid(3), sequence=1, first_sample=0, pcm=b'\x00\x00' * 480)
    lease._recognition_task = asyncio.create_task(lease.recognize(backend,
        is_current=registry.is_current, register_utterance=registry.register_utterance, request_budget=budget))
    await asyncio.wait_for(second_audio.wait(), 1)
    await lease.request_client_endpoint(endpoint_id=uid(4), source_end_sample=480)
    async with asyncio.timeout(1):
        while not lease._segment_sealed:
            await asyncio.sleep(0)
    candidate = lease.natural_candidate()
    assert candidate is not None and candidate.text == 'before after'
    result = await lease.manual_commit(commit_id=uid(5), revision=candidate.revision,
        utterance_id=candidate.utterance_id, registry=registry)
    assert result.text == 'before after' and lease.stable_text == ''
    assert await lease.manual_commit(commit_id=uid(5), revision=candidate.revision,
        utterance_id=candidate.utterance_id, registry=registry) == result
    assert lease._commit_count == 1 and budget.snapshot().used == 2
    await registry.aclose()


@pytest.mark.asyncio
async def test_hard_duration_drain_timeout_does_not_loop_or_erase_final():
    from mira.bootstrap.development_voice import _AttemptBudget, _BoundedRecognitionEvents
    class Provider:
        endpoint_mode = 'google_vad_offsets'
        max_stream_seconds = .01
        calls = 0
        async def transcribe_events(self, packets):
            self.calls += 1
            async for packet in packets:
                yield ContinuousTranscriptResult('recognized', True, len(packet.pcm) // 2)
            await asyncio.Event().wait()
    provider = Provider()
    budget = _AttemptBudget(3, 'input_limit')
    backend = _BoundedRecognitionEvents(provider, attempts=budget, max_seconds=.01)
    registry = ContinuousListeningRegistry(limits=replace(unlimited(), drain_timeout_seconds=.1))
    lease = await registry.start('desktop', uid(6), natural_mode=True)
    lease.audio.push(lease_id=uid(6), sequence=1, first_sample=0, pcm=b'\x00\x00' * 160)
    lease._recognition_task = asyncio.create_task(lease.recognize(backend,
        is_current=registry.is_current, register_utterance=registry.register_utterance, request_budget=budget))
    await asyncio.wait_for(asyncio.gather(lease._recognition_task, return_exceptions=True), 1)
    assert lease.reason == 'timeout' and lease.terminal_preview.text == 'recognized'
    assert provider.calls == 1 and budget.snapshot().used == 1
    await registry.aclose()


def test_history_retains_exact_latest_audio_and_old_control_without_raw_progress_growth():
    from mira.domain import transitions
    from mira.domain.models import AudioProgress, AudioStatus, Effect, EffectKind, Receipt
    state = transitions.begin_input(SessionState('s', 'c'), request_id='scene', activity_seq=1, cutoff=0, text='scene')
    control = Effect('scene', EffectKind.SCENE, 'cafe_warm', 'scene-digest', 1, 1)
    state = transitions.accept_range(state, output_epoch=1, effects=(control,))
    state = transitions.record_receipt(state, Receipt(control.id, control.digest, 1, 1, 1))
    seq = 1
    latest = None
    for i in range(2, 70):
        state = transitions.begin_input(state, request_id=uid(i), activity_seq=i, cutoff=seq, text=f'audio {i}')
        state = transitions.retain_recent_history(state, max_inputs=64, max_effects=16)
        speech = Effect(uid(i), EffectKind.SPEECH, 'said text', f'digest-{i}', state.output_epoch, i)
        state = transitions.accept_range(state, output_epoch=state.output_epoch, effects=(speech,))
        for samples, status in ((100, AudioStatus.RENDERED), (200, AudioStatus.RENDERED), (300, AudioStatus.COMPLETED)):
            seq += 1
            latest = AudioProgress(speech.id, speech.digest, state.output_epoch, i, seq, 16000, samples, status)
            state = transitions.record_audio_progress(state, latest)
    state = transitions.begin_input(state, request_id='next', activity_seq=70, cutoff=seq, text='next')
    state = transitions.retain_recent_history(state, max_inputs=64, max_effects=16)
    assert control in state.presented_effects
    assert len(state.audio_progress) <= 16
    assert latest in state.audio_progress and latest.rendered_samples == 300
    assert state.presentation_floor == seq


@pytest.mark.asyncio
async def test_archive_pending_records_backpressure_before_retirement_and_keep_absolute_indices():
    from mira.application.actor_conversation import SessionConversationBinding
    release = asyncio.Event()
    entered = asyncio.Event()
    captures = []
    class Archive:
        async def capture(self, *args):
            entered.set()
            await release.wait()
            captures.append(args)
        async def load_session(self, *args): pass
        async def session_revision(self, *args): pass
        async def aclose(self): pass
    binding = SessionConversationBinding(Archive(), authorize_transcript_persistence=True)
    # No presentation rows are needed for this storage sequencing test.
    class Empty:
        async def generate(self, context):
            if False: yield
    actor = SessionActor(SessionState('s', 'c'), Empty(), FixtureReviewBackend(), MemoryEventJournal(100),
                         RuntimeLimits(1, None, 128), conversation_binding=binding)
    for n in range(1, 65):
        await actor.submit(request_id=uid(n), activity_seq=n, cutoff=0, text=f'input {n}')
        while actor._tasks: await asyncio.sleep(0)
    await entered.wait()
    with pytest.raises(DomainError) as blocked:
        await actor.submit(request_id=uid(65), activity_seq=65, cutoff=0, text='input 65')
    assert blocked.value.code == 'busy'
    assert (await actor.snapshot()).input_epoch == 64
    release.set()
    await binding.flush()
    await actor.submit(request_id=uid(65), activity_seq=65, cutoff=0, text='input 65')
    while actor._tasks: await asyncio.sleep(0)
    await binding.flush()
    saved = {item.user_input_index: item.text for batch in captures for item in batch[1]}
    assert saved == {i: f'input {i + 1}' for i in range(65)}
    assert actor._conversation_inputs[-1].user_input_index == 64
    await actor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("lease_seconds", [None, 120])
async def test_unlimited_shared_stt_rolls_many_streams_without_truncating_one_utterance(lease_seconds):
    from mira.bootstrap.development_voice import _AttemptBudget, _BoundedRecognitionEvents
    captured = []
    goal = asyncio.Event()

    class Provider:
        endpoint_mode = 'google_vad_offsets'
        max_stream_seconds = .01
        async def transcribe_events(self, packets):
            seen = [packet async for packet in packets]
            captured.append(tuple(seen))
            if seen:
                yield ContinuousTranscriptResult(f'{len(captured)}.', True,
                    seen[-1].first_sample + len(seen[-1].pcm) // 2)

    budget = _AttemptBudget(None, 'input_limit')
    backend = _BoundedRecognitionEvents(Provider(), attempts=budget, max_seconds=.01)
    registry = ContinuousListeningRegistry(limits=replace(unlimited(), max_seconds=lease_seconds,
        max_samples=None if lease_seconds is None else lease_seconds * SAMPLE_RATE_HZ))
    lease = await registry.start('desktop', uid(1), natural_mode=True, client_endpointing=True)
    original = bytes(range(256)) * 30  # 24 exact bounded streams, one continuous utterance.
    lease.audio.push(lease_id=uid(1), sequence=1, first_sample=0, pcm=original)

    async def consume():
        while True:
            event = await lease.events.get()
            assert event.type != 'utterance_ready', 'RPC duration does not mean the user stopped speaking'
            if event.type == 'transcript' and event.revision == 24:
                goal.set()

    consumer = asyncio.create_task(consume())
    recognition = asyncio.create_task(lease.recognize(backend, is_current=registry.is_current,
        register_utterance=registry.register_utterance, request_budget=budget))
    lease._recognition_task = recognition
    try:
        await asyncio.wait_for(goal.wait(), 2)
        assert lease.active and budget.snapshot().used == 24
        assert budget.snapshot().remaining is None
        assert lease.stable_text == ''.join(f'{n}.' for n in range(1, 25))
        assert b''.join(p.pcm for stream in captured for p in stream) == original
        assert all(sum(len(p.pcm) // 2 for p in stream) == 160 for stream in captured)
        assert lease._commit_count == 0
    finally:
        consumer.cancel()
        await registry.aclose()
        await asyncio.gather(consumer, recognition, return_exceptions=True)


@pytest.mark.asyncio
async def test_actual_120_second_rpc_boundaries_preserve_260_seconds_of_pcm_and_one_whole_commit():
    import hashlib
    import time
    from mira.bootstrap.development_voice import _AttemptBudget, _BoundedRecognitionEvents
    observed_hash = hashlib.sha256()
    expected_hash = hashlib.sha256()
    stream_samples = []
    candidates = []
    ready = asyncio.Event()

    class Provider:
        endpoint_mode = 'google_vad_offsets'
        max_stream_seconds = 120
        async def transcribe_events(self, packets):
            stream_samples.append(0)
            index = len(stream_samples) - 1
            async for packet in packets:
                observed_hash.update(packet.pcm)
                stream_samples[index] += len(packet.pcm) // 2
            if stream_samples[index]:
                yield ContinuousTranscriptResult(f'part{index + 1} ', True, stream_samples[index])

    budget = _AttemptBudget(None, 'input_limit')
    backend = _BoundedRecognitionEvents(Provider(), attempts=budget, max_seconds=120)
    registry = ContinuousListeningRegistry(limits=unlimited())
    lease = await registry.start('desktop', uid(1), natural_mode=True, client_endpointing=True)

    async def consume():
        while True:
            event = await lease.events.get()
            if event.type == 'utterance_ready':
                candidates.append(event); ready.set()

    consumer = asyncio.create_task(consume())
    recognition = asyncio.create_task(lease.recognize(backend, is_current=registry.is_current,
        register_utterance=registry.register_utterance, request_budget=budget))
    lease._recognition_task = recognition
    peak_queue = 0
    try:
        total = 260 * SAMPLE_RATE_HZ
        sequence = 0
        while lease.audio.samples < total:
            sequence += 1
            samples = min(6000, total - lease.audio.samples)
            pcm = b'\x01\x02' * samples
            # Advance only the synthetic capture clock; exercise production sample bounds.
            lease.audio._started = time.monotonic() - (lease.audio.samples + samples) / SAMPLE_RATE_HZ
            lease.audio.push(lease_id=lease.lease_id, sequence=sequence,
                first_sample=lease.audio.samples, pcm=pcm)
            expected_hash.update(pcm)
            peak_queue = max(peak_queue, lease.audio._queued_samples)
            while lease.audio._queued_samples:
                await asyncio.sleep(0)
            assert lease.active and not candidates
        assert stream_samples == [120 * SAMPLE_RATE_HZ, 120 * SAMPLE_RATE_HZ, 20 * SAMPLE_RATE_HZ]
        assert budget.snapshot().used == 3 and budget.snapshot().remaining is None
        await lease.request_client_endpoint(endpoint_id=uid(2), source_end_sample=total)
        await asyncio.wait_for(ready.wait(), 1)
        candidate = candidates[0]
        assert candidate.text == 'part1 part2 part3'
        assert candidate.source_end_sample == total and peak_queue <= 32_000
        result = await lease.manual_commit(commit_id=uid(3), revision=candidate.revision,
            utterance_id=candidate.utterance_id, registry=registry)
        assert result.text == 'part1 part2 part3' and lease._commit_count == 1
        assert observed_hash.digest() == expected_hash.digest()
        assert len(lease._commit_results) <= 64 and len(lease._settled_activities) <= 33
        assert len(lease._client_endpoints) <= 64 and len(lease._finals) <= 32
        await asyncio.sleep(0)
        lease.audio.push(lease_id=lease.lease_id, sequence=sequence + 1, first_sample=total, pcm=b'\0\0' * 640)
        async with asyncio.timeout(1):
            while budget.snapshot().used != 4:
                await asyncio.sleep(0)
        assert lease.active and lease.audio.samples == total + 640
    finally:
        consumer.cancel(); await registry.aclose()
        await asyncio.gather(consumer, recognition, return_exceptions=True)


@pytest.mark.asyncio
async def test_three_hundred_real_segmented_utterances_keep_service_and_revision_state_bounded():
    import time
    from mira.bootstrap.development_voice import _AttemptBudget, _BoundedRecognitionEvents
    candidates = asyncio.Queue()
    calls = 0

    class Provider:
        endpoint_mode = 'google_vad_offsets'
        max_stream_seconds = 120
        async def transcribe_events(self, packets):
            nonlocal calls
            total = 0
            async for packet in packets:
                if total == 0:
                    calls += 1
                total += len(packet.pcm) // 2
            if total:
                yield ContinuousTranscriptResult(f'utterance {calls}', True, total)

    budget = _AttemptBudget(None, 'input_limit')
    backend = _BoundedRecognitionEvents(Provider(), attempts=budget, max_seconds=120)
    registry = ContinuousListeningRegistry(limits=unlimited())
    lease = await registry.start('desktop', uid(1), natural_mode=True, client_endpointing=True)

    async def consume():
        while True:
            event = await lease.events.get()
            if event.type == 'utterance_ready':
                await candidates.put(event)

    consumer = asyncio.create_task(consume())
    task = asyncio.create_task(lease.recognize(backend, is_current=registry.is_current,
        register_utterance=registry.register_utterance, request_budget=budget))
    lease._recognition_task = task
    first = None
    try:
        for n in range(1, 301):
            async with asyncio.timeout(1):
                while lease._segment is None or lease._segment.draining or lease._segment_sealed:
                    await asyncio.sleep(0)
            lease.audio._started = time.monotonic() - n * 640 / SAMPLE_RATE_HZ
            lease.audio.push(lease_id=lease.lease_id, sequence=n, first_sample=(n - 1) * 640, pcm=b'\1\0' * 640)
            await lease.request_client_endpoint(endpoint_id=uid(1000 + n), source_end_sample=n * 640)
            candidate = await asyncio.wait_for(candidates.get(), 1)
            result = await lease.manual_commit(commit_id=uid(2000 + n), revision=candidate.revision,
                utterance_id=candidate.utterance_id, registry=registry)
            await registry.mark_delivered('desktop', lease.lease_id, result.commit_id)
            await registry.validate_submission('desktop', result.commit_id, result.commit_id, result.text)
            await registry.mark_accepted('desktop', result.commit_id, result.commit_id, result.text)
            if first is None:
                first = candidate
            assert result.text == f'utterance {n}' and lease.active
            assert len(lease._commit_results) <= 64
            assert len(lease._settled_activities) <= 33 and len(lease._client_endpoints) <= 64
            assert len(lease._finals) <= 32 and len(lease._seen_offsets) <= 2
            assert len(registry._utterances) <= 128 and len(lease._late_revision_events) <= 64
        assert lease._commit_count == calls == budget.snapshot().used == 300
        assert budget.snapshot().remaining is None and lease.stable_text == ''
        with pytest.raises(DomainError) as stale:
            await lease.manual_commit(commit_id=uid(2001), revision=first.revision,
                utterance_id=first.utterance_id, registry=registry)
        assert stale.value.code == 'transcript_stale'
        assert budget.snapshot().used == 300
    finally:
        consumer.cancel(); await registry.aclose()
        await asyncio.gather(consumer, task, return_exceptions=True)
