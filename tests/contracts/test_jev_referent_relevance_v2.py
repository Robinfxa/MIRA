"""Versioned referent relevance admission; all transports here are synthetic."""
import json
from dataclasses import replace

import pytest

from mira.adapters.review.jev import (
    JevHttpResponse, JevReviewBackend, map_response_contract,
)
from mira.adapters.review.jev_input import (
    JevInputDecisionBackend, _questions,
)
from mira.application.decision_contracts import (
    INPUT_QUESTION_SET, INPUT_QUESTION_SET_V2, ChoiceProbability, ControlledReferent,
    InputDecisionStatus, ReferentObservation, ResponseContractProducer, SemanticValue,
    PresentationFact, evidence_digest, valid_snapshot,
)
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V1
from mira.application.contracts import ReviewVerdict
from mira.bootstrap.development_review import create_development_review_providers
from mira.domain.models import EffectKind
from mira.domain.models import Effect
from tests.contracts.test_decision_contracts import candidate, snapshot
from tests.contracts.test_jev_review import MODEL, SyntheticTransport as OutputTransport


def empty_snapshot(text="你好，我们一起听雨。"):
    return replace(snapshot(text), referents=())


class SyntheticInputTransport:
    def __init__(self, *, nouls=None, choice=None):
        self.nouls = {"speech_restriction": 0.0, "capture_restriction": 0.0,
                      "display_request": 0.0, "referent_required": 0.4} | (nouls or {})
        self.choice = choice
        self.calls = []

    async def __call__(self, payload, *, timeout_seconds, max_response_bytes):
        request = json.loads(payload)
        self.calls.append(request)
        answers = {}
        for key, question in request["questions"].items():
            name = key.rsplit(":", 1)[-1]
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": self.nouls[name]}
                continue
            options = question["criteria"]
            if self.choice is None:
                selected = "photo-1" if "photo-1" in options else "none"
                probabilities = {option: float(option == selected) for option in options}
                confidence = 1.0
            else:
                selected = self.choice["choice"]
                probabilities = self.choice["probabilities"]
                confidence = self.choice["confidence"]
            answers[key] = {"type": "choice", "choice": selected,
                            "confidence": confidence, "probabilities": probabilities}
        body = {"model": MODEL, "answers": answers,
                "usage": {"input_tokens": 12, "output_tokens": 7}}
        return JevHttpResponse(200, json.dumps(body).encode())


def input_backend(transport, *, question_set_revision=INPUT_QUESTION_SET_V2,
                  snapshot_is_current=None):
    return JevInputDecisionBackend(
        transport=transport, model=MODEL, decision_policy=USER_DEVELOPMENT_0_6_V1,
        question_set_revision=question_set_revision, request_limit=1,
        snapshot_is_current=snapshot_is_current,
    )


def producer(snap, observed, proposal=None):
    return ResponseContractProducer().produce(
        snap.context, proposal or candidate(), snapshot=snap, observation=observed)


def ambiguous_empty_choice():
    return {"choice": "none", "confidence": 0.12,
            "probabilities": {"none": 0.56, "ambiguous": 0.44}}


@pytest.mark.asyncio
async def test_v2_no_referent_need_accepts_empty_set_and_retains_uncertainty():
    snap = empty_snapshot()
    transport = SyntheticInputTransport(choice=ambiguous_empty_choice())
    observed = await input_backend(transport).observe(snap)
    assert observed.status == InputDecisionStatus.OBSERVED
    assert observed.question_set_revision == INPUT_QUESTION_SET_V2
    assert observed.referent.status == "unknown"
    assert observed.referent.referent_id is None
    assert {item.option: item.probability for item in observed.referent.probabilities} == {
        "none": 0.56, "ambiguous": 0.44}
    required = next(item for item in observed.predicates if item.predicate == "referent_required")
    assert (required.value, required.probability) == (SemanticValue.NO, 0.4)
    assert observed.unresolved_items == ("referent_identity",)
    contract = producer(snap, observed)
    assert contract is not None
    assert contract.unresolved_items == ("referent_identity",)
    assert contract.input_observation.referent.status == "unknown"


@pytest.mark.asyncio
async def test_absent_photo_question_stays_blocked_without_identity():
    snap = empty_snapshot("What is in the particular photo from yesterday?")
    transport = SyntheticInputTransport(
        nouls={"referent_required": 0.6}, choice={"choice": "none", "confidence": 1.0,
                                                   "probabilities": {"none": 1.0,
                                                                     "ambiguous": 0.0}})
    observed = await input_backend(transport).observe(snap)
    assert observed.status == InputDecisionStatus.UNKNOWN
    assert next(item for item in observed.predicates if item.predicate == "referent_required").value \
        == SemanticValue.YES
    assert producer(snap, observed) is None


