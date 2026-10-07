"""Actual Actor wiring for the selected development policy; all transports are synthetic."""
import asyncio
import json
from dataclasses import replace

import pytest

from mira.adapters.review.jev import JevHttpResponse, JevReviewBackend
from mira.adapters.review.jev_input import JevInputDecisionBackend
from mira.application.contracts import CandidateRange, EffectProposal, ReviewVerdict
from mira.application.decision_contracts import (
    DecisionPolicyRef, InputDecisionStatus, ResponseContractProducer, SemanticValue,
    mira26_author_policy,
)
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V1
from mira.application.decision_runtime import DecisionSnapshotOwner
from mira.application.ports.generation import GenerationBackend
from mira.adapters.review.jev import JevTransport
from mira.bootstrap.providers import Providers, create_providers
from mira.config.loader import ConfigurationError, load_settings
from mira.config.settings import ProviderSettings
from mira.domain.models import EffectKind, Phase, SessionState
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.adapters.journal.memory import MemoryEventJournal
from tests.contracts.test_decision_contracts import candidate, snapshot


MODEL = "jev-1.13.0"


def _choice(choice: str, probability: float = 0.7334) -> dict:
    other = (1 - probability) / 2
    return {
        "type": "choice",
        "choice": choice,
        "confidence": (probability - 1 / 3) / (1 - 1 / 3),
        "probabilities": {name: probability if name == choice else other
                          for name in ("allow", "reject", "unknown")},
    }


class SyntheticJevTransport:
    """In-process TypeSafe-shaped response source; it cannot access a network."""

    def __init__(self, *, output_choice: str = "allow", capture: float = 0.0,
                 input_unknown: bool = False, output_gate: bool = False,
                 suppress_cancel: bool = False) -> None:
        self.output_choice = output_choice
        self.capture = capture
        self.input_unknown = input_unknown
        self.calls: list[tuple[dict, float, int]] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.output_gate = output_gate
        self.suppress_cancel = suppress_cancel

    async def __call__(self, payload: bytes, *, timeout_seconds: float,
                       max_response_bytes: int) -> JevHttpResponse:
        request = json.loads(payload)
        self.calls.append((request, timeout_seconds, max_response_bytes))
        output = "contract" in request["state"]
        if output and self.output_gate:
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                if not self.suppress_cancel:
                    raise
                await self.release.wait()
        answers = {}
        for key, question in request["questions"].items():
            if output:
                if question["type"] == "noul":
                    answers[key] = {"type": "noul", "noul": 0.0}
                else:
                    answers[key] = _choice(self.output_choice)
            elif question["type"] == "noul":
                value = (0.5 if self.input_unknown and key.endswith("capture_restriction")
                         else self.capture if key.endswith("capture_restriction") else 0.0)
                answers[key] = {"type": "noul", "noul": value}
            else:
                options = question["criteria"]
                selected = "none"
                assert selected in options
                answers[key] = {
                    "type": "choice", "choice": selected, "confidence": 1.0,
                    "probabilities": {option: float(option == selected) for option in options},
                }
        response = {"model": MODEL, "answers": answers,
                    "usage": {"input_tokens": 15, "output_tokens": 5}}
        return JevHttpResponse(200, json.dumps(response).encode("utf-8"))


class StaticGeneration:
    def __init__(self, proposal: CandidateRange | None = None) -> None:
        self.proposal = proposal or CandidateRange(
            (EffectProposal(EffectKind.POSE, "face_calm"),), "synthetic-candidate")
        self.calls = 0

    async def generate(self, context):
        self.calls += 1
        yield self.proposal


def factory(*, generation: GenerationBackend | None = None,
            input_transport: JevTransport | None = None,
            output_transport: JevTransport | None = None,
            input_request_limit=2, output_request_limit=2,
            input_timeout_seconds=10.0, output_timeout_seconds=10.0,
            authorized=True, decision_policy=USER_DEVELOPMENT_0_6_V1) -> Providers:
    from mira.bootstrap.development_review import create_development_review_providers

    return create_development_review_providers(
        generation=generation or StaticGeneration(),
        input_transport=input_transport or SyntheticJevTransport(),
        output_transport=output_transport or SyntheticJevTransport(),
        authorized=authorized, decision_policy=decision_policy,
        input_request_limit=input_request_limit, output_request_limit=output_request_limit,
        input_timeout_seconds=input_timeout_seconds, output_timeout_seconds=output_timeout_seconds,
    )


