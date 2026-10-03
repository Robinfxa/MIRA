"""Offline streamed-part behavior; no credentials or provider calls."""
import asyncio
import base64

import pytest

from mira.adapters.speech.errors import SpeechProviderError
from mira.adapters.speech.google_gemini_tts import GeminiTtsOptions, GoogleGeminiTtsBackend


def chunk(parts, finish=None):
    candidate = {"content": {"parts": parts}}
    if finish is not None:
        candidate["finishReason"] = finish
    return {"candidates": [candidate]}


def pcm_part():
    return {"inlineData": {"mimeType": "audio/l16;rate=24000;channels=1",
                           "data": base64.b64encode(b"\x01\x00\x02\x00").decode()}}


class Stream:
    def __init__(self, events):
        self.events = events
        self.closed = False
        self.waiting = asyncio.Event()

    async def stream(self, **_):
        try:
            for event in self.events:
                if event == "WAIT":
                    self.waiting.set()
                    await asyncio.Future()
                if isinstance(event, Exception):
                    raise event
                yield event
        finally:
            self.closed = True


def backend(stream):
    return GoogleGeminiTtsBackend(GeminiTtsOptions(project_id="synthetic-project", voice="Kore"), stream)


@pytest.mark.asyncio
@pytest.mark.parametrize("events", [
    [chunk([{"text": "non-audio metadata"}]), chunk([pcm_part()], "STOP")],
    [chunk([{"text": "non-audio metadata"}, pcm_part()], "STOP")],
    [chunk([pcm_part()], "STOP"), chunk([{"text": "post-terminal metadata"}])],
])
async def test_non_inline_parts_do_not_terminate_or_become_audio(events):
    stream = Stream(events)
    packets = [packet async for packet in backend(stream).synthesize("合成测试", "stream")]
    assert len(packets) == 1
    assert packets[0].pcm == b"\x01\x00\x02\x00"
    assert packets[0].first_sample == 0
    assert stream.closed


@pytest.mark.asyncio
async def test_text_only_completed_stream_reports_empty_audio_after_exhaustion():
    stream = Stream([chunk([{"text": "NEVER-RETAIN-THIS"}], "STOP")])
    with pytest.raises(SpeechProviderError) as caught:
        _ = [packet async for packet in backend(stream).synthesize("合成测试", "stream")]
    assert caught.value.code == "empty_audio"
    assert caught.value.audio_details.validation_reason == "non_audio_part"
    assert caught.value.audio_details.candidate_finish_reason == "STOP"
    assert "NEVER-RETAIN-THIS" not in repr(caught.value.audio_details)
    assert stream.closed


@pytest.mark.asyncio
async def test_stop_on_text_never_allows_later_audio():
    stream = Stream([chunk([{"text": "finished"}], "STOP"), chunk([pcm_part()])])
    with pytest.raises(SpeechProviderError) as caught:
        _ = [packet async for packet in backend(stream).synthesize("合成测试", "stream")]
    assert caught.value.code == "invalid_response"
    assert stream.closed


@pytest.mark.asyncio
async def test_present_malformed_inline_data_is_not_silently_skipped():
    stream = Stream([chunk([{"inlineData": None}], "STOP")])
    with pytest.raises(SpeechProviderError) as caught:
        _ = [packet async for packet in backend(stream).synthesize("合成测试", "stream")]
    assert caught.value.code == "invalid_response"
    assert stream.closed


@pytest.mark.asyncio
async def test_text_then_audio_without_finish_still_fails_incomplete():
    stream = Stream([chunk([{"text": "metadata"}]), chunk([pcm_part()])])
    with pytest.raises(SpeechProviderError) as caught:
        _ = [packet async for packet in backend(stream).synthesize("合成测试", "stream")]
    assert caught.value.code == "incomplete_stream"
    assert stream.closed


@pytest.mark.asyncio
async def test_timeout_after_non_audio_keeps_only_safe_observed_part_facts():
    stream = Stream([chunk([{"text": "SECRET-SYNTHETIC"}]), TimeoutError("private upstream text")])
    with pytest.raises(SpeechProviderError) as caught:
        _ = [packet async for packet in backend(stream).synthesize("合成测试", "stream")]
    assert caught.value.code == "timeout"
    assert caught.value.audio_details.validation_reason == "non_audio_part"
    assert "SECRET-SYNTHETIC" not in repr(caught.value.audio_details)
    assert "private upstream" not in str(caught.value)
    assert stream.closed


@pytest.mark.asyncio
async def test_cancel_while_waiting_after_text_reaps_without_audio():
    stream = Stream([chunk([{"text": "metadata"}]), "WAIT", chunk([pcm_part()], "STOP")])
    generator = backend(stream).synthesize("合成测试", "stream")
    pending = asyncio.create_task(anext(generator))
    try:
        await asyncio.wait_for(stream.waiting.wait(), 0.1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await generator.aclose()
    assert stream.closed
