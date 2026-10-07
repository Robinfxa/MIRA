"""Explicit one-lifespan, bounded composition for the development voice seam.

This module does not read configuration or discover credentials. Voice remains off
unless a caller explicitly constructs this factory and gives it to the existing
``create_development_app`` voice_factory seam. Limits are per returned provider
bundle; they are technical request/audio bounds, not a dollar-spend ledger or a
durable cross-process quota.
"""
from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from mira.adapters.speech.errors import SpeechProviderError, close_stream
from mira.application.ports.media import AudioPacket, TranscriptRevision
from mira.application.ports.continuous_speech import (
    ContinuousRecognitionEvent, ContinuousSpeechActivity, ContinuousTranscriptResult,
    ContinuousRecognitionStarted,
)
from mira.application.ports.request_budget import RequestBudgetSnapshot
from mira.bootstrap.providers import GoogleVoiceProviders, create_google_voice
from mira.config.loader import ConfigurationError
from mira.config.service_settings import SpeechSettings
from mira.bootstrap.development_usage import (
    UsageProfile, parse_usage_profile, validate_count, validate_duration,
)

_MAX_PCM_PACKET_BYTES = 2 * 1024 * 1024
_PCM_SAMPLE_RATE_HZ = 24000
_MAX_TTS_TEXT_CHARACTERS = 16000
_APPLICATION_TTS_VOICES = frozenset({"Kore", "Gacrux"})


@dataclass(frozen=True, slots=True)
class DevelopmentVoiceLimits:
    """Explicit per-app attempt and media ceilings; these do not represent dollars."""

    tts_request_limit: int
    stt_request_limit: int | None
    tts_max_audio_seconds: float
    stt_max_input_seconds: float
    usage_profile: UsageProfile | str = UsageProfile.PROBE

    def __post_init__(self) -> None:
        profile = parse_usage_profile(self.usage_profile)
        object.__setattr__(self, "usage_profile", profile)
        validate_count(self.tts_request_limit, profile, name="TTS request ceiling")
        if self.stt_request_limit is not None or profile is not UsageProfile.APPLICATION:
            validate_count(self.stt_request_limit, profile, name="STT request ceiling")
        for value, name, kind in (
                (self.tts_max_audio_seconds, "TTS audio", "tts"),
                (self.stt_max_input_seconds, "STT input", "stt")):
            validate_duration(value, profile, name=name, voice=kind)
            if int(value * _PCM_SAMPLE_RATE_HZ) < 1:
                raise ConfigurationError(f"{name} duration ceiling is below one PCM sample.")

    @property
    def tts_max_samples(self) -> int:
        return int(self.tts_max_audio_seconds * _PCM_SAMPLE_RATE_HZ)


class _AttemptBudget:
    """Atomic, irreversible reservation counter scoped to one app lifespan."""

    def __init__(self, limit: int | None, error_code: str) -> None:
        self._limit = limit
        self._error_code = error_code
        self._used = 0
        self._lock = asyncio.Lock()

    async def reserve(self) -> None:
        async with self._lock:
            if self._limit is not None and self._used >= self._limit:
                raise SpeechProviderError(self._error_code)
            # Do this before the first provider iterator is entered. Never refund it:
            # a cancellation or lost response cannot tell us whether remote work began.
            self._used += 1

    def snapshot(self) -> RequestBudgetSnapshot:
        # Event-loop confined app-lifespan counter; Python integer reads are atomic.
        return RequestBudgetSnapshot(self._used, self._limit)


