"""Offline contract coverage for provider-direct Responses generation."""
import asyncio
import json
import re

import httpx
import pytest
from pydantic import SecretStr

from mira.adapters.generation.direct_codex_responses import (
    DirectCodexResponsesGenerationBackend,
    DirectResponsesError,
    DirectResponsesLimits,
    ResponsesRoute,
)
from mira.application.contracts import GenerationContext
from mira.domain.models import EffectKind

TOKEN = "synthetic-oauth-token-not-a-real-credential"
CONTEXT = GenerationContext("请陪我听雨。", ("请陪我听雨。",), (), 7)
OUTPUT = {"effects": [
    {"kind": "speech", "value": "我们一起听雨。"},
    {"kind": "subtitle", "value": "雨声很轻。"},
    {"kind": "pose", "value": "look_at_rain"},
]}
JSON_OUTPUT = json.dumps(OUTPUT, ensure_ascii=False)


class CredentialSource:
    def __init__(self, *, account_id="acct-synthetic", residency="us"):
        self.account_id = account_id
        self.residency = residency
        self.calls = 0

    async def get_credentials(self):
        self.calls += 1
        return type("Credentials", (), {
            "access_token": SecretStr(TOKEN),
            "account_id": self.account_id,
            "residency": self.residency,
        })()


class ByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


class BlockingStream(httpx.AsyncByteStream):
    def __init__(self, prefix):
        self.prefix = prefix
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        yield self.prefix
        self.entered.set()
        await self.release.wait()
        yield b"event: response.completed\ndata: {\"type\":\"response.completed\",\"response\":{\"status\":\"completed\",\"output\":null}}\n\n"

    async def aclose(self):
        self.closed = True


def event(kind, obj=None, *, event_name=None):
    data = json.dumps(obj if obj is not None else {"type": kind}, ensure_ascii=False)
    name = event_name or kind
    return f"event: {name}\ndata: {data}\n\n".encode("utf-8")


