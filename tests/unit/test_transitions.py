from dataclasses import replace

import pytest

from mira.domain.errors import DomainError
from mira.domain.models import Effect, EffectKind, Phase, Receipt, SessionState
from mira.domain.transitions import accept_range, begin_input, fail, record_receipt, seal, stop


def initial():
    return SessionState("session", "client")


def started():
    return begin_input(initial(), activity_seq=1, cutoff=0, request_id="r1", text="hello")


def issued():
    state = started()
    effect = Effect("e1", EffectKind.SUBTITLE, "hello", "a" * 64, 1, 1)
    return accept_range(state, output_epoch=1, effects=(effect,)), effect


def receipt(effect, sequence=1):
    return Receipt(effect.id, effect.digest, effect.output_epoch, effect.activity_seq, sequence)


def test_input_advances_versions_without_mutating_original():
    original = initial()
    changed = begin_input(original, activity_seq=1, cutoff=0, request_id="r1", text="hi")
    assert original.revision == 0
    assert (changed.activity_seq, changed.input_epoch, changed.output_epoch, changed.permit_revision) == (1,1,1,1)
    assert changed.phase == Phase.THINKING


def test_stale_input_rejected():
    with pytest.raises(DomainError, match="newer"):
        begin_input(started(), activity_seq=1, cutoff=0, request_id="r2", text="again")


def test_stop_invalidates_future_but_not_received_history():
    state, effect = issued()
    state = record_receipt(state, receipt(effect))
    state = stop(state, activity_seq=2, cutoff=1)
    assert state.active_grants == () and state.phase == Phase.STOPPED
    assert state.presented_effects == (effect,)


def test_stop_retransmit_is_idempotent():
    state = stop(started(), activity_seq=2, cutoff=0)
    assert stop(state, activity_seq=2, cutoff=0) is state


def test_late_result_cannot_revive_stopped_branch():
    state, effect = issued()
    stopped = stop(state, activity_seq=2, cutoff=0)
    assert accept_range(stopped, output_epoch=1, effects=(effect,)) is stopped
    assert seal(stopped, output_epoch=1) is stopped
    assert fail(stopped, output_epoch=1, code="late_failure") is stopped


def test_snapshot_extension_keeps_valid_grants():
    state, effect = issued()
    second = replace(effect, id="e2", value="second", digest="b"*64)
    extended = accept_range(state, output_epoch=1, effects=(second,))
    assert extended.active_grants == (effect, second)
    assert extended.permit_revision == state.permit_revision + 1


def test_duplicate_effect_id_rejected():
    state, effect = issued()
    with pytest.raises(DomainError, match="reused"):
        accept_range(state, output_epoch=1, effects=(effect,))


def test_origin_mismatch_rejected():
    state, effect = issued()
    with pytest.raises(DomainError, match="origin"):
        accept_range(state, output_epoch=1, effects=(replace(effect,id="new",activity_seq=5),))


def test_receipt_does_not_mean_plan_is_sealed():
    state, effect = issued()
    state = record_receipt(state, receipt(effect))
    assert not state.sealed and state.phase == Phase.READY
    assert seal(state, output_epoch=1).phase == Phase.IDLE


def test_sealed_plan_waits_for_required_receipt():
    state, effect = issued()
    state = seal(state, output_epoch=1)
    assert state.phase == Phase.READY
    assert record_receipt(state, receipt(effect)).phase == Phase.IDLE


def test_duplicate_receipt_is_idempotent():
    state, effect = issued()
    state = record_receipt(state, receipt(effect))
    assert record_receipt(state, receipt(effect)) is state


def test_receipt_cannot_be_rewritten():
    state, effect = issued()
    state = record_receipt(state, receipt(effect))
    with pytest.raises(DomainError, match="rewritten"):
        record_receipt(state, receipt(effect,2))


def test_unknown_receipt_rejected():
    _, effect = issued()
    with pytest.raises(DomainError, match="no issued"):
        record_receipt(initial(), receipt(effect))


def test_wrong_digest_rejected():
    state, effect = issued()
    with pytest.raises(DomainError, match="identity"):
        record_receipt(state, replace(receipt(effect),digest="b"*64))


def test_late_valid_receipt_only_adds_history():
    state, effect = issued()
    state = stop(state,activity_seq=2,cutoff=1)
    patched = record_receipt(state,receipt(effect))
    assert patched.presented_effects == (effect,)
    assert patched.phase == Phase.STOPPED and patched.active_grants == ()
    assert patched.permit_revision == state.permit_revision


def test_late_receipt_beyond_stop_fence_rejected():
    state,effect = issued()
    state = stop(state,activity_seq=2,cutoff=0)
    with pytest.raises(DomainError, match="stop fence"):
        record_receipt(state,receipt(effect))


def test_cutoff_cannot_erase_acknowledged_progress():
    state,effect=issued()
    state=record_receipt(state,receipt(effect))
    with pytest.raises(DomainError,match="backwards"):
        stop(state,activity_seq=2,cutoff=0)


def test_duplicate_presentation_sequence_rejected():
    state,effect=issued()
    second=replace(effect,id="e2")
    state=accept_range(state,output_epoch=1,effects=(second,))
    state=record_receipt(state,receipt(effect))
    with pytest.raises(DomainError,match="sequence"):
        record_receipt(state,receipt(second))


def test_new_request_after_stop_has_new_origin_and_no_old_grants():
    state,effect=issued()
    state=stop(state,activity_seq=2,cutoff=0)
    resumed=begin_input(state,activity_seq=3,cutoff=0,request_id="r3",text="continue")
    assert resumed.output_epoch == 3 and resumed.request_id == "r3"
    assert resumed.active_grants == ()
    assert accept_range(resumed,output_epoch=1,effects=(effect,)) is resumed


def test_repeated_stops_do_not_grow_fences_without_issued_effects():
    state=initial()
    for activity in range(1,1001):
        state=stop(state,activity_seq=activity,cutoff=0)
    assert state.fences==() and state.activity_seq==1000