class _BoundedSynthesis:
    def __init__(self, backend, *, attempts: _AttemptBudget, max_samples: int) -> None:
        self._backend = backend
        self._attempts = attempts
        self._max_samples = max_samples

    def synthesize(self, approved_text: str, stream_id: str) -> AsyncIterator[AudioPacket]:
        return self._synthesize(approved_text, stream_id)

    async def _synthesize(self, approved_text: str, stream_id: str) -> AsyncIterator[AudioPacket]:
        if (not isinstance(approved_text, str) or not approved_text.strip()
                or len(approved_text) > _MAX_TTS_TEXT_CHARACTERS
                or not isinstance(stream_id, str) or not stream_id):
            raise SpeechProviderError("invalid_input")
        await self._attempts.reserve()
        stream = self._backend.synthesize(approved_text, stream_id)
        cursor = 0
        try:
            async for packet in stream:
                if (not isinstance(packet, AudioPacket) or packet.stream_id != stream_id
                        or type(packet.first_sample) is not int or packet.first_sample != cursor
                        or type(packet.sample_rate_hz) is not int
                        or packet.sample_rate_hz != _PCM_SAMPLE_RATE_HZ
                        or not isinstance(packet.pcm, bytes) or not packet.pcm
                        or len(packet.pcm) % 2 or len(packet.pcm) > _MAX_PCM_PACKET_BYTES
                        or (packet.pcm[:4] == b"RIFF" and packet.pcm[8:12] == b"WAVE")):
                    raise SpeechProviderError("invalid_audio")
                samples = len(packet.pcm) // 2
                if cursor + samples > self._max_samples:
                    raise SpeechProviderError("output_limit")
                cursor += samples
                # No buffering or lookahead: once this packet is validated it goes on.
                yield packet
        except Exception as error:
            if isinstance(error, SpeechProviderError):
                raise
            raise SpeechProviderError("unavailable") from None
        finally:
            await close_stream(stream, preserve_error=sys.exc_info()[0] is not None)


class _BoundedRecognition:
    def __init__(self, backend, *, attempts: _AttemptBudget, max_seconds: float) -> None:
        self._backend = backend
        self._attempts = attempts
        self._max_seconds = max_seconds

    def transcribe(self, packets: AsyncIterator[AudioPacket]) -> AsyncIterator[TranscriptRevision]:
        return self._transcribe(packets)

    async def _transcribe(self, packets: AsyncIterator[AudioPacket]) -> AsyncIterator[TranscriptRevision]:
        source = aiter(packets)
        stream = bounded = None
        try:
            try:
                first = await anext(source)
            except StopAsyncIteration:
                return
            self._validate_packet(first, expected_stream=None, expected_rate=None, expected_sample=None)
            if len(first.pcm) // 2 > self._max_samples(first.sample_rate_hz):
                raise SpeechProviderError("input_limit")

            # Reserve after empty/invalid/oversized local input is rejected, but before
            # invoking the concrete recognizer. Cancellation and unknown outcomes stick.
            await self._attempts.reserve()
            bounded = self._bounded_packets(first, source)
            stream = self._backend.transcribe(bounded)
            async for revision in stream:
                yield revision
        except Exception as error:
            if isinstance(error, SpeechProviderError):
                raise
            raise SpeechProviderError("unavailable") from None
        finally:
            preserve_error = sys.exc_info()[0] is not None
            for resource in (stream, bounded, source):
                await close_stream(resource, preserve_error=preserve_error)

    def _max_samples(self, sample_rate_hz: int) -> int:
        return int(self._max_seconds * sample_rate_hz)

    @staticmethod
    def _validate_packet(packet: object, *, expected_stream: str | None,
                         expected_rate: int | None, expected_sample: int | None) -> None:
        if (not isinstance(packet, AudioPacket) or not isinstance(packet.stream_id, str)
                or not packet.stream_id or (expected_stream is not None and packet.stream_id != expected_stream)
                or type(packet.first_sample) is not int or packet.first_sample < 0
                or (expected_sample is not None and packet.first_sample != expected_sample)
                or type(packet.sample_rate_hz) is not int or not 8000 <= packet.sample_rate_hz <= 48000
                or (expected_rate is not None and packet.sample_rate_hz != expected_rate)
                or not isinstance(packet.pcm, bytes) or not packet.pcm or len(packet.pcm) % 2
                or len(packet.pcm) > _MAX_PCM_PACKET_BYTES
                or (packet.pcm[:4] == b"RIFF" and packet.pcm[8:12] == b"WAVE")):
            raise SpeechProviderError("invalid_input")

    async def _bounded_packets(self, first: AudioPacket,
                               source: AsyncIterator[AudioPacket]) -> AsyncIterator[AudioPacket]:
        expected_sample = first.first_sample
        total_samples = 0
        packet = first
        try:
            while True:
                self._validate_packet(packet, expected_stream=first.stream_id,
                                      expected_rate=first.sample_rate_hz,
                                      expected_sample=expected_sample)
                samples = len(packet.pcm) // 2
                if total_samples + samples > self._max_samples(first.sample_rate_hz):
                    raise SpeechProviderError("input_limit")
                total_samples += samples
                expected_sample += samples
                # Forward each bounded chunk directly to STT. Never aggregate audio.
                yield packet
                try:
                    packet = await anext(source)
                except StopAsyncIteration:
                    return
        finally:
            await close_stream(source, preserve_error=sys.exc_info()[0] is not None)


