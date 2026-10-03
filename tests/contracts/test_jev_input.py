"""Synthetic transport only; these tests do not evaluate Chinese language quality."""
import asyncio
import json
from dataclasses import asdict, replace

import pytest

from mira.adapters.review.jev import JevHttpResponse
from mira.adapters.review.jev_input import JevInputDecisionBackend, _parse
from mira.application.decision_contracts import InputDecisionStatus, SemanticValue, evidence_digest
from tests.contracts.test_decision_contracts import snapshot

MODEL = "jev-1.13.0"


class SyntheticTransport:
    def __init__(self, mutate=None, status=200):
        self.calls = []
        self.mutate = mutate
        self.status = status

    async def __call__(self, payload, **kwargs):
        request = json.loads(payload)
        self.calls.append(request)
        answers = {}
        for key, question in request["questions"].items():
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.0 if key.endswith("capture_restriction") else 1.0}
            else:
                answers[key] = {"type": "choice", "choice": "photo-1", "confidence": 1.0,
                                "probabilities": {option: float(option == "photo-1")
                                                  for option in question["criteria"]}}
        body = {"model": MODEL, "answers": answers,
                "usage": {"input_tokens": 100, "output_tokens": 40}}
        if self.mutate:
            self.mutate(body)
        return JevHttpResponse(self.status, json.dumps(body).encode())


def backend(transport, **kwargs):
    return JevInputDecisionBackend(transport=transport, model=MODEL,
        **({"calibration_ref": "synthetic-test-only", "request_limit": 1} | kwargs))


@pytest.mark.asyncio
async def test_primary_api_choice_example_is_parseable_without_invented_precision():
    # https://docs.typesafe.ai/api, Choice answer, checked 2026-10-03.
    # Only the option labels differ from the source; no expected formula helper.
    def mutate(body):
        key = next(k for k in body["answers"] if k.endswith("referent"))
        body["answers"][key] = {
            "type": "choice", "choice": "photo-1", "confidence": 0.81,
            "probabilities": {"photo-1": 0.88, "none": 0.12, "ambiguous": 0.0},
        }
    result = await backend(SyntheticTransport(mutate)).observe(snapshot())
    assert result.status == InputDecisionStatus.UNKNOWN
    assert result.reason_code == "jev_input_semantic_unknown"
    assert result.referent.status == "unknown"
    assert result.referent.confidence == 0.81
    assert result.input_tokens == 100


@pytest.mark.asyncio
async def test_observed_rounded_confidence_preserves_semantic_unknown():
    # Only n=3, p_max=.95, confidence=.93 and sum=1 were retained from the
    # 20261003T103917836466Z live diagnostic. The other probabilities are synthetic.
    def mutate(body):
        key = next(k for k in body["answers"] if k.endswith("referent"))
        body["answers"][key] = {
            "type": "choice", "choice": "photo-1", "confidence": 0.93,
            "probabilities": {"photo-1": 0.95, "none": 0.05, "ambiguous": 0.0},
        }
    result = await backend(SyntheticTransport(mutate)).observe(snapshot())
    assert result.status == InputDecisionStatus.UNKNOWN
    assert result.reason_code == "jev_input_semantic_unknown"
    assert result.referent.confidence == 0.93
    assert dict((x.option, x.probability) for x in result.referent.probabilities) == {
        "photo-1": 0.95, "none": 0.05, "ambiguous": 0.0}


@pytest.mark.parametrize("probabilities,confidence", [
    # Synthetic latent p=.953 gives confidence=.906 for two options.
    ({"none": 0.95, "ambiguous": 0.05}, 0.91),
    # Four options: (.90 - .25) / .75 = .86666..., reported as .87.
    ({"none": 0.9, "ambiguous": 0.04, "photo-1": 0.03, "photo-2": 0.03}, 0.87),
])
def test_choice_rounding_uses_actual_option_count(probabilities, confidence):
    question = {"referent": {"type": "choice", "criteria": dict.fromkeys(probabilities)}}
    body = {"model": MODEL, "answers": {"referent": {
        "type": "choice", "choice": "none", "confidence": confidence,
        "probabilities": probabilities,
    }}, "usage": {"input_tokens": 1, "output_tokens": 1}}
    _, referent, _ = _parse(json.dumps(body).encode(), MODEL, question)
    assert referent.status == "unknown"
    assert referent.confidence == confidence


