"""Output completion-applicability v3 mechanics; injected synthetic transports only."""
import json
from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.adapters.review.jev import (
    JevHttpResponse, JevReviewBackend, OUTPUT_QUESTION_SET_V3, OUTPUT_QUESTION_SET_INTERACTION, _canonical, _digest,
    candidate_digest, context_digest,
)
from mira.adapters.diagnostics.privacy import _encode_response_validation
from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext, ReviewVerdict
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
from mira.bootstrap.development_app import create_development_app
from mira.config.settings import Settings
from mira.domain.models import Effect, EffectKind
from tests.contracts.test_codex_generation import SyntheticTransport as CodexTransport, agent, event, terminal
from tests.contracts.test_decision_contracts import candidate, snapshot
from tests.contracts.test_development_app_entry import public_runtime, wait_ready
from tests.contracts.test_development_review_composition import SyntheticJevTransport as InputTransport
from tests.contracts.test_jev_review import MODEL, contract_for, inputs


def choice(label="allow", probability=0.9):
    other = (1 - probability) / 2
    confidence = (probability - 1 / 3) / (1 - 1 / 3)
    return {"type": "choice", "choice": label, "confidence": confidence,
            "probabilities": {name: probability if name == label else other
                              for name in ("allow", "reject", "unknown")}}


class OutputTransport:
    def __init__(self, *, applicability=0.0, choices=None, malformed=None):
        self.applicability = applicability
        self.choices = choices or {}
        self.malformed = malformed
        self.calls = []
        self.payloads = []

    async def __call__(self, payload, **_kwargs):
        request = json.loads(payload)
        self.calls.append(request)
        self.payloads.append(payload)
        answers = {}
        for key, question in request["questions"].items():
            suffix = key.rsplit(":", 1)[-1]
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": self.applicability}
            else:
                answers[key] = self.choices.get(suffix, choice())
        if self.malformed is not None:
            key = next(key for key in answers if key.endswith(":" + self.malformed[0]))
            mode = self.malformed[1]
            if mode == "missing":
                answers.pop(key)
            elif mode == "wrong_type":
                answers[key] = {"type": "choice", "noul": 0.0}
            elif mode == "boolean":
                answers[key]["noul"] = True
            elif mode == "nan":
                answers[key]["noul"] = float("nan")
            elif mode == "out_of_range":
                answers[key]["noul"] = 1.01
            elif mode == "malformed_choice":
                answers[key]["confidence"] = True
            elif mode == "extra_answer":
                answers["unexpected:answer"] = choice()
        response = {"model": MODEL, "answers": answers,
                    "usage": {"input_tokens": 1, "output_tokens": 1}}
        return JevHttpResponse(200, json.dumps(response).encode())


def backend(transport, context=None, proposal=None, *, controls=()):
    context = context or inputs()[0]
    proposal = proposal or inputs()[1]
    contract = replace(contract_for(context, proposal), policy_revision=OUTPUT_QUESTION_SET_V3,
                       allowed_controls=tuple(controls))
    return JevReviewBackend(
        transport=transport, model=MODEL, contract_resolver=lambda *_: contract,
        decision_policy=USER_DEVELOPMENT_0_6_V2, question_set_revision=OUTPUT_QUESTION_SET_V3,
        request_limit=1,
    ), context, proposal, contract


