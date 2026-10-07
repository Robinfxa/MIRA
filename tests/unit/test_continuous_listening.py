from __future__ import annotations

import asyncio

import pytest

from mira.application.continuous_listening import (
    ContinuousListeningRegistry, ListeningAudioBuffer, ListeningEvent,
    ListeningLimits, SAMPLE_RATE_HZ,
)
from mira.application.ports.continuous_speech import (
    ContinuousSpeechActivity, ContinuousTranscriptResult,
)
from mira.domain.errors import DomainError


def _id(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012x}"


async def _drain(lease) -> list[ListeningEvent]:
    values = []
    while not lease.events.empty():
        values.append(lease.events.get_nowait())
    return values


@pytest.mark.asyncio
async def test_three_utterances_and_silence_remain_active_until_explicit_manual_commit():
    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-1", _id(1))
    for begin, final, end, text in (
        (100, 900, 1_100, "第一句。"),
        (2_000, 2_700, 2_900, "第二句。"),
        (4_000, 4_700, 4_900, "第三句。"),
    ):
        await lease._on_activity(ContinuousSpeechActivity("begin", begin))
        await lease._on_transcript(ContinuousTranscriptResult(text, True, final))
        await lease._on_activity(ContinuousSpeechActivity("end", end))
    assert lease.active
    assert lease.stable_text == "第一句。第二句。第三句。"
    events = await _drain(lease)
    assert any(event.type == "transcript" for event in events)
    assert any(event.type == "endpoint_pending" for event in events)
    assert not any(event.type == "commit_ready" for event in events)
    assert not registry._utterances

    result = await lease.manual_commit(commit_id=_id(11), revision=lease.revision, registry=registry)
    assert result.text == "第一句。第二句。第三句。"
    assert lease.active, "sending one turn must leave microphone lease alive"
    assert lease.stable_text == ""
    assert ("session-1", _id(11)) in registry._utterances
    await lease._on_transcript(ContinuousTranscriptResult("后续。", True, 5_500))
    assert lease.stable_text == "后续。"
    next_result = await lease.manual_commit(commit_id=_id(12), revision=lease.revision, registry=registry)
    assert next_result.segment_seq == 2
    assert next_result.text == "后续。"


@pytest.mark.asyncio
async def test_interim_revision_is_preview_only_and_cannot_be_committed():
    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-2", _id(2))
    await lease._on_activity(ContinuousSpeechActivity("begin", 100))
    await lease._on_transcript(ContinuousTranscriptResult("现在说话", False, None))
    assert lease.stable_text == ""
    assert lease._latest_preview == "现在说话"
    with pytest.raises(DomainError, match="stable final"):
        await lease.manual_commit(commit_id=_id(21), revision=lease.revision, registry=registry)
    assert not registry._utterances
    assert lease.active


@pytest.mark.asyncio
async def test_stale_display_revision_requires_new_click_without_losing_final_text():
    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-3", _id(3))
    await lease._on_transcript(ContinuousTranscriptResult("稳定文本", True, 1_000))
    displayed_revision = lease.revision
    await lease._on_transcript(ContinuousTranscriptResult("另一个词", False, None))
    with pytest.raises(DomainError, match="changed"):
        await lease.manual_commit(commit_id=_id(31), revision=displayed_revision, registry=registry)
    assert lease.stable_text == "稳定文本"
    # The user clicks again after the newer revision appears; only stable text enters history.
    result = await lease.manual_commit(commit_id=_id(32), revision=lease.revision, registry=registry)
    assert result.text == "稳定文本"
    assert lease._interim_transcript == "另一个词"
    assert lease._latest_preview == "另一个词"
    # A repeated control with same id/revision returns the same one-use snapshot.
    assert await lease.manual_commit(commit_id=_id(32), revision=result.revision, registry=registry) == result


@pytest.mark.asyncio
async def test_late_final_tail_after_endpoint_remains_visible_for_next_manual_confirmation():
    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-4", _id(4))
    await lease._on_activity(ContinuousSpeechActivity("begin", 0))
    await lease._on_activity(ContinuousSpeechActivity("end", 96_000))
    await lease._on_transcript(ContinuousTranscriptResult("前半句。", True, 64_000))
    await lease._on_transcript(ContinuousTranscriptResult("后半句。", True, 92_800))
    assert lease.stable_text == "前半句。后半句。"
    events = await _drain(lease)
    hints = [event for event in events if event.type == "endpoint_pending"]
    assert hints and hints[-1].text == "前半句。后半句。"
    assert not any(event.type == "commit_ready" for event in events)
    result = await lease.manual_commit(commit_id=_id(41), revision=lease.revision, registry=registry)
    assert result.text == "前半句。后半句。"


