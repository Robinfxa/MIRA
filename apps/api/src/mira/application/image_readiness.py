"""Local image capability observations. No prompts, provider IO or admission authority."""
from dataclasses import asdict, dataclass, fields, replace

from mira.domain.story import valid_story_projection
from mira.application.image_operation_diagnostics import SafeImageOperationDiagnostic

_STATES = ('enabled', 'disabled', 'missing_consent', 'budget_exhausted', 'held', 'provider_error')
_REASONS = ('ready', 'runtime_disabled', 'custom_brief_consent', 'image_attempts',
    'image_bytes', 'image_cost', 'process_budget', 'process_busy', 'review_unavailable',
    'story_unavailable', 'task_limit', 'already_requested', 'photo_dismissed',
    'effect_limit', 'dialogue_budget', 'continuation', 'operation_failed', 'provider_error')
_PROVIDER_OBSERVATIONS = ('not_observed', 'generation_returned', 'review_returned',
                          'generation_error', 'review_error')


@dataclass(frozen=True, slots=True)
class SafeImageReadinessDiagnostic:
    phase: str
    state: str
    reason: str
    output_epoch: int = 0
    activity_seq: int = 0
    image_attempts: int = 0
    image_attempt_limit: int = 0
    process_remaining_jobs: int | None = None
    generation_tool: str = 'not_observed'
    fixed_photo_tool: str = 'not_observed'
    provider_observation: str = 'not_observed'
    operation_stage: str = 'unobserved'
    failure_reason: str = 'none'
    failure_exception: str = 'none'
    png_width: int | None = None
    png_height: int | None = None
    png_dimensions: str = 'unobserved'
    png_mode: str = 'unobserved'
    png_bit_depth: str = 'unobserved'
    png_alpha: str = 'unobserved'
    job_state: str = 'unobserved'
    job_event_reason: str = 'none'
    job_origin_epoch: int = 0
    job_origin_activity: int = 0
    completion_state: str = 'unavailable'

    def __post_init__(self):
        SafeImageOperationDiagnostic(**{field.name: getattr(self, field.name)
            for field in fields(SafeImageOperationDiagnostic)})
        for value, allowed in ((self.phase, ('definitions', 'request', 'continuation', 'operation')),
                (self.state, _STATES), (self.reason, _REASONS),
                (self.generation_tool, ('not_observed', 'advertised', 'absent')),
                (self.fixed_photo_tool, ('not_observed', 'advertised', 'absent')),
                (self.provider_observation, _PROVIDER_OBSERVATIONS),
                (self.job_state, ('unobserved','pending','generating','reviewing','qualified','presented','failed','cancelled','held')),
                (self.job_event_reason, ('none','ordinary_input','explicit_photo_cancel','stop_all','session_close','scope_changed','reply_interrupted')),
                (self.completion_state, ('unavailable','pending','context_consumed','requested','granted','presented','failed','cancelled'))):
            if type(value) is not str or value not in allowed:
                raise ValueError('invalid image readiness class')
        for value, maximum in ((self.job_origin_epoch,2**53-1),(self.job_origin_activity,2**53-1),(self.output_epoch, 2**53-1), (self.activity_seq, 2**53-1),
                (self.image_attempts, 4), (self.image_attempt_limit, 4)):
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError('invalid image readiness count')
        if self.process_remaining_jobs is not None and (type(self.process_remaining_jobs) is not int
                or not 0 <= self.process_remaining_jobs <= 4):
            raise ValueError('invalid image readiness process count')
        if self.generation_tool == 'advertised' and self.state != 'enabled':
            raise ValueError('invalid image readiness advertisement')


