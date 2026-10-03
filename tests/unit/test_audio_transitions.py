"""Typed software audio facts; no physical-hearing or text-alignment assertions."""
from dataclasses import replace

import pytest

from mira.domain.errors import DomainError
from mira.domain.models import AudioProgress, AudioStatus, Effect, EffectKind, Receipt, SessionState
from mira.domain.transitions import (
    MAX_AUDIO_PROGRESS, accept_range, begin_input, record_audio_progress, record_receipt, seal, stop,
)


def issued():
    state = begin_input(SessionState("s", "c"), activity_seq=1, cutoff=0,
                        request_id="r", text="hello")
    speech = Effect("speak", EffectKind.SPEECH, "Approved full speech.", "a" * 64, 1, 1)
    visual = replace(speech, id="visual", kind=EffectKind.SUBTITLE)
    return accept_range(state, output_epoch=1, effects=(speech, visual)), speech, visual


def progress(effect, sequence=1, samples=240, status=AudioStatus.RENDERED):
    return AudioProgress(effect.id, effect.digest, effect.output_epoch, effect.activity_seq,
                         sequence, 24000, samples, status)


def visual_receipt(effect, sequence=1):
    return Receipt(effect.id, effect.digest, effect.output_epoch, effect.activity_seq, sequence)


def test_audio_and_visual_sequences_share_one_namespace():
    state, speech, visual = issued()
    state = record_audio_progress(state, progress(speech))
    with pytest.raises(DomainError, match="sequence"):
        record_receipt(state, visual_receipt(visual))
    state, speech, visual = issued()
    state = record_receipt(state, visual_receipt(visual))
    with pytest.raises(DomainError, match="sequence"):
        record_audio_progress(state, progress(speech))


def test_sealed_mixed_plan_needs_both_channels():
    state, speech, visual = issued()
    state = seal(state, output_epoch=1)
    state = record_audio_progress(state, progress(speech, status=AudioStatus.COMPLETED))
    assert state.phase == "ready"
    state = record_receipt(state, visual_receipt(visual, 2))
    assert state.phase == "idle"


@pytest.mark.parametrize("status", [AudioStatus.INTERRUPTED, AudioStatus.FAILED])
def test_partial_terminal_is_retained_without_full_text_completion(status):
    state, speech, _ = issued()
    state = record_audio_progress(state, progress(speech))
    state = record_audio_progress(state, progress(speech, 2, 240, status))
    assert state.presented_effects == ()
    assert state.audio_progress[-1].status == status
    assert record_audio_progress(state, state.audio_progress[0]) is state
    with pytest.raises(DomainError, match="Terminal"):
        record_audio_progress(state, progress(speech, 3, 480, AudioStatus.COMPLETED))


def test_sample_rate_is_stable_for_one_effect():
    state, speech, _ = issued()
    state = record_audio_progress(state, progress(speech))
    with pytest.raises(DomainError, match="backwards"):
        record_audio_progress(state, replace(progress(speech, 2, 480), sample_rate_hz=16000))


def test_repeated_same_counter_needs_explicit_terminal_status():
    state, speech, _ = issued()
    state = record_audio_progress(state, progress(speech))
    with pytest.raises(DomainError, match="backwards"):
        record_audio_progress(state, progress(speech, 2))
    assert record_audio_progress(state, progress(speech, 2, status=AudioStatus.COMPLETED))


def test_audio_history_has_hard_bound_and_duplicates_still_work():
    state, speech, _ = issued()
    facts = tuple(progress(speech, i + 1, i + 1) for i in range(MAX_AUDIO_PROGRESS))
    state = replace(state, audio_progress=facts)
    assert record_audio_progress(state, facts[-1]) is state
    with pytest.raises(DomainError, match="budget"):
        record_audio_progress(state, progress(speech, MAX_AUDIO_PROGRESS + 1, MAX_AUDIO_PROGRESS + 1))


def test_late_completed_fact_does_not_change_new_branch():
    state, speech, _ = issued()
    state = stop(state, activity_seq=2, cutoff=1)
    # The new branch cannot capture context before the cutoff fact is known.
    with pytest.raises(DomainError) as pending:
        begin_input(state, activity_seq=3, cutoff=1, request_id="new", text="again")
    assert pending.value.code == "history_pending"
    terminal = progress(speech, status=AudioStatus.COMPLETED)
    state = record_audio_progress(state, terminal)
    state = begin_input(state, activity_seq=3, cutoff=1, request_id="new", text="again")
    # A duplicate delayed delivery is still history-only and cannot revive speech.
    late = record_audio_progress(state, terminal)
    assert late is state
    assert late.phase == state.phase == "thinking"
    assert late.active_grants == () and late.output_epoch == 3
    assert late.permit_revision == state.permit_revision
    assert late.presented_effects == (speech,)


def test_visual_effect_cannot_accept_audio_fact():
    state, _, visual = issued()
    with pytest.raises(DomainError, match="speech effect"):
        record_audio_progress(state, progress(visual))


@pytest.mark.parametrize("samples,status", [(0, AudioStatus.RENDERED), (0, AudioStatus.COMPLETED),
                                          (24000 * 301, AudioStatus.RENDERED)])
def test_sample_bounds_fail_closed(samples, status):
    state, speech, _ = issued()
    with pytest.raises(DomainError, match="bounds"):
        record_audio_progress(state, progress(speech, samples=samples, status=status))
