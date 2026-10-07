"""Continuous PCM startup and finite memory, using real adapters and fake RPCs."""
import asyncio
from types import SimpleNamespace

import pytest

from mira.adapters.speech.google_stt_continuous_v2 import (
    GoogleSpeechV2ContinuousBackend, GoogleSpeechV2GrpcContinuousTransport,
)
from mira.adapters.speech.google_stt_v2 import (
    GoogleSpeechV2Backend, GoogleSpeechV2GrpcTransport, SttOptions,
)
from mira.application.continuous_listening import ListeningAudioBuffer, ListeningLimits
from mira.domain.errors import DomainError


def push(buffer, sequence, first_sample, pcm):
    buffer.push(lease_id=buffer.lease_id, sequence=sequence,
                first_sample=first_sample, pcm=pcm)


@pytest.mark.asyncio
@pytest.mark.parametrize("continuous", [True, False], ids=["continuous", "ordinary-google"])
async def test_twenty_ms_audio_survives_one_second_google_rpc_startup(continuous):
    entered, release = asyncio.Event(), asyncio.Event()
    received, calls = [], []

    class FakeRpc:
        closed = False

        def __aiter__(self):
            async def responses():
                yield SimpleNamespace(results=[SimpleNamespace(
                    alternatives=[SimpleNamespace(transcript="synthetic final")],
                    is_final=True, result_end_offset=None)], speech_event_type=None)
            return responses()

        def cancel(self):
            self.closed = True

        async def aclose(self):
            self.closed = True

    rpc = FakeRpc()

    class DelayedClient:
        async def streaming_recognize(self, *, requests, timeout, retry):
            calls.append((timeout, retry))
            entered.set()
            await release.wait()
            received.extend([request async for request in requests])
            return rpc

    if continuous:
        transport = GoogleSpeechV2GrpcContinuousTransport(DelayedClient(),
            request_factory=lambda **kwargs: kwargs, response_event_type=None)
        backend = GoogleSpeechV2ContinuousBackend(SttOptions(project_id="synthetic"), transport)
    else:
        transport = GoogleSpeechV2GrpcTransport(DelayedClient(),
            request_factory=lambda **kwargs: kwargs)
        backend = GoogleSpeechV2Backend(SttOptions(project_id="synthetic"), transport)
    buffer = ListeningAudioBuffer("lease", limits=ListeningLimits())
    frames = [index.to_bytes(2, "little") * 320 for index in range(51)]

    async def collect():
        stream = (backend.transcribe_events(buffer.packets()) if continuous
                  else backend.transcribe(buffer.packets()))
        return [event async for event in stream]

    task = asyncio.create_task(collect())
    try:
        push(buffer, 1, 0, frames[0])
        async with asyncio.timeout(2):
            await entered.wait()
        for index in range(1, 51):
            # Timed input is the behavior being tested; Event establishes RPC state.
            await asyncio.sleep(.02)
            push(buffer, index + 1, index * 320, frames[index])
        buffer.finish()
        release.set()
        async with asyncio.timeout(2):
            result = await task
        assert result[-1].text == "synthetic final" and result[-1].is_final
        assert b"".join(request["audio"] for request in received if "audio" in request) == b"".join(frames)
        assert len(calls) == 1 and calls[0][1] is None
        assert rpc.closed
        assert buffer._queued_samples == 0
    finally:
        release.set()
        buffer.clear()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_two_second_capacity_returns_exactly_and_finish_drains_all_frames():
    buffer = ListeningAudioBuffer("lease", limits=ListeningLimits())
    buffer._started -= 3
    for index in range(100):
        push(buffer, index + 1, index * 320, bytes([index, 0]) * 320)
    assert buffer._queued_samples == 32_000
    with pytest.raises(DomainError, match="full"):
        push(buffer, 101, 32_000, b"\0\0")
    assert buffer.samples == 32_000
    source = buffer.packets()
    assert (await anext(source)).first_sample == 0
    assert buffer._queued_samples == 31_680
    with pytest.raises(DomainError, match="full"):
        push(buffer, 101, 32_000, b"\0\0" * 321)
    push(buffer, 101, 32_000, b"\0\0" * 320)
    buffer.finish()
    buffer.finish()
    remaining = [packet async for packet in source]
    assert [packet.first_sample for packet in remaining] == list(range(320, 32_320, 320))
    assert sum(len(packet.pcm) for packet in remaining) == 64_000
    assert buffer._queued_samples == 0


@pytest.mark.asyncio
async def test_packet_cap_cancel_clear_and_late_push_rejection():
    buffer = ListeningAudioBuffer("lease", limits=ListeningLimits())
    for index in range(200):
        push(buffer, index + 1, index, b"\0\0")
    with pytest.raises(DomainError, match="full"):
        push(buffer, 201, 200, b"\0\0")
    assert buffer._queue.qsize() == 200 and buffer._queued_samples == 200
    buffer.clear()
    buffer.clear()
    assert buffer._queue.empty() and buffer._queued_samples == 0
    assert [packet async for packet in buffer.packets()] == []
    with pytest.raises(DomainError, match="no longer active"):
        push(buffer, 201, 200, b"\0\0")


@pytest.mark.asyncio
async def test_large_frames_cannot_bypass_pending_pcm_bound():
    buffer = ListeningAudioBuffer("lease", limits=ListeningLimits())
    buffer._started -= 3
    for index in range(5):
        push(buffer, index + 1, index * 6000, b"\0\0" * 6000)
    with pytest.raises(DomainError, match="full"):
        push(buffer, 6, 30_000, b"\0\0" * 2001)
    push(buffer, 6, 30_000, b"\0\0" * 2000)
    assert buffer._queued_samples == 32_000
    buffer.clear()
    assert buffer._queued_samples == 0


@pytest.mark.asyncio
async def test_explicit_small_packet_capacity_still_drains_full_queue():
    buffer = ListeningAudioBuffer("lease", limits=ListeningLimits(queue_capacity=1))
    push(buffer, 1, 0, b"\0\0" * 80)
    with pytest.raises(DomainError, match="full"):
        push(buffer, 2, 80, b"\0\0")
    buffer.finish()
    assert [packet.first_sample async for packet in buffer.packets()] == [0]
    assert buffer._queued_samples == 0


@pytest.mark.parametrize("capacity", [0, 201, True, 1.5])
def test_packet_capacity_configuration_remains_finite(capacity):
    with pytest.raises(ValueError, match="continuous_listening_limits_invalid"):
        ListeningLimits(queue_capacity=capacity)