@pytest.mark.asyncio
async def test_v3_sends_one_noul_in_existing_bound_batch_and_binds_the_revision():
    transport = OutputTransport()
    review, context, proposal, contract = backend(transport)

    result = await review.review_detailed(context, proposal)

    request = transport.calls[0]
    questions = request["questions"]
    noul = [item for item in questions.values() if item["type"] == "noul"]
    assert len(questions) == 8 and len(noul) == 1
    applicability = next(key for key in questions if key.endswith(":completed_claim_present"))
    assert questions[applicability]["type"] == "noul"
    assert set(questions[applicability]["criteria"]) == {"true", "false"}
    question = questions[applicability]["instructions"]["question"]
    assert "speech or subtitle" in question
    assert "past" in question or "already happened" in question
    assert all(word in question for word in ("pose", "scene", "media", "pending proposals"))
    o3 = next(value for key, value in questions.items() if key.endswith(":o3"))
    assert "Future intentions and typed pose, scene, or media effects" in o3["instructions"]["question"]
    assert request["state"]["contract"]["policy_revision"] == OUTPUT_QUESTION_SET_V3
    assert request["state"]["contract"]["context_digest"] == context_digest(context)
    assert request["state"]["contract"]["candidate_digest"] == candidate_digest(proposal)
    expected_binding = _digest({"state": request["state"], "model": MODEL,
                                "question_set": OUTPUT_QUESTION_SET_V3})
    assert result.request_digest == expected_binding
    assert result.contract_digest == _digest(asdict(contract))
    assert result.observation.verdict == ReviewVerdict.ALLOW
    assert len(transport.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("probability", "o3_probability"), [(0.0, 0.65), (0.4, 0.9)])
async def test_v3_only_clear_no_ignores_weak_or_strong_o3_for_nonclaim(probability, o3_probability):
    context = GenerationContext("看看雨", ("看看雨",), (), 1)
    proposal = CandidateRange((
        EffectProposal(EffectKind.SUBTITLE, "你好，我们一起听雨。"),
        EffectProposal(EffectKind.POSE, "look_at_rain"),
    ), "look-rain")
    pose = proposal.effects[1]
    transport = OutputTransport(applicability=probability, choices={
        "o3": choice("reject", o3_probability),
    })
    review, context, proposal, _ = backend(transport, context, proposal, controls=(pose,))

    result = await review.review_detailed(context, proposal)

    assert result.observation.verdict == ReviewVerdict.ALLOW
    assert len(transport.calls) == 1
    assert next(key for key in transport.calls[0]["questions"]
                if key.endswith(":completed_claim_present")) in transport.calls[0]["questions"]


@pytest.mark.asyncio
async def test_v3_yes_and_unknown_keep_original_o3_result():
    context = GenerationContext("已经展示了吗？", ("已经展示了吗？",), (), 1)
    proposal = CandidateRange((EffectProposal(EffectKind.SUBTITLE, "雨窗照片已经展示。"),), "claim")
    yes_transport = OutputTransport(applicability=0.6,
                                    choices={"o3": choice("reject", 0.9)})
    review, context, proposal, _ = backend(yes_transport, context, proposal)
    rejected = await review.review_detailed(context, proposal)
    assert rejected.observation.verdict == ReviewVerdict.REJECT
    assert rejected.observation.reason_code == "jev_user_development_0_6_v2_reject"

    uncertain_transport = OutputTransport(applicability=0.4001,
        choices={"o3": choice("reject", 0.65)})
    review, context, proposal, _ = backend(uncertain_transport, context, proposal)
    uncertain = await review.review_detailed(context, proposal)
    assert uncertain.observation.verdict == ReviewVerdict.UNKNOWN
    assert uncertain.observation.reason_code == "jev_user_development_0_6_v2_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(("probability", "expected"), [
    (0.3999, ReviewVerdict.ALLOW), (0.4, ReviewVerdict.ALLOW),
    (0.4001, ReviewVerdict.UNKNOWN),
])
async def test_v3_no_probability_boundary_is_inclusive_at_0_4(probability, expected):
    transport = OutputTransport(applicability=probability,
                                 choices={"o3": choice("reject", 0.65)})
    review, context, proposal, _ = backend(transport)
    result = await review.review_detailed(context, proposal)
    assert result.observation.verdict == expected