@pytest.mark.asyncio
async def test_offset_mismatch_is_only_a_hint_and_missing_offset_stays_manual():
    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-5", _id(5))
    await lease._on_activity(ContinuousSpeechActivity("begin", 10_000))
    await lease._on_transcript(ContinuousTranscriptResult("VAD的提示", True, 20_000))
    await lease._on_activity(ContinuousSpeechActivity("end", 21_000))
    events = await _drain(lease)
    assert any(event.type == "endpoint_pending" for event in events)
    assert not registry._utterances
    result = await lease.manual_commit(commit_id=_id(51), revision=lease.revision, registry=registry)
    assert result.text == "VAD的提示"

    lease2 = await registry.start("session-6", _id(6))
    await lease2._on_transcript(ContinuousTranscriptResult("缺少offset也可以手动", True, None))
    assert lease2.stable_text == "缺少offset也可以手动"
    events = await _drain(lease2)
    assert any(event.reason == "missing_result_offset" for event in events)
    manual = await lease2.manual_commit(commit_id=_id(61), revision=lease2.revision, registry=registry)
    assert manual.text == "缺少offset也可以手动"


@pytest.mark.asyncio
async def test_repeated_final_offset_is_deduplicated_before_manual_commit():
    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-7", _id(7))
    await lease._on_transcript(ContinuousTranscriptResult("同一段", True, 100))
    await lease._on_transcript(ContinuousTranscriptResult("同一段", True, 100))
    assert lease.stable_text == "同一段"
    result = await lease.manual_commit(commit_id=_id(71), revision=lease.revision, registry=registry)
    assert result.text == "同一段"


@pytest.mark.asyncio
async def test_manual_commit_id_exact_binding_requires_delivery_and_fences_conflicts():
    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-8", _id(8))
    await lease._on_transcript(ContinuousTranscriptResult("你好", True, 100))
    result = await lease.manual_commit(commit_id=_id(81), revision=lease.revision, registry=registry)
    with pytest.raises(DomainError, match="not been delivered"):
        await registry.validate_submission("session-8", result.commit_id, "req-a", result.text)
    assert await registry.mark_delivered("session-8", lease.lease_id, result.commit_id)
    assert await registry.validate_submission("session-8", result.commit_id, "req-a", result.text)
    # A second body/request cannot consume the same one-use ID.
    with pytest.raises(DomainError):
        await registry.validate_submission("session-8", result.commit_id, "req-b", result.text)
    with pytest.raises(DomainError):
        await registry.validate_submission("session-8", result.commit_id, "req-a", "你好世界")
    with pytest.raises(DomainError):
        await registry.validate_submission("other-session", result.commit_id, "req-a", result.text)


@pytest.mark.asyncio
async def test_global_stop_revokes_unaccepted_manual_commit_but_preserves_exact_accepted_retry():
    registry = ContinuousListeningRegistry()
    failed = await registry.start("session-9", _id(9))
    await failed._on_transcript(ContinuousTranscriptResult("历史pending", True, 100))
    failed_result = await failed.manual_commit(commit_id=_id(91), revision=failed.revision, registry=registry)
    await registry.mark_delivered("session-9", failed.lease_id, failed_result.commit_id)
    # Simulate actor.submit(history_pending): reservation was attempted but Actor never accepted it.
    await registry.validate_submission("session-9", failed_result.commit_id, "request-failed", failed_result.text)
    await registry.stop_session("session-9", "user_stop")
    with pytest.raises(DomainError, match="revoked"):
        await registry.validate_submission("session-9", failed_result.commit_id,
                                           "request-failed", failed_result.text)

    accepted = await registry.start("session-10", _id(10))
    await accepted._on_transcript(ContinuousTranscriptResult("已接受", True, 200))
    accepted_result = await accepted.manual_commit(commit_id=_id(101), revision=accepted.revision, registry=registry)
    await registry.mark_delivered("session-10", accepted.lease_id, accepted_result.commit_id)
    await registry.validate_submission("session-10", accepted_result.commit_id, "request-ok", accepted_result.text)
    await registry.mark_accepted("session-10", accepted_result.commit_id, "request-ok", accepted_result.text)
    await registry.stop_session("session-10", "user_stop")
    assert await registry.validate_submission("session-10", accepted_result.commit_id,
        "request-ok", accepted_result.text)
    with pytest.raises(DomainError):
        await registry.validate_submission("session-10", accepted_result.commit_id,
            "request-other", accepted_result.text)


@pytest.mark.asyncio
async def test_old_callback_cannot_publish_after_new_lease_replaces_it():
    registry = ContinuousListeningRegistry()
    old = await registry.start("session-11", _id(11))
    new = await registry.start("session-11", _id(111))
    assert not old.active
    assert registry.is_current(new)

    class DelayedBackend:
        started = 0
        async def transcribe_events(self, packets):
            self.started += 1
            yield ContinuousTranscriptResult("stale", True, 100)

    backend = DelayedBackend()
    await old.recognize(backend, is_current=registry.is_current,
        register_utterance=registry.register_utterance)
    assert backend.started == 0
    assert registry.is_current(new)
    terminal = old.events.get_nowait()
    assert terminal.type == "stopped" and terminal.reason == "replaced"
    assert old.events.empty()


