"""Lazy composition for the standalone local-only memory console."""
from __future__ import annotations

from mira.config.local_memory import LocalMemoryManagementOptions
from mira.config.loader import ConfigurationError


def create_local_memory_management_factory(options: LocalMemoryManagementOptions, *,
                                          authorized_local_writes: bool = False):
    """Construct an inert factory; open the existing fixed-scope DB only after pairing."""
    if authorized_local_writes is not True:
        raise ConfigurationError("memory_management_consent_required")
    if type(options) is not LocalMemoryManagementOptions:
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
