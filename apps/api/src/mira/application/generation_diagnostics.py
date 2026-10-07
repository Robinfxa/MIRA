"""Closed, payload-free generation failure facts. No provider strings are accepted."""
from dataclasses import dataclass

GENERATION_PHASES = frozenset({
    'admission', 'prompt', 'request', 'credentials', 'response_headers', 'http_status',
    'auth', 'authorization', 'quota', 'redirect', 'transport', 'stream', 'sse',
    'terminal', 'provider', 'tool_forbidden', 'output_item', 'terminal_output',
    'incomplete_stream', 'incomplete_output', 'output_missing', 'output_multiple', 'validation',
})
GENERATION_REASONS = GENERATION_PHASES | frozenset({
    'service_tier_rejected', 'other', 'content_decode', 'content_encoding', 'utf8', 'json_shape',
    'content_type_missing', 'content_type_unsupported', 'content_type_parameters',
    'content_length_invalid', 'content_length_limit',
    'event_limit', 'wire_limit', 'decoded_limit', 'line_limit',
    'candidate_value_invalid', 'candidate_outer_shape', 'image_proposal_forbidden', 'media_effect_forbidden',
    'snapshot_output_shape', 'snapshot_item_shape', 'snapshot_message_count',
    'snapshot_text_mismatch', 'empty_snapshot_without_completed', 'message_type',
    'message_role', 'message_status', 'message_phase', 'message_content_shape',
    'message_part_shape', 'message_part_type', 'message_text_empty', 'message_total_limit',
    'reasoning_status', 'reasoning_encrypted_shape', 'reasoning_parts_shape',
    'reasoning_part_shape', 'unmatched_delta', 'candidate_missing', 'delta_done_text_mismatch',
    'message_phase_mismatch', 'late_delta_after_done', 'duplicate_output_item',
    'message_id_reused', 'snapshot_phase_mismatch',
    'codex_prompt_limit', 'codex_context_invalid', 'codex_capability_invalid',
    'codex_output_limit', 'codex_json_invalid', 'codex_effects_invalid', 'codex_effects_unsupported',
    'codex_character_proposal_invalid',
})
GENERATION_EVENTS = frozenset({
    'other', 'done_sentinel', 'response.created', 'response.in_progress', 'response.queued',
    'response.output_item.added', 'response.output_item.done', 'response.output_text.delta',
    'response.output_text.done', 'response.content_part.added', 'response.content_part.done',
    'response.completed', 'response.failed', 'response.incomplete', 'response.cancelled',
    'response.canceled', 'response.error', 'error', 'response.refusal.delta', 'response.refusal.done',
    'response.reasoning_summary_text.delta', 'response.reasoning_summary_text.done',
    'response.reasoning_text.delta', 'response.reasoning_text.done',
    'response.output_text.annotation.added',
})
GENERATION_STATUSES = frozenset({'none', 'completed', 'failed', 'error', 'incomplete',
                               'cancelled', 'canceled', 'in_progress', 'queued', 'other'})
GENERATION_ERROR_CODES = frozenset({
    'none', 'other', 'model_not_found', 'invalid_model', 'unsupported_model',
    'model_not_supported', 'invalid_request_error', 'invalid_api_key', 'token_expired',
    'rate_limit_exceeded', 'usage_limit_reached', 'insufficient_quota',
    'server_error', 'internal_error', 'overloaded', 'context_length_exceeded',
    'max_output_tokens', 'content_filter',
})
GENERATION_CONTENT_TYPES = frozenset({'unobserved', 'missing', 'text/event-stream',
    'application/json', 'text/html', 'text/plain', 'application/octet-stream', 'other'})
GENERATION_LENGTH_KINDS = frozenset({'unobserved', 'missing', 'valid', 'invalid', 'oversized',
    'duplicate_identical', 'duplicate_conflicting'})
GENERATION_HEADER_FAILURES = frozenset({'none', 'content_type_missing', 'content_type_unsupported',
    'content_type_parameters', 'content_length_invalid', 'content_length_limit'})
GENERATION_BODY_KINDS = frozenset({'not_read', 'empty', 'sse_like', 'html', 'json_error',
    'json_response', 'json_other', 'other', 'truncated', 'read_failed', 'decode_failed', 'read_timeout'})
GENERATION_ENCODINGS = frozenset({'unknown', 'identity', 'gzip', 'deflate', 'other'})
GENERATION_JSON_FAILURE_KINDS = frozenset({
    'syntax', 'duplicate_key', 'nonfinite', 'encoding', 'depth', 'type', 'unknown',
})
GENERATION_JSON_WRAPPER_SHAPES = frozenset({
    'bare_object', 'array', 'markdown_fence', 'plain_or_other',
})


REQUESTED_SERVICE_TIERS = frozenset({'unspecified', 'standard', 'fast'})
REQUEST_SERVICE_TIERS = frozenset({'omitted', 'default', 'priority'})
PROVIDER_SERVICE_TIERS = frozenset({
    'unobserved', 'absent', 'unknown', 'invalid', 'default', 'priority', 'fast', 'flex', 'scale', 'auto',
})


