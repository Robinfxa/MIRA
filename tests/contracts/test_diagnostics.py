"""Synthetic offline diagnostics, never real credentials or provider requests."""
import json
from dataclasses import replace

import pytest

from mira.adapters.diagnostics.errors import classify_failure
from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics
from mira.application.diagnostic_events import (
    CancellationReason,
    DiagnosticCode,
    DiagnosticContext,
    DiagnosticEvent,
    DiagnosticOutcome,
    DiagnosticStage,
)


def event(**kwargs):
    return DiagnosticEvent(DiagnosticStage.GENERATION, DiagnosticOutcome.SUCCEEDED,
        DiagnosticContext("request-1", "session-1", "turn-1", "effect-1"), **kwargs)


def read_events(root):
    return [json.loads(line) for file in (root / "events").glob("events-*.jsonl")
            for line in file.read_text().splitlines()]


def test_correlated_bounded_events_never_copy_identifiers_or_payloads(tmp_path):
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    assert sink.emit(event(duration_ms=12.5))
    assert sink.emit(event(duration_ms=15))
    assert sink.flush()
    records = read_events(tmp_path)
    assert len(records) == 2
    assert records[0]["context"] == records[1]["context"]
    assert set(records[0]["context"]) == {"request_id", "session_id", "turn_id", "effect_id"}
    assert "session-1" not in json.dumps(records)
    assert records[0]["duration_ms"] == 12.5
    assert sink.status().written_events == 2


@pytest.mark.parametrize(("status", "code"), [(401, "unauthenticated"), (403, "permission_denied"),
                                              (429, "quota_exhausted"), (504, "timeout")])
def test_known_provider_status_has_safe_actionable_class(status, code):
    result = classify_failure(RuntimeError("Bearer synthetic-private-token"), http_status=status)
    assert result.code == code
    assert result.message and result.action
    assert "synthetic" not in result.message + result.action


def test_timeout_permission_and_unknown_causes_are_not_guessed():
    assert classify_failure(TimeoutError("private")).code == DiagnosticCode.TIMEOUT
    assert classify_failure(PermissionError("private")).code == DiagnosticCode.PERMISSION_DENIED
    assert classify_failure(RuntimeError("401 invalid token")).code == DiagnosticCode.UNKNOWN


@pytest.mark.parametrize("reason", [CancellationReason.USER_STOP, CancellationReason.DISCONNECT])
def test_cancellation_reason_is_not_failure_or_timeout(tmp_path, reason):
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    cancelled = replace(event(), outcome=DiagnosticOutcome.CANCELLED,
                        cancellation_reason=reason, code=DiagnosticCode.CANCELLED)
    assert sink.emit(cancelled)
    sink.flush()
    record = read_events(tmp_path)[0]
    assert record["outcome"] == "cancelled"
    assert record["cancellation_reason"] == reason
    assert record["code"] != "timeout"


def test_invalid_free_text_and_nonfinite_timings_are_dropped(tmp_path):
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    for bad in [replace(event(), stage="Bearer secret"), replace(event(), duration_ms=float("nan")),
                replace(event(), code="private upstream body"),
                replace(event(), http_status=True), replace(event(), duration_ms=-1)]:
        assert not sink.emit(bad)
    sink.flush()
    assert not read_events(tmp_path)
    assert sink.status().dropped_events == 5


def test_queue_pressure_is_nonblocking_and_counted(tmp_path):
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path, queue_capacity=1), worker=False)
    assert sink.emit(event())
    assert not sink.emit(event())
    assert sink.status().dropped_events == 1
    assert sink.flush()
    assert len(read_events(tmp_path)) == 1


def test_rotation_retention_and_private_permissions(tmp_path):
    now = [100000.0]
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path, max_file_bytes=1200, max_files=2,
        retention_seconds=10), worker=False, clock=lambda: now[0])
    for _ in range(20):
        assert sink.emit(event())
        sink.flush()
    files = list((tmp_path / "events").glob("events-*.jsonl"))
    assert 1 <= len(files) <= 2
    assert all(file.stat().st_size <= 1200 for file in files)
    assert all(file.stat().st_mode & 0o077 == 0 for file in files)
    assert (tmp_path / "events").stat().st_mode & 0o077 == 0
    now[0] += 11
    sink.cleanup()
    assert not list((tmp_path / "events").glob("events-*.jsonl"))


def test_logging_io_failure_never_escapes_or_records_exception(tmp_path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("sentinel")
    sink = LocalDiagnostics(DiagnosticOptions(blocked), worker=False)
    assert sink.emit(event())
    assert sink.flush()
    assert sink.status().io_failures >= 1
    assert blocked.read_text() == "sentinel"
    sink.close()
    assert not sink.emit(event())


def test_symlink_destination_is_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "logs"
    root.mkdir()
    (root / "events").symlink_to(outside, target_is_directory=True)
    sink = LocalDiagnostics(DiagnosticOptions(root), worker=False)
    sink.emit(event())
    sink.flush()
    assert not list(outside.iterdir())
    assert sink.status().io_failures == 1


def test_slow_disk_cannot_stall_emit_or_close(tmp_path):
    import threading

    sink = LocalDiagnostics(DiagnosticOptions(tmp_path))
    entered, release, emitted, closed = (threading.Event() for _ in range(4))
    original = sink._events.append
    def blocked(line):
        entered.set()
        assert release.wait(3)
        original(line)
    sink._events.append = blocked
    assert sink.emit(event()) and entered.wait(1)
    def actions():
        sink.emit(event())
        emitted.set()
        sink.close()
        closed.set()
    thread = threading.Thread(target=actions)
    try:
        thread.start()
        assert emitted.wait(.5), "event loop would wait for disk"
        assert closed.wait(.5), "shutdown would wait for disk"
    finally:
        release.set()
        thread.join(timeout=1)
    assert sink.flush()


def test_predeclared_adapter_reason_is_known_but_free_text_is_not():
    from mira.application.diagnostic_errors import classify_reason

    assert classify_failure(RuntimeError("codex_timeout")).code == DiagnosticCode.TIMEOUT
    assert classify_failure(RuntimeError("upstream said codex_timeout with token")).code == DiagnosticCode.UNKNOWN
    assert classify_reason("jev_authentication_failed").code == DiagnosticCode.UNAUTHENTICATED
    assert classify_reason("jev_forbidden").code == DiagnosticCode.PERMISSION_DENIED
    assert classify_reason("jev_rate_limited").code == DiagnosticCode.QUOTA_EXHAUSTED
    assert classify_reason("synthetic private body").code == DiagnosticCode.UNKNOWN