@pytest.mark.asyncio
async def test_v3_supported_claim_with_matching_presented_evidence_stays_allowable():
    presented = Effect("photo-1", EffectKind.MEDIA, "red-car-photo", "photo-digest", 0, 1)
    context = GenerationContext("这张照片里有什么？", ("这张照片里有什么？",), (presented,), 1)
    proposal = CandidateRange((
        EffectProposal(EffectKind.SUBTITLE, "照片里有一辆红色汽车。"),
    ), "photo-fact")
    transport = OutputTransport(applicability=0.9)
    review, context, proposal, _ = backend(transport, context, proposal)

    result = await review.review_detailed(context, proposal)

    assert result.observation.verdict == ReviewVerdict.ALLOW
    assert transport.calls[0]["state"]["context"]["presented_effects"][0]["id"] == "photo-1"


@pytest.mark.asyncio
async def test_v3_control_only_proposals_are_not_completion_evidence_or_claims():
    context = GenerationContext("看雨", ("看雨",), (), 1)
    proposal = CandidateRange((
        EffectProposal(EffectKind.POSE, "look_at_rain"),
        EffectProposal(EffectKind.SCENE, "rain-window"),
    ), "controls-only")
    transport = OutputTransport(applicability=0.0,
                                 choices={"o3": choice("reject", 0.9)})
    review, context, proposal, _ = backend(transport, context, proposal,
                                            controls=proposal.effects)

    result = await review.review_detailed(context, proposal)

    assert result.observation.verdict == ReviewVerdict.ALLOW
    question = next(item["instructions"]["question"] for key, item in
                    transport.calls[0]["questions"].items()
                    if key.endswith(":completed_claim_present"))
    assert "Typed pose, scene, and media" in question


@pytest.mark.asyncio
async def test_v3_applicability_no_does_not_bypass_explicit_ban_question():
    context, _ = inputs()
    proposal = CandidateRange((EffectProposal(EffectKind.SPEECH, "我会拍摄你。"),), "banned")
    transport = OutputTransport(applicability=0.0, choices={
        "o3": choice("reject", 0.9), "o4": choice("reject", 0.9),
    })
    review, context, proposal, _ = backend(transport, context, proposal)

    result = await review.review_detailed(context, proposal)

    assert result.observation.verdict == ReviewVerdict.REJECT
    assert result.observation.reason_code == "jev_user_development_0_6_v2_reject"


@pytest.mark.asyncio
async def test_v3_applicability_no_cannot_convert_another_unknown_to_allow():
    transport = OutputTransport(applicability=0.0, choices={
        "o1": choice("unknown", 0.9), "o3": choice("reject", 0.9),
    })
    review, context, proposal, _ = backend(transport)

    result = await review.review_detailed(context, proposal)

    assert result.observation.verdict == ReviewVerdict.UNKNOWN
    assert result.observation.reason_code == "jev_user_development_0_6_v2_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(("key", "mode"), [
    ("completed_claim_present", "missing"),
    ("completed_claim_present", "wrong_type"),
    ("completed_claim_present", "boolean"),
    ("completed_claim_present", "nan"),
    ("completed_claim_present", "out_of_range"),
    ("o3", "malformed_choice"),
    ("o3", "missing"),
    ("completed_claim_present", "extra_answer"),
])
async def test_v3_malformed_answers_fail_technically_even_when_applicability_is_no(key, mode):
    transport = OutputTransport(applicability=0.0,
                                choices={"o3": choice("reject", 0.9)},
                                malformed=(key, mode))
    review, context, proposal, _ = backend(transport)

    result = await review.review_detailed(context, proposal)

    assert result.observation.verdict == ReviewVerdict.UNKNOWN
    assert result.observation.reason_code == "jev_response_contract_invalid"
    assert len(transport.calls) == 1
    summary = result.observation.response_diagnostics
    assert summary is not None
    record = _encode_response_validation(summary)
    fact = next(item for item in record["answer_facts"]
                if item["question_suffix"] == "completed_claim_present")
    malformed_noul = key == "completed_claim_present" and mode != "extra_answer"
    assert fact["noul_probability"] == (None if malformed_noul else 0.0)
    assert all(key not in json.dumps(record) for key in transport.calls[0]["questions"])


