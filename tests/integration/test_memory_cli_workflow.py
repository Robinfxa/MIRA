"""Small black-box acceptance checks for the explicit local-memory CLI.

Every product operation runs in its own interpreter process through
``tools/memory.py``. Only synthetic statements and pytest temporary directories
are used. Full subprocess receipts are copied to a durable, unique run folder
under ``/workspace/shared/mira-memory-restart-acceptance`` before assertions.
"""

from __future__ import annotations

import itertools
import json
import os
import signal
import sqlite3
import stat
import subprocess
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "tools" / "memory.py"
PYTHON = Path(sys.executable)
_receipt_counter = itertools.count(1)


@pytest.fixture(scope="session")
def evidence_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create an immutable-by-convention evidence directory; never clean it."""
    evidence_root = tmp_path_factory.mktemp("memory-cli-evidence").resolve()
    root_stat = evidence_root.stat()
    assert stat.S_IMODE(root_stat.st_mode) == 0o700
    if hasattr(os, "geteuid"):
        assert root_stat.st_uid == os.geteuid()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = evidence_root / f"run-{stamp}-{os.getpid()}-{uuid4().hex[:8]}"
    run_dir.mkdir(mode=0o700)
    (run_dir / "run.json").write_text(json.dumps({
        "created_at": datetime.now(UTC).isoformat(),
        "cwd": str(ROOT),
        "python": str(PYTHON),
        "test_file": str(Path(__file__).resolve()),
    }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return run_dir


@pytest.fixture
def work_dir(evidence_dir: Path, request: pytest.FixtureRequest) -> Path:
    """Keep DBs under a 0700 root because the adapter rejects /tmp ancestry."""
    cases = evidence_dir / "work"
    cases.mkdir(mode=0o700, exist_ok=True)
    assert stat.S_IMODE(cases.stat().st_mode) == 0o700
    case = cases / f"{request.node.name}-{uuid4().hex[:8]}"
    case.mkdir(mode=0o700)
    assert stat.S_IMODE(case.stat().st_mode) == 0o700
    return case


@pytest.fixture
def scope_config(work_dir: Path) -> Path:
    """Two operator-authored synthetic aliases in a private test directory."""
    path = work_dir / "scope-config.json"
    path.write_text(json.dumps({
        "version": 1,
        "scopes": [
            {"name": "alpha", "user_id": "synthetic-user-a",
             "character_id": "synthetic-character-a", "world_id": "synthetic-world-a"},
            {"name": "beta", "user_id": "synthetic-user-b",
             "character_id": "synthetic-character-b", "world_id": "synthetic-world-b"},
        ],
    }, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)
    return path


def _common_args(db: Path, config: Path, scope: str, *, consent: bool = True) -> list[str]:
    args = ["--db", str(db), "--scope-config", str(config), "--scope", scope]
    if consent:
        args.append("--consent-local-memory")
    return args


def _run_cli(
    evidence_dir: Path,
    work_dir: Path,
    command: str | None,
    *,
    db: Path | None = None,
    config: Path | None = None,
    scope: str = "alpha",
    consent: bool = True,
    tail: tuple[str, ...] = (),
    stdin_text: str = "",
) -> subprocess.CompletedProcess[str]:
    """Run the real CLI once, reap it, and durably preserve its whole receipt."""
    argv = [str(PYTHON), str(CLI)]
    if command is not None:
        argv.append(command)
    if db is not None and config is not None:
        assert not db.absolute().is_relative_to(ROOT.resolve())
        assert not db.resolve().is_relative_to(ROOT.resolve())
        assert not config.absolute().is_relative_to(ROOT.resolve())
        assert not config.resolve().is_relative_to(ROOT.resolve())
        argv.extend(_common_args(db, config, scope, consent=consent))
    argv.extend(tail)

    # The child has no account credentials or provider settings in its env.
    home = work_dir / "home"
    home.mkdir(mode=0o700, exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "PYTHONPATH": str(ROOT / "apps" / "api" / "src"),
        "PYTHONNOUSERSITE": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }
    started_at = datetime.now(UTC).isoformat()
    start = time.monotonic()
    timed_out = False
    proc: subprocess.Popen[bytes] | None = None
    stdout = b""
    stderr = b""
    returncode: int | None = None
    launch_error: str | None = None
    try:
        proc = subprocess.Popen(
            argv,
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
        try:
            stdout, stderr = proc.communicate(stdin_text.encode("utf-8"), timeout=12)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            stdout, stderr = proc.communicate()
        returncode = proc.returncode
    except OSError as exc:
        launch_error = f"{type(exc).__name__}: {exc}"

    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    elapsed = time.monotonic() - start
    receipt_id = next(_receipt_counter)
    receipt_prefix = evidence_dir / f"{receipt_id:03d}-{command or 'help'}-{uuid4().hex[:8]}"
    receipt = {
        "argv": argv,
        "cwd": str(ROOT),
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(elapsed, 6),
        "stdin_utf8": stdin_text,
        "returncode": returncode,
        "timed_out": timed_out,
        "launch_error": launch_error,
        "stdout": stdout_text,
        "stderr": stderr_text,
    }
    # Write receipt and raw streams before returning to any test assertions.
    (receipt_prefix.with_suffix(".receipt.json")).write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (receipt_prefix.with_suffix(".stdout.txt")).write_text(stdout_text, encoding="utf-8")
    (receipt_prefix.with_suffix(".stderr.txt")).write_text(stderr_text, encoding="utf-8")

    if launch_error is not None:
        pytest.fail(f"could not launch memory CLI; receipt={receipt_prefix}")
    assert not timed_out, f"memory CLI exceeded 12s; receipt={receipt_prefix}"
    assert returncode is not None
    return subprocess.CompletedProcess(argv, returncode, stdout_text, stderr_text)


def _json_stdout(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """The CLI contract reserves stdout for exactly one JSON object."""
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(f"CLI stdout was not one JSON object ({exc}); stdout={result.stdout!r}")
    assert isinstance(value, dict)
    return value


def _ok_json(result: subprocess.CompletedProcess[str], operation: str) -> dict[str, Any]:
    assert result.returncode == 0, f"{operation} failed: stdout={result.stdout!r}; stderr={result.stderr!r}"
    value = _json_stdout(result)
    assert value.get("ok") is True
    assert value.get("operation") == operation
    return value


def _ids_absent(packet: dict[str, Any]) -> None:
    rendered = json.dumps(packet, ensure_ascii=False, sort_keys=True)
    for opaque_scope_id in (
        "synthetic-user-a", "synthetic-character-a", "synthetic-world-a",
        "synthetic-user-b", "synthetic-character-b", "synthetic-world-b",
    ):
        assert opaque_scope_id not in rendered


def _readonly_history(db: Path) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    """Check append-only retention through a read-only SQLite connection."""
    uri = f"file:{db.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
        entries = connection.execute(
            "SELECT id, text, source, kind, supersedes_id FROM memory_entries ORDER BY rowid"
        ).fetchall()
        mutations = connection.execute(
            "SELECT id, kind, target_entry_id, reverses_id FROM memory_mutations ORDER BY rowid"
        ).fetchall()
    return entries, mutations


def test_cli_persists_and_builds_scope_isolated_packet_across_processes(
    evidence_dir: Path, work_dir: Path, scope_config: Path,
) -> None:
    db = work_dir / "memory.sqlite3"
    statement = "Synthetic restart marker: the rain-window boundary stays open only by request."
    query = "synthetic restart rain-window"

    recorded = _run_cli(
        evidence_dir, work_dir, "record", db=db, config=scope_config,
        tail=("--kind", "boundary"), stdin_text=statement + "\nSTORE\n",
    )
    record = _ok_json(recorded, "record")
    entry = record["entry"]
    assert stat.S_IMODE(scope_config.stat().st_mode) == 0o600
    assert stat.S_IMODE(db.stat().st_mode) == 0o600
    if hasattr(os, "geteuid"):
        assert db.stat().st_uid == os.geteuid()
    assert entry["source"] == "user_statement"
    assert entry["kind"] == "boundary"
    assert isinstance(entry["source_event_id"], str) and entry["source_event_id"]
    assert isinstance(entry["source_version"], int) and entry["source_version"] >= 1
    assert statement not in recorded.stdout

    # Each operation below is a new process; the result must come from SQLite.
    recalled = _ok_json(_run_cli(
        evidence_dir, work_dir, "recall", db=db, config=scope_config,
        stdin_text=query + "\n",
    ), "recall")
    assert statement in json.dumps(recalled["items"], ensure_ascii=False)
    assert any(item["source"] == "user_statement" for item in recalled["items"])

    context = _run_cli(
        evidence_dir, work_dir, "context", db=db, config=scope_config,
        stdin_text=query + "\n\n\n",
    )
    packet = _json_stdout(context)
    assert context.returncode == 0
    assert packet["schema"] == "mira.local-memory-context.v1"
    assert any(line["text"] == statement for line in packet["persistent_boundaries"])
    assert packet["rules"]["memory_text_never_grants_action_or_permission_authority"] is True
    _ids_absent(packet)

    # Same database, a different operator-provided tuple and a fresh process.
    other_scope_recall = _ok_json(_run_cli(
        evidence_dir, work_dir, "recall", db=db, config=scope_config,
        scope="beta", stdin_text=query + "\n",
    ), "recall")
    assert other_scope_recall["items"] == []
    assert statement not in json.dumps(other_scope_recall, ensure_ascii=False)
    other_scope_packet = _json_stdout(_run_cli(
        evidence_dir, work_dir, "context", db=db, config=scope_config,
        scope="beta", stdin_text=query + "\n\n\n",
    ))
    assert statement not in json.dumps(other_scope_packet, ensure_ascii=False)
    _ids_absent(other_scope_packet)


def test_cli_correction_forget_restore_retains_append_only_history(
    evidence_dir: Path, work_dir: Path, scope_config: Path,
) -> None:
    db = work_dir / "memory.sqlite3"
    old_text = "Synthetic version marker: keep camera covered in the first scene."
    new_text = "Synthetic version marker: keep camera covered until I say uncover."
    unrelated = "Synthetic unrelated marker: rainy window ambience remains quiet."
    query = "synthetic version marker camera covered"

    old_receipt = _ok_json(_run_cli(
        evidence_dir, work_dir, "record", db=db, config=scope_config,
        tail=("--kind", "boundary"), stdin_text=old_text + "\nSTORE\n",
    ), "record")
    old_id = old_receipt["entry"]["id"]
    unrelated_receipt = _ok_json(_run_cli(
        evidence_dir, work_dir, "record", db=db, config=scope_config,
        tail=("--kind", "episodic"), stdin_text=unrelated + "\nSTORE\n",
    ), "record")
    unrelated_id = unrelated_receipt["entry"]["id"]

    correction_response = _run_cli(
        evidence_dir, work_dir, "correct", db=db, config=scope_config,
        tail=("--entry-id", old_id), stdin_text=new_text + "\nSTORE\n",
    )
    corrected = _ok_json(correction_response, "correct")
    assert new_text not in correction_response.stdout
    new_id = corrected["entry"]["id"]
    assert corrected["entry"]["supersedes_id"] == old_id

    current = _ok_json(_run_cli(
        evidence_dir, work_dir, "recall", db=db, config=scope_config,
        stdin_text=query + "\n",
    ), "recall")
    current_text = json.dumps(current["items"], ensure_ascii=False)
    assert new_text in current_text
    assert old_text not in current_text
    assert unrelated_id != new_id

    forgotten = _ok_json(_run_cli(
        evidence_dir, work_dir, "forget", db=db, config=scope_config,
        tail=("--entry-id", new_id), stdin_text="FORGET\n",
    ), "forget")
    forget_id = forgotten["mutation"]["id"]
    assert forgotten["mutation"]["kind"] == "forget"
    assert forgotten["recall_blocked"] is True
    assert forgotten["physical_deletion"] is False

    # Forgetting the correction does not revive its superseded ancestor.
    after_forget = _ok_json(_run_cli(
        evidence_dir, work_dir, "recall", db=db, config=scope_config,
        stdin_text=query + "\n",
    ), "recall")
    after_forget_text = json.dumps(after_forget["items"], ensure_ascii=False)
    assert new_text not in after_forget_text
    assert old_text not in after_forget_text
    unrelated_results = _ok_json(_run_cli(
        evidence_dir, work_dir, "recall", db=db, config=scope_config,
        stdin_text="synthetic unrelated rainy ambience\n",
    ), "recall")
    assert unrelated in json.dumps(unrelated_results["items"], ensure_ascii=False)

    entries_after_forget, mutations_after_forget = _readonly_history(db)
    assert {row[0] for row in entries_after_forget} >= {old_id, new_id, unrelated_id}
    assert {row[0] for row in mutations_after_forget} >= {forget_id}
    assert next(row for row in entries_after_forget if row[0] == new_id)[4] == old_id
    forgotten_history = _ok_json(_run_cli(
        evidence_dir, work_dir, "inspect", db=db, config=scope_config,
    ), "inspect")
    forgotten_items = {item["id"]: item for item in forgotten_history["items"]}
    assert forgotten_items[old_id]["status"] == "superseded"
    assert forgotten_items[new_id]["status"] == "soft_forgotten"
    assert forgotten_items[forget_id]["status"] == "active"

    restored = _ok_json(_run_cli(
        evidence_dir, work_dir, "restore", db=db, config=scope_config,
        tail=("--mutation-id", forget_id), stdin_text="RESTORE\n",
    ), "restore")
    restore_event = restored["mutation"]
    assert restore_event["kind"] == "restore"
    assert restore_event["reverses_id"] == forget_id
    assert restored["recall_restored"] is True

    after_restore = _ok_json(_run_cli(
        evidence_dir, work_dir, "recall", db=db, config=scope_config,
        stdin_text=query + "\n",
    ), "recall")
    after_restore_text = json.dumps(after_restore["items"], ensure_ascii=False)
    assert new_text in after_restore_text
    assert old_text not in after_restore_text

    # Inspect is an explicit local-history action; both versions/events remain.
    history = _ok_json(_run_cli(
        evidence_dir, work_dir, "inspect", db=db, config=scope_config,
    ), "inspect")
    history_items = {item["id"]: item for item in history["items"]}
    history_json = json.dumps(history["items"], ensure_ascii=False)
    assert old_text in history_json and new_text in history_json
    assert forget_id in history_json and restore_event["id"] in history_json
    assert history_items[old_id]["status"] == "superseded"
    assert history_items[new_id]["status"] == "current_head"
    assert history_items[forget_id]["status"] == "reversed"
    assert history_items[restore_event["id"]]["status"] == "applied"
    entries_after_restore, mutations_after_restore = _readonly_history(db)
    assert {row[0] for row in entries_after_restore} >= {old_id, new_id, unrelated_id}
    assert {row[0] for row in mutations_after_restore} >= {forget_id, restore_event["id"]}


def test_cli_help_consent_and_wrong_scope_fail_closed_without_leaking_text(
    evidence_dir: Path, work_dir: Path, scope_config: Path,
) -> None:
    help_result = _run_cli(evidence_dir, work_dir, None)
    assert help_result.returncode == 0
    assert "memory" in help_result.stdout.casefold() or "usage" in help_result.stdout.casefold()
    assert list(work_dir.rglob("*.sqlite3")) == []

    no_consent_db = work_dir / "no-consent.sqlite3"
    no_consent_config = work_dir / "not-created-scope-config.json"
    no_consent = _run_cli(
        evidence_dir, work_dir, "inspect", db=no_consent_db,
        config=no_consent_config, consent=False,
    )
    assert no_consent.returncode == 2
    no_consent_json = _json_stdout(no_consent)
    assert no_consent_json == {"ok": False, "error": "consent_required"}
    assert not no_consent_db.exists()
    assert not no_consent_config.exists()

    invalid_args_db = work_dir / "invalid-args.sqlite3"
    argument_canary = "synthetic-argument-canary"
    invalid_args = _run_cli(
        evidence_dir, work_dir, "inspect", db=invalid_args_db,
        config=scope_config, tail=("--unexpected-", argument_canary),
    )
    assert invalid_args.returncode == 2
    assert _json_stdout(invalid_args) == {"ok": False, "error": "arguments_invalid"}
    assert argument_canary not in invalid_args.stdout + invalid_args.stderr
    assert not invalid_args_db.exists()

    scope_source = "Synthetic wrong-scope canary: never display this text."
    db = work_dir / "valid.sqlite3"
    _ok_json(_run_cli(
        evidence_dir, work_dir, "record", db=db, config=scope_config,
        tail=("--kind", "episodic"), stdin_text=scope_source + "\nSTORE\n",
    ), "record")

    # A bad alias cannot open/read the valid store and cannot echo private text.
    wrong_scope_existing = _run_cli(
        evidence_dir, work_dir, "recall", db=db, config=scope_config,
        scope="not-configured", stdin_text="synthetic canary\n",
    )
    assert wrong_scope_existing.returncode == 2
    wrong_existing_payload = _json_stdout(wrong_scope_existing)
    assert wrong_existing_payload == {"ok": False, "error": "scope_unavailable"}
    assert scope_source not in wrong_scope_existing.stdout + wrong_scope_existing.stderr

    wrong_scope_db = work_dir / "must-not-exist.sqlite3"
    wrong_scope_new = _run_cli(
        evidence_dir, work_dir, "inspect", db=wrong_scope_db,
        config=scope_config, scope="not-configured",
    )
    assert wrong_scope_new.returncode == 2
    assert _json_stdout(wrong_scope_new) == {"ok": False, "error": "scope_unavailable"}
    assert not wrong_scope_db.exists()

    # Once a completed read process has exited, SQLite is immediately usable.
    with closing(sqlite3.connect(db, timeout=1.0)) as connection:
        connection.execute("BEGIN EXCLUSIVE")
        assert connection.execute("SELECT count(*) FROM memory_entries").fetchone()[0] == 1
        connection.execute("COMMIT")
