"""Entirely synthetic TypeSafe contract tests; no keys or external requests."""
import asyncio
import json
from dataclasses import replace

import pytest

from mira.adapters.review.jev import (
    QUESTION_SET_VERSION, JevHttpResponse, JevReviewBackend, JevReviewContract,
    candidate_digest, context_digest,
)
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext, ReviewVerdict
from mira.domain.models import Effect, EffectKind

MODEL = "jev-1.13.0"


def inputs():
    context = GenerationContext(
        user_text="请介绍窗外的雨，不要拍摄我。",
        user_inputs=("请介绍窗外的雨，不要拍摄我。",),
        presented_effects=(), output_epoch=3,
    )
    candidate = CandidateRange((EffectProposal(EffectKind.SUBTITLE, "窗外正下着雨。"),), "live-1")
    return context, candidate


def contract_for(context, candidate):
    return JevReviewContract(
        contract_id="contract-3", policy_revision=QUESTION_SET_VERSION,
        context_digest=context_digest(context), candidate_digest=candidate_digest(candidate),
        effective_constraints=("不要拍摄用户。",), response_obligations=("介绍窗外的雨。",),
        character_facts=("当前场景窗外正下雨。",), synthetic=True,
    )


def answer(choice="allow", probability=1.0):
    others = (1 - probability) / 2
    return {
        "type": "choice", "choice": choice,
        "confidence": (probability - 1 / 3) / (1 - 1 / 3),
        "probabilities": {name: probability if name == choice else others
                          for name in ("allow", "reject", "unknown")},
    }


@pytest.mark.asyncio
async def test_primary_api_choice_example_is_parseable_without_invented_precision():
    # https://docs.typesafe.ai/api, Choice answer, checked 2026-10-03.
    # Rename only option labels; keep the published numbers independent of answer().
    def mutate(response):
        response["answers"][next(iter(response["answers"]))] = {
            "type": "choice", "choice": "allow", "confidence": 0.81,
            "probabilities": {"allow": 0.88, "reject": 0.12, "unknown": 0.0},
        }
    result = await backend(SyntheticTransport(mutate)).review_detailed(*inputs())
    assert result.observation.verdict == ReviewVerdict.UNKNOWN
    assert result.observation.reason_code == "jev_semantic_unknown"
    assert result.model == MODEL
    assert result.usage.input_tokens == 333


@pytest.mark.asyncio
async def test_observed_rounded_confidence_preserves_semantic_unknown():
    # Numeric-only authenticated diagnostic 20261003T103917836466Z: n=3,
    # p_max=.95, confidence=.93, sum=1. Remaining .05 is synthetic allocation.
    def mutate(response):
        response["answers"][next(iter(response["answers"]))] = {
            "type": "choice", "choice": "allow", "confidence": 0.93,
            "probabilities": {"allow": 0.95, "reject": 0.05, "unknown": 0.0},
        }
    result = await backend(SyntheticTransport(mutate)).review_detailed(*inputs())
    assert result.observation.verdict == ReviewVerdict.UNKNOWN
    assert result.observation.reason_code == "jev_semantic_unknown"
    assert result.model == MODEL


@pytest.mark.asyncio
@pytest.mark.parametrize("probabilities,confidence", [
    ({"allow": 0.88, "reject": 0.12, "unknown": 0.0}, 0.80),
    ({"allow": 0.88, "reject": 0.12, "unknown": 0.0}, 0.84),
    ({"allow": 0.9, "reject": 0.1, "unknown": 0.0}, 1.0),
    ({"allow": 1.0, "reject": 0.0, "unknown": 0.0}, 0.98),
    ({"allow": 0.951, "reject": 0.049, "unknown": 0.0}, 0.93),
    ({"allow": 0.95, "reject": 0.05, "unknown": 0.0}, 0.9301),
])
async def test_confidence_compatibility_rejects_nonoverlap_and_unobserved_precision(
    probabilities, confidence,
):
    def mutate(response):
        response["answers"][next(iter(response["answers"]))] = {
            "type": "choice", "choice": "allow", "confidence": confidence,
            "probabilities": probabilities,
        }
    result = await backend(SyntheticTransport(mutate)).review(*inputs())
    assert result.verdict == ReviewVerdict.UNKNOWN
    assert result.reason_code == "jev_response_contract_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize("calibrated", [False, True])
