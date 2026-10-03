"""OBS-02: synthetic credential envelopes only; no runtime config/auth/network."""
import json
import zipfile

import pytest

from mira.adapters.diagnostics.export import export_diagnostics
from mira.adapters.diagnostics.privacy import PrivacyFilter
from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics
from mira.application.contracts import GenerationContext
from mira.application.diagnostic_events import (
    ContentReview, DiagnosticContext, RecordingKind, ReviewedRecording, capture_model_safely,
)

MARKER = "SYNTHETIC_UNKNOWN_CREDENTIAL_7719"


def enabled_sink(root, *, secrets=()):
    sink = LocalDiagnostics(DiagnosticOptions(root), secrets=secrets, worker=False)
    assert sink.set_recording(True, consent=True)
    return sink


def records(root):
    return [json.loads(line) for file in (root / "raw").glob("raw-*.jsonl")
            for line in file.read_text().splitlines()]


def test_generation_context_cannot_launder_rejected_credential_envelope(tmp_path):
    sink = enabled_sink(tmp_path)
    payload = json.dumps({"api_key": MARKER})
    assert not sink.capture_text(RecordingKind.DIALOGUE, payload, DiagnosticContext())
    capture_model_safely(sink, RecordingKind.MODEL_INPUT,
        GenerationContext(payload, (payload,), (), 1), DiagnosticContext())
    assert sink.flush()
    assert not records(tmp_path)
    assert sink.status().accepted_recordings == 0
    assert sink.status().dropped_recordings == 2


ENVELOPES = [
    json.dumps({"text": json.dumps({"api_key": MARKER})}),
    json.dumps([{"safe": [json.dumps({"Authorization": MARKER})]}]),
    json.dumps(json.dumps(json.dumps({"headers": {"X-Api-Key": MARKER}}))),
    json.dumps({"text": '{"api\\u005fkey": "' + MARKER + '"}'}),
    json.dumps({"text": '{"\\u0061pi_key": "' + MARKER + '"}'}),
    json.dumps({"text": {"ＡＰＩ＿ＫＥＹ": MARKER}}, ensure_ascii=False),
    json.dumps({"text": {"OPENAI_API_KEY": MARKER}}),
    json.dumps({"text": {"Cookie": MARKER}}),
    'payload: ' + json.dumps({"api_key": MARKER}) + ' end',
    json.dumps({"text": 'payload: ' + json.dumps({"api_key": MARKER})}),
    json.dumps({"text": 'settings "api_key" = "' + MARKER + '"'}),
    json.dumps({"text": "settings 'password' = '" + MARKER + "'"}),
    '{\\"api_key\\":\\"' + MARKER + '\\"}',
    '{"safe": "ok", "safe": "' + MARKER + '"}',
    json.dumps({"text": '{"api_key": "' + MARKER}),
    json.dumps({"text": '{"safe": NaN}'}),
    json.dumps({"text": 'prefix {"api\\u005fkey": "' + MARKER + '"'}),
]


@pytest.mark.parametrize("payload", ENVELOPES)
@pytest.mark.parametrize("kind", [RecordingKind.MODEL_INPUT, RecordingKind.MODEL_OUTPUT])
def test_structured_credential_envelopes_and_ambiguous_records_fail_closed(tmp_path, payload, kind):
    sink = enabled_sink(tmp_path)
    assert not sink.capture_text(kind, payload, DiagnosticContext())
    assert not sink.capture(ReviewedRecording(kind, review=ContentReview.APPROVED, text=payload))
    assert sink.flush()
    assert not records(tmp_path)


@pytest.mark.parametrize("payload", ENVELOPES)
def test_export_revalidates_legacy_approved_structured_records(tmp_path, payload):
    raw = tmp_path / "raw"
    raw.mkdir()
    record = {"schema": 1, "record_type": "reviewed_raw", "timestamp": 1000,
              "kind": "model_input", "privacy_review": "approved", "context": {}, "text": payload}
    (raw / "raw-synthetic.jsonl").write_text(json.dumps(record) + "\n")
    result = export_diagnostics(tmp_path, tmp_path / "safe.zip",
                               include_raw=True, confirm_sensitive_export=True)
    assert result["raw_count"] == 0 and result["skipped_records"] == 1
    with zipfile.ZipFile(tmp_path / "safe.zip") as archive:
        assert MARKER.encode() not in archive.read("reviewed-raw.jsonl")


def test_json_escaped_injected_secrets_and_assignments_are_redacted(tmp_path):
    secret = "SYNTHETIC_ACTIVE_CAPABILITY_7719"
    sink = enabled_sink(tmp_path, secrets=(secret,))
    escaped_secret = "\\u0053" + secret[1:]
    text = '{"plain": "' + escaped_secret + '", "nested": "password=\\\"' + MARKER + '\\\""}'
    assert sink.capture_text(RecordingKind.MODEL_INPUT, text, DiagnosticContext())
    assert sink.flush()
    saved = records(tmp_path)[0]
    assert saved["privacy_review"] == "redacted"
    assert json.loads(saved["text"]) == {"plain": "[REDACTED]", "nested": "[REDACTED]"}
    assert MARKER not in saved["text"] and secret not in saved["text"]


def test_safe_plain_and_logical_json_content_are_preserved(tmp_path):
    sink = enabled_sink(tmp_path)
    safe = '普通安全对话；not an encoding: C:\\folder\\file'
    assert sink.capture_text(RecordingKind.DIALOGUE, safe, DiagnosticContext())
    logical = json.dumps({"user_text": "safe dialogue", "items": [1, True, None], "note": "[REDACTED]"})
    assert sink.capture_text(RecordingKind.MODEL_INPUT, logical, DiagnosticContext())
    assert sink.flush()
    assert [record["text"] for record in records(tmp_path)] == [safe, logical]


@pytest.mark.parametrize("payload", [
    "[" * 5000 + "0" + "]" * 5000,
    "[" * 5000 + "0",
    json.dumps({"text": "[" * 5000 + "0" + "]" * 5000}),
    json.dumps([0] * 5000),
    "a" * (128 * 1024 + 1),
    "中" * (128 * 1024 // 3 + 1),
])
def test_review_has_depth_node_and_byte_budgets(payload):
    with pytest.raises(ValueError):
        PrivacyFilter().text(payload)


def test_unknown_review_and_unreviewed_audio_stay_ineligible(tmp_path):
    sink = enabled_sink(tmp_path)
    assert not sink.capture(ReviewedRecording(RecordingKind.MODEL_OUTPUT,
        review=ContentReview.UNCERTAIN, text="safe"))
    assert not sink.capture(ReviewedRecording(RecordingKind.AUDIO_INPUT,
        audio=b"\0\0" * 20, sample_rate_hz=16000))
    assert sink.flush() and not records(tmp_path)


@pytest.mark.parametrize("fragment", ["x-", "eyJ-"], ids=["assignment-prefix", "jwt-prefix"])
def test_flat_credential_patterns_complete_within_bounded_work(fragment):
    # A subprocess makes a regex regression terminable rather than hanging the suite.
    import subprocess
    import sys
    from pathlib import Path
    source = Path(__file__).resolve().parents[2] / "apps/api/src"
    result = subprocess.run([sys.executable, "-c",
        "from mira.adapters.diagnostics.privacy import PrivacyFilter; "
        f"value={fragment!r} * 16384; "
        "assert PrivacyFilter().text(value) == value; print('bounded')"],
        env={"PYTHONPATH": str(source)}, capture_output=True, text=True, timeout=3)
    assert result.returncode == 0 and result.stdout == "bounded\n"
