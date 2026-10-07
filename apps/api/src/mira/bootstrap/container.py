"""Composition root. No service locator, dynamic plugin loading, or global singleton."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from mira.adapters.diagnostics.audio_review import ReviewedAudioCapture
from mira.adapters.journal.memory import MemoryEventJournal
from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics, NullDiagnostics
from mira.application.ports.diagnostics import Diagnostics
from mira.application.ports.journal import EventJournal
from mira.application.ports.media import SpeechRecognitionBackend, SpeechSynthesisBackend
from mira.application.continuous_listening import ContinuousListeningRegistry, ListeningLimits
from mira.application.ports.continuous_speech import ContinuousSpeechRecognitionBackend
from mira.application.ports.request_budget import RequestBudget
from mira.application.ports.reviewed_audio import ReviewedAudioCapturePort
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.application.sessions import SessionRegistry
from mira.bootstrap.providers import Providers, create_providers
from mira.config.settings import Settings
from mira.config.loader import ConfigurationError
from mira.domain.story import ReadinessCatalog

if TYPE_CHECKING:
    from mira.application.actor_memory import SessionMemoryBinding


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    sessions: SessionRegistry
    journal: EventJournal
    reviewed_audio: ReviewedAudioCapturePort
    speech_enabled: bool = False
    microphone_enabled: bool = False
    generation_mode: str = "mock"
    media_shutdown: Callable[[], Awaitable[None]] | None = None
    diagnostics: Diagnostics = field(default_factory=NullDiagnostics)
    continuous_speech_recognition: ContinuousSpeechRecognitionBackend | None = None
    listening_leases: ContinuousListeningRegistry = field(default_factory=ContinuousListeningRegistry)
    stt_request_budget: RequestBudget | None = None

    @property
    def continuous_listening_enabled(self) -> bool:
        return (self.continuous_speech_recognition is not None
                and self.listening_leases.limits.max_seconds != 0)

    async def close(self) -> None:
        try:
            await self.listening_leases.aclose()
        except Exception:
            pass
        try:
            self.reviewed_audio.close()
        except Exception:
            pass
        try:
            await self.sessions.close()
        finally:
            try:
                if self.media_shutdown is not None:
                    await self.media_shutdown()
            finally:
                try:
                    self.diagnostics.close()
                except Exception:
                    pass


def build_container(settings: Settings, *, providers: Providers | None = None,
                    speech_synthesis: SpeechSynthesisBackend | None = None,
                    speech_recognition: SpeechRecognitionBackend | None = None,
                    media_shutdown: Callable[[], Awaitable[None]] | None = None,
                    diagnostics: Diagnostics | None = None,
                    memory_binding: SessionMemoryBinding | None = None,
                    continuous_speech_recognition: ContinuousSpeechRecognitionBackend | None = None,
                    listening_limits: ListeningLimits | None = None,
                    stt_request_budget: RequestBudget | None = None,
                    authorize_memory_to_speech_provider: bool = False,
                    character_factory: Callable | None = None,
                    visual_readiness: ReadinessCatalog | None = None,
                    conversation_factory: Callable | None = None,
                    character_review: bool = False,
                    story_image_factory: Callable | None = None) -> Container:
    if settings.providers.generation == "rehearsal" and any(value is not None for value in (
            providers, speech_synthesis, speech_recognition, media_shutdown, memory_binding,
            continuous_speech_recognition, character_factory, conversation_factory)):
        raise ConfigurationError("Offline rehearsal cannot be combined with injected providers or media.")
    if story_image_factory is not None and (not callable(story_image_factory) or character_factory is None):
        raise ConfigurationError('story_images_require_explicit_factory_and_story')
    selected = providers or create_providers(settings.providers, character_review=character_review)
    # Native tools carry explicit typed authority without constructing JEV. Legacy
    # image proposals still require conversation-first optional intent review; both
    # paths retain the separately admitted image runtime and exact-pixel review.
    if story_image_factory is not None and not selected.native_tool_authority and (
            selected.semantic_review is None or not selected.semantic_review.conversation_first):
        raise ConfigurationError('story_images_require_optional_intent_review')
    if character_factory is not None and not callable(character_factory):
        raise ConfigurationError("character_factory_invalid")
    if type(authorize_memory_to_speech_provider) is not bool:
        raise ConfigurationError("memory_speech_consent_invalid")
    if authorize_memory_to_speech_provider and memory_binding is None:
        raise ConfigurationError("memory_speech_consent_requires_memory")
    if memory_binding is not None:
        from mira.application.actor_memory import SessionMemoryBinding
        if type(memory_binding) is not SessionMemoryBinding or settings.runtime.max_sessions != 1:
            raise ConfigurationError("memory_recall_requires_single_operator")
        if not authorize_memory_to_speech_provider and any(value is not None for value in (
                speech_synthesis, speech_recognition, media_shutdown, selected.speech_synthesis,
                continuous_speech_recognition)):
            raise ConfigurationError("memory_recall_text_only")
    if conversation_factory is not None and (not callable(conversation_factory) or settings.runtime.max_sessions != 1):
        raise ConfigurationError("conversation_requires_single_operator")
    speech_synthesis = speech_synthesis or selected.speech_synthesis
    journal = MemoryEventJournal(settings.runtime.journal_capacity)
    if diagnostics is None:
        diagnostics = NullDiagnostics()
        config = settings.diagnostics
        if config.enabled:
            # Known secret values stay only in the trusted filter, never records/repr.
            secrets = tuple(value.get_secret_value() for value in (
                settings.providers.api_key, settings.services.gateway.api_key,
                settings.services.openai.api_key, settings.services.jev.api_key) if value is not None)
            try:
                diagnostics = LocalDiagnostics(DiagnosticOptions(root=Path(config.directory),
                    max_file_bytes=config.max_file_bytes, max_files=config.max_files,
                    retention_seconds=config.retention_seconds, queue_capacity=config.queue_capacity,
                    raw_max_file_bytes=config.raw_max_file_bytes, raw_max_files=config.raw_max_files,
                    raw_retention_seconds=config.raw_retention_seconds), secrets=secrets)
                if config.development_recording:
                    diagnostics.set_recording(True, consent=config.recording_consent)
            except Exception:
                # Diagnostics setup must not stop the interactive service.
                diagnostics = NullDiagnostics()
    limits = RuntimeLimits(settings.runtime.timeout_seconds, settings.runtime.max_turns,
                           settings.runtime.max_effects)
    def actor_factory(state, media_allowed=True):
        return SessionActor(state, selected.generation, selected.review, journal, limits,
                                   tool_generation=selected.tool_generation,
                                   native_tool_authority=selected.native_tool_authority,
                                   tool_caption_chunker=selected.tool_caption_chunker,
                                   speech_synthesis=speech_synthesis if media_allowed else None,
                                   speech_recognition=speech_recognition if media_allowed else None, diagnostics=diagnostics,
                                   semantic_review=selected.semantic_review,
                                   decision_owner=selected.decision_owner,
                                   visual_readiness=visual_readiness,
                                   story_image_runtime=story_image_factory(state) if story_image_factory else None,
                                   **({"character_runtime":character_factory(state)} if character_factory is not None else {}),
                                   **({"conversation_binding": conversation_factory(state)} if conversation_factory is not None else {}),
                                   **({"memory_binding": memory_binding} if memory_binding is not None else {}))

    sessions = SessionRegistry(actor_factory, journal, settings.runtime.max_sessions,
        text_only_factory=lambda state: actor_factory(state, False))
    reviewed_audio = ReviewedAudioCapture(diagnostics)
    if settings.diagnostics.development_recording:
        # Keep the old explicit private config path coherent with the coordinator. Default settings
        # remain off; an explicit UI/API transition is required before any runtime staging otherwise.
        reviewed_audio.set_recording(True, consent=settings.diagnostics.recording_consent)
    return Container(
        settings=settings,
        sessions=sessions,
        journal=journal,
        reviewed_audio=reviewed_audio,
        speech_enabled=speech_synthesis is not None,
        microphone_enabled=speech_recognition is not None,
        generation_mode="injected" if providers is not None else settings.providers.generation,
        media_shutdown=media_shutdown,
        diagnostics=diagnostics,
        continuous_speech_recognition=continuous_speech_recognition,
        listening_leases=ContinuousListeningRegistry(limits=listening_limits or ListeningLimits(),
                                                    diagnostics=diagnostics),
        stt_request_budget=stt_request_budget,
    )