@pytest.mark.asyncio
async def test_audio_buffer_enforces_identity_sequence_pacing_and_queue_cap():
    limits = ListeningLimits(max_seconds=2, max_samples=32_000, queue_capacity=1)
    buffer = ListeningAudioBuffer(_id(20), limits=limits)
    pcm = b"\x01\x00" * 80
    buffer.push(lease_id=buffer.lease_id, sequence=1, first_sample=0, pcm=pcm)
    with pytest.raises(DomainError):
        buffer.push(lease_id=_id(21), sequence=2, first_sample=80, pcm=pcm)
    with pytest.raises(DomainError):
        buffer.push(lease_id=buffer.lease_id, sequence=3, first_sample=80, pcm=pcm)
    with pytest.raises(DomainError):
        buffer.push(lease_id=buffer.lease_id, sequence=2, first_sample=80, pcm=pcm)
    buffer.clear()


@pytest.mark.asyncio
async def test_stop_discards_audio_and_future_chunks_are_rejected():
    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-12", _id(12))
    lease.audio.push(lease_id=lease.lease_id, sequence=1, first_sample=0, pcm=b"\0\0" * 80)
    await registry.stop_session("session-12", "user_stop")
    assert not lease.active
    assert lease.audio._queue.empty()
    with pytest.raises(DomainError):
        lease.audio.push(lease_id=lease.lease_id, sequence=2, first_sample=80, pcm=b"\0\0" * 80)


@pytest.mark.asyncio
async def test_global_close_revokes_all_leases_and_new_starts():
    registry = ContinuousListeningRegistry()
    one = await registry.start("session-13", _id(13))
    two = await registry.start("session-14", _id(14))
    await registry.aclose()
    assert not one.active and not two.active
    with pytest.raises(DomainError):
        await registry.start("session-13", _id(15))


@pytest.mark.asyncio
async def test_output_queue_overflow_always_emits_visible_terminal_stop():
    registry = ContinuousListeningRegistry(limits=ListeningLimits(
        max_seconds=2, max_samples=32_000, output_capacity=1))
    lease = await registry.start("session-15", _id(15))
    assert await lease.emit(ListeningEvent("transcript", lease.lease_id, revision=1, text="first"))
    assert not await lease.emit(ListeningEvent("transcript", lease.lease_id, revision=2, text="second"))
    assert not lease.active
    terminal = lease.events.get_nowait()
    assert terminal.type == "stopped" and terminal.reason == "output_limit"
    assert lease.events.empty()


@pytest.mark.asyncio
async def test_manual_commit_cap_stops_visibly_after_preserving_ready_snapshot_and_retry():
    registry = ContinuousListeningRegistry(limits=ListeningLimits(
        max_seconds=2, max_samples=32_000, max_utterances=1))
    lease = await registry.start("session-16", _id(16))
    await lease._on_transcript(ContinuousTranscriptResult("最后允许的一句", True, 100))
    result = await lease.manual_commit(commit_id=_id(161), revision=lease.revision, registry=registry)
    assert result.text == "最后允许的一句"
    assert not lease.active
    terminal = lease.events.get_nowait()
    assert terminal.type == "stopped" and terminal.reason == "utterance_limit"
    assert await registry.mark_delivered("session-16", lease.lease_id, result.commit_id)
    # A history_pending Actor result leaves the exact request reserved. The finite
    # lease stop does not revoke its already-returned one-use snapshot; an exact retry
    # can later succeed without creating a second text binding.
    assert await registry.validate_submission("session-16", result.commit_id, "retry-id", result.text)
    assert await registry.validate_submission("session-16", result.commit_id, "retry-id", result.text)
    await registry.mark_accepted("session-16", result.commit_id, "retry-id", result.text)
    assert await registry.validate_submission("session-16", result.commit_id, "retry-id", result.text)
    assert len(registry._utterances) == 1


@pytest.mark.asyncio
async def test_duplicate_final_after_commit_preserves_newer_interim_and_revision():
    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-duplicate", _id(301))
    await lease._on_transcript(ContinuousTranscriptResult("第一句。", True, 100))
    committed = await lease.manual_commit(commit_id=_id(302), revision=lease.revision, registry=registry)
    await lease._on_transcript(ContinuousTranscriptResult("第二句还在说", False, 200))
    revision = lease.revision
    await _drain(lease)

    await lease._on_transcript(ContinuousTranscriptResult("第一句。", True, 100))

    assert committed.text == "第一句。"
    assert lease._latest_preview == "第二句还在说"
    assert lease._interim_transcript == "第二句还在说"
    assert lease.stable_text == ""
    assert lease.revision == revision
    assert not await _drain(lease), "duplicate callbacks have no new display or commit authority"
    # The same words at a later offset are a new occurrence, not a retransmission.
    await lease._on_transcript(ContinuousTranscriptResult("第一句。", True, 300))
    assert lease.stable_text == "第一句。"
    assert lease.revision == revision + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["user_stop", "permission_lost", "replaced", "disconnect", "session_closed"])
