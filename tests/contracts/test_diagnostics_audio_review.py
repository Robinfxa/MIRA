"""Synthetic contracts for exact-buffer, development-only PCM review staging."""
import base64
import hashlib
import json
from dataclasses import replace

import pytest

from mira.adapters.diagnostics.audio_review import (
    AudioCaptureLimits,
    AudioCaptureOwner,
    ReviewedAudioCapture,
)
from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics
from mira.application.diagnostic_events import ContentReview, RecordingKind


class RecorderSpy:
    def __init__(self, *, capture_result=True):
        self.recording = False
        self.capture_result = capture_result
        self.recordings = []
        self.set_calls = []
        self.emitted = []

    def set_recording(self, enabled, *, consent=False):
        self.set_calls.append((enabled, consent))
        if enabled and consent is not True:
            return False
        self.recording = enabled
        return True

    def capture(self, record):
        self.recordings.append(record)
        return self.capture_result

    def emit(self, event):
        self.emitted.append(event)
        return True


class ManualClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def owner(*, session="session-1", turn="turn-1", stream="stream-1"):
    return AudioCaptureOwner(session_id=session, turn_id=turn, stream_id=stream)


def enabled_capture(sink=None, *, limits=None, clock=None):
    sink = sink or RecorderSpy()
    capture = ReviewedAudioCapture(sink, limits=limits, clock=clock)
    result = capture.set_recording(True, consent=True)
    assert result.ok
    assert capture.status().recording_active
    return capture, sink


def stage(capture, pcm=b"\x01\x00\x02\x00", *, current_owner=None):
    result = capture.begin(current_owner or owner(), sample_rate_hz=16000)
    assert result.ok and result.handle is not None
    assert capture.append(result.handle, pcm).ok
    review = capture.request_review(result.handle)
    assert review.ok and review.ticket is not None
    return result.handle, review.ticket


def test_mode_requires_visible_explicit_opt_in_and_off_wipes_pending_buffer():
    sink = RecorderSpy()
    capture = ReviewedAudioCapture(sink)
    assert not capture.status().recording_active
    assert not capture.status().notice == ""

    refused = capture.set_recording(True)
    assert not refused.ok and refused.code == "consent_required"
    assert not sink.recording
    enabled = capture.set_recording(True, consent=True)
    assert enabled.ok and capture.status().recording_active
    assert "原始音频" in capture.status().notice

    _, ticket = stage(capture)
    disabled = capture.set_recording(False)
    assert disabled.ok and not capture.status().recording_active
    assert not capture.status().has_pending_audio
    assert bytes(ticket.pcm) == b""
    assert not sink.recordings


def test_pcm_staging_is_bounded_transient_and_not_saved_before_review():
    capture, sink = enabled_capture(limits=AudioCaptureLimits(max_audio_bytes=8))
    begun = capture.begin(owner(), sample_rate_hz=16000)
    assert begun.ok
    assert capture.append(begun.handle, b"\x01\x00\x02\x00").ok
    status = capture.status()
    assert status.has_pending_audio and status.staged_bytes == 4
    assert status.max_audio_bytes == 8
    assert sink.recordings == []

    review = capture.request_review(begun.handle)
    assert review.ok and bytes(review.ticket.pcm) == b"\x01\x00\x02\x00"
    assert sink.recordings == []


def test_invalid_or_oversize_pcm_fails_closed_and_wipes_buffer():
    capture, sink = enabled_capture(limits=AudioCaptureLimits(max_audio_bytes=8))
    begun = capture.begin(owner(), sample_rate_hz=16000)
    assert begun.ok
    too_large = capture.append(begun.handle, b"\x00" * 10)
    assert not too_large.ok and too_large.code == "audio_limit_reached"
    assert not capture.status().has_pending_audio

    begun = capture.begin(owner(stream="stream-2"), sample_rate_hz=16000)
    assert begun.ok
    assert capture.append(begun.handle, b"\x00").ok
    invalid = capture.request_review(begun.handle)
    assert not invalid.ok and invalid.code == "invalid_pcm"
    assert not capture.status().has_pending_audio
    assert not sink.recordings


