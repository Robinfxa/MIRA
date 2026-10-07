"""Named Choice wire-admission policies; separate from semantic thresholds."""
from enum import StrEnum


class ChoiceWirePolicyVersion(StrEnum):
    LEGACY_STRICT = "jev-choice-cent-interval-v1"
    REPORTED_CONFIDENCE = "jev-reported-confidence-v2"


CHOICE_WIRE_POLICY_LEGACY_STRICT = ChoiceWirePolicyVersion.LEGACY_STRICT.value
CHOICE_WIRE_POLICY_REPORTED_V2 = ChoiceWirePolicyVersion.REPORTED_CONFIDENCE.value
SUPPORTED_CHOICE_WIRE_POLICIES = frozenset(
    (CHOICE_WIRE_POLICY_LEGACY_STRICT, CHOICE_WIRE_POLICY_REPORTED_V2))


def is_supported_choice_wire_policy(value: object) -> bool:
    return type(value) is str and value in SUPPORTED_CHOICE_WIRE_POLICIES
