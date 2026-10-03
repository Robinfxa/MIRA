"""Explicit caller-injected development composition for the real JEV review ports.

This narrow factory is intentionally separate from ``create_providers``. It has no
environment, credential or ADC discovery, network/client allocation, calibration
claim, or paid-call admission logic. The caller owns those decisions and supplies the
already-authorized transports plus an independent bounded attempt allowance.
"""
from __future__ import annotations

import math

from mira.adapters.review.jev import JevReviewBackend, JevTransport
from mira.adapters.review.jev_input import JevInputDecisionBackend
from mira.application.decision_contracts import mira26_author_policy
from mira.application.decision_policy import (
    DecisionThresholdPolicy,
    is_supported_development_policy,
)
from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
from mira.application.ports.generation import GenerationBackend
from mira.bootstrap.providers import Providers
from mira.config.loader import ConfigurationError


_FIXED_JEV_MODEL = "jev-1.13.0"
_MAX_REQUESTS_PER_REVIEW_PORT = 8
_MAX_TIMEOUT_SECONDS = 30.0


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
    if not is_supported_development_policy(decision_policy):
        raise ConfigurationError("Development semantic review requires the exact supported policy.")
    if not callable(getattr(generation, "generate", None)):
        raise ConfigurationError(
            "Development semantic review requires an injected generation backend.")
    if not callable(input_transport) or not callable(output_transport):
        raise ConfigurationError(
            "Development semantic review requires two injected JEV transports.")
    if (type(input_request_limit) is not int
            or not 1 <= input_request_limit <= _MAX_REQUESTS_PER_REVIEW_PORT
            or type(output_request_limit) is not int
            or not 1 <= output_request_limit <= _MAX_REQUESTS_PER_REVIEW_PORT):
        raise ConfigurationError(
            "Input and output JEV request limits must each be between 1 and 8.")
    if (type(input_timeout_seconds) not in (int, float)
            or not math.isfinite(input_timeout_seconds)
            or not 0 < input_timeout_seconds <= _MAX_TIMEOUT_SECONDS
            or type(output_timeout_seconds) not in (int, float)
            or not math.isfinite(output_timeout_seconds)
            or not 0 < output_timeout_seconds <= _MAX_TIMEOUT_SECONDS):
        raise ConfigurationError(
            "Input and output JEV timeouts must each be finite and at most 30 seconds.")

    input_backend = JevInputDecisionBackend(
        transport=input_transport,
        model=_FIXED_JEV_MODEL,
        calibration_ref=None,
        decision_policy=decision_policy,
        request_limit=input_request_limit,
        timeout_seconds=input_timeout_seconds,
    )
    output_backend = JevReviewBackend(
        transport=output_transport,
        model=_FIXED_JEV_MODEL,
        contract_resolver=None,
        calibration_ref=None,
        decision_policy=decision_policy,
        request_limit=output_request_limit,
        timeout_seconds=output_timeout_seconds,
    )
    return Providers(
        generation=generation,
        review=output_backend,
        semantic_review=SemanticReviewCoordinator(input_backend, output_backend),
        decision_owner=DecisionSnapshotOwner(mira26_author_policy()),
    )
