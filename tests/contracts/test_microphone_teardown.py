"""Adversarial barriers, not scheduler delays, expose microphone teardown races."""
import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mira.application.diagnostic_events import CancellationReason
from mira.application.media_runtime import MicrophoneBuffer
from mira.bootstrap.container import build_container
from mira.config.settings import Settings
from mira.domain.errors import DomainError
from mira.entrypoints.http import media_routes


class WaitingStt:
    def __init__(self):
        self.started = asyncio.Event()
        self.closed = asyncio.Event()

    async def transcribe(self, packets):
        self.started.set()
        try:
            await asyncio.Event().wait()
            if False:
                yield
        finally:
            self.closed.set()


class Socket:
    def __init__(self, container, token):
        self.app = SimpleNamespace(state=SimpleNamespace(container=container))
        self.headers = {"origin": "http://localhost:8000"}
        self.query_params = {}
        self.incoming = asyncio.Queue()
        self.frames = []
        self.ready = asyncio.Event()
        self.closed = asyncio.Event()
        self.put({"type": "start", "session_token": token, "stream_id": str(uuid4()),
                  "activity_seq": 0, "input_epoch": 0, "sample_rate_hz": 16000})

    def put(self, value):
        self.incoming.put_nowait({"type": "websocket.receive", "text": json.dumps(value)})

    async def accept(self):
        pass

    async def receive(self):
        return await self.incoming.get()

    async def send_text(self, text):
        self.frames.append(json.loads(text))
        if self.frames[-1]["type"] == "ready":
            self.ready.set()

    async def close(self, **kwargs):
        self.closed.set()


class HeldSender:
    """Force the real route to suspend while one socket child is cleaning up."""
    def __init__(self):
        self.started = asyncio.Event()
        self.cleaning = asyncio.Event()
        self.release = asyncio.Event()
        self.task = None

    async def __call__(self, *args):
        self.task = asyncio.current_task()
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cleaning.set()
            await self.release.wait()


async def entered_request(monkeypatch):
    stt, sender = WaitingStt(), HeldSender()
    container = build_container(Settings(), speech_recognition=stt)
    actor, token = container.sessions.create(str(uuid4()))
    buffers = []
    class ObservedBuffer(MicrophoneBuffer):
        def __init__(self, stream_id):
            super().__init__(stream_id)
            buffers.append(self)
    monkeypatch.setattr(media_routes, "MicrophoneBuffer", ObservedBuffer)
    monkeypatch.setattr(media_routes, "_send_transcripts", sender)
    socket = Socket(container, token)
    state = await actor.snapshot()
    request = asyncio.create_task(media_routes.microphone(socket, state.session_id))
    await socket.ready.wait()
    await stt.started.wait()
    await sender.started.wait()
    buffer = buffers[0]
    # The provider deliberately leaves this queued; cancellation must erase it.
    buffer.push(sequence=1, first_sample=0, pcm=b"\0\0" * 320)
    operation, = actor._media_operations
    return container, actor, operation, buffer, socket, request, sender, stt


async def finish_fixture(container, request, sender):
    sender.release.set()
    if not request.done():
        request.cancel()
    await asyncio.gather(request, return_exceptions=True)
    await container.close()
    if sender.task is not None:
        await asyncio.gather(sender.task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["disconnect", "cancel", "outer_cancel"])
async def test_microphone_invalidates_before_suspended_child_cleanup(monkeypatch, trigger):
    parts = await entered_request(monkeypatch)
    container, actor, operation, buffer, socket, request, sender, stt = parts
    try:
        if trigger == "disconnect":
            socket.incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})
        elif trigger == "cancel":
            socket.put({"type": "cancel"})
        else:
            request.cancel()
        async with asyncio.timeout(1):
            await sender.cleaning.wait()
        assert operation.cancelled.is_set(), "Provider invalidation must precede child cleanup."
        assert buffer.finished and buffer._queue.empty(), "Raw PCM must clear before any cleanup await."
        expected = CancellationReason.USER_STOP if trigger == "cancel" else CancellationReason.DISCONNECT
        assert operation._cancel_reason == expected
        with pytest.raises(DomainError, match="cancelled"):
            await anext(operation.values())
    finally:
        await finish_fixture(container, request, sender)


@pytest.mark.asyncio
async def test_request_cancel_during_child_cleanup_still_reaps_provider(monkeypatch):
    parts = await entered_request(monkeypatch)
    container, actor, operation, buffer, socket, request, sender, stt = parts
    try:
        socket.incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await sender.cleaning.wait()
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        assert operation.cancelled.is_set(), "Cancelling the cleanup await must not skip provider revocation."
        assert buffer._queue.empty()
        async with asyncio.timeout(1):
            await stt.closed.wait()
        assert operation.task.done()
    finally:
        await finish_fixture(container, request, sender)