def item_done(text=JSON_OUTPUT, *, item_type="message", item_id="msg-1", index=0):
    item = {"id": item_id, "type": item_type, "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}
    if item_type != "message":
        item = {"id": item_id, "type": item_type, "status": "completed",
                "call_id": "call-1", "name": "do_not_run"}
    return event("response.output_item.done", {
        "type": "response.output_item.done", "output_index": index, "item": item,
        "benign_future_metadata": {"shape": "ignored"},
    })


def completed(*, output=None):
    return event("response.completed", {
        "type": "response.completed",
        "response": {"id": "resp-1", "status": "completed", "output": output},
    })


def snapshot_message(text=JSON_OUTPUT, *, item_id="msg-1"):
    return {"id": item_id, "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text}]}


def route_url(route):
    return ("https://chatgpt.com/backend-api/codex/responses"
            if route is ResponsesRoute.CHATGPT_SUBSCRIPTION
            else "https://api.openai.com/v1/responses")


def backend(handler, *, route=ResponsesRoute.CHATGPT_SUBSCRIPTION, model="gpt-6-luna",
            source=None, admitted=True, request_limit=1, limits=None, native_character_tools=True):
    requests = []

    async def inspect(request):
        requests.append(request)
        return await handler(request)

    transport = httpx.MockTransport(inspect)
    source = source or CredentialSource()
    instance = DirectCodexResponsesGenerationBackend(
        route=route, model=model, credential_source=source, admitted=admitted,
        request_limit=request_limit, limits=limits, transport=transport, native_character_tools=native_character_tools,
    )
    return instance, source, requests


async def collect(instance, context=CONTEXT):
    return [candidate async for candidate in instance.generate(context)]


def response(body, *, status=200, headers=None, stream=None):
    if stream is not None:
        return httpx.Response(status, headers=headers or {"content-type": "text/event-stream"},
                              stream=stream)
    return httpx.Response(status, headers=headers or {"content-type": "text/event-stream"},
                          stream=ByteStream([body]))


@pytest.mark.asyncio
async def test_default_off_fails_before_credentials_or_http():
    async def handle(_):
        raise AssertionError("HTTP must not start")

    instance, source, requests = backend(handle, admitted=False)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(instance)
    assert raised.value.code == "blocked"
    assert raised.value.stage == "admission"
    assert source.calls == 0
    assert requests == []


def test_model_and_route_are_explicit_and_fixed():
    with pytest.raises(TypeError):
        DirectCodexResponsesGenerationBackend(credential_source=CredentialSource())
    with pytest.raises((TypeError, ValueError, DirectResponsesError)):
        DirectCodexResponsesGenerationBackend(
            route="https://evil.example/responses", model="gpt-6-luna",
            credential_source=CredentialSource(), admitted=True, request_limit=1,
        )
    with pytest.raises((TypeError, ValueError, DirectResponsesError)):
        DirectCodexResponsesGenerationBackend(
            route=ResponsesRoute.OPENAI_API, model="\r\nAuthorization: bad",
            credential_source=CredentialSource(), admitted=True, request_limit=1,
        )


def test_bounded_model_identifier_allows_common_api_model_ids():
    for model in ("gpt-6-luna", "ft:gpt-4o:org:model-id", "provider/model-v2",
                  "m" + "a" * 199):
        DirectCodexResponsesGenerationBackend(
            route=ResponsesRoute.OPENAI_API, model=model,
            credential_source=CredentialSource(), admitted=True, request_limit=1,
        )
    for model in ("model with spaces", "model\nforged", "m" + "a" * 200):
        with pytest.raises(ValueError):
            DirectCodexResponsesGenerationBackend(
                route=ResponsesRoute.OPENAI_API, model=model,
                credential_source=CredentialSource(), admitted=True, request_limit=1,
            )


@pytest.mark.asyncio
async def test_subscription_headers_and_secret_are_route_bound():
    async def handle(request):
        assert str(request.url) == route_url(ResponsesRoute.CHATGPT_SUBSCRIPTION)
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert request.headers["chatgpt-account-id"] == "acct-synthetic"
        assert request.headers["x-openai-internal-codex-residency"] == "us"
        assert request.headers["originator"].lower() == "mira"
        assert "hermes" not in request.headers["user-agent"].lower()
        return response(item_done() + completed(output=None))

    instance, _, _ = backend(handle)
    result = await collect(instance)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_api_route_omits_subscription_metadata():
    async def handle(request):
        assert str(request.url) == route_url(ResponsesRoute.OPENAI_API)
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert "chatgpt-account-id" not in request.headers
        assert "x-openai-internal-codex-residency" not in request.headers
        return response(item_done() + completed(output=None))

    instance, _, _ = backend(handle, route=ResponsesRoute.OPENAI_API, model="gpt-4.1-mini")
    assert len(await collect(instance)) == 1


@pytest.mark.asyncio
async def test_request_uses_responses_messages_without_tools_or_schema_format():
    async def handle(request):
        body = json.loads(request.content)
        assert body["model"] == "gpt-6-luna"
        assert body["instructions"]
        assert body["input"] == [{"role": "user", "content": [
            {"type": "input_text", "text": body["input"][0]["content"][0]["text"]},
        ]}]
        assert "请陪我听雨。" in body["input"][0]["content"][0]["text"]
        assert body["stream"] is True
        assert body["store"] is False
        assert "tools" not in body
        assert "tool_choice" not in body
        assert "text" not in body
        return response(item_done() + completed(output=None))

    instance, _, _ = backend(handle)
    await collect(instance)


@pytest.mark.asyncio
async def test_fragmented_multiline_sse_yields_after_completed_item_and_terminal():
    item = {"type": "response.output_item.done", "output_index": 0,
            "item": {"id": "msg-1", "type": "message", "role": "assistant",
                     "status": "completed", "content": [{"type": "output_text",
                     "text": JSON_OUTPUT}]}}
    multiline = (b"event: response.output_item.done\n"
                 b"data: {\"type\":\"response.output_item.done\",\n"
                 b"data: \"output_index\":0,\"item\":"
                 + json.dumps(item["item"], ensure_ascii=False).encode()
                 + b"}\n\n")
    unknown = b"event: vendor.optional_metadata\ndata: intentionally not JSON\n\n"
    success = completed(output=None)
    all_bytes = unknown + multiline + success
    chunks = [all_bytes[index:index + 3] for index in range(0, len(all_bytes), 3)]
    stream = ByteStream(chunks)

    async def handle(_):
        return response(b"", stream=stream)

    instance, _, _ = backend(handle)
    results = await collect(instance)
    assert len(results) == 1
    assert [effect.kind for effect in results[0].effects] == [
        EffectKind.SPEECH, EffectKind.SUBTITLE, EffectKind.POSE,
    ]
    assert results[0].fixture_id.startswith("direct-codex-responses-origin:")
    assert re.fullmatch(r"direct-codex-responses-origin:[a-f0-9]{32}", results[0].fixture_id)
    assert stream.closed


@pytest.mark.asyncio
async def test_null_completed_output_uses_item_done():
    async def handle(_):
        return response(item_done() + completed(output=None))

    instance, _, _ = backend(handle)
    assert len(await collect(instance)) == 1


@pytest.mark.asyncio
async def test_done_sentinel_after_completed_is_accepted():
    async def handle(_):
        return response(item_done() + completed(output=None) + b"data: [DONE]\n\n")

    instance, _, _ = backend(handle)
    assert len(await collect(instance)) == 1


@pytest.mark.asyncio
async def test_done_sentinel_cannot_replace_completed_event():
    async def handle(_):
        return response(item_done() + b"data: [DONE]\n\n")

    instance, _, _ = backend(handle)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(instance)
    assert raised.value.code == "invalid_response"
    assert raised.value.stage == "terminal"


@pytest.mark.asyncio
async def test_event_after_done_sentinel_invalidates_success():
    async def handle(_):
        return response(item_done() + completed(output=None) + b"data: [DONE]\n\n"
                        + event("response.failed", {"type": "response.failed"}))

    instance, _, _ = backend(handle)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(instance)
    assert raised.value.code == "invalid_response"
    assert raised.value.stage == "terminal"


@pytest.mark.asyncio
async def test_nonnull_terminal_snapshot_must_match_single_streamed_message():
    reasoning = {"id": "rs-1", "type": "reasoning", "status": "completed",
                 "summary": [{"type": "summary_text", "text": "ignored privately"}],
                 "encrypted_content": "opaque"}

    async def valid(_):
        return response(item_done() + completed(output=[reasoning, snapshot_message()]))

    instance, _, _ = backend(valid)
    assert len(await collect(instance)) == 1

    delta = event("response.output_text.delta", {
        "type": "response.output_text.delta", "item_id": "msg-1",
        "output_index": 0, "content_index": 0, "delta": JSON_OUTPUT,
    })

    async def valid_delta(_):
        return response(delta + completed(output=[snapshot_message()]))

    instance, _, _ = backend(valid_delta)
    assert len(await collect(instance)) == 1

    invalid_snapshots = [
        [snapshot_message(), {"id": "call-1", "type": "function_call", "call_id": "c1",
                              "name": "do_not_run", "arguments": "{}"}],
        [snapshot_message(), snapshot_message(item_id="msg-2")],
        [snapshot_message(text=json.dumps({"effects": [{"kind": "subtitle", "value": "另一个结果"}]},
                                          ensure_ascii=False))],
        [{"id": "unknown-1", "type": "unknown_output_item"}],
        [snapshot_message(text=JSON_OUTPUT), {"id": "rs-2", "type": "reasoning",
                                             "status": "completed", "summary": "not a list"}],
    ]
    for output in invalid_snapshots:
        async def invalid(_, output=output):
            return response(item_done() + completed(output=output))

        instance, _, _ = backend(invalid)
        with pytest.raises(DirectResponsesError) as raised:
            await collect(instance)
        assert raised.value.code == "invalid_response"
        assert raised.value.stage in ("tool_forbidden", "terminal_output")

    async def snapshot_only(_):
        return response(completed(output=[snapshot_message()]))

    instance, _, _ = backend(snapshot_only)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(instance)
    assert raised.value.code == "invalid_response"


@pytest.mark.asyncio
async def test_delta_fallback_requires_terminal_success():
    delta = event("response.output_text.delta", {
        "type": "response.output_text.delta", "item_id": "msg-fallback",
        "output_index": 0, "content_index": 0, "delta": JSON_OUTPUT,
    })

    async def handle(_):
        return response(delta + completed(output=None))

    instance, _, _ = backend(handle)
    assert len(await collect(instance)) == 1


@pytest.mark.asyncio
async def test_failure_incomplete_early_eof_and_tools_never_yield():
    cases = [
        (event("response.failed", {"type": "response.failed", "response": {
            "status": "failed", "error": {"message": "secret provider details"}}}), "unavailable"),
        (event("response.incomplete", {"type": "response.incomplete", "response": {
            "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}}),
         "invalid_response"),
        (item_done(), "invalid_response"),
        (completed(output=None), "invalid_response"),
        (item_done(text="not JSON") + completed(output=None), "invalid_response"),
        (item_done(text='{"effects":[],"effects":[]}') + completed(output=None),
         "invalid_response"),
        (item_done(item_type="function_call") + completed(output=None), "invalid_response"),
    ]
    for stream, code in cases:
        async def handle(_, stream=stream):
            return response(stream)

        instance, _, _ = backend(handle)
        with pytest.raises(DirectResponsesError) as raised:
            await collect(instance)
        assert raised.value.code == code


@pytest.mark.asyncio
async def test_limits_and_provenance_are_bounded_and_local():
    too_long = b"event: vendor.metadata\ndata: " + b"x" * 1200 + b"\n\n"

    async def handle(_):
        return response(too_long)

    instance, _, _ = backend(handle, limits=DirectResponsesLimits(max_line_bytes=1024))
    with pytest.raises(DirectResponsesError) as raised:
        await collect(instance)
    assert raised.value.code == "response_limit"
    assert raised.value.stage == "sse"

    async def okay(_):
        return response(item_done() + completed(output=None))

    limited, _, _ = backend(okay, limits=DirectResponsesLimits(max_output_bytes=128))
    with pytest.raises(DirectResponsesError) as raised:
        await collect(limited)
    assert raised.value.code == "output_limit"
    assert raised.value.stage == "output_item"


@pytest.mark.asyncio
async def test_request_prompt_wire_and_event_bounds_fail_before_yield():
    async def unused(_):
        raise AssertionError("the request should be blocked locally")

    request_limited, source, requests = backend(
        unused, limits=DirectResponsesLimits(max_request_bytes=1024))
    with pytest.raises(DirectResponsesError) as raised:
        await collect(request_limited)
    assert raised.value.code == "input_limit"
    assert source.calls == 0
    assert requests == []

    prompt_limited, source, requests = backend(
        unused, limits=DirectResponsesLimits(max_prompt_bytes=1024))
    oversized_context = GenerationContext("雨" * 700, ("雨" * 700,), (), 1)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(prompt_limited, oversized_context)
    assert raised.value.code == "input_limit"
    assert source.calls == 0
    assert requests == []

    wire = b"event: vendor.metadata\n" + b"data: " + b"z" * 70 + b"\n"
    wire = b"\n".join([wire.rstrip(b"\n")] * 20) + b"\n\n"

    async def wire_handler(_):
        return response(wire)

    wire_limited, _, _ = backend(
        wire_handler, limits=DirectResponsesLimits(max_wire_bytes=1024))
    with pytest.raises(DirectResponsesError) as raised:
        await collect(wire_limited)
    assert raised.value.code == "response_limit"
    assert raised.value.stage == "sse"

    two_events = (b"event: vendor.one\ndata: opaque\n\n"
                  b"event: vendor.two\ndata: opaque\n\n")

    async def event_handler(_):
        return response(two_events)

    event_limited, _, _ = backend(
        event_handler, limits=DirectResponsesLimits(max_events=1))
    with pytest.raises(DirectResponsesError) as raised:
        await collect(event_limited)
    assert raised.value.code == "response_limit"
    assert raised.value.reason == 'event_limit'
    assert raised.value.generation_diagnostic.reason == 'event_limit'


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", [
    "text/event-stream", "Text/Event-Stream; charset=utf-8",
    'text/event-stream; charset="utf-8"',
])
async def test_valid_event_stream_media_type_parameters_are_accepted(content_type):
    async def handle(_):
        return response(item_done() + completed(output=None),
                        headers={"content-type": content_type})

    instance, _, _ = backend(handle)
    assert len(await collect(instance)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", [
    "text/event-streamx", "application/text/event-stream", "text/event-stream; broken",
    "text/event-stream; charset",
])
async def test_invalid_or_prefix_event_stream_media_type_is_rejected(content_type):
    async def handle(_):
        return response(item_done() + completed(output=None),
                        headers={"content-type": content_type})

    instance, _, _ = backend(handle)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(instance)
    assert raised.value.code == "invalid_response"
    assert raised.value.stage == "response_headers"


@pytest.mark.asyncio
async def test_status_errors_are_safe_and_never_include_body_or_switch_route():
    for status, code in ((401, "unauthenticated"), (403, "permission_denied"),
                         (429, "quota_exhausted"), (503, "unavailable")):
        requests = []

        async def handle(request, status=status):
            requests.append(str(request.url))
            return response(b"secret provider response body", status=status,
                            headers={"content-type": "application/json"})

        instance, _, _ = backend(handle)
        with pytest.raises(DirectResponsesError) as raised:
            await collect(instance)
        assert raised.value.code == code
        assert raised.value.http_status == status
        assert "secret" not in str(raised.value)
        assert requests == [route_url(ResponsesRoute.CHATGPT_SUBSCRIPTION)]


@pytest.mark.asyncio
async def test_401_does_not_switch_routes():
    visited = []

    async def handle(request):
        visited.append(str(request.url))
        return response(b"private", status=401, headers={"content-type": "application/json"})

    instance, _, _ = backend(handle)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(instance)
    assert raised.value.code == "unauthenticated"
    assert visited == [route_url(ResponsesRoute.CHATGPT_SUBSCRIPTION)]


@pytest.mark.asyncio
async def test_timeout_and_late_cancel_never_yield():
    first = item_done()
    stream = BlockingStream(first)

    async def handle(_):
        return response(b"", stream=stream)

    instance, _, _ = backend(handle)
    emitted = []

    async def consume():
        async for candidate in instance.generate(CONTEXT):
            emitted.append(candidate)

    task = asyncio.create_task(consume())
    await asyncio.wait_for(stream.entered.wait(), timeout=1)
    assert emitted == []
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert emitted == []
    assert stream.closed

    hanging_stream = BlockingStream(b"")

    async def hang(_):
        return response(b"", stream=hanging_stream)

    limits = DirectResponsesLimits(startup_seconds=1, turn_seconds=0.05)
    timed, _, _ = backend(hang, limits=limits)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(timed)
    assert raised.value.code == "timeout"
    assert raised.value.stage == "stream"
