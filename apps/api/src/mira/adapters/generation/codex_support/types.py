"""Trusted construction inputs. No environment or credential discovery."""
from __future__ import annotations

import math
import hashlib
import json
import platform
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

PINNED_VERSION = '0.159.2'
# Kept as the historical Linux x86_64 alias for existing tests and smoke harnesses.
PINNED_EXECUTABLE_SHA256 = '1748767b230ebfc3d4ab7e4e254920d0c0ad9691fd8c11f190e7d44511a4a92e'
PINNED_MACOS_ARM64_EXECUTABLE_SHA256 = '16593cc2f422d5f398a8e40f550ebbaf1245392528957be342c295920a300704'
PINNED_MACOS_X86_64_EXECUTABLE_SHA256 = '5acdb61ada4233af340719ddb243d5e71ea24f04afeed922644d8f1d486d4c79'
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
class CodexPlatformPin:
    """One exact official CLI build selected from the current interpreter host facts."""

    platform_family: str
    platform_os: str
    machine: str
    executable_sha256: str


def current_codex_platform_pin() -> CodexPlatformPin:
    """Select only reviewed Codex 0.159.2 binaries for the actual host OS and machine."""
    raw_machine = platform.machine()
    if type(raw_machine) is not str:
        raise ValueError('codex_platform_pin_unavailable')
    machine = raw_machine.strip().lower()
    if machine in ('amd64', 'x64'):
        machine = 'x86_64'
    elif machine in ('aarch64',):
        machine = 'arm64'

    if sys.platform == 'linux' and machine == 'x86_64':
        return CodexPlatformPin('unix', 'linux', machine, PINNED_EXECUTABLE_SHA256)
    if sys.platform == 'darwin' and machine == 'arm64':
        return CodexPlatformPin('unix', 'macos', machine,
                                PINNED_MACOS_ARM64_EXECUTABLE_SHA256)
    if sys.platform == 'darwin' and machine == 'x86_64':
        return CodexPlatformPin('unix', 'macos', machine,
                                PINNED_MACOS_X86_64_EXECUTABLE_SHA256)
    raise ValueError('codex_platform_pin_unavailable')


@dataclass(frozen=True, slots=True)
class ReadonlyInstallationApproval:
    """Explicit binding for one verified, kernel-read-only managed executable."""

    executable_path: str
    verified_uid: int
    verified_mode: int

    def __post_init__(self):
        path = Path(self.executable_path) if type(self.executable_path) is str else None
        if (path is None or not path.is_absolute() or '..' in path.parts
                or str(path) != self.executable_path or '\0' in self.executable_path
                or type(self.verified_uid) is not int or self.verified_uid < 0
                or type(self.verified_mode) is not int or not 0 <= self.verified_mode <= 0o777
                or self.verified_mode & 0o022 or not self.verified_mode & 0o111):
            raise ValueError('codex_readonly_installation_approval_invalid')


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
    readonly_installation: ReadonlyInstallationApproval | None = None

    def __post_init__(self):
        if (type(self.route_value_sha256) is not str
                or not re.fullmatch(r'[a-f0-9]{64}', self.route_value_sha256)
                or type(self.managed_environment_sha256) is not str
                or not re.fullmatch(r'[a-f0-9]{64}', self.managed_environment_sha256)
                or type(self.observed_home_mode) is not int
                or not 0 <= self.observed_home_mode <= 0o777
                or self.observed_home_mode & 0o022
                or (self.readonly_installation is not None
                    and type(self.readonly_installation) is not ReadonlyInstallationApproval)):
            raise ValueError('codex_development_approval_invalid')


@dataclass(frozen=True, slots=True)
class CodexRuntime:
    executable: Path
    codex_home: Path
    runtime_cwd: Path
    environment: Mapping[str, str] = field(default_factory=dict, repr=False)
    executable_sha256: str | None = None
    # An approved config/read digest is required for the real subprocess factory.
    # Injected synthetic factories can omit it; every category guard still applies.
    expected_config_sha256: str | None = None
    # Caller must explicitly verify applicable managed policy controls are preserved.
    policy_environment_confirmed: bool = False
    development_context: ApprovedDevelopmentContext | None = None
    platform_family: str = field(init=False, repr=False)
    platform_os: str = field(init=False, repr=False)
    platform_machine: str = field(init=False, repr=False)

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
        pin = current_codex_platform_pin()
        requested_digest = pin.executable_sha256 if self.executable_sha256 is None else self.executable_sha256
        if requested_digest != pin.executable_sha256:
            raise ValueError('codex_executable_pin_invalid')
        object.__setattr__(self, 'executable_sha256', requested_digest)
        object.__setattr__(self, 'platform_family', pin.platform_family)
        object.__setattr__(self, 'platform_os', pin.platform_os)
        object.__setattr__(self, 'platform_machine', pin.machine)
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