async def test_explicit_cancellation_clears_already_settled_unsent_preview(reason):
    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-terminal", _id(401))
    lease.audio.push(lease_id=lease.lease_id, sequence=1, first_sample=0, pcm=b"\0\0" * 200)
    class FinishedBackend:
        async def transcribe_events(self, packets):
            await anext(packets)
            yield ContinuousTranscriptResult("已经识别的句尾", True, 100)
    await lease.recognize(FinishedBackend(), is_current=registry.is_current,
        register_utterance=registry.register_utterance)
    assert not lease.active
    assert lease.terminal_preview is not None
    assert lease.terminal_preview.text == "已经识别的句尾"
    await registry.stop_lease(lease, reason)
    assert lease.terminal_preview is None
    assert not registry._utterances


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["user_stop", "permission_lost", "replaced", "disconnect", "session_closed"])
async def test_uncooperative_provider_tail_cannot_publish_after_cancellation(reason):
    import asyncio

    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-late", _id(501))
    waiting = asyncio.Event()
    release = asyncio.Event()
    lease.audio.push(lease_id=lease.lease_id, sequence=1, first_sample=0, pcm=b"\0\0" * 200)
    class DelayedBackend:
        async def transcribe_events(self, packets):
            await anext(packets)
            yield ContinuousTranscriptResult("停止前已识别", True, 100)
            waiting.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
            yield ContinuousTranscriptResult("停止后迟到尾句", True, 200)
    task = asyncio.create_task(lease.recognize(DelayedBackend(), is_current=registry.is_current,
        register_utterance=registry.register_utterance))
    lease._recognition_task = task
    await asyncio.wait_for(waiting.wait(), 1)
    assert [event.text for event in await _drain(lease) if event.type == "transcript"] == ["停止前已识别"]
    await registry.stop_lease(lease, reason)
    await asyncio.wait_for(task, 1)
    assert lease.stable_text == "停止前已识别"
    assert lease.terminal_preview is None
    assert [event.type for event in await _drain(lease)] == ["stopped"]
    assert not registry._utterances


@pytest.mark.asyncio
async def test_first_late_final_after_commit_is_retained_once_and_its_duplicate_is_ignored():
    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-first-late", _id(601))
    await lease._on_activity(ContinuousSpeechActivity("begin", 0))
    await lease._on_activity(ContinuousSpeechActivity("end", 400))
    await lease._on_transcript(ContinuousTranscriptResult("第一段。", True, 100))
    first = await lease.manual_commit(commit_id=_id(602), revision=lease.revision, registry=registry)
    await lease._on_transcript(ContinuousTranscriptResult("迟到句尾。", True, 300))
    late_revision = lease.revision
    await lease._on_transcript(ContinuousTranscriptResult("迟到句尾。", True, 300))
    assert lease.stable_text == "迟到句尾。"
    assert lease.revision == late_revision
    second = await lease.manual_commit(commit_id=_id(603), revision=late_revision, registry=registry)
    assert (first.text, second.text) == ("第一段。", "迟到句尾。")
    assert (first.segment_seq, second.segment_seq) == (1, 2)
    assert len(registry._utterances) == 2


async def _natural_lease():
    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-natural", _id(701))
    # Select the new mode while keeping pre-feature RED executable.
    lease.natural_mode = True
    lease.audio.push(lease_id=lease.lease_id, sequence=1, first_sample=0, pcm=b"\0\0" * 1600)
    return registry, lease


@pytest.mark.asyncio
async def test_natural_endpoint_waits_for_final_coverage_then_emits_one_token():
    registry, lease = await _natural_lease()
    await lease._on_activity(ContinuousSpeechActivity("begin", 100))
    await lease._on_activity(ContinuousSpeechActivity("end", 800))
    await lease._on_transcript(ContinuousTranscriptResult("前半句。", True, 400))
    assert not [event for event in await _drain(lease) if event.type == "utterance_ready"]
    await lease._on_transcript(ContinuousTranscriptResult("后半句。", True, 800))
    ready = [event for event in await _drain(lease) if event.type == "utterance_ready"]
    assert len(ready) == 1
    event = ready[0]
    assert event.text == "前半句。后半句。"
    assert (event.begin_offset_samples, event.end_offset_samples, event.final_offset_samples) == (100, 800, 800)
    assert not registry._utterances, "eligibility is not yet a submitted user input"
    result = await lease.manual_commit(commit_id=_id(702), revision=event.revision,
        utterance_id=event.utterance_id, registry=registry)
    assert result.text == event.text
    assert result.utterance_id == event.utterance_id
    assert lease.active
    await lease._on_transcript(ContinuousTranscriptResult("后半句。", True, 800))
    assert not [item for item in await _drain(lease) if item.type == "utterance_ready"]


