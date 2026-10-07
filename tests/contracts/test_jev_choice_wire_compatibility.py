"""Strict mathematical compatibility for independently rounded JEV Choice fields."""
from __future__ import annotations

import json
import random
from fractions import Fraction

import pytest

from mira.adapters.review.jev import _parse_response
from mira.adapters.review.jev_input import _parse as parse_input
from mira.adapters.review.jev_support.diagnostics import summarize_response_validation
from mira.application.choice_confidence import (
    CHOICE_WIRE_COMPATIBILITY_VERSION,
    choice_confidence_consistent,
    choice_probability_sum_compatible,
)

MODEL = "jev-1.13.0"
QUESTION = "nonce:digest:o1"


@pytest.mark.parametrize(("probabilities", "compatible"), [
    ({"allow": 0.93, "reject": 0.05, "unknown": 0.01}, True),   # .99
    ({"allow": 0.70, "reject": 0.30, "unknown": 0.01}, True),   # 1.01
    ({"allow": 0.70, "reject": 0.28, "unknown": 0.00}, False),  # .98
    ({"allow": 0.70, "reject": 0.31, "unknown": 0.01}, False),  # 1.02
])
def test_probability_sum_wire_compatibility_uses_intersecting_cent_intervals(
    probabilities, compatible,
):
    assert choice_probability_sum_compatible(probabilities) is compatible


@pytest.mark.parametrize(("probabilities", "confidence", "consistent"), [
    ({"allow": 0.93, "reject": 0.05, "unknown": 0.01}, 0.90, True),
    ({"allow": 0.70, "reject": 0.30, "unknown": 0.01}, 0.55, True),
    ({"allow": 0.70, "reject": 0.29, "unknown": 0.00}, 0.55, True),
    # Each field is independently plausible, but no single normalized vector has
    # this top probability and confidence at the same time.
    ({"allow": 0.80, "reject": 0.19, "unknown": 0.00}, 0.90, False),
    ({"allow": 0.70, "reject": 0.28, "unknown": 0.00}, 0.55, False),
    ({"allow": 0.70, "reject": 0.31, "unknown": 0.01}, 0.55, False),
])
def test_joint_choice_confidence_requires_one_feasible_distribution(
    probabilities, confidence, consistent,
):
    assert choice_confidence_consistent(probabilities, confidence) is consistent


def test_wire_compatibility_has_an_explicit_version_marker():
    assert CHOICE_WIRE_COMPATIBILITY_VERSION == "jev-choice-cent-interval-v1"


def test_full_precision_normalized_branch_keeps_legacy_tolerance():
    probabilities = {"allow": 0.88, "reject": 0.12, "unknown": 0.0}
    confidence = (0.88 - 1 / 3) / (1 - 1 / 3)
    assert choice_probability_sum_compatible(probabilities)
    assert choice_confidence_consistent(probabilities, confidence + 0.00005)


def test_full_precision_branch_keeps_legacy_probability_sum_tolerance():
    probabilities = {"allow": 0.88, "reject": 0.120009, "unknown": 0.0}
    confidence = (0.88 - 1 / 3) / (1 - 1 / 3)
    assert choice_probability_sum_compatible(probabilities)
    assert choice_confidence_consistent(probabilities, confidence)


@pytest.mark.parametrize(("probabilities", "confidence"), [
    # In n=2 the displayed formula happens to agree with the raw .50 maximum,
    # but no normalized vector in the rounding intervals can have confidence 0.
    ({"first": 0.50, "second": 0.49}, 0.00),
    # n=3: the raw max implies .97, while normalized interval feasibility requires
    # a lower top probability because the other reported options already have mass.
    ({"none": 0.00, "ambiguous": 0.03, "photo-1": 0.98}, 0.97),
])
def test_unnormalized_cent_sum_never_uses_legacy_confidence_shortcut(
    probabilities, confidence,
):
    assert choice_probability_sum_compatible(probabilities)
    assert not choice_confidence_consistent(probabilities, confidence)


@pytest.mark.parametrize("probabilities", [
    {"allow": True, "reject": 0, "unknown": 0},
    {"allow": -0.01, "reject": 1.0, "unknown": 0},
    {"allow": float("nan"), "reject": 0.5, "unknown": 0.5},
    {"allow": float("inf"), "reject": 0.0, "unknown": 0.0},
])
def test_cent_branch_does_not_relax_numeric_or_precision_validation(probabilities):
    assert not choice_probability_sum_compatible(probabilities)
    assert not choice_confidence_consistent(probabilities, 0.90)


def test_noncent_confidence_mismatch_does_not_enter_the_cent_branch():
    probabilities = {"allow": 0.931, "reject": 0.059, "unknown": 0.01}
    assert choice_probability_sum_compatible(probabilities)
    assert not choice_confidence_consistent(probabilities, 0.90)