@pytest.mark.parametrize("mode", ["boolean", "missing", "wrong_type"])
def test_v3_bad_applicability_is_logged_as_bounded_safe_product_diagnostic(
    tmp_path, monkeypatch, mode,
):
    from mira.bootstrap import development_app as module

    codex = CodexTransport(events=[
        event("item/completed", item=agent(json.dumps({"effects": [
            {"kind": "subtitle", "value": "你好，我们一起听雨。"},
            {"kind": "pose", "value": "look_at_rain"},
        ]}, ensure_ascii=False))), terminal(),
    ])

    async def codex_factory(*_):
        return codex

    output = OutputTransport(applicability=0.0, choices={"o3": choice("reject", 0.9)},
                             malformed=("completed_claim_present", mode))
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    create_app = module.create_app
    monkeypatch.setattr(module, "create_app",
                        lambda settings, **kwargs: create_app(settings, **kwargs, diagnostics=sink))
    app = create_development_app(
        runtime=public_runtime(), settings=Settings(), route_kind="public",
        input_transport=InputTransport(), output_transport=output, authorized=True,
        decision_policy=USER_DEVELOPMENT_0_6_V2, codex_transport_factory=codex_factory,
    )
    with TestClient(app) as client:
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        path = "/api/v1/sessions/" + created["session"]["session_id"]
        headers = {"X-Mira-Session-Token": created["session_token"]}
        submitted = client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0,
            "text": "请写一句你好，并看看雨。",
        })
        state = wait_ready(client, path, headers)
        assert submitted.status_code == 202
        assert state["last_error"] == "invalid_response"
        assert state["active_grants"] == []
    assert sink.flush()
    records = []
    for path in (tmp_path / "events").glob("events-*.jsonl"):
        records.extend(json.loads(line) for line in path.read_text().splitlines())
    event_record = next(item for item in records if item.get("stage") == "output_review"
                        and "response_validation" in item)
    summary = event_record["response_validation"]
    assert summary["expected_answer_count"] == 9
    assert any(item["question_suffix"] == "completed_claim_present"
               and item["noul_probability"] is None for item in summary["answer_facts"])
    assert "questions" not in json.dumps(records)
    assert "completed_claim_present" in json.dumps(summary)
    sink.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(("applicability", "o3_choice", "expected_error"), [
    (0.0, choice("reject", 0.65), None),
    (0.5, choice("reject", 0.65), "review_uncertain"),
])
async def test_v3_real_asgi_nonclaim_allow_and_uncertain_fallback_paths(
    applicability, o3_choice, expected_error,
):
    generated = {"effects": [
        {"kind": "subtitle", "value": "你好，我们一起听雨。"},
        {"kind": "pose", "value": "look_at_rain"},
    ]}
    codex = CodexTransport(events=[
        event("item/completed", item=agent(json.dumps(generated, ensure_ascii=False))), terminal(),
    ])

    async def codex_factory(*_):
        return codex

    output = OutputTransport(applicability=applicability, choices={"o3": o3_choice})
    app = create_development_app(
        runtime=public_runtime(), settings=Settings(), route_kind="public",
        input_transport=InputTransport(), output_transport=output, authorized=True,
        decision_policy=USER_DEVELOPMENT_0_6_V2, codex_transport_factory=codex_factory,
    )
    with TestClient(app) as client:
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        path = "/api/v1/sessions/" + created["session"]["session_id"]
        headers = {"X-Mira-Session-Token": created["session_token"]}
        submitted = client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0,
            "text": "请写一句你好，并看看雨。",
        })
        assert submitted.status_code == 202
        state = wait_ready(client, path, headers)

    assert state["last_error"] == expected_error
    assert bool(state["active_grants"]) is (expected_error is None)
    assert codex.closed
    assert len(output.calls) == (1 if expected_error is not None else 2)
    assert all(call["state"]["contract"]["policy_revision"] == OUTPUT_QUESTION_SET_INTERACTION
               for call in output.calls)
    assert all(sum(question["type"] == "noul" for question in call["questions"].values()) == 1
               for call in output.calls)
