"""The input adapter uses the real injected HTTP seam without network or credentials."""
import json

import httpx
import pytest
from pydantic import SecretStr

from mira.adapters.review.jev_input import JevInputDecisionBackend
from mira.adapters.review.jev_support.http import HttpxJevTransport, SYSTEMONE_URL
from mira.application.decision_contracts import InputDecisionStatus
from tests.contracts.test_decision_contracts import snapshot
from tests.contracts.test_jev_review_http import Chunks


@pytest.mark.asyncio
async def test_input_uses_real_http_seam_with_fixed_origin_and_distinct_primitives():
    calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url) == SYSTEMONE_URL
        assert request.headers["authorization"] == "Bearer synthetic-not-a-key"
        payload = json.loads(request.content)
        answers = {}
        for key, question in payload["questions"].items():
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.0 if key.endswith("capture_restriction") else 1.0}
            else:
                answers[key] = {"type": "choice", "choice": "photo-1", "confidence": 1.0,
                    "probabilities": {option: float(option == "photo-1") for option in question["criteria"]}}
        body = json.dumps({"model": payload["model"], "answers": answers,
                           "usage": {"input_tokens": 80, "output_tokens": 30}}).encode()
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=Chunks((body,)))
    transport = HttpxJevTransport(SecretStr("synthetic-not-a-key"), transport=httpx.MockTransport(handler))
    adapter = JevInputDecisionBackend(transport=transport, model="jev-1.13.0", request_limit=1,
                                     calibration_ref="synthetic-test-only")
    result = await adapter.observe(snapshot())
    assert result.status == InputDecisionStatus.OBSERVED
    assert len(calls) == 1
    assert "synthetic-not-a-key" not in repr(result)


@pytest.mark.asyncio
async def test_input_http_error_does_not_read_private_body_or_follow_redirect():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={"location": "https://other.invalid/"},
                              stream=Chunks((b"synthetic-private",)))
    transport = HttpxJevTransport(SecretStr("synthetic"), transport=httpx.MockTransport(handler))
    adapter = JevInputDecisionBackend(transport=transport, model="jev-1.13.0", request_limit=1)
    result = await adapter.observe(snapshot())
    assert result.reason_code == "jev_input_http_error"
    assert len(calls) == 1
    assert "synthetic-private" not in repr(result)
