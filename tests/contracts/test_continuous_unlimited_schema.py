"""Offline public DTO regression for local-unlimited delivery."""
import pytest
from pydantic import ValidationError
from mira.entrypoints.http import schemas
LEASE = '12345678-1234-4234-8234-123456789012'

def test_null_local_limits_and_finite_service_budget_are_distinct():
    ready = schemas.ContinuousListeningReady(lease_id=LEASE, max_seconds=None, max_samples=None,
        max_utterances=None, max_streams_per_session=None, max_total_streams=None,
        max_recognition_streams=None, session_lease_starts_used=1000001,
        total_lease_starts_used=1000001, stt_requests_used=10, stt_requests_remaining=0,
        endpoint_mode='google_vad_offsets_natural', manual_commit_required=False)
    assert ready.model_dump()['max_seconds'] is None
    assert ready.stt_requests_remaining == 0
    with pytest.raises(ValidationError):
        schemas.ContinuousListeningReady.model_validate({**ready.model_dump(), 'stt_requests_remaining': 101})

def test_cumulative_counters_outlive_old_quotas_without_relaxing_messages():
    assert schemas.ContinuousListeningAudio(type='audio', lease_id=LEASE, sequence=1000001,
        first_sample=16000 * 10000, pcm_base64='AAAA').sequence == 1000001
    assert schemas.ContinuousListeningCommitReady(lease_id=LEASE, commit_id=LEASE,
        segment_seq=1000001, revision=1000001, text='retained').segment_seq == 1000001
    assert schemas.ContinuousListeningUtteranceReady(lease_id=LEASE, utterance_id=LEASE,
        revision=1000001, text='long lease', begin_offset_samples=16000 * 10000,
        end_offset_samples=16000 * 10001, source_end_sample=16000 * 10001,
        final_offset_samples=16000 * 10001).revision == 1000001
    assert schemas.ContinuousListeningRecognitionStatus(lease_id=LEASE,
        stream_index=1000001, state='opening').stream_index == 1000001
    with pytest.raises(ValidationError):
        schemas.ContinuousListeningAudio(type='audio', lease_id=LEASE, sequence=True,
            first_sample=0, pcm_base64='AAAA')
    with pytest.raises(ValidationError):
        schemas.ContinuousListeningAudio(type='audio', lease_id=LEASE, sequence=1,
            first_sample=0, pcm_base64='A' * 16001)

def test_service_exhaustion_and_pending_capacity_are_closed_reasons():
    assert schemas.ContinuousListeningStopped(lease_id=LEASE, reason='service_budget_exhausted')
    assert schemas.ContinuousListeningCommitRejected(lease_id=LEASE, commit_id=LEASE,
        reason='pending_capacity', current_revision=1000001)
    with pytest.raises(ValidationError):
        schemas.ContinuousListeningStopped(lease_id=LEASE, reason='invented_reason')
