"""Directed domain/Actor tests for server receipt-before-input ordering."""
import asyncio
from dataclasses import replace

import pytest

from mira.adapters.fixture_catalog import FIXTURES
from mira.adapters.journal.memory import MemoryEventJournal
from mira.adapters.review.mock import FixtureReviewBackend
from mira.application.contracts import CandidateRange
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.domain.errors import DomainError
from mira.domain.models import (
    AudioProgress, AudioStatus, Effect, EffectKind, Fence, Phase, Receipt, SessionState,
)
from mira.domain.transitions import (
    _complete_presentation_prefix, accept_range, begin_input, record_audio_progress,
    record_receipt, stop,
)


def _started():
    return begin_input(SessionState("s", "c"), activity_seq=1, cutoff=0,
                       request_id="seed", text="seed")


def _effect(effect_id, kind, *, epoch=1, activity=1):
    return Effect(effect_id, kind, effect_id, (effect_id[0] * 64)[:64], epoch, activity)


def _receipt(effect, sequence):
    return Receipt(effect.id, effect.digest, effect.output_epoch, effect.activity_seq, sequence)


def _audio(effect, sequence):
    return AudioProgress(effect.id, effect.digest, effect.output_epoch, effect.activity_seq,
                         sequence, 24000, 240, AudioStatus.COMPLETED)


def test_input_requires_complete_global_prefix():
    state = accept_range(_started(), output_epoch=1, effects=(
        _effect("v1", EffectKind.MEDIA), _effect("a1", EffectKind.SPEECH),
        _effect("v2", EffectKind.MEDIA),
    ))
    # A cutoff-zero client needs no facts; audio and visual facts share one sequence space.
    assert begin_input(state, activity_seq=2, cutoff=0, request_id="zero", text="zero").activity_seq == 2

    # Sequence 2 exists but seq 1 is missing: the known maximum is not a prefix.
    state = record_receipt(state, _receipt(state.issued_effects[2], 2))
    with pytest.raises(DomainError) as pending:
        begin_input(state, activity_seq=2, cutoff=2, request_id="gap", text="gap")
    assert pending.value.code == "history_pending"

    state = record_audio_progress(state, _audio(state.issued_effects[1], 1))
    state = record_receipt(state, _receipt(state.issued_effects[0], 3))
    accepted = begin_input(state, activity_seq=2, cutoff=3, request_id="complete", text="complete")
    assert accepted.activity_seq == 2 and accepted.user_inputs == ("seed", "complete")


def test_interior_sequence_gap_blocks_input_until_shared_audio_fact_arrives():
    state = accept_range(_started(), output_epoch=1, effects=(
        _effect("v1", EffectKind.MEDIA), _effect("a1", EffectKind.SPEECH),
        _effect("v2", EffectKind.MEDIA),
    ))
    state = record_receipt(state, _receipt(state.issued_effects[0], 1))
    state = record_receipt(state, _receipt(state.issued_effects[2], 3))
    with pytest.raises(DomainError) as pending:
        begin_input(state, activity_seq=2, cutoff=3, request_id="interior", text="interior")
    assert pending.value.code == "history_pending"
    state = record_audio_progress(state, _audio(state.issued_effects[1], 2))
    assert begin_input(state, activity_seq=2, cutoff=3, request_id="complete", text="complete")


def test_fact_above_cutoff_does_not_fill_a_missing_prefix_slot():
    state = accept_range(_started(), output_epoch=1,
                         effects=(_effect("v1", EffectKind.MEDIA), _effect("v2", EffectKind.MEDIA)))
    state = record_receipt(state, _receipt(state.issued_effects[1], 2))
    assert not _complete_presentation_prefix(state, 1)


def test_large_cutoff_is_checked_without_range_iteration():
    cutoff = 10 ** 1000
    with pytest.raises(DomainError) as pending:
        begin_input(_started(), activity_seq=2, cutoff=cutoff,
                    request_id="huge", text="huge")
    assert pending.value.code == "history_pending"


