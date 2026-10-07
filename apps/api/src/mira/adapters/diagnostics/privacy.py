"""Allowlist encoding plus defensive credential filtering, not a universal DLP claim."""
import base64
import json
import math
import re
import unicodedata
from dataclasses import asdict, dataclass, fields

from mira.application.generation_diagnostics import SafeGenerationDiagnostic
from mira.application.fixed_photo_diagnostics import SafeFixedPhotoDiagnostic
from mira.application.wardrobe_diagnostics import SafeWardrobeDiagnostic
from mira.application.optional_candidate_diagnostics import SafeOptionalCandidateDiagnostic
from mira.application.image_readiness import SafeImageReadinessDiagnostic
from mira.application.native_tool_diagnostics import SafeNativeToolDiagnostic

from mira.application.diagnostic_events import (
    CancellationReason,
    ContentReview,
    DiagnosticCode,
    DiagnosticContext,
    DiagnosticEvent,
    DiagnosticKind,
    DiagnosticOutcome,
    DiagnosticStage,
    RecordingKind,
    ReviewedRecording,
    correlation_hash,
)
from mira.application.contracts import (
    ReportedConfidenceWarning, ResponseChoice, ResponseValidationReason, ResponseWireType,
    SafeResponseAnswerFacts, SafeResponseValidation,
)
from mira.application.choice_wire_policy import (
    CHOICE_WIRE_POLICY_REPORTED_V2, SUPPORTED_CHOICE_WIRE_POLICIES,
)

