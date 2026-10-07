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


def _reported_choice_event():
    from mira.adapters.review.jev_support.diagnostics import summarize_response_validation
    from mira.application.choice_wire_policy import CHOICE_WIRE_POLICY_REPORTED_V2
    from mira.application.diagnostic_events import DiagnosticCode
    from mira.adapters.diagnostics.privacy import encode_event

    questions = {"synthetic:o1": {"type": "choice", "criteria": {
        "allow": "allow", "reject": "reject", "unknown": "unknown"}}}
    body = json.dumps({"model": "jev-1.13.0", "answers": {"synthetic:o1": {
        "type": "choice", "choice": "allow", "confidence": 0.9,
        "probabilities": {"allow": 0.75, "reject": 0.15, "unknown": 0.1}}}}).encode()
    summary = summarize_response_validation(body, questions, None,
        maximum_response_bytes=65536,
        choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2)
    return encode_event(DiagnosticEvent(DiagnosticStage.OUTPUT_REVIEW,
        DiagnosticOutcome.FAILED, code=DiagnosticCode.UNKNOWN,
        response_validation=summary), 1791175054.5)


def test_reported_choice_warning_survives_current_export_schema():
    from mira.adapters.diagnostics.privacy import validate_event_record

    record = _reported_choice_event()
    answer = record["response_validation"]["answer_facts"][0]
    assert answer["confidence_mismatch_warning"] is True
    assert "noul_probability" not in answer
    assert validate_event_record(json.loads(json.dumps(record))) == record


@pytest.mark.parametrize("field,value", [
    ("raw_private_text", "synthetic-never-export"), ("noul_probability", 0.1),
])
def test_reported_choice_export_rejects_extra_or_wrong_kind_fields(field, value):
    from mira.adapters.diagnostics.privacy import validate_event_record

    record = _reported_choice_event()
    record["response_validation"]["answer_facts"][0][field] = value
    with pytest.raises(ValueError):
        validate_event_record(record)


def test_existing_reported_choice_log_reexports_without_new_provider_call(tmp_path):
    root = tmp_path / "diagnostics"
    (root / "events").mkdir(parents=True)
    log = root / "events" / "events-synthetic.jsonl"
    record = _reported_choice_event()
    log.write_text(json.dumps(record) + "\n")
    original = log.read_bytes()
    destination = tmp_path / "recovered-metadata.zip"
    result = export_diagnostics(root, destination)
    assert result["event_count"] == 1 and result["skipped_records"] == 0
    assert result["raw_count"] == 0 and result["raw_included"] is False
    assert log.read_bytes() == original
    with zipfile.ZipFile(destination) as bundle:
        assert json.loads(bundle.read("events.jsonl")) == record


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
