"""Explicit private local-memory transmission configuration; no import-time IO.

This is separate from local recording consent. An operator must explicitly choose
the existing database/scope and allow its selected evidence to be sent to the
already admitted Codex generation and TypeSafe JEV review providers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from mira.config.loader import ConfigurationError
from mira.config.memory_scope import load_private_memory_scope
from mira.domain.memory import MemoryScope


@dataclass(frozen=True, slots=True)
class MemoryRecallOptions:
    database: Path = field(repr=False)
    scope: MemoryScope = field(repr=False)
    scope_alias: str = field(repr=False)
    authorized_transmission: bool
    timeout_ms: int = 200
    max_packet_bytes: int = 8_192


def load_memory_recall_options(*, database: Path, scope_config: Path, scope_alias: str,
                               authorized_transmission: bool, checkout_root: Path,
                               timeout_ms: int = 200,
                               max_packet_bytes: int = 8_192) -> MemoryRecallOptions:
    """Read bounded scope configuration only after separate transmission consent.

    The database is never opened here. Its schema and race-resistant filesystem
    identity are checked again by the read-only adapter during application startup.
    No scope ID or storage path is accepted from HTTP or model output.
    """
    if authorized_transmission is not True:
        raise ConfigurationError("memory_transmission_consent_required")
    if not hasattr(os, "geteuid"):
        raise ConfigurationError("memory_private_platform_unsupported")
    if (type(timeout_ms) is not int or not 10 <= timeout_ms <= 1_000
            or type(max_packet_bytes) is not int or not 1_024 <= max_packet_bytes <= 32_768):
        raise ConfigurationError("memory_limits_invalid")
    private_scope = load_private_memory_scope(
        database=database,
        scope_config=scope_config,
        scope_alias=scope_alias,
        checkout_root=checkout_root,
    )
    return MemoryRecallOptions(private_scope.database, private_scope.scope,
                               private_scope.scope_alias, True, timeout_ms, max_packet_bytes)