async def test_rounding_acceptance_never_rounds_up_confidence_for_admission(calibrated):
    def mutate(response):
        response["answers"][next(iter(response["answers"]))] = {
            "type": "choice", "choice": "allow", "confidence": 0.98,
            "probabilities": {"allow": 0.99, "reject": 0.01, "unknown": 0.0},
        }
    result = await backend(SyntheticTransport(mutate), calibrated=calibrated).review(*inputs())
    assert result.verdict == ReviewVerdict.UNKNOWN
    assert result.reason_code == "jev_semantic_unknown"


@pytest.mark.asyncio
async def test_rounded_high_confidence_still_requires_calibration():
    def mutate(response):
        for item in response["answers"].values():
            item.update(confidence=0.99)
    result = await backend(SyntheticTransport(mutate), calibrated=False).review(*inputs())
    assert result.verdict == ReviewVerdict.UNKNOWN
    assert result.reason_code == "jev_policy_not_calibrated"


class SyntheticTransport:
    def __init__(self, mutate=None, status=200, choice="allow"):
        self.calls = []
        self.mutate = mutate
        self.status = status
        self.choice = choice

    async def __call__(self, payload, *, timeout_seconds, max_response_bytes):
        request = json.loads(payload)
        self.calls.append(request)
        response = {"model": MODEL,
                    "answers": {key: answer(self.choice) for key in request["questions"]},
                    "usage": {"input_tokens": 333, "output_tokens": 88}}
        if self.mutate:
            self.mutate(response)
        return JevHttpResponse(self.status, json.dumps(response).encode())


def backend(transport, *, resolver=contract_for, calibrated=True, limit=1):
    return JevReviewBackend(
        transport=transport, model=MODEL, contract_resolver=resolver,
        calibration_ref="synthetic-test-only" if calibrated else None, request_limit=limit,
    )


@pytest.mark.asyncio
async def test_exact_complete_review_covers_content_and_returns_usage():
    transport = SyntheticTransport()
    context, candidate = inputs()
    result = await backend(transport).review_detailed(context, candidate)
    assert result.observation.verdict == ReviewVerdict.ALLOW
    assert result.usage.input_tokens == 333
    assert result.model == MODEL
    request = transport.calls[0]
    assert request["state"]["candidate"]["effects"][0]["value"] == candidate.effects[0].value
    assert request["state"]["context"]["user_text"] == context.user_text
    assert len(request["questions"]) == 7  # O1–O6 plus precise effect coverage
    assert all(result.request_digest in key for key in request["questions"])


@pytest.mark.asyncio
async def test_missing_contract_never_calls_transport():
    transport = SyntheticTransport()
    result = await backend(transport, resolver=lambda *_: None).review(*inputs())
    assert result.reason_code == "jev_contract_missing"
    assert result.verdict == ReviewVerdict.UNKNOWN
    assert not transport.calls


@pytest.mark.asyncio
async def test_changed_candidate_cannot_reuse_contract_or_fixture_identity():
    context, candidate = inputs()
    contract = contract_for(context, candidate)
    changed = replace(candidate, effects=(EffectProposal(EffectKind.SUBTITLE, "已经拍下你了。"),))
    transport = SyntheticTransport()
    result = await backend(transport, resolver=lambda *_: contract).review(context, changed)
    assert result.reason_code == "jev_contract_binding_mismatch"
    assert not transport.calls


@pytest.mark.asyncio
async def test_partial_answers_fail_closed():
    def mutate(response):
        response["answers"].pop(next(iter(response["answers"])))
    result = await backend(SyntheticTransport(mutate)).review(*inputs())
    assert result.verdict == ReviewVerdict.UNKNOWN
    assert result.reason_code == "jev_response_contract_invalid"