class ResistantIterator:
    """A provider that continues after cancellation and holds aclose open."""
    def __init__(self):
        self.started = asyncio.Event()
        self.cancel_seen = asyncio.Event()
        self.release_value = asyncio.Event()
        self.closing = asyncio.Event()
        self.release_close = asyncio.Event()
        self.close_calls = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        from mira.application.ports.media import TranscriptRevision
        self.started.set()
        try:
            await self.release_value.wait()
        except asyncio.CancelledError:
            self.cancel_seen.set()
            await self.release_value.wait()
        return TranscriptRevision("late", 1, "must never revive", True)

    async def aclose(self):
        self.close_calls += 1
        self.closing.set()
        await self.release_close.wait()


class ResistantStt:
    def __init__(self):
        self.streams = []

    def transcribe(self, packets):
        stream = ResistantIterator()
        self.streams.append(stream)
        return stream


async def wait_reaped(actor):
    async with asyncio.timeout(1):
        while actor._media_operations:
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_repeated_outer_cancel_owns_socket_cleanup_until_it_exits(monkeypatch):
    parts = await entered_request(monkeypatch)
    container, actor, operation, buffer, socket, request, sender, stt = parts
    try:
        request.cancel()
        await sender.cleaning.wait()
        # The second cancellation interrupts the bounded wait, not its children.
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        assert request.cancelled() and request.cancelling() == 2
        assert operation.cancelled.is_set() and buffer._queue.empty()
        assert not sender.task.done(), "Outer cancellation must not cut through child cleanup."
        assert operation in actor._media_operations, "A pending child still consumes media capacity."
        assert operation._cancel_reason == CancellationReason.DISCONNECT
        sender.release.set()
        await asyncio.gather(sender.task, return_exceptions=True)
        await wait_reaped(actor)
    finally:
        await finish_fixture(container, request, sender)


@pytest.mark.asyncio
async def test_resistant_providers_hold_capacity_until_actual_iterator_close():
    stt = ResistantStt()
    container = build_container(Settings(), speech_recognition=stt)
    actor, _ = container.sessions.create(str(uuid4()))
    operations = []
    try:
        for index in range(4):
            buffer = MicrophoneBuffer(str(uuid4()))
            buffer.push(sequence=1, first_sample=0, pcm=b"\0\0" * 320)
            operation = await actor.open_microphone(stream_id=buffer.stream_id,
                activity_seq=0, input_epoch=0, buffer=buffer)
            operations.append(operation)
            # Event needs the producer's source to be entered first.
            async with asyncio.timeout(1):
                while len(stt.streams) <= index:
                    await asyncio.sleep(0)
                await stt.streams[index].started.wait()
            # Includes the actual 0.25s bounded cleanup; no widened test wait.
            await actor.close_media(operation, CancellationReason.DISCONNECT)
            assert operation in actor._media_operations
            assert buffer.finished and buffer._queue.empty()
            assert operation._queue.empty()
            assert operation._cancel_reason == CancellationReason.DISCONNECT
        extra = MicrophoneBuffer(str(uuid4()))
        with pytest.raises(DomainError, match="terminating"):
            await actor.open_microphone(stream_id=extra.stream_id,
                activity_seq=0, input_epoch=0, buffer=extra)
        for stream in stt.streams:
            stream.release_value.set()
            await stream.closing.wait()
        assert len(actor._media_operations) == 4, "aclose is still running."
        for operation in operations:
            with pytest.raises(DomainError, match="cancelled"):
                await anext(operation.values())
            assert operation._queue.empty(), "Late provider output must be discarded."
            # Repeated close must not cancel/skip the in-progress iterator aclose.
            await actor.close_media(operation, CancellationReason.USER_STOP)
            assert operation._cancel_reason == CancellationReason.DISCONNECT
        assert all(stream.close_calls == 1 for stream in stt.streams)
        assert len(actor._media_operations) == 4
        for stream in stt.streams:
            stream.release_close.set()
        await wait_reaped(actor)
        assert all(operation.task.done() and operation.done.is_set() for operation in operations)
        replacement = await actor.open_microphone(stream_id=extra.stream_id,
            activity_seq=0, input_epoch=0, buffer=extra)
        await actor.close_media(replacement)
    finally:
        for stream in stt.streams:
            stream.release_value.set()
            stream.release_close.set()
        await container.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["stop", "session_close"])
