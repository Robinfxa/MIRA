import json
import zipfile

import pytest

from mira.adapters.diagnostics.export import export_diagnostics
from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics
from mira.application.diagnostic_events import (
    ContentReview,
    DiagnosticEvent,
    DiagnosticOutcome,
    DiagnosticStage,
    RecordingKind,
    ReviewedRecording,
)


def populate(root):
    sink = LocalDiagnostics(DiagnosticOptions(root), worker=False)
    sink.emit(DiagnosticEvent(DiagnosticStage.HTTP, DiagnosticOutcome.SUCCEEDED))
    sink.set_recording(True, consent=True)
    sink.capture(ReviewedRecording(RecordingKind.DIALOGUE,
        review=ContentReview.APPROVED, text="synthetic-private-dialogue"))
    sink.flush()
    return sink


def test_export_defaults_to_revalidated_sanitized_metadata(tmp_path):
    root = tmp_path / "logs"
    populate(root)
    output = tmp_path / "diagnostics.zip"
    result = export_diagnostics(root, output)
    assert result["raw_included"] is False and result["event_count"] >= 1
    with zipfile.ZipFile(output) as bundle:
        assert set(bundle.namelist()) == {"manifest.json", "events.jsonl"}
        data = b"".join(bundle.read(name) for name in bundle.namelist())
    assert b"synthetic-private-dialogue" not in data
    assert output.stat().st_mode & 0o077 == 0


def test_raw_export_requires_separate_explicit_confirmation(tmp_path):
    root = tmp_path / "logs"
    populate(root)
    output = tmp_path / "diagnostics.zip"
    with pytest.raises(ValueError, match="consent"):
        export_diagnostics(root, output, include_raw=True)
    assert not output.exists()
    result = export_diagnostics(root, output, include_raw=True, confirm_sensitive_export=True)
    assert result["raw_included"] is True
    with zipfile.ZipFile(output) as bundle:
        assert "reviewed-raw.jsonl" in bundle.namelist()


def test_export_drops_injected_fields_malformed_records_and_symlinks(tmp_path):
    root = tmp_path / "logs"
    populate(root)
    events = root / "events"
    original = json.loads(next(events.glob("events-*.jsonl")).read_text().splitlines()[0])
    original["raw_prompt"] = "synthetic-secret-private-dialogue"
    (events / "events-injected.jsonl").write_text(json.dumps(original) + "\nnot-json\n")
    outside = tmp_path / "secret.txt"
    outside.write_text("synthetic-secret-private-dialogue")
    (events / "events-link.jsonl").symlink_to(outside)
    output = tmp_path / "safe.zip"
    result = export_diagnostics(root, output)
    assert result["skipped_records"] >= 2
    with zipfile.ZipFile(output) as bundle:
        assert b"synthetic-secret-private-dialogue" not in b"".join(
            bundle.read(name) for name in bundle.namelist())


def test_export_never_overwrites_existing_destination(tmp_path):
    output = tmp_path / "existing.zip"
    output.write_bytes(b"sentinel")
    with pytest.raises(FileExistsError):
        export_diagnostics(tmp_path / "missing", output)
    assert output.read_bytes() == b"sentinel"


def test_export_skips_overdeep_json_without_crashing(tmp_path):
    root = tmp_path / "logs"
    populate(root)
    (root / "events" / "events-deep.jsonl").write_text("[" * 20000 + "0" + "]" * 20000 + "\n")
    result = export_diagnostics(root, tmp_path / "safe.zip")
    assert result["skipped_records"] == 1 and result["event_count"] >= 1
