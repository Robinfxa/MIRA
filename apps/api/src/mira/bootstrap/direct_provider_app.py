"""Direct-provider app composition. No native executable, auth discovery or network IO.

Callers select subscription OAuth or official API billing explicitly and inject the
matching direct HTTP generation adapter. Review, presentation and cancellation keep
the existing application contracts. Authentication is owned by MIRA's separate flow.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import FastAPI

from mira.application.ports.generation import GenerationBackend
from mira.application.ports.generation_tools import ToolGenerationBackend
from mira.adapters.review.jev import JevTransport
from mira.application.decision_policy import (
    DecisionThresholdPolicy, USER_DEVELOPMENT_0_6_V2, is_supported_development_policy,
)
from mira.bootstrap.providers import GoogleVoiceProviders, Providers
from mira.config.loader import ConfigurationError
from mira.config.settings import Settings
from mira.config.memory import MemoryRecallOptions
from mira.entrypoints.http.operator_pairing import OperatorPairing
from mira.entrypoints.http.device_pairing import DevicePairing
from mira.entrypoints.http.trusted_device_access import TrustedDeviceAccess
from mira.config.http_access import validate_http_access
from mira.entrypoints.http.app import create_app
from mira.application.continuous_listening import ListeningLimits
from mira.bootstrap.development_usage import (
    UsageDeclaration, UsageProfile, UsageSnapshot, parse_usage_profile,
    validate_count, validate_optional_count, validate_boundary_timeout,
)

_MAX_TIMEOUT_SECONDS = 30.0


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


def validate_natural_listening_options(*, client_silence_ms: int = 700, natural_grace_seconds: float = 0.65,
        drain_timeout_seconds: float = 2.0, max_recognition_streams: int | None = None) -> dict:
    """Public finite policy; no resource construction or budget mutation."""
    if type(client_silence_ms) is not int or not 250 <= client_silence_ms <= 2000:
        raise ConfigurationError('listen_silence_ms must be an integer within [250, 2000].')
    for value, lower, upper, name in (
        (natural_grace_seconds, 0.25, 2.0, 'listen_grace_seconds'),
        (drain_timeout_seconds, 0.1, 5.0, 'listen_drain_seconds'),
    ):
        if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
            raise ConfigurationError(f'{name} must be finite and within [{lower}, {upper}].')
    if max_recognition_streams is not None and (type(max_recognition_streams) is not int or not 1 <= max_recognition_streams <= 32):
        raise ConfigurationError('listen_max_recognition_streams must be an integer within [1, 32].')
    return {'client_silence_ms': client_silence_ms, 'natural_grace_seconds': float(natural_grace_seconds),
        'drain_timeout_seconds': float(drain_timeout_seconds),
        'max_recognition_streams': max_recognition_streams}


def create_direct_provider_app(
    *,
    generation: GenerationBackend,
    tool_generation: ToolGenerationBackend | None = None,
    model: str,
    settings: Settings,
    route: Literal["chatgpt_subscription", "openai_api"],
    api_billing_authorized: bool = False,
    input_transport: JevTransport | None = None,
    output_transport: JevTransport | None = None,
    authorized: bool,
    action_review_mode: Literal['luna_tools', 'legacy_jev'] = 'luna_tools',
    decision_policy: DecisionThresholdPolicy = USER_DEVELOPMENT_0_6_V2,
    generation_request_limit: int | None = 1,
    session_turn_limit: int | None = 1,
    local_listening_unlimited: bool = True,
    local_listening_limits: ListeningLimits | None = None,
    input_request_limit: int = 2,
    output_request_limit: int = 2,
    boundary_request_limit: int = 0,
    boundary_timeout_seconds: float = 0.4,
    input_timeout_seconds: float = 10.0,
    output_timeout_seconds: float = 10.0,
    input_max_request_bytes: int | None = None,
    output_max_request_bytes: int | None = None,
    usage_profile: UsageProfile | str = UsageProfile.PROBE,
    voice_factory: Callable[[], GoogleVoiceProviders] | None = None,
    voice_usage_limits: object | None = None,
    voice_required: bool = False,
    client_silence_ms: int = 700,
    natural_grace_seconds: float = 0.65,
    drain_timeout_seconds: float = 2.0,
    max_recognition_streams: int | None = None,
    web_root: Path | None = None,
    memory_options: MemoryRecallOptions | None = None,
    conversation_options: object | None = None,
    operator_pairing: OperatorPairing | DevicePairing | TrustedDeviceAccess | None = None,
    loopback_port: int | None = None,
    authorize_local_memory_management: bool = False,
    authorize_memory_to_direct_provider_and_jev: bool = False,
    authorize_memory_derived_speech_to_google: bool = False,
    character_factory: Callable | None = None,
    character_binding_factory: Callable | None = None,
    character_renderer: str = 'static-pixi',
    story_image_factory: Callable | None = None,
) -> FastAPI:
    """Compose one loopback app after the caller has admitted all transmissions.

    An absent voice bundle selects text-only candidate generation. ``voice_required``
    needs an already-authorized in-process voice factory; the CLI intentionally does
    not load one from a module or plugin.
    """
    if type(settings) is not Settings or not callable(getattr(generation, "generate", None)):
        raise ConfigurationError("Direct provider requires typed settings and a generation adapter.")
    if type(action_review_mode) is not str or action_review_mode not in ('luna_tools', 'legacy_jev'):
        raise ConfigurationError('action_review_mode_invalid')
    native_tools = action_review_mode == 'luna_tools'
    if native_tools and tool_generation is None:
        raise ConfigurationError('native_tools_require_tool_generation')
    if native_tools and (input_transport is not None or output_transport is not None or boundary_request_limit):
        raise ConfigurationError('native_tools_cannot_configure_jev_transports_or_boundaries')
    try:
        private_policy = validate_http_access(settings.http.host, settings.http.port,
            settings.http.allowed_origins, settings.http.private_network)
    except ValueError:
        raise ConfigurationError("private_http_configuration_invalid") from None
    if private_policy is not None:
        if type(operator_pairing) not in (DevicePairing, TrustedDeviceAccess):
            raise ConfigurationError("private_device_pairing_required")
        if memory_options is not None or conversation_options is not None or character_binding_factory is not None:
            raise ConfigurationError("private_device_mode_ephemeral_only")
        if voice_required and private_policy.scheme != "https" and loopback_port is None:
            raise ConfigurationError("private_device_voice_requires_https")
    if tool_generation is not None and not callable(getattr(tool_generation, 'open_tool_turn', None)):
        raise ConfigurationError('media_tool_generation_invalid')
    natural_options = validate_natural_listening_options(
        client_silence_ms=client_silence_ms, natural_grace_seconds=natural_grace_seconds, drain_timeout_seconds=drain_timeout_seconds,
        max_recognition_streams=max_recognition_streams)
    if route not in ("chatgpt_subscription", "openai_api"):
        raise ConfigurationError("Choose an explicit supported direct provider route.")
    if type(model) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model) is None:
        raise ConfigurationError("Direct provider requires an explicit bounded model identifier.")
    if type(api_billing_authorized) is not bool:
        raise ConfigurationError("API billing acknowledgement must be explicit.")
    if route == "openai_api" and not api_billing_authorized:
        raise ConfigurationError("Official API billing requires a separate explicit acknowledgement.")
    if type(authorize_memory_to_direct_provider_and_jev) is not bool:
        raise ConfigurationError("Direct-provider memory transmission consent must be explicit.")
    if type(authorize_memory_derived_speech_to_google) is not bool:
        raise ConfigurationError("memory_speech_consent_invalid")
    if authorize_memory_derived_speech_to_google and (memory_options is None or not voice_required):
        raise ConfigurationError("memory_speech_consent_requires_memory_voice")
    if memory_options is not None and not authorize_memory_to_direct_provider_and_jev:
        raise ConfigurationError("Stored memory needs new direct-provider transmission consent" +
            (" and JEV transmission consent." if not native_tools else "."))
    if authorized is not True:
        raise ConfigurationError("Direct provider requires explicit dialogue transmission and applicable spend consent.")
    if character_factory is not None and not callable(character_factory):
        raise ConfigurationError("character_factory_invalid")
    if character_binding_factory is not None and (not callable(character_binding_factory)
            or character_factory is not None):
        raise ConfigurationError('character_binding_factory_invalid')
    if not is_supported_development_policy(decision_policy):
        raise ConfigurationError("Development app requires the supported immutable policy.")
    usage_profile = parse_usage_profile(usage_profile)
    if generation_request_limit is not None or route != "chatgpt_subscription" or usage_profile is not UsageProfile.APPLICATION:
        validate_count(generation_request_limit, usage_profile, name="Generation request ceiling")
    if type(local_listening_unlimited) is not bool:
        raise ConfigurationError("local_listening_unlimited_invalid")
    if local_listening_limits is not None and type(local_listening_limits) is not ListeningLimits:
        raise ConfigurationError("local_listening_limits_invalid")
    validate_count(input_request_limit, usage_profile, name="Input JEV request ceiling")
    validate_count(output_request_limit, usage_profile, name="Output JEV request ceiling")
    validate_optional_count(boundary_request_limit, usage_profile, name="Boundary JEV request ceiling")
    boundary_timeout = validate_boundary_timeout(boundary_timeout_seconds)
    if session_turn_limit is not None or usage_profile is not UsageProfile.APPLICATION:
        validate_count(session_turn_limit, usage_profile, name="Session turn ceiling", turns=True)
    if session_turn_limit is not None and generation_request_limit is not None and generation_request_limit > session_turn_limit * (2 if tool_generation is not None else 1):
        raise ConfigurationError("Generation requests cannot exceed the session turn ceiling.")
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
    if type(authorize_local_memory_management) is not bool:
        raise ConfigurationError("memory_management_consent_invalid")
    if authorize_local_memory_management and memory_options is None:
        raise ConfigurationError("memory_management_requires_memory_mode")
    if private_policy is None and memory_options is None and conversation_options is None and character_binding_factory is None and operator_pairing is not None:
        raise ConfigurationError("operator_pairing_requires_memory_mode")
    if memory_options is not None and type(operator_pairing) is not OperatorPairing:
        raise ConfigurationError("memory_operator_pairing_required")
    if character_binding_factory is not None and type(operator_pairing) is not OperatorPairing:
        raise ConfigurationError('character_operator_pairing_required')
    conversation_runtime_factory=None
    if conversation_options is not None:
        if type(operator_pairing) is not OperatorPairing:
            raise ConfigurationError('conversation_operator_pairing_required')
        from mira.bootstrap.conversation import conversation_factory
        from dataclasses import replace
        # A programmatic caller cannot omit the configured manual database exclusion.
        if memory_options is not None:
            conversation_options=replace(conversation_options,
                excluded_databases=conversation_options.excluded_databases+(memory_options.database,))
        recipients=('OpenAI ChatGPT 订阅服务' if route=='chatgpt_subscription' else 'OpenAI 官方 API')+(
            '与 TypeSafe/JEV 输出审核' if not native_tools else '')
        conversation_runtime_factory=conversation_factory(conversation_options,
            speech_enabled=voice_required,recipients=recipients)
    memory_factory = None
    memory_management_factory = None
    if memory_options is not None:
        if (voice_factory is not None or voice_required) and not authorize_memory_derived_speech_to_google:
            raise ConfigurationError("memory_recall_text_only")
        from mira.bootstrap.development_memory import create_development_memory_factory
        memory_factory = create_development_memory_factory(memory_options)
        if authorize_local_memory_management:
            from mira.bootstrap.development_memory_management import create_development_memory_management_factory
            memory_management_factory = create_development_memory_management_factory(
                memory_options, authorized=True)

    tool_caption_chunker = None
    if native_tools:
        from mira.application.semantic_chunking import DeterministicCaptionChunking
        generation = DeterministicCaptionChunking(generation)
        tool_caption_chunker = generation
        providers = Providers(generation=generation, review=None,
            tool_generation=tool_generation, tool_caption_chunker=tool_caption_chunker,
            native_tool_authority=True)
    elif boundary_request_limit:
        from mira.adapters.review.jev_chunking import JevBoundaryBackend
        from mira.application.semantic_chunking import SemanticChunkingGeneration
        generation = SemanticChunkingGeneration(generation, JevBoundaryBackend(
            transport=output_transport, model="jev-1.13.0", request_limit=boundary_request_limit,
            timeout_seconds=boundary_timeout), timeout_seconds=boundary_timeout)
        if tool_generation is not None:
            tool_caption_chunker = generation

    if not native_tools:
        # Explicit compatibility only; never a fallback from a native failure.
        from mira.bootstrap.development_review import create_development_review_providers
        providers = create_development_review_providers(
            generation=generation, input_transport=input_transport,
            output_transport=output_transport, authorized=True,
            decision_policy=decision_policy, usage_profile=usage_profile,
            input_request_limit=input_request_limit, output_request_limit=output_request_limit,
            input_timeout_seconds=input_timeout, output_timeout_seconds=output_timeout,
            input_max_request_bytes=input_max_request_bytes,
            output_max_request_bytes=output_max_request_bytes,
            character_observations=character_factory is not None or character_binding_factory is not None,
            conversation_first=True, story_images=story_image_factory is not None)
    if not native_tools and tool_generation is not None:
        from dataclasses import replace
        providers = replace(providers, tool_generation=tool_generation,
                            tool_caption_chunker=tool_caption_chunker)

    port = settings.http.port
    safe_settings = settings.model_copy(update={
        "http": settings.http if private_policy is not None else settings.http.model_copy(update={
            "host": "127.0.0.1",
            "allowed_origins": (f"http://127.0.0.1:{port}", f"http://localhost:{port}"),
        }),
        "runtime": settings.runtime.model_copy(update={
            "max_sessions": (operator_pairing.max_devices if type(operator_pairing) is TrustedDeviceAccess else 2) if private_policy is not None else 1,
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
        if local_listening_limits is not None and admitted_seconds >= 1:
            from dataclasses import replace
            listening_limits = replace(local_listening_limits, **{**natural_options,
                "max_recognition_streams": (local_listening_limits.max_recognition_streams
                    if max_recognition_streams is None else max_recognition_streams)})
        elif local_listening_unlimited and admitted_seconds >= 1:
            listening_limits = ListeningLimits(**natural_options)
        else:
            # Explicit historical finite composition, including sub-second disable.
            listening_limits = ListeningLimits(max_seconds=lease_seconds,
                max_samples=(16_000 * lease_seconds if lease_seconds else 0),
                max_utterances=12, max_streams_per_session=4,
                max_total_streams=voice_usage_limits.stt_request_limit,
                **natural_options)
    app = create_app(safe_settings, providers=providers, voice_factory=voice_factory,
        story_image_factory=story_image_factory,
        web_root=web_root,listening_limits=listening_limits,character_renderer=character_renderer,
        character_factory=character_factory,character_binding_factory=character_binding_factory,
        memory_factory=memory_factory,memory_management_factory=memory_management_factory,
        operator_pairing=operator_pairing, loopback_port=loopback_port,
        conversation_runtime_factory=conversation_runtime_factory,
        authorize_memory_to_speech_provider=authorize_memory_derived_speech_to_google)
    app.state.usage_declaration = UsageDeclaration(
        profile=usage_profile, codex_requests=generation_request_limit,
        subscription_generation_unlimited=generation_request_limit is None and route == "chatgpt_subscription",
        session_turns=session_turn_limit, input_jev_requests=0 if native_tools else input_request_limit,
        generation_requests_per_turn=2 if tool_generation is not None else 1,
        output_jev_requests=0 if native_tools else output_request_limit,
        boundary_jev_requests=0 if native_tools else boundary_request_limit,
        native_tool_authority=native_tools,
        boundary_jev_timeout_seconds=boundary_timeout,
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
    app.state.direct_provider_route = route
    app.state.direct_provider_model = model
    app.state.action_review_mode = action_review_mode
    if native_tools or memory_options is not None or character_binding_factory is not None or conversation_options is not None:
        # Public, fixed recipient names only; no account, scope or memory contents.
        app.state.memory_recipients_label = (
            "OpenAI ChatGPT 订阅服务" if route == "chatgpt_subscription" else "OpenAI 官方 API"
        ) + ("与 TypeSafe/JEV 输出审核" if not native_tools else "") + (
            "；获准合成的语音可能包含记忆内容，并发送给 Google Cloud TTS"
            if authorize_memory_derived_speech_to_google or (character_binding_factory is not None and voice_required)
            or (conversation_options is not None and conversation_options.authorize_recalled_speech_to_google) else "")
    return app
