"""Explicit, bounded entry for an admitted local Codex + JEV development session.

This is intentionally separate from ``create_app`` and ``create_providers``. It
constructs no credentials, HTTP clients or provider requests at import/factory time;
the caller supplies an admitted Codex runtime and already-budgeted JEV transports.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import FastAPI

from mira.adapters.generation.codex_app_server import (
    CodexAppServerGenerationBackend, CodexLimits, CodexRuntime, TransportFactory,
)
from mira.adapters.generation.codex_support.types import ApprovedDevelopmentContext
from mira.adapters.review.jev import JevTransport
from mira.application.decision_policy import (
    DecisionThresholdPolicy, USER_DEVELOPMENT_0_6_V2, is_supported_development_policy,
)
from mira.bootstrap.providers import GoogleVoiceProviders, Providers
from mira.config.loader import ConfigurationError
from mira.config.settings import Settings
from mira.config.memory import MemoryRecallOptions
from mira.entrypoints.http.operator_pairing import OperatorPairing
from mira.entrypoints.http.app import create_app
from mira.application.continuous_listening import ListeningLimits
from mira.adapters.review.jev_support.http import HttpxJevTransport
from mira.bootstrap.development_usage import (
    UsageDeclaration, UsageProfile, UsageSnapshot, parse_usage_profile,
    validate_count,
)

_MAX_TIMEOUT_SECONDS = 30.0


def _managed_home_is_bound(runtime: CodexRuntime) -> bool:
    """Match an explicit Codex home or its canonical HOME/.codex default lexically.

    Filesystem canonicality, ownership and fingerprints belong to runtime validation
    before spawn; factory composition must not inspect homes or authentication state.
    """
    environment = runtime.environment

    def canonical_absolute(value: str) -> Path | None:
        path = Path(value)
        if not value or not path.is_absolute() or ".." in path.parts or str(path) != value:
            return None
        return path

    home_value = environment.get("HOME")
    home = canonical_absolute(home_value) if home_value is not None else None
    if home_value is not None and home is None:
        return False

    if "CODEX_HOME" in environment:
        bound_home = canonical_absolute(environment["CODEX_HOME"])
    elif home is not None:
        bound_home = canonical_absolute(str(home / ".codex"))
    else:
        return False
    return bound_home is not None and bound_home == runtime.codex_home


def _bounded_timeout(value: object, name: str) -> float:
    """Validate against the small ceiling before float conversion / isfinite."""
    if type(value) not in (int, float):
        raise ConfigurationError(f"{name} must be a finite number in (0, 30].")
    # This comparison also rejects arbitrarily large integers without converting them
    # to float (which can raise OverflowError inside math.isfinite).
    if value <= 0 or value > _MAX_TIMEOUT_SECONDS:
        raise ConfigurationError(f"{name} must be a finite number in (0, 30].")
    if type(value) is float and not math.isfinite(value):
        raise ConfigurationError(f"{name} must be a finite number in (0, 30].")
    return float(value)


def create_development_app(
    *,
    runtime: CodexRuntime,
    settings: Settings,
    route_kind: Literal["public", "managed"],
    input_transport: JevTransport,
    output_transport: JevTransport,
    authorized: bool,
    decision_policy: DecisionThresholdPolicy = USER_DEVELOPMENT_0_6_V2,
    codex_request_limit: int = 1,
    session_turn_limit: int = 1,
    input_request_limit: int = 2,
    output_request_limit: int = 2,
    input_timeout_seconds: float = 10.0,
    output_timeout_seconds: float = 10.0,
    usage_profile: UsageProfile | str = UsageProfile.PROBE,
    codex_limits: CodexLimits | None = None,
    codex_transport_factory: TransportFactory | None = None,
    voice_factory: Callable[[], GoogleVoiceProviders] | None = None,
    voice_usage_limits: object | None = None,
    voice_required: bool = False,
    web_root: Path | None = None,
    memory_options: MemoryRecallOptions | None = None,
    operator_pairing: OperatorPairing | None = None,
    authorize_local_memory_management: bool = False,
) -> FastAPI:
    """Compose one loopback app after the caller has admitted all transmissions.

    An absent voice bundle selects text-only candidate generation. ``voice_required``
    needs an already-authorized in-process voice factory; the CLI intentionally does
    not load one from a module or plugin.
    """
    if type(runtime) is not CodexRuntime or type(settings) is not Settings:
        raise ConfigurationError("Development entry requires typed runtime and settings.")
    if route_kind not in ("public", "managed"):
        raise ConfigurationError("Route kind must be explicit: public or managed.")
    if ((route_kind == "public" and runtime.development_context is not None)
            or (route_kind == "managed" and type(runtime.development_context)
                is not ApprovedDevelopmentContext)):
        raise ConfigurationError("Admission route kind and pinned runtime context disagree.")
    if (runtime.expected_config_sha256 is None or not runtime.policy_environment_confirmed
            or (route_kind == "public" and "CODEX_HOME" in runtime.environment)
            or (route_kind == "managed" and not _managed_home_is_bound(runtime))):
        raise ConfigurationError("Codex runtime is missing its explicit pinned admission.")
    if authorized is not True:
        raise ConfigurationError("Development app requires explicit transmission and spend admission.")
    if not is_supported_development_policy(decision_policy):
        raise ConfigurationError("Development app requires the supported immutable policy.")
    usage_profile = parse_usage_profile(usage_profile)
    validate_count(codex_request_limit, usage_profile, name="Codex request ceiling")
    validate_count(input_request_limit, usage_profile, name="Input JEV request ceiling")
    validate_count(output_request_limit, usage_profile, name="Output JEV request ceiling")
    validate_count(session_turn_limit, usage_profile, name="Session turn ceiling", turns=True)
    if codex_request_limit > session_turn_limit:
        raise ConfigurationError("Codex requests cannot exceed the session turn ceiling.")
    input_timeout = _bounded_timeout(input_timeout_seconds, "Input JEV timeout")
    output_timeout = _bounded_timeout(output_timeout_seconds, "Output JEV timeout")
    if type(voice_required) is not bool:
        raise ConfigurationError("Voice mode must be an explicit boolean.")
    if voice_required and voice_factory is None:
        raise ConfigurationError("Voice-required mode needs an admitted in-process voice factory.")
    if voice_factory is not None and not voice_required:
        raise ConfigurationError("An admitted voice factory requires voice-required mode.")
    if voice_factory is not None and not callable(voice_factory):
        raise ConfigurationError("Voice factory is invalid.")
    if voice_factory is not None:
        from mira.bootstrap.development_voice import DevelopmentVoiceLimits

        if type(voice_usage_limits) is not DevelopmentVoiceLimits:
            raise ConfigurationError("Voice mode requires its exact typed usage limits.")
        if voice_usage_limits.usage_profile is not usage_profile:
            raise ConfigurationError("Voice and text usage profiles must match.")
    elif voice_usage_limits is not None:
        raise ConfigurationError("Voice usage limits require an admitted voice factory.")
    if codex_limits is not None and type(codex_limits) is not CodexLimits:
        raise ConfigurationError("Codex limits must use the typed bounded settings.")
    if type(authorize_local_memory_management) is not bool:
        raise ConfigurationError("memory_management_consent_invalid")
    if authorize_local_memory_management and memory_options is None:
        raise ConfigurationError("memory_management_requires_memory_mode")
    if memory_options is None and operator_pairing is not None:
        raise ConfigurationError("operator_pairing_requires_memory_mode")
    if memory_options is not None and type(operator_pairing) is not OperatorPairing:
        raise ConfigurationError("memory_operator_pairing_required")
    memory_factory = None
    memory_management_factory = None
    if memory_options is not None:
        if voice_factory is not None or voice_required:
            raise ConfigurationError("memory_recall_text_only")
        from mira.bootstrap.development_memory import create_development_memory_factory
        memory_factory = create_development_memory_factory(memory_options)
        if authorize_local_memory_management:
            from mira.bootstrap.development_memory_management import create_development_memory_management_factory
            memory_management_factory = create_development_memory_management_factory(
                memory_options, authorized=True)

    # The normal provider factory still rejects Codex/JEV profiles. This entry passes
    # the real injected provider bundle to that same application and pins every request
    # to one local session with its own finite turn ceiling.
    generation = CodexAppServerGenerationBackend(
        runtime=runtime, admitted=True, request_limit=codex_request_limit,
        limits=codex_limits or CodexLimits(startup_seconds=10, turn_seconds=30,
                                           shutdown_seconds=2),
        transport_factory=codex_transport_factory,
        speech_enabled=voice_factory is not None,
    )
    from mira.bootstrap.development_review import create_development_review_providers

    providers: Providers = create_development_review_providers(
        generation=generation,
        input_transport=input_transport,
        output_transport=output_transport,
        authorized=True,
        decision_policy=decision_policy,
        usage_profile=usage_profile,
        input_request_limit=input_request_limit,
        output_request_limit=output_request_limit,
        input_timeout_seconds=input_timeout,
        output_timeout_seconds=output_timeout,
    )

    port = settings.http.port
    safe_settings = settings.model_copy(update={
        "http": settings.http.model_copy(update={
            "host": "127.0.0.1",
            "allowed_origins": (f"http://127.0.0.1:{port}", f"http://localhost:{port}"),
        }),
        "runtime": settings.runtime.model_copy(update={
            "max_sessions": 1,
            "max_turns": session_turn_limit,
        }),
        "providers": settings.providers.model_copy(update={
            "generation": "mock",
            "review": "fixture",
            "allow_external_calls": False,
            "allow_paid_api": False,
            "api_key": None,
        }),
        "diagnostics": settings.diagnostics.model_copy(update={
            # Preserve bounded sanitized diagnostics; only raw capture stays unarmed.
            "development_recording": False,
            "recording_consent": False,
        }),
    })
    listening_limits = None
    if voice_usage_limits is not None:
        # Floor a declared finite STT bound; never round it up. The shared STT
        # adapter may still support sub-second PTT, but the continuous lease protocol
        # advertises whole seconds, so disable only that feature below its minimum.
        admitted_seconds = voice_usage_limits.stt_max_input_seconds
        lease_seconds = min(120, int(admitted_seconds))
        listening_limits = ListeningLimits(max_seconds=lease_seconds,
            max_samples=(16_000 * lease_seconds if lease_seconds else 0),
            max_streams_per_session=4,
            max_total_streams=voice_usage_limits.stt_request_limit)
    app = create_app(safe_settings, providers=providers, voice_factory=voice_factory,
                      web_root=web_root, listening_limits=listening_limits,
                      **({"memory_factory": memory_factory, "operator_pairing": operator_pairing}
                         if memory_factory is not None else {}),
                      **({"memory_management_factory": memory_management_factory}
                         if memory_management_factory is not None else {}))
    app.state.usage_declaration = UsageDeclaration(
        profile=usage_profile, codex_requests=codex_request_limit,
        session_turns=session_turn_limit, input_jev_requests=input_request_limit,
        output_jev_requests=output_request_limit,
        input_jev_timeout_seconds=input_timeout,
        output_jev_timeout_seconds=output_timeout,
        tts_requests=(voice_usage_limits.tts_request_limit
                      if voice_usage_limits is not None else None),
        stt_requests=(voice_usage_limits.stt_request_limit
                      if voice_usage_limits is not None else None),
        tts_max_audio_seconds=(voice_usage_limits.tts_max_audio_seconds
                               if voice_usage_limits is not None else None),
        stt_max_stream_seconds=(voice_usage_limits.stt_max_input_seconds
                                if voice_usage_limits is not None else None),
    )
    app.state.usage_snapshot = UsageSnapshot(app.state.usage_declaration)
    return app


def jev_transport_from_settings(settings: Settings) -> HttpxJevTransport:
    """Build the fixed HTTPS JEV transport from an explicitly loaded local config."""
    if type(settings) is not Settings or settings.services.jev.api_key is None:
        raise ConfigurationError("Explicit JEV configuration and credential are required for serve.")
    return HttpxJevTransport(settings.services.jev.api_key)