@pytest.mark.asyncio
async def test_semantic_reject_is_not_retried_or_replaced():
    transport = SyntheticTransport(choice="reject")
    result = await backend(transport, limit=2).review(*inputs())
    assert result.verdict == ReviewVerdict.REJECT
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_chinese_policy_without_calibration_never_allows():
    result = await backend(SyntheticTransport(), calibrated=False).review(*inputs())
    assert result.verdict == ReviewVerdict.UNKNOWN
    assert result.reason_code == "jev_policy_not_calibrated"


@pytest.mark.asyncio
async def test_request_budget_is_consumed_once_without_retry():
    transport = SyntheticTransport(status=429)
    review = backend(transport)
    first = await review.review(*inputs())
    second = await review.review(*inputs())
    assert first.reason_code == "jev_rate_limited"
    assert second.reason_code == "jev_request_budget_exhausted"
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_cancellation_propagates_and_does_not_retry():
    started = asyncio.Event()
    cancelled = asyncio.Event()
    async def wait_transport(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    task = asyncio.create_task(backend(wait_transport).review(*inputs()))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("model", "jev-latest"), ("model", "jev-1.12.0"), ("answers", []),
    ("usage", {"input_tokens": -1, "output_tokens": 1}),
    ("usage", {"input_tokens": True, "output_tokens": 1}),
    ("usage", {"input_tokens": 2.0, "output_tokens": 1}),
    ("usage", {"input_tokens": 64_001, "output_tokens": 1}),
    ("usage", {"input_tokens": 2}),
])
async def test_invalid_response_envelopes_fail_closed(field, value):
    result = await backend(SyntheticTransport(lambda response: response.update({field: value}))).review(
        *inputs())
    assert result.verdict == ReviewVerdict.UNKNOWN
    assert result.reason_code == "jev_response_contract_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [
    {"type": "noul", "noul": 1.0},
    {**answer(), "extra": "unrequested"},
    {**answer(), "choice": "approve"},
    {**answer(), "confidence": True},
    {**answer(), "confidence": 1.01},
    {**answer(), "confidence": float("nan")},
    {**answer(), "probabilities": {"allow": True, "reject": 0, "unknown": 0}},
    {**answer(), "probabilities": {"allow": 1.2, "reject": -0.2, "unknown": 0}},
    {**answer(), "probabilities": {"allow": 0.1, "reject": 0.7, "unknown": 0.2}},
    {**answer(), "probabilities": {"allow": 1, "reject": 0}},
    {**answer(), "probabilities": {"allow": 1, "reject": 1, "unknown": 1}},
    {**answer(), "probabilities": {"allow": float("inf"), "reject": 0, "unknown": 0}},
    {**answer(), "probabilities": {"allow": 0.9, "reject": 0.05, "unknown": 0.05}},
])
async def test_malformed_primitives_never_become_allow(malformed):
    def mutate(response):
        response["answers"][next(iter(response["answers"]))] = malformed
    result = await backend(SyntheticTransport(mutate)).review(*inputs())
    assert result.reason_code == "jev_response_contract_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    b'{"model":"a","model":"b"}', b'[]', b'null', b'{}', b'not json', b'\xff',
    b' ' * (64 * 1024 + 1), b'[' * 1100 + b']' * 1100,
])
async def test_malformed_raw_bodies_are_redacted(body):
    async def transport(*args, **kwargs):
        return JevHttpResponse(200, body)
    result = await backend(transport).review(*inputs())
    assert result.reason_code == "jev_response_contract_invalid"
    assert result.verdict == ReviewVerdict.UNKNOWN


@pytest.mark.asyncio
async def test_duplicate_answer_keys_are_not_last_value_wins():
    class DuplicateTransport(SyntheticTransport):
        async def __call__(self, *args, **kwargs):
            result = await super().__call__(*args, **kwargs)
            body = result.body.replace(b'"input_tokens": 333', b'"input_tokens": 4,"input_tokens": 333')
            return JevHttpResponse(200, body)
    result = await backend(DuplicateTransport()).review(*inputs())
    assert result.reason_code == "jev_response_contract_invalid"


