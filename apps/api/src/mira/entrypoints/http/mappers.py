from dataclasses import asdict

from mira.application.diagnostic_errors import public_error_code
from mira.application.diagnostic_events import safe_diagnostic_id

from mira.domain.models import SessionState
from mira.entrypoints.http.schemas import AudioProgressView, EffectView, SessionView


def session_view(state: SessionState) -> SessionView:
    return SessionView(
        session_id=state.session_id, client_instance_id=state.client_instance_id,
        revision=state.revision, activity_seq=state.activity_seq, input_epoch=state.input_epoch,
        output_epoch=state.output_epoch, permit_revision=state.permit_revision,
        phase=state.phase, request_id=state.request_id, sealed=state.sealed,
        active_grants=[EffectView(**asdict(e)) for e in state.active_grants],
        presented_effects=[EffectView(**asdict(e)) for e in state.presented_effects],
        audio_progress=[AudioProgressView(**asdict(p)) for p in state.audio_progress],
        last_error=public_error_code(state.last_error) if state.last_error is not None else None,
        last_error_diagnostic_id=(safe_diagnostic_id(state.last_error_diagnostic_id)
                                  if state.last_error is not None else None),
    )
