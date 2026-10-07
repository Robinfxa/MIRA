"""Configured request limits cross the real HTTPX and story/Actor seams offline."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from mira.adapters.journal.memory import MemoryEventJournal
from mira.adapters.review.jev import JevTransportError
from mira.adapters.review.jev_support.http import HttpxJevTransport
from mira.application.actor_story import SessionCharacterRuntime
from mira.application.contracts import CandidateRange, EffectProposal
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.application.story import StoryRuntime
from mira.bootstrap.character_assets import renderer_readiness
from mira.bootstrap.character_story import builtin_definition
from mira.bootstrap.development_review import create_development_review_providers
from mira.domain.models import EffectKind, Receipt, SessionState

ROOT = Path(__file__).resolve().parents[2]


class BytesStream(httpx.AsyncByteStream):
    def __init__(self, value):
        self.value = value

    async def __aiter__(self):
        yield self.value


def response(value=b"{}"):
    return httpx.Response(200, headers={"content-type": "application/json"},
                          stream=BytesStream(value))


def payload_at(size):
    prefix = b'{"synthetic":"'
    suffix = b'"}'
    available = size - len(prefix) - len(suffix)
    return prefix + "🌧".encode() * (available // 4) + b"x" * (available % 4) + suffix


@pytest.mark.asyncio
@pytest.mark.parametrize(("limit", "size", "allowed"), [
    (32768, 32768, True), (32768, 32769, False),
    (65536, 32768, True), (65536, 32769, True),
    (65536, 65536, True), (65536, 65537, False),
    (131072, 131072, True), (131072, 131073, False),
])
async def test_transport_enforces_its_exact_configured_utf8_limit(limit, size, allowed):
    sent = []

    def handler(request):
        sent.append(request.content)
        return response()

    transport = HttpxJevTransport(SecretStr("synthetic-only"),
        transport=httpx.MockTransport(handler), max_request_bytes=limit)
    payload = payload_at(size)
    assert len(payload) == size and "🌧" in json.loads(payload)["synthetic"]
    if allowed:
        assert (await transport(payload, timeout_seconds=1, max_response_bytes=64)).status_code == 200
        assert sent == [payload]
    else:
        with pytest.raises(JevTransportError, match="^jev_request_invalid$"):
            await transport(payload, timeout_seconds=1, max_response_bytes=64)
        assert sent == []


@pytest.mark.asyncio
async def test_legacy_transport_default_remains_32_kib():
    sent = []
    transport = HttpxJevTransport(SecretStr("synthetic-only"),
        transport=httpx.MockTransport(lambda request: sent.append(request.content) or response()))
    await transport(payload_at(32768), timeout_seconds=1, max_response_bytes=64)
    with pytest.raises(JevTransportError, match="^jev_request_invalid$"):
        await transport(payload_at(32769), timeout_seconds=1, max_response_bytes=64)
    assert list(map(len, sent)) == [32768]


@pytest.mark.parametrize("limit", [True, False, None, "65536", 65536.0,
    float("nan"), float("inf"), -1, 0, 1023, 131073])
def test_transport_rejects_invalid_or_above_global_limit_before_io(limit):
    with pytest.raises(ValueError, match="^jev_request_limit_invalid$"):
        HttpxJevTransport(SecretStr("synthetic-only"), max_request_bytes=limit)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["{}", bytearray(b"{}"), memoryview(b"{}"), None])
async def test_transport_rejects_nonbytes_without_dispatch(payload):
    sent = []
    transport = HttpxJevTransport(SecretStr("synthetic-only"), max_request_bytes=65536,
        transport=httpx.MockTransport(lambda request: sent.append(request) or response()))
    with pytest.raises(JevTransportError, match="^jev_request_invalid$"):
        await transport(payload, timeout_seconds=1, max_response_bytes=64)
    assert sent == []


class Generation:
    def __init__(self, prior_turns=0):
        self.prior_turns = prior_turns
        self.calls = 0

    async def generate(self, context):
        self.calls += 1
        if len(context.user_inputs) <= self.prior_turns:
            yield CandidateRange((EffectProposal(EffectKind.SUBTITLE,
                "这是用于离线测试的普通聊天回复。" * 4),), "synthetic-prior-chat")
        else:
            yield CandidateRange((EffectProposal(EffectKind.SUBTITLE, "可以看看这张原创海岸插画。"),
                EffectProposal(EffectKind.MEDIA, "trip_photo")), "synthetic-fixed-photo")


def providers_for(transport, **changes):
    options = dict(generation=Generation(), input_transport=transport,
        output_transport=transport, authorized=True, decision_policy=USER_DEVELOPMENT_0_6_V2,
        input_request_limit=2, output_request_limit=2, usage_profile="application",
        character_observations=True, conversation_first=True)
    options.update(changes)
    return create_development_review_providers(**options)


@pytest.mark.asyncio
@pytest.mark.parametrize(("input_limit", "output_limit"), [(32768, 65536), (16384, 32768), (12000, 70000)])
async def test_factory_binds_separate_input_output_transports_without_mutating_original(input_limit, output_limit):
    sent = []
    original = HttpxJevTransport(SecretStr("synthetic-only"),
        transport=httpx.MockTransport(lambda request: sent.append(request.content) or response()))
    providers = providers_for(original, input_max_request_bytes=input_limit,
                              output_max_request_bytes=output_limit)
    input_wire = providers.semantic_review._input_decision._transport
    output_wire = providers.review._transport
    assert input_wire is not output_wire and original is not input_wire and original is not output_wire
    for wire, limit in ((input_wire, input_limit), (output_wire, output_limit), (original, 32768)):
        before = len(sent)
        await wire(payload_at(limit), timeout_seconds=1, max_response_bytes=64)
        with pytest.raises(JevTransportError, match="^jev_request_invalid$"):
            await wire(payload_at(limit + 1), timeout_seconds=1, max_response_bytes=64)
        assert len(sent) == before + 1 and len(sent[-1]) == limit
    assert providers.semantic_review._input_decision._requests_remaining == 2
    assert providers.review._requests_remaining == 2
    assert providers.review._decision_policy is USER_DEVELOPMENT_0_6_V2


def test_factory_keeps_injected_non_http_transport_and_existing_default_limits():
    async def synthetic(_payload, **_kwargs):
        raise AssertionError("inert factory must not call review")

    providers = providers_for(synthetic, usage_profile="probe")
    assert providers.semantic_review._input_decision._transport is synthetic
    assert providers.review._transport is synthetic
    assert providers.semantic_review._input_decision._max_request_bytes == 16384
    assert providers.review._max_request_bytes == 32768


def test_factory_does_not_replace_custom_http_subclass_interface():
    class CustomHTTP(HttpxJevTransport):
        async def __call__(self, _payload, **_kwargs):
            raise AssertionError("custom caller owns this transport")

    custom = CustomHTTP(SecretStr("synthetic-only"))
    providers = providers_for(custom)
    assert providers.semantic_review._input_decision._transport is custom
    assert providers.review._transport is custom


class ReviewHTTP:
    """Synthetic server response bytes; every request traverses HttpxJevTransport."""
    def __init__(self, mode="allow"):
        self.mode = mode
        self.calls = []

    def __call__(self, request):
        raw = request.content
        body = json.loads(raw)
        output = "contract" in body["state"]
        self.calls.append(("output" if output else "input", raw))
        if output and self.mode == "malformed":
            return response(b"{bad-json")
        if output and self.mode == "oversized":
            return response(b" " * 65537)
        answers = {}
        for key, question in body["questions"].items():
            suffix = key.rsplit(":", 1)[-1]
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": float(suffix in ("display_request", "referent_required"))}
            else:
                choice = self.mode if output and self.mode in ("reject", "unknown") else (
                    "allow" if output else "authored.trip_photo")
                assert choice in question["criteria"]
                answers[key] = {"type": "choice", "choice": choice, "confidence": 1.0,
                    "probabilities": {option: float(option == choice) for option in question["criteria"]}}
        return response(json.dumps({"model": "jev-1.13.0", "answers": answers,
            "usage": {"input_tokens": 10, "output_tokens": 10}}).encode())


@pytest.mark.asyncio
@pytest.mark.parametrize(("output_limit", "mode", "media_expected", "output_dispatched"), [
    (None, "allow", True, True), (65536, "allow", True, True),
    (1024, "allow", False, False),
    (65536, "reject", False, True), (65536, "unknown", False, True),
    (65536, "malformed", False, True), (65536, "oversized", False, True),
])
async def test_five_turn_story_photo_uses_real_http_bound_and_preserves_fail_closed_controls(
        output_limit, mode, media_expected, output_dispatched):
    handler = ReviewHTTP(mode)
    transport = HttpxJevTransport(SecretStr("synthetic-only"), transport=httpx.MockTransport(handler))
    generation = Generation(prior_turns=5)
    providers = providers_for(transport, generation=generation, output_max_request_bytes=output_limit)
    readiness = renderer_readiness("code-native-review", web_root=ROOT / "apps/web")
    character = SessionCharacterRuntime(StoryRuntime(builtin_definition(), "synthetic-only-scope"), readiness)
    actor = SessionActor(SessionState(str(uuid4()), str(uuid4())), generation, providers.review,
        MemoryEventJournal(200), RuntimeLimits(4, 9, 100),
        semantic_review=providers.semantic_review, decision_owner=providers.decision_owner,
        visual_readiness=readiness, character_runtime=character)
    try:
        for turn in range(1, 6):
            await actor.submit(request_id=str(uuid4()), activity_seq=turn, cutoff=turn - 1,
                               text="这是用于离线测试的普通聊天输入。" * 2)
            async with asyncio.timeout(4):
                await asyncio.gather(*tuple(actor._tasks))
            previous = await actor.snapshot()
            assert previous.sealed and previous.last_error is None
            effect, = previous.active_grants
            await actor.receipt(Receipt(effect.id, effect.digest, effect.output_epoch, effect.activity_seq, turn))
        assert handler.calls == [], "ordinary chat must not add review requests"
        await actor.submit(request_id=str(uuid4()), activity_seq=6, cutoff=5,
                           text="请展示内置的原创海岸灯塔插画。")
        async with asyncio.timeout(4):
            await asyncio.gather(*tuple(actor._tasks))
        state = await actor.snapshot()
        assert state.sealed and state.last_error is None
        kinds = [effect.kind for effect in state.active_grants]
        assert EffectKind.SUBTITLE in kinds
        assert (EffectKind.MEDIA in kinds) is media_expected
        assert generation.calls == 6
        assert [track for track, _raw in handler.calls] == (["input", "output"] if output_dispatched else ["input"])
        # Current ready chapter vocabulary is explicit in the author policy;
        # ordinary chat still emitted no review, and no chapter is granted here.
        input_state = json.loads(handler.calls[0][1])['state']
        chapter_controls = [row for row in input_state['author_policy']['allowed_controls']
                            if row['value'].startswith('xiahe_')]
        assert chapter_controls == [
            {'kind': 'scene', 'value': 'xiahe_recognition'},
            {'kind': 'scene', 'value': 'xiahe_gift_offer'},
            {'kind': 'scene', 'value': 'xiahe_photo_handover'},
        ]
        assert len(handler.calls[0][1]) == 13832
        if output_dispatched:
            # Same canon/persona metadata plus 77 bytes for the explicit stranger
            # speaker contract. No role history is released by ordinary dialogue.
            # HTTP caps and reject/unknown/oversized/receipt branches are unchanged.
            assert len(handler.calls[1][1]) == 34725
            state_view = json.loads(handler.calls[1][1])['state']['context']
            assert 'chapter' not in state_view['character_story']
            assert state_view['first_person_dialogue']['speaker_contract'] == {
                'frame': 'unrecognized_visitor', 'recognition': 'inactive'}
            continuity = state_view['first_person_dialogue']['self_continuity']
            assert continuity['memory_evidence'] == 'not_attached'
            assert continuity['conversation_recall'] == 'not_attached'
            assert len(json.dumps(continuity, separators=(',', ':')).encode()) <= 256
        if media_expected:
            media = next(effect for effect in state.active_grants if effect.kind is EffectKind.MEDIA)
            assert media.value == "trip_photo"
            # A grant is not a presentation fact until its actual software receipt.
            for sequence, effect in enumerate(state.active_grants, 6):
                await actor.receipt(Receipt(effect.id, effect.digest, effect.output_epoch, effect.activity_seq, sequence))
            assert any(effect.kind is EffectKind.MEDIA for effect in (await actor.snapshot()).presented_effects)
    finally:
        await actor.close()