@dataclass(frozen=True, slots=True)
class SafeServiceTierDiagnostic:
    """One request's optional provider-reported tier, never inferred from the request."""
    requested_service_tier: str
    request_service_tier: str
    provider_service_tier: str
    outcome: str
    reason: str = 'other'
    fast_confirmed: bool = False

    def __post_init__(self):
        for value, allowed in (
                (self.requested_service_tier, REQUESTED_SERVICE_TIERS),
                (self.request_service_tier, REQUEST_SERVICE_TIERS),
                (self.provider_service_tier, PROVIDER_SERVICE_TIERS),
                (self.outcome, {'completed', 'failed', 'cancelled'}),
                (self.reason, GENERATION_REASONS)):
            if type(value) is not str or value not in allowed:
                raise ValueError('invalid service tier diagnostic class')
        object.__setattr__(self, 'fast_confirmed', self.outcome == 'completed'
            and self.provider_service_tier in {'priority', 'fast'})


@dataclass(frozen=True, slots=True)
class SafeGenerationDiagnostic:
    phase: str
    reason: str
    http_status: int | None = None
    content_encoding: str = 'unknown'
    event_types: tuple[str, ...] = ()
    event_count: int = 0
    terminal_status: str = 'none'
    provider_error_code: str = 'none'
    wire_bytes: int = 0
    decoded_bytes: int = 0
    content_type: str = 'unobserved'
    content_length_kind: str = 'unobserved'
    header_failure: str = 'none'
    body_kind: str = 'not_read'
    header_compatibility: str = 'none'
    snapshot_output_kind: str = 'unobserved'
    snapshot_item_count: int = 0
    snapshot_message_count: int = 0
    snapshot_reasoning_count: int = 0
    snapshot_item_types: tuple[str, ...] = ()
    snapshot_item_statuses: tuple[str, ...] = ()
    snapshot_message_phases: tuple[str, ...] = ()
    completed_message_count: int = 0
    completed_reasoning_count: int = 0
    delta_message_count: int = 0
    unmatched_delta_count: int = 0
    completed_text_bytes: int = 0
    snapshot_text_bytes: int = 0
    snapshot_matches_stream: bool | None = None
    terminal_compatibility: str = 'none'
    json_failure_kind: str | None = None
    wrapper_shape: str | None = None
    requested_service_tier: str = 'unspecified'
    request_service_tier: str = 'omitted'
    provider_service_tier: str = 'unobserved'

    def __post_init__(self):
        for value, allowed in ((self.json_failure_kind, GENERATION_JSON_FAILURE_KINDS),
                               (self.wrapper_shape, GENERATION_JSON_WRAPPER_SHAPES)):
            if value is not None and (type(value) is not str or value not in allowed):
                raise ValueError('invalid generation JSON diagnostic class')
        for value, allowed in ((self.requested_service_tier, REQUESTED_SERVICE_TIERS),
                (self.request_service_tier, REQUEST_SERVICE_TIERS),
                (self.provider_service_tier, PROVIDER_SERVICE_TIERS),
                (self.phase, GENERATION_PHASES), (self.reason, GENERATION_REASONS),
                (self.content_encoding, GENERATION_ENCODINGS),
                (self.terminal_status, GENERATION_STATUSES),
                (self.provider_error_code, GENERATION_ERROR_CODES),
                (self.content_type, GENERATION_CONTENT_TYPES),
                (self.content_length_kind, GENERATION_LENGTH_KINDS),
                (self.header_failure, GENERATION_HEADER_FAILURES),
                (self.body_kind, GENERATION_BODY_KINDS),
                (self.header_compatibility, frozenset({'none', 'subscription_missing_content_type'})),
                (self.snapshot_output_kind, frozenset({'unobserved','omitted','null','empty','list','other'})),
                (self.terminal_compatibility, frozenset({'none','subscription_empty_output'}))):
            if type(value) is not str or value not in allowed:
                raise ValueError('invalid generation diagnostic class')
        for values, allowed in (
                (self.snapshot_item_types, {'message','reasoning','tool','other'}),
                (self.snapshot_item_statuses, {'none','completed','in_progress','incomplete','other'}),
                (self.snapshot_message_phases, {'none','commentary','final_answer','other'})):
            if (type(values) is not tuple or len(values) > len(allowed)
                    or any(type(v) is not str or v not in allowed for v in values)
                    or len(set(values)) != len(values)):
                raise ValueError('invalid generation terminal shape')
        if self.snapshot_matches_stream is not None and type(self.snapshot_matches_stream) is not bool:
            raise ValueError('invalid generation terminal equality')
        if self.http_status is not None and (type(self.http_status) is not int
                                           or not 100 <= self.http_status <= 599):
            raise ValueError('invalid generation diagnostic status')
        if (type(self.event_types) is not tuple or len(self.event_types) > len(GENERATION_EVENTS)
                or any(type(v) is not str or v not in GENERATION_EVENTS for v in self.event_types)
                or len(set(self.event_types)) != len(self.event_types)):
            raise ValueError('invalid generation diagnostic events')
        for value, maximum in ((self.event_count, 4097), (self.wire_bytes, 4194305),
                               (self.decoded_bytes, 4194305),
                (self.snapshot_item_count,4097), (self.snapshot_message_count,4097),
                (self.snapshot_reasoning_count,4097), (self.completed_message_count,4097),
                (self.completed_reasoning_count,4097), (self.delta_message_count,4097),
                (self.unmatched_delta_count,4097), (self.completed_text_bytes,4194305),
                (self.snapshot_text_bytes,4194305)):
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError('invalid generation diagnostic count')


def generation_failure_diagnostic(error) -> SafeGenerationDiagnostic | None:
    """Unknown exceptions cannot inject arbitrary attributes into ordinary diagnostics."""
    try:
        value = getattr(error, 'generation_diagnostic', None)
        if type(value) is not SafeGenerationDiagnostic:
            return None
        value.__post_init__()
        return value
    except Exception:
        return None
