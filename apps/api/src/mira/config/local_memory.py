"""Standalone local-edit consent and fixed-scope configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mira.config.loader import ConfigurationError
from mira.config.memory_scope import load_private_memory_scope
from mira.domain.memory import MemoryScope


@dataclass(frozen=True, slots=True)
class LocalMemoryManagementOptions:
    database: Path = field(repr=False)
    scope: MemoryScope = field(repr=False)
    scope_alias: str = field(repr=False)


def load_local_memory_management_options(*, database: Path, scope_config: Path,
                                         scope_alias: str, consent_local_memory: bool,
                                         checkout_root: Path) -> LocalMemoryManagementOptions:
    """Read only the named private scope metadata after explicit local consent.

    SQLite is not opened here. This type deliberately has no provider or
    transmission permission field and is not accepted by the recall factory.
    """
    if consent_local_memory is not True:
        raise ConfigurationError("memory_local_consent_required")
    selected = load_private_memory_scope(database=database, scope_config=scope_config,
                                         scope_alias=scope_alias, checkout_root=checkout_root)
    return LocalMemoryManagementOptions(selected.database, selected.scope, selected.scope_alias)