def test_review_exposes_exact_readonly_pcm_digest_and_owner_binding():
    capture, sink = enabled_capture()
    expected = b"\x10\x00\x20\x00\x30\x00"
    handle, ticket = stage(capture, expected)

    assert ticket.pcm.readonly
    assert bytes(ticket.pcm) == expected
    assert ticket.digest == hashlib.sha256(expected).hexdigest()
    assert ticket.owner == owner()
    assert ticket.stage_token == handle.token
    assert ticket.recording_generation == capture.status().recording_generation
    assert sink.recordings == []


def test_buffer_mutation_digest_mismatch_and_repeated_submit_cannot_save():
    capture, sink = enabled_capture()
    _, ticket = stage(capture)
    # The public review view is read-only, but an accidental mutable backing reference must still
    # fail exact-buffer validation rather than reuse the displayed digest.
    ticket.pcm.obj[0] ^= 0x7F
    changed = capture.confirm_save(ticket, reviewed_digest=ticket.digest,
                                   review=ContentReview.APPROVED, persist_consent=True)
    assert not changed.ok and changed.code == "buffer_changed"
    assert not sink.recordings

    _, ticket = stage(capture, current_owner=owner(stream="stream-2"))
    mismatch = capture.confirm_save(ticket, reviewed_digest="0" * 64,
                                    review=ContentReview.APPROVED, persist_consent=True)
    assert not mismatch.ok and mismatch.code == "digest_mismatch"
    assert not sink.recordings

    _, ticket = stage(capture, current_owner=owner(stream="stream-3"))
    wrong_owner = replace(ticket, owner=owner(session="different-session"))
    stale_owner = capture.confirm_save(wrong_owner, reviewed_digest=ticket.digest,
                                       review=ContentReview.APPROVED, persist_consent=True)
    assert not stale_owner.ok and stale_owner.code == "stale_review_ticket"
    assert not sink.recordings
    saved = capture.confirm_save(ticket, reviewed_digest=ticket.digest,
                                 review=ContentReview.APPROVED, persist_consent=True)
    assert saved.ok and saved.code == "queued_private_local"
    repeated = capture.confirm_save(ticket, reviewed_digest=ticket.digest,
                                    review=ContentReview.APPROVED, persist_consent=True)
    assert not repeated.ok and repeated.code == "stale_review_ticket"
    assert len(sink.recordings) == 1


def test_expired_review_is_wiped_and_reported():
    clock = ManualClock()
    capture, sink = enabled_capture(
        limits=AudioCaptureLimits(ttl_seconds=5), clock=clock
    )
    _, ticket = stage(capture)
    clock.now += 5
    result = capture.confirm_save(ticket, reviewed_digest=ticket.digest,
                                  review=ContentReview.APPROVED, persist_consent=True)
    assert not result.ok and result.code == "review_expired"
    assert bytes(ticket.pcm) == b""
    assert not sink.recordings
    assert not capture.status().has_pending_audio


def test_new_input_cancels_prior_candidate_and_close_disables_sink():
    capture, sink = enabled_capture()
    _, old_ticket = stage(capture)
    new_input = capture.begin(owner(session="session-2", turn="turn-2", stream="stream-2"),
                              sample_rate_hz=16000)
    assert new_input.ok
    assert bytes(old_ticket.pcm) == b""
    stale = capture.confirm_save(old_ticket, reviewed_digest=old_ticket.digest,
                                 review=ContentReview.APPROVED, persist_consent=True)
    assert not stale.ok and stale.code == "stale_review_ticket"

    capture.close()
    assert not sink.recording
    assert not capture.status().recording_active
    assert not capture.begin(owner(stream="stream-3"), sample_rate_hz=16000).ok
    assert sink.set_calls[-1] == (False, False)