def actor_for(providers: Providers) -> SessionActor:
    return SessionActor(
        SessionState("session-1", "browser-1"), providers.generation, providers.review,
        MemoryEventJournal(100), RuntimeLimits(timeout_seconds=2, max_turns=8, max_effects=32),
        semantic_review=providers.semantic_review, decision_owner=providers.decision_owner,
    )


async def start(value: SessionActor, text: str = "请介绍雨。") -> None:
    await value.submit(request_id="input-1", activity_seq=1, cutoff=0, text=text)


async def finish(value: SessionActor):
    async with asyncio.timeout(3):
        await asyncio.gather(*tuple(value._tasks), return_exceptions=True)
    return await value.snapshot()


@pytest.mark.parametrize("authorized,policy", [
    (False, USER_DEVELOPMENT_0_6_V1),
    (1, USER_DEVELOPMENT_0_6_V1),
    (True, replace(USER_DEVELOPMENT_0_6_V1, confidence_min=0.95)),
])
def test_factory_requires_explicit_exact_admission(authorized, policy):
    input_transport, output_transport = SyntheticJevTransport(), SyntheticJevTransport()
    with pytest.raises(ConfigurationError):
        factory(authorized=authorized, decision_policy=policy,
                input_transport=input_transport, output_transport=output_transport)
    assert input_transport.calls == output_transport.calls == []


def test_default_factory_guard_remains_closed():
    from mira.bootstrap.development_review import create_development_review_providers

    settings = load_settings(environ={})
    default = create_providers(settings.providers)
    assert default.semantic_review is None and default.decision_owner is None
    closed = ProviderSettings(generation="api", review="jev",
                              allow_external_calls=True, allow_paid_api=True)
    with pytest.raises(ConfigurationError):
        create_providers(closed)
    with pytest.raises(ConfigurationError):
        create_development_review_providers(
            generation=StaticGeneration(), input_transport=SyntheticJevTransport(),
            output_transport=SyntheticJevTransport(), decision_policy=USER_DEVELOPMENT_0_6_V1,
        )


def test_factory_composes_real_adapters_without_io():
    generation = StaticGeneration()
    input_transport, output_transport = SyntheticJevTransport(), SyntheticJevTransport()
    providers = factory(generation=generation, input_transport=input_transport,
                        output_transport=output_transport)
    assert providers.generation is generation
    assert type(providers.review) is JevReviewBackend
    assert type(providers.semantic_review._input_decision) is JevInputDecisionBackend
    assert providers.semantic_review._output_review is providers.review
    assert type(providers.decision_owner) is DecisionSnapshotOwner
    assert providers.decision_owner.author_policy == mira26_author_policy()
    assert providers.review._model == providers.semantic_review._input_decision._model == MODEL
    assert providers.review._decision_policy is USER_DEVELOPMENT_0_6_V1
    assert providers.semantic_review._input_decision._decision_policy is USER_DEVELOPMENT_0_6_V1
    assert providers.review._calibration_ref is None
    assert providers.semantic_review._input_decision._calibration_ref is None
    assert providers.review._requests_remaining == 2
    assert providers.semantic_review._input_decision._requests_remaining == 2
    assert input_transport.calls == output_transport.calls == []
    assert generation.calls == 0


@pytest.mark.asyncio
async def test_actor_grants_valid_candidate_through_selected_synthetic_transports():
    input_transport, output_transport = SyntheticJevTransport(), SyntheticJevTransport()
    providers = factory(input_transport=input_transport, output_transport=output_transport)
    value = actor_for(providers)
    await start(value)
    state = await finish(value)
    assert state.sealed and len(state.active_grants) == 1
    assert len(input_transport.calls) == len(output_transport.calls) == 2
    assert all(call[0]["model"] == MODEL for call in input_transport.calls + output_transport.calls)
    observation = output_transport.calls[0][0]["state"]["contract"]["input_observation"]
    assert observation["calibration_ref"] is None
    assert observation["decision_policy_ref"] == DecisionPolicyRef.USER_DEVELOPMENT_0_6_V1
    assert output_transport.calls[0][0]["state"]["candidate"]["fixture_id"] == "synthetic-candidate"
    await value.close()


