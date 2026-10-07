"""Pure, bounded JEV response summaries for the existing local diagnostics sink."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping

from mira.application.choice_confidence import (
    choice_confidence_consistent,
    choice_probability_sum_compatible,
)
from mira.application.choice_wire_policy import (
    CHOICE_WIRE_POLICY_LEGACY_STRICT, CHOICE_WIRE_POLICY_REPORTED_V2,
    is_supported_choice_wire_policy,
)
from mira.application.contracts import (
    ResponseChoice, ResponseValidationReason, ResponseWireType,
    SafeResponseAnswerFacts, SafeResponseValidation,
)

_MAX_DIAGNOSTIC_ANSWERS = 64
_CHOICES = frozenset(("allow", "reject", "unknown"))
_PARSER_REASONS = {reason.value: reason for reason in ResponseValidationReason}


class _NonfiniteNumber:
    __slots__ = ()


class _OversizedInteger:
    __slots__ = ()


class _DuplicateKey(ValueError):
    __slots__ = ()


_NONFINITE = _NonfiniteNumber()
_OVERSIZED = _OversizedInteger()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey()
        result[key] = value
    return result


def _parse_integer(token: str):
    digits = token.lstrip("-")
    if len(digits) > 18:
        return _OVERSIZED
    return int(token)


def _parse_float(token: str):
    try:
        value = float(token)
    except (ValueError, OverflowError):
        return _NONFINITE
    return value if math.isfinite(value) else _NONFINITE


def _wire_type(value: object) -> ResponseWireType:
    if value is _MISSING:
        return ResponseWireType.MISSING
    if value is None:
        return ResponseWireType.NULL
    if type(value) is bool:
        return ResponseWireType.BOOLEAN
    if type(value) in (int, float) or value in (_NONFINITE, _OVERSIZED):
        return ResponseWireType.NUMBER
    if type(value) is str:
        return ResponseWireType.STRING
    if type(value) is dict:
        return ResponseWireType.OBJECT
    if type(value) is list:
        return ResponseWireType.ARRAY
    return ResponseWireType.OTHER


class _Missing:
    __slots__ = ()


_MISSING = _Missing()


def _parser_reason(error: BaseException) -> ResponseValidationReason:
    if type(error) is UnicodeDecodeError:
        return ResponseValidationReason.INVALID_UTF8
    if type(error) is json.JSONDecodeError:
        return ResponseValidationReason.JSON_DECODE
    if type(error) is OverflowError:
        return ResponseValidationReason.NUMERIC_OVERFLOW
    try:
        args = error.args
        if type(error) is ValueError and len(args) == 1 and type(args[0]) is str:
            return _PARSER_REASONS.get(args[0], ResponseValidationReason.UNKNOWN)
    except Exception:
        pass
    return ResponseValidationReason.UNKNOWN


def _bounded_probability(value: object) -> float | None:
    if type(value) is int:
        return float(value) if value in (0, 1) else None
    if type(value) is float and math.isfinite(value) and 0 <= value <= 1:
        return value
    return None


def _bounded_count(value: int, maximum: int = _MAX_DIAGNOSTIC_ANSWERS) -> int:
    return min(max(value, 0), maximum)


def _range(values: list[float], *, maximum: float = 1.0) -> tuple[float, float] | None:
    if not values:
        return None
    low, high = min(values), max(values)
    if not (math.isfinite(low) and math.isfinite(high) and 0 <= low <= high <= maximum):
        return None
    return float(low), float(high)


def _minimal_summary(body: bytes, maximum_response_bytes: int,
                     expected_count: int, reason: ResponseValidationReason,
                     wire_type: ResponseWireType = ResponseWireType.OTHER) -> SafeResponseValidation:
    bounded_length = min(len(body), maximum_response_bytes + 1)
    digest = hashlib.sha256(body).hexdigest() if len(body) <= maximum_response_bytes else None
    return SafeResponseValidation(reason, wire_type, bounded_length, digest,
        expected_count, None, None, None, None, None, None, None)


def summarize_response_validation(body: bytes, expected_questions: Mapping,
                                  error: BaseException, *,
                                  maximum_response_bytes: int,
                                  choice_wire_policy_version: str = CHOICE_WIRE_POLICY_LEGACY_STRICT
                                  ) -> SafeResponseValidation:
    """Return only fixed enums, bounded counts, finite values, and an optional hash.

    Expected question identifiers are inspected only to count known output dimensions.
    Their nonce/digest prefix is never returned. The response parser here is diagnostic
    only and cannot affect the canonical JEV parser or decision.
    """
    if type(body) is not bytes or type(maximum_response_bytes) is not int or maximum_response_bytes < 0:
        raise ValueError("invalid diagnostic input")
    if not is_supported_choice_wire_policy(choice_wire_policy_version):
        raise ValueError("invalid choice wire policy")
    expected = ()
    expected_noul = ()
    if type(expected_questions) is dict:
        expected = tuple(key for key, question in expected_questions.items()
            if type(key) is str and type(question) is dict and question.get("type") == "choice"
            and key.rsplit(":", 1)[-1] in {
                *(f"o{index}" for index in range(1, 7)),
                *(f"effect_{index}" for index in range(8)),
                *(f"event_{index}" for index in range(8)),
                "affect_supported", "event_scope",
            })
        expected_noul = tuple(key for key, question in expected_questions.items()
            if type(key) is str and type(question) is dict and question.get("type") == "noul"
            and key.rsplit(":", 1)[-1] in {"completed_claim_present", "story_relevance",
                "story_willingness", "story_refusal", "specific_notice"})
    expected_count = min(len(expected), 15) + min(len(expected_noul), 5)
    reason = _parser_reason(error)
    if len(body) > maximum_response_bytes:
        return _minimal_summary(body, maximum_response_bytes, expected_count, reason)
    digest = hashlib.sha256(body).hexdigest()
    try:
        document = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=lambda _token: _NONFINITE, parse_int=_parse_integer,
            parse_float=_parse_float)
    except Exception:
        return _minimal_summary(body, maximum_response_bytes, expected_count, reason)

    wire_type = _wire_type(document)
    if type(document) is not dict:
        return SafeResponseValidation(reason, wire_type, len(body), digest, expected_count,
            None, None, None, None, None, None, None)

    answers = document.get("answers", _MISSING)
    if type(answers) is not dict:
        return SafeResponseValidation(reason, wire_type, len(body), digest, expected_count,
            None, None, None, None, None, None, None)

    answer_count = _bounded_count(len(answers))
    ordered_expected = sorted(expected, key=lambda key: key.rsplit(":", 1)[-1])
    matched = [key for key in ordered_expected if key in answers]
    ordered_noul = sorted(expected_noul, key=lambda key: key.rsplit(":", 1)[-1])[:5]
    matched_noul = [key for key in ordered_noul if key in answers]
    matched_all = [*matched, *matched_noul]
    missing_count = max(0, expected_count - len(matched_all))
    unexpected_count = _bounded_count(len(answers) - len(matched_all))
    invalid_count = invalid_probability_count = nonfinite_count = oversized_integer_count = 0
    selected_probabilities: list[float] = []
    confidences: list[float] = []
    probability_sums: list[float] = []
    answer_facts: list[SafeResponseAnswerFacts] = []
    answer_fields = {"type", "choice", "confidence", "probabilities"}
    for key in ordered_expected[:15]:
        suffix = key.rsplit(":", 1)[-1]
        answer = answers.get(key, _MISSING)
        if answer is _MISSING:
            answer_facts.append(SafeResponseAnswerFacts(
                suffix, ResponseWireType.MISSING, ResponseValidationReason.ANSWER_COVERAGE,
                None, None, None, len(_CHOICES), None, None, 0, None, None, None, None,
                None, None))
            invalid_count += 1
            continue
        answer_reason = None
        if type(answer) is not dict:
            invalid_count += 1
            answer_facts.append(SafeResponseAnswerFacts(
                suffix, _wire_type(answer), ResponseValidationReason.ANSWER_SHAPE, None,
                None, None, len(_CHOICES), None, None, 0, None, None, None, None, None, None))
            continue
        choice = answer.get("choice", _MISSING)
        safe_choice = ResponseChoice(choice) if type(choice) is str and choice in _CHOICES else None
        if (set(answer) != answer_fields or answer.get("type") != "choice"
                or safe_choice is None):
            answer_reason = ResponseValidationReason.ANSWER_SHAPE
        confidence = answer.get("confidence", _MISSING)
        if confidence is _NONFINITE:
            nonfinite_count += 1
        elif confidence is _OVERSIZED:
            oversized_integer_count += 1
        bounded_confidence = _bounded_probability(confidence)
        if bounded_confidence is None:
            answer_reason = answer_reason or ResponseValidationReason.ANSWER_SHAPE
        else:
            confidences.append(bounded_confidence)

        probabilities = answer.get("probabilities", _MISSING)
        probability_field_count = None
        unexpected_probability_count = None
        known_values = {}
        probability_invalid = type(probabilities) is not dict
        numeric_values = []
        if type(probabilities) is dict:
            probability_field_count = _bounded_count(len(probabilities))
            unexpected_probability_count = _bounded_count(sum(name not in _CHOICES for name in probabilities))
            probability_invalid = set(probabilities) != _CHOICES
            for name in _CHOICES:
                value = probabilities.get(name, _MISSING)
                if value is _NONFINITE:
                    nonfinite_count += 1
                elif value is _OVERSIZED:
                    oversized_integer_count += 1
                bounded = _bounded_probability(value)
                if bounded is not None:
                    numeric_values.append((name, bounded))
                else:
                    probability_invalid = True
            known_values = {name: value for name, value in numeric_values}
        if safe_choice is not None and safe_choice.value in known_values:
            selected_probability = known_values[safe_choice.value]
            selected_probabilities.append(selected_probability)
        else:
            selected_probability = None
        maximum_probability = max(known_values.values()) if known_values else None
        complete_numeric = set(known_values) == _CHOICES
        probability_sum = sum(known_values.values()) if complete_numeric else None
        if probability_sum is not None:
            # Preserve the observed bounded sum even when it is not normalized.
            probability_sums.append(probability_sum)
            if not choice_probability_sum_compatible(known_values):
                probability_invalid = True
        selected_is_maximum = (selected_probability >= maximum_probability
            if selected_probability is not None and maximum_probability is not None and complete_numeric
            else None)
        confidence_consistent = (choice_confidence_consistent(known_values, bounded_confidence)
            if complete_numeric and bounded_confidence is not None else None)
        if probability_invalid:
            invalid_probability_count += 1
            answer_reason = answer_reason or ResponseValidationReason.PROBABILITIES
        elif selected_is_maximum is False:
            answer_reason = answer_reason or ResponseValidationReason.CHOICE_NOT_MAXIMUM
        elif (confidence_consistent is False
              and choice_wire_policy_version == CHOICE_WIRE_POLICY_LEGACY_STRICT):
            answer_reason = answer_reason or ResponseValidationReason.INCONSISTENT_CONFIDENCE
        if answer_reason is not None:
            invalid_count += 1
        answer_facts.append(SafeResponseAnswerFacts(
            suffix, ResponseWireType.OBJECT, answer_reason, safe_choice,
            _bounded_count(len(answer)),
            _bounded_count(sum(name not in answer_fields for name in answer)),
            len(_CHOICES), probability_field_count, unexpected_probability_count,
            _bounded_count(len(known_values), 3), bounded_confidence, selected_probability,
            maximum_probability, probability_sum, selected_is_maximum, confidence_consistent,
            confidence_mismatch_warning=(
                choice_wire_policy_version == CHOICE_WIRE_POLICY_REPORTED_V2
                and confidence_consistent is False
            ) if choice_wire_policy_version == CHOICE_WIRE_POLICY_REPORTED_V2 else None,
        ))

    for key in ordered_noul:
        suffix = key.rsplit(":", 1)[-1]
        answer = answers.get(key, _MISSING)
        if answer is _MISSING:
            answer_facts.append(SafeResponseAnswerFacts(
                suffix, ResponseWireType.MISSING, ResponseValidationReason.ANSWER_COVERAGE,
                None, None, None, 0, None, None, 0, None, None, None, None, None, None))
            invalid_count += 1
            continue
        probability = answer.get("noul", _MISSING) if type(answer) is dict else _MISSING
        if probability is _NONFINITE:
            nonfinite_count += 1
        elif probability is _OVERSIZED:
            oversized_integer_count += 1
        schema_valid = (type(answer) is dict and set(answer) == {"type", "noul"}
                        and answer.get("type") == "noul")
        bounded = _bounded_probability(probability) if schema_valid else None
        answer_reason = None
        if not schema_valid:
            answer_reason = ResponseValidationReason.ANSWER_SHAPE
        if bounded is None:
            invalid_probability_count += 1
            answer_reason = answer_reason or ResponseValidationReason.PROBABILITIES
        if answer_reason is not None:
            invalid_count += 1
        answer_facts.append(SafeResponseAnswerFacts(
            suffix, _wire_type(answer), answer_reason, None,
            _bounded_count(len(answer)) if type(answer) is dict else None,
            _bounded_count(sum(name not in {"type", "noul"} for name in answer))
            if type(answer) is dict else None,
            0, None, None, 0, None, None, None, None, None, None,
            bounded if bounded is not None else None,
        ))

    # If a 500+ digit JSON integer was rejected by the canonical parser, do not use its
    # free-form exception text. The diagnostic parser represents it only as a marker.
    if oversized_integer_count and reason == ResponseValidationReason.UNKNOWN:
        reason = ResponseValidationReason.NUMERIC_OVERFLOW
    return SafeResponseValidation(
        reason, wire_type, len(body), digest, expected_count, answer_count,
        missing_count, unexpected_count, _bounded_count(invalid_count, 20),
        _bounded_count(invalid_probability_count, 20),
        _bounded_count(nonfinite_count, 64), _bounded_count(oversized_integer_count, 64),
        _range(selected_probabilities), _range(confidences), _range(probability_sums, maximum=3.0),
        tuple(answer_facts),
        (choice_wire_policy_version
         if choice_wire_policy_version == CHOICE_WIRE_POLICY_REPORTED_V2 else None),
    )
