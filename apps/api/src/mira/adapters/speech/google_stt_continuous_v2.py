"""Google Speech V2 continuous-only stream with VAD and audio-result offsets.

Ordinary push-to-talk uses `google_stt_v2.GoogleSpeechV2Backend` unchanged. This
adapter opens exactly one streaming RPC for an audio lease, preserves server VAD
boundaries and final-result offsets, and deliberately does not set voice-activity
timeouts (silence is not a reason to close the continuous lease).
"""
from __future__ import annotations

import sys
from datetime import timedelta
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from typing import Any, Protocol

from mira.adapters.speech.errors import SpeechProviderError, close_stream, raise_if_cancelled, safe_error
from mira.adapters.speech.google_stt_v2 import SttOptions
from mira.application.ports.continuous_speech import (
    ContinuousRecognitionEvent, ContinuousSpeechActivity, ContinuousSpeechRecognitionBackend,
    ContinuousTranscriptResult,
)
from mira.application.ports.media import AudioPacket


class ContinuousSttTransport(Protocol):
    def stream(self, requests: AsyncIterator[dict[str, Any]], *, timeout_seconds: float
               ) -> AsyncGenerator[ContinuousRecognitionEvent, None]: ...


class GoogleSpeechV2ContinuousBackend(ContinuousSpeechRecognitionBackend):
    endpoint_mode = "google_vad_offsets"

    def __init__(self, options: SttOptions, transport: ContinuousSttTransport):
        self.options, self.transport = options, transport
        self.max_stream_seconds = options.max_stream_seconds

    def transcribe_events(self, packets: AsyncIterator[AudioPacket]
                          ) -> AsyncGenerator[ContinuousRecognitionEvent, None]:
        return self._transcribe_events(packets)

    async def _transcribe_events(self, packets: AsyncIterator[AudioPacket]
                                 ) -> AsyncGenerator[ContinuousRecognitionEvent, None]:
        source = aiter(packets)
        requests = stream = None
        try:
            try:
                first = await anext(source)
            except StopAsyncIteration:
                return
            if (not isinstance(first, AudioPacket) or first.sample_rate_hz != 16_000
                    or first.first_sample != 0):
                raise SpeechProviderError("invalid_input")
            self._validate_packet(first, first.stream_id, first.first_sample)
            requests = self._requests(first, source)
            stream = self.transport.stream(requests, timeout_seconds=self.options.timeout_seconds)
            async for event in stream:
                raise_if_cancelled()
                if not isinstance(event, (ContinuousTranscriptResult, ContinuousSpeechActivity)):
                    raise SpeechProviderError("invalid_response")
                yield event
        except Exception as error:
            raise safe_error(error) from None
        finally:
            preserve = sys.exc_info()[0] is not None
            for resource in (stream, requests, source):
                await close_stream(resource, preserve_error=preserve)

    def _validate_packet(self, packet: AudioPacket, stream_id: str, expected: int) -> None:
        if (not isinstance(packet, AudioPacket) or not isinstance(packet.stream_id, str)
                or not packet.stream_id or packet.stream_id != stream_id
                or type(packet.first_sample) is not int or packet.first_sample < 0
                or packet.first_sample != expected or type(packet.sample_rate_hz) is not int
                or packet.sample_rate_hz != 16_000 or not isinstance(packet.pcm, bytes)
                or not packet.pcm or len(packet.pcm) % 2
                or len(packet.pcm) > 2 * 1024 * 1024
                or (expected == 0 and packet.pcm[:4] == b"RIFF" and packet.pcm[8:12] == b"WAVE")):
            raise SpeechProviderError("invalid_input")

    async def _requests(self, first: AudioPacket, source: AsyncIterator[AudioPacket]
                        ) -> AsyncGenerator[dict[str, Any], None]:
        raise_if_cancelled()
        yield {"recognizer": self.options.recognizer, "streaming_config": {
            "config": {"explicit_decoding_config": {"encoding": "LINEAR16",
                "sample_rate_hertz": first.sample_rate_hz, "audio_channel_count": 1},
                "language_codes": [self.options.language_code], "model": self.options.model},
            "streaming_features": {"interim_results": True,
                                   "enable_voice_activity_events": True}}}
        packet, expected, samples = first, first.first_sample, 0
        while True:
            self._validate_packet(packet, first.stream_id, expected)
            sample_count = len(packet.pcm) // 2
            samples += sample_count
            if samples > self.options.max_stream_seconds * first.sample_rate_hz:
                raise SpeechProviderError("input_limit")
            for offset in range(0, len(packet.pcm), self.options.max_chunk_bytes):
                raise_if_cancelled()
                yield {"audio": packet.pcm[offset:offset + self.options.max_chunk_bytes]}
            expected += sample_count
            try:
                packet = await anext(source)
            except StopAsyncIteration:
                return