def test_explicit_exact_buffer_approval_queues_one_private_raw_record(tmp_path):
    sink = LocalDiagnostics(DiagnosticOptions(root=tmp_path / "diagnostics"), worker=False)
    capture, _ = enabled_capture(sink)
    pcm = b"\x10\x00\x20\x00\x30\x00\x40\x00"
    _, ticket = stage(capture, pcm)
    saved = capture.confirm_save(ticket, reviewed_digest=ticket.digest,
                                 review=ContentReview.APPROVED, persist_consent=True)
    assert saved.ok and saved.code == "queued_private_local"
    assert "队列" in saved.message
    assert sink.status().accepted_recordings == 1
    assert sink.status().written_recordings == 0
    assert not (tmp_path / "diagnostics" / "raw").exists()

    assert sink.flush()
    raw_files = list((tmp_path / "diagnostics" / "raw").glob("raw-*.jsonl"))
    assert len(raw_files) == 1
    assert not (tmp_path / "diagnostics" / "events").exists()
    record = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert record["kind"] == "audio_input"
    assert record["audio_base64"] == base64.b64encode(pcm).decode("ascii")
    assert record["sample_rate_hz"] == 16000
    assert record["privacy_review"] == "approved"
    # This candidate is a provisional input stream, not a canonical effect.
    assert set(record["context"]) == {"session_id", "turn_id"}
    assert all(value.startswith("h_") for value in record["context"].values())
    assert "session-1" not in raw_files[0].read_text(encoding="utf-8")
    assert sink.status().accepted_events == 0
    assert sink.status().written_recordings == 1
    capture.close()
    sink.close()


def test_persistence_needs_explicit_consent_and_actionable_sink_acceptance():
    sink = RecorderSpy()
    capture, _ = enabled_capture(sink)
    _, ticket = stage(capture)
    no_persist_consent = capture.confirm_save(
        ticket, reviewed_digest=ticket.digest, review=ContentReview.APPROVED,
        persist_consent=False,
    )
    assert not no_persist_consent.ok
    assert no_persist_consent.code == "persist_consent_required"
    assert sink.recordings == []

    _, ticket = stage(capture, current_owner=owner(stream="stream-2"))
    uncertain = capture.confirm_save(ticket, reviewed_digest=ticket.digest,
                                     review=ContentReview.UNCERTAIN, persist_consent=True)
    assert not uncertain.ok and uncertain.code == "review_not_approved"
    assert sink.recordings == []

    sink = RecorderSpy(capture_result=False)
    capture, _ = enabled_capture(sink)
    _, ticket = stage(capture)
    refused = capture.confirm_save(ticket, reviewed_digest=ticket.digest,
                                   review=ContentReview.APPROVED, persist_consent=True)
    assert not refused.ok and refused.code == "local_queue_rejected"
    assert "未接受" in refused.message
    assert len(sink.recordings) == 1
    assert sink.recordings[0].audio == b"\x01\x00\x02\x00"


def test_known_credential_bytes_remain_blocked_by_existing_privacy_filter(tmp_path):
    secret = b"synthetic-secret-value"
    sink = LocalDiagnostics(DiagnosticOptions(root=tmp_path / "diagnostics"),
                            secrets=(secret.decode("ascii"),), worker=False)
    capture, _ = enabled_capture(sink)
    # This is deliberately a synthetic negative fixture, not representative speech.
    pcm = secret + b"\x00\x00"
    _, ticket = stage(capture, pcm)
    rejected = capture.confirm_save(ticket, reviewed_digest=ticket.digest,
                                    review=ContentReview.APPROVED, persist_consent=True)
    assert not rejected.ok and rejected.code == "local_queue_rejected"
    assert sink.status().accepted_recordings == 0
    assert sink.status().dropped_recordings >= 1
    assert not (tmp_path / "diagnostics" / "raw").exists()
    capture.close()
    sink.close()


def test_audio_review_does_not_emit_ordinary_events_or_authorize_raw_export():
    sink = RecorderSpy()
    capture, _ = enabled_capture(sink)
    _, ticket = stage(capture)
    result = capture.confirm_save(ticket, reviewed_digest=ticket.digest,
                                  review=ContentReview.APPROVED, persist_consent=True)
    assert result.ok
    assert sink.emitted == []
    assert not hasattr(capture, "emit")
    assert not hasattr(capture, "export")
    assert not hasattr(capture, "include_raw")
    assert len(sink.recordings) == 1