@pytest.mark.parametrize("outcome", ["unknown", "reject", "input-unknown"])
@pytest.mark.asyncio
async def test_actor_unknown_or_reject_never_grants(outcome):
    input_transport = SyntheticJevTransport(input_unknown=outcome == "input-unknown")
    output_choice = outcome if outcome != "input-unknown" else "allow"
    output_transport = SyntheticJevTransport(output_choice=output_choice)
    providers = factory(input_transport=input_transport, output_transport=output_transport)
    value = actor_for(providers)
    await start(value)
    state = await finish(value)
    assert state.phase == Phase.ERROR and not state.active_grants and not state.issued_effects
    if outcome == "input-unknown":
        assert len(input_transport.calls) == 1 and not output_transport.calls
    else:
        assert len(input_transport.calls) == len(output_transport.calls) == 1
    await value.close()


@pytest.mark.asyncio
async def test_capture_prohibition_blocks_media_before_output_review():
    input_transport, output_transport = SyntheticJevTransport(capture=1.0), SyntheticJevTransport()
    media_candidate = CandidateRange(
        (EffectProposal(EffectKind.MEDIA, "photo"),), "media-candidate")
    providers = factory(generation=StaticGeneration(media_candidate),
                        input_transport=input_transport, output_transport=output_transport)
    snap = snapshot(text="不要拍我。")
    observation = await providers.semantic_review.observe(snap)
    capture = next(item for item in observation.predicates
                   if item.predicate == "capture_restriction")
    assert observation.status == InputDecisionStatus.OBSERVED
    assert capture.value == SemanticValue.YES and observation.calibration_ref is None
    assert observation.decision_policy_ref == DecisionPolicyRef.USER_DEVELOPMENT_0_6_V1
    assert ResponseContractProducer().produce(snap.context, media_candidate, snapshot=snap,
                                              observation=observation) is None
    value = actor_for(providers)
    await start(value, "不要拍我。")
    state = await finish(value)
    assert state.phase == Phase.ERROR and not state.active_grants and not state.issued_effects
    assert not output_transport.calls
    await value.close()


@pytest.mark.asyncio
async def test_stop_cancels_delayed_review_without_resurrecting_authority():
    input_transport = SyntheticJevTransport()
    output_transport = SyntheticJevTransport(output_gate=True, suppress_cancel=True)
    providers = factory(input_transport=input_transport, output_transport=output_transport,
                        output_timeout_seconds=2.0)
    value = actor_for(providers)
    await start(value)
    async with asyncio.timeout(1):
        await output_transport.entered.wait()
        stopped = await value.stop(activity_seq=2, cutoff=0)
    assert stopped.phase == Phase.STOPPED
    output_transport.release.set()
    state = await finish(value)
    assert state == stopped and not state.active_grants and not state.issued_effects
    assert len(input_transport.calls) == len(output_transport.calls) == 1
    await value.close()


@pytest.mark.asyncio
async def test_input_output_budgets_and_timeouts_are_independent_and_bounded():
    input_transport, output_transport = SyntheticJevTransport(), SyntheticJevTransport()
    providers = factory(input_transport=input_transport, output_transport=output_transport,
                        input_request_limit=1, output_request_limit=2,
                        input_timeout_seconds=2.0, output_timeout_seconds=3.0)
    assert providers.semantic_review._input_decision._requests_remaining == 1
    assert providers.review._requests_remaining == 2
    assert providers.semantic_review._input_decision._timeout_seconds == 2.0
    assert providers.review._timeout_seconds == 3.0

    snap = snapshot()
    observed = await providers.semantic_review.observe(snap)
    exhausted = await providers.semantic_review.observe(snap)
    assert observed.status == InputDecisionStatus.OBSERVED
    assert exhausted.status == InputDecisionStatus.UNAVAILABLE
    assert len(input_transport.calls) == 1 and input_transport.calls[0][1] == 2.0
    for _ in range(2):
        result = await providers.semantic_review.review(snap, candidate(), observed)
        assert result.verdict == ReviewVerdict.ALLOW
    exhausted_output = await providers.semantic_review.review(snap, candidate(), observed)
    assert exhausted_output.verdict == ReviewVerdict.UNKNOWN
    assert len(output_transport.calls) == 2
    assert all(call[1] == 3.0 for call in output_transport.calls)
    assert all(call[2] == 64 * 1024 for call in input_transport.calls + output_transport.calls)

    for kwargs in (
        {"input_request_limit": 9}, {"output_request_limit": 9},
        {"input_timeout_seconds": 31.0}, {"output_timeout_seconds": 31.0},
    ):
        with pytest.raises(ConfigurationError):
            factory(**kwargs)
