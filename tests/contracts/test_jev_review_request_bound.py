"""Bounded 32 KiB output-review requests, verified through backend and ASGI seams.

All transports in this module are synthetic and in-process. These tests do not prove
provider access, account authorization, human presentation, or physical audio behavior.
"""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mira.adapters.review import jev as jev_module
from mira.adapters.review.jev import (
    MAX_REQUEST_BYTES,
    OUTPUT_QUESTION_SET_V3, OUTPUT_QUESTION_SET_INTERACTION,
    QUESTION_SET_VERSION,
    JevHttpResponse,
    JevReviewBackend,
    JevReviewContract,
    JevTransportError,
    candidate_digest,
    context_digest,
)
from mira.adapters.review.jev_input import MAX_REQUEST_BYTES as INPUT_MAX_REQUEST_BYTES
from mira.adapters.review.jev_support.http import HttpxJevTransport
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V1
from mira.bootstrap.development_app import create_development_app
from mira.config.settings import Settings
from mira.domain.models import EffectKind
from tests.contracts.test_codex_generation import SyntheticTransport, agent, event, terminal
from tests.contracts.test_development_app_entry import public_runtime, wait_ready
from tests.contracts.test_development_review_composition import SyntheticJevTransport

MODEL = "jev-1.13.0"


class _ResponseChunks(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"{}"


def _output_context(padding_bytes: int = 0) -> GenerationContext:
    """Keep input count/JSON shape fixed while adding exact UTF-8 bytes."""
    if not 0 <= padding_bytes <= 32 * 4095 * 4:
        raise ValueError("synthetic input size is outside the contract")
    values = ["x"] * 32
    remainder = padding_bytes
    for index in range(32):
        capacity = 4095
        rain = min(remainder // 4, capacity)
        values[index] += "🌧" * rain
        remainder -= rain * 4
        capacity -= rain
        ascii_padding = min(remainder, capacity)
        values[index] += "x" * ascii_padding
        remainder -= ascii_padding
    assert remainder == 0 and all(len(value) <= 4096 for value in values)
    return GenerationContext("request", tuple(values), (), 1)


def _output_candidate() -> CandidateRange:
    return CandidateRange((EffectProposal(EffectKind.SUBTITLE, "synthetic response"),),
                          "request-bound-probe")


def _output_contract(context: GenerationContext, candidate: CandidateRange) -> JevReviewContract:
    return JevReviewContract(
        contract_id="bound-contract", policy_revision=QUESTION_SET_VERSION,
        context_digest=context_digest(context), candidate_digest=candidate_digest(candidate),
        effective_constraints=(), response_obligations=("Answer the synthetic request.",),
        character_facts=("Fictional adult character.",), synthetic=True,
    )


class CapturingOutputTransport:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    async def __call__(self, payload: bytes, *, timeout_seconds: float,
                       max_response_bytes: int) -> JevHttpResponse:
        self.payloads.append(payload)
        request = json.loads(payload)
        answers = {
            key: {"type": "choice", "choice": "allow", "confidence": 1.0,
                  "probabilities": {"allow": 1.0, "reject": 0.0, "unknown": 0.0}}
            for key in request["questions"]
        }
        body = json.dumps({"model": MODEL, "answers": answers,
                           "usage": {"input_tokens": 2, "output_tokens": 1}},
                          separators=(",", ":")).encode("utf-8")
        return JevHttpResponse(200, body)


async def _measure_backend_payload(context: GenerationContext) -> bytes:
    transport = CapturingOutputTransport()
    backend = JevReviewBackend(
        transport=transport, model=MODEL,
        contract_resolver=lambda current, candidate: _output_contract(current, candidate),
        decision_policy=USER_DEVELOPMENT_0_6_V1, request_limit=1, timeout_seconds=1,
    )
    await backend.review_detailed(context, _output_candidate())
    assert len(transport.payloads) == 1
    return transport.payloads[0]


def _context_at_payload_size(base_size: int, target_size: int) -> GenerationContext:
    return _output_context(target_size - base_size)


@pytest.mark.asyncio
@pytest.mark.parametrize(("target_bytes", "should_send"), [(32768, True), (32769, False)])
async def test_output_backend_enforces_exact_utf8_serialized_byte_limit(target_bytes, should_send):
    """The output adapter measures the final canonical UTF-8 payload, not characters."""
    baseline = await _measure_backend_payload(_output_context())
    target_context = _context_at_payload_size(len(baseline), target_bytes)
    transport = CapturingOutputTransport()
    backend = JevReviewBackend(
        transport=transport, model=MODEL,
        contract_resolver=lambda current, candidate: _output_contract(current, candidate),
        decision_policy=USER_DEVELOPMENT_0_6_V1, request_limit=1, timeout_seconds=1,
    )

    result = await backend.review_detailed(target_context, _output_candidate())

    if should_send:
        assert len(transport.payloads) == 1
        assert len(transport.payloads[0]) == target_bytes
        assert result.observation.reason_code != "jev_request_too_large"
        sent = json.loads(transport.payloads[0])
        assert sent["state"]["context"]["user_inputs"] == list(target_context.user_inputs)
        assert any("🌧" in value for value in target_context.user_inputs)
        assert sent["state"]["contract"]["context_digest"] == context_digest(target_context)
    else:
        assert not transport.payloads
        assert result.observation.reason_code == "jev_request_too_large"
        assert INPUT_MAX_REQUEST_BYTES == 16 * 1024


@pytest.mark.asyncio
async def test_http_transport_uses_utf8_bytes_for_exact_limit_and_overlimit_fail_closed():
    received: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request.content)
        return httpx.Response(200, headers={"content-type": "application/json"},
                              stream=_ResponseChunks())

    transport = HttpxJevTransport(SecretStr("synthetic-key"),
                                  transport=httpx.MockTransport(handler))
    exact = ("🌧" * 8192).encode("utf-8")
    one_over = ("🌧" * 8192 + "x").encode("utf-8")
    assert len("🌧" * 8192) == 8192 and len(exact) == 32768 and len(one_over) == 32769

    result = await transport(exact, timeout_seconds=1, max_response_bytes=64 * 1024)

    assert result.status_code == 200 and received == [exact]
    with pytest.raises(JevTransportError, match="^jev_request_invalid$"):
        await transport(one_over, timeout_seconds=1, max_response_bytes=64 * 1024)
    assert received == [exact], "the over-limit request must fail before opening HTTP"


class CapturingAsgiJevTransport(SyntheticJevTransport):
    def __init__(self) -> None:
        super().__init__()
        self.payloads: list[bytes] = []

    async def __call__(self, payload: bytes, *, timeout_seconds: float,
                       max_response_bytes: int) -> JevHttpResponse:
        self.payloads.append(payload)
        return await super().__call__(payload, timeout_seconds=timeout_seconds,
                                      max_response_bytes=max_response_bytes)


def _question_binding(request: dict, *, question_set_revision: str) -> str:
    data = {"state": request["state"], "model": request["model"],
            "question_set": question_set_revision}
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_four_round_actual_asgi_keeps_full_context_contract_and_independent_budgets():
    input_transport, output_transport = CapturingAsgiJevTransport(), CapturingAsgiJevTransport()
    codex_transports: list[SyntheticTransport] = []

    async def codex_factory(_runtime, _limits):
        round_number = len(codex_transports) + 1
        output = {
            "effects": [
                {"kind": "subtitle", "value": f"雨声伴随第{round_number}轮。"},
                {"kind": "pose", "value": "face_warm"},
            ],
        }
        transport = SyntheticTransport(events=[
            event("item/completed", item=agent(json.dumps(output, ensure_ascii=False))),
            terminal(),
        ])
        codex_transports.append(transport)
        return transport

    app = create_development_app(
        runtime=public_runtime(), settings=Settings(), route_kind="public",
        input_transport=input_transport, output_transport=output_transport,
        authorized=True, decision_policy=USER_DEVELOPMENT_0_6_V1,
        codex_request_limit=4, session_turn_limit=4,
        input_request_limit=8, output_request_limit=8,
        input_timeout_seconds=2, output_timeout_seconds=2,
        codex_transport_factory=codex_factory,
    )

    with TestClient(app) as client:
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())})
        assert created.status_code == 201
        path = "/api/v1/sessions/" + created.json()["session"]["session_id"]
        headers = {"X-Mira-Session-Token": created.json()["session_token"]}
        next_presentation_seq = 1

        for turn in range(1, 5):
            response = client.post(path + "/inputs", headers=headers, json={
                "request_id": str(uuid4()), "activity_seq": turn,
                "presentation_cutoff": next_presentation_seq - 1,
                "text": f"请用一句新话陪我听雨，第{turn}轮。",
            })
            assert response.status_code == 202
            state = wait_ready(client, path, headers)
            assert state["phase"] == "ready" and len(state["active_grants"]) == 2, (
                state.get("last_error"), state, client.get(path + "/events", headers=headers).json(),
                [(len(payload), request.get("state", {}).get("contract", {}).get("scope"))
                 for payload, (request, _timeout, _maximum) in zip(
                     output_transport.payloads, output_transport.calls)],
                [len(payload) for payload in input_transport.payloads],
            )
            for effect in state["active_grants"]:
                receipt = client.post(path + "/receipts", headers=headers, json={
                    "effect_id": effect["id"], "digest": effect["digest"],
                    "output_epoch": effect["output_epoch"],
                    "activity_seq": effect["activity_seq"],
                    "presentation_seq": next_presentation_seq,
                })
                assert receipt.status_code == 200
                next_presentation_seq += 1

        assert len(codex_transports) == 4
        assert len(input_transport.calls) == len(input_transport.payloads) == 8
        assert len(output_transport.calls) == len(output_transport.payloads) == 8
        assert all(item.closed for item in codex_transports)

    # Input JEV keeps its separate 16 KiB guard. Output budget, response ceiling and
    # complete contract evidence remain unchanged; this production assembly explicitly
    # selects v2 while the historical evaluation harness retains the v1 default.
    assert INPUT_MAX_REQUEST_BYTES == 16 * 1024
    assert MAX_REQUEST_BYTES == 32 * 1024
    for transport in (input_transport, output_transport):
        assert all(max_response_bytes == 64 * 1024
                   for _request, _timeout, max_response_bytes in transport.calls)
    for turn in range(4):
        input_request = input_transport.calls[turn * 2][0]
        assert input_request["state"]["context"]["user_inputs"][-1].endswith(f"第{turn + 1}轮。")
        expected_presented = (turn) * 2
        assert len(input_request["state"]["presentation_facts"]) >= expected_presented

    for index, (payload, (request, _timeout, _maximum_response)) in enumerate(
            zip(output_transport.payloads, output_transport.calls)):
        assert len(payload) <= 32 * 1024
        state = request["state"]
        context = state["context"]
        contract = state["contract"]
        assert set(context) >= {
            "user_text", "user_inputs", "presented_effects", "accepted_prefix", "output_epoch",
        }
        assert contract["snapshot"] is not None and contract["input_observation"] is not None
        assert contract["policy_revision"] == OUTPUT_QUESTION_SET_INTERACTION
        assert contract["snapshot"]["context"] == context
        assert contract["basis_snapshot_digest"] and contract["response_contract_digest"]
        assert contract["context_digest"] == jev_module._digest(context)
        assert contract["candidate_digest"] == jev_module._digest(state["candidate"])
        binding = _question_binding(request, question_set_revision=OUTPUT_QUESTION_SET_INTERACTION)
        assert all(key.split(":")[1] == binding for key in request["questions"])
        # Stage and seal both retain the same complete live input history per turn.
        assert len(context["user_inputs"]) == (index // 2) + 1
        assert len(context["presented_effects"]) == (index // 2) * 2
