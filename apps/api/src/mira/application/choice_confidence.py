"""Provider-neutral validation for the reported normalized Choice statistic.

TypeSafe's Choice wire fields can be rounded independently. This module accepts
nearest-cent representations only when one normalized latent distribution can
produce every reported value. It never replaces the values used by policy.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from fractions import Fraction

CHOICE_WIRE_COMPATIBILITY_VERSION = "jev-choice-cent-interval-v1"
_PROBABILITY_SUM_TOLERANCE = 0.00001
_CONFIDENCE_TOLERANCE = 0.0001
_HALF_CENT = Fraction(1, 200)


def _valid_probabilities(probabilities: object) -> bool:
    return (isinstance(probabilities, Mapping) and len(probabilities) >= 2
            and all(type(value) in (int, float) and 0 <= value <= 1
                    and (type(value) is int or math.isfinite(value))
                    for value in probabilities.values()))


def _cent_interval(value: int | float) -> tuple[Fraction, Fraction] | None:
    """Return the clipped nearest-cent interval only for exact decimal cents."""
    reported = Fraction(str(value))
    if (reported * 100).denominator != 1:
        return None
    return max(Fraction(0), reported - _HALF_CENT), min(Fraction(1), reported + _HALF_CENT)


def choice_probability_sum_compatible(probabilities: Mapping[str, int | float]) -> bool:
    """Check that the reported probability vector can sum to one on the wire.

    Preserve the pre-existing full-precision sum tolerance. Otherwise, accept only
    cent-grid values whose closed, clipped rounding intervals contain a normalized
    vector. This preliminary predicate intentionally does not check confidence.
    """
    if not _valid_probabilities(probabilities):
        return False
    total = sum(probabilities.values())
    if math.isclose(total, 1, abs_tol=_PROBABILITY_SUM_TOLERANCE):
        return True
    intervals = [_cent_interval(value) for value in probabilities.values()]
    if any(interval is None for interval in intervals):
        return False
    return (sum(interval[0] for interval in intervals) <= 1
            <= sum(interval[1] for interval in intervals))


def _joint_cent_feasible(
    probabilities: Mapping[str, int | float], confidence: int | float,
) -> bool:
    values = [_cent_interval(value) for value in probabilities.values()]
    confidence_interval = _cent_interval(confidence)
    if confidence_interval is None or any(interval is None for interval in values):
        return False
    intervals = [interval for interval in values if interval is not None]
    count = len(intervals)
    confidence_low, confidence_high = confidence_interval

    # Invert TypeSafe's Choice confidence equation exactly over rationals.
    top_from_confidence_low = (1 + (count - 1) * confidence_low) / count
    top_from_confidence_high = (1 + (count - 1) * confidence_high) / count

    reported_top = max(probabilities.values())
    top_index = next(index for index, value in enumerate(probabilities.values())
                     if value == reported_top)
    top_low, top_high = intervals[top_index]
    other_intervals = [interval for index, interval in enumerate(intervals)
                       if index != top_index]
    other_lower_sum = sum(lower for lower, _ in other_intervals)

    # A top value x must (1) be report-compatible, (2) match the confidence
    # interval, (3) dominate every other lower bound, and (4) leave enough mass
    # for the other intervals. After intersecting those constraints, feasibility
    # is monotone in x, so checking the highest allowed x is sufficient.
    lower = max(top_low, top_from_confidence_low,
                *(item_lower for item_lower, _ in other_intervals))
    upper = min(top_high, top_from_confidence_high, 1 - other_lower_sum)
    if lower > upper:
        return False
    other_capacity = sum(min(item_upper, upper) for _, item_upper in other_intervals)
    return upper + other_capacity >= 1


def choice_confidence_consistent(
    probabilities: Mapping[str, int | float], confidence: int | float,
) -> bool:
    """Accept the legacy exact statistic or jointly feasible rounded wire values.

    The legacy branch keeps its prior sum/confidence tolerances. The new branch is
    restricted to exact cent-grid reporting and proves existence of one normalized
    latent vector whose maximum yields the confidence interval. No input is mutated,
    rounded, normalized, or used to change an admission threshold.
    """
    if (not _valid_probabilities(probabilities)
            or type(confidence) not in (int, float)
            or not 0 <= confidence <= 1
            or (type(confidence) is float and not math.isfinite(confidence))
            or not choice_probability_sum_compatible(probabilities)):
        return False

    count = len(probabilities)
    probability = max(probabilities.values())
    expected = (probability - 1 / count) / (1 - 1 / count)
    # The historical formula shortcut is valid only when the raw reported vector
    # itself passes the historical normalization tolerance. Cent-grid sums outside
    # that window must pass joint latent-vector feasibility below.
    if (math.isclose(sum(probabilities.values()), 1,
                     abs_tol=_PROBABILITY_SUM_TOLERANCE)
            and math.isclose(confidence, expected, abs_tol=_CONFIDENCE_TOLERANCE)):
        return True

    return _joint_cent_feasible(probabilities, confidence)