@pytest.mark.asyncio
@pytest.mark.parametrize("incomplete", ["offset", "end", "interim", "new_begin", "coverage"])
async def test_natural_endpoint_falls_back_when_boundary_evidence_is_incomplete(incomplete):
    _registry, lease = await _natural_lease()
    await lease._on_activity(ContinuousSpeechActivity("begin", 100))
    if incomplete != "end":
        await lease._on_activity(ContinuousSpeechActivity("end", 800))
    if incomplete == "new_begin":
        await lease._on_activity(ContinuousSpeechActivity("begin", 900))
    if incomplete == "interim":
        await lease._on_transcript(ContinuousTranscriptResult("先有稳定段", True, 400))
        await lease._on_transcript(ContinuousTranscriptResult("尚未说完", False, 800))
    else:
        await lease._on_transcript(ContinuousTranscriptResult("你好。", True,
            None if incomplete == "offset" else 400 if incomplete == "coverage" else 800))
    assert not [event for event in await _drain(lease) if event.type == "utterance_ready"]
    assert lease.active
    assert lease._latest_preview


@pytest.mark.asyncio
async def test_natural_candidate_is_revoked_by_a_new_begin_before_commit():
    registry, lease = await _natural_lease()
    await lease._on_activity(ContinuousSpeechActivity("begin", 100))
    await lease._on_activity(ContinuousSpeechActivity("end", 800))
    await lease._on_transcript(ContinuousTranscriptResult("你好。", True, 800))
    ready, = [event for event in await _drain(lease) if event.type == "utterance_ready"]
    await lease._on_activity(ContinuousSpeechActivity("begin", 900))
    with pytest.raises(DomainError, match="changed"):
        await lease.manual_commit(commit_id=_id(703), revision=ready.revision,
            utterance_id=ready.utterance_id, registry=registry)
    assert not registry._utterances
    assert lease.stable_text == "你好。"


@pytest.mark.asyncio
@pytest.mark.parametrize("submission_state", ["pending", "reserved", "accepted"])
async def test_late_natural_tail_stays_with_original_token_and_never_becomes_a_second_turn(submission_state):
    registry, lease = await _natural_lease()
    await lease._on_activity(ContinuousSpeechActivity("begin", 100))
    await lease._on_activity(ContinuousSpeechActivity("end", 800))
    await lease._on_transcript(ContinuousTranscriptResult("你好。", True, 800))
    ready, = [event for event in await _drain(lease) if event.type == "utterance_ready"]
    result = await lease.manual_commit(commit_id=_id(704), revision=ready.revision,
        utterance_id=ready.utterance_id, registry=registry)
    await registry.mark_delivered(lease.session_id, lease.lease_id, result.commit_id)
    if submission_state in {"reserved", "accepted"}:
        await registry.validate_submission(lease.session_id, result.commit_id, "request-natural", result.text)
    if submission_state == "accepted":
        await registry.mark_accepted(lease.session_id, result.commit_id, "request-natural", result.text)
    await _drain(lease)
    await lease._on_transcript(ContinuousTranscriptResult("迟到尾词", True, 850))
    events = await _drain(lease)
    correction, = [event for event in events if event.type == "utterance_revision"]
    assert correction.utterance_id == ready.utterance_id
    assert correction.commit_id == result.commit_id
    assert correction.text == "你好。迟到尾词"
    assert correction.submission_state == submission_state
    assert lease.stable_text == ""
    assert not [event for event in events if event.type == "utterance_ready"]
    assert len(registry._utterances) == 1
    if submission_state != "accepted":
        with pytest.raises(DomainError, match="revoked"):
            await registry.validate_submission(lease.session_id, result.commit_id, "request-natural", result.text)
    else:
        assert await registry.validate_submission(lease.session_id, result.commit_id, "request-natural", result.text)
    await lease._on_transcript(ContinuousTranscriptResult("迟到尾词", True, 850))
    assert not await _drain(lease)


@pytest.mark.asyncio
async def test_natural_endpoint_waits_for_complete_provider_batch_and_no_interim():
    _registry, lease = await _natural_lease()
    await lease._on_activity(ContinuousSpeechActivity("begin", 100))
    await lease._on_activity(ContinuousSpeechActivity("end", 800))
    await lease._on_transcript(ContinuousTranscriptResult("完整稳定段", True, 800,
        provider_batch_complete=False, has_pending_interim=True))
    assert not [event for event in await _drain(lease) if event.type == "utterance_ready"]
    await lease._on_transcript(ContinuousTranscriptResult("临时第一部分与第二部分", False, 900,
        provider_batch_complete=True, has_pending_interim=True))
    assert not [event for event in await _drain(lease) if event.type == "utterance_ready"]
    await lease._on_transcript(ContinuousTranscriptResult("新的稳定尾段", True, 950))
    ready, = [event for event in await _drain(lease) if event.type == "utterance_ready"]
    assert ready.text == "完整稳定段新的稳定尾段"


