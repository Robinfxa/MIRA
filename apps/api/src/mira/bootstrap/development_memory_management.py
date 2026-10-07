"""Explicit local-edit composition; construction has no storage or provider I/O."""
from __future__ import annotations

from mira.config.loader import ConfigurationError
from mira.config.memory import MemoryRecallOptions


def create_development_memory_management_factory(options: MemoryRecallOptions, *,
                                                  authorized: bool = False):
    """Open only when the app invokes this factory after operator pairing.

    Provider-transmission consent does not imply permission to edit local records.
    No database path/scope is taken from an HTTP request or generated content.
    """
    if authorized is not True:
        raise ConfigurationError("memory_management_consent_required")
    if type(options) is not MemoryRecallOptions:
        raise ConfigurationError("memory_management_configuration_invalid")

    async def open_manager():
        from mira.adapters.memory.async_management import AsyncSQLiteMemoryManagement
        from mira.application.memory_management import MemoryManagement

        backend = AsyncSQLiteMemoryManagement(options.database, options.scope)
        manager = MemoryManagement(backend, authorized=True)
        try:
            await manager.open()
        except BaseException:
            await manager.aclose()
            raise
        return manager

    return open_manager
