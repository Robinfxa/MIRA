"""Validated immutable configuration, never instantiated at import time."""
from typing import Literal

from pydantic import Field, SecretStr

from mira.config.base import FrozenSettings
from mira.config.diagnostic_settings import DiagnosticSettings
from mira.config.service_settings import ServiceSettings


class HttpSettings(FrozenSettings):
    host: Literal["127.0.0.1", "localhost"] = "127.0.0.1"
    port: int = Field(default=8000, ge=1024, le=65535)
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:8000", "http://localhost:8000")


class RuntimeSettings(FrozenSettings):
    timeout_seconds: float = Field(default=10, gt=0, le=120)
    max_sessions: int = Field(default=32, ge=1, le=1000)
    max_turns: int = Field(default=64, ge=1, le=1000)
    max_effects: int = Field(default=256, ge=1, le=10000)
    journal_capacity: int = Field(default=2048, ge=10, le=100000)


class ProviderSettings(FrozenSettings):
    generation: Literal["mock", "replay", "rehearsal", "codex", "api"] = "mock"
    review: Literal["fixture", "jev", "api"] = "fixture"
    replay_scenario: Literal["photo-tour", "delayed-photo", "failed-tail"] = "photo-tour"
    mock_delay_ms: int = Field(default=500, ge=0, le=10000)
    allow_external_calls: bool = False
    allow_paid_api: bool = False
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)


class Settings(FrozenSettings):
    environment: Literal["development", "test"] = "development"
    http: HttpSettings = Field(default_factory=HttpSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    providers: ProviderSettings = Field(default_factory=ProviderSettings)
    services: ServiceSettings = Field(default_factory=ServiceSettings)
    diagnostics: DiagnosticSettings = Field(default_factory=DiagnosticSettings)
