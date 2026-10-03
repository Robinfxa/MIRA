"""Pure state transitions. Visual receipts and software audio facts are distinct."""
from dataclasses import replace

from mira.domain.errors import DomainError
from mira.domain.models import (
    AudioProgress, AudioStatus, Effect, EffectKind, Fence, Phase, Receipt, SessionState,
)

# Bounded append-only facts preserve duplicate detection and sequence uniqueness.
MAX_AUDIO_PROGRESS = 4096
MAX_AUDIO_SECONDS = 300


def _presentation_sequences(state: SessionState) -> tuple[int, ...]:
    return tuple(r.presentation_seq for r in state.receipts) + tuple(
        p.presentation_seq for p in state.audio_progress
    )


def _cutoff(state: SessionState, value: int) -> None:
    known = max(_presentation_sequences(state), default=0)
    previous = state.last_presentation_cutoff
    if value < max(known, previous):
        raise DomainError("invalid_cutoff", "Presentation cutoff cannot move backwards.")


def _fences_after_stop(state: SessionState, cutoff: int) -> tuple[Fence, ...]:
    # An empty branch has no receipts to validate. Do not retain an unbounded
    # collection of fences when a user repeatedly presses Stop.
    if any(effect.output_epoch == state.output_epoch for effect in state.issued_effects):
        return state.fences + (Fence(state.output_epoch, cutoff),)
    return state.fences


def begin_input(
    state: SessionState, *, activity_seq: int, cutoff: int, request_id: str, text: str
) -> SessionState:
    if activity_seq <= state.activity_seq:
        raise DomainError("stale_activity", "A new request needs a newer local activity.")
    _cutoff(state, cutoff)
    return replace(
        state, revision=state.revision + 1, activity_seq=activity_seq,
        input_epoch=state.input_epoch + 1, output_epoch=state.output_epoch + 1,
        permit_revision=state.permit_revision + 1, phase=Phase.THINKING,
        request_id=request_id, sealed=False, active_grants=(), last_error=None,
        last_error_diagnostic_id=None,
        fences=_fences_after_stop(state, cutoff), last_presentation_cutoff=cutoff,
        user_inputs=state.user_inputs + (text,),
    )


def stop(state: SessionState, *, activity_seq: int, cutoff: int) -> SessionState:
    # Retransmission does not produce a new transition or undo a later input.
    if activity_seq <= state.activity_seq:
        return state
    _cutoff(state, cutoff)
    return replace(
        state, revision=state.revision + 1, activity_seq=activity_seq,
        output_epoch=state.output_epoch + 1, permit_revision=state.permit_revision + 1,
        phase=Phase.STOPPED, request_id=None, active_grants=(), sealed=False,
        fences=_fences_after_stop(state, cutoff), last_presentation_cutoff=cutoff, last_error=None,
        last_error_diagnostic_id=None,
    )


def accept_range(
    state: SessionState, *, output_epoch: int, effects: tuple[Effect, ...]
) -> SessionState:
    if output_epoch != state.output_epoch or state.request_id is None or state.sealed:
        return state  # A late provider result cannot reopen a branch.
    if any(e.output_epoch != output_epoch or e.activity_seq != state.activity_seq for e in effects):
        raise DomainError("invalid_effect", "Effect origin does not match this branch.")
    ids = [e.id for e in state.issued_effects] + [e.id for e in effects]
    if len(ids) != len(set(ids)):
        raise DomainError("duplicate_effect", "An effect identity cannot be reused.")
    return replace(
        state, revision=state.revision + 1, permit_revision=state.permit_revision + 1,
        phase=Phase.READY, active_grants=state.active_grants + effects,
        issued_effects=state.issued_effects + effects,
    )


def seal(state: SessionState, *, output_epoch: int) -> SessionState:
    if output_epoch != state.output_epoch or state.request_id is None:
        return state
    received = {e.id for e in state.presented_effects}
    finished = all(e.id in received for e in state.active_grants)
    return replace(state, revision=state.revision + 1, sealed=True,
                   phase=Phase.IDLE if finished else Phase.READY)


def fail(state: SessionState, *, output_epoch: int, code: str,
         diagnostic_id: str | None = None) -> SessionState:
    if output_epoch != state.output_epoch or state.request_id is None:
        return state
    return replace(state, revision=state.revision + 1,
                   permit_revision=state.permit_revision + 1, phase=Phase.ERROR,
                   active_grants=(), request_id=None, last_error=code,
                   last_error_diagnostic_id=diagnostic_id)


