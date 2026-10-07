"""Explicit caller-injected development composition for the real JEV review ports.

This narrow factory is intentionally separate from ``create_providers``. It has no
environment, credential or ADC discovery, network/client allocation, calibration
claim, or paid-call admission logic. The caller owns those decisions and supplies the
already-authorized transports plus an independent bounded attempt allowance.
"""
from __future__ import annotations

import math

from mira.adapters.review.jev import JevReviewBackend, JevTransport, OUTPUT_QUESTION_SET_INTERACTION, OUTPUT_QUESTION_SET_CHARACTER_INTERACTION, OUTPUT_QUESTION_SET_OPTIONAL_EVENTS, OUTPUT_QUESTION_SET_STORY_IMAGES
from mira.adapters.review.jev_input import JevInputDecisionBackend
from mira.adapters.review.jev_support.http import HttpxJevTransport
from mira.application.choice_wire_policy import CHOICE_WIRE_POLICY_REPORTED_V2
from mira.application.decision_contracts import INPUT_QUESTION_SET_V2, INPUT_QUESTION_SET_AUTHORED, mira26_author_policy
from mira.application.decision_policy import (
    DecisionThresholdPolicy,
    is_supported_development_policy,
)
from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
from mira.application.ports.generation import GenerationBackend
from mira.bootstrap.providers import Providers
from mira.bootstrap.development_usage import UsageProfile, parse_usage_profile, validate_count
from mira.config.loader import ConfigurationError


_FIXED_JEV_MODEL = "jev-1.13.0"
_MAX_TIMEOUT_SECONDS = 30.0


def resolve_review_request_limits(
    *, usage_profile: UsageProfile | str = UsageProfile.PROBE,
    character_observations: bool = False,
    input_max_request_bytes: int | None = None,
    output_max_request_bytes: int | None = None,
) -> tuple[int, int]:
    """Resolve exact operator-visible byte ceilings; never provider-call budgets."""
    profile = parse_usage_profile(usage_profile)
    if type(character_observations) is not bool:
        raise ConfigurationError("character_observation_mode_invalid")
    defaults = ((32 * 1024, 64 * 1024)
                if profile is UsageProfile.APPLICATION and character_observations
                else (16 * 1024, 32 * 1024))
    values = tuple(default if value is None else value
                   for value, default in zip((input_max_request_bytes, output_max_request_bytes), defaults))
    if any(type(value) is not int or not 1024 <= value <= 128 * 1024 for value in values):
        raise ConfigurationError("JEV request byte ceilings must be integers from 1024 to 131072.")
    return values


def create_development_review_providers(
    *,
    generation: GenerationBackend,
    input_transport: JevTransport,
    output_transport: JevTransport,
    authorized: bool = False,
    decision_policy: DecisionThresholdPolicy,
    input_request_limit: int = 2,
    output_request_limit: int = 2,
    input_timeout_seconds: float = 10.0,
    output_timeout_seconds: float = 10.0,
    usage_profile: UsageProfile | str = UsageProfile.PROBE,
    character_observations: bool = False,
    conversation_first: bool = False,
    story_images: bool = False,
    input_max_request_bytes: int | None = None,
    output_max_request_bytes: int | None = None,
) -> Providers:
    """Compose real JEV adapters behind the existing Actor semantic-review seam.

    ``authorized`` attests that the caller has already admitted transmission, account,
    credential and spend. This helper does not independently verify that admission,
    discover credentials, read configuration, or contact a service. Input and output
    limits/timeouts are independently bounded; no calibration reference is supplied.
    """
    if authorized is not True:
        raise ConfigurationError(
            "Development semantic review requires explicit caller authorization.")
    if type(character_observations) is not bool:
        raise ConfigurationError("character_observation_mode_invalid")
    if not is_supported_development_policy(decision_policy):
        raise ConfigurationError("Development semantic review requires the exact supported policy.")
    if not callable(getattr(generation, "generate", None)):
        raise ConfigurationError(
            "Development semantic review requires an injected generation backend.")
    if not callable(input_transport) or not callable(output_transport):
        raise ConfigurationError(
            "Development semantic review requires two injected JEV transports.")
    usage_profile = parse_usage_profile(usage_profile)
    validate_count(input_request_limit, usage_profile, name="Input JEV request ceiling")
    validate_count(output_request_limit, usage_profile, name="Output JEV request ceiling")
    if (type(input_timeout_seconds) not in (int, float)
            or not math.isfinite(input_timeout_seconds)
            or not 0 < input_timeout_seconds <= _MAX_TIMEOUT_SECONDS
            or type(output_timeout_seconds) not in (int, float)
            or not math.isfinite(output_timeout_seconds)
            or not 0 < output_timeout_seconds <= _MAX_TIMEOUT_SECONDS):
        raise ConfigurationError(
            "Input and output JEV timeouts must each be finite and at most 30 seconds.")

    input_bytes, output_bytes = resolve_review_request_limits(
        usage_profile=usage_profile, character_observations=character_observations,
        input_max_request_bytes=input_max_request_bytes,
        output_max_request_bytes=output_max_request_bytes)
    # The production transport must enforce the same already-resolved envelope as
    # its backend. Keep shared originals and caller-owned custom interfaces intact.
    if type(input_transport) is HttpxJevTransport:
        input_transport = input_transport.with_max_request_bytes(input_bytes)
    if type(output_transport) is HttpxJevTransport:
        output_transport = output_transport.with_max_request_bytes(output_bytes)
    input_backend = JevInputDecisionBackend(
        transport=input_transport,
        model=_FIXED_JEV_MODEL,
        calibration_ref=None,
        decision_policy=decision_policy,
        question_set_revision=INPUT_QUESTION_SET_AUTHORED if conversation_first else INPUT_QUESTION_SET_V2,
        choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2,
        request_limit=input_request_limit,
        timeout_seconds=input_timeout_seconds,
        max_request_bytes=input_bytes,
    )
    output_backend = JevReviewBackend(
        transport=output_transport,
        model=_FIXED_JEV_MODEL,
        contract_resolver=None,
        calibration_ref=None,
        decision_policy=decision_policy,
        question_set_revision=(OUTPUT_QUESTION_SET_STORY_IMAGES if story_images and conversation_first else
            OUTPUT_QUESTION_SET_OPTIONAL_EVENTS if conversation_first else
            OUTPUT_QUESTION_SET_CHARACTER_INTERACTION if character_observations else OUTPUT_QUESTION_SET_INTERACTION),
        choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2,
        request_limit=output_request_limit,
        timeout_seconds=output_timeout_seconds,
        max_request_bytes=output_bytes,
    )
    return Providers(
        generation=generation,
        review=output_backend,
        semantic_review=SemanticReviewCoordinator(input_backend, output_backend,
                                                  conversation_first=conversation_first),
        decision_owner=DecisionSnapshotOwner(mira26_author_policy(),
            include_authored_referents=conversation_first),
    )