@pytest.mark.asyncio
async def test_midband_referent_necessity_remains_unknown_and_blocking():
    snap = empty_snapshot()
    transport = SyntheticInputTransport(nouls={"referent_required": 0.5},
                                        choice=ambiguous_empty_choice())
    observed = await input_backend(transport).observe(snap)
    assert observed.status == InputDecisionStatus.UNKNOWN
    assert next(item for item in observed.predicates if item.predicate == "referent_required").value \
        == SemanticValue.UNKNOWN
    assert producer(snap, observed) is None


@pytest.mark.asyncio
async def test_nonempty_ambiguous_referent_set_stays_blocked_when_identity_is_required():
    snap = snapshot("Which one is in that photo?")
    second_photo = Effect("photo-2", EffectKind.MEDIA, "fixed-photo-v2", "photo-digest-2", 1, 1)
    second_fact = PresentationFact(second_photo, "presented")
    snap = replace(
        snap,
        context=replace(snap.context, presented_effects=snap.context.presented_effects + (second_photo,)),
        presentation_facts=(snap.presentation_facts[0], second_fact, *snap.presentation_facts[1:]),
        referents=snap.referents + (
            ControlledReferent("photo-2", "another presented photo", "photo-2"),),
    )
    assert valid_snapshot(snap)
    choice = {"choice": "ambiguous", "confidence": 0.8666666667,
              "probabilities": {"none": 0.0, "ambiguous": 0.9,
                                "photo-1": 0.05, "photo-2": 0.05}}
    observed = await input_backend(
        SyntheticInputTransport(nouls={"referent_required": 0.6}, choice=choice)).observe(snap)
    assert observed.status == InputDecisionStatus.UNKNOWN
    assert observed.referent.status == "ambiguous"
    assert producer(snap, observed) is None


@pytest.mark.asyncio
async def test_exact_presented_identity_can_bind_when_needed():
    snap = snapshot("What is in the shown photo?")
    observed = await input_backend(
        SyntheticInputTransport(nouls={"referent_required": 0.6})).observe(snap)
    assert observed.status == InputDecisionStatus.OBSERVED
    assert observed.referent.status == "resolved"
    assert observed.referent.referent_id == "photo-1"
    assert producer(snap, observed) is not None


@pytest.mark.asyncio
async def test_high_scoring_unpresented_identity_is_not_admitted():
    snap = snapshot("What is in the shown photo?")
    snap = replace(snap, referents=(replace(snap.referents[0],
                                             presentation_effect_id="speech-1"),))
    observed = await input_backend(
        SyntheticInputTransport(nouls={"referent_required": 0.6})).observe(snap)
    assert observed.status == InputDecisionStatus.UNKNOWN
    assert observed.referent.status == "resolved"
    assert observed.referent.referent_id == "photo-1"
    assert producer(snap, observed) is None


@pytest.mark.asyncio
async def test_display_request_requires_presented_target_even_when_identity_is_irrelevant():
    snap = empty_snapshot("Keep that photo visible.")
    transport = SyntheticInputTransport(
        nouls={"display_request": 0.6, "referent_required": 0.4},
        choice={"choice": "none", "confidence": 1.0,
                "probabilities": {"none": 1.0, "ambiguous": 0.0}})
    observed = await input_backend(transport).observe(snap)
    assert observed.status == InputDecisionStatus.UNKNOWN
    assert producer(snap, observed) is None


@pytest.mark.asyncio
async def test_newly_generated_text_is_not_preexisting_display_request():
    snap = empty_snapshot("Put a newly generated sentence on screen and look at the rain.")
    transport = SyntheticInputTransport(choice=ambiguous_empty_choice())
    observed = await input_backend(transport).observe(snap)
    assert observed.status == InputDecisionStatus.OBSERVED
    assert next(item for item in observed.predicates if item.predicate == "display_request").value \
        == SemanticValue.NO
    question_texts = [q["instructions"]["question"]
                      for q in transport.calls[0]["questions"].values()]
    assert any("pre-existing controlled object" in text and "newly generated text" in text
               for text in question_texts)
    assert any("looking toward ambient scenery" in text for text in question_texts)


@pytest.mark.asyncio
async def test_referent_exemption_does_not_override_speech_or_media_controls():
    snap = empty_snapshot("Say one sentence, and do not speak aloud.")
    transport = SyntheticInputTransport(nouls={"speech_restriction": 0.6},
                                         choice=ambiguous_empty_choice())
    observed = await input_backend(transport).observe(snap)
    assert observed.status == InputDecisionStatus.OBSERVED
    assert producer(snap, observed, candidate(EffectKind.SPEECH, "I will still speak.")) is None
    assert producer(snap, observed, candidate(EffectKind.MEDIA, "photo-1")) is None

    capture_input = "Do not photograph me; just say hello and look toward the rain."
    capture_snap = replace(empty_snapshot(capture_input), effective_constraints=())
    capture_observed = await input_backend(SyntheticInputTransport(
        nouls={"capture_restriction": 0.6}, choice=ambiguous_empty_choice())).observe(capture_snap)
    capture_contract = producer(capture_snap, capture_observed)
    assert capture_observed.status == InputDecisionStatus.OBSERVED
    assert next(item for item in capture_observed.predicates
                if item.predicate == "capture_restriction").value == SemanticValue.YES
    assert capture_contract is not None
    assert capture_input in capture_contract.effective_constraints
    assert producer(capture_snap, capture_observed,
                    candidate(EffectKind.MEDIA, "captured-photo")) is None