_CONTEXT_KEYS = tuple(field.name for field in fields(DiagnosticContext))
_HASH = re.compile(r"h_[0-9a-f]{32}\Z")
_FORBIDDEN_ENVELOPE = re.compile(
    r'(?i)(?:authorization\s*[":=]|["\'](?:headers|private_key|client_secret|credentials|'
    r'access_token|refresh_token|id_token|password|api_key|x-api-key)["\']\s*:|'
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----)')
_SECRET_SHAPES = (
    re.compile(r"(?i)(?<![A-Za-z0-9_-])[_-]*(?:[A-Za-z][A-Za-z0-9_-]*[_-])?(?:api[_-]?key|password|passwd|private[_-]?key|access[_-]?token|refresh[_-]?token|"
               r"client[_-]?secret|secret|credentials|token)\s*(?:=|:|\bis\b)\s*"
               r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*')"),
    re.compile(r"(?i)\bBearer\s+[^\s,;\"']+"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b"),
    re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"(?i)(?<![A-Za-z0-9_-])[_-]*(?:[A-Za-z][A-Za-z0-9_-]*[_-])?(?:api[_-]?key|password|passwd|private[_-]?key|access[_-]?token|refresh[_-]?token|"
               r"client[_-]?secret|secret|credentials|token)\s*(?:=|:|\bis\b)\s*[^\s,;\"']+"),
    re.compile(r"(?i)https?://[^\s/@:]+:[^\s/@]+@[^\s]+"),
)


# Raw text is deliberately a small, conservative language, not arbitrary encoding/DLP.
_MAX_TEXT_BYTES = 128 * 1024
_MAX_DEPTH = 16
_MAX_NODES = 4096
_MAX_REVIEW_CHARS = 1024 * 1024
_CREDENTIAL_KEYS = frozenset((
    "authorization", "proxyauthorization", "headers", "requestheaders", "httpheaders",
    "privatekey", "clientsecret", "credentials", "accesstoken", "refreshtoken",
    "idtoken", "password", "passwd", "apikey", "xapikey", "secret", "token",
    "cookie", "setcookie",
))
_QUOTED_ASSIGNMENT = re.compile(r"[\"']([^\"'\\\r\n]{1,256})[\"']\s*[:=]")
_JSON_START = re.compile(r"[\[{]")
_NON_JSON_ESCAPE = re.compile(r'\\(?:["\\]|u[0-9a-fA-F]{4})')
_RESPONSE_VALIDATION_KEYS = tuple(field.name for field in fields(SafeResponseValidation))
_RESPONSE_ANSWER_KEYS = tuple(field.name for field in fields(SafeResponseAnswerFacts))
_RESPONSE_QUESTION_SUFFIX = re.compile(r"(?:o[1-6]|effect_[0-7]|event_[0-7]|event_scope|completed_claim_present|story_relevance|story_willingness|story_refusal|specific_notice|affect_supported)\Z")
_RESPONSE_NOUL_SUFFIXES = frozenset({"completed_claim_present", "story_relevance",
    "story_willingness", "story_refusal", "specific_notice"})


def _credential_key(value: str) -> bool:
    # JSON decoding handles Unicode escapes; NFKC covers compatibility-width keys.
    # This intentionally does not promise arbitrary homoglyph/encoded-key detection.
    normal = unicodedata.normalize("NFKC", value).casefold()
    compact = "".join(char for char in normal if char.isalnum())
    return (compact in _CREDENTIAL_KEYS or
            any(compact.endswith(key) for key in _CREDENTIAL_KEYS
                if key not in ("headers", "token", "secret", "cookie")) or
            any(part in _CREDENTIAL_KEYS for part in re.split(r"[_\s-]+", normal)))


@dataclass
class _ReviewBudget:
    nodes: int = 0
    chars: int = 0

    def spend(self, *, depth: int, chars: int = 0) -> None:
        self.nodes += 1
        self.chars += chars
        if depth > _MAX_DEPTH or self.nodes > _MAX_NODES or self.chars > _MAX_REVIEW_CHARS:
            raise ValueError("privacy review budget exceeded")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous JSON object")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("nonfinite JSON value")


_JSON = json.JSONDecoder(object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def _json_end(value: str, start: int, depth: int) -> int:
    """Bound structural depth before handing untrusted text to the JSON decoder."""
    quoted, escaped, stack = False, False, []
    for index in range(start, len(value)):
        char = value[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in "[{":
            stack.append(char)
            if depth + len(stack) > _MAX_DEPTH:
                raise ValueError("privacy review depth exceeded")
        elif char in "]}":
            if not stack or stack.pop() != ("[" if char == "]" else "{"):
                raise ValueError("malformed JSON structure")
            if not stack:
                return index + 1
    raise ValueError("incomplete JSON structure")


def context_dict(context: DiagnosticContext) -> dict:
    if type(context) is not DiagnosticContext:
        raise ValueError("invalid correlation")
    result = {}
    for key in _CONTEXT_KEYS:
        value = getattr(context, key)
        if value is not None:
            if type(value) is not str or not 1 <= len(value) <= 256:
                raise ValueError("invalid correlation")
            result[key] = correlation_hash(value)
    return result


def _number(value, *, minimum=0, maximum=86400000):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("invalid numeric field")
    return round(value, 3)


def _bounded_count(value, *, maximum: int, optional: bool = True):
    if value is None and optional:
        return None
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("invalid response diagnostic count")
    return value


def _bounded_range(value, *, maximum: float):
    if value is None:
        return None
    if type(value) is not tuple or len(value) != 2:
        raise ValueError("invalid response diagnostic range")
    lower = _optional_probability(value[0], maximum=maximum)
    upper = _optional_probability(value[1], maximum=maximum)
    if lower is None or upper is None or lower > upper:
        raise ValueError("invalid response diagnostic range")
    return [lower, upper]


def _optional_probability(value, *, maximum: float = 1.0):
    if value is None:
        return None
    if type(value) is int:
        if not 0 <= value <= maximum:
            raise ValueError("invalid response diagnostic probability")
        return float(value)
    if (type(value) is not float or not math.isfinite(value)
            or not 0 <= value <= maximum):
        raise ValueError("invalid response diagnostic probability")
    return value


def _encode_response_answer_facts(value: SafeResponseAnswerFacts) -> dict:
    if type(value) is not SafeResponseAnswerFacts:
        raise ValueError("invalid response answer diagnostics")
    suffix = value.question_suffix
    if type(suffix) is not str or not _RESPONSE_QUESTION_SUFFIX.fullmatch(suffix):
        raise ValueError("invalid response question suffix")
    try:
        wire_type = ResponseWireType(value.answer_wire_type).value
        reason = (ResponseValidationReason(value.answer_reason).value
                  if value.answer_reason is not None else None)
        choice = ResponseChoice(value.choice).value if value.choice is not None else None
    except (TypeError, ValueError):
        raise ValueError("invalid response answer diagnostics") from None
    is_noul = suffix in _RESPONSE_NOUL_SUFFIXES
    if (type(value.expected_probability_count) is not int
            or value.expected_probability_count != (0 if is_noul else 3)):
        raise ValueError("invalid response answer diagnostics")
    if (value.selected_is_maximum is not None and type(value.selected_is_maximum) is not bool
            or value.confidence_consistent is not None and type(value.confidence_consistent) is not bool
            or value.confidence_mismatch_warning is not None
            and type(value.confidence_mismatch_warning) is not bool):
        raise ValueError("invalid response answer diagnostics")
    if (is_noul and (value.choice is not None
                     or value.probability_field_count is not None
                     or value.confidence is not None or value.selected_probability is not None
                     or value.maximum_probability is not None or value.probability_sum is not None
                     or value.selected_is_maximum is not None
                     or value.confidence_consistent is not None
                     or value.confidence_mismatch_warning is not None)):
        raise ValueError("invalid response answer diagnostics")
    if not is_noul and value.noul_probability is not None:
        raise ValueError("invalid response answer diagnostics")
    result = {
        "question_suffix": suffix,
        "answer_wire_type": wire_type,
        "answer_reason": reason,
        "choice": choice,
        "answer_field_count": _bounded_count(value.answer_field_count, maximum=64),
        "unexpected_answer_field_count": _bounded_count(
            value.unexpected_answer_field_count, maximum=64),
        "expected_probability_count": value.expected_probability_count,
        "probability_field_count": _bounded_count(value.probability_field_count, maximum=64),
        "unexpected_probability_field_count": _bounded_count(
            value.unexpected_probability_field_count, maximum=64),
        "valid_probability_count": _bounded_count(value.valid_probability_count, maximum=3,
                                                    optional=False),
        "confidence": _optional_probability(value.confidence),
        "selected_probability": _optional_probability(value.selected_probability),
        "maximum_probability": _optional_probability(value.maximum_probability),
        "probability_sum": _optional_probability(value.probability_sum, maximum=3),
        "selected_is_maximum": value.selected_is_maximum,
        "confidence_consistent": value.confidence_consistent,
    }
    if is_noul:
        result["noul_probability"] = _optional_probability(value.noul_probability)
    if value.confidence_mismatch_warning is not None:
        result["confidence_mismatch_warning"] = value.confidence_mismatch_warning
    return result


def _encode_response_validation(value: SafeResponseValidation) -> dict:
    if type(value) is not SafeResponseValidation:
        raise ValueError("invalid response diagnostics")
    try:
        reason = ResponseValidationReason(value.parser_reason).value
        wire_type = ResponseWireType(value.response_wire_type).value
    except (TypeError, ValueError):
        raise ValueError("invalid response diagnostics") from None
    response_bytes = _bounded_count(value.response_bytes, maximum=64 * 1024 + 1)
    expected = _bounded_count(value.expected_answer_count, maximum=20)
    answer_count = _bounded_count(value.answer_count, maximum=64)
    missing = _bounded_count(value.missing_answer_count, maximum=20)
    unexpected = _bounded_count(value.unexpected_answer_count, maximum=64)
    invalid = _bounded_count(value.invalid_answer_count, maximum=20)
    invalid_probabilities = _bounded_count(value.invalid_probability_count, maximum=20)
    nonfinite = _bounded_count(value.nonfinite_numeric_count, maximum=64)
    oversized = _bounded_count(value.oversized_integer_count, maximum=64)
    digest = value.response_sha256
    if digest is not None and (type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError("invalid response diagnostics")
    if type(value.answer_facts) is not tuple or len(value.answer_facts) > 20:
        raise ValueError("invalid response answer diagnostics")
    answer_facts = [_encode_response_answer_facts(item) for item in value.answer_facts]
    suffixes = [item["question_suffix"] for item in answer_facts]
    if len(suffixes) != len(set(suffixes)):
        raise ValueError("duplicate response question suffix")
    if expected is not None and len(answer_facts) != expected:
        raise ValueError("response answer diagnostic count mismatch")
    result = {
        "parser_reason": reason, "response_wire_type": wire_type,
        "response_bytes": response_bytes, "response_sha256": digest,
        "expected_answer_count": expected, "answer_count": answer_count,
        "missing_answer_count": missing, "unexpected_answer_count": unexpected,
        "invalid_answer_count": invalid, "invalid_probability_count": invalid_probabilities,
        "nonfinite_numeric_count": nonfinite, "oversized_integer_count": oversized,
        "selected_probability_range": _bounded_range(value.selected_probability_range, maximum=1),
        "confidence_range": _bounded_range(value.confidence_range, maximum=1),
        "probability_sum_range": _bounded_range(value.probability_sum_range, maximum=3),
        "answer_facts": answer_facts,
    }
    if value.choice_wire_policy_version is not None:
        if value.choice_wire_policy_version not in SUPPORTED_CHOICE_WIRE_POLICIES:
            raise ValueError("invalid response choice wire policy")
        if (value.choice_wire_policy_version == CHOICE_WIRE_POLICY_REPORTED_V2
                and any(("confidence_mismatch_warning" in item)
                         if item["question_suffix"] in _RESPONSE_NOUL_SUFFIXES else
                         item.get("confidence_mismatch_warning") not in (True, False)
                        for item in answer_facts)):
            raise ValueError("invalid reported-confidence warning facts")
        result["choice_wire_policy_version"] = value.choice_wire_policy_version
    return result


def _encode_reported_confidence_warning(value: ReportedConfidenceWarning) -> dict:
    if (type(value) is not ReportedConfidenceWarning
            or value.choice_wire_policy_version != CHOICE_WIRE_POLICY_REPORTED_V2):
        raise ValueError("invalid reported-confidence warning")
    maximum = _optional_probability(value.maximum_probability)
    confidence = _optional_probability(value.confidence)
    probability_sum = _optional_probability(value.probability_sum, maximum=3)
    if maximum is None or confidence is None or probability_sum is None:
        raise ValueError("invalid reported-confidence warning")
    return {"choice_wire_policy_version": CHOICE_WIRE_POLICY_REPORTED_V2,
            "maximum_probability": maximum, "confidence": confidence,
            "probability_sum": probability_sum}


def _reported_confidence_warning_from_record(value) -> ReportedConfidenceWarning:
    if type(value) is not dict or set(value) != {
            "choice_wire_policy_version", "maximum_probability", "confidence", "probability_sum"}:
        raise ValueError("invalid reported-confidence warning")
    try:
        warning = ReportedConfidenceWarning(**value)
    except (TypeError, ValueError):
        raise ValueError("invalid reported-confidence warning") from None
    _encode_reported_confidence_warning(warning)
    return warning


def _response_answer_facts_from_record(value) -> tuple[SafeResponseAnswerFacts, ...]:
    if type(value) is not list or len(value) > 20:
        raise ValueError("invalid response answer diagnostics")
    result = []
    for item in value:
        legacy_keys = set(_RESPONSE_ANSWER_KEYS) - {"noul_probability", "confidence_mismatch_warning"}
        no_warning_keys = set(_RESPONSE_ANSWER_KEYS) - {"confidence_mismatch_warning"}
        choice_warning_keys = set(_RESPONSE_ANSWER_KEYS) - {"noul_probability"}
        if type(item) is not dict or set(item) not in (
                set(_RESPONSE_ANSWER_KEYS), legacy_keys, no_warning_keys, choice_warning_keys):
            raise ValueError("invalid response answer diagnostics")
        converted = dict(item)
        try:
            converted["answer_wire_type"] = ResponseWireType(converted["answer_wire_type"])
            if converted["answer_reason"] is not None:
                converted["answer_reason"] = ResponseValidationReason(converted["answer_reason"])
            if converted["choice"] is not None:
                converted["choice"] = ResponseChoice(converted["choice"])
            answer = SafeResponseAnswerFacts(**converted)
        except (TypeError, ValueError):
            raise ValueError("invalid response answer diagnostics") from None
        _encode_response_answer_facts(answer)
        result.append(answer)
    suffixes = [item.question_suffix for item in result]
    if len(suffixes) != len(set(suffixes)):
        raise ValueError("duplicate response question suffix")
    return tuple(result)


def _response_validation_from_record(value) -> SafeResponseValidation:
    legacy_keys = set(_RESPONSE_VALIDATION_KEYS) - {"choice_wire_policy_version"}
    if type(value) is not dict or set(value) not in (set(_RESPONSE_VALIDATION_KEYS), legacy_keys):
        raise ValueError("invalid response diagnostics")
    converted = dict(value)
    for key in ("selected_probability_range", "confidence_range", "probability_sum_range"):
        item = converted[key]
        if item is not None:
            if type(item) is not list or len(item) != 2:
                raise ValueError("invalid response diagnostic range")
            # Serializer checks bounds, exact numeric types and finiteness.
            converted[key] = tuple(item)
    converted["answer_facts"] = _response_answer_facts_from_record(converted["answer_facts"])
    try:
        checked = SafeResponseValidation(**converted)
    except (TypeError, ValueError):
        raise ValueError("invalid response diagnostics") from None
    _encode_response_validation(checked)
    return checked


def encode_event(event: DiagnosticEvent, now: float) -> dict:
    if type(event) is not DiagnosticEvent:
        raise ValueError("invalid event")
    result = {"schema": 1, "record_type": "event", "timestamp": _number(now, maximum=1e12),
              "stage": DiagnosticStage(event.stage).value,
              "kind": DiagnosticKind(event.kind).value,
              "outcome": DiagnosticOutcome(event.outcome).value,
              "context": context_dict(event.context)}
    if event.code is not None:
        result["code"] = DiagnosticCode(event.code).value
    if event.cancellation_reason is not None:
        if event.outcome != DiagnosticOutcome.CANCELLED:
            raise ValueError("cancellation reason requires cancelled outcome")
        result["cancellation_reason"] = CancellationReason(event.cancellation_reason).value
    if event.duration_ms is not None:
        result["duration_ms"] = _number(event.duration_ms)
    if event.http_status is not None:
        if type(event.http_status) is not int or not 100 <= event.http_status <= 599:
            raise ValueError("invalid status")
        result["http_status"] = event.http_status
    if event.native_tool is not None:
        if type(event.native_tool) is not SafeNativeToolDiagnostic or event.stage != DiagnosticStage.NATIVE_TOOL:
            raise ValueError('invalid native tool diagnostic')
        event.native_tool.__post_init__()
        result['native_tool'] = asdict(event.native_tool)
    if event.image_readiness is not None:
        if (type(event.image_readiness) is not SafeImageReadinessDiagnostic
                or event.stage != DiagnosticStage.IMAGE_READINESS):
            raise ValueError('invalid image readiness diagnostic')
        event.image_readiness.__post_init__()
        result['image_readiness'] = asdict(event.image_readiness)
    if event.wardrobe is not None:
        if type(event.wardrobe) is not SafeWardrobeDiagnostic or event.stage != DiagnosticStage.WARDROBE:
            raise ValueError('invalid wardrobe diagnostic')
        event.wardrobe.__post_init__()
        result['wardrobe'] = asdict(event.wardrobe)
    if event.optional_candidate_hold is not None:
        value = event.optional_candidate_hold
        if (type(value) is not SafeOptionalCandidateDiagnostic
                or event.stage != DiagnosticStage.GENERATION
                or event.kind != DiagnosticKind.STATE_CHANGED or event.outcome != DiagnosticOutcome.DROPPED):
            raise ValueError('invalid optional candidate diagnostic')
        value.__post_init__()
        result['optional_candidate_hold'] = {**asdict(value), 'reasons': list(value.reasons)}
    if event.fixed_photo is not None:
        if type(event.fixed_photo) is not SafeFixedPhotoDiagnostic or event.stage != DiagnosticStage.FIXED_PHOTO:
            raise ValueError('invalid fixed photo diagnostic')
        event.fixed_photo.__post_init__()
        result['fixed_photo'] = asdict(event.fixed_photo)
    if event.generation_diagnostic is not None:
        value = event.generation_diagnostic
        if (type(value) is not SafeGenerationDiagnostic or event.stage != DiagnosticStage.GENERATION
                or event.outcome != DiagnosticOutcome.FAILED):
            raise ValueError('invalid generation diagnostics')
        value.__post_init__()
        result['generation_diagnostic'] = asdict(value)
        for key in ('event_types','snapshot_item_types','snapshot_item_statuses','snapshot_message_phases'):
            result['generation_diagnostic'][key] = list(getattr(value,key))
    if event.response_validation is not None:
        result["response_validation"] = _encode_response_validation(event.response_validation)
    if event.reported_confidence_warning is not None:
        if (DiagnosticStage(event.stage) != DiagnosticStage.INPUT_REVIEW
                or DiagnosticOutcome(event.outcome) not in
                (DiagnosticOutcome.SUCCEEDED, DiagnosticOutcome.FAILED)):
            raise ValueError("reported-confidence warning requires input review event")
        result["reported_confidence_warning"] = _encode_reported_confidence_warning(
            event.reported_confidence_warning)
    return result


def validate_event_record(record: dict) -> dict:
    required = {"schema", "record_type", "timestamp", "stage", "kind", "outcome", "context"}
    optional = {"code", "cancellation_reason", "duration_ms", "http_status",
                "response_validation", "reported_confidence_warning", "generation_diagnostic", "fixed_photo", "wardrobe",
                "optional_candidate_hold", "image_readiness", "native_tool"}
    if (type(record) is not dict or not required <= record.keys()
            or record.keys() - required - optional or type(record["schema"]) is not int
            or record["schema"] != 1 or record["record_type"] != "event"):
        raise ValueError("invalid event schema")
    context = record["context"]
    if (type(context) is not dict or context.keys() - set(_CONTEXT_KEYS)
            or any(type(value) is not str or not _HASH.fullmatch(value) for value in context.values())):
        raise ValueError("invalid correlation")
    native_tool = None
    if 'native_tool' in record:
        value = record['native_tool']
        if type(value) is not dict or set(value) != {f.name for f in fields(SafeNativeToolDiagnostic)}:
            raise ValueError('invalid native tool diagnostic')
        native_tool = SafeNativeToolDiagnostic(**value)
    image_readiness = None
    if 'image_readiness' in record:
        value = record['image_readiness']
        current_fields = {f.name for f in fields(SafeImageReadinessDiagnostic)}
        operation_fields = {'operation_stage', 'failure_reason', 'failure_exception',
            'png_width', 'png_height', 'png_dimensions', 'png_mode', 'png_bit_depth', 'png_alpha'}
        job_fields={'job_state','job_event_reason','job_origin_epoch','job_origin_activity','completion_state'}
        if type(value) is not dict or set(value) not in (current_fields,current_fields-operation_fields,
                current_fields-job_fields,current_fields-operation_fields-job_fields):
            raise ValueError('invalid image readiness diagnostic')
        image_readiness = SafeImageReadinessDiagnostic(**value)
    wardrobe = None
    optional_candidate_hold = None
    if 'optional_candidate_hold' in record:
        value = record['optional_candidate_hold']
        if (type(value) is not dict or set(value) != {f.name for f in fields(SafeOptionalCandidateDiagnostic)}
                or type(value.get('reasons')) is not list):
            raise ValueError('invalid optional candidate diagnostic')
        optional_candidate_hold = SafeOptionalCandidateDiagnostic(**{**value, 'reasons': tuple(value['reasons'])})
    if 'wardrobe' in record:
        value = record['wardrobe']
        if type(value) is not dict or set(value) != {f.name for f in fields(SafeWardrobeDiagnostic)}:
            raise ValueError('invalid wardrobe diagnostic')
        wardrobe = SafeWardrobeDiagnostic(**value)
    fixed_photo = None
    if 'fixed_photo' in record:
        value = record['fixed_photo']
        if type(value) is not dict or set(value) != {f.name for f in fields(SafeFixedPhotoDiagnostic)}:
            raise ValueError('invalid fixed photo diagnostic')
        fixed_photo = SafeFixedPhotoDiagnostic(**value)
    generation_diagnostic = None
    if 'generation_diagnostic' in record:
        value = record['generation_diagnostic']
        allowed = {f.name for f in fields(SafeGenerationDiagnostic)}
        required = allowed - {'content_type', 'content_length_kind', 'header_failure', 'body_kind',
                              'header_compatibility', 'snapshot_output_kind', 'snapshot_item_count',
                              'snapshot_message_count', 'snapshot_reasoning_count', 'snapshot_item_types',
                              'snapshot_item_statuses', 'snapshot_message_phases', 'completed_message_count',
                              'completed_reasoning_count', 'delta_message_count', 'unmatched_delta_count',
                              'completed_text_bytes', 'snapshot_text_bytes', 'snapshot_matches_stream',
                              'terminal_compatibility', 'json_failure_kind', 'wrapper_shape',
                              'requested_service_tier', 'request_service_tier', 'provider_service_tier'}
        if (type(value) is not dict or not required <= value.keys() or value.keys() - allowed
                or type(value.get('event_types')) is not list):
            raise ValueError('invalid generation diagnostics')
        converted = dict(value)
        for key in ('event_types','snapshot_item_types','snapshot_item_statuses','snapshot_message_phases'):
            if key in converted:
                if type(converted[key]) is not list:
                    raise ValueError('invalid generation terminal shape')
                converted[key] = tuple(converted[key])
        generation_diagnostic = SafeGenerationDiagnostic(**converted)
    response_validation = (_response_validation_from_record(record["response_validation"])
                           if "response_validation" in record else None)
    reported_confidence_warning = (
        _reported_confidence_warning_from_record(record["reported_confidence_warning"])
        if "reported_confidence_warning" in record else None)
    event = DiagnosticEvent(stage=record["stage"], kind=record["kind"], outcome=record["outcome"],
        code=record.get("code"), cancellation_reason=record.get("cancellation_reason"),
        duration_ms=record.get("duration_ms"), http_status=record.get("http_status"),
        response_validation=response_validation,
        generation_diagnostic=generation_diagnostic, fixed_photo=fixed_photo, wardrobe=wardrobe,
        image_readiness=image_readiness, native_tool=native_tool,
        optional_candidate_hold=optional_candidate_hold,
        reported_confidence_warning=reported_confidence_warning)
    checked = encode_event(event, record["timestamp"])
    checked["context"] = dict(context)
    return checked


class PrivacyFilter:
    """Trusted injection of active secrets; repr never exposes them.

    Pattern checks are a second defense. Exact-record privacy review is still
    mandatory, especially for audio and unknown credential formats.
    """
    def __init__(self, secrets=()):
        self._secrets: tuple[str, ...] = ()
        for value in secrets:
            self.add_secret(value)

    def add_secret(self, value: str) -> None:
        if type(value) is not str or not value or len(value) > 8192:
            raise ValueError("invalid trusted secret")
        if value in self._secrets:
            return
        if len(self._secrets) >= 4096:
            raise ValueError("trusted secret budget reached")
        self._secrets += (value,)

    def text(self, value: str) -> str:
        if (type(value) is not str or len(value) > _MAX_TEXT_BYTES
                or len(value.encode()) > _MAX_TEXT_BYTES):
            raise ValueError("invalid text buffer")
        result = self._text(value, _ReviewBudget(), 0)
        if len(result) > _MAX_TEXT_BYTES or len(result.encode()) > _MAX_TEXT_BYTES:
            raise ValueError("filtered text exceeds budget")
        return result

    def _plain(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value)
        if (_FORBIDDEN_ENVELOPE.search(normalized) or any(
                _credential_key(match.group(1)) for match in _QUOTED_ASSIGNMENT.finditer(normalized))):
            raise ValueError("credential envelope is ineligible")
        for secret in sorted(self._secrets, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        for pattern in _SECRET_SHAPES:
            value = pattern.sub("[REDACTED]", value)
        # Escaped syntax outside valid JSON is uncertain, never guessed/decoded.
        if _NON_JSON_ESCAPE.search(value):
            raise ValueError("ambiguous non-JSON escape")
        return value

    def _walk(self, value, budget: _ReviewBudget, depth: int):
        budget.spend(depth=depth)
        if type(value) is str:
            return self._text(value, budget, depth + 1)
        if type(value) is list:
            return [self._walk(item, budget, depth + 1) for item in value]
        if type(value) is dict:
            result = {}
            for key, item in value.items():
                budget.spend(depth=depth + 1, chars=len(key))
                if _credential_key(key):
                    raise ValueError("credential envelope is ineligible")
                safe_key = self._text(key, budget, depth + 1)
                if safe_key in result:
                    raise ValueError("ambiguous filtered JSON object")
                result[safe_key] = self._walk(item, budget, depth + 1)
            return result
        if value is None or type(value) in (bool, int):
            return value
        if type(value) is float and math.isfinite(value):
            return value
        raise ValueError("invalid JSON value")

    def _text(self, value: str, budget: _ReviewBudget, depth: int) -> str:
        budget.spend(depth=depth, chars=len(value))
        stripped = value.lstrip()
        if stripped and stripped[0] in '{["' and not stripped.startswith("[REDACTED]"):
            if stripped[0] in "{[":
                _json_end(stripped, 0, depth)
            parsed, end = _JSON.raw_decode(stripped)
            if stripped[end:].strip():
                raise ValueError("ambiguous JSON suffix")
            checked = self._walk(parsed, budget, depth + 1)
            return (value if checked == parsed else
                    json.dumps(checked, ensure_ascii=False, allow_nan=False))
        value = self._plain(value)
        # A JSON envelope embedded in prose still receives the same review. Invalid
        # bracket/brace fragments are dropped conservatively rather than decoded.
        pieces, cursor = [], 0
        while cursor < len(value):
            match = _JSON_START.search(value, cursor)
            if match is None:
                break
            start = match.start()
            pieces.append(value[cursor:start])
            if value.startswith("[REDACTED]", start):
                pieces.append("[REDACTED]")
                cursor = start + len("[REDACTED]")
                continue
            end = _json_end(value, start, depth)
            parsed, decoded_end = _JSON.raw_decode(value, start)
            if end != decoded_end:
                raise ValueError("ambiguous JSON fragment")
            checked = self._walk(parsed, budget, depth + 1)
            pieces.append(value[start:end] if checked == parsed else
                          json.dumps(checked, ensure_ascii=False, allow_nan=False))
            cursor = end
        pieces.append(value[cursor:])
        return "".join(pieces)

    def recording(self, record: ReviewedRecording, *, now: float,
                  max_text_bytes: int, max_audio_bytes: int) -> dict:
        if (type(record) is not ReviewedRecording
                or record.review not in (ContentReview.APPROVED, ContentReview.REDACTED)):
            raise ValueError("privacy review required")
        kind = RecordingKind(record.kind)
        result = {"schema": 1, "record_type": "reviewed_raw",
                  "timestamp": _number(now, maximum=1e12), "kind": kind.value,
                  "privacy_review": ContentReview(record.review).value,
                  "context": context_dict(record.context)}
        if kind in (RecordingKind.DIALOGUE, RecordingKind.MODEL_INPUT, RecordingKind.MODEL_OUTPUT):
            if (type(record.text) is not str or record.audio is not None
                    or record.sample_rate_hz is not None
                    or len(record.text) > max_text_bytes
                    or len(record.text.encode()) > max_text_bytes):
                raise ValueError("invalid text buffer")
            result["text"] = self.text(record.text)
            if result["text"] != record.text:
                result["privacy_review"] = ContentReview.REDACTED.value
        else:
            if (type(record.audio) is not bytes or record.text is not None
                    or not record.audio or len(record.audio) % 2
                    or len(record.audio) > max_audio_bytes
                    or type(record.sample_rate_hz) is not int
                    or record.sample_rate_hz not in (16000, 24000, 48000)):
                raise ValueError("invalid audio buffer")
            # A known credential embedded as bytes is also forbidden. This is not
            # spoken-secret detection; approval must cover listening/privacy review.
            if any(secret.encode() in record.audio for secret in self._secrets):
                raise ValueError("credential bytes")
            ascii_view = record.audio.decode("ascii", errors="ignore")
            if _FORBIDDEN_ENVELOPE.search(ascii_view) or any(
                    pattern.search(ascii_view) for pattern in _SECRET_SHAPES):
                raise ValueError("credential bytes")
            result["audio_base64"] = base64.b64encode(record.audio).decode("ascii")
            result["sample_rate_hz"] = record.sample_rate_hz
        return result


def validate_raw_record(record: dict) -> dict:
    required = {"schema", "record_type", "timestamp", "kind", "privacy_review", "context"}
    if (type(record) is not dict or not required <= record.keys()
            or record.keys() - required - {"text", "audio_base64", "sample_rate_hz"}
            or type(record["schema"]) is not int or record["schema"] != 1
            or record["record_type"] != "reviewed_raw"):
        raise ValueError("invalid recording schema")
    context = record["context"]
    if (type(context) is not dict or context.keys() - set(_CONTEXT_KEYS)
            or any(type(value) is not str or not _HASH.fullmatch(value) for value in context.values())):
        raise ValueError("invalid correlation")
    audio = None
    if "audio_base64" in record:
        audio = base64.b64decode(record["audio_base64"], validate=True)
    checked = PrivacyFilter().recording(ReviewedRecording(kind=record["kind"],
        review=record["privacy_review"], text=record.get("text"), audio=audio,
        sample_rate_hz=record.get("sample_rate_hz")), now=record["timestamp"],
        max_text_bytes=128 * 1024, max_audio_bytes=512 * 1024)
    checked["context"] = dict(context)
    return checked
