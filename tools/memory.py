"""Explicit, local-only workflow for source-linked memory records."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from mira.adapters.memory.errors import (  # noqa: E402
    MemoryEntryNotFoundError,
    MemoryPrivacyError,
    MemoryStoreError,
    MemoryStoreFullError,
    UnsafeMemoryPathError,
    UnknownMemoryDatabaseError,
)
from mira.adapters.memory.sqlite import SQLiteMemoryStore  # noqa: E402
from mira.application.memory_context import (  # noqa: E402
    MemoryContextError,
    RequiredMemoryContextOverflow,
    build_context_packet,
)
from mira.domain.memory import (  # noqa: E402
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


MAX_MANIFEST_BYTES = 16_384
MAX_HISTORY_LIMIT = 1_000
MAX_RECALL_LIMIT = 8
MAX_RECALL_CHARS = 4_000
MAX_STATEMENT_CHARS = 4_096
MAX_QUERY_CHARS = 256


class _CliError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # noqa: ARG002
        # argparse's default diagnostic echoes the rejected argument. User text
        # is intentionally never accepted as an option, but keep failures safe.
        raise _CliError("arguments_invalid")


def _parser() -> _SafeArgumentParser:
    parser = _SafeArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", parser_class=_SafeArgumentParser)

    def common(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--db", required=True, type=str,
                         help="absolute path to an owner-private SQLite file outside the checkout")
        sub.add_argument("--scope-config", required=True, type=str,
                         help="absolute path to a private server-owned scope JSON file")
        sub.add_argument("--scope", required=True, type=str,
                         help="scope alias resolved from the scope config")
        sub.add_argument("--consent-local-memory", action="store_true",
                         help="explicitly allow this command to access the selected local scope")
        return sub

    sub = common("inspect", "read the bounded provenance and mutation history")
    sub.add_argument("--limit", type=int, default=100, choices=range(1, MAX_HISTORY_LIMIT + 1),
                     metavar="1..1000")
    sub.add_argument("--entry-id", type=str,
                     help="limit history to one scoped entry and its direct mutations")

    sub = common("record", "record one explicitly confirmed user statement")
    sub.add_argument("--kind", required=True, choices=("boundary", "episodic"),
                     help="operator-selected classification; never inferred from text")

    sub = common("correct", "supersede one user-statement entry with a correction")
    sub.add_argument("--entry-id", required=True, type=str)

    sub = common("forget", "reversibly suppress one user-statement entry from recall")
    sub.add_argument("--entry-id", required=True, type=str)

    sub = common("restore", "undo one active soft-forget event")
    sub.add_argument("--mutation-id", required=True, type=str)

    sub = common("recall", "recall bounded matching local candidates")
    sub.add_argument("--timeout-ms", type=int, default=200, choices=range(10, 1001),
                     metavar="10..1000")

    sub = common("context", "print one bounded, immutable memory context preview")
    sub.add_argument("--timeout-ms", type=int, default=200, choices=range(10, 1001),
                     metavar="10..1000")
    sub.add_argument("--max-packet-bytes", type=int, default=8_192,
                     choices=range(1_024, 32_769), metavar="1024..32768")
    return parser


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _error(code: str) -> int:
    _emit({"ok": False, "error": code})
    return 2


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _external_private_path(raw: str, *, purpose: str) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise _CliError(f"{purpose}_path_invalid")
    lexical = Path(os.path.abspath(candidate))
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        raise _CliError(f"{purpose}_path_invalid") from None
    if _inside(lexical, ROOT) or _inside(resolved, ROOT):
        raise _CliError(f"{purpose}_must_be_outside_checkout")
    return lexical


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON value")


def _read_private_scope_config(path: Path, alias: str) -> MemoryScope:
    if not alias or len(alias) > 64 or any(ch.isspace() for ch in alias):
        raise _CliError("scope_unavailable")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current = current / part
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise _CliError("scope_config_not_private")
        descriptor = os.open(path, flags)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_MANIFEST_BYTES:
                raise _CliError("scope_config_invalid")
            if os.name == "posix":
                euid = getattr(os, "geteuid", lambda: -1)()
                if info.st_uid != euid or stat.S_IMODE(info.st_mode) & 0o077:
                    raise _CliError("scope_config_not_private")
                parent_info = os.stat(path.parent, follow_symlinks=False)
                if (not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != euid
                        or stat.S_IMODE(parent_info.st_mode) & 0o077):
                    raise _CliError("scope_config_not_private")
            raw = os.read(descriptor, MAX_MANIFEST_BYTES + 1)
        finally:
            os.close(descriptor)
    except _CliError:
        raise
    except OSError:
        raise _CliError("scope_config_unavailable") from None
    if len(raw) > MAX_MANIFEST_BYTES:
        raise _CliError("scope_config_invalid")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=_reject_json_constant)
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise _CliError("scope_config_invalid") from None
    if not isinstance(document, dict) or set(document) != {"version", "scopes"}:
        raise _CliError("scope_config_invalid")
    if document["version"] != 1 or type(document["version"]) is not int:
        raise _CliError("scope_config_invalid")
    rows = document["scopes"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise _CliError("scope_config_invalid")
    found: MemoryScope | None = None
    aliases: set[str] = set()
    try:
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "name", "user_id", "character_id", "world_id"
            }:
                raise ValueError("unexpected scope shape")
            name = row["name"]
            if (not isinstance(name, str) or not name or len(name) > 64
                    or any(ch.isspace() for ch in name) or name in aliases):
                raise ValueError("invalid scope alias")
            aliases.add(name)
            scope = MemoryScope(row["user_id"], row["character_id"], row["world_id"])
            if name == alias:
                found = scope
    except (TypeError, ValueError):
        raise _CliError("scope_config_invalid") from None
    if found is None:
        raise _CliError("scope_unavailable")
    return found


def _validate_db_path(path: Path) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError:
        raise _CliError("memory_path_unavailable") from None
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise _CliError("memory_path_unsafe")
    if info.st_nlink != 1:
        raise _CliError("memory_path_unsafe")


def _retention_notice(args: argparse.Namespace, *, write: bool = False) -> None:
    action = "write" if write else "read"
    print(
        "LOCAL MEMORY ACCESS\n"
        f"operation: {action}\n"
        f"scope alias: {args.scope}\n"
        f"database: {args._db_path}\n"
        "scope identifiers remain in the private scope config and are not emitted in context packets\n"
        "exact source text remains in this local SQLite file until the file is removed; soft-forget "
        "only blocks recall and is reversible; no remote service is contacted",
        file=sys.stderr,
        flush=True,
    )


def _open_store(args: argparse.Namespace, *, create: bool) -> SQLiteMemoryStore:
    path: Path = args._db_path
    if not create and not path.exists():
        raise _CliError("memory_database_missing")
    _validate_db_path(path)
    try:
        return SQLiteMemoryStore(path).open()
    except UnsafeMemoryPathError:
        raise _CliError("memory_path_unsafe") from None
    except UnknownMemoryDatabaseError:
        raise _CliError("memory_database_unrecognized") from None
    except MemoryStoreError:
        raise _CliError("memory_operation_failed") from None


def _input_line(prompt: str, *, max_chars: int) -> str:
    print(prompt, file=sys.stderr, flush=True)
    value = sys.stdin.readline()
    if value == "":
        raise _CliError("input_required")
    value = value.rstrip("\r\n")
    if not value.strip() or len(value) > max_chars:
        raise _CliError("input_invalid")
    return value


def _input_optional_lines(prompt: str) -> tuple[str, ...]:
    print(prompt, file=sys.stderr, flush=True)
    values: list[str] = []
    while True:
        line = sys.stdin.readline()
        if line == "" or line in ("\n", "\r\n"):
            return tuple(values)
        value = line.rstrip("\r\n")
        if (not value.strip() or len(value) > 2_048 or len(values) >= 16):
            raise _CliError("input_invalid")
        values.append(value)


def _confirm(token: str, action: str) -> None:
    print(action, file=sys.stderr, flush=True)
    value = sys.stdin.readline()
    if value.rstrip("\r\n") != token:
        raise _CliError("confirmation_declined")


def _entry_dict(entry: MemoryEntry, *, status: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "item_type": "entry",
        "id": entry.id,
        "source": entry.source.value,
        "kind": entry.kind.value,
        "text": entry.text,
        "source_event_id": entry.source_event_id,
        "source_version": entry.source_version,
        "recorded_at": entry.recorded_at,
        "supersedes_id": entry.supersedes_id,
        "depends_on": list(entry.depends_on),
    }
    if status is not None:
        result["status"] = status
    return result


def _mutation_dict(mutation: MemoryMutation, *, status: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "item_type": "mutation",
        "id": mutation.id,
        "kind": mutation.kind.value,
        "target_entry_id": mutation.target_entry_id,
        "reverses_id": mutation.reverses_id,
        "recorded_at": mutation.recorded_at,
    }
    if status is not None:
        result["status"] = status
    return result


def _history_status(items: Sequence[MemoryHistoryItem]) -> dict[str, str]:
    entries = {item.id: item for item in items if isinstance(item, MemoryEntry)}
    mutations = [item for item in items if isinstance(item, MemoryMutation)]
    superseded = {item.supersedes_id for item in entries.values()
                  if item.supersedes_id is not None}
    restored = {item.reverses_id for item in mutations
                if item.kind is MemoryMutationKind.RESTORE}
    forgotten = {item.target_entry_id for item in mutations
                 if item.kind is MemoryMutationKind.FORGET and item.id not in restored}
    suppressed = set(forgotten)
    changed = True
    while changed:
        changed = False
        for item in entries.values():
            if item.id not in suppressed and any(parent in suppressed for parent in item.depends_on):
                suppressed.add(item.id)
                changed = True
    statuses = {}
    for entry_id in entries:
        if entry_id in suppressed and entry_id in superseded:
            statuses[entry_id] = "soft_forgotten_and_superseded"
        elif entry_id in suppressed:
            statuses[entry_id] = "dependency_suppressed" if entry_id not in forgotten else "soft_forgotten"
        elif entry_id in superseded:
            statuses[entry_id] = "superseded"
        else:
            statuses[entry_id] = "current_head"
    return statuses


def _inspection_items(
    items: Sequence[MemoryHistoryItem], *, status_complete: bool
) -> list[dict[str, object]]:
    statuses = _history_status(items)
    restored = {item.reverses_id for item in items if isinstance(item, MemoryMutation)
                and item.kind is MemoryMutationKind.RESTORE}
    rendered: list[dict[str, object]] = []
    for item in items:
        if isinstance(item, MemoryEntry):
            status = statuses.get(item.id, "unknown") if status_complete else "unknown_partial_history"
            rendered.append(_entry_dict(item, status=status))
        elif item.kind is MemoryMutationKind.FORGET:
            status = (("reversed" if item.id in restored else "active")
                      if status_complete else "unknown_partial_history")
            rendered.append(_mutation_dict(item, status=status))
        else:
            status = "applied" if status_complete else "unknown_partial_history"
            rendered.append(_mutation_dict(item, status=status))
    return rendered


def _target_entry(store: SQLiteMemoryStore, scope: MemoryScope, entry_id: str) -> MemoryEntry:
    items = store.history(scope, entry_id=entry_id, limit=MAX_HISTORY_LIMIT)
    found = next((item for item in items if isinstance(item, MemoryEntry) and item.id == entry_id), None)
    if found is None:
        raise _CliError("entry_unavailable")
    if found.source is not MemorySource.USER_STATEMENT:
        raise _CliError("entry_not_cli_managed")
    return found


def _execute(args: argparse.Namespace, scope: MemoryScope) -> int:
    command = args.command
    if command == "record":
        _retention_notice(args, write=True)
        value = _input_line(
            "Enter one exact statement explicitly confirmed by the user; do not paraphrase:",
            max_chars=MAX_STATEMENT_CHARS,
        )
        print("Statement preview follows; text will not be echoed in JSON or diagnostics:",
              file=sys.stderr, flush=True)
        print(value, file=sys.stderr, flush=True)
        _confirm("STORE", "Type STORE to persist this exact user statement locally (anything else cancels):")
        entry = MemoryEntry(
            id=uuid4().hex,
            scope=scope,
            source=MemorySource.USER_STATEMENT,
            kind=MemoryKind(args.kind),
            text=value,
            source_event_id=f"local-cli-{uuid4().hex}",
            source_version=1,
        )
        with _open_store(args, create=True) as store:
            stored = store.append(entry)
        _emit({
            "ok": True,
            "operation": "record",
            "entry": {
                "id": stored.id,
                "source": stored.source.value,
                "kind": stored.kind.value,
                "source_event_id": stored.source_event_id,
                "source_version": stored.source_version,
                "supersedes_id": stored.supersedes_id,
            },
            "retention": "local_soft_forget_only",
        })
        return 0

    _retention_notice(args, write=command in {"correct", "forget", "restore"})
    if command == "inspect":
        with _open_store(args, create=False) as store:
            if args.entry_id is None:
                probe_limit = min(args.limit + 1, MAX_HISTORY_LIMIT)
                items = store.history(scope, limit=probe_limit)
                partial = len(items) > args.limit or (
                    args.limit == MAX_HISTORY_LIMIT and len(items) == MAX_HISTORY_LIMIT
                )
                if partial:
                    items = items[:args.limit]
            else:
                items = store.history(scope, entry_id=args.entry_id, limit=args.limit)
                partial = False
        _emit({
            "ok": True,
            "operation": "inspect",
            "items": _inspection_items(items, status_complete=not partial),
            "partial_history": partial,
        })
        return 0

    if command == "recall":
        query = _input_line("Recall query (one line, max 256 characters):", max_chars=MAX_QUERY_CHARS)
        with _open_store(args, create=False) as store:
            entries = store.recall(MemoryQuery(
                scope=scope,
                text=query,
                limit=MAX_RECALL_LIMIT,
                max_chars=MAX_RECALL_CHARS,
                include_interpretations=False,
                timeout_ms=args.timeout_ms,
            ))
        _emit({"ok": True, "operation": "recall", "items": [_entry_dict(item) for item in entries]})
        return 0

    if command == "context":
        request = _input_line("Current request text (one line, max 256 characters):",
                              max_chars=MAX_QUERY_CHARS)
        caller_boundaries = _input_optional_lines(
            "Optional explicit current boundary lines, one per line; blank line ends this section:")
        caller_corrections = _input_optional_lines(
            "Optional explicit current correction lines, one per line; blank line ends this section:")
        with _open_store(args, create=False) as store:
            packet = build_context_packet(
                store,
                scope,
                request,
                caller_boundaries=caller_boundaries,
                caller_corrections=caller_corrections,
                max_packet_bytes=args.max_packet_bytes,
                timeout_ms=args.timeout_ms,
            )
        print(packet.to_json())
        return 0

    if command == "correct":
        with _open_store(args, create=False) as store:
            old = _target_entry(store, scope, args.entry_id)
            value = _input_line(
                "Enter the exact correction explicitly confirmed by the user:",
                max_chars=MAX_STATEMENT_CHARS,
            )
            print("Existing statement:", file=sys.stderr, flush=True)
            print(old.text, file=sys.stderr, flush=True)
            print("Replacement statement:", file=sys.stderr, flush=True)
            print(value, file=sys.stderr, flush=True)
            _confirm("STORE", "Type STORE to append a superseding statement (anything else cancels):")
            replacement = MemoryEntry(
                id=uuid4().hex,
                scope=scope,
                source=MemorySource.USER_STATEMENT,
                kind=old.kind,
                text=value,
                source_event_id=f"local-cli-correction-{uuid4().hex}",
                source_version=1,
                supersedes_id=old.id,
            )
            stored = store.supersede(scope, old.id, replacement)
        _emit({
            "ok": True,
            "operation": "correct",
            "entry": {
                "id": stored.id,
                "source": stored.source.value,
                "kind": stored.kind.value,
                "source_event_id": stored.source_event_id,
                "source_version": stored.source_version,
                "supersedes_id": stored.supersedes_id,
            },
            "retention": "local_soft_forget_only",
        })
        return 0

    if command == "forget":
        with _open_store(args, create=False) as store:
            target = _target_entry(store, scope, args.entry_id)
            print("Statement to suppress from recall:", file=sys.stderr, flush=True)
            print(target.text, file=sys.stderr, flush=True)
            print("Soft-forget keeps the original text in this local database; it can be restored.",
                  file=sys.stderr, flush=True)
            _confirm("FORGET", "Type FORGET to suppress this row and its dependent memories:")
            mutation = store.forget(scope, target.id)
        _emit({
            "ok": True,
            "operation": "forget",
            "mutation": {
                "id": mutation.id,
                "kind": mutation.kind.value,
                "target_entry_id": mutation.target_entry_id,
                "reverses_id": mutation.reverses_id,
            },
            "recall_blocked": True,
            "physical_deletion": False,
        })
        return 0

    if command == "restore":
        with _open_store(args, create=False) as store:
            items = store.history(scope, entry_id=args.mutation_id, limit=MAX_HISTORY_LIMIT)
            forgotten = next((item for item in items
                              if isinstance(item, MemoryMutation) and item.id == args.mutation_id), None)
            if forgotten is None or forgotten.kind is not MemoryMutationKind.FORGET:
                raise _CliError("forget_event_unavailable")
            target = _target_entry(store, scope, forgotten.target_entry_id)
            print("Statement whose recall may be restored:", file=sys.stderr, flush=True)
            print(target.text, file=sys.stderr, flush=True)
            _confirm("RESTORE", "Type RESTORE to reverse this soft-forget event:")
            mutation = store.undo_forget(scope, forgotten.id)
        _emit({
            "ok": True,
            "operation": "restore",
            "mutation": {
                "id": mutation.id,
                "kind": mutation.kind.value,
                "target_entry_id": mutation.target_entry_id,
                "reverses_id": mutation.reverses_id,
            },
            "recall_restored": True,
        })
        return 0

    raise _CliError("operation_unavailable")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        parser.print_help()
        return 0
    try:
        args = parser.parse_args(arguments)
        if args.command is None:
            parser.print_help()
            return 0
        if not args.consent_local_memory:
            raise _CliError("consent_required")
        args._db_path = _external_private_path(args.db, purpose="memory")
        config_path = _external_private_path(args.scope_config, purpose="scope_config")
        scope = _read_private_scope_config(config_path, args.scope)
        return _execute(args, scope)
    except SystemExit as result:
        return int(result.code or 0)
    except _CliError as error:
        return _error(error.code)
    except RequiredMemoryContextOverflow:
        return _error("required_context_exceeds_packet_budget")
    except MemoryRevisionChangedError:
        return _error("stale_context")
    except MemoryContextError as error:
        return _error(str(error))
    except MemoryEntryNotFoundError:
        return _error("entry_unavailable")
    except MemoryPrivacyError:
        return _error("memory_text_rejected")
    except MemoryStoreFullError:
        return _error("memory_store_full")
    except (MemoryStoreError, UnsafeMemoryPathError, UnknownMemoryDatabaseError):
        return _error("memory_operation_failed")
    except OSError:
        return _error("local_io_failed")
    except (TypeError, ValueError):
        return _error("memory_operation_invalid")


if __name__ == "__main__":
    raise SystemExit(main())