def test_seeded_rational_distributions_survive_independent_cent_rounding():
    generator = random.Random(20261004)
    for count in range(2, 6):
        for _ in range(30):
            weights = [generator.randrange(0, 101) for _ in range(count)]
            if not any(weights):
                weights[0] = 1
            denominator = sum(weights)
            latent = [Fraction(weight, denominator) for weight in weights]
            reported = {f"option-{index}": round(float(value), 2)
                        for index, value in enumerate(latent)}
            maximum = max(latent)
            confidence = (maximum - Fraction(1, count)) / (1 - Fraction(1, count))
            reported_confidence = round(float(confidence), 2)
            assert choice_confidence_consistent(reported, reported_confidence)


def test_clipped_intervals_keep_zero_one_cent_values_feasible():
    assert choice_confidence_consistent(
        {"certain": 1.0, "reject": 0.0, "unknown": 0.0}, 0.99,
    )
    assert choice_confidence_consistent(
        {"first": 0.34, "second": 0.33, "third": 0.33}, 0.0,
    )


def _output_body(probabilities, confidence):
    answer = {"type": "choice", "choice": "allow", "confidence": confidence,
              "probabilities": probabilities}
    return json.dumps({"model": MODEL, "answers": {QUESTION: answer},
                       "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()


def test_output_parser_accepts_feasible_cent_grid_and_preserves_reported_values():
    probabilities = {"allow": 0.93, "reject": 0.05, "unknown": 0.01}
    parsed, _ = _parse_response(_output_body(probabilities, 0.90), MODEL, {QUESTION})
    assert parsed == [("allow", 0.93, 0.90)]


@pytest.mark.parametrize(("probabilities", "confidence", "compatible"), [
    ({"allow": 0.70, "reject": 0.29, "unknown": 0.00}, 0.55, True),  # .99
    ({"allow": 0.70, "reject": 0.30, "unknown": 0.01}, 0.55, True),  # 1.01
    ({"allow": 0.70, "reject": 0.28, "unknown": 0.00}, 0.55, False), # .98
    ({"allow": 0.70, "reject": 0.31, "unknown": 0.01}, 0.55, False), # 1.02
])
def test_output_parser_sum_boundaries_match_mathematical_feasibility(
    probabilities, confidence, compatible,
):
    if compatible:
        parsed, _ = _parse_response(_output_body(probabilities, confidence), MODEL, {QUESTION})
        assert parsed == [("allow", 0.70, confidence)]
    else:
        with pytest.raises(ValueError, match="probabilities"):
            _parse_response(_output_body(probabilities, confidence), MODEL, {QUESTION})


def test_output_parser_rejects_jointly_impossible_cent_grid():
    probabilities = {"allow": 0.80, "reject": 0.19, "unknown": 0.00}
    with pytest.raises(ValueError, match="inconsistent_confidence"):
        _parse_response(_output_body(probabilities, 0.90), MODEL, {QUESTION})


def test_input_referent_parser_preserves_raw_cent_grid_for_thresholds():
    probabilities = {"photo-1": 0.93, "none": 0.05, "ambiguous": 0.01}
    questions = {"referent": {"type": "choice", "criteria": dict.fromkeys(probabilities)}}
    body = {"model": MODEL, "answers": {"referent": {
        "type": "choice", "choice": "photo-1", "confidence": 0.90,
        "probabilities": probabilities,
    }}, "usage": {"input_tokens": 1, "output_tokens": 1}}
    _, referent, _ = parse_input(json.dumps(body).encode(), MODEL, questions)
    assert referent.status == "unknown"
    assert referent.confidence == 0.90
    assert {item.option: item.probability for item in referent.probabilities} == probabilities


def test_raw_allow_threshold_is_never_satisfied_by_rounding_up_confidence():
    # Raw probability meets .99; raw confidence remains below the .985 gate.
    probabilities = {"allow": 0.99, "reject": 0.01, "unknown": 0.0}
    assert choice_confidence_consistent(probabilities, 0.98)
    assert probabilities["allow"] == 0.99 and 0.98 < 0.985


def test_diagnostics_keep_raw_sum_while_reporting_joint_compatibility():
    probabilities = {"allow": 0.80, "reject": 0.19, "unknown": 0.00}
    body = _output_body(probabilities, 0.90)
    expected = {QUESTION: {"type": "choice"}}
    with pytest.raises(ValueError) as caught:
        _parse_response(body, MODEL, {QUESTION})
    summary = summarize_response_validation(body, expected, caught.value,
                                            maximum_response_bytes=64 * 1024)
    fact = summary.answer_facts[0]
    assert summary.probability_sum_range == (0.99, 0.99)
    assert fact.probability_sum == 0.99
    assert fact.confidence_consistent is False
    assert fact.answer_reason.value == "inconsistent_confidence"