@pytest.mark.asyncio
async def test_prior_response_cannot_approve_even_identical_second_request():
    class ReplayTransport(SyntheticTransport):
        prior = None
        async def __call__(self, *args, **kwargs):
            response = await super().__call__(*args, **kwargs)
            if self.prior is None:
                self.prior = response
            return self.prior
    transport = ReplayTransport()
    review = backend(transport, limit=2)
    first = await review.review(*inputs())
    second = await review.review(*inputs())
    assert first.verdict == ReviewVerdict.ALLOW
    assert second.reason_code == "jev_response_contract_invalid"
    assert transport.calls[0]["questions"].keys() != transport.calls[1]["questions"].keys()


@pytest.mark.asyncio
async def test_extra_answer_is_not_ignored():
    def mutate(response):
        response["answers"]["not-requested"] = answer()
    result = await backend(SyntheticTransport(mutate)).review(*inputs())
    assert result.reason_code == "jev_response_contract_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize("choice,probability", [("unknown", 1), ("allow", 0.98), ("allow", 0.34)])
async def test_uncertain_answers_stay_unknown(choice, probability):
    def mutate(response):
        response["answers"][next(iter(response["answers"]))] = answer(choice, probability)
    result = await backend(SyntheticTransport(mutate)).review(*inputs())
    assert result.verdict == ReviewVerdict.UNKNOWN
    assert result.reason_code == "jev_semantic_unknown"


@pytest.mark.asyncio
async def test_reject_and_malformed_answer_is_contract_error_not_complete_reject():
    def mutate(response):
        response["answers"][next(iter(response["answers"]))] = {"allow": True}
    result = await backend(SyntheticTransport(mutate, choice="reject")).review(*inputs())
    assert result.reason_code == "jev_response_contract_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reason", [
    (401, "jev_authentication_failed"), (403, "jev_forbidden"),
    (422, "jev_request_invalid"), (529, "jev_overloaded"),
    (503, "jev_service_error"), (307, "jev_http_error"), (404, "jev_http_error"),
])
async def test_http_failures_are_distinct_redacted_and_never_retried(status, reason):
    transport = SyntheticTransport(status=status)
    result = await backend(transport, limit=2).review(*inputs())
    assert result.reason_code == reason
    assert len(transport.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error,reason", [
    (TimeoutError("synthetic-private-material"), "jev_timeout"),
    (RuntimeError("synthetic-private-material"), "jev_transport_error"),
])
async def test_exception_text_never_leaves_transport_boundary(error, reason, caplog, capsys):
    async def transport(*args, **kwargs):
        raise error
    result = await backend(transport).review(*inputs())
    assert result.reason_code == reason
    assert "synthetic-private-material" not in repr(result) + caplog.text + str(capsys.readouterr())


@pytest.mark.asyncio
async def test_changed_context_and_both_prefixes_invalidate_prior_contract():
    context, candidate = inputs()
    contract = contract_for(context, candidate)
    effect = Effect("effect", EffectKind.SUBTITLE, "先前的话", "digest", 3, 2)
    for changed in (replace(context, output_epoch=4), replace(context, user_text="新请求"),
                    replace(context, user_inputs=("新的约束",)),
                    replace(context, presented_effects=(effect,)),
                    replace(context, accepted_prefix=(effect,))):
        transport = SyntheticTransport()
        result = await backend(transport, resolver=lambda *_: contract).review(changed, candidate)
        assert result.reason_code == "jev_contract_binding_mismatch"
        assert not transport.calls


@pytest.mark.asyncio
async def test_both_prefixes_and_scope_are_sent_as_distinct_exact_facts():
    context, candidate = inputs()
    presented = Effect("shown", EffectKind.SUBTITLE, "已经出现", "digest-a", 2, 1)
    pending = Effect("pending", EffectKind.SUBTITLE, "还未出现", "digest-b", 3, 2)
    context = replace(context, presented_effects=(presented,), accepted_prefix=(pending,))
    transport = SyntheticTransport()
    result = await backend(transport, resolver=lambda c, v: replace(contract_for(c, v), scope="seal")).review(
        context, candidate)
    assert result.verdict == ReviewVerdict.ALLOW
    state = transport.calls[0]["state"]
    assert state["context"]["presented_effects"][0]["id"] == "shown"
    assert state["context"]["accepted_prefix"][0]["id"] == "pending"
    assert state["contract"]["scope"] == "seal"