@pytest.mark.asyncio
async def test_output_review_sees_retained_uncertainty_and_can_reject_object_claim():
    snap = empty_snapshot("Tell me what was in the missing photo.")
    input_observation = await input_backend(SyntheticInputTransport(
        nouls={"referent_required": 0.4}, choice=ambiguous_empty_choice())).observe(snap)
    assert input_observation.status == InputDecisionStatus.OBSERVED
    claimed_candidate = candidate(EffectKind.SPEECH,
                                  "The missing photo showed a red car.")
    contract = producer(snap, input_observation, claimed_candidate)
    assert contract is not None
    output_transport = OutputTransport(choice="reject")
    output = JevReviewBackend(
        transport=output_transport, model=MODEL,
        contract_resolver=lambda _context, _candidate: map_response_contract(contract),
        request_limit=1, decision_policy=USER_DEVELOPMENT_0_6_V1,
    )
    reviewed = await output.review_detailed(snap.context, claimed_candidate)
    assert reviewed.observation.verdict == ReviewVerdict.REJECT
    reviewed_input = output_transport.calls[0]["state"]["contract"]["input_observation"]
    assert reviewed_input["unresolved_items"] == ["referent_identity"]
    assert reviewed_input["referent"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_unresolved_marker_is_exact_required_evidence_for_v2_contract():
    snap = empty_snapshot()
    observation = await input_backend(SyntheticInputTransport(
        choice=ambiguous_empty_choice())).observe(snap)
    assert observation.status == InputDecisionStatus.OBSERVED
    assert producer(snap, replace(observation, unresolved_items=())) is None
    assert producer(snap, replace(observation, unresolved_items=("other",))) is None
    assert evidence_digest(snap) == observation.snapshot_digest


@pytest.mark.parametrize("status,probabilities,confidence", [
    ("resolved", (ChoiceProbability("none", 0.21), ChoiceProbability("ambiguous", 0.2),
                   ChoiceProbability("photo-1", 0.59)), 0.7),
    ("resolved", (ChoiceProbability("none", 0.2), ChoiceProbability("ambiguous", 0.41),
                   ChoiceProbability("photo-1", 0.39)), 0.7),
])
@pytest.mark.asyncio
async def test_forged_resolved_identity_must_meet_probability_floor_and_be_distribution_max(
    status, probabilities, confidence,
):
    snap = snapshot()
    base = await input_backend(SyntheticInputTransport()).observe(snap)
    forged = replace(base, referent=ReferentObservation(
        status, "photo-1", probabilities, confidence))
    assert producer(snap, forged) is None


@pytest.mark.parametrize("stale,stop", [(True, False), (False, True)])
@pytest.mark.asyncio
async def test_stale_or_stopped_snapshot_cannot_enter_v2_observation(stale, stop):
    snap = replace(empty_snapshot(), local_stop=stop)
    transport = SyntheticInputTransport()
    observed = await input_backend(transport,
        snapshot_is_current=(lambda _snapshot: not stale) if stale else None).observe(snap)
    assert observed.status in (InputDecisionStatus.STALE, InputDecisionStatus.UNAVAILABLE)
    assert not transport.calls


def test_two_argument_question_helper_keeps_historical_v1_evaluator_shape():
    snap = empty_snapshot()
    v1 = _questions(snap, "1" * 64)
    expected_names = {"speech_restriction", "capture_restriction", "display_request", "referent"}
    assert {key.rsplit(":", 1)[-1] for key in v1} == expected_names
    assert all("referent_required" not in key for key in v1)
    explicit_v1 = _questions(snap, "1" * 64, INPUT_QUESTION_SET)
    strip_nonce = lambda questions: {key.rsplit(":", 1)[-1]: question
                                     for key, question in questions.items()}
    assert strip_nonce(explicit_v1) == strip_nonce(v1)


def test_development_factory_explicitly_selects_v2_without_io():
    class Generation:
        async def generate(self, _context):
            return
            yield

    input_transport, output_transport = SyntheticInputTransport(), OutputTransport()
    providers = create_development_review_providers(
        generation=Generation(), input_transport=input_transport,
        output_transport=output_transport, authorized=True,
        decision_policy=USER_DEVELOPMENT_0_6_V1,
    )
    assert providers.semantic_review._input_decision._question_set_revision == INPUT_QUESTION_SET_V2
    assert not input_transport.calls and not output_transport.calls
