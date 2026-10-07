"""Opt-in, synchronous SQLite evidence store with explicit private-file checks.

The default application never constructs this adapter. Call ``open()`` only
after an explicit local workflow chooses to use it. Data is retained in a
bounded append-only ledger; ``forget`` suppresses records but does not erase
their original text from the local database.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import sqlite3
import stat
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from unicodedata import name as unicode_name
from uuid import uuid4

from mira.adapters.diagnostics.privacy import PrivacyFilter
from mira.adapters.memory.errors import (
    MemoryConflictError,
    MemoryDeadlineExceededError,
    MemoryEntryNotFoundError,
    MemoryPrivacyError,
    MemoryResultTooLargeError,
    MemoryStoreClosedError,
    MemoryManagementBusyError,
    MemoryManagementOperationIdConflictError,
    MemoryStoreError,
    MemoryStoreFullError,
    UnknownMemoryDatabaseError,
    UnsafeMemoryPathError,
)
from mira.application.ports.memory import MemoryPort
from mira.application.ports.memory_management import (
    MemoryManagementCommand,
    MemoryManagementEntry,
    MemoryManagementOperation,
    MemoryManagementOperationResult,
    MemoryManagementPage,
)
from mira.domain.memory import (
    MemoryEntry,
    MemoryHistoryItem,
    MemoryKind,
    MemoryMutation,
    MemoryMutationKind,
    MemoryQuery,
    MemoryRevisionChangedError,
    MemoryScope,
    MemorySource,
)

_APPLICATION_ID = int.from_bytes(b"MIRA", "big")
_SCHEMA_VERSION = 1
_MAX_CURRENT_BOUNDARIES = 64
_MAX_CURRENT_BOUNDARY_CHARS = 32_768
_MANAGEMENT_PAGE_RESPONSE_BUDGET_BYTES = 128 * 1024
_MANAGEMENT_PAGE_ENVELOPE_BOUND_BYTES = 1_024
_MANAGEMENT_ENTRY_METADATA_BOUND_BYTES = 1_024
_MANAGEMENT_ENTRY_MAX_CHARS = 16_384
_MANAGEMENT_ENTRY_MAX_UTF8_BYTES = 65_536
_QUERY_TERMS = re.compile(r"[^\W_]+", re.UNICODE)
_TABLES = {
    "memory_entries": {
        "id", "user_id", "character_id", "world_id", "source", "kind", "text",
        "source_event_id", "source_version", "recorded_at", "supersedes_id",
    },
    "memory_links": {
        "memory_id", "user_id", "character_id", "world_id", "ancestor_id", "relation",
    },
    "memory_mutations": {
        "id", "user_id", "character_id", "world_id", "kind", "target_entry_id",
        "reverses_id", "recorded_at",
    },
    "memory_history": {
        "seq", "event_id", "user_id", "character_id", "world_id", "event_kind",
        "recorded_at",
    },
}

_CREATE_SCHEMA = (
    """CREATE TABLE memory_entries (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        world_id TEXT NOT NULL,
        source TEXT NOT NULL,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        source_event_id TEXT NOT NULL,
        source_version INTEGER NOT NULL CHECK(source_version > 0),
        recorded_at TEXT NOT NULL,
        supersedes_id TEXT,
        UNIQUE(id, user_id, character_id, world_id),
        UNIQUE(user_id, character_id, world_id, source_event_id, source_version),
        FOREIGN KEY(supersedes_id, user_id, character_id, world_id)
            REFERENCES memory_entries(id, user_id, character_id, world_id)
    )""",
    """CREATE TABLE memory_links (
        memory_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        world_id TEXT NOT NULL,
        ancestor_id TEXT NOT NULL,
        relation TEXT NOT NULL CHECK(relation IN ('supersedes', 'depends_on')),
        PRIMARY KEY(memory_id, ancestor_id, relation),
        FOREIGN KEY(memory_id, user_id, character_id, world_id)
            REFERENCES memory_entries(id, user_id, character_id, world_id),
        FOREIGN KEY(ancestor_id, user_id, character_id, world_id)
            REFERENCES memory_entries(id, user_id, character_id, world_id)
    )""",
    """CREATE TABLE memory_mutations (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        world_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('forget', 'restore')),
        target_entry_id TEXT NOT NULL,
        reverses_id TEXT,
        recorded_at TEXT NOT NULL,
        UNIQUE(id, user_id, character_id, world_id),
        FOREIGN KEY(target_entry_id, user_id, character_id, world_id)
            REFERENCES memory_entries(id, user_id, character_id, world_id),
        FOREIGN KEY(reverses_id, user_id, character_id, world_id)
            REFERENCES memory_mutations(id, user_id, character_id, world_id)
    )""",
    """CREATE TABLE memory_history (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        world_id TEXT NOT NULL,
        event_kind TEXT NOT NULL CHECK(event_kind IN ('entry', 'forget', 'restore')),
        recorded_at TEXT NOT NULL
    )""",
    "CREATE INDEX memory_entries_scope ON memory_entries(user_id, character_id, world_id, kind)",
    "CREATE INDEX memory_links_scope_ancestor ON memory_links(user_id, character_id, world_id, ancestor_id)",
    "CREATE INDEX memory_mutations_scope_target ON memory_mutations(user_id, character_id, world_id, target_entry_id)",
    "CREATE INDEX memory_history_scope_seq ON memory_history(user_id, character_id, world_id, seq)",
    "CREATE UNIQUE INDEX memory_one_restore_per_forget ON memory_mutations(reverses_id) WHERE kind='restore'",
)


def _normalized_schema_sql(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.strip().rstrip(";").split())


_EXPECTED_SCHEMA_OBJECTS = {
    (kind, match.group(3)): _normalized_schema_sql(statement)
    for statement in _CREATE_SCHEMA
    if (match := re.match(r"\s*CREATE\s+(UNIQUE\s+)?(TABLE|INDEX)\s+([a-z_]+)", statement, re.I))
    for kind in ("table" if match.group(2).casefold() == "table" else "index",)
}
_EXPECTED_AUTOINDEX_COUNTS = {
    "memory_entries": 3,
    "memory_history": 1,
    "memory_links": 1,
    "memory_mutations": 2,
}


def _scope_values(scope: MemoryScope) -> tuple[str, str, str]:
    if not isinstance(scope, MemoryScope):
        raise ValueError("an explicit MemoryScope is required")
    return scope.user_id, scope.character_id, scope.world_id


def _time_text(value: str | None) -> str:
    if value is None:
        value = datetime.now(UTC).isoformat(timespec="microseconds")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("memory timestamp must include a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def _parse_time(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid stored memory timestamp")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def _cjk_term(term: str) -> bool:
    return any("CJK" in unicode_name(char, "") for char in term)


def _tokens(value: str) -> set[str]:
    return {part.casefold() for part in _QUERY_TERMS.findall(value)}


class SQLiteMemoryStore(MemoryPort):
    """Bounded, owner-private SQLite evidence store; constructor performs no I/O."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        max_records: int = 2_048,
        max_entry_chars: int = 4_096,
    ) -> None:
        self.path = Path(path)
        if not self.path.is_absolute() or ".." in self.path.parts:
            raise ValueError("memory path must be absolute and normalized")
        if (isinstance(max_records, bool) or not isinstance(max_records, int)
                or not 1 <= max_records <= 10_000):
            raise ValueError("max_records must be an integer between 1 and 10000")
        if (isinstance(max_entry_chars, bool) or not isinstance(max_entry_chars, int)
                or not 128 <= max_entry_chars <= 16_384):
            raise ValueError("max_entry_chars must be an integer between 128 and 16384")
        self.max_records = max_records
        self.max_entry_chars = max_entry_chars
        self.max_events = max_records * 3
        self._connection: sqlite3.Connection | None = None
        self._read_only = False
        self._readonly_identity: tuple[int, int] | None = None
        self._existing_writer_identity: tuple[int, int] | None = None
        self._operation_deadline: float | None = None

    def open(self) -> SQLiteMemoryStore:
        if self._connection is not None:
            return self
        self._ensure_private_parent(create=True)
        created = False
        try:
            try:
                os.lstat(self.path)
            except FileNotFoundError:
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                flags |= getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(self.path, flags, 0o600)
                os.close(descriptor)
                created = True
            self._check_private_regular_file(self.path, expected_mode=0o600)
            for suffix in ("-journal", "-wal", "-shm"):
                sidecar = Path(str(self.path) + suffix)
                if os.path.lexists(sidecar):
                    self._check_private_regular_file(sidecar, expected_mode=0o600)

            if not created:
                self._verify_existing_database()

            connection = sqlite3.connect(
                str(self.path), timeout=0.1, isolation_level=None, check_same_thread=True
            )
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA busy_timeout=100")
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA trusted_schema=OFF")
                connection.execute("PRAGMA journal_mode=DELETE")
                connection.execute("PRAGMA synchronous=FULL")
                page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
                page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
                max_pages = max(1, (64 * 1024 * 1024) // page_size)
                if page_count > max_pages:
                    raise MemoryStoreFullError("local memory database exceeds its storage bound")
                connection.execute(f"PRAGMA max_page_count={max_pages}")
                if created:
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        for statement in _CREATE_SCHEMA:
                            connection.execute(statement)
                        connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
                        connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                        connection.execute("COMMIT")
                    except Exception:
                        connection.execute("ROLLBACK")
                        raise
                self._check_private_regular_file(self.path, expected_mode=0o600)
                self._connection = connection
            except Exception:
                connection.close()
                raise
            return self
        except (UnsafeMemoryPathError, UnknownMemoryDatabaseError, MemoryStoreFullError):
            raise
        except OSError:
            raise UnsafeMemoryPathError("unsafe local memory path") from None
        except sqlite3.Error:
            raise UnknownMemoryDatabaseError("local memory database is unavailable") from None

    def _ensure_private_parent(self, *, create: bool) -> None:
        current = Path(self.path.anchor)
        parts = self.path.parts[1:-1]
        euid = getattr(os, "geteuid", lambda: None)()
        for index, part in enumerate(parts):
            current = current / part
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                if not create:
                    raise UnsafeMemoryPathError("unsafe local memory path") from None
                try:
                    os.mkdir(current, 0o700)
                except FileExistsError:
                    pass
                info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise UnsafeMemoryPathError("unsafe local memory path")
            if info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
                raise UnsafeMemoryPathError("unsafe local memory path")
            if not create and euid is not None:
                if info.st_uid not in (0, euid):
                    raise UnsafeMemoryPathError("unsafe local memory path")
                if info.st_mode & stat.S_ISVTX and info.st_uid not in (0, euid):
                    raise UnsafeMemoryPathError("unsafe local memory path")
            if euid is not None and index == len(parts) - 1 and info.st_uid != euid:
                raise UnsafeMemoryPathError("unsafe local memory path")
            if index == len(parts) - 1 and stat.S_IMODE(info.st_mode) != 0o700:
                raise UnsafeMemoryPathError("unsafe local memory path")
        if not parts:
            raise UnsafeMemoryPathError("unsafe local memory path")

    def open_readonly(self, *, timeout_ms: int = 200) -> SQLiteMemoryStore:
        """Open an existing private store without creating or changing it.

        This is a separate explicit opt-in from :meth:`open`. It never creates
        parent directories, changes mode bits, changes journal mode, or runs
        schema DDL. The connection stays on the calling thread; the async
        wrapper invokes this only on its dedicated SQLite worker.
        """
        if self._connection is not None:
            if self._read_only:
                return self
            raise MemoryStoreClosedError("local memory store is already open writable")
        if (isinstance(timeout_ms, bool) or type(timeout_ms) is not int
                or not 10 <= timeout_ms <= 1_000):
            raise ValueError("timeout_ms must be an integer between 10 and 1000")

        deadline = time.monotonic() + timeout_ms / 1_000
        descriptor: int | None = None
        connection: sqlite3.Connection | None = None
        try:
            self._ensure_private_parent(create=False)
            self._check_private_regular_file(self.path, expected_mode=0o600)
            for suffix in ("-journal", "-wal", "-shm"):
                sidecar = Path(str(self.path) + suffix)
                if os.path.lexists(sidecar):
                    self._check_private_regular_file(sidecar, expected_mode=0o600)
                    if os.lstat(sidecar).st_size > 64 * 1024 * 1024:
                        raise MemoryStoreFullError(
                            "local memory database sidecar exceeds its storage bound"
                        )

            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(self.path, flags)
            opened_info = os.fstat(descriptor)
            path_info = os.lstat(self.path)
            euid = getattr(os, "geteuid", lambda: None)()
            if (not stat.S_ISREG(opened_info.st_mode)
                    or stat.S_ISLNK(path_info.st_mode)
                    or (opened_info.st_dev, opened_info.st_ino)
                    != (path_info.st_dev, path_info.st_ino)
                    or opened_info.st_nlink != 1
                    or euid is not None and opened_info.st_uid != euid
                    or stat.S_IMODE(opened_info.st_mode) != 0o600):
                raise UnsafeMemoryPathError("unsafe local memory path")
            if opened_info.st_size > 64 * 1024 * 1024:
                raise MemoryStoreFullError("local memory database exceeds its storage bound")

            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=ro", uri=True, timeout=0.05,
                isolation_level=None, check_same_thread=True,
            )
            connection.row_factory = sqlite3.Row
            # Publish only the handle needed by Connection.interrupt(); every
            # database operation and close remain on this opening thread.
            self._connection = connection
            self._read_only = True
            self._readonly_identity = (opened_info.st_dev, opened_info.st_ino)
            connection.execute("PRAGMA busy_timeout=50")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA query_only=ON")
            connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
            self._assert_readonly_path()
            self._verify_exact_existing_database(connection, deadline=deadline)
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            if page_count * page_size > 64 * 1024 * 1024:
                raise MemoryStoreFullError("local memory database exceeds its storage bound")
            self._assert_readonly_path()
            connection.execute("PRAGMA busy_timeout=0")
            return self
        except (UnsafeMemoryPathError, UnknownMemoryDatabaseError, MemoryStoreFullError,
                MemoryDeadlineExceededError):
            if connection is not None:
                connection.close()
            self._connection = None
            self._read_only = False
            self._readonly_identity = None
            raise
        except OSError:
            if connection is not None:
                connection.close()
            self._connection = None
            self._read_only = False
            self._readonly_identity = None
            raise UnsafeMemoryPathError("unsafe local memory path") from None
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            self._connection = None
            self._read_only = False
            self._readonly_identity = None
            if time.monotonic() >= deadline or "interrupt" in str(exc).casefold():
                raise MemoryDeadlineExceededError(
                    "local memory open exceeded its time bound"
                ) from None
            raise UnknownMemoryDatabaseError("unrecognized local memory database") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def open_existing_writable(self, *, timeout_ms: int = 200) -> SQLiteMemoryStore:
        """Open an existing private store for explicit local edits.

        Unlike :meth:`open`, this path never creates a database or parent,
        changes OS modes, changes journal mode, or runs schema DDL. The
        connection is owned by the calling thread; async management invokes it
        only on its dedicated writer worker.
        """
        if self._connection is not None:
            if self._existing_writer_identity is not None:
                return self
            raise MemoryStoreClosedError("local memory store is already open")
        if (isinstance(timeout_ms, bool) or type(timeout_ms) is not int
                or not 10 <= timeout_ms <= 1_000):
            raise ValueError("timeout_ms must be an integer between 10 and 1000")

        deadline = time.monotonic() + timeout_ms / 1_000
        descriptor: int | None = None
        connection: sqlite3.Connection | None = None
        try:
            self._ensure_private_parent(create=False)
            self._check_private_regular_file(self.path, expected_mode=0o600)
            for suffix in ("-journal", "-wal", "-shm"):
                sidecar = Path(str(self.path) + suffix)
                if os.path.lexists(sidecar):
                    self._check_private_regular_file(sidecar, expected_mode=0o600)
                    if os.lstat(sidecar).st_size > 64 * 1024 * 1024:
                        raise MemoryStoreFullError(
                            "local memory database sidecar exceeds its storage bound"
                        )

            flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(self.path, flags)
            opened_info = os.fstat(descriptor)
            path_info = os.lstat(self.path)
            euid = getattr(os, "geteuid", lambda: None)()
            identity = (opened_info.st_dev, opened_info.st_ino)
            if (not stat.S_ISREG(opened_info.st_mode)
                    or stat.S_ISLNK(path_info.st_mode)
                    or identity != (path_info.st_dev, path_info.st_ino)
                    or opened_info.st_nlink != 1
                    or euid is not None and opened_info.st_uid != euid
                    or stat.S_IMODE(opened_info.st_mode) != 0o600):
                raise UnsafeMemoryPathError("unsafe local memory path")
            if opened_info.st_size > 64 * 1024 * 1024:
                raise MemoryStoreFullError("local memory database exceeds its storage bound")

            # mode=rw is a second no-create guard if the path disappears after
            # the lstat/open checks. The path's private parent and inode are
            # checked again after SQLite opens it and before each store use.
            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=rw", uri=True, timeout=0.05,
                isolation_level=None, check_same_thread=True,
            )
            connection.row_factory = sqlite3.Row
            self._connection = connection
            self._existing_writer_identity = identity
            connection.execute("PRAGMA busy_timeout=50")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA synchronous=FULL")
            connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
            self._assert_existing_writer_path()
            self._verify_exact_existing_database(connection, deadline=deadline)
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            if page_count * page_size > 64 * 1024 * 1024:
                raise MemoryStoreFullError("local memory database exceeds its storage bound")
            max_pages = max(1, (64 * 1024 * 1024) // page_size)
            connection.execute(f"PRAGMA max_page_count={max_pages}")
            self._assert_existing_writer_path()
            connection.execute("PRAGMA busy_timeout=0")
            connection.set_progress_handler(None, 0)
            return self
        except (UnsafeMemoryPathError, UnknownMemoryDatabaseError, MemoryStoreFullError,
                MemoryDeadlineExceededError):
            if connection is not None:
                connection.close()
            self._connection = None
            self._existing_writer_identity = None
            raise
        except OSError:
            if connection is not None:
                connection.close()
            self._connection = None
            self._existing_writer_identity = None
            raise UnsafeMemoryPathError("unsafe local memory path") from None
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            self._connection = None
            self._existing_writer_identity = None
            if time.monotonic() >= deadline or "interrupt" in str(exc).casefold():
                raise MemoryDeadlineExceededError(
                    "local memory open exceeded its time bound"
                ) from None
            raise UnknownMemoryDatabaseError("unrecognized local memory database") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _verify_exact_existing_database(
        self, connection: sqlite3.Connection, *, deadline: float
    ) -> None:
        """Check identifiers, exact declared schema objects, columns and integrity."""
        try:
            app_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if app_id != _APPLICATION_ID or version != _SCHEMA_VERSION:
                raise UnknownMemoryDatabaseError("unrecognized local memory database")

            objects = {
                (row["type"], row["name"]): _normalized_schema_sql(row["sql"])
                for row in connection.execute(
                    "SELECT type,name,sql FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_autoindex_%' ORDER BY type,name"
                )
            }
            expected = dict(_EXPECTED_SCHEMA_OBJECTS)
            expected[("table", "sqlite_sequence")] = "CREATE TABLE sqlite_sequence(name,seq)"
            if objects != expected:
                raise UnknownMemoryDatabaseError("unrecognized local memory database")

            auto_indexes: dict[str, int] = {}
            for row in connection.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE name LIKE 'sqlite_autoindex_%'"
            ):
                if row["type"] != "index" or row["sql"] is not None:
                    raise UnknownMemoryDatabaseError("unrecognized local memory database")
                auto_indexes[row["tbl_name"]] = auto_indexes.get(row["tbl_name"], 0) + 1
            if auto_indexes != _EXPECTED_AUTOINDEX_COUNTS:
                raise UnknownMemoryDatabaseError("unrecognized local memory database")

            for table, columns in _TABLES.items():
                actual_columns = {
                    row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
                }
                if actual_columns != columns:
                    raise UnknownMemoryDatabaseError("unrecognized local memory database")
            check = connection.execute("PRAGMA quick_check(1)").fetchone()
            if time.monotonic() >= deadline:
                raise MemoryDeadlineExceededError("local memory open exceeded its time bound")
            if check is None or check[0] != "ok":
                raise UnknownMemoryDatabaseError("unrecognized local memory database")
        except (UnknownMemoryDatabaseError, MemoryDeadlineExceededError):
            raise
        except sqlite3.Error as exc:
            if time.monotonic() >= deadline or "interrupt" in str(exc).casefold():
                raise MemoryDeadlineExceededError(
                    "local memory open exceeded its time bound"
                ) from None
            raise UnknownMemoryDatabaseError("unrecognized local memory database") from None

    @staticmethod
    def _check_private_regular_file(path: Path, *, expected_mode: int) -> None:
        try:
            info = os.lstat(path)
        except OSError:
            raise UnsafeMemoryPathError("unsafe local memory path") from None
        euid = getattr(os, "geteuid", lambda: None)()
        if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)
                or euid is not None and info.st_uid != euid
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != expected_mode):
            raise UnsafeMemoryPathError("unsafe local memory path")

    def _verify_existing_database(self) -> None:
        try:
            uri = self.path.as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=0.1)
            try:
                app_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if app_id != _APPLICATION_ID or version != _SCHEMA_VERSION:
                    raise UnknownMemoryDatabaseError("unrecognized local memory database")
                actual_tables = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                }
                if actual_tables != set(_TABLES):
                    raise UnknownMemoryDatabaseError("unrecognized local memory database")
                for table, columns in _TABLES.items():
                    actual_columns = {
                        row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                    }
                    if actual_columns != columns:
                        raise UnknownMemoryDatabaseError("unrecognized local memory database")
                check = connection.execute("PRAGMA quick_check(1)").fetchone()
                if check is None or check[0] != "ok":
                    raise UnknownMemoryDatabaseError("unrecognized local memory database")
            finally:
                connection.close()
        except UnknownMemoryDatabaseError:
            raise
        except sqlite3.Error:
            raise UnknownMemoryDatabaseError("unrecognized local memory database") from None

    def close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.close()
        self._read_only = False
        self._readonly_identity = None
        self._existing_writer_identity = None
        self._operation_deadline = None

    def __enter__(self) -> SQLiteMemoryStore:
        return self.open()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise MemoryStoreClosedError("local memory store is not open")
        if self._read_only:
            self._ensure_private_parent(create=False)
            self._assert_readonly_path()
        elif self._existing_writer_identity is not None:
            self._ensure_private_parent(create=False)
            self._assert_existing_writer_path()
        return self._connection

    def _assert_readonly_path(self) -> None:
        identity = self._readonly_identity
        if identity is None:
            raise UnsafeMemoryPathError("unsafe local memory path")
        try:
            info = os.lstat(self.path)
        except OSError:
            raise UnsafeMemoryPathError("unsafe local memory path") from None
        euid = getattr(os, "geteuid", lambda: None)()
        if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)
                or (info.st_dev, info.st_ino) != identity
                or info.st_nlink != 1
                or euid is not None and info.st_uid != euid
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise UnsafeMemoryPathError("unsafe local memory path")

    def _assert_existing_writer_path(self) -> None:
        identity = self._existing_writer_identity
        if identity is None:
            raise UnsafeMemoryPathError("unsafe local memory path")
        try:
            info = os.lstat(self.path)
        except OSError:
            raise UnsafeMemoryPathError("unsafe local memory path") from None
        euid = getattr(os, "geteuid", lambda: None)()
        if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)
                or (info.st_dev, info.st_ino) != identity
                or info.st_nlink != 1
                or euid is not None and info.st_uid != euid
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise UnsafeMemoryPathError("unsafe local memory path")

    @contextmanager
    def _bounded_read_deadline(self, deadline: float) -> Iterator[None]:
        """Apply one outer SQLite VM deadline across a composed packet read."""
        connection = self._db()
        previous = self._operation_deadline
        if previous is not None:
            deadline = min(deadline, previous)
        self._operation_deadline = deadline
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
        try:
            yield
            if time.monotonic() >= deadline:
                raise MemoryDeadlineExceededError("local memory read exceeded its time bound")
        except sqlite3.OperationalError as exc:
            if time.monotonic() >= deadline or "interrupt" in str(exc).casefold():
                raise MemoryDeadlineExceededError(
                    "local memory read exceeded its time bound"
                ) from None
            raise
        finally:
            self._operation_deadline = previous
            if self._connection is not None:
                if previous is None:
                    connection.set_progress_handler(None, 0)
                else:
                    connection.set_progress_handler(
                        lambda: int(time.monotonic() >= previous), 100
                    )

    def scope_revision(self, scope: MemoryScope) -> int:
        """Return the latest append-only history sequence within this exact scope."""
        connection = self._db()
        self._check_operation_deadline()
        revision = self._scope_revision_on(connection, scope)
        self._check_operation_deadline()
        return revision

    @staticmethod
    def _scope_revision_on(connection: sqlite3.Connection, scope: MemoryScope,
                           *, before_seq: int | None = None) -> int:
        query = ("SELECT coalesce(max(seq),0) FROM memory_history "
                 "WHERE user_id=? AND character_id=? AND world_id=?")
        values: tuple[object, ...] = _scope_values(scope)
        if before_seq is not None:
            query += " AND seq<?"
            values += (before_seq,)
        row = connection.execute(query, values).fetchone()
        return int(row[0])

    @staticmethod
    def _encode_management_cursor(revision: int, seq: int) -> str:
        raw = f"{revision}:{seq}".encode("ascii")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_management_cursor(cursor: str) -> tuple[int, int]:
        if (type(cursor) is not str or not 1 <= len(cursor) <= 64
                or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None):
            raise ValueError("memory_cursor_invalid")
        try:
            raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
            text = raw.decode("ascii")
            revision_text, seq_text = text.split(":", 1)
            revision, seq = int(revision_text), int(seq_text)
        except (ValueError, UnicodeError, binascii.Error):
            raise ValueError("memory_cursor_invalid") from None
        if (revision < 0 or seq < 1 or text != f"{revision}:{seq}"
                or SQLiteMemoryStore._encode_management_cursor(revision, seq) != cursor):
            raise ValueError("memory_cursor_invalid")
        return revision, seq

    def management_list(self, scope: MemoryScope, *, limit: int = 20,
                        cursor: str | None = None) -> MemoryManagementPage:
        """Read one revision-bound page of current explicit USER_STATEMENT heads."""
        if not isinstance(scope, MemoryScope):
            raise ValueError("an explicit MemoryScope is required")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("management list limit must be between 1 and 50")
        if cursor is not None and type(cursor) is not str:
            raise ValueError("memory_cursor_invalid")
        decoded_cursor = self._decode_management_cursor(cursor) if cursor is not None else None
        connection = self._db()
        self._check_operation_deadline()
        connection.execute("BEGIN")
        try:
            revision = self._scope_revision_on(connection, scope)
            if decoded_cursor is not None:
                cursor_revision, before_seq = decoded_cursor
                if cursor_revision != revision:
                    raise MemoryRevisionChangedError("memory_management_page_stale")
            else:
                before_seq = None

            suppressed, _ = self._suppression_state(
                connection, scope, deadline=self._operation_deadline
            )
            page: list[tuple[MemoryManagementEntry, int]] = []
            page_size_bound = _MANAGEMENT_PAGE_ENVELOPE_BOUND_BYTES
            scan_before = before_seq
            more_visible = False
            stop_page = False
            exhausted = False
            batch_size = min(100, max(32, limit * 2))
            while len(page) <= limit and not exhausted and not stop_page:
                self._check_operation_deadline()
                scope_values = _scope_values(scope)
                query = """SELECT e.id,e.text,e.kind,e.source_version,e.recorded_at,h.seq
                           FROM memory_entries e JOIN memory_history h ON h.event_id=e.id
                           WHERE e.user_id=? AND e.character_id=? AND e.world_id=?
                             AND e.source='user_statement'
                             AND NOT EXISTS (
                               SELECT 1 FROM memory_links child
                               WHERE child.ancestor_id=e.id AND child.relation='supersedes'
                                 AND child.user_id=e.user_id AND child.character_id=e.character_id
                                 AND child.world_id=e.world_id)
                             AND h.user_id=? AND h.character_id=? AND h.world_id=?"""
                values: tuple[object, ...] = (*scope_values, *scope_values)
                if scan_before is not None:
                    query += " AND h.seq<?"
                    values += (scan_before,)
                query += " ORDER BY h.seq DESC LIMIT ?"
                values += (batch_size,)
                rows = connection.execute(query, values).fetchall()
                if not rows:
                    exhausted = True
                    break

                last_scanned = int(rows[-1]["seq"])
                forgets = self._active_management_forgets(
                    connection, scope, tuple(str(row["id"]) for row in rows)
                )
                for row in rows:
                    self._check_operation_deadline()
                    entry_id = str(row["id"])
                    tombstone = forgets.get(entry_id)
                    if entry_id in suppressed and tombstone is None:
                        continue
                    text = str(row["text"])
                    try:
                        text_bytes = len(text.encode("utf-8", errors="strict"))
                    except UnicodeEncodeError:
                        raise MemoryResultTooLargeError(
                            "local memory entry exceeds its display bound"
                        ) from None
                    if (len(text) > _MANAGEMENT_ENTRY_MAX_CHARS
                            or text_bytes > _MANAGEMENT_ENTRY_MAX_UTF8_BYTES):
                        raise MemoryResultTooLargeError(
                            "local memory entry exceeds its display bound"
                        )
                    # Reserve for worst-case JSON escaping (six ASCII bytes per
                    # code point), entry IDs/timestamps/tombstone metadata and
                    # the fixed page envelope. One domain-max entry always fits.
                    item_size_bound = (
                        6 * len(text) + _MANAGEMENT_ENTRY_METADATA_BOUND_BYTES
                    )
                    if (_MANAGEMENT_PAGE_ENVELOPE_BOUND_BYTES + item_size_bound
                            > _MANAGEMENT_PAGE_RESPONSE_BUDGET_BYTES):
                        raise MemoryResultTooLargeError(
                            "local memory entry exceeds its display bound"
                        )
                    if (len(page) >= limit
                            or page_size_bound + item_size_bound
                            > _MANAGEMENT_PAGE_RESPONSE_BUDGET_BYTES):
                        more_visible = True
                        stop_page = True
                        break
                    recorded_at = _parse_time(row["recorded_at"])
                    item = MemoryManagementEntry(
                        entry_id=entry_id,
                        text=text,
                        kind=MemoryKind(row["kind"]),
                        source_version=int(row["source_version"]),
                        recorded_at=recorded_at,
                        active=tombstone is None,
                        forget_event_id=tombstone[0] if tombstone is not None else None,
                        forgotten_at=tombstone[1] if tombstone is not None else None,
                    )
                    page.append((item, int(row["seq"])))
                    page_size_bound += item_size_bound
                scan_before = last_scanned
                if stop_page:
                    break
                if len(rows) < batch_size:
                    exhausted = True

            visible = page[:limit]
            next_cursor = (self._encode_management_cursor(revision, visible[-1][1])
                           if more_visible and visible else None)
            self._check_operation_deadline()
            connection.execute("COMMIT")
            return MemoryManagementPage(
                revision=revision,
                entries=tuple(item for item, _seq in visible),
                next_cursor=next_cursor,
            )
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    @staticmethod
    def _active_management_forgets(
        connection: sqlite3.Connection, scope: MemoryScope, entry_ids: tuple[str, ...]
    ) -> dict[str, tuple[str, str]]:
        """Return the newest still-active direct forget for each requested head."""
        if not entry_ids:
            return {}
        placeholders = ",".join("?" for _ in entry_ids)
        rows = connection.execute(
            f"""SELECT m.id,m.target_entry_id,m.recorded_at
                FROM memory_mutations m JOIN memory_history h ON h.event_id=m.id
                WHERE m.user_id=? AND m.character_id=? AND m.world_id=?
                  AND m.kind='forget' AND m.target_entry_id IN ({placeholders})
                  AND NOT EXISTS (
                    SELECT 1 FROM memory_mutations restored
                    WHERE restored.reverses_id=m.id AND restored.kind='restore')
                ORDER BY h.seq DESC""",
            (*_scope_values(scope), *entry_ids),
        ).fetchall()
        result: dict[str, tuple[str, str]] = {}
        for row in rows:
            target = str(row["target_entry_id"])
            result.setdefault(target, (str(row["id"]), _parse_time(row["recorded_at"])))
        return result

    def management_apply(
        self, scope: MemoryScope, command: MemoryManagementCommand
    ) -> MemoryManagementOperationResult:
        """CAS one explicit operation and its idempotency event atomically."""
        if not isinstance(scope, MemoryScope) or not isinstance(command, MemoryManagementCommand):
            raise ValueError("typed memory-management inputs are required")
        if command.confirmed is not True:
            raise ValueError("memory_management_confirmation_required")
        self._validate_management_command_shape(command)
        connection = self._db()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._check_operation_deadline()
            existing_event = connection.execute(
                """SELECT event_id,event_kind,seq FROM memory_history
                   WHERE event_id=? AND user_id=? AND character_id=? AND world_id=?""",
                (command.operation_id, *_scope_values(scope)),
            ).fetchone()
            if existing_event is not None:
                if not self._management_replay_matches(connection, scope, command, existing_event):
                    raise MemoryManagementOperationIdConflictError(
                        "operation_id_conflict"
                    )
                revision = self._scope_revision_on(connection, scope)
                self._check_operation_deadline()
                if existing_event["event_kind"] == "entry":
                    result = MemoryManagementOperationResult(
                        status="committed", operation_id=command.operation_id,
                        revision=revision, entry_id=command.operation_id, replayed=True,
                    )
                else:
                    result = MemoryManagementOperationResult(
                        status="committed", operation_id=command.operation_id,
                        revision=revision, event_id=command.operation_id, replayed=True,
                    )
                connection.execute("COMMIT")
                return result

            current_revision = self._scope_revision_on(connection, scope)
            self._check_operation_deadline()
            if current_revision != command.expected_revision:
                raise MemoryRevisionChangedError("memory_management_revision_stale")

            if command.operation is MemoryManagementOperation.RECORD:
                entry = MemoryEntry(
                    id=command.operation_id,
                    scope=scope,
                    source=MemorySource.USER_STATEMENT,
                    text=command.text or "",
                    source_event_id=f"local-management:{command.operation_id}",
                    source_version=1,
                    kind=command.kind or MemoryKind.EPISODIC,
                )
                self._privacy_check(entry)
                self._check_records_capacity(connection)
                self._check_events_capacity(connection)
                self._check_operation_deadline()
                self._insert_entry(connection, entry)
                result_entry_id, result_event_id = entry.id, None
            elif command.operation is MemoryManagementOperation.CORRECT:
                previous = self._get_entry(connection, scope, command.entry_id or "")
                if previous is None or previous.source is not MemorySource.USER_STATEMENT:
                    raise MemoryEntryNotFoundError(
                        "memory entry was not found in this scope"
                    )
                if self._has_superseder(connection, scope, previous.id):
                    raise MemoryConflictError("only the current statement head can be corrected")
                suppressed, _ = self._suppression_state(connection, scope)
                if previous.id in suppressed:
                    raise MemoryConflictError("a forgotten statement cannot be corrected")
                entry = MemoryEntry(
                    id=command.operation_id,
                    scope=scope,
                    source=MemorySource.USER_STATEMENT,
                    text=command.text or "",
                    source_event_id=previous.source_event_id,
                    source_version=previous.source_version + 1,
                    supersedes_id=previous.id,
                    depends_on=previous.depends_on,
                    kind=previous.kind,
                )
                self._privacy_check(entry)
                self._check_records_capacity(connection)
                self._check_events_capacity(connection)
                self._check_operation_deadline()
                self._insert_entry(connection, entry)
                result_entry_id, result_event_id = entry.id, None
            elif command.operation is MemoryManagementOperation.FORGET:
                target = self._get_entry(connection, scope, command.entry_id or "")
                if target is None or target.source is not MemorySource.USER_STATEMENT:
                    raise MemoryEntryNotFoundError("memory entry was not found in this scope")
                if self._has_superseder(connection, scope, target.id):
                    raise MemoryConflictError("only the current statement head can be forgotten")
                suppressed, _ = self._suppression_state(connection, scope)
                if target.id in suppressed:
                    raise MemoryConflictError("statement is already suppressed")
                self._check_events_capacity(connection)
                self._check_operation_deadline()
                mutation = MemoryMutation(
                    id=command.operation_id, scope=scope,
                    kind=MemoryMutationKind.FORGET, target_entry_id=target.id,
                    reverses_id=None,
                )
                self._insert_mutation(connection, mutation)
                result_entry_id, result_event_id = None, mutation.id
            else:
                forget_id = command.forget_event_id or ""
                row = connection.execute(
                    """SELECT * FROM memory_mutations
                       WHERE id=? AND user_id=? AND character_id=? AND world_id=?""",
                    (forget_id, *_scope_values(scope)),
                ).fetchone()
                if row is None:
                    raise MemoryEntryNotFoundError("forget event was not found in this scope")
                forget = self._row_mutation(row)
                if forget.kind is not MemoryMutationKind.FORGET:
                    raise MemoryConflictError("only a forget event can be restored")
                target = self._get_entry(connection, scope, forget.target_entry_id)
                if target is None or target.source is not MemorySource.USER_STATEMENT:
                    raise MemoryEntryNotFoundError("memory entry was not found in this scope")
                if self._has_superseder(connection, scope, target.id):
                    raise MemoryConflictError("only a current statement can be restored")
                if connection.execute(
                        "SELECT 1 FROM memory_mutations WHERE reverses_id=? LIMIT 1",
                        (forget.id,)).fetchone():
                    raise MemoryConflictError("forget event has already been restored")
                self._check_events_capacity(connection)
                self._check_operation_deadline()
                mutation = MemoryMutation(
                    id=command.operation_id, scope=scope,
                    kind=MemoryMutationKind.RESTORE, target_entry_id=target.id,
                    reverses_id=forget.id,
                )
                self._insert_mutation(connection, mutation)
                result_entry_id, result_event_id = None, mutation.id

            revision = self._scope_revision_on(connection, scope)
            self._check_operation_deadline()
            connection.execute("COMMIT")
            return MemoryManagementOperationResult(
                status="committed", operation_id=command.operation_id,
                revision=revision, entry_id=result_entry_id, event_id=result_event_id,
                replayed=False,
            )
        except (MemoryRevisionChangedError, MemoryDeadlineExceededError,
                MemoryManagementOperationIdConflictError,
                MemoryConflictError, MemoryEntryNotFoundError, MemoryPrivacyError,
                MemoryStoreFullError, ValueError):
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        except sqlite3.OperationalError as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if (self._operation_deadline is not None
                    and time.monotonic() >= self._operation_deadline):
                raise MemoryDeadlineExceededError(
                    "local memory operation exceeded its time bound"
                ) from None
            message = str(exc).casefold()
            if "busy" in message or "locked" in message:
                raise MemoryManagementBusyError("memory_management_busy") from None
            raise MemoryStoreError("local memory operation failed") from None
        except sqlite3.IntegrityError:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise MemoryManagementOperationIdConflictError("operation_id_conflict") from None
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if "full" in str(exc).casefold():
                raise MemoryStoreFullError("local memory reached its storage bound") from None
            raise MemoryStoreError("local memory operation failed") from None

    @staticmethod
    def _validate_management_command_shape(command: MemoryManagementCommand) -> None:
        operation = command.operation
        if operation is MemoryManagementOperation.RECORD:
            valid = (type(command.text) is str and bool(command.text.strip())
                     and isinstance(command.kind, MemoryKind)
                     and command.entry_id is None and command.forget_event_id is None)
        elif operation is MemoryManagementOperation.CORRECT:
            valid = (type(command.text) is str and bool(command.text.strip())
                     and command.kind is None and command.entry_id is not None
                     and command.forget_event_id is None)
        elif operation is MemoryManagementOperation.FORGET:
            valid = (command.text is None and command.kind is None
                     and command.entry_id is not None and command.forget_event_id is None)
        else:
            valid = (command.text is None and command.kind is None
                     and command.entry_id is None and command.forget_event_id is not None)
        if not valid:
            raise ValueError("memory_management_command_invalid")

    def _management_replay_matches(
        self, connection: sqlite3.Connection, scope: MemoryScope,
        command: MemoryManagementCommand, event: sqlite3.Row,
    ) -> bool:
        before_revision = self._scope_revision_on(
            connection, scope, before_seq=int(event["seq"])
        )
        if before_revision != command.expected_revision:
            return False
        event_kind = str(event["event_kind"])
        if command.operation in {
                MemoryManagementOperation.RECORD, MemoryManagementOperation.CORRECT}:
            if event_kind != "entry":
                return False
            entry = self._get_entry(connection, scope, command.operation_id)
            if entry is None or entry.source is not MemorySource.USER_STATEMENT:
                return False
            if entry.text != command.text:
                return False
            if command.operation is MemoryManagementOperation.RECORD:
                return (entry.kind is command.kind and entry.supersedes_id is None
                        and entry.source_event_id == f"local-management:{command.operation_id}"
                        and entry.source_version == 1)
            previous = self._get_entry(connection, scope, command.entry_id or "")
            return (previous is not None and previous.source is MemorySource.USER_STATEMENT
                    and entry.supersedes_id == previous.id
                    and entry.kind is previous.kind
                    and entry.source_event_id == previous.source_event_id
                    and entry.source_version == previous.source_version + 1)

        expected_kind = ("forget" if command.operation is MemoryManagementOperation.FORGET
                         else "restore")
        if event_kind != expected_kind:
            return False
        row = connection.execute(
            """SELECT * FROM memory_mutations
               WHERE id=? AND user_id=? AND character_id=? AND world_id=?""",
            (command.operation_id, *_scope_values(scope)),
        ).fetchone()
        if row is None:
            return False
        mutation = self._row_mutation(row)
        if command.operation is MemoryManagementOperation.FORGET:
            return (mutation.kind is MemoryMutationKind.FORGET
                    and mutation.target_entry_id == command.entry_id
                    and mutation.reverses_id is None)
        return (mutation.kind is MemoryMutationKind.RESTORE
                and mutation.reverses_id == command.forget_event_id)

    def _check_operation_deadline(self) -> None:
        deadline = self._operation_deadline
        if deadline is not None and time.monotonic() >= deadline:
            raise MemoryDeadlineExceededError("local memory read exceeded its time bound")

    def _check_events_capacity(self, connection: sqlite3.Connection) -> None:
        events = int(connection.execute("SELECT count(*) FROM memory_history").fetchone()[0])
        if events >= self.max_events:
            raise MemoryStoreFullError("local memory event history reached its configured bound")

    def _check_records_capacity(self, connection: sqlite3.Connection) -> None:
        records = int(connection.execute("SELECT count(*) FROM memory_entries").fetchone()[0])
        if records >= self.max_records:
            raise MemoryStoreFullError("local memory reached its configured record bound")

    def _privacy_check(self, entry: MemoryEntry) -> None:
        if len(entry.text) > self.max_entry_chars:
            raise MemoryStoreFullError("memory entry exceeds its configured text bound")
        try:
            filtered = PrivacyFilter().text(entry.text)
        except Exception:
            raise MemoryPrivacyError("memory text is ineligible for private storage") from None
        if filtered != entry.text:
            raise MemoryPrivacyError("memory text is ineligible for private storage")

    def append(self, entry: MemoryEntry) -> MemoryEntry:
        connection = self._db()
        if not isinstance(entry, MemoryEntry):
            raise ValueError("a typed MemoryEntry is required")
        if entry.recorded_at is None:
            entry = replace(entry, recorded_at=_time_text(None))
        self._privacy_check(entry)
        if entry.kind is MemoryKind.BOUNDARY and entry.source is not MemorySource.USER_STATEMENT:
            raise ValueError("BOUNDARY entries require the user_statement source")
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._find_source_key(connection, entry)
            if existing is not None:
                if self._same_payload(existing, entry):
                    connection.execute("COMMIT")
                    return existing
                raise MemoryConflictError("source event version already has a different memory record")
            self._check_records_capacity(connection)
            self._check_events_capacity(connection)
            if connection.execute("SELECT 1 FROM memory_entries WHERE id=?", (entry.id,)).fetchone():
                raise MemoryConflictError("memory entry ID already exists")
            prior_version = connection.execute(
                """SELECT id,source_version,source FROM memory_entries
                   WHERE user_id=? AND character_id=? AND world_id=? AND source_event_id=?
                   ORDER BY source_version DESC LIMIT 1""",
                (*_scope_values(entry.scope), entry.source_event_id),
            ).fetchone()
            if prior_version is not None:
                if (entry.source_version != int(prior_version["source_version"]) + 1
                        or entry.supersedes_id != prior_version["id"]
                        or entry.source.value != prior_version["source"]):
                    raise MemoryConflictError(
                        "a new source-event version must supersede its prior version"
                    )
            suppressed, _ = self._suppression_state(connection, entry.scope)
            if entry.supersedes_id is not None:
                parent = self._get_entry(connection, entry.scope, entry.supersedes_id)
                if parent is None:
                    raise MemoryEntryNotFoundError("superseded entry was not found in this scope")
                if self._has_superseder(connection, entry.scope, parent.id):
                    raise MemoryConflictError("only the current correction head can be superseded")
                if parent.id in suppressed:
                    raise MemoryConflictError("suppressed memory cannot be superseded")
                if entry.kind is not parent.kind:
                    raise ValueError("supersession preserves the original memory kind")
                if entry.source is not parent.source:
                    raise MemoryConflictError("a correction cannot change its source authority")
            for ancestor_id in entry.depends_on:
                ancestor = self._get_entry(connection, entry.scope, ancestor_id)
                if ancestor is None:
                    raise MemoryEntryNotFoundError("dependent source was not found in this scope")
                if ancestor_id in suppressed:
                    raise MemoryConflictError("suppressed memory cannot support a new derivation")
            self._insert_entry(connection, entry)
            connection.execute("COMMIT")
            return entry
        except (MemoryStoreError, ValueError):
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if "full" in str(exc).casefold():
                raise MemoryStoreFullError("local memory reached its storage bound") from None
            raise MemoryStoreError("local memory operation failed") from None

    @staticmethod
    def _same_payload(existing: MemoryEntry, candidate: MemoryEntry) -> bool:
        return (
            existing.scope == candidate.scope
            and existing.source is candidate.source
            and existing.text == candidate.text
            and existing.source_event_id == candidate.source_event_id
            and existing.source_version == candidate.source_version
            and existing.kind is candidate.kind
            and existing.supersedes_id == candidate.supersedes_id
            and existing.depends_on == candidate.depends_on
        )

    def _find_source_key(
        self, connection: sqlite3.Connection, entry: MemoryEntry
    ) -> MemoryEntry | None:
        values = (*_scope_values(entry.scope), entry.source_event_id, entry.source_version)
        row = connection.execute(
            """SELECT * FROM memory_entries
               WHERE user_id=? AND character_id=? AND world_id=?
                 AND source_event_id=? AND source_version=?""",
            values,
        ).fetchone()
        return self._row_entry(row) if row is not None else None

    def _insert_entry(self, connection: sqlite3.Connection, entry: MemoryEntry) -> None:
        scope_values = _scope_values(entry.scope)
        connection.execute(
            """INSERT INTO memory_entries(
                 id,user_id,character_id,world_id,source,kind,text,source_event_id,
                 source_version,recorded_at,supersedes_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (entry.id, *scope_values, entry.source.value, entry.kind.value, entry.text,
             entry.source_event_id, entry.source_version, _time_text(entry.recorded_at),
             entry.supersedes_id),
        )
        if entry.supersedes_id is not None:
            connection.execute(
                """INSERT INTO memory_links(memory_id,user_id,character_id,world_id,ancestor_id,relation)
                   VALUES(?,?,?,?,?,'supersedes')""",
                (entry.id, *scope_values, entry.supersedes_id),
            )
        for ancestor_id in entry.depends_on:
            connection.execute(
                """INSERT INTO memory_links(memory_id,user_id,character_id,world_id,ancestor_id,relation)
                   VALUES(?,?,?,?,?,'depends_on')""",
                (entry.id, *scope_values, ancestor_id),
            )
        connection.execute(
            """INSERT INTO memory_history(event_id,user_id,character_id,world_id,event_kind,recorded_at)
               VALUES(?,?,?,?, 'entry', ?)""",
            (entry.id, *scope_values, _time_text(entry.recorded_at)),
        )

    def supersede(
        self, scope: MemoryScope, old_id: str, replacement: MemoryEntry
    ) -> MemoryEntry:
        if not isinstance(replacement, MemoryEntry) or replacement.scope != scope:
            raise ValueError("replacement must belong to the requested scope")
        old_id = str(old_id)
        connection = self._db()
        old = self._get_entry(connection, scope, old_id)
        if old is None:
            raise MemoryEntryNotFoundError("superseded entry was not found in this scope")
        candidate = replace(replacement, supersedes_id=old.id, kind=old.kind)
        return self.append(candidate)

    def _get_entry(
        self, connection: sqlite3.Connection, scope: MemoryScope, entry_id: str
    ) -> MemoryEntry | None:
        row = connection.execute(
            """SELECT * FROM memory_entries
               WHERE id=? AND user_id=? AND character_id=? AND world_id=?""",
            (entry_id, *_scope_values(scope)),
        ).fetchone()
        return self._row_entry(row) if row is not None else None

    def _has_superseder(
        self, connection: sqlite3.Connection, scope: MemoryScope, entry_id: str
    ) -> bool:
        return connection.execute(
            """SELECT 1 FROM memory_links WHERE ancestor_id=? AND relation='supersedes'
               AND user_id=? AND character_id=? AND world_id=? LIMIT 1""",
            (entry_id, *_scope_values(scope)),
        ).fetchone() is not None

    def _suppression_state(
        self, connection: sqlite3.Connection, scope: MemoryScope,
        deadline: float | None = None,
    ) -> tuple[set[str], list[MemoryMutation]]:
        values = _scope_values(scope)
        mutations = [self._row_mutation(row) for row in connection.execute(
            """SELECT * FROM memory_mutations
               WHERE user_id=? AND character_id=? AND world_id=? ORDER BY rowid""",
            values,
        )]
        restored = {item.reverses_id for item in mutations
                    if item.kind is MemoryMutationKind.RESTORE}
        active = [item for item in mutations
                  if item.kind is MemoryMutationKind.FORGET and item.id not in restored]
        children: dict[str, set[str]] = {}
        for child, ancestor in connection.execute(
            """SELECT memory_id,ancestor_id FROM memory_links
               WHERE user_id=? AND character_id=? AND world_id=? AND relation='depends_on'""",
            values,
        ):
            children.setdefault(ancestor, set()).add(child)
        suppressed = {item.target_entry_id for item in active}
        stack = list(suppressed)
        while stack:
            if deadline is not None and time.monotonic() >= deadline:
                raise MemoryDeadlineExceededError("local memory query exceeded its time bound")
            parent_id = stack.pop()
            for child_id in children.get(parent_id, ()):
                if child_id not in suppressed:
                    suppressed.add(child_id)
                    stack.append(child_id)
        return suppressed, mutations

    def _snapshot(
        self, connection: sqlite3.Connection, scope: MemoryScope,
        deadline: float | None = None,
    ) -> tuple[tuple[MemoryEntry, ...], dict[str, MemoryEntry], set[str]]:
        rows = connection.execute(
            """SELECT * FROM memory_entries
               WHERE user_id=? AND character_id=? AND world_id=?""",
            _scope_values(scope),
        ).fetchall()
        links = connection.execute(
            """SELECT memory_id,ancestor_id,relation FROM memory_links
               WHERE user_id=? AND character_id=? AND world_id=?""",
            _scope_values(scope),
        ).fetchall()
        dependencies: dict[str, list[str]] = {}
        superseded: set[str] = set()
        for link in links:
            if deadline is not None and time.monotonic() >= deadline:
                raise MemoryDeadlineExceededError("local memory query exceeded its time bound")
            if link["relation"] == "depends_on":
                dependencies.setdefault(link["memory_id"], []).append(link["ancestor_id"])
            else:
                superseded.add(link["ancestor_id"])
        entries: dict[str, MemoryEntry] = {}
        for row in rows:
            if deadline is not None and time.monotonic() >= deadline:
                raise MemoryDeadlineExceededError("local memory query exceeded its time bound")
            entries[row["id"]] = self._row_entry(
                row, depends_on=tuple(sorted(dependencies.get(row["id"], ())))
            )
        suppressed, _ = self._suppression_state(connection, scope, deadline)
        heads = [entry for entry_id, entry in entries.items()
                 if entry_id not in superseded and entry_id not in suppressed]
        current = tuple(sorted(heads, key=lambda item: (item.recorded_at, item.id)))
        return current, entries, suppressed

    @staticmethod
    def _obsolete_ancestors(
        entry: MemoryEntry,
        entries: dict[str, MemoryEntry],
        suppressed: set[str],
        *,
        include_interpretations: bool,
    ) -> tuple[MemoryEntry, ...]:
        ancestors: list[MemoryEntry] = []
        visited: set[str] = set()
        current_id = entry.supersedes_id
        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            current = entries.get(current_id)
            if current is None:
                break
            if (current.id not in suppressed and
                    (include_interpretations or current.source is not MemorySource.INTERPRETATION)):
                ancestors.append(current)
            current_id = current.supersedes_id
        return tuple(ancestors)

    def recall(self, query: MemoryQuery) -> tuple[MemoryEntry, ...]:
        if not isinstance(query, MemoryQuery):
            raise ValueError("a typed MemoryQuery is required")
        connection = self._db()
        deadline = time.monotonic() + query.timeout_ms / 1_000
        if self._operation_deadline is not None:
            deadline = min(deadline, self._operation_deadline)
        remaining_ms = int(max(0, (deadline - time.monotonic()) * 1_000))
        if remaining_ms <= 0:
            raise MemoryDeadlineExceededError("local memory query exceeded its time bound")
        connection.execute(f"PRAGMA busy_timeout={min(query.timeout_ms, 100, remaining_ms)}")
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
        try:
            connection.execute("BEGIN")
            try:
                candidates, entries, suppressed = self._snapshot(
                    connection, query.scope, deadline
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            query_text = " ".join(query.text.casefold().split())
            query_terms = _tokens(query.text)
            ranked: list[tuple[int, int, int, str, str, MemoryEntry]] = []
            for entry in candidates:
                if time.monotonic() >= deadline:
                    raise MemoryDeadlineExceededError("local memory query exceeded its time bound")
                if entry.source is MemorySource.INTERPRETATION and not query.include_interpretations:
                    continue
                versions = (entry,) + self._obsolete_ancestors(
                    entry, entries, suppressed,
                    include_interpretations=query.include_interpretations,
                )
                phrase = matched = 0
                for version in versions:
                    if time.monotonic() >= deadline:
                        raise MemoryDeadlineExceededError(
                            "local memory query exceeded its time bound"
                        )
                    normalized = " ".join(version.text.casefold().split())
                    version_phrase = int(bool(query_text) and query_text in normalized)
                    version_terms = _tokens(version.text)
                    version_matched = sum(
                        1 for term in query_terms
                        if term in version_terms or _cjk_term(term) and term in normalized
                    )
                    if (version_phrase, version_matched) > (phrase, matched):
                        phrase, matched = version_phrase, version_matched
                if not phrase and not matched:
                    continue
                source_rank = int(entry.source is MemorySource.INTERPRETATION)
                ranked.append((phrase, matched, source_rank,
                               _time_text(entry.recorded_at), entry.id, entry))
            ranked.sort(key=lambda row: (
                -row[0], -row[1], row[2], -_time_key(row[3]), row[4]
            ))
            results: list[MemoryEntry] = []
            chars = 0
            for _, _, _, _, _, entry in ranked:
                if time.monotonic() >= deadline:
                    raise MemoryDeadlineExceededError("local memory query exceeded its time bound")
                if len(results) >= query.limit:
                    break
                if chars + len(entry.text) > query.max_chars:
                    continue
                results.append(entry)
                chars += len(entry.text)
            return tuple(results)
        except sqlite3.OperationalError as exc:
            message = str(exc).casefold()
            error_code = getattr(exc, "sqlite_errorcode", None)
            primary_code = error_code & 0xFF if isinstance(error_code, int) else None
            lock_error = primary_code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
            if (time.monotonic() >= deadline or "interrupt" in message
                    or lock_error or "locked" in message or "busy" in message):
                raise MemoryDeadlineExceededError(
                    "local memory query exceeded its time bound"
                ) from None
            raise MemoryStoreError("local memory query failed") from None
        except sqlite3.Error:
            raise MemoryStoreError("local memory query failed") from None
        finally:
            if self._operation_deadline is None:
                connection.set_progress_handler(None, 0)
            else:
                outer_deadline = self._operation_deadline
                connection.set_progress_handler(
                    lambda: int(time.monotonic() >= outer_deadline), 100
                )
            reset_busy_timeout = (0 if self._read_only or self._existing_writer_identity is not None
                                  else 100)
            connection.execute(f"PRAGMA busy_timeout={reset_busy_timeout}")

    @contextmanager
    def _bounded_management_deadline(self, deadline: float) -> Iterator[None]:
        """Apply one short no-retry SQLite VM deadline to one management write."""
        connection = self._db()
        previous = self._operation_deadline
        if previous is not None:
            deadline = min(deadline, previous)
        self._operation_deadline = deadline
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
        connection.execute("PRAGMA busy_timeout=0")
        try:
            yield
            self._check_operation_deadline()
        except sqlite3.OperationalError as exc:
            if time.monotonic() >= deadline or "interrupt" in str(exc).casefold():
                raise MemoryDeadlineExceededError(
                    "local memory operation exceeded its time bound"
                ) from None
            raise
        finally:
            self._operation_deadline = previous
            if self._connection is not None:
                if previous is None:
                    connection.set_progress_handler(None, 0)
                else:
                    connection.set_progress_handler(
                        lambda: int(time.monotonic() >= previous), 100
                    )
                connection.execute("PRAGMA busy_timeout=0")

    def current_constraints(self, scope: MemoryScope) -> tuple[MemoryEntry, ...]:
        connection = self._db()
        self._check_operation_deadline()
        connection.execute("BEGIN")
        try:
            boundaries = tuple(entry for entry in self._snapshot(
                connection, scope, self._operation_deadline
            )[0]
                               if entry.kind is MemoryKind.BOUNDARY)
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        chars = sum(len(entry.text) for entry in boundaries)
        self._check_operation_deadline()
        if len(boundaries) > _MAX_CURRENT_BOUNDARIES or chars > _MAX_CURRENT_BOUNDARY_CHARS:
            raise MemoryResultTooLargeError("effective boundary set exceeds its recall bound")
        return boundaries

    def forget(self, scope: MemoryScope, entry_id: str) -> MemoryMutation:
        connection = self._db()
        entry_id = str(entry_id)
        mutation = MemoryMutation(
            id=uuid4().hex,
            scope=scope,
            kind=MemoryMutationKind.FORGET,
            target_entry_id=entry_id,
            reverses_id=None,
            recorded_at=_time_text(None),
        )
        connection.execute("BEGIN IMMEDIATE")
        try:
            if self._get_entry(connection, scope, entry_id) is None:
                raise MemoryEntryNotFoundError("memory entry was not found in this scope")
            self._check_events_capacity(connection)
            self._insert_mutation(connection, mutation)
            connection.execute("COMMIT")
            return mutation
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def undo_forget(self, scope: MemoryScope, forget_event_id: str) -> MemoryMutation:
        connection = self._db()
        forget_event_id = str(forget_event_id)
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                """SELECT * FROM memory_mutations
                   WHERE id=? AND user_id=? AND character_id=? AND world_id=?""",
                (forget_event_id, *_scope_values(scope)),
            ).fetchone()
            if row is None:
                raise MemoryEntryNotFoundError("active forget event was not found in this scope")
            forget = self._row_mutation(row)
            if forget.kind is not MemoryMutationKind.FORGET:
                raise MemoryConflictError("only a forget event can be restored")
            if connection.execute(
                "SELECT 1 FROM memory_mutations WHERE reverses_id=?", (forget.id,)
            ).fetchone():
                raise MemoryConflictError("forget event has already been restored")
            self._check_events_capacity(connection)
            mutation = MemoryMutation(
                id=uuid4().hex,
                scope=scope,
                kind=MemoryMutationKind.RESTORE,
                target_entry_id=forget.target_entry_id,
                reverses_id=forget.id,
                recorded_at=_time_text(None),
            )
            self._insert_mutation(connection, mutation)
            connection.execute("COMMIT")
            return mutation
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _insert_mutation(self, connection: sqlite3.Connection, mutation: MemoryMutation) -> None:
        scope_values = _scope_values(mutation.scope)
        connection.execute(
            """INSERT INTO memory_mutations(
                 id,user_id,character_id,world_id,kind,target_entry_id,reverses_id,recorded_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (mutation.id, *scope_values, mutation.kind.value, mutation.target_entry_id,
             mutation.reverses_id, _time_text(mutation.recorded_at)),
        )
        connection.execute(
            """INSERT INTO memory_history(event_id,user_id,character_id,world_id,event_kind,recorded_at)
               VALUES(?,?,?,?,?,?)""",
            (mutation.id, *scope_values, mutation.kind.value, _time_text(mutation.recorded_at)),
        )

    def history(
        self, scope: MemoryScope, entry_id: str | None = None, limit: int = 100
    ) -> tuple[MemoryHistoryItem, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise ValueError("history limit must be an integer between 1 and 1000")
        connection = self._db()
        connection.execute("BEGIN")
        try:
            scope_values = _scope_values(scope)
            history_rows = connection.execute(
                """SELECT event_id,event_kind FROM memory_history
                   WHERE user_id=? AND character_id=? AND world_id=? ORDER BY seq""",
                scope_values,
            ).fetchall()
            if entry_id is None:
                rows = history_rows[:limit]
            else:
                requested_id = str(entry_id)
                entry = self._get_entry(connection, scope, requested_id)
                mutation = connection.execute(
                    """SELECT * FROM memory_mutations
                       WHERE id=? AND user_id=? AND character_id=? AND world_id=?""",
                    (requested_id, *scope_values),
                ).fetchone()
                target_id = entry.id if entry is not None else (
                    mutation["target_entry_id"] if mutation is not None else None
                )
                if target_id is None:
                    rows = []
                else:
                    links = connection.execute(
                        """SELECT memory_id,ancestor_id FROM memory_links
                           WHERE user_id=? AND character_id=? AND world_id=?
                             AND relation='supersedes'""",
                        scope_values,
                    ).fetchall()
                    adjacent: dict[str, set[str]] = {}
                    for child_id, ancestor_id in links:
                        adjacent.setdefault(child_id, set()).add(ancestor_id)
                        adjacent.setdefault(ancestor_id, set()).add(child_id)
                    lineage = {target_id}
                    pending = [target_id]
                    while pending:
                        current = pending.pop()
                        for neighbour in adjacent.get(current, ()):
                            if neighbour not in lineage:
                                lineage.add(neighbour)
                                pending.append(neighbour)
                    mutation_targets = {
                        row[0] for row in connection.execute(
                            """SELECT id,target_entry_id FROM memory_mutations
                               WHERE user_id=? AND character_id=? AND world_id=?""",
                            scope_values,
                        ) if row[1] in lineage
                    }
                    if mutation is not None:
                        mutation_targets.add(requested_id)
                    related_ids = lineage | mutation_targets
                    rows = [row for row in history_rows if row[0] in related_ids]
                    if len(rows) > limit:
                        raise MemoryResultTooLargeError(
                            "correction history exceeds its configured result bound"
                        )
            items: list[MemoryHistoryItem] = []
            for event_id, event_kind in rows:
                if event_kind == "entry":
                    row = connection.execute(
                        """SELECT * FROM memory_entries WHERE id=? AND user_id=?
                           AND character_id=? AND world_id=?""",
                        (event_id, *scope_values),
                    ).fetchone()
                    if row is not None:
                        items.append(self._row_entry(row))
                else:
                    row = connection.execute(
                        """SELECT * FROM memory_mutations WHERE id=? AND user_id=?
                           AND character_id=? AND world_id=?""",
                        (event_id, *scope_values),
                    ).fetchone()
                    if row is not None:
                        items.append(self._row_mutation(row))
            connection.execute("COMMIT")
            return tuple(items)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _row_entry(
        self, row: sqlite3.Row, *, depends_on: tuple[str, ...] | None = None
    ) -> MemoryEntry:
        scope = MemoryScope(row["user_id"], row["character_id"], row["world_id"])
        supersedes_id = row["supersedes_id"]
        if depends_on is None:
            if self._connection is None:
                depends_on = ()
            else:
                depends_on = tuple(
                link[0] for link in self._connection.execute(
                    """SELECT ancestor_id FROM memory_links
                       WHERE memory_id=? AND relation='depends_on' ORDER BY ancestor_id""",
                    (row["id"],),
                )
                )
        return MemoryEntry(
            id=row["id"], scope=scope, source=MemorySource(row["source"]),
            text=row["text"], source_event_id=row["source_event_id"],
            source_version=int(row["source_version"]), recorded_at=_parse_time(row["recorded_at"]),
            supersedes_id=supersedes_id, depends_on=depends_on,
            kind=MemoryKind(row["kind"]),
        )

    @staticmethod
    def _row_mutation(row: sqlite3.Row) -> MemoryMutation:
        return MemoryMutation(
            id=row["id"],
            scope=MemoryScope(row["user_id"], row["character_id"], row["world_id"]),
            kind=MemoryMutationKind(row["kind"]), target_entry_id=row["target_entry_id"],
            reverses_id=row["reverses_id"], recorded_at=_parse_time(row["recorded_at"]),
        )

def _time_key(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()