@pytest.mark.asyncio
async def test_contract_revocation_while_request_runs_cannot_allow():
    context, candidate = inputs()
    current = contract_for(context, candidate)
    def revoke(_response):
        nonlocal current
        current = None
    result = await backend(SyntheticTransport(revoke), resolver=lambda *_: current).review(context, candidate)
    assert result.reason_code == "jev_contract_stale"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [EffectKind.POSE, EffectKind.SCENE])
async def test_controls_need_exact_trusted_coverage_and_model_review(kind):
    context, candidate = inputs()
    control = EffectProposal(kind, "rain-window")
    candidate = replace(candidate, effects=candidate.effects + (control,))
    transport = SyntheticTransport()
    uncovered = await backend(transport).review(context, candidate)
    assert uncovered.reason_code == "jev_control_not_covered"
    assert not transport.calls
    review = backend(transport, resolver=lambda c, v: replace(contract_for(c, v), allowed_controls=(control,)))
    result = await review.review(context, candidate)
    assert result.verdict == ReviewVerdict.ALLOW
    assert len(transport.calls[0]["questions"]) == 8


@pytest.mark.asyncio
async def test_media_never_uses_text_review_to_claim_pixel_approval():
    context, candidate = inputs()
    candidate = replace(candidate, effects=(EffectProposal(EffectKind.MEDIA, "photo-rain"),))
    transport = SyntheticTransport()
    result = await backend(transport).review(context, candidate)
    assert result.reason_code == "jev_media_requires_dm"
    assert not transport.calls


@pytest.mark.asyncio
async def test_missing_or_invalid_input_contract_is_rejected_before_network():
    context, candidate = inputs()
    transport = SyntheticTransport()
    for changed in (replace(candidate, effects=()), replace(candidate, effects=list(candidate.effects)),
                    replace(candidate, effects=(EffectProposal("subtitle", "bad kind"),))):
        result = await backend(transport).review(context, changed)
        assert result.reason_code == "jev_review_input_invalid"
    for changed in (replace(contract_for(context, candidate), policy_revision="unvalidated-v2"),
                    replace(contract_for(context, candidate), response_obligations=()),
                    replace(contract_for(context, candidate), character_facts=()),
                    replace(contract_for(context, candidate), effective_constraints=["mutable"]),
                    replace(contract_for(context, candidate), scope="invented")):
        result = await backend(transport, resolver=lambda *_: changed).review(context, candidate)
        assert result.reason_code == "jev_contract_invalid"
    assert not transport.calls


@pytest.mark.asyncio
async def test_oversized_request_is_not_truncated_to_a_different_review():
    context, candidate = inputs()
    context = replace(context, user_inputs=tuple("雨" * 4000 for _ in range(10)))
    transport = SyntheticTransport()
    result = await backend(transport).review(context, candidate)
    assert result.reason_code == "jev_request_too_large"
    assert not transport.calls


@pytest.mark.asyncio
async def test_default_budget_is_zero_even_with_injected_key_transport():
    transport = SyntheticTransport()
    review = JevReviewBackend(transport=transport, model=MODEL, contract_resolver=contract_for)
    result = await review.review(*inputs())
    assert result.reason_code == "jev_request_budget_exhausted"
    assert not transport.calls


@pytest.mark.parametrize("kwargs", [
    {"model": "jev-latest"}, {"model": "jev-preview"}, {"model": "jev-1.13"},
    {"request_limit": -1}, {"request_limit": True}, {"request_limit": 101},
    {"timeout_seconds": 0}, {"timeout_seconds": 31}, {"timeout_seconds": float("nan")},
    {"calibration_ref": ""},
])
def test_invalid_settings_fail_without_network_or_input_echo(kwargs):
    settings = {"transport": SyntheticTransport(), "model": MODEL, "contract_resolver": contract_for}
    settings.update(kwargs)
    with pytest.raises(ValueError, match="^jev_configuration_invalid$"):
        JevReviewBackend(**settings)


