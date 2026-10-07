"""Explicit local-memory reader composition; no recording or provider requests."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from mira.config.loader import ConfigurationError
from mira.config.memory import MemoryRecallOptions
from mira.domain.memory import MemoryScope

if TYPE_CHECKING:
    from mira.application.actor_memory import SessionMemoryBinding


def create_development_memory_factory(
    options: MemoryRecallOptions,
) -> Callable[[], Awaitable[SessionMemoryBinding]]:
    """Return an inert factory for one operator-bound reader owned by app lifespan.

    Local store consent does not grant provider transmission. Callers must supply
    the independently admitted options; the public CLI discloses Codex and JEV.
    Constructing this factory opens no files and starts no thread or connection.
    """
    if (type(options) is not MemoryRecallOptions or options.authorized_transmission is not True
            or type(options.scope) is not MemoryScope):
        raise ConfigurationError("memory_transmission_consent_required")
    if (type(options.timeout_ms) is not int or not 10 <= options.timeout_ms <= 1_000
            or type(options.max_packet_bytes) is not int
            or not 1_024 <= options.max_packet_bytes <= 32_768):
        raise ConfigurationError("memory_limits_invalid")

    async def open_binding() -> SessionMemoryBinding:
        from mira.adapters.memory.async_read import AsyncSQLiteMemoryReader
        from mira.application.actor_memory import SessionMemoryBinding

        reader = AsyncSQLiteMemoryReader(options.database, options.scope)
        try:
            await reader.open()
            return SessionMemoryBinding(reader, options.scope,
                timeout_ms=options.timeout_ms, max_packet_bytes=options.max_packet_bytes,
                close_reader_on_actor_close=False)
        except BaseException:
            await reader.aclose()
            raise

    return open_binding