class _BoundedRecognitionEvents:
    """Continuous-only wrapper sharing the exact irreversible STT attempt counter."""
    def __init__(self, backend, *, attempts: _AttemptBudget, max_seconds: float) -> None:
        self._backend = backend
        self._attempts = attempts
        self._max_seconds = max_seconds
        self.endpoint_mode = getattr(backend, "endpoint_mode", "unavailable_manual")
        self.max_stream_seconds = min(max_seconds, getattr(backend, "max_stream_seconds", max_seconds))

    def transcribe_events(self, packets):
        return self._transcribe_events(packets)

    async def _transcribe_events(self, packets):
        source = aiter(packets)
        bounded = stream = None
        try:
            try:
                first = await anext(source)
            except StopAsyncIteration:
                return
            _BoundedRecognition._validate_packet(first, expected_stream=None,
                                                 expected_rate=16_000, expected_sample=0)
            if len(first.pcm) // 2 > int(self._max_seconds * first.sample_rate_hz):
                raise SpeechProviderError("input_limit")
            # PTT and click-start leases reserve from this same atomic budget. Empty,
            # malformed and oversized initial audio does not consume an attempt.
            await self._attempts.reserve()
            snapshot = self._attempts.snapshot()
            yield ContinuousRecognitionStarted(snapshot.used, snapshot.remaining)
            policy = _BoundedRecognition(self._backend, attempts=self._attempts,
                                         max_seconds=self._max_seconds)
            bounded = policy._bounded_packets(first, source)
            stream = self._backend.transcribe_events(bounded)
            async for event in stream:
                if not isinstance(event, (ContinuousTranscriptResult, ContinuousSpeechActivity)):
                    raise SpeechProviderError("invalid_response")
                yield event
        except Exception as error:
            if isinstance(error, SpeechProviderError):
                raise
            raise SpeechProviderError("unavailable") from None
        finally:
            preserve_error = sys.exc_info()[0] is not None
            for resource in (stream, bounded, source):
                await close_stream(resource, preserve_error=preserve_error)


