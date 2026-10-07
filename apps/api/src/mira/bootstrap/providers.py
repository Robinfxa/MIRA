"""Explicit factories are the only place selecting concrete provider adapters."""
import asyncio
import math
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable

from mira.adapters.generation.mock import MockGenerationBackend
from mira.adapters.generation.replay.backend import ReplayGenerationBackend
from mira.adapters.generation.replay.script import ReplayScriptError, load_script
from mira.adapters.review.mock import FixtureReviewBackend
from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
from mira.application.ports.generation import GenerationBackend
from mira.application.ports.generation_tools import ToolGenerationBackend, CompleteCandidateChunker
from mira.application.ports.review import ReviewBackend
from mira.application.ports.media import SpeechRecognitionBackend, SpeechSynthesisBackend
from mira.application.ports.continuous_speech import ContinuousSpeechRecognitionBackend
from mira.application.ports.request_budget import RequestBudget
from mira.config.loader import ConfigurationError
from mira.config.settings import ProviderSettings
from mira.config.service_settings import SpeechSettings

_DEFAULT_STT_MAX_STREAM_SECONDS = 60.0
_MAX_STT_MAX_STREAM_SECONDS = 290.0
_DEFAULT_TTS_MAX_AUDIO_SAMPLES = 24_000 * 180


def _voice_duration_bounds(stt_max_stream_seconds: float | None,
                           tts_max_audio_samples: int | None) -> tuple[float, int]:
    """Validate optional narrowing limits before importing/allocating SDK clients."""
    if stt_max_stream_seconds is None:
        stt_max = _DEFAULT_STT_MAX_STREAM_SECONDS
    else:
        value = stt_max_stream_seconds
        if (type(value) not in (int, float) or value <= 0
                or value > _MAX_STT_MAX_STREAM_SECONDS
                or (type(value) is float and not math.isfinite(value))
                or int(value * 8_000) < 1):
            raise ConfigurationError("Voice duration/sample limits are invalid or exceed factory defaults.")
        stt_max = float(value)

    if tts_max_audio_samples is None:
        tts_max = _DEFAULT_TTS_MAX_AUDIO_SAMPLES
    elif (type(tts_max_audio_samples) is not int or not 1 <= tts_max_audio_samples
          <= _DEFAULT_TTS_MAX_AUDIO_SAMPLES):
        raise ConfigurationError("Voice duration/sample limits are invalid or exceed factory defaults.")
    else:
        tts_max = tts_max_audio_samples
    return stt_max, tts_max


@dataclass(frozen=True, slots=True)
class Providers:
    generation: GenerationBackend
    review: ReviewBackend | None
    semantic_review: SemanticReviewCoordinator | None = None
    decision_owner: DecisionSnapshotOwner | None = None
    speech_synthesis: SpeechSynthesisBackend | None = None
    tool_generation: ToolGenerationBackend | None = None
    tool_caption_chunker: CompleteCandidateChunker | None = None
    native_tool_authority: bool = False

    def __post_init__(self) -> None:
        if type(self.native_tool_authority) is not bool or (self.native_tool_authority and
                (self.tool_generation is None or self.semantic_review is not None or self.decision_owner is not None)):
            raise ConfigurationError('native_tool_authority_composition_invalid')
        if self.review is None:
            if not self.native_tool_authority:raise ConfigurationError('review_required')
            from mira.application.ports.review import DisabledReviewBackend
            object.__setattr__(self,'review',DisabledReviewBackend())
        if (self.semantic_review is None) != (self.decision_owner is None):
            raise ConfigurationError("Semantic review requires both an explicit owner and coordinator.")
        if self.tool_generation is not None and not callable(getattr(self.tool_generation, 'open_tool_turn', None)):
            raise ConfigurationError('media_tool_generation_invalid')
        if self.tool_caption_chunker is not None and (self.tool_generation is None
                or not callable(getattr(self.tool_caption_chunker, 'expand', None))):
            raise ConfigurationError('media_tool_caption_chunker_invalid')


def create_providers(settings: ProviderSettings, *, character_review: bool = False) -> Providers:
    if type(character_review) is not bool:
        raise ConfigurationError('character_review_selection_invalid')
    if settings.generation not in {"mock", "replay", "rehearsal"} or settings.review != "fixture":
        raise ConfigurationError(
            "Live adapters exist, but this application factory does not yet compose them under "
            "verified explicit admission. Configured fields alone do not enable live startup. "
            "Run offline configuration checks and consult current service-setup documentation. "
            "No automatic Mock or paid-API fallback is used."
        )
    if settings.allow_external_calls or settings.allow_paid_api:
        raise ConfigurationError("Foundation profile does not enable external calls or paid APIs.")
    if settings.generation == "rehearsal":
        from mira.adapters.generation.rehearsal.backend import (
            RehearsalGenerationBackend, RehearsalReviewBackend, RehearsalSpeechBackend,
            authored_ranges, load_clips,
        )
        clips = load_clips()
        ranges = authored_ranges(clips)
        return Providers(RehearsalGenerationBackend(ranges, settings.mock_delay_ms),
                         RehearsalReviewBackend(ranges), speech_synthesis=RehearsalSpeechBackend(clips))
    if settings.generation == "replay":
        try:
            script = load_script(settings.replay_scenario)
        except ReplayScriptError as error:
            raise ConfigurationError(str(error)) from None
        return Providers(ReplayGenerationBackend(script), FixtureReviewBackend())
    return Providers(MockGenerationBackend(settings.mock_delay_ms,
                                          character_review=character_review), FixtureReviewBackend())


