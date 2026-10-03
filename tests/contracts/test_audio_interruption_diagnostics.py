"""Offline observed interruption facts must not invent a user Stop cause."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mira.adapters.diagnostics.privacy import encode_event
from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.contracts import CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict
from mira.application.diagnostic_events import (
    CancellationReason, DiagnosticCode, DiagnosticOutcome, DiagnosticStage,
    correlation_hash, request_correlation,
)
from mira.application.media_runtime import MicrophoneBuffer
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.domain.errors import DomainError
from mira.domain.models import AudioProgress, AudioStatus, EffectKind, SessionState


class Events:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)
        return True


class Generate:
    async def generate(self, context):
        for text in ("Synthetic speech", "Synthetic pending tail"):
            yield CandidateRange((EffectProposal(EffectKind.SPEECH, text),), "synthetic")


class HeldReview:
    def __init__(self):
        self.entered = {1: asyncio.Event(), 2: asyncio.Event()}

    async def review(self, context, candidate):
        if context.output_epoch != 1 or context.accepted_prefix:
            self.entered[context.output_epoch].set()
            await asyncio.Event().wait()
        return ReviewObservation(ReviewVerdict.ALLOW, "synthetic")


class HeldSpeech:
    def __init__(self):
        self.started = asyncio.Event()

    async def synthesize(self, text, stream_id):
        self.started.set()
        await asyncio.Event().wait()
        yield


class HeldMicrophone:
    def __init__(self):
        self.started = asyncio.Event()

    async def transcribe(self, packets):
        self.started.set()
        await asyncio.Event().wait()
        yield


@asynccontextmanager
async def ready_actor():
    sink, review, speech, microphone = Events(), HeldReview(), HeldSpeech(), HeldMicrophone()
    actor = SessionActor(SessionState(str(uuid4()), str(uuid4())), Generate(), review,
        MemoryEventJournal(100), RuntimeLimits(5, 10, 30), diagnostics=sink,
        speech_synthesis=speech, speech_recognition=microphone)
    try:
        await actor.submit(request_id=str(uuid4()), activity_seq=1, cutoff=0, text="Synthetic input")
        async with asyncio.timeout(1):
            await review.entered[1].wait()
        before = await actor.snapshot()
        effect, = before.active_grants
        operation = await actor.open_speech(effect_id=effect.id, digest=effect.digest,
            output_epoch=effect.output_epoch, activity_seq=effect.activity_seq)
        buffer = MicrophoneBuffer(str(uuid4()))
        mic = await actor.open_microphone(stream_id=buffer.stream_id, activity_seq=1,
                                          input_epoch=1, buffer=buffer)
        async with asyncio.timeout(1):
            await speech.started.wait()
            await microphone.started.wait()
        buffer.push(sequence=1, first_sample=0, pcm=b"\0\0" * 320)
        progress = AudioProgress(effect.id, effect.digest, 1, 1, 1, 24000, 240, AudioStatus.RENDERED)
        await actor.audio_progress(progress)
        yield SimpleNamespace(actor=actor, sink=sink, review=review, operation=operation, mic=mic,
            buffer=buffer, progress=progress, tasks=tuple(actor._tasks))
    finally:
        await actor.close()


def cancelled(events, stage):
    return [event for event in events if event.stage == stage
            and event.outcome == DiagnosticOutcome.CANCELLED]


async def finish_cancelled_work(parts):
    await asyncio.gather(*parts.tasks, *parts.operation.tasks, *parts.mic.tasks,
                         return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", [DiagnosticStage.PLAYBACK, DiagnosticStage.GENERATION,
    DiagnosticStage.OUTPUT_REVIEW, DiagnosticStage.TTS, DiagnosticStage.STT])
async def test_interruption_distinguishes_unknown_playback_from_revoked_work(stage):
    async with ready_actor() as parts:
        terminal = replace(parts.progress, presentation_seq=2, status=AudioStatus.INTERRUPTED)
        request_id = str(uuid4())
        token = request_correlation.set(request_id)
        try:
            state = await parts.actor.audio_progress(terminal)
        finally:
            request_correlation.reset(token)
        # Authority and input disposal still change before any cleanup await.
        assert state.request_id is None and state.active_grants == ()
        assert state.audio_progress == (parts.progress, terminal)
        assert state.presented_effects == () and state.user_inputs == ("Synthetic input",)
        assert state.last_error == "audio_interrupted"
        assert state.last_error_diagnostic_id == correlation_hash(request_id)
        assert parts.operation.cancelled.is_set() and parts.mic.cancelled.is_set()
        assert parts.buffer.finished and parts.buffer._queue.empty()
        await finish_cancelled_work(parts)
        observed, = cancelled(parts.sink.events, stage)
        expected = CancellationReason.UNKNOWN if stage == DiagnosticStage.PLAYBACK else CancellationReason.PERMIT_REVOKED
        assert observed.cancellation_reason == expected
        assert observed.code == DiagnosticCode.CANCELLED
        playback, = cancelled(parts.sink.events, DiagnosticStage.PLAYBACK)
        assert encode_event(playback, 1)["context"]["request_id"] == state.last_error_diagnostic_id
        assert not any(event.cancellation_reason == CancellationReason.USER_STOP for event in parts.sink.events)
        with pytest.raises(DomainError, match="cancelled"):
            await anext(parts.operation.values())
        events = tuple(parts.sink.events)
        assert await parts.actor.audio_progress(terminal) is state
        assert tuple(parts.sink.events) == events


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["stop", "new_input"])
async def test_known_cause_survives_late_interruption_without_cancelling_new_branch(action):
    async with ready_actor() as parts:
        reason = CancellationReason.USER_STOP if action == "stop" else CancellationReason.SUPERSEDED
        if action == "stop":
            await parts.actor.stop(activity_seq=2, cutoff=2)
            newer = ()
        else:
            await parts.actor.submit(request_id=str(uuid4()), activity_seq=2, cutoff=2,
                                     text="Synthetic new input")
            async with asyncio.timeout(1):
                await parts.review.entered[2].wait()
            newer = tuple(task for task in parts.actor._tasks if task not in parts.tasks)
            assert len(newer) == 1
        await finish_cancelled_work(parts)
        before = await parts.actor.snapshot()
        terminal = replace(parts.progress, presentation_seq=2, status=AudioStatus.INTERRUPTED)
        events_before = tuple(parts.sink.events)
        state = await parts.actor.audio_progress(terminal)
        assert state == replace(before, revision=before.revision + 1,
                               audio_progress=before.audio_progress + (terminal,))
        assert not cancelled(parts.sink.events, DiagnosticStage.PLAYBACK)
        for stage in (DiagnosticStage.GENERATION, DiagnosticStage.OUTPUT_REVIEW,
                      DiagnosticStage.TTS, DiagnosticStage.STT):
            event, = cancelled(parts.sink.events, stage)
            assert event.cancellation_reason == reason
        assert tuple(event for event in parts.sink.events if event.stage != DiagnosticStage.SESSION) == tuple(
            event for event in events_before if event.stage != DiagnosticStage.SESSION)
        assert all(not task.done() and not task.cancelling() for task in newer)
        assert parts.operation._cancel_reason == reason and parts.mic._cancel_reason == reason
        assert await parts.actor.audio_progress(terminal) is state


@pytest.mark.asyncio
async def test_later_stop_does_not_relabel_prior_unexplained_interruption():
    async with ready_actor() as parts:
        terminal = replace(parts.progress, presentation_seq=2, status=AudioStatus.INTERRUPTED)
        await parts.actor.audio_progress(terminal)
        await finish_cancelled_work(parts)
        events = tuple(event for event in parts.sink.events if event.stage != DiagnosticStage.SESSION)
        state = await parts.actor.stop(activity_seq=2, cutoff=2)
        assert state.phase == "stopped" and state.last_error is None
        assert state.last_error_diagnostic_id is None and state.audio_progress[-1] == terminal
        assert await parts.actor.audio_progress(terminal) is state
        assert tuple(event for event in parts.sink.events if event.stage != DiagnosticStage.SESSION) == events
        playback, = cancelled(parts.sink.events, DiagnosticStage.PLAYBACK)
        assert playback.cancellation_reason == CancellationReason.UNKNOWN
        assert parts.operation._cancel_reason == CancellationReason.PERMIT_REVOKED


@pytest.mark.asyncio
async def test_playback_failure_keeps_failure_class_and_permit_revocation():
    async with ready_actor() as parts:
        terminal = replace(parts.progress, presentation_seq=2, status=AudioStatus.FAILED)
        state = await parts.actor.audio_progress(terminal)
        await finish_cancelled_work(parts)
        event, = [event for event in parts.sink.events if event.stage == DiagnosticStage.PLAYBACK]
        assert event.outcome == DiagnosticOutcome.FAILED and event.code == DiagnosticCode.UNKNOWN
        assert event.cancellation_reason is None and state.last_error == "audio_failed"
        for stage in (DiagnosticStage.GENERATION, DiagnosticStage.OUTPUT_REVIEW,
                      DiagnosticStage.TTS, DiagnosticStage.STT):
            observed, = cancelled(parts.sink.events, stage)
            assert observed.cancellation_reason == CancellationReason.PERMIT_REVOKED
        assert await parts.actor.audio_progress(terminal) is state


@pytest.mark.asyncio
async def test_late_interruption_during_stop_teardown_keeps_known_cause():
    async with ready_actor() as parts:
        await parts.actor.stop(activity_seq=2, cutoff=2)
        # Stop has invalidated synchronously; its cancelled children have not run yet.
        assert all(not task.done() and task.cancelling() for task in parts.tasks)
        assert not parts.operation.task.done() and not parts.mic.task.done()
        assert parts.buffer.finished and parts.buffer._queue.empty()
        events = tuple(event for event in parts.sink.events if event.stage != DiagnosticStage.SESSION)
        terminal = replace(parts.progress, presentation_seq=2, status=AudioStatus.INTERRUPTED)
        state = await parts.actor.audio_progress(terminal)
        assert state.phase == "stopped" and state.request_id is None and state.active_grants == ()
        assert state.audio_progress[-1] == terminal and state.last_error_diagnostic_id is None
        assert tuple(event for event in parts.sink.events if event.stage != DiagnosticStage.SESSION) == events
        await finish_cancelled_work(parts)
        for stage in (DiagnosticStage.GENERATION, DiagnosticStage.OUTPUT_REVIEW,
                      DiagnosticStage.TTS, DiagnosticStage.STT):
            observed, = cancelled(parts.sink.events, stage)
            assert observed.cancellation_reason == CancellationReason.USER_STOP
        assert not cancelled(parts.sink.events, DiagnosticStage.PLAYBACK)
