"""Explicit, versioned decision policy selected for development.

This is a decision-policy choice, not a calibration record or a claim about
statistical quality. Keep the recognized policy deliberately small and immutable.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DecisionPolicyRef(StrEnum):
    USER_DEVELOPMENT_0_6_V1 = "user-development-0.6-v1"
    USER_DEVELOPMENT_0_6_V2 = "user-development-0.6-v2"


@dataclass(frozen=True, slots=True)
class DecisionThresholdPolicy:
    reference: DecisionPolicyRef
    choice_probability_min: float
    confidence_min: float
    noul_yes_probability_min: float
    noul_no_probability_max: float
    referent_probability_min: float
    referent_confidence_min: float


USER_DEVELOPMENT_0_6_V1 = DecisionThresholdPolicy(
    reference=DecisionPolicyRef.USER_DEVELOPMENT_0_6_V1,
    choice_probability_min=0.6,
    confidence_min=0.6,
    noul_yes_probability_min=0.6,
    noul_no_probability_max=0.4,
    referent_probability_min=0.6,
    referent_confidence_min=0.6,
)

# V2 is intentionally a new version even though its numeric thresholds are the
# same: the output adapter now applies them to REJECT as well as ALLOW.
USER_DEVELOPMENT_0_6_V2 = DecisionThresholdPolicy(
    reference=DecisionPolicyRef.USER_DEVELOPMENT_0_6_V2,
    choice_probability_min=0.6,
    confidence_min=0.6,
    noul_yes_probability_min=0.6,
    noul_no_probability_max=0.4,
    referent_probability_min=0.6,
    referent_confidence_min=0.6,
)


def is_supported_development_policy(value: object) -> bool:
    """Reject arbitrary bundles and accept only exact immutable policy versions."""
    return (type(value) is DecisionThresholdPolicy
            and type(value.reference) is DecisionPolicyRef
            and value in (USER_DEVELOPMENT_0_6_V1, USER_DEVELOPMENT_0_6_V2))