def test_cancel_and_recording_mode_cycle_invalidate_old_approvals():
    capture, sink = enabled_capture()
    handle, ticket = stage(capture)
    cancelled = capture.cancel(handle)
    assert cancelled.ok and cancelled.code == "audio_cancelled"
    assert bytes(ticket.pcm) == b""
    assert not capture.status().has_pending_audio

    _, ticket = stage(capture, current_owner=owner(stream="stream-2"))
    assert capture.set_recording(False).ok
    assert capture.set_recording(True, consent=True).ok
    stale = capture.confirm_save(ticket, reviewed_digest=ticket.digest,
                                 review=ContentReview.APPROVED, persist_consent=True)
    assert not stale.ok and stale.code == "stale_review_ticket"
    assert not sink.recordings


def test_limits_and_owner_fields_reject_unbounded_or_missing_values():
    with pytest.raises(ValueError):
        AudioCaptureLimits(max_audio_bytes=512 * 1024 + 1)
    with pytest.raises(ValueError):
        AudioCaptureLimits(ttl_seconds=60.1)
    with pytest.raises(ValueError):
        AudioCaptureOwner(session_id="session", turn_id="", stream_id="stream")


def test_provisional_input_keeps_turn_and_effect_unknown_in_persisted_context(tmp_path):
    sink = LocalDiagnostics(DiagnosticOptions(root=tmp_path / "diagnostics"), worker=False)
    capture, _ = enabled_capture(sink)
    provisional = AudioCaptureOwner(session_id="session-1", turn_id=None,
                                    stream_id="mic-stream-1", input_epoch=4)
    _, ticket = stage(capture, current_owner=provisional)
    assert ticket.owner.turn_id is None and ticket.owner.effect_id is None
    assert ticket.owner.input_epoch == 4 and ticket.owner.stream_id == "mic-stream-1"
    result = capture.confirm_save(ticket, reviewed_digest=ticket.digest,
                                  review=ContentReview.APPROVED, persist_consent=True)
    assert result.ok
    assert sink.flush()
    path = next((tmp_path / "diagnostics" / "raw").glob("raw-*.jsonl"))
    record = json.loads(path.read_text(encoding="utf-8"))
    assert set(record["context"]) == {"session_id"}
    capture.close()
    sink.close()


def test_audio_output_kind_is_ticket_bound_and_persisted_truthfully():
    sink = RecorderSpy()
    capture, _ = enabled_capture(sink)
    output_owner = AudioCaptureOwner(session_id="session-1", turn_id="turn-7",
        stream_id="effect-stream-7", effect_id="effect-7", output_epoch=7)
    started = capture.begin_recording(output_owner, sample_rate_hz=24000,
                                      kind=RecordingKind.AUDIO_OUTPUT)
    assert started.ok and started.handle is not None
    assert capture.append(started.handle, b"\x01\x00\x02\x00").ok
    ticket = capture.request_review(started.handle).ticket
    assert ticket.recording_kind is RecordingKind.AUDIO_OUTPUT

    swapped = replace(ticket, recording_kind=RecordingKind.AUDIO_INPUT)
    rejected = capture.confirm_save(swapped, reviewed_digest=ticket.digest,
        review=ContentReview.APPROVED, persist_consent=True)
    assert not rejected.ok and rejected.code == "stale_review_ticket"
    assert sink.recordings == []

    saved = capture.confirm_save(ticket, reviewed_digest=ticket.digest,
        review=ContentReview.APPROVED, persist_consent=True)
    assert saved.ok and sink.recordings[0].kind is RecordingKind.AUDIO_OUTPUT
    assert sink.recordings[0].context.turn_id == "turn-7"
    assert sink.recordings[0].context.effect_id == "effect-7"


def test_reviewed_audio_rejects_non_audio_recording_kinds():
    capture, sink = enabled_capture()
    invalid = capture.begin_recording(owner(), sample_rate_hz=16000,
                                      kind=RecordingKind.DIALOGUE)
    assert not invalid.ok and invalid.code == "invalid_recording_kind"
    assert not capture.status().has_pending_audio and sink.recordings == []
