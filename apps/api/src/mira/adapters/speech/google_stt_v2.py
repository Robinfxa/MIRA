"""STT V2 streaming adapter. Authentication/client construction belong to bootstrap.

Input is headerless mono PCM16 little-endian. No retries or model/region fallback.
The caller supplies real-time pacing and closes the async generator on early exit.
"""
import re
import sys
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from mira.adapters.speech.errors import (
    SpeechProviderError, close_stream, raise_if_cancelled, safe_error,
)
from mira.application.ports.media import AudioPacket, TranscriptRevision


@dataclass(frozen=True, slots=True)
class SttOptions:
    project_id: str
    location: str = "us"
    model: str = "chirp_3"
    language_code: str = "cmn-Hans-CN"
    timeout_seconds: float = 300
    max_stream_seconds: float = 290
    max_chunk_bytes: int = 12000

    def __post_init__(self):
        for value in (self.project_id, self.location, self.model, self.language_code):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}", value):
                raise ValueError("Invalid STT identifier")
        if not 0 < self.max_stream_seconds < 300 or not 0 < self.timeout_seconds <= 310:
            raise ValueError("STT requires a bounded stream duration and deadline")
        if not 2 <= self.max_chunk_bytes <= 15000 or self.max_chunk_bytes % 2:
            raise ValueError("STT chunks must be sample-aligned and at most 15000 bytes")

    @property
    def endpoint(self) -> str:
        return "speech.googleapis.com" if self.location == "global" else f"{self.location}-speech.googleapis.com"

    @property
    def recognizer(self) -> str:
        return f"projects/{self.project_id}/locations/{self.location}/recognizers/_"


@dataclass(frozen=True, slots=True)
class SttResult:
    transcript: str
    is_final: bool


@dataclass(frozen=True, slots=True)
class SttResponse:
    results: tuple[SttResult, ...]


class SttTransport(Protocol):
    def stream(self, requests: AsyncIterator[dict[str, Any]], *, timeout_seconds: float
               ) -> AsyncGenerator[SttResponse, None]: ...


class GoogleSpeechV2Backend:
    def __init__(self, options: SttOptions, transport: SttTransport):
        self.options, self.transport = options, transport

    async def transcribe(self, packets: AsyncIterator[AudioPacket]) -> AsyncGenerator[TranscriptRevision, None]:
        # Peek locally before opening a billable stream and bind one stream/rate.
        source = aiter(packets)
        requests = stream = None
        committed, revision = "", 0
        pending_interim = False
        try:
            try:
                first = await anext(source)
            except StopAsyncIteration:
                return
            if not isinstance(first, AudioPacket):
                raise SpeechProviderError("invalid_input")
            self._validate_packet(first, first.stream_id, first.sample_rate_hz, first.first_sample)
            requests = self._requests(first, source)
            stream = self.transport.stream(requests, timeout_seconds=self.options.timeout_seconds)
            async for response in stream:
                raise_if_cancelled()
                if not isinstance(response, SttResponse):
                    raise SpeechProviderError("invalid_response")
                if not response.results:
                    continue
                interim = []
                seen_interim = False
                for result in response.results:
                    if (not isinstance(result, SttResult) or not isinstance(result.transcript, str)
                            or type(result.is_final) is not bool):
                        raise SpeechProviderError("invalid_response")
                    if result.is_final:
                        if seen_interim:
                            raise SpeechProviderError("invalid_response")
                        committed += result.transcript
                    else:
                        seen_interim = True
                        interim.append(result.transcript)
                pending_interim = seen_interim
                revision += 1
                yield TranscriptRevision(first.stream_id, revision, committed + "".join(interim),
                                         not seen_interim)
            if pending_interim:
                raise SpeechProviderError("incomplete_stream")
        except Exception as error:
            raise safe_error(error) from None
        finally:
            preserve = sys.exc_info()[0] is not None
            for resource in (stream, requests, source):
                await close_stream(resource, preserve_error=preserve)

    @staticmethod
    def _validate_packet(packet: AudioPacket, stream_id: str, rate: int, expected: int) -> None:
        if (not isinstance(packet, AudioPacket) or not isinstance(packet.stream_id, str)
                or not packet.stream_id or packet.stream_id != stream_id
                or type(packet.first_sample) is not int or packet.first_sample < 0
                or packet.first_sample != expected or type(packet.sample_rate_hz) is not int
                or packet.sample_rate_hz != rate or not 8000 <= rate <= 48000
                or not isinstance(packet.pcm, bytes) or not packet.pcm or len(packet.pcm) % 2):
            raise SpeechProviderError("invalid_input")

    async def _requests(self, first: AudioPacket, source: AsyncIterator[AudioPacket]
                        ) -> AsyncGenerator[dict[str, Any], None]:
        raise_if_cancelled()
        yield {"recognizer": self.options.recognizer, "streaming_config": {
            "config": {"explicit_decoding_config": {"encoding": "LINEAR16",
                "sample_rate_hertz": first.sample_rate_hz, "audio_channel_count": 1},
                "language_codes": [self.options.language_code], "model": self.options.model},
            "streaming_features": {"interim_results": True}}}
        packet, expected, samples = first, first.first_sample, 0
        while True:
            self._validate_packet(packet, first.stream_id, first.sample_rate_hz, expected)
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


class GoogleSpeechV2GrpcTransport:
    """Bridge to an injected SpeechAsyncClient and StreamingRecognizeRequest factory.

    Bootstrap supplies a credential-bound client with the options.endpoint; it must
    not use ADC discovery here. For example request_factory=cloud_speech.StreamingRecognizeRequest.
    The bridge never closes a shared client, only its per-call RPC.
    """
    def __init__(self, client: Any, *, request_factory: Callable[..., Any]):
        self._client, self._request_factory = client, request_factory

    async def stream(self, requests: AsyncIterator[dict[str, Any]], *, timeout_seconds: float
                     ) -> AsyncGenerator[SttResponse, None]:
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
                results = []
                for result in response.results:
                    if not result.alternatives:
                        raise SpeechProviderError("invalid_response")
                    results.append(SttResult(result.alternatives[0].transcript, result.is_final))
                yield SttResponse(tuple(results))
        except Exception as error:
            raise safe_error(error) from None
        finally:
            if rpc is not None:
                rpc.cancel()
            await close_stream(outgoing, preserve_error=sys.exc_info()[0] is not None)