def validate_development_voice_settings(
    speech_settings: SpeechSettings, *, usage_profile: UsageProfile | str,
) -> SpeechSettings:
    """Inert shared validation for launch checks and admitted voice composition.

    This validates selection only, without changing settings, discovering
    credentials, constructing SDK clients, or establishing live availability.
    The exact route continues automatic language detection; the configured
    ``tts_language_code`` is not serialized into its current request.
    """
    if type(speech_settings) is not SpeechSettings:
        raise ConfigurationError("Development voice requires explicit typed speech settings.")
    profile = parse_usage_profile(usage_profile)
    if (not speech_settings.project_id or speech_settings.auth != "google_adc"
            or speech_settings.asr_provider != "google_cloud"
            or speech_settings.tts_provider != "google_cloud"
            or speech_settings.stt_model != "chirp_3"
            or speech_settings.tts_model != "gemini-3.8-flash-tts"
            or speech_settings.tts_endpoint != "aiplatform.googleapis.com"
            or speech_settings.tts_location != "global"):
        raise ConfigurationError("Development voice requires project config and the fixed Google voice selection.")
    if profile is UsageProfile.PROBE:
        if speech_settings.tts_voice != "Kore":
            raise ConfigurationError("Development probe requires the fixed Google voice selection: Kore.")
    elif (not isinstance(speech_settings.tts_voice, str)
          or speech_settings.tts_voice not in _APPLICATION_TTS_VOICES):
        raise ConfigurationError("Application Google voice selection must be explicit: Kore or Gacrux.")
    return speech_settings


def create_development_voice_factory(
    *,
    speech_settings: SpeechSettings,
    credentials: object,
    token_provider: Callable[[], Awaitable[str]],
    authorized: bool,
    limits: DevelopmentVoiceLimits,
    http_client=None,
    stt_ssl_channel_credentials=None,
) -> Callable[[], GoogleVoiceProviders]:
    """Build a single-use lifespan factory from explicit caller-owned inputs.

    The factory must be passed to the existing development app with voice-required
    mode enabled. Construction is inert. Calling it once inside a running application
    loop creates the existing Google bundle; attempting to call it again is rejected,
    so restarting the same factory cannot replenish its counters. A new process or a
    newly constructed factory starts a new per-instance budget and must be separately
    admitted; this object is not a durable or dollar-denominated budget.
    Probe keeps its historical fixed Kore selection. Application requires an
    explicit supported selection; it never replaces an existing Kore setting.
    """
    if authorized is not True:
        raise ConfigurationError("Development voice requires explicit voice/data/spend authorization.")
    if credentials is None:
        raise ConfigurationError("Development voice requires caller-injected opaque credentials.")
    if not callable(token_provider):
        raise ConfigurationError("Development voice requires a caller-injected async token provider.")
    if type(limits) is not DevelopmentVoiceLimits:
        raise ConfigurationError("Development voice requires explicit bounded request and duration limits.")
    validate_development_voice_settings(speech_settings, usage_profile=limits.usage_profile)

    claimed = False

    def voice_factory() -> GoogleVoiceProviders:
        nonlocal claimed
        if claimed:
            raise ConfigurationError("Development voice factory can be used only once per lifespan.")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            raise ConfigurationError("Construct development voice inside the application lifespan.") from None
        claimed = True
        providers = create_google_voice(
            speech_settings,
            credentials=credentials,
            token_provider=token_provider,
            authorized=True,
            http_client=http_client,
            stt_ssl_channel_credentials=stt_ssl_channel_credentials,
            stt_max_stream_seconds=limits.stt_max_input_seconds,
            tts_max_audio_samples=limits.tts_max_samples,
        )

        stt_attempts = _AttemptBudget(limits.stt_request_limit, "input_limit")
        tts_attempts = _AttemptBudget(limits.tts_request_limit, "output_limit")
        return GoogleVoiceProviders(
            speech_recognition=_BoundedRecognition(
                providers.speech_recognition,
                attempts=stt_attempts,
                max_seconds=limits.stt_max_input_seconds,
            ),
            speech_synthesis=_BoundedSynthesis(
                providers.speech_synthesis,
                attempts=tts_attempts,
                max_samples=limits.tts_max_samples,
            ),
            _shutdown=providers.close,
            continuous_speech_recognition=_BoundedRecognitionEvents(
                providers.continuous_speech_recognition,
                attempts=stt_attempts,
                max_seconds=limits.stt_max_input_seconds,
            ),
            stt_request_budget=stt_attempts,
        )

    return voice_factory