class GoogleSpeechV2GrpcContinuousTransport:
    """Bridge a previously injected SpeechAsyncClient; never performs auth discovery."""
    def __init__(self, client: Any, *, request_factory: Callable[..., Any], response_event_type,
                 sample_rate_hz: int = 16_000):
        if type(sample_rate_hz) is not int or sample_rate_hz != 16_000:
            raise ValueError("continuous_stt_requires_16khz")
        self._client, self._request_factory = client, request_factory
        self._event_enum = response_event_type
        self._sample_rate_hz = sample_rate_hz

    async def stream(self, requests: AsyncIterator[dict[str, Any]], *, timeout_seconds: float
                     ) -> AsyncGenerator[ContinuousRecognitionEvent, None]:
        async def encoded():
            async for request in requests:
                raise_if_cancelled()
                yield self._request_factory(**request)

        outgoing = encoded()
        rpc = None
        try:
            rpc = await self._client.streaming_recognize(requests=outgoing,
                                                         timeout=timeout_seconds, retry=None)
            async for response in rpc:
                raise_if_cancelled()
                event_name = self._enum_name(response.speech_event_type)
                if response.results:
                    if event_name not in ("SPEECH_EVENT_TYPE_UNSPECIFIED", ""):
                        raise SpeechProviderError("invalid_response")
                    results = tuple(response.results)
                    # Google specifies zero or one newly final portion, followed by
                    # consecutive interim portions. Validate the complete SDK batch
                    # before exposing a final that could authorize a natural turn.
                    if any(result.is_final for result in results[1:]):
                        raise SpeechProviderError("invalid_response")
                    mapped = []
                    has_interim = any(not result.is_final for result in results)
                    for index, result in enumerate(results):
                        if not result.alternatives:
                            raise SpeechProviderError("invalid_response")
                        mapped.append(ContinuousTranscriptResult(
                            text=result.alternatives[0].transcript,
                            is_final=result.is_final,
                            result_end_offset_samples=self._field_samples(
                                result, "result_end_offset", self._sample_rate_hz),
                            provider_batch_complete=index == len(results) - 1,
                            has_pending_interim=has_interim,
                        ))
                    if mapped[0].is_final:
                        yield mapped.pop(0)
                    if mapped:
                        # Multiple interim results are consecutive portions of one
                        # hypothesis, not replacements for each other.
                        yield ContinuousTranscriptResult(
                            "".join(item.text for item in mapped), False,
                            mapped[-1].result_end_offset_samples,
                            provider_batch_complete=True, has_pending_interim=True)
                elif event_name in ("SPEECH_ACTIVITY_BEGIN", "SPEECH_ACTIVITY_END"):
                    yield ContinuousSpeechActivity(
                        "begin" if event_name == "SPEECH_ACTIVITY_BEGIN" else "end",
                        self._field_samples(response, "speech_event_offset", self._sample_rate_hz,
                                            required=True),
                    )
                elif event_name not in ("SPEECH_EVENT_TYPE_UNSPECIFIED", ""):
                    # END_OF_SINGLE_UTTERANCE closes a stream and is intentionally unsupported.
                    raise SpeechProviderError("invalid_response")
        except Exception as error:
            raise safe_error(error) from None
        finally:
            preserve = sys.exc_info()[0] is not None
            for resource in (rpc, outgoing, requests):
                await close_stream(resource, preserve_error=preserve)

    def _enum_name(self, value: Any) -> str:
        if value is None:
            return ""
        name = getattr(value, "name", None)
        if isinstance(name, str):
            return name
        try:
            return self._event_enum(value).name
        except Exception:
            return "unknown"

    @classmethod
    def _field_samples(cls, owner: Any, field_name: str, sample_rate_hz: int,
                       *, required: bool = False) -> int | None:
        duration = getattr(owner, field_name, None)
        proto = getattr(owner, "_pb", None)
        has_field = None
        if proto is not None:
            try:
                has_field = proto.HasField(field_name)
            except (AttributeError, ValueError):
                has_field = None
        if has_field is False or duration is None:
            if required:
                raise SpeechProviderError("invalid_response")
            return None
        return cls._duration_samples(duration, sample_rate_hz, required=required)

    @staticmethod
    def _duration_samples(duration: Any, sample_rate_hz: int, *, required: bool = False) -> int | None:
        if duration is None:
            if required:
                raise SpeechProviderError("invalid_response")
            return None
        if isinstance(duration, timedelta):
            # Proto-plus maps protobuf Duration to datetime.timedelta at microsecond
            # resolution. Convert with integer arithmetic only; never round through float.
            total_microseconds = ((duration.days * 86_400 + duration.seconds) * 1_000_000
                                  + duration.microseconds)
            if total_microseconds < 0:
                raise SpeechProviderError("invalid_response")
            return total_microseconds * sample_rate_hz // 1_000_000
        seconds = getattr(duration, "seconds", None)
        nanos = getattr(duration, "nanos", None)
        if (type(seconds) is not int or type(nanos) is not int or seconds < 0
                or not 0 <= nanos < 1_000_000_000):
            raise SpeechProviderError("invalid_response")
        return seconds * sample_rate_hz + nanos * sample_rate_hz // 1_000_000_000