@pytest.mark.asyncio
async def test_natural_endpoint_does_not_split_one_result_across_two_activities():
    _registry, lease = await _natural_lease()
    await lease._on_activity(ContinuousSpeechActivity("begin", 100))
    await lease._on_activity(ContinuousSpeechActivity("end", 500))
    await lease._on_activity(ContinuousSpeechActivity("begin", 700))
    await lease._on_activity(ContinuousSpeechActivity("end", 1200))
    await lease._on_transcript(ContinuousTranscriptResult("两段一起识别，无法分配文本边界。", True, 1200))
    assert not [event for event in await _drain(lease) if event.type == "utterance_ready"]
    assert lease.stable_text == "两段一起识别，无法分配文本边界。"


@pytest.mark.asyncio
async def test_natural_batch_with_two_final_parts_waits_for_batch_boundary():
    _registry, lease = await _natural_lease()
    await lease._on_activity(ContinuousSpeechActivity("begin", 100))
    await lease._on_activity(ContinuousSpeechActivity("end", 800))
    await lease._on_transcript(ContinuousTranscriptResult("第一稳定段", True, 800,
        provider_batch_complete=False))
    assert not [event for event in await _drain(lease) if event.type == "utterance_ready"]
    await lease._on_transcript(ContinuousTranscriptResult("第二稳定段", True, 900,
        provider_batch_complete=True))
    ready, = [event for event in await _drain(lease) if event.type == "utterance_ready"]
    assert ready.text == "第一稳定段第二稳定段"


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["user_stop", "permission_lost", "replaced", "disconnect", "session_closed"])
async def test_natural_candidate_cannot_commit_after_cancellation(reason):
    registry, lease = await _natural_lease()
    await lease._on_activity(ContinuousSpeechActivity("begin", 100))
    await lease._on_activity(ContinuousSpeechActivity("end", 800))
    await lease._on_transcript(ContinuousTranscriptResult("你好。", True, 800))
    ready, = [event for event in await _drain(lease) if event.type == "utterance_ready"]
    await registry.stop_lease(lease, reason)
    with pytest.raises(DomainError, match="revoked"):
        await lease.manual_commit(commit_id=_id(705), revision=ready.revision,
            utterance_id=ready.utterance_id, registry=registry)
    assert not registry._utterances
    assert lease.terminal_previews == ()


@pytest.mark.asyncio
async def test_natural_terminal_preserves_current_interim_and_separate_old_utterance_correction():
    registry, lease = await _natural_lease()
    await lease._on_activity(ContinuousSpeechActivity("begin", 100))
    await lease._on_activity(ContinuousSpeechActivity("end", 800))
    await lease._on_transcript(ContinuousTranscriptResult("先前一句。", True, 800))
    ready, = [event for event in await _drain(lease) if event.type == "utterance_ready"]
    await lease.manual_commit(commit_id=_id(706), revision=ready.revision,
        utterance_id=ready.utterance_id, registry=registry)
    await lease._on_activity(ContinuousSpeechActivity("begin", 900))
    await lease._on_transcript(ContinuousTranscriptResult("新句还在说", False, 1200))
    await lease._on_transcript(ContinuousTranscriptResult("旧句迟到尾词", True, 850))
    lease.stop("provider_stream_ended", retain_preview=True)
    snapshots = lease.terminal_previews
    assert [event.type for event in snapshots] == ["transcript", "utterance_revision"]
    assert snapshots[0].text == "新句还在说" and snapshots[0].is_final is False
    assert snapshots[1].text == "先前一句。旧句迟到尾词"
    assert snapshots[1].utterance_id == ready.utterance_id
    await registry.stop_lease(lease, "user_stop")
    assert lease.terminal_previews == ()


@pytest.mark.asyncio
async def test_natural_candidate_commit_token_and_request_identity_are_one_use():
    registry, lease = await _natural_lease()
    await lease._on_activity(ContinuousSpeechActivity("begin", 100))
    await lease._on_activity(ContinuousSpeechActivity("end", 800))
    await lease._on_transcript(ContinuousTranscriptResult("你好。", True, 800))
    ready, = [event for event in await _drain(lease) if event.type == "utterance_ready"]
    result = await lease.manual_commit(commit_id=_id(707), revision=ready.revision,
        utterance_id=ready.utterance_id, registry=registry)
    assert await lease.manual_commit(commit_id=_id(707), revision=ready.revision,
        utterance_id=ready.utterance_id, registry=registry) == result
    with pytest.raises(DomainError):
        await lease.manual_commit(commit_id=_id(708), revision=ready.revision,
            utterance_id=ready.utterance_id, registry=registry)
    with pytest.raises(DomainError):
        await lease.manual_commit(commit_id=_id(707), revision=ready.revision,
            utterance_id=_id(999), registry=registry)
    assert len(registry._utterances) == 1


