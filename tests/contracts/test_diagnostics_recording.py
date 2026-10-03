import json

from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics
from mira.application.diagnostic_events import ContentReview, RecordingKind, ReviewedRecording


def text_record(text="synthetic dialogue", review=ContentReview.APPROVED):
    return ReviewedRecording(RecordingKind.DIALOGUE, review=review, text=text)


def raw_records(root):
    return [json.loads(line) for file in (root / "raw").glob("raw-*.jsonl")
            for line in file.read_text().splitlines()]


def test_raw_is_off_by_default_and_requires_explicit_consent(tmp_path):
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    assert not sink.status().recording_active
    assert not sink.capture(text_record())
    assert not sink.set_recording(True)
    assert not sink.status().recording_active
    assert sink.set_recording(True, consent=True)
    assert sink.status().recording_active and "开发录制" in sink.status().notice
    assert sink.capture(text_record())
    sink.flush()
    assert raw_records(tmp_path)[0]["text"] == "synthetic dialogue"


def test_mode_disable_revokes_pending_recordings(tmp_path):
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    sink.set_recording(True, consent=True)
    assert sink.capture(text_record())
    assert sink.set_recording(False)
    sink.flush()
    assert not raw_records(tmp_path)
    assert not sink.status().recording_active
    assert not sink.capture(text_record())
    assert sink.status().dropped_recordings == 2


def test_raw_text_removes_injected_secrets_and_credential_shapes(tmp_path):
    secret = "synthetic-active-secret-123456"
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), secrets=(secret,), worker=False)
    sink.set_recording(True, consent=True)
    assert sink.capture(text_record(f"safe dialogue {secret}; sk-synthetic1234567890; "
        "Bearer synthetic-bearer-0123456789; api_key=synthetic-inline-secret"))
    sink.flush()
    encoded = json.dumps(raw_records(tmp_path))
    for value in [secret, "sk-synthetic1234567890", "synthetic-bearer-0123456789",
                  "synthetic-inline-secret"]:
        assert value not in encoded
    assert "[REDACTED]" in encoded


def test_authorization_and_credential_envelopes_are_never_saved(tmp_path):
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    sink.set_recording(True, consent=True)
    for value in ['{"Authorization": "Bearer synthetic"}',
                  '{"headers": {"X-Api-Key": "synthetic"}}',
                  '{"private_key": "synthetic"}', "-----BEGIN PRIVATE KEY-----\nsynthetic"]:
        assert not sink.capture(text_record(value))
    sink.flush()
    assert not raw_records(tmp_path)


def test_uncertain_rejected_or_unreviewed_audio_is_dropped(tmp_path):
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    sink.set_recording(True, consent=True)
    assert not sink.capture(text_record(review=ContentReview.UNCERTAIN))
    assert not sink.capture(text_record(review=ContentReview.REJECTED))
    assert not sink.capture(ReviewedRecording(RecordingKind.AUDIO_INPUT,
        audio=b"\0\0" * 20, sample_rate_hz=16000))
    assert sink.capture(ReviewedRecording(RecordingKind.AUDIO_INPUT,
        review=ContentReview.APPROVED, audio=b"\0\0" * 20, sample_rate_hz=16000))
    sink.flush()
    records = raw_records(tmp_path)
    assert len(records) == 1 and records[0]["audio_base64"]


def test_raw_quotas_retention_and_buffer_bounds(tmp_path):
    now = [20000.0]
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path, raw_max_file_bytes=1200,
        raw_max_files=2, raw_retention_seconds=5, max_text_bytes=100),
        worker=False, clock=lambda: now[0])
    sink.set_recording(True, consent=True)
    assert not sink.capture(text_record("a" * 101))
    for _ in range(20):
        assert sink.capture(text_record())
        sink.flush()
    files = list((tmp_path / "raw").glob("raw-*.jsonl"))
    assert 1 <= len(files) <= 2
    assert all(file.stat().st_size <= 1200 and file.stat().st_mode & 0o077 == 0 for file in files)
    now[0] += 6
    sink.cleanup()
    assert not raw_records(tmp_path)


def test_raw_queue_has_a_byte_budget_independent_of_record_count(tmp_path):
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path, queue_capacity=256), worker=False)
    sink.set_recording(True, consent=True)
    accepted = sum(sink.capture(text_record("a" * (128 * 1024))) for _ in range(30))
    assert 0 < accepted < 30
    assert sink.status().dropped_recordings > 0


def test_quoted_credential_values_are_removed(tmp_path):
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    sink.set_recording(True, consent=True)
    assert sink.capture(text_record('password="synthetic-quoted-password"; '
        "api_key='synthetic-quoted-key'; token: \"synthetic-quoted-token\""))
    sink.flush()
    encoded = json.dumps(raw_records(tmp_path))
    for value in ("synthetic-quoted-password", "synthetic-quoted-key", "synthetic-quoted-token"):
        assert value not in encoded


def test_retention_bounds_oldest_record_age_despite_new_writes(tmp_path):
    now = [1000.0]
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path, raw_retention_seconds=10),
                            worker=False, clock=lambda: now[0])
    sink.set_recording(True, consent=True)
    sink.capture(text_record("first synthetic dialogue"))
    sink.flush()
    now[0] += 9
    sink.capture(text_record("second synthetic dialogue"))
    sink.flush()
    now[0] += 2
    sink.cleanup()
    assert all(record["text"] != "first synthetic dialogue" for record in raw_records(tmp_path))


def test_env_style_and_private_key_assignments_never_persist(tmp_path):
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    sink.set_recording(True, consent=True)
    values = ["OPENAI_API_KEY=synthetic-prefixed-api-key", "private_key=synthetic-private-key",
              "MIRA_SERVICES__JEV__API_KEY='synthetic-nested-key'", "CUSTOM_SECRET=synthetic-secret"]
    for value in values:
        sink.capture(text_record(value))
    sink.flush()
    encoded = json.dumps(raw_records(tmp_path))
    assert "synthetic-" not in encoded


def test_runtime_text_capture_filters_newly_injected_active_secrets(tmp_path):
    from mira.application.diagnostic_events import DiagnosticContext

    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    assert not sink.capture_text(RecordingKind.DIALOGUE, "synthetic", DiagnosticContext())
    sink.set_recording(True, consent=True)
    assert sink.add_secret("synthetic-session-capability")
    assert sink.capture_text(RecordingKind.MODEL_OUTPUT,
        "rejected semantic content synthetic-session-capability", DiagnosticContext())
    sink.flush()
    records = raw_records(tmp_path)
    assert len(records) == 1 and "rejected semantic content" in records[0]["text"]
    assert "synthetic-session-capability" not in json.dumps(records)