def record_receipt(state: SessionState, receipt: Receipt) -> SessionState:
    effect = next((e for e in state.issued_effects if e.id == receipt.effect_id), None)
    if effect is None:
        raise DomainError("unknown_effect", "Receipt has no issued effect.")
    if (effect.digest, effect.output_epoch, effect.activity_seq) != (
        receipt.digest, receipt.output_epoch, receipt.activity_seq
    ):
        raise DomainError("receipt_mismatch", "Receipt identity differs from the issued effect.")
    if effect.kind == EffectKind.SPEECH:
        raise DomainError("audio_receipt_required", "Speech requires typed audio progress.")
    previous = next((r for r in state.receipts if r.effect_id == receipt.effect_id), None)
    if previous is not None:
        if previous == receipt:
            return state
        raise DomainError("receipt_conflict", "A presentation cannot be rewritten.")
    if receipt.presentation_seq <= 0 or receipt.presentation_seq in _presentation_sequences(state):
        raise DomainError("receipt_sequence", "Presentation sequence must identify one effect.")
    fence = next((f for f in state.fences if f.output_epoch == effect.output_epoch), None)
    if fence is not None and receipt.presentation_seq > fence.presentation_cutoff:
        raise DomainError("after_stop_fence", "Old receipt claims presentation after its stop fence.")
    # An old valid receipt only adds history; it does not alter grants or restart the phase.
    receipts = state.receipts + (receipt,)
    phase = state.phase
    received = {r.effect_id for r in receipts} | {
        p.effect_id for p in state.audio_progress if p.status == AudioStatus.COMPLETED
    }
    if state.sealed and state.request_id is not None and all(
        e.id in received for e in state.active_grants
    ):
        phase = Phase.IDLE
    return replace(state, revision=state.revision + 1, receipts=receipts, phase=phase)


def record_audio_progress(state: SessionState, progress: AudioProgress, *,
                          diagnostic_id: str | None = None) -> SessionState:
    effect = next((e for e in state.issued_effects if e.id == progress.effect_id), None)
    if effect is None:
        raise DomainError("unknown_effect", "Audio progress has no issued effect.")
    if (effect.digest, effect.output_epoch, effect.activity_seq) != (
        progress.digest, progress.output_epoch, progress.activity_seq
    ):
        raise DomainError("receipt_mismatch", "Audio origin differs from the issued effect.")
    if effect.kind != EffectKind.SPEECH:
        raise DomainError("not_speech", "Audio progress requires a speech effect.")
    if (not isinstance(progress.status, AudioStatus)
            or not 8000 <= progress.sample_rate_hz <= 48000
            or not 0 <= progress.rendered_samples <= progress.sample_rate_hz * MAX_AUDIO_SECONDS
            or (progress.status in {AudioStatus.RENDERED, AudioStatus.COMPLETED}
                and progress.rendered_samples == 0)):
        raise DomainError("invalid_audio_progress", "Audio progress is outside the supported bounds.")
    if progress in state.audio_progress:
        return state
    if (progress.presentation_seq <= 0
            or progress.presentation_seq in _presentation_sequences(state)):
        raise DomainError("receipt_sequence", "Presentation sequence must identify one fact.")
    previous = next((p for p in reversed(state.audio_progress)
                     if p.effect_id == progress.effect_id), None)
    if previous is not None:
        if previous.status != AudioStatus.RENDERED:
            raise DomainError("audio_terminal", "Terminal audio progress cannot be rewritten.")
        if (progress.sample_rate_hz != previous.sample_rate_hz
                or progress.presentation_seq <= previous.presentation_seq
                or progress.rendered_samples < previous.rendered_samples
                or (progress.rendered_samples == previous.rendered_samples
                    and progress.status == AudioStatus.RENDERED)):
            raise DomainError("audio_non_monotonic", "Audio progress cannot move backwards.")
    fence = next((f for f in state.fences if f.output_epoch == effect.output_epoch), None)
    if fence is not None and progress.presentation_seq > fence.presentation_cutoff:
        raise DomainError("after_stop_fence", "Old audio claims rendering after its stop fence.")
    if len(state.audio_progress) >= MAX_AUDIO_PROGRESS:
        raise DomainError("audio_history_capacity", "Audio progress budget reached; create a new session.")
    changed = replace(state, revision=state.revision + 1,
                      audio_progress=state.audio_progress + (progress,))
    if (effect.output_epoch == state.output_epoch and state.request_id is not None
            and progress.status in {AudioStatus.INTERRUPTED, AudioStatus.FAILED}):
        # A current sink failure also revokes server authority. A later Stop can
        # still establish its exact presentation cutoff; old facts stay history.
        return replace(changed, phase=Phase.ERROR, active_grants=(), request_id=None,
                       permit_revision=state.permit_revision + 1,
                       last_error="audio_" + progress.status.value,
                       last_error_diagnostic_id=diagnostic_id)
    # A late valid fact adds history only. It never revives grants or the old phase.
    if (effect.output_epoch == state.output_epoch and state.request_id is not None
            and state.sealed and all(e in changed.presented_effects for e in state.active_grants)):
        changed = replace(changed, phase=Phase.IDLE)
    return changed
