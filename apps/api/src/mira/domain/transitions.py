"""Pure state transitions. Visual receipts and software audio facts are distinct."""
from dataclasses import replace

from mira.domain.errors import DomainError
from mira.domain.story_images import ImageReservation, parse_generated_photo
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


def _complete_presentation_prefix(state: SessionState, cutoff: int) -> bool:
    # Presentation sequences are globally unique and the retained history is bounded.
    # Compare the count instead of iterating over a client-controlled cutoff.
    return (cutoff >= state.presentation_floor and
            len({sequence for sequence in _presentation_sequences(state)
                 if state.presentation_floor < sequence <= cutoff}) == cutoff - state.presentation_floor)


def _cutoff(state: SessionState, value: int) -> None:
    known = max(_presentation_sequences(state), default=state.presentation_floor)
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
    if not _complete_presentation_prefix(state, cutoff):
        raise DomainError("history_pending", "Presentation history through the cutoff is incomplete.")
    return replace(
        state, revision=state.revision + 1, activity_seq=activity_seq,
        input_epoch=state.input_epoch + 1, output_epoch=state.output_epoch + 1,
        permit_revision=state.permit_revision + 1, phase=Phase.THINKING,
        request_id=request_id, sealed=False, active_grants=(), last_error=None,
        last_error_diagnostic_id=None,
        fences=_fences_after_stop(state, cutoff), last_presentation_cutoff=cutoff,
        user_inputs=state.user_inputs + (text,),
        image_reservations=tuple(replace(r,consumed=False) if r.qualified_resource_id
            and not any(parse_generated_photo(e.value)==(r.qualified_resource_id,r.qualified_content_digest)
                for e in state.presented_effects) else r for r in state.image_reservations),
    )


def revoke_for_history_pending(state: SessionState, *, cutoff: int) -> SessionState:
    """Revoke the prior branch without consuming a local Stop/input activity."""
    if state.request_id is None:
        return state
    _cutoff(state, cutoff)
    return replace(
        state, revision=state.revision + 1,
        output_epoch=state.output_epoch + 1, permit_revision=state.permit_revision + 1,
        phase=Phase.STOPPED, request_id=None, active_grants=(), sealed=False,
        fences=_fences_after_stop(state, cutoff), last_presentation_cutoff=cutoff,
        last_error=None, last_error_diagnostic_id=None,
    )


def stop(state: SessionState, *, activity_seq: int, cutoff: int, cancel_images: bool = True) -> SessionState:
    # Retransmission does not produce a new transition or undo a later input.
    if activity_seq <= state.activity_seq:
        return state
    _cutoff(state, cutoff)
    return replace(
        state, revision=state.revision + 1, activity_seq=activity_seq,
        output_epoch=state.output_epoch + 1, permit_revision=state.permit_revision + 1,
        phase=Phase.STOPPED, request_id=None, active_grants=(), sealed=False,
        image_cancellation_generation=state.image_cancellation_generation+int(cancel_images),
        fences=_fences_after_stop(state, cutoff), last_presentation_cutoff=cutoff, last_error=None,
        last_error_diagnostic_id=None,
    )


def _authored_photo(effect: Effect) -> bool:
    return effect.kind is EffectKind.MEDIA and (effect.value in ('trip_photo', 'trip_photo_placeholder') or parse_generated_photo(effect.value) is not None)