def runtime_image_readiness(runtime, *, output_epoch=0, activity_seq=0):
    value = SafeImageReadinessDiagnostic('definitions', 'disabled', 'runtime_disabled',
        output_epoch, activity_seq)
    if runtime is None:
        return value
    admission = runtime.admission
    value = replace(value, state='enabled', reason='ready', image_attempts=runtime.attempts,
        image_attempt_limit=admission.max_attempts,
        provider_observation=runtime.provider_observation,job_state=runtime.job_state,job_event_reason=runtime.job_event_reason,
        job_origin_epoch=runtime._diagnostic_context[0],job_origin_activity=runtime._diagnostic_context[1],completion_state=runtime.completion_state)
    operation = getattr(runtime, 'operation_diagnostic', None)
    # The producer binds this snapshot to its current diagnostic request ID.
    # A new reservation resets it; late writes from a different job are ignored.
    # Ordinary reply epochs must not erase a retained job's operation evidence.
    retained_job = (getattr(runtime, '_diagnostic_request_id', None) is not None
        and value.job_state in ('pending', 'generating', 'reviewing', 'qualified',
                                'presented', 'failed', 'held'))
    if (type(operation) is SafeImageOperationDiagnostic and (retained_job
            or getattr(runtime, '_diagnostic_context', None) == (output_epoch, activity_seq))):
        try:
            value = replace(value, **asdict(operation))
        except (ValueError, TypeError):
            pass
    # A gate may be supplied by another implementation without observation support.
    # Unknown counters are kept null, never fabricated as fresh capacity.
    gate = runtime.operation_readiness()
    if gate is not None:
        gate_state, remaining = gate
        value = replace(value, process_remaining_jobs=remaining)
        if gate_state == 'busy':
            return replace(value, state='held', reason='process_busy')
        if gate_state == 'budget_exhausted':
            return replace(value, state='budget_exhausted', reason='process_budget')
    if not admission.authorized_custom_brief:
        return replace(value, state='missing_consent', reason='custom_brief_consent')
    if runtime.attempts >= admission.max_attempts:
        return replace(value, state='budget_exhausted', reason='image_attempts')
    if runtime.reserved_bytes+runtime.used_bytes+admission.max_output_bytes > admission.max_total_bytes:
        return replace(value, state='budget_exhausted', reason='image_bytes')
    if runtime.cost_reserved+admission.cost_per_attempt_microunits > admission.max_cost_microunits:
        return replace(value, state='budget_exhausted', reason='image_cost')
    return value


def image_tool_readiness(context, state, runtime, *, review_available, image_task_count, max_effects):
    value = runtime_image_readiness(runtime, output_epoch=state.output_epoch, activity_seq=state.activity_seq)
    if value.state != 'enabled':
        return value
    for blocked, reason in (
            (state.story_image.state in ('generating','reviewing'),'process_busy'),
            (state.activity_seq <= state.image_dismissed_through_activity, 'photo_dismissed'),
            (len(state.issued_effects) >= max_effects, 'effect_limit'),
            (not review_available, 'review_unavailable'),
            (not valid_story_projection(context.character_story), 'story_unavailable'),
            (image_task_count+2 > 4, 'task_limit'),
            (any(r.parent_request_id == state.request_id for r in state.image_reservations), 'already_requested')):
        if blocked:
            return replace(value, state='held', reason=reason)
    return value


def advertised_image_readiness(value, names, *, continuation=False):
    """Final adapter tool names only; a model/user cannot supply this observation."""
    if (type(value) is not SafeImageReadinessDiagnostic or type(names) is not tuple
            or len(names) != len(set(names))
            or any(type(name) is not str or name not in ('show_photo', 'generate_story_image') for name in names)):
        raise ValueError('invalid image readiness advertisement')
    if continuation:
        value = replace(value, phase='continuation', state='held', reason='continuation')
    else:
        value = replace(value, phase='request')
        if value.state == 'enabled' and 'generate_story_image' not in names:
            value = replace(value, state='budget_exhausted', reason='dialogue_budget')
    return replace(value,
        generation_tool='advertised' if 'generate_story_image' in names else 'absent',
        fixed_photo_tool='advertised' if 'show_photo' in names else 'absent')
