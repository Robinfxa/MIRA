"""PTT PCM pacing and delayed STT consumption; synthetic frames and no network."""
import asyncio

import pytest

from mira.adapters.speech.google_stt_v2 import (
    GoogleSpeechV2Backend, SttOptions, SttResponse, SttResult,
)
from mira.application.media_runtime import MicrophoneBuffer
from mira.domain.errors import DomainError


@pytest.mark.asyncio
async def test_twenty_ms_audio_survives_one_second_google_startup_without_frame_loss():
    entered, release = asyncio.Event(), asyncio.Event()
    received = []
    class DelayedGoogleTransport:
        async def stream(self, requests, *, timeout_seconds):
            entered.set()
            await release.wait()
            received.extend([request async for request in requests])
            yield SttResponse((SttResult('synthetic final', True),))
    backend = GoogleSpeechV2Backend(SttOptions(project_id='synthetic-project'), DelayedGoogleTransport())
    buffer = MicrophoneBuffer('synthetic-stream')
    frames = [index.to_bytes(2, 'little') * 320 for index in range(51)]
    async def collect():
        return [revision async for revision in backend.transcribe(buffer.packets())]
    task = asyncio.create_task(collect())
    try:
        buffer.push(sequence=1, first_sample=0, pcm=frames[0])
        async with asyncio.timeout(2):
            await entered.wait()  # Backend peeked first audio; RPC is now held.
        for index in range(1, 51):
            # A timed PCM input is the behavior under test, not a guessed race.
            await asyncio.sleep(.02)  # Browser AudioWorklet's default 20ms cadence.
            buffer.push(sequence=index + 1, first_sample=index * 320, pcm=frames[index])
        await buffer.finish()
        release.set()
        async with asyncio.timeout(2):
            result = await task
        assert result[-1].text == 'synthetic final' and result[-1].is_final
        assert b''.join(request['audio'] for request in received if 'audio' in request) == b''.join(frames)
    finally:
        release.set()
        buffer.clear()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_buffer_capacity_tracks_pcm_duration_and_releases_when_consumed():
    buffer = MicrophoneBuffer('synthetic-stream')
    buffer._started -= 3  # Establish valid pacing without waiting for a capacity test.
    for index in range(100):
        buffer.push(sequence=index + 1, first_sample=index * 320, pcm=b'\0\0' * 320)
    with pytest.raises(DomainError, match='buffer is full'):
        buffer.push(sequence=101, first_sample=32000, pcm=b'\0\0')
    source = buffer.packets()
    assert (await anext(source)).first_sample == 0
    buffer.push(sequence=101, first_sample=32000, pcm=b'\0\0' * 320)
    await buffer.finish()
    remaining = [packet async for packet in source]
    assert len(remaining) == 100
    assert [packet.first_sample for packet in remaining] == list(range(320, 32320, 320))
    assert sum(len(packet.pcm) // 2 for packet in remaining) == 32000


@pytest.mark.asyncio
async def test_buffer_has_independent_packet_bound_and_cancel_discards_immediately():
    buffer = MicrophoneBuffer('synthetic-stream')
    buffer._started -= 3
    for index in range(200):
        buffer.push(sequence=index + 1, first_sample=index, pcm=b'\0\0')
    with pytest.raises(DomainError, match='buffer is full'):
        buffer.push(sequence=201, first_sample=200, pcm=b'\0\0')
    buffer.clear()
    assert [packet async for packet in buffer.packets()] == []
    assert buffer.finished


@pytest.mark.asyncio
async def test_large_valid_packets_cannot_expand_duration_bound():
    buffer = MicrophoneBuffer('synthetic-stream')
    buffer._started -= 3
    for index in range(5):
        buffer.push(sequence=index + 1, first_sample=index * 6000, pcm=b'\0\0' * 6000)
    with pytest.raises(DomainError, match='buffer is full'):
        buffer.push(sequence=6, first_sample=30000, pcm=b'\0\0' * 6000)
    buffer.clear()
