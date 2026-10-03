"""Trusted construction inputs. No environment or credential discovery."""
from __future__ import annotations

import math
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

PINNED_VERSION = '0.159.2'
PINNED_EXECUTABLE_SHA256 = '1748767b230ebfc3d4ab7e4e254920d0c0ad9691fd8c11f190e7d44511a4a92e'
MODEL = 'gpt-6-luna'
DISABLED_FEATURES = ('apps', 'plugins', 'browser_use', 'computer_use', 'multi_agent',
                     'shell_tool', 'image_generation', 'tool_suggest', 'sleep_tool', 'token_budget')
_ENV_KEYS = frozenset(('HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'HTTP_PROXY', 'HTTPS_PROXY',
                       'ALL_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy', 'all_proxy',
                       'no_proxy', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE',
                       'CURL_CA_BUNDLE', 'CODEX_PERMISSION_PROFILE',
                       'CODEX_NETWORK_PROXY_ACTIVE', 'CODEX_SANDBOX_NETWORK_DISABLED'))


class CodexGenerationError(RuntimeError):
    """Fixed diagnostic code, never provider output, paths, environment or credentials."""


@dataclass(frozen=True, slots=True)
class ApprovedDevelopmentContext:
    """Trusted, explicit approval of one existing development context, not an endpoint.

    No loader, HTTP or user prompt constructs this. Fingerprints come from a
    separately approved native-client preflight; they cannot authorize a new route.
    The existing home mode is checked unchanged, never tightened or relaxed here.
    """
    route_value_sha256: str
    observed_home_mode: int
    managed_environment_sha256: str

    def __post_init__(self):
        if (type(self.route_value_sha256) is not str
                or not re.fullmatch(r'[a-f0-9]{64}', self.route_value_sha256)
                or type(self.managed_environment_sha256) is not str
                or not re.fullmatch(r'[a-f0-9]{64}', self.managed_environment_sha256)
                or type(self.observed_home_mode) is not int
                or not 0 <= self.observed_home_mode <= 0o777
                or self.observed_home_mode & 0o022):
            raise ValueError('codex_development_approval_invalid')


@dataclass(frozen=True, slots=True)
class CodexRuntime:
    executable: Path
    codex_home: Path
    runtime_cwd: Path
    environment: Mapping[str, str] = field(default_factory=dict, repr=False)
    executable_sha256: str = PINNED_EXECUTABLE_SHA256
    # An approved config/read digest is required for the real subprocess factory.
    # Injected synthetic factories can omit it; every category guard still applies.
    expected_config_sha256: str | None = None
    # Caller must explicitly verify applicable managed policy controls are preserved.
    policy_environment_confirmed: bool = False
    development_context: ApprovedDevelopmentContext | None = None

    def __post_init__(self):
        if self.development_context is not None:
            if (type(self.development_context) is not ApprovedDevelopmentContext
                    or self.expected_config_sha256 is None):
                raise ValueError('codex_development_approval_invalid')
        if type(self.policy_environment_confirmed) is not bool:
            raise ValueError('codex_policy_environment_invalid')
        if any(not isinstance(path, Path) or not path.is_absolute() or '..' in path.parts
               for path in (self.executable, self.codex_home, self.runtime_cwd)):
            raise ValueError('codex_runtime_paths_invalid')
        if self.codex_home == self.runtime_cwd or self.codex_home in self.runtime_cwd.parents:
            raise ValueError('codex_runtime_paths_overlap')
        if self.executable_sha256 != PINNED_EXECUTABLE_SHA256:
            raise ValueError('codex_executable_pin_invalid')
        if self.expected_config_sha256 is not None and not re.fullmatch(
                r'[a-f0-9]{64}', self.expected_config_sha256):
            raise ValueError('codex_config_pin_invalid')
        if (not isinstance(self.environment, Mapping)
                or any(type(key) is not str or '\0' in key or type(value) is not str or '\0' in value
                       or (self.development_context is None and key not in _ENV_KEYS)
                       for key, value in self.environment.items())):
            raise ValueError('codex_environment_invalid')
        if self.development_context is not None:
            fingerprint = hashlib.sha256(json.dumps(dict(self.environment), sort_keys=True,
                separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
            if fingerprint != self.development_context.managed_environment_sha256:
                raise ValueError('codex_development_approval_invalid')
        object.__setattr__(self, 'environment', MappingProxyType(dict(self.environment)))


@dataclass(frozen=True, slots=True)
class CodexLimits:
    startup_seconds: float = 10.0
    turn_seconds: float = 60.0
    shutdown_seconds: float = 1.0
    max_line_bytes: int = 131072
    max_wire_bytes: int = 1048576
    max_output_bytes: int = 16384
    max_prompt_bytes: int = 65536
    max_events: int = 1024
    queue_capacity: int = 128

    def __post_init__(self):
        for value in (self.startup_seconds, self.turn_seconds, self.shutdown_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 120:
                raise ValueError('codex_timeout_limit_invalid')
        bounds = ((self.max_line_bytes, 1024, 262144), (self.max_wire_bytes, 1024, 4194304),
                  (self.max_output_bytes, 128, 65536), (self.max_prompt_bytes, 1024, 131072),
                  (self.max_events, 1, 4096), (self.queue_capacity, 1, 256))
        if any(type(v) is not int or not low <= v <= high for v, low, high in bounds):
            raise ValueError('codex_size_limit_invalid')


class CodexTransport(Protocol):
    async def send(self, message: dict) -> None: ...
    async def receive(self) -> bytes: ...
    async def close(self) -> None: ...