def test_stop_does_not_wait_for_prefix_and_late_fact_is_history_only():
    state = accept_range(_started(), output_epoch=1, effects=(_effect("v1", EffectKind.MEDIA),))
    stopped = stop(state, activity_seq=2, cutoff=1)
    assert stopped.phase == Phase.STOPPED and stopped.request_id is None
    assert stopped.active_grants == () and stopped.receipts == ()
    assert stopped.activity_seq == 2 and stopped.input_epoch == 1
    assert stopped.user_inputs == state.user_inputs

    late = record_receipt(stopped, _receipt(state.issued_effects[0], 1))
    assert late.receipts == (_receipt(state.issued_effects[0], 1),)
    assert late.phase == Phase.STOPPED and late.request_id is None and late.active_grants == ()


def _actor(generation):
    return SessionActor(SessionState("s", "c"), generation, FixtureReviewBackend(),
                        MemoryEventJournal(100), RuntimeLimits(2, 16, 128))


async def _wait_for_snapshot(actor, predicate):
    async with asyncio.timeout(2):
        while True:
            state = await actor.snapshot()
            if predicate(state):
                return state
            await asyncio.sleep(.002)


@pytest.mark.asyncio
async def test_pending_input_revokes_uncooperative_old_branch_without_consuming_retry():
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()
    contexts = []

    class UncooperativeThenRetry:
        async def generate(self, context):
            contexts.append(context)
            if context.user_text == "old":
                yield CandidateRange(FIXTURES["hello"], "hello")
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await release.wait()
                # This output comes from a cancellation-resistant old provider.
                yield CandidateRange(FIXTURES["camera"], "camera")
            else:
                yield CandidateRange(FIXTURES["hello"], "hello")

    actor = _actor(UncooperativeThenRetry())
    try:
        await actor.submit(request_id="old-id", activity_seq=1, cutoff=0, text="old")
        await entered.wait()
        before = await _wait_for_snapshot(actor, lambda state: bool(state.issued_effects))
        assert before.request_id == "old-id" and before.output_epoch == 1
        assert before.activity_seq == 1 and before.input_epoch == 1
        assert before.receipts == ()

        with pytest.raises(DomainError) as pending:
            await actor.submit(request_id="retry-id", activity_seq=2, cutoff=1, text="retry")
        assert pending.value.code == "history_pending"
        await asyncio.wait_for(cancelled.wait(), .5)

        revoked = await actor.snapshot()
        assert revoked.activity_seq == 1 and revoked.input_epoch == 1
        assert revoked.user_inputs == ("old",) and revoked.request_id is None
        assert revoked.output_epoch == 2 and revoked.phase == Phase.STOPPED
        assert revoked.active_grants == () and revoked.issued_effects == before.issued_effects
        assert revoked.last_presentation_cutoff == 1 and revoked.fences == (Fence(1, 1),)
        assert set(actor._request_fingerprints) == {"old-id"}
        assert tuple(item.event_id for item in actor._decision_inputs) == ("old-id",)

        # The late but valid receipt fills the exact hole without restoring the old branch.
        first_effect = before.issued_effects[0]
        await actor.receipt(_receipt(first_effect, 1))
        late = await actor.snapshot()
        assert late.phase == Phase.STOPPED and late.request_id is None and late.active_grants == ()

        # Retry the exact same request identity after the fact is accepted.
        retried = await actor.submit(request_id="retry-id", activity_seq=2, cutoff=1, text="retry")
        assert retried.activity_seq == 2 and retried.input_epoch == 2
        assert retried.user_inputs == ("old", "retry")
        await _wait_for_snapshot(actor, lambda state: state.sealed and state.output_epoch == 3)
        assert len(contexts) == 2  # old branch and exact retry; its continuation is the same call
        assert contexts[-1].presented_effects == (first_effect,)
        assert tuple(item.event_id for item in actor._decision_inputs) == ("old-id", "retry-id")

        # The accepted id is still idempotent and never appends a second input.
        idempotent = await actor.submit(request_id="retry-id", activity_seq=2, cutoff=1, text="retry")
        assert idempotent == await actor.snapshot()
        assert (await actor.snapshot()).user_inputs == ("old", "retry")
    finally:
        release.set()
        await actor.close()
