"""Explicit factories are the only place selecting concrete provider adapters."""
import asyncio
from dataclasses import dataclass
from collections.abc import Awaitable, Callable

from mira.adapters.generation.mock import MockGenerationBackend
from mira.adapters.generation.replay.backend import ReplayGenerationBackend
from mira.adapters.generation.replay.script import ReplayScriptError, load_script
from mira.adapters.review.mock import FixtureReviewBackend
from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
from mira.application.ports.generation import GenerationBackend
from mira.application.ports.review import ReviewBackend
from mira.application.ports.media import SpeechRecognitionBackend, SpeechSynthesisBackend
from mira.config.loader import ConfigurationError
from mira.config.settings import ProviderSettings
from mira.config.service_settings import SpeechSettings


@dataclass(frozen=True, slots=True)
class Providers:
    generation: GenerationBackend
    review: ReviewBackend
    semantic_review: SemanticReviewCoordinator | None = None
    decision_owner: DecisionSnapshotOwner | None = None
    speech_synthesis: SpeechSynthesisBackend | None = None

    def __post_init__(self) -> None:
        if (self.semantic_review is None) != (self.decision_owner is None):
            raise ConfigurationError("Semantic review requires both an explicit owner and coordinator.")


def create_providers(settings: ProviderSettings) -> Providers:
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
    return Providers(MockGenerationBackend(settings.mock_delay_ms), FixtureReviewBackend())


@dataclass(slots=True)
class GoogleVoiceProviders:
    """Explicit live resources; caller attaches close to the application lifecycle."""
    speech_recognition: SpeechRecognitionBackend
    speech_synthesis: SpeechSynthesisBackend
    _shutdown: Callable[[], Awaitable[None]]
    _closed: bool = False

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._shutdown()


def create_google_voice(settings: SpeechSettings, *, credentials,
                        token_provider: Callable[[], Awaitable[str]],
                        authorized: bool = False, http_client=None) -> GoogleVoiceProviders:
    """Compose only after the caller has obtained capability/data/spend approval.

    Never discovers ADC, reads credentials, refreshes a literal token, or enables
    the voice capability just because configuration fields happen to exist.
    The supplied credential and async token provider must already be authorized.
    This function does not perform a live readiness check or an inference call.
    An explicitly injected HTTP client may carry an already-approved proxy/CA
    route and remains caller-owned. The default client verifies TLS, ignores
    environment proxies and is closed by the returned bundle.
    """
    if (authorized is not True or credentials is None or not callable(token_provider)
            or not settings.project_id or not settings.tts_voice):
        raise ConfigurationError("Voice requires explicit admission, injected authentication, project and voice.")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        raise ConfigurationError("Construct voice inside application lifespan via voice_factory.") from None
    # Keep optional vendor imports and client construction inside this admitted factory.
    from google.api_core.client_options import ClientOptions
    from google.cloud.speech_v2 import SpeechAsyncClient
    from google.cloud.speech_v2.types import cloud_speech
    import httpx
    from mira.adapters.speech.google_stt_v2 import (
        GoogleSpeechV2Backend, GoogleSpeechV2GrpcTransport, SttOptions,
    )
    from mira.adapters.speech.google_gemini_tts import (
        GeminiTtsOptions, GoogleGeminiTtsBackend, GoogleGeminiTtsRestTransport,
    )

    # Validate both capabilities before allocating either shared client.
    stt_options = SttOptions(project_id=settings.project_id, location=settings.stt_location,
                             model=settings.stt_model, language_code=settings.stt_language_code,
                             max_stream_seconds=60)
    tts_options = GeminiTtsOptions(project_id=settings.project_id, voice=settings.tts_voice,
                                   model=settings.tts_model, location=settings.tts_location,
                                   style=settings.tts_style)
    stt_client = SpeechAsyncClient(credentials=credentials, client_options=ClientOptions(
        api_endpoint=stt_options.endpoint, quota_project_id=settings.quota_project_id))
    owns_http_client = http_client is None
    if http_client is None:
        http_client = httpx.AsyncClient(trust_env=False, follow_redirects=False)
    stt = GoogleSpeechV2Backend(stt_options, GoogleSpeechV2GrpcTransport(
        stt_client, request_factory=cloud_speech.StreamingRecognizeRequest))
    tts = GoogleGeminiTtsBackend(tts_options, GoogleGeminiTtsRestTransport(
        http_client, token_provider=token_provider, quota_project_id=settings.quota_project_id))

    async def shutdown() -> None:
        try:
            if owns_http_client:
                await http_client.aclose()
        finally:
            await stt_client.transport.close()

    return GoogleVoiceProviders(stt, tts, shutdown)