def dismiss_photo(state: SessionState, *, expected_revision: int, cutoff: int,
                  target: str = 'all_photos', effect_id: str | None = None,
                  resource_id: str | None = None) -> SessionState:
    """Close an exact surface or explicitly cancel image work, without reply/audio stop."""
    if expected_revision != state.photo_visibility_revision:
        raise DomainError('photo_revision_conflict', 'Photo visibility revision changed.')
    if cutoff < 0 or not _complete_presentation_prefix(state, cutoff):
        raise DomainError('history_pending', 'Presentation history through the cutoff is incomplete.')
    if target not in ('fixed_photo','image_job','display_generated','all_photos'):
        raise DomainError('invalid_input','Invalid photo control target.')
    cancel_images=target in ('image_job','all_photos')
    close_fixed=target in ('fixed_photo','all_photos')
    def closes(effect):
        if not _authored_photo(effect):return False
        identity=parse_generated_photo(effect.value)
        if target=='all_photos':return True
        if target=='fixed_photo':return identity is None
        if target=='display_generated':return effect.id==effect_id
        return identity is not None and identity[0]==resource_id
    grants=tuple(e for e in state.active_grants if not closes(e))
    received={effect.id for effect in state.presented_effects}
    phase=state.phase
    if state.sealed and state.request_id is not None and all(e.id in received for e in grants):phase=Phase.IDLE
    photos={e.id:e for e in state.presented_effects if _authored_photo(e)}
    latest=max((r for r in state.receipts if r.effect_id in photos),key=lambda r:r.presentation_seq,default=None)
    closes_visible=target=='all_photos' or latest is not None and closes(photos[latest.effect_id])
    return replace(state,revision=state.revision+1,permit_revision=state.permit_revision+1,
        active_grants=grants,phase=phase,photo_visible=state.photo_visible and not closes_visible,
        photo_visibility_revision=state.photo_visibility_revision+1,
        image_cancellation_generation=state.image_cancellation_generation+int(cancel_images),
        photo_dismissed_through_activity=state.activity_seq if close_fixed else state.photo_dismissed_through_activity,
        photo_dismissal_cutoff=cutoff if close_fixed else state.photo_dismissal_cutoff,
        image_dismissed_through_activity=state.activity_seq if cancel_images else state.image_dismissed_through_activity,
        image_dismissal_cutoff=cutoff if cancel_images else state.image_dismissal_cutoff)


def _photo_dismissed(state: SessionState, effect: Effect) -> bool:
    cutoff=state.image_dismissed_through_activity if parse_generated_photo(effect.value) else state.photo_dismissed_through_activity
    return _authored_photo(effect) and effect.activity_seq<=cutoff


def accept_range(
    state: SessionState, *, output_epoch: int, effects: tuple[Effect, ...]
) -> SessionState:
    if output_epoch != state.output_epoch or state.request_id is None or state.sealed:
        return state  # A late provider result cannot reopen a branch.
    if any(e.output_epoch != output_epoch or e.activity_seq != state.activity_seq for e in effects):
        raise DomainError("invalid_effect", "Effect origin does not match this branch.")
    # A close fences every photo from this activity, including grants approved later.
    effects = tuple(e for e in effects if not _photo_dismissed(state,e))
    if not effects:
        return state
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



def set_response_preference(state: SessionState, *, muted: bool,
                            expected_revision: int) -> SessionState:
    if type(muted) is not bool or type(expected_revision) is not int or expected_revision < 0:
        raise DomainError("invalid_input", "Invalid output preference.")
    if expected_revision != state.response_preference_revision:
        raise DomainError("stale_activity", "Output preference changed; refresh before retrying.")
    # Never revive old speech on unmute. The next accepted input computes its mode.
    grants = tuple(e for e in state.active_grants
                   if e.kind != EffectKind.SPEECH and (not muted or e.cue_speech_id is None)) if muted else state.active_grants
    return replace(state, revision=state.revision + 1,
                   permit_revision=state.permit_revision + int(grants != state.active_grants),
                   response_preference_revision=state.response_preference_revision + 1,
                   response_muted=muted,
                   response_mode="text_only" if muted else state.response_mode,
                   active_grants=grants)