async def test_actor_revocation_clears_input_before_any_await(trigger):
    stt = WaitingStt()
    container = build_container(Settings(), speech_recognition=stt)
    actor, _ = container.sessions.create(str(uuid4()))
    buffer = MicrophoneBuffer(str(uuid4()))
    buffer.push(sequence=1, first_sample=0, pcm=b"\0\0" * 320)
    operation = await actor.open_microphone(stream_id=buffer.stream_id,
        activity_seq=0, input_epoch=0, buffer=buffer)
    await stt.started.wait()
    try:
        if trigger == "stop":
            await actor.stop(activity_seq=1, cutoff=0)
            assert operation._cancel_reason == CancellationReason.USER_STOP
        else:
            await actor.close()
            assert operation._cancel_reason == CancellationReason.SESSION_CLOSED
        assert operation.cancelled.is_set() and buffer.finished and buffer._queue.empty()
        await actor.close_media(operation, CancellationReason.DISCONNECT)
        await wait_reaped(actor)
        if trigger == "session_close":
            with pytest.raises(DomainError, match="closed"):
                await actor.open_microphone(stream_id=str(uuid4()), activity_seq=0,
                    input_epoch=0, buffer=MicrophoneBuffer(str(uuid4())))
    finally:
        await container.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["finish", "disconnect", "cancel", "outer_cancel"])
async def test_final_drain_keeps_reader_alive_and_never_revives(trigger):
    from mira.application.ports.media import TranscriptRevision
    class DrainStt:
        def __init__(self):
            self.draining = asyncio.Event()
            self.release = asyncio.Event()
            self.closed = asyncio.Event()
            self.received = []
        async def transcribe(self, packets):
            try:
                async for packet in packets:
                    self.received.append(packet)
                self.draining.set()
                await self.release.wait()
                yield TranscriptRevision(self.received[0].stream_id, 1, "final text", True)
            finally:
                self.closed.set()
    stt = DrainStt()
    container = build_container(Settings(), speech_recognition=stt)
    actor, token = container.sessions.create(str(uuid4()))
    state = await actor.snapshot()
    socket = Socket(container, token)
    request = asyncio.create_task(media_routes.microphone(socket, state.session_id))
    try:
        await socket.ready.wait()
        operation, = actor._media_operations
        socket.put({"type": "audio", "sequence": 1, "first_sample": 0, "pcm_base64": "AAA="})
        socket.put({"type": "finish"})
        await stt.draining.wait()
        assert not operation.cancelled.is_set() and len(stt.received) == 1
        if trigger == "finish":
            stt.release.set()
        elif trigger == "disconnect":
            socket.incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})
        elif trigger == "cancel":
            socket.put({"type": "cancel"})
        else:
            request.cancel()
        async with asyncio.timeout(1):
            await asyncio.gather(request, return_exceptions=True)
            await stt.closed.wait()
        await wait_reaped(actor)
        if trigger == "finish":
            assert [frame["type"] for frame in socket.frames] == ["ready", "transcript", "complete"]
            assert socket.frames[-1]["had_final"] is True
        else:
            assert all(frame["type"] not in {"transcript", "complete"} for frame in socket.frames)
        assert await actor.snapshot() == state, "Transcripts must not mint a user turn."
    finally:
        stt.release.set()
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        await container.close()


@pytest.mark.asyncio
async def test_cancelled_session_shutdown_keeps_provider_registered_until_reaped():
    stt = ResistantStt()
    container = build_container(Settings(), speech_recognition=stt)
    actor, _ = container.sessions.create(str(uuid4()))
    buffer = MicrophoneBuffer(str(uuid4()))
    buffer.push(sequence=1, first_sample=0, pcm=b"\0\0" * 320)
    operation = await actor.open_microphone(stream_id=buffer.stream_id,
        activity_seq=0, input_epoch=0, buffer=buffer)
    generation_started, generation_cleaning, release_generation = (
        asyncio.Event(), asyncio.Event(), asyncio.Event())
    async def generation_cleanup():
        generation_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            generation_cleaning.set()
            await release_generation.wait()
    # A held existing generation task makes Actor.close suspend before its media wait.
    generation = asyncio.create_task(generation_cleanup())
    actor._tasks.add(generation)
    generation.add_done_callback(actor._tasks.discard)
    await generation_started.wait()
    await stt.streams[0].started.wait()
    close_request = asyncio.create_task(actor.close())
    try:
        await generation_cleaning.wait()
        assert operation.cancelled.is_set() and buffer._queue.empty()
        close_request.cancel()
        await asyncio.sleep(0)  # Deliver first cancellation at the generation wait.
        close_request.cancel()  # Interrupt the subsequent bounded media wait too.
        async with asyncio.timeout(1):
            await asyncio.gather(close_request, return_exceptions=True)
        assert close_request.cancelled()
        assert operation in actor._media_operations
        assert operation._cancel_reason == CancellationReason.SESSION_CLOSED
        stream = stt.streams[0]
        stream.release_value.set()
        await stream.closing.wait()
        assert operation in actor._media_operations
        stream.release_close.set()
        await wait_reaped(actor)
        assert operation._queue.empty()
    finally:
        release_generation.set()
        for stream in stt.streams:
            stream.release_value.set()
            stream.release_close.set()
        close_request.cancel()
        await asyncio.gather(close_request, generation, return_exceptions=True)
        await container.close()