@pytest.mark.asyncio
async def test_new_activity_can_settle_its_own_suffix_while_older_activity_is_held():
    registry, lease = await _natural_lease()
    await lease._on_activity(ContinuousSpeechActivity("begin", 100))
    await lease._on_activity(ContinuousSpeechActivity("end", 500))
    await lease._on_transcript(ContinuousTranscriptResult("播放重叠期间保留的文字。", True, 500))
    held, = [event for event in await _drain(lease) if event.type == "utterance_ready"]
    await lease._on_activity(ContinuousSpeechActivity("begin", 700))
    await lease._on_activity(ContinuousSpeechActivity("end", 1200))
    await lease._on_transcript(ContinuousTranscriptResult("打断之后的新话。", True, 1200))
    fresh, = [event for event in await _drain(lease) if event.type == "utterance_ready"]
    assert fresh.utterance_id != held.utterance_id
    assert fresh.text == "打断之后的新话。"
    committed = await lease.manual_commit(commit_id=_id(709), revision=fresh.revision,
        utterance_id=fresh.utterance_id, registry=registry)
    assert committed.text == fresh.text
    assert lease.stable_text == held.text
    reset, = [event for event in await _drain(lease) if event.type == "transcript"]
    assert reset.text == held.text
    assert reset.commit_id == committed.commit_id
    assert reset.utterance_id == fresh.utterance_id
    assert len(registry._utterances) == 1


@pytest.mark.asyncio
async def test_exact_delivered_commit_retry_remains_deliverable_after_reservation_and_acceptance():
    registry, lease = await _natural_lease()
    await lease._on_activity(ContinuousSpeechActivity("begin", 100))
    await lease._on_activity(ContinuousSpeechActivity("end", 800))
    await lease._on_transcript(ContinuousTranscriptResult("精确重试", True, 800))
    ready, = [event for event in await _drain(lease) if event.type == "utterance_ready"]
    result = await lease.manual_commit(commit_id=_id(710), revision=ready.revision,
        utterance_id=ready.utterance_id, registry=registry)
    assert await registry.mark_delivered(lease.session_id, lease.lease_id, result.commit_id)
    await registry.validate_submission(lease.session_id, result.commit_id, "same-input", result.text)
    assert await registry.mark_delivered(lease.session_id, lease.lease_id, result.commit_id)
    await registry.mark_accepted(lease.session_id, result.commit_id, "same-input", result.text)
    assert await registry.mark_delivered(lease.session_id, lease.lease_id, result.commit_id)
    assert not await registry.mark_delivered("different-session", lease.lease_id, result.commit_id)


@pytest.mark.asyncio
async def test_global_stop_after_finite_limit_still_fences_unsent_terminal_preview():
    registry = ContinuousListeningRegistry()
    lease = await registry.start("session-limit-stop", _id(720))
    await lease._on_transcript(ContinuousTranscriptResult("尚未写到页面的输入", True, 100))
    await registry.stop_lease(lease, "max_samples")
    assert lease.terminal_preview is not None
    await registry.stop_session(lease.session_id, "user_stop")
    assert lease.terminal_previews == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["pending", "reserved", "accepted"])
async def test_exact_commit_delivery_retry_preserves_binding_without_consuming_again(phase):
    registry = ContinuousListeningRegistry()
    lease = await registry.start("retry-session", _id(901))
    await lease._on_transcript(ContinuousTranscriptResult("同一段", True, 100))
    result = await lease.manual_commit(commit_id=_id(902), revision=lease.revision, registry=registry)
    assert await registry.mark_delivered("retry-session", lease.lease_id, result.commit_id)
    if phase in {"reserved", "accepted"}:
        await registry.validate_submission("retry-session", result.commit_id, "same-request", result.text)
    if phase == "accepted":
        await registry.mark_accepted("retry-session", result.commit_id, "same-request", result.text)
    assert await lease.manual_commit(commit_id=result.commit_id, revision=result.revision, registry=registry) == result
    assert await registry.mark_delivered("retry-session", lease.lease_id, result.commit_id)
    binding = registry._utterances[("retry-session", result.commit_id)]
    assert binding.status == phase
    assert lease._commit_count == 1
    assert not await registry.mark_delivered("other-session", lease.lease_id, result.commit_id)
    assert not await registry.mark_delivered("retry-session", _id(903), result.commit_id)
    with pytest.raises(DomainError):
        await lease.manual_commit(commit_id=result.commit_id, revision=result.revision + 1, registry=registry)
    if phase != "pending":
        with pytest.raises(DomainError):
            await registry.validate_submission("retry-session", result.commit_id, "changed-request", result.text)
        with pytest.raises(DomainError):
            await registry.validate_submission("retry-session", result.commit_id, "same-request", "changed-text")
    await registry.stop_session("retry-session", "user_stop")
    assert await registry.mark_delivered("retry-session", lease.lease_id, result.commit_id) is (phase == "accepted")