def fail_speech(state: SessionState, *, output_epoch: int, effect_id: str, code: str,
                diagnostic_id: str | None = None) -> SessionState:
    """Retain only already-issued independent text when current speech fails."""
    if (output_epoch != state.output_epoch or state.request_id is None
            or not any(e.id == effect_id and e.kind == EffectKind.SPEECH
                       for e in state.active_grants)):
        return state
    independent = tuple(e for e in state.active_grants
                        if e.kind == EffectKind.SUBTITLE and e.cue_id is not None
                        and e.cue_speech_id is None)
    if not independent:
        return fail(state, output_epoch=output_epoch, code=code, diagnostic_id=diagnostic_id)
    received = {r.effect_id for r in state.receipts}
    return replace(state, revision=state.revision + 1,
                   permit_revision=state.permit_revision + 1,
                   phase=Phase.IDLE if all(e.id in received for e in independent) else Phase.READY,
                   active_grants=independent, sealed=True, last_error=code,
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
    if receipt.presentation_seq <= state.presentation_floor or receipt.presentation_seq in _presentation_sequences(state):
        raise DomainError("receipt_sequence", "Presentation sequence must identify one effect.")
    fence = next((f for f in state.fences if f.output_epoch == effect.output_epoch), None)
    if fence is not None and receipt.presentation_seq > fence.presentation_cutoff:
        raise DomainError("after_stop_fence", "Old receipt claims presentation after its stop fence.")
    if (_photo_dismissed(state,effect) and receipt.presentation_seq >
            (state.image_dismissal_cutoff if parse_generated_photo(effect.value) else state.photo_dismissal_cutoff)):
        raise DomainError('after_photo_dismissal', 'Photo receipt claims presentation after dismissal.')
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
    visible = state.photo_visible or (_authored_photo(effect) and not _photo_dismissed(state,effect))
    return replace(state, revision=state.revision + 1, receipts=receipts, phase=phase,
                   photo_visible=visible)


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
    if (progress.presentation_seq <= state.presentation_floor
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
        # A terminal report after a TTS failure only adds a fact: the speech is
        # already revoked, and must not revoke the independently retained text.
        return fail_speech(changed, output_epoch=effect.output_epoch, effect_id=effect.id,
                           code="audio_" + progress.status.value, diagnostic_id=diagnostic_id)
    # A late valid fact adds history only. It never revives grants or the old phase.
    if (effect.output_epoch == state.output_epoch and state.request_id is not None
            and state.sealed and all(e in changed.presented_effects for e in state.active_grants)):
        changed = replace(changed, phase=Phase.IDLE)
    return changed


def reserve_generated_media(state: SessionState, reservation: ImageReservation) -> SessionState:
    if (type(reservation) is not ImageReservation or state.request_id is None
            or reservation.session_id!=state.session_id
            or reservation.cancellation_generation!=state.image_cancellation_generation
            or (state.request_id,state.output_epoch,state.activity_seq,state.photo_visibility_revision)
            != (reservation.parent_request_id,reservation.output_epoch,reservation.activity_seq,reservation.photo_visibility_revision)
            or state.activity_seq <= state.image_dismissed_through_activity
            or any(r.parent_request_id == reservation.parent_request_id for r in state.image_reservations)
            or len(state.image_reservations) >= 4):
        return state
    return replace(state,revision=state.revision+1,image_reservations=state.image_reservations+(reservation,))


def accept_generated_media(state: SessionState, *, reservation: ImageReservation, effect: Effect) -> SessionState:
    """One current grant for exact independently qualified bytes from a live session job."""
    if (reservation.qualified_resource_id is None or reservation.qualified_content_digest is None
            or reservation not in state.image_reservations or reservation.consumed
            or reservation.session_id!=state.session_id
            or reservation.cancellation_generation!=state.image_cancellation_generation
            or state.request_id is None or state.activity_seq<=state.image_dismissed_through_activity
            or any(parse_generated_photo(e.value)==(reservation.qualified_resource_id,reservation.qualified_content_digest)
                for e in state.presented_effects)):return state
    if (effect.kind is not EffectKind.MEDIA or parse_generated_photo(effect.value)!=
            (reservation.qualified_resource_id,reservation.qualified_content_digest)
            or (effect.output_epoch,effect.activity_seq)!=(state.output_epoch,state.activity_seq)
            or any(e.id==effect.id for e in state.issued_effects)):
        raise DomainError('invalid_effect','Invalid reserved image effect.')
    reservations=tuple(replace(r,consumed=True,current_effect_id=effect.id) if r==reservation else r for r in state.image_reservations)
    return replace(state,revision=state.revision+1,permit_revision=state.permit_revision+1,
        phase=Phase.READY,image_reservations=reservations,
        active_grants=state.active_grants+(effect,),issued_effects=state.issued_effects+(effect,))


def qualify_generated_media(state: SessionState, *, reservation: ImageReservation,
        resource_id: str, content_digest: str, specification_digest: str, policy_revision: str) -> SessionState:
    if (reservation not in state.image_reservations or reservation.consumed
            or reservation.qualified_resource_id is not None or reservation.session_id!=state.session_id
            or reservation.cancellation_generation!=state.image_cancellation_generation
            or (reservation.specification_digest,reservation.policy_revision)!=(specification_digest,policy_revision)
            or parse_generated_photo('generated_story_photo:v1:'+resource_id+':'+content_digest) is None):return state
    qualified=replace(reservation,qualified_resource_id=resource_id,qualified_content_digest=content_digest)
    return replace(state,revision=state.revision+1,
        image_reservations=tuple(qualified if r==reservation else r for r in state.image_reservations))


def accept_image_completion(state: SessionState, *, request_id: str, parent_request_id: str,
                            output_epoch: int, activity_seq: int, effects: tuple[Effect,...]) -> SessionState:
    """A single post-seal dialogue append; no prior grant or job is reopened."""
    image=state.story_image
    if (not state.sealed or state.request_id!=parent_request_id
            or (state.output_epoch,state.activity_seq)!=(output_epoch,activity_seq)
            or image.request_id!=request_id or image.completion_state!='requested'
            or image.state not in ('presented','failed')):return state
    if (not effects or len(effects)>2 or sum(e.kind is EffectKind.SUBTITLE for e in effects)!=1
            or any(e.kind not in (EffectKind.SUBTITLE,EffectKind.SPEECH)
                or (e.output_epoch,e.activity_seq)!=(output_epoch,activity_seq) for e in effects)
            or len({e.id for e in (*state.issued_effects,*effects)})!=len(state.issued_effects)+len(effects)):
        raise DomainError('invalid_effect','Invalid image completion cue.')
    return replace(state,revision=state.revision+1,permit_revision=state.permit_revision+1,
        phase=Phase.READY,active_grants=state.active_grants+effects,issued_effects=state.issued_effects+effects,
        story_image=replace(image,completion_state='granted',
            completion_effect_id=next(e.id for e in effects if e.kind is EffectKind.SUBTITLE),
            completion_speech_effect_id=next((e.id for e in effects if e.kind is EffectKind.SPEECH),None)))


def retain_recent_history(state: SessionState, *, max_inputs: int = 64, max_effects: int = 64) -> SessionState:
    """Retire only a proven complete old prefix after an accepted new input.

    Exact facts keep their original origin/digest. Old missing receipts are never
    synthesized; a retired sequence cannot be reused. This is RAM retention, not
    a summary, persistent archive, user correction, or assertion of total recall.
    """
    cutoff = state.last_presentation_cutoff
    if not _complete_presentation_prefix(state, cutoff):
        raise DomainError('history_pending', 'Cannot retire an incomplete presentation prefix.')
    omitted = max(0, len(state.user_inputs) - max_inputs)
    # Keep exact latest control receipts as well as recent dialogue. They are
    # current app facts even when the conversation has moved on for many turns.
    presented = {item.id for item in state.presented_effects}
    controls = {}
    for effect in state.issued_effects:
        if effect.id not in presented or effect.kind in {EffectKind.SUBTITLE, EffectKind.SPEECH}:
            continue
        channel = effect.kind.value
        if effect.kind is EffectKind.POSE:
            channel = next((prefix for prefix in ('outfit_', 'emotion_', 'accessory_', 'face_', 'gaze_')
                            if effect.value.startswith(prefix)),
                           'camera_pose' if effect.value in {'raise_camera', 'lower_camera'} else 'pose')
        controls[channel] = effect.id
    mandatory = set(controls.values())
    if len(mandatory) > max_effects:
        raise DomainError('effect_capacity', 'Current control evidence exceeds retained capacity.')
    recent = state.issued_effects[-max(1, max_effects - len(mandatory)):]
    keep = mandatory | {item.id for item in recent}
    effects = tuple(item for item in state.issued_effects if item.id in keep)
    keep = {effect.id for effect in effects}
    epochs = {effect.output_epoch for effect in effects}
    latest_audio = {}
    for fact in state.audio_progress:
        if fact.effect_id in keep:
            latest_audio[fact.effect_id] = fact
    return replace(state, user_inputs=state.user_inputs[omitted:],
        retired_user_inputs=state.retired_user_inputs + omitted,
        presentation_floor=cutoff, issued_effects=effects,
        receipts=tuple(item for item in state.receipts if item.effect_id in keep),
        audio_progress=tuple(sorted(latest_audio.values(), key=lambda item: item.presentation_seq)),
        fences=tuple(item for item in state.fences if item.output_epoch in epochs),
        # Reply history and image-job authority have different lifetimes. Keep
        # only the current live job (at most one); origin epoch is immutable.
        image_reservations=tuple(item for item in state.image_reservations
            if state.story_image.state in ('pending','generating','reviewing','qualified')
            and item.request_id == state.story_image.request_id
            and item.session_id == state.session_id
            and item.cancellation_generation == state.image_cancellation_generation))