@pytest.mark.asyncio
@pytest.mark.parametrize("probability,confidence", [
    (0.88, 0.80), (0.88, 0.84), (0.9, 1.0), (1.0, 0.98),
    (0.951, 0.93), (0.95, 0.9301),
])
async def test_choice_confidence_compatibility_rejects_invalid_precision_or_interval(
    probability, confidence,
):
    def mutate(body):
        item = body["answers"][next(k for k in body["answers"] if k.endswith("referent"))]
        item.update(confidence=confidence,
                    probabilities={"photo-1": probability, "none": round(1 - probability, 3),
                                   "ambiguous": 0.0})
    result = await backend(SyntheticTransport(mutate)).observe(snapshot())
    assert result.status == InputDecisionStatus.INVALID
    assert result.reason_code == "jev_input_response_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize("calibration_ref", [None, "synthetic-test-only"])
async def test_rounded_choice_never_increases_confidence_for_admission(calibration_ref):
    def mutate(body):
        item = body["answers"][next(k for k in body["answers"] if k.endswith("referent"))]
        item.update(confidence=0.98,
                    probabilities={"photo-1": 0.99, "none": 0.01, "ambiguous": 0.0})
    result = await backend(SyntheticTransport(mutate), calibration_ref=calibration_ref).observe(snapshot())
    assert result.status == InputDecisionStatus.UNKNOWN
    assert result.referent.status == "unknown"
    assert result.referent.confidence == 0.98


@pytest.mark.asyncio
async def test_rounded_high_confidence_still_requires_calibration():
    def mutate(body):
        body["answers"][next(k for k in body["answers"] if k.endswith("referent"))]["confidence"] = 0.99
    result = await backend(SyntheticTransport(mutate), calibration_ref=None).observe(snapshot())
    assert result.status == InputDecisionStatus.UNKNOWN
    assert result.reason_code == "jev_input_not_calibrated"


@pytest.mark.asyncio
async def test_exact_raw_snapshot_and_independent_primitive_questions():
    snap = snapshot()
    transport = SyntheticTransport()
    result = await backend(transport).observe(snap)
    assert result.status == InputDecisionStatus.OBSERVED
    assert result.snapshot_digest == evidence_digest(snap)
    assert {x.predicate: x.value for x in result.predicates} == {
        "speech_restriction": SemanticValue.YES, "capture_restriction": SemanticValue.NO,
        "display_request": SemanticValue.YES}
    assert result.referent.referent_id == "photo-1"
    assert result.input_tokens == 100
    request = transport.calls[0]
    assert request["state"] == json.loads(json.dumps(asdict(snap)))
    assert sorted(q["type"] for q in request["questions"].values()) == ["choice", "noul", "noul", "noul"]
    assert all(result.request_digest in key for key in request["questions"])
    assert not hasattr(result.predicates[0], "confidence")


@pytest.mark.asyncio
async def test_defaults_disable_calls_and_uncalibrated_answers_remain_unknown():
    transport = SyntheticTransport()
    default = JevInputDecisionBackend(transport=transport, model=MODEL)
    result = await default.observe(snapshot())
    assert result.reason_code == "jev_input_budget_exhausted"
    assert not transport.calls
    result = await backend(transport, calibration_ref=None).observe(snapshot())
    assert result.status == InputDecisionStatus.UNKNOWN
    assert result.reason_code == "jev_input_not_calibrated"
    assert result.unresolved_items == (snapshot().context.user_text,)