@dataclass(slots=True)
class GoogleVoiceProviders:
    """Explicit live resources; caller attaches close to the application lifecycle."""
    speech_recognition: SpeechRecognitionBackend
    speech_synthesis: SpeechSynthesisBackend
    _shutdown: Callable[[], Awaitable[None]]
    continuous_speech_recognition: ContinuousSpeechRecognitionBackend | None = None
    stt_request_budget: RequestBudget | None = field(default=None, repr=False)
    _closed: bool = False

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._shutdown()


def create_google_voice(settings: SpeechSettings, *, credentials,
                        token_provider: Callable[[], Awaitable[str]],
                        authorized: bool = False, http_client=None,
                        stt_ssl_channel_credentials=None,
                        stt_max_stream_seconds: float | None = None,
                        tts_max_audio_samples: int | None = None) -> GoogleVoiceProviders:
    """Compose only after the caller has obtained capability/data/spend approval.

    Never discovers ADC, reads credentials, refreshes a literal token, or enables
    the voice capability just because configuration fields happen to exist.
    The supplied credential and async token provider must already be authorized.
    This function does not perform a live readiness check or an inference call.
    An explicitly injected HTTP client may carry an already-approved proxy/CA
    route and remains caller-owned. The default client verifies TLS, ignores
    environment proxies and is closed by the returned bundle. The default STT
    stream remains 60 seconds; an explicit ceiling may raise it only to 290 seconds,
    matching the adapter's existing <300 bound. TTS remains capped by its existing
    180-second factory default. Both typed adapter options are validated before
    SDK clients allocate.
    """
    if (authorized is not True or credentials is None or not callable(token_provider)
            or not settings.project_id or not settings.tts_voice):
        raise ConfigurationError("Voice requires explicit admission, injected authentication, project and voice.")
    bounded_stt_seconds, bounded_tts_samples = _voice_duration_bounds(
        stt_max_stream_seconds, tts_max_audio_samples,
    )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        raise ConfigurationError("Construct voice inside application lifespan via voice_factory.") from None
    # Keep optional vendor imports and client construction inside this admitted factory.
    from google.api_core.client_options import ClientOptions
    from google.cloud.speech_v2 import SpeechAsyncClient
    from google.cloud.speech_v2.services.speech.transports.grpc_asyncio import SpeechGrpcAsyncIOTransport
    from google.cloud.speech_v2.types import cloud_speech
    import httpx
    from mira.adapters.speech.google_stt_v2 import (
        GoogleSpeechV2Backend, GoogleSpeechV2GrpcTransport, SttOptions,
    )
    from mira.adapters.speech.google_stt_continuous_v2 import (
        GoogleSpeechV2ContinuousBackend, GoogleSpeechV2GrpcContinuousTransport,
    )
    from mira.adapters.speech.google_gemini_tts import (
        GeminiTtsOptions, GoogleGeminiTtsBackend, GoogleGeminiTtsRestTransport,
    )

    # Validate both capabilities before allocating either shared client.
    try:
        stt_options = SttOptions(project_id=settings.project_id, location=settings.stt_location,
                                 model=settings.stt_model, language_code=settings.stt_language_code,
                                 max_stream_seconds=bounded_stt_seconds)
        tts_options = GeminiTtsOptions(project_id=settings.project_id, voice=settings.tts_voice,
                                       model=settings.tts_model, location=settings.tts_location,
                                       style=settings.tts_style,
                                       max_audio_samples=bounded_tts_samples)
    except ValueError:
        raise ConfigurationError("Google speech adapter options are invalid.") from None
    if stt_ssl_channel_credentials is None:
        stt_client = SpeechAsyncClient(credentials=credentials, client_options=ClientOptions(
            api_endpoint=stt_options.endpoint, quota_project_id=settings.quota_project_id))
    else:
        # GAPIC's documented async gRPC transport accepts an explicit SSL channel
        # credential. It still performs normal CA and hostname verification; a
        # caller-supplied channel is deliberately not accepted here because that
        # would bypass this trust input and its ownership/lifecycle boundary.
        stt_transport = SpeechGrpcAsyncIOTransport(
            credentials=credentials, host=stt_options.endpoint,
            quota_project_id=settings.quota_project_id,
            ssl_channel_credentials=stt_ssl_channel_credentials,
        )
        stt_client = SpeechAsyncClient(transport=stt_transport)
    owns_http_client = http_client is None
    if http_client is None:
        http_client = httpx.AsyncClient(trust_env=False, follow_redirects=False)
    stt = GoogleSpeechV2Backend(stt_options, GoogleSpeechV2GrpcTransport(
        stt_client, request_factory=cloud_speech.StreamingRecognizeRequest))
    continuous_stt = GoogleSpeechV2ContinuousBackend(stt_options,
        GoogleSpeechV2GrpcContinuousTransport(stt_client,
            request_factory=cloud_speech.StreamingRecognizeRequest,
            response_event_type=cloud_speech.StreamingRecognizeResponse.SpeechEventType))
    tts = GoogleGeminiTtsBackend(tts_options, GoogleGeminiTtsRestTransport(
        http_client, token_provider=token_provider, quota_project_id=settings.quota_project_id))

    async def shutdown() -> None:
        try:
            if owns_http_client:
                await http_client.aclose()
        finally:
            await stt_client.transport.close()

    return GoogleVoiceProviders(stt, tts, shutdown, continuous_stt)
