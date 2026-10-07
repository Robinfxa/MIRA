from dataclasses import asdict

from mira.application.diagnostic_errors import public_error_code
from mira.application.diagnostic_events import safe_diagnostic_id

from mira.domain.models import SessionState
from mira.entrypoints.http.schemas import AudioProgressView, EffectView, SessionView, StoryImageView, FixedPhotoView, ChapterProjectionView


def session_view(state: SessionState) -> SessionView:
    return SessionView(fixed_photo=FixedPhotoView(**asdict(state.fixed_photo)),story_image=StoryImageView(**asdict(state.story_image)),
        chapter_projection=(ChapterProjectionView(**asdict(state.chapter_projection))
                            if state.chapter_projection is not None else None),
        session_id=state.session_id, client_instance_id=state.client_instance_id,
        presentation_floor=getattr(state, "presentation_floor", 0),
        retired_user_inputs=getattr(state, "retired_user_inputs", 0),
        revision=state.revision, activity_seq=state.activity_seq, input_epoch=state.input_epoch,
        output_epoch=state.output_epoch, permit_revision=state.permit_revision,
        phase=state.phase, request_id=state.request_id, sealed=state.sealed,
        active_grants=[EffectView(**asdict(e)) for e in state.active_grants],
        presented_effects=[EffectView(**asdict(e)) for e in state.presented_effects],
        audio_progress=[AudioProgressView(**asdict(p)) for p in state.audio_progress],
        photo_visible=state.photo_visible, photo_visibility_revision=state.photo_visibility_revision,
        last_error=public_error_code(state.last_error) if state.last_error is not None else None,
        last_error_diagnostic_id=(safe_diagnostic_id(state.last_error_diagnostic_id)
                                  if state.last_error is not None else None),
        response_muted=state.response_muted, response_mode=state.response_mode,
        response_preference_revision=state.response_preference_revision,
    )