@pytest.mark.asyncio
async def test_explicit_local_stop_never_waits_for_or_calls_provider():
    transport = SyntheticTransport()
    result = await backend(transport).observe(replace(snapshot(), local_stop=True))
    assert result.reason_code == "jev_input_local_stop"
    assert not transport.calls


@pytest.mark.asyncio
async def test_missing_extra_and_previous_request_answers_fail_exact_coverage():
    first_body = None
    def replay(body):
        nonlocal first_body
        if first_body is None:
            first_body = body.copy()
        else:
            body.update(first_body)
    adapter = backend(SyntheticTransport(replay), request_limit=2)
    assert (await adapter.observe(snapshot())).status == InputDecisionStatus.OBSERVED
    assert (await adapter.observe(snapshot())).reason_code == "jev_input_response_invalid"
    for mutate in (lambda body: body["answers"].pop(next(iter(body["answers"]))),
                   lambda body: body["answers"].update({"extra": {"type": "noul", "noul": 1}})):
        result = await backend(SyntheticTransport(mutate)).observe(snapshot())
        assert result.status == InputDecisionStatus.INVALID


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [
    {"type": "noul", "noul": True}, {"type": "noul", "noul": 1.01},
    {"type": "noul", "noul": float("nan")}, {"type": "noul", "noul": "1"},
    {"type": "noul", "noul": 1, "confidence": 1},
])
async def test_noul_has_no_invented_confidence_and_rejects_invalid_probability(malformed):
    def mutate(body):
        key = next(k for k in body["answers"] if k.endswith("speech_restriction"))
        body["answers"][key] = malformed
    result = await backend(SyntheticTransport(mutate)).observe(snapshot())
    assert result.reason_code == "jev_input_response_invalid"


@pytest.mark.asyncio
async def test_ambiguous_referent_or_uncertain_predicate_stays_unknown():
    for name in ("referent", "speech_restriction"):
        def mutate(body):
            key = next(k for k in body["answers"] if k.endswith(name))
            answer = body["answers"][key]
            if name == "referent":
                answer.update(choice="ambiguous", probabilities={k: float(k == "ambiguous")
                                                                 for k in answer["probabilities"]})
            else:
                answer["noul"] = 0.5
        result = await backend(SyntheticTransport(mutate)).observe(snapshot())
        assert result.status == InputDecisionStatus.UNKNOWN
        assert result.unresolved_items


@pytest.mark.asyncio
async def test_snapshot_revoked_while_waiting_is_stale():
    current = True
    def mutate(_body):
        nonlocal current
        current = False
    result = await backend(SyntheticTransport(mutate), snapshot_is_current=lambda _: current).observe(snapshot())
    assert result.status == InputDecisionStatus.STALE


@pytest.mark.asyncio
async def test_http_failure_budget_and_cancellation_are_not_retries():
    transport = SyntheticTransport(status=429)
    adapter = backend(transport)
    assert (await adapter.observe(snapshot())).reason_code == "jev_input_rate_limited"
    assert (await adapter.observe(snapshot())).reason_code == "jev_input_budget_exhausted"
    assert len(transport.calls) == 1
    started = asyncio.Event()
    async def blocked(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()
    task = asyncio.create_task(backend(blocked).observe(snapshot()))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("model", "jev-latest"), ("model", "jev-1.12.0"), ("answers", []),
    ("usage", {"input_tokens": True, "output_tokens": 2}),
    ("usage", {"input_tokens": -1, "output_tokens": 2}),
    ("usage", {"input_tokens": 100}),
])
async def test_envelope_and_usage_are_exact(field, value):
    result = await backend(SyntheticTransport(lambda body: body.update({field: value}))).observe(snapshot())
    assert result.status == InputDecisionStatus.INVALID
    assert result.input_tokens is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"choice": "invented"}, {"confidence": 0.9}, {"confidence": True},
    {"probabilities": {"none": 0.0, "ambiguous": 0.0, "photo-1": 0.9}},
    {"probabilities": {"none": 1.0, "ambiguous": 0.0, "photo-1": 0.0}},
    {"probabilities": {"none": 0.0, "ambiguous": 0.0, "photo-1": 1.0, "extra": 0.0}},
])
async def test_choice_identity_distribution_and_statistic_are_validated(change):
    def mutate(body):
        body["answers"][next(k for k in body["answers"] if k.endswith("referent"))].update(change)
    result = await backend(SyntheticTransport(mutate)).observe(snapshot())
    assert result.reason_code == "jev_input_response_invalid"