@pytest.mark.asyncio
async def test_shared_budget_is_reserved_before_concurrent_awaits():
    started = asyncio.Event()
    release = asyncio.Event()
    transport = SyntheticTransport()
    async def slow_transport(*args, **kwargs):
        started.set()
        await release.wait()
        return await transport(*args, **kwargs)
    review = backend(slow_transport)
    first = asyncio.create_task(review.review(*inputs()))
    await asyncio.wait_for(started.wait(), 1)
    second = await review.review(*inputs())
    assert second.reason_code == "jev_request_budget_exhausted"
    release.set()
    assert (await first).verdict == ReviewVerdict.ALLOW
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_transport_swallowing_cancel_cannot_return_allow():
    started = asyncio.Event()
    transport = SyntheticTransport()
    async def uncooperative(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return await transport(*args, **kwargs)
    task = asyncio.create_task(backend(uncooperative).review(*inputs()))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_exact_probability_threshold_tolerates_float_roundoff_only():
    def mutate(response):
        response["answers"] = {key: answer("allow", 0.99) for key in response["answers"]}
    result = await backend(SyntheticTransport(mutate)).review(*inputs())
    assert result.verdict == ReviewVerdict.ALLOW


@pytest.mark.asyncio
async def test_low_confidence_reject_label_is_unknown_not_substantive_rejection():
    def mutate(response):
        response["answers"][next(iter(response["answers"]))] = answer("reject", 0.34)
    result = await backend(SyntheticTransport(mutate)).review(*inputs())
    assert result.verdict == ReviewVerdict.UNKNOWN
    assert result.reason_code == "jev_semantic_unknown"


@pytest.mark.asyncio
async def test_actual_deadline_cancels_transport_and_consumes_attempt():
    cancelled = asyncio.Event()
    calls = 0
    async def never_returns(*args, **kwargs):
        nonlocal calls
        calls += 1
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    review = JevReviewBackend(transport=never_returns, model=MODEL, contract_resolver=contract_for,
                              request_limit=1, timeout_seconds=0.001)
    result = await review.review(*inputs())
    assert result.reason_code == "jev_timeout"
    assert cancelled.is_set()
    assert (await review.review(*inputs())).reason_code == "jev_request_budget_exhausted"
    assert calls == 1


@pytest.mark.asyncio
async def test_uncooperative_timeout_return_is_discarded():
    transport = SyntheticTransport()
    async def late_result(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return await transport(*args, **kwargs)
    review = JevReviewBackend(transport=late_result, model=MODEL, contract_resolver=contract_for,
                              request_limit=1, timeout_seconds=0.001,
                              calibration_ref="synthetic-test-only")
    result = await review.review(*inputs())
    assert result.reason_code == "jev_timeout"


@pytest.mark.asyncio
async def test_speech_is_reviewed_as_distinct_textual_effect_not_caption_permission():
    context, candidate = inputs()
    caption_contract = contract_for(context, candidate)
    speech = replace(candidate, effects=(EffectProposal(EffectKind.SPEECH, candidate.effects[0].value),))
    transport = SyntheticTransport()
    stale = await backend(transport, resolver=lambda *_: caption_contract).review(context, speech)
    assert stale.reason_code == "jev_contract_binding_mismatch"
    assert not transport.calls
    accepted = await backend(transport).review(context, speech)
    assert accepted.verdict == ReviewVerdict.ALLOW
    assert transport.calls[0]["state"]["candidate"]["effects"][0]["kind"] == "speech"
    assert len(transport.calls[0]["questions"]) == 7


@pytest.mark.asyncio
async def test_speech_constraint_violation_is_rejected_even_when_caption_would_be_fine():
    context, candidate = inputs()
    context = replace(context, user_text="不要说话，只显示字幕。",
                      user_inputs=("不要说话，只显示字幕。",))
    speech = replace(candidate, effects=(EffectProposal(EffectKind.SPEECH, "窗外正下着雨。"),))
    result = await backend(SyntheticTransport(choice="reject")).review(context, speech)
    assert result.verdict == ReviewVerdict.REJECT
