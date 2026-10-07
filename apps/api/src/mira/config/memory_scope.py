"""Shared validation for an existing private database and selected local scope.

This module does not decide why the caller may read or write the scope. Both
callers must enforce their own explicit consent before invoking it. Validation
reads only bounded scope metadata; it never opens SQLite.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from mira.config.loader import ConfigurationError
from mira.domain.memory import MemoryScope

MAX_SCOPE_CONFIG_BYTES = 16_384


@dataclass(frozen=True, slots=True)
class PrivateMemoryScope:
    database: Path = field(repr=False)
    scope: MemoryScope = field(repr=False)
    scope_alias: str = field(repr=False)


def _private_existing_file(path: Path, *, label: str, checkout_root: Path) -> Path:
    if (not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts
            or not isinstance(checkout_root, Path)):
        raise ConfigurationError(f"memory_{label}_path_invalid")
    try:
        lexical = Path(os.path.abspath(path))
        resolved = path.resolve(strict=True)
        root = checkout_root.resolve()
        if (lexical == root or root in lexical.parents
                or resolved == root or root in resolved.parents):
            raise ConfigurationError(f"memory_{label}_outside_checkout_required")
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            component = current.lstat()
            if stat.S_ISLNK(component.st_mode):
                raise ConfigurationError(f"memory_{label}_not_private")
            if current != path:
                if (not stat.S_ISDIR(component.st_mode)
                        or component.st_uid not in {0, os.geteuid()}
                        or (stat.S_IMODE(component.st_mode) & 0o022
                            and not component.st_mode & stat.S_ISVTX)):
                    raise ConfigurationError(f"memory_{label}_not_private")
        info = path.lstat()
        parent = path.parent.lstat()
        if (resolved != lexical or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not stat.S_ISDIR(parent.st_mode) or not hasattr(os, "geteuid")
                or info.st_uid != os.geteuid() or parent.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077
                or stat.S_IMODE(parent.st_mode) & 0o077):
            raise ConfigurationError(f"memory_{label}_not_private")
    except ConfigurationError:
        raise
    except (OSError, RuntimeError):
        raise ConfigurationError(f"memory_{label}_unavailable") from None
    return lexical


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def _read_scope(path: Path, alias: str) -> MemoryScope:
    if type(alias) is not str or not alias or len(alias) > 64 or any(c.isspace() for c in alias):
        raise ConfigurationError("memory_scope_unavailable")
    descriptor = None
    try:
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise ConfigurationError("memory_scope_config_not_private")
        raw = os.read(descriptor, MAX_SCOPE_CONFIG_BYTES + 1)
        if not raw or len(raw) > MAX_SCOPE_CONFIG_BYTES:
            raise ValueError("size")
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")))
        if (type(document) is not dict or set(document) != {"version", "scopes"}
                or type(document["version"]) is not int or document["version"] != 1
                or type(document["scopes"]) is not list or not 1 <= len(document["scopes"]) <= 32):
            raise ValueError("shape")
        result = None
        aliases = set()
        for row in document["scopes"]:
            if type(row) is not dict or set(row) != {"name", "user_id", "character_id", "world_id"}:
                raise ValueError("row")
            name = row["name"]
            if (type(name) is not str or not name or len(name) > 64
                    or any(c.isspace() for c in name) or name in aliases):
                raise ValueError("alias")
            aliases.add(name)
            scope = MemoryScope(row["user_id"], row["character_id"], row["world_id"])
            if name == alias:
                result = scope
        if result is None:
            raise ConfigurationError("memory_scope_unavailable")
        return result
    except ConfigurationError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        raise ConfigurationError("memory_scope_config_invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def load_private_memory_scope(*, database: Path, scope_config: Path, scope_alias: str,
                              checkout_root: Path) -> PrivateMemoryScope:
    """Validate selected external file metadata and one fixed scope, without SQLite IO."""
    if not hasattr(os, "geteuid"):
        raise ConfigurationError("memory_private_platform_unsupported")
    private_database = _private_existing_file(database, label="database", checkout_root=checkout_root)
    private_config = _private_existing_file(scope_config, label="scope_config", checkout_root=checkout_root)
    scope = _read_scope(private_config, scope_alias)
    return PrivateMemoryScope(private_database, scope, scope_alias)