@pytest.mark.asyncio
async def test_duplicate_json_keys_and_oversized_response_are_invalid():
    for body in (b'{"model":"jev-1.13.0","model":"jev-1.13.0"}', b"x" * 65537):
        async def transport(*_args, **_kwargs):
            return JevHttpResponse(200, body)
        assert (await backend(transport).observe(snapshot())).status == InputDecisionStatus.INVALID


@pytest.mark.asyncio
async def test_request_size_and_invalid_snapshot_do_not_call_transport():
    transport = SyntheticTransport()
    snap = snapshot("雨" * 4096)
    result = await backend(transport).observe(snap)
    assert result.reason_code == "jev_input_request_too_large"
    assert not transport.calls
    result = await backend(transport).observe(replace(snapshot(), reliable_inputs=[]))
    assert result.reason_code == "jev_input_snapshot_invalid"
    assert not transport.calls


@pytest.mark.asyncio
async def test_concurrent_calls_share_one_atomic_budget():
    started, release = asyncio.Event(), asyncio.Event()
    synthetic = SyntheticTransport()
    async def transport(*args, **kwargs):
        started.set()
        await release.wait()
        return await synthetic(*args, **kwargs)
    adapter = backend(transport)
    first = asyncio.create_task(adapter.observe(snapshot()))
    await asyncio.wait_for(started.wait(), 1)
    second = await adapter.observe(snapshot())
    release.set()
    assert second.reason_code == "jev_input_budget_exhausted"
    assert (await first).status == InputDecisionStatus.OBSERVED
    assert len(synthetic.calls) == 1


@pytest.mark.asyncio
async def test_timeout_consumes_budget_and_sanitizes_exception_text(caplog, capsys):
    cancelled = asyncio.Event()
    async def transport(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    adapter = backend(transport, timeout_seconds=0.01)
    assert (await adapter.observe(snapshot())).reason_code == "jev_input_timeout"
    assert cancelled.is_set()
    assert (await adapter.observe(snapshot())).reason_code == "jev_input_budget_exhausted"
    async def failing(*args, **kwargs):
        raise RuntimeError("synthetic-private-provider-data")
    result = await backend(failing).observe(snapshot())
    assert result.reason_code == "jev_input_transport_error"
    assert "synthetic-private-provider-data" not in repr(result) + caplog.text + str(capsys.readouterr())


@pytest.mark.asyncio
async def test_known_stale_snapshot_never_calls_transport():
    transport = SyntheticTransport()
    result = await backend(transport, snapshot_is_current=lambda _: False).observe(snapshot())
    assert result.status == InputDecisionStatus.STALE
    assert not transport.calls


@pytest.mark.parametrize("kwargs", [
    {"model": "jev-latest"}, {"model": "other"}, {"request_limit": True},
    {"request_limit": 101}, {"request_limit": -1}, {"timeout_seconds": float("inf")},
    {"calibration_ref": "invalid reference"},
])
def test_invalid_configuration_is_rejected_before_any_transport(kwargs):
    with pytest.raises(ValueError, match="^jev_input_configuration_invalid$"):
        JevInputDecisionBackend(**({"transport": SyntheticTransport(), "model": MODEL} | kwargs))
