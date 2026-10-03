"""Composition root. No service locator, dynamic plugin loading, or global singleton."""
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Awaitable, Callable

from mira.adapters.diagnostics.audio_review import ReviewedAudioCapture
from mira.adapters.journal.memory import MemoryEventJournal
from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics, NullDiagnostics
from mira.application.ports.diagnostics import Diagnostics
from mira.application.ports.journal import EventJournal
from mira.application.ports.media import SpeechRecognitionBackend, SpeechSynthesisBackend
from mira.application.ports.reviewed_audio import ReviewedAudioCapturePort
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.application.sessions import SessionRegistry
from mira.bootstrap.providers import Providers, create_providers
from mira.config.settings import Settings
from mira.config.loader import ConfigurationError


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

    async def close(self) -> None:
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
                    diagnostics: Diagnostics | None = None) -> Container:
    if settings.providers.generation == "rehearsal" and any(value is not None for value in (
            providers, speech_synthesis, speech_recognition, media_shutdown)):
        raise ConfigurationError("Offline rehearsal cannot be combined with injected providers or media.")
    selected = providers or create_providers(settings.providers)
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
    sessions = SessionRegistry(
        lambda state: SessionActor(state, selected.generation, selected.review, journal, limits,
                                   speech_synthesis=speech_synthesis,
                                   speech_recognition=speech_recognition, diagnostics=diagnostics,
                                   semantic_review=selected.semantic_review,
                                   decision_owner=selected.decision_owner),
        journal, settings.runtime.max_sessions,
    )
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
    )