@pytest.mark.asyncio
async def test_client_silence_queued_cancellation_keeps_pcm_and_same_stream_alive():
    from mira.application.continuous_listening import _RecognitionSegment
    registry, lease = await _natural_lease()
    segment = _RecognitionSegment(1)
    lease._segment = segment
    await lease.request_client_endpoint(endpoint_id=_id(1001), source_end_sample=1600)
    await lease.cancel_client_endpoint(endpoint_id=_id(1001))
    assert not segment.draining and segment.client_endpoint is None
    stream = lease.audio.segment_packets(segment)
    packet = await anext(stream)
    assert len(packet.pcm) // 2 == 1600
    assert lease.active and not segment.stop_requests.is_set()
    states = [event.endpoint_state for event in await _drain(lease) if event.type == "endpoint_status"]
    assert states == ["queued", "cancelled"]
    await lease.aclose()
    await stream.aclose()


@pytest.mark.asyncio
async def test_client_silence_frontier_drains_queued_pcm_and_preserves_later_packets():
    from mira.application.continuous_listening import _RecognitionSegment
    registry, lease = await _natural_lease()
    segment = _RecognitionSegment(1)
    lease._segment = segment
    await lease.request_client_endpoint(endpoint_id=_id(1002), source_end_sample=1600)
    lease.audio.push(lease_id=lease.lease_id, sequence=2, first_sample=1600, pcm=b"\x01\0" * 320)
    stream = lease.audio.segment_packets(segment)
    assert len((await anext(stream)).pcm) // 2 == 1600
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), .5)
    assert segment.last_sample == 1600 and segment.draining
    assert lease.audio._queued_samples == 320
    assert not registry._utterances
    await lease.aclose()


@pytest.mark.asyncio
async def test_client_silence_stop_cancels_queued_endpoint_without_reviving():
    from mira.application.continuous_listening import _RecognitionSegment
    registry, lease = await _natural_lease()
    lease._segment = _RecognitionSegment(1)
    await lease.request_client_endpoint(endpoint_id=_id(1003), source_end_sample=1600)
    await registry.stop_lease(lease, "user_stop")
    with pytest.raises(DomainError):
        await lease.cancel_client_endpoint(endpoint_id=_id(1003))
    await asyncio.sleep(0)
    assert not registry._utterances and lease.terminal_previews == ()
    assert all(event.type == "stopped" for event in await _drain(lease))


@pytest.mark.asyncio
async def test_client_silence_late_missing_offset_final_stays_linked_after_accepted_input():
    from mira.application.continuous_listening import _RecognitionSegment, _ClientEndpoint
    registry, lease = await _natural_lease()
    endpoint = _ClientEndpoint(_id(1004), 1600, "completed")
    segment = _RecognitionSegment(1, base_sample=0, last_sample=1600, draining=True,
                                  client_endpoint=endpoint)
    lease._segment = segment
    await lease._on_activity(ContinuousSpeechActivity("begin", 0))
    await lease._on_transcript(ContinuousTranscriptResult("已经发送的句子。", True, None))
    lease._segment_sealed = True
    lease._settle_client_endpoint(segment)
    candidate = lease.natural_candidate()
    assert candidate is not None
    committed = await lease.manual_commit(commit_id=_id(1005), revision=candidate.revision,
        utterance_id=candidate.utterance_id, registry=registry)
    await registry.mark_delivered(lease.session_id, lease.lease_id, committed.commit_id)
    await registry.validate_submission(lease.session_id, committed.commit_id, "accepted-request", committed.text)
    await registry.mark_accepted(lease.session_id, committed.commit_id, "accepted-request", committed.text)
    await _drain(lease)
    await lease._on_transcript(ContinuousTranscriptResult("迟到的尾词。", True, None))
    correction, = [event for event in await _drain(lease) if event.type == "utterance_revision"]
    assert correction.utterance_id == candidate.utterance_id
    assert correction.commit_id == committed.commit_id and correction.submission_state == "accepted"
    assert correction.text == "已经发送的句子。迟到的尾词。"
    assert lease.stable_text == "" and len(registry._utterances) == 1


@pytest.mark.asyncio
async def test_client_silence_queue_wait_has_the_same_bounded_timeout():
    from mira.application.continuous_listening import _RecognitionSegment
    registry = ContinuousListeningRegistry(limits=ListeningLimits(drain_timeout_seconds=.1))
    lease = await registry.start("stalled-requests", _id(1006), natural_mode=True,
                                 client_endpointing=True)
    lease._segment = _RecognitionSegment(1)
    lease.audio.push(lease_id=lease.lease_id, sequence=1, first_sample=0, pcm=b"\0\0" * 320)
    await lease.request_client_endpoint(endpoint_id=_id(1007), source_end_sample=320)
    while True:
        event = await asyncio.wait_for(lease.events.get(), .5)
        if event.type == "stopped":
            break
    assert event.reason == "timeout" and not lease.active
    assert not registry._utterances


@pytest.mark.parametrize("value", [249, 2001, True, 700.1])
def test_client_silence_limit_rejects_invalid_timing(value):
    with pytest.raises(ValueError):
        ListeningLimits(client_silence_ms=value)
