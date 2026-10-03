"""Provider-neutral validation for the reported normalized Choice statistic.

The cent-grid branch checks whether independently rounded wire values are
mathematically compatible. It does not replace those values; decision thresholds
must always be applied to the original reported probability and confidence.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from fractions import Fraction


def choice_confidence_consistent(
    probabilities: Mapping[str, int | float], confidence: int | float,
) -> bool:
    """Accept exact values or overlapping nearest-cent intervals for the statistic.

    This matches the existing wire compatibility rule used by JEV parsers. Inputs
    are still required to be finite, normalized probability data. The interval path
    validates representation only; it never rounds a value into an admission gate.
    """
    if not isinstance(probabilities, Mapping) or len(probabilities) < 2:
        return False
    if (type(confidence) not in (int, float) or not 0 <= confidence <= 1
            or not math.isfinite(confidence)
            or any(type(value) not in (int, float) or not 0 <= value <= 1
                   or not math.isfinite(value) for value in probabilities.values())
            or not math.isclose(sum(probabilities.values()), 1, abs_tol=0.00001)):
        return False
    count = len(probabilities)
    probability = max(probabilities.values())
    expected = (probability - 1 / count) / (1 - 1 / count)
    if math.isclose(confidence, expected, abs_tol=0.0001):
        return True
    values = [Fraction(str(value)) for value in (*probabilities.values(), confidence)]
    if any((value * 100).denominator != 1 for value in values):
        return False
    # Rational endpoints avoid adding an arbitrary epsilon to the rounding interval.
    top, reported = max(values[:-1]), values[-1]
    half_cent = Fraction(1, 200)
    lower = max(Fraction(1, count), top - half_cent)
    upper = min(Fraction(1), top + half_cent)
    expected_lower = (count * lower - 1) / (count - 1)
    expected_upper = (count * upper - 1) / (count - 1)
    return (expected_lower <= min(Fraction(1), reported + half_cent)
            and expected_upper >= max(Fraction(0), reported - half_cent))
