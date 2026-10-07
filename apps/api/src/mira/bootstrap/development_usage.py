"""Small immutable application-usage declarations for one admitted invocation.

These are technical per-invocation ceilings, not a billing ledger.  ``probe`` keeps
the historical conservative limits; ``application`` is an explicit, still-bounded
profile for longer continuous listening sessions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from mira.config.loader import ConfigurationError


class UsageProfile(str, Enum):
    PROBE = "probe"
    APPLICATION = "application"


@dataclass(frozen=True, slots=True)
class UsageProfileCaps:
    max_provider_requests: int
    max_session_turns: int
    max_tts_audio_seconds: float
    max_stt_stream_seconds: float


PROFILE_CAPS = {
    UsageProfile.PROBE: UsageProfileCaps(8, 8, 30.0, 30.0),
    UsageProfile.APPLICATION: UsageProfileCaps(100, 100, 30.0, 290.0),
}


def parse_usage_profile(value: object) -> UsageProfile:
    """Accept only the two exact names or their enum values; bool and aliases fail."""
    if type(value) is UsageProfile:
        return value
    if type(value) is str:
        try:
            return UsageProfile(value)
        except ValueError:
            pass
    raise ConfigurationError("usage_profile_invalid")


def profile_caps(profile: object) -> UsageProfileCaps:
    return PROFILE_CAPS[parse_usage_profile(profile)]


def validate_count(value: object, profile: object, *, name: str,
                   turns: bool = False) -> int:
    caps = profile_caps(profile)
    maximum = caps.max_session_turns if turns else caps.max_provider_requests
    if type(value) is not int or not 1 <= value <= maximum:
        raise ConfigurationError(f"{name} must be an integer from 1 to {maximum}.")
    return value


def validate_optional_count(value: object, profile: object, *, name: str) -> int:
    if type(value) is int and value == 0:
        return 0
    return validate_count(value, profile, name=name)


def validate_boundary_timeout(value: object) -> float:
    if (type(value) not in (int, float) or not 0 < value <= 2
            or (type(value) is float and not math.isfinite(value))):
        raise ConfigurationError('Boundary timeout must be finite and in (0, 2].')
    return float(value)


def validate_duration(value: object, profile: object, *, name: str,
                      voice: str) -> float:
    caps = profile_caps(profile)
    if voice == "tts":
        maximum = caps.max_tts_audio_seconds
    elif voice == "stt":
        maximum = caps.max_stt_stream_seconds
    else:
        raise ConfigurationError("usage_duration_kind_invalid")
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not 0 < value <= maximum):
        raise ConfigurationError(f"{name} duration must be finite and in (0, {maximum}].")
    return float(value)


@dataclass(frozen=True, slots=True)
class UsageDeclaration:
    """Exact limits made available to a local frontend or operator status view."""

    profile: UsageProfile
    codex_requests: int | None
    session_turns: int | None
    input_jev_requests: int
    output_jev_requests: int
    input_jev_timeout_seconds: float
    output_jev_timeout_seconds: float
    tts_requests: int | None = None
    stt_requests: int | None = None
    tts_max_audio_seconds: float | None = None
    stt_max_stream_seconds: float | None = None
    boundary_jev_requests: int = 0
    boundary_jev_timeout_seconds: float = 0.4
    generation_requests_per_turn: int = 1
    native_tool_authority: bool = False
    subscription_generation_unlimited: bool = False

    def __post_init__(self) -> None:
        profile = parse_usage_profile(self.profile)
        object.__setattr__(self, "profile", profile)
        if type(self.subscription_generation_unlimited) is not bool:
            raise ConfigurationError("subscription_generation_unlimited_invalid")
        if self.codex_requests is not None or not self.subscription_generation_unlimited or profile is not UsageProfile.APPLICATION:
            validate_count(self.codex_requests, profile, name="codex_requests")
        if self.subscription_generation_unlimited and self.codex_requests is not None:
            raise ConfigurationError("subscription_generation_unlimited_requires_no_count_limit")
        if type(self.native_tool_authority) is not bool:
            raise ConfigurationError("native_tool_authority_invalid")
        for name in ("input_jev_requests", "output_jev_requests", "boundary_jev_requests"):
            value = getattr(self, name)
            if self.native_tool_authority:
                if type(value) is not int or value != 0:
                    raise ConfigurationError("native_tools_cannot_declare_jev_requests")
            elif name != "boundary_jev_requests":
                validate_count(value, profile, name=name)
        if self.session_turns is not None or profile is not UsageProfile.APPLICATION:
            validate_count(self.session_turns, profile, name="session_turns", turns=True)
        if type(self.generation_requests_per_turn) is not int or self.generation_requests_per_turn not in (1, 2):
            raise ConfigurationError('generation_requests_per_turn_invalid')
        if self.session_turns is not None and self.codex_requests is not None and self.codex_requests > self.session_turns * self.generation_requests_per_turn:
            raise ConfigurationError("Codex requests cannot exceed the session turn ceiling.")
        for name in ("input_jev_timeout_seconds", "output_jev_timeout_seconds"):
            value = getattr(self, name)
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not 0 < value <= 30):
                raise ConfigurationError(f"{name} must be finite and in (0, 30].")
        validate_optional_count(self.boundary_jev_requests, profile, name='Boundary JEV request ceiling')
        validate_boundary_timeout(self.boundary_jev_timeout_seconds)
        voice_values = (self.tts_requests, self.stt_requests,
                        self.tts_max_audio_seconds, self.stt_max_stream_seconds)
        if all(value is None for value in voice_values):
            return
        if any(value is None for value in (self.tts_requests, self.tts_max_audio_seconds, self.stt_max_stream_seconds)):
            raise ConfigurationError("voice_usage_declaration_incomplete")
        validate_count(self.tts_requests, profile, name="tts_requests")
        if self.stt_requests is not None or profile is not UsageProfile.APPLICATION:
            validate_count(self.stt_requests, profile, name="stt_requests")
        validate_duration(self.tts_max_audio_seconds, profile,
                          name="tts_max_audio_seconds", voice="tts")
        validate_duration(self.stt_max_stream_seconds, profile,
                          name="stt_max_stream_seconds", voice="stt")


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    """A typed point-in-time view; unknown counts stay ``None`` rather than zero."""

    declaration: UsageDeclaration
    codex_requests_used: int | None = None
    session_turns_used: int | None = None
    input_jev_requests_used: int | None = None
    output_jev_requests_used: int | None = None
    tts_requests_used: int | None = None
    stt_requests_used: int | None = None
    active_tts_audio_seconds: float | None = None
    active_stt_stream_seconds: float | None = None
    elapsed_seconds: float | None = None

    def __post_init__(self) -> None:
        if type(self.declaration) is not UsageDeclaration:
            raise ConfigurationError("usage_snapshot_declaration_invalid")
        for name in ("codex_requests_used", "session_turns_used",
                     "input_jev_requests_used", "output_jev_requests_used",
                     "tts_requests_used", "stt_requests_used"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ConfigurationError("usage_snapshot_count_invalid")
        for name in ("active_tts_audio_seconds", "active_stt_stream_seconds", "elapsed_seconds"):
            value = getattr(self, name)
            if value is not None and (type(value) not in (int, float)
                                      or not math.isfinite(value) or value < 0):
                raise ConfigurationError("usage_snapshot_duration_invalid")
        limits = self.declaration
        pairs = ((self.codex_requests_used, limits.codex_requests),
                 (self.session_turns_used, limits.session_turns),
                 (self.input_jev_requests_used, limits.input_jev_requests),
                 (self.output_jev_requests_used, limits.output_jev_requests),
                 (self.tts_requests_used, limits.tts_requests),
                 (self.stt_requests_used, limits.stt_requests))
        if any(used is not None and limit is not None and used > limit
               for used, limit in pairs):
            raise ConfigurationError("usage_snapshot_exceeds_declared_limit")
        if (self.active_tts_audio_seconds is not None
                and limits.tts_max_audio_seconds is not None
                and self.active_tts_audio_seconds > limits.tts_max_audio_seconds):
            raise ConfigurationError("usage_snapshot_exceeds_declared_tts_duration")
        if (self.active_stt_stream_seconds is not None
                and limits.stt_max_stream_seconds is not None
                and self.active_stt_stream_seconds > limits.stt_max_stream_seconds):
            raise ConfigurationError("usage_snapshot_exceeds_declared_stt_duration")
