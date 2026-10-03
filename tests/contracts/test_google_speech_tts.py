"""Synthetic Google wire contract; no real credentials, HTTP or paid inference."""
import asyncio
import base64
import json

import pytest

from mira.adapters.speech.errors import SpeechProviderError
from mira.adapters.speech.google_gemini_tts import (
    GeminiTtsOptions,
    GoogleGeminiTtsBackend,
    GoogleGeminiTtsRestTransport,
)
from tools.google_voice_smoke import TtsRequestPolicyTransport


def audio(pcm=b"\x00\x01\x02\x03", mime="audio/L16;codec=pcm;rate=24000", finish=None):
    candidate = {"content": {"parts": [{"inlineData": {
        "mimeType": mime, "data": base64.b64encode(pcm).decode(),
    }}]}}
    if finish:
        candidate["finishReason"] = finish
    return {"candidates": [candidate]}


class Transport:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []
        self.closed = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(self, *, url, body, timeout_seconds):
        self.calls.append((url, body, timeout_seconds))
        try:
            for chunk in self.chunks:
                if chunk == "WAIT":
                    self.entered.set()
                    await self.release.wait()
                elif isinstance(chunk, Exception):
                    raise chunk
                else:
                    yield chunk
        finally:
            self.closed = True


def backend(transport, **kwargs):
    return GoogleGeminiTtsBackend(GeminiTtsOptions(project_id="mira-test", voice="Kore", **kwargs), transport)


@pytest.mark.asyncio
async def test_exact_model_wire_and_contiguous_pcm():
    transport = Transport([{"usageMetadata": {}}, audio(), audio(b"\x04\x05", finish="STOP")])
    packets = [item async for item in backend(transport, style="warm").synthesize("你好", "out-1")]
    assert [(p.stream_id, p.first_sample, p.sample_rate_hz, p.pcm) for p in packets] == [
        ("out-1", 0, 24000, b"\x00\x01\x02\x03"), ("out-1", 2, 24000, b"\x04\x05")]
    url, body, timeout = transport.calls[0]
    assert url == "https://aiplatform.googleapis.com/v1/projects/mira-test/locations/global/publishers/google/models/gemini-3.8-flash-tts:streamGenerateContent?alt=sse"
    assert body == {"contents": [{"role": "user", "parts": [{"text": "你好", "speechMetadata": {"style": "warm"}}]}], "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"voice": "Kore"}}, "responseFormat": [{"audio": {"mimeType": "AUDIO_L16"}}]}}
    assert timeout > 0 and transport.closed


@pytest.mark.asyncio
async def test_official_minimal_streaming_request_omits_optional_cap_and_encoding():
    transport = Transport([audio(finish="STOP")])
    backend_minimal = GoogleGeminiTtsBackend(
        GeminiTtsOptions(project_id="mira-test", voice="Kore"),
        TtsRequestPolicyTransport(transport, "official_minimal"),
    )
    packets = [packet async for packet in backend_minimal.synthesize(
        "你好，这是一次语音连接测试。", "out-minimal",
    )]
    assert len(packets) == 1 and packets[0].sample_rate_hz == 24000
    url, body, _ = transport.calls[0]
    assert url.endswith("/locations/global/publishers/google/models/gemini-3.8-flash-tts:streamGenerateContent?alt=sse")
    assert body == {
        "contents": [{"role": "user", "parts": [{"text": "你好，这是一次语音连接测试。"}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"voice": "Kore"}},
        },
    }
    assert "maxOutputTokens" not in body["generationConfig"]
    assert "responseFormat" not in body["generationConfig"]
    assert transport.closed


@pytest.mark.parametrize("options", [{"model": "gemini-2.5-flash-preview-tts"}, {"location": "us"}, {"voice": "made-up"}, {"project_id": "x/../../oops"}])
def test_unsupported_options_fail_locally(options):
    with pytest.raises(ValueError):
        GeminiTtsOptions(**({"project_id": "mira-test", "voice": "Kore"} | options))


@pytest.mark.asyncio
@pytest.mark.parametrize("chunks,code", [
    ([audio(mime="audio/wav", finish="STOP")], "unsupported_audio"),
    ([audio(b"\x00", finish="STOP")], "invalid_audio"),
    ([audio()], "incomplete_stream"),
    ([{"candidates": [{"finishReason": "STOP"}]}], "empty_audio"),
    ([{"promptFeedback": {"blockReason": "SAFETY"}}], "blocked"),
    ([audio(finish="MAX_TOKENS")], "incomplete_stream"),
    ([{"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/l16", "data": "???"}}]}}]}], "invalid_audio"),
    ([RuntimeError("credential=TOP-SECRET")], "unavailable"),
])
async def test_bad_or_incomplete_audio_is_explicit(chunks, code):
    transport = Transport(chunks)
    with pytest.raises(SpeechProviderError) as caught:
        _ = [item async for item in backend(transport).synthesize("你好", "out-1")]
    assert caught.value.code == code
    assert "TOP-SECRET" not in str(caught.value)
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("part,expected", [
    ({"text": "synthetic-only"}, "non_audio_part"),
    ({"inlineData": {"mimeType": "audio/wav", "data": "AA=="}}, "unsupported_mime_type"),
    ({"inlineData": {"mimeType": "audio/l16;rate=16000", "data": "AA=="}}, "unsupported_mime_parameter"),
    ({"inlineData": {"mimeType": "audio/l16", "data": "%%%"}}, "invalid_base64"),
    ({"inlineData": {"mimeType": "audio/l16", "data": base64.b64encode(b"RIFF0000WAVE").decode()}}, "wav_header"),
    ({"inlineData": {"mimeType": "audio/l16", "data": base64.b64encode(b"\x00").decode()}}, "odd_pcm_bytes"),
])
async def test_audio_response_error_contains_only_safe_media_facts(part, expected):
    transport = Transport([{"candidates": [{"content": {"parts": [part]}, "finishReason": "STOP"}]}])
    with pytest.raises(SpeechProviderError) as caught:
        _ = [item async for item in backend(transport).synthesize("synthetic-only", "out-diagnostic")]
    detail = caught.value.audio_details
    assert detail.validation_reason == expected
    serialized = repr(detail)
    for secret in ("synthetic-only", "AA==", "%%%", "RIFF", "WAVE"):
        assert secret not in serialized
    assert transport.closed


@pytest.mark.asyncio
async def test_scoped_synthetic_text_only_diagnostic_is_bounded_and_redacted():
    provider_text = (
        "The model cannot return the requested audio. "
        "你好，这是一次语音连接测试。 access_token=ya29.TOP_SECRET projects/mira-test "
        "https://example.invalid/private"
    )
    transport = Transport([{
        "modelVersion": "gemini-3.8-flash-tts-001",
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 12, "totalTokenCount": 15,
                          "privateField": "must-not-cross"},
        "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": provider_text}]}}],
    }])
    scoped = GoogleGeminiTtsBackend(
        GeminiTtsOptions(project_id="mira-test", voice="Kore", capture_provider_text_diagnostics=True),
        transport,
    )
    with pytest.raises(SpeechProviderError) as caught:
        _ = [item async for item in scoped.synthesize("你好，这是一次语音连接测试。", "out-text-only")]
    detail = caught.value.audio_details
    assert detail.validation_reason == "non_audio_part"
    assert detail.model_version == "gemini-3.8-flash-tts-001"
    assert (detail.input_token_count, detail.output_token_count, detail.total_token_count) == (3, 12, 15)
    assert "The model cannot return" in detail.response_text_excerpt
    assert "[synthetic-prompt-redacted]" in detail.response_text_excerpt
    serialized = repr(detail)
    for secret in ("TOP_SECRET", "ya29.", "mira-test", "example.invalid", "must-not-cross"):
        assert secret not in serialized
    assert len(detail.response_text_excerpt) <= 512 and transport.closed


@pytest.mark.asyncio
async def test_audio_budget_is_enforced():
    transport = Transport([audio(b"\0" * 8, finish="STOP")])
    with pytest.raises(SpeechProviderError, match="output_limit"):
        _ = [item async for item in backend(transport, max_audio_samples=3).synthesize("你好", "out-1")]


@pytest.mark.asyncio
async def test_tts_cancel_and_early_close_release_transport():
    transport = Transport([audio(), "WAIT", audio(finish="STOP")])
    stream = backend(transport).synthesize("你好", "out-1")
    assert (await anext(stream)).first_sample == 0
    task = asyncio.create_task(anext(stream))
    await asyncio.wait_for(transport.entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    transport.release.set()
    assert transport.closed
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    transport2 = Transport([audio(), audio(finish="STOP")])
    stream2 = backend(transport2).synthesize("你好", "out-2")
    await anext(stream2)
    await stream2.aclose()
    assert transport2.closed


class Response:
    def __init__(self, chunks, status=200):
        self.chunks, self.status_code = chunks, status
        self.headers = {"content-type": "text/event-stream"}
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def aiter_bytes(self):
        for chunk in self.chunks:
            yield chunk


class Client:
    def __init__(self, response):
        self.response, self.calls = response, []

    def stream(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


@pytest.mark.asyncio
async def test_rest_sse_transport_decodes_chunk_boundaries_and_cleans_up():
    data = (": keepalive\r\ndata: " + json.dumps(audio(finish="STOP")) + "\r\n\r\n").encode()
    response = Response([data[:7], data[7:40], data[40:]])
    client = Client(response)
    transport = GoogleGeminiTtsRestTransport(client)
    packets = [item async for item in backend(transport).synthesize("你好", "out-1")]
    assert len(packets) == 1 and response.closed
    assert client.calls[0][0][0] == "POST"
    assert client.calls[0][1]["follow_redirects"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(401, "unauthenticated"), (403, "permission_denied"), (429, "quota_exhausted"), (503, "unavailable")])
async def test_rest_http_status_safe_mapping(status, code):
    response = Response([b"private-response"], status)
    with pytest.raises(SpeechProviderError) as caught:
        _ = [item async for item in backend(GoogleGeminiTtsRestTransport(Client(response))).synthesize("你好", "out-1")]
    assert caught.value.code == code and response.closed


def google_error_body(*, status="INVALID_ARGUMENT", reason="INVALID_ARGUMENT",
                      message="Unknown name 'maxOutputTokens' at 'generationConfig'; cannot find field.",
                      field="generationConfig.maxOutputTokens"):
    return json.dumps({"error": {
        "code": 400,
        "status": status,
        "message": message,
        "details": [
            {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason,
             "domain": "googleapis.com", "metadata": {"resource": "projects/synthetic-project"}},
            {"@type": "type.googleapis.com/google.rpc.BadRequest",
             "fieldViolations": [{"field": field, "description": "contains private request text"}]},
        ],
    }}).encode()


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status,status,reason,field,code", [
    (400, "INVALID_ARGUMENT", "INVALID_ARGUMENT", "generationConfig.maxOutputTokens", "invalid_input"),
    (401, "UNAUTHENTICATED", "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "", "unauthenticated"),
    (403, "PERMISSION_DENIED", "BILLING_DISABLED", "", "permission_denied"),
    (429, "RESOURCE_EXHAUSTED", "RATE_LIMIT_EXCEEDED", "", "quota_exhausted"),
])
async def test_http_error_retains_only_allowlisted_safe_provider_details(http_status, status, reason, field, code):
    base_message = ("Unknown name 'maxOutputTokens' at 'generationConfig'; cannot find field."
                    if field else "Provider rejected the request.")
    body = google_error_body(
        status=status, reason=reason,
        message=(base_message + " access_token=ya29.TOP-SECRET 你好，这是一次语音连接测试。 projects/synthetic-project"),
        field=field,
    )
    response = Response([body], status=http_status)
    caught = None
    with pytest.raises(SpeechProviderError) as error:
        _ = [item async for item in backend(GoogleGeminiTtsRestTransport(Client(response))).synthesize("你好", "out-1")]
    caught = error.value
    assert caught.code == code
    assert caught.details.http_status == http_status
    assert caught.details.provider_status == status
    assert caught.details.provider_reason == reason
    assert caught.details.field_names == ((field,) if field else ())
    assert caught.details.diagnostic == "unknown_request_field" if field else caught.details.diagnostic in {
        "authentication_rejected", "authorization_rejected", "quota_rejected"
    }
    serialized = repr(caught.details)
    for forbidden in ("TOP-SECRET", "ya29.", "你好，这是一次语音连接测试。", "synthetic-project", "private request text", "googleapis.com"):
        assert forbidden not in serialized
    assert response.closed


@pytest.mark.asyncio
async def test_http_error_body_capture_is_bounded_and_malformed_body_has_no_detail():
    oversize = google_error_body() + b" " * 10000
    response = Response([oversize], status=400)
    with pytest.raises(SpeechProviderError) as caught:
        _ = [item async for item in backend(GoogleGeminiTtsRestTransport(Client(response))).synthesize("你好", "out-1")]
    assert caught.value.details.body_bytes_read <= 8192
    assert caught.value.details.body_truncated is True
    assert response.closed

    malformed = Response([b"not-json TOP-SECRET"], status=400)
    with pytest.raises(SpeechProviderError) as caught:
        _ = [item async for item in backend(GoogleGeminiTtsRestTransport(Client(malformed))).synthesize("你好", "out-1")]
    assert caught.value.code == "invalid_input"
    assert caught.value.details.provider_status is None
    assert caught.value.details.field_names == ()
    assert "TOP-SECRET" not in repr(caught.value.details) and malformed.closed


@pytest.mark.asyncio
async def test_http_error_body_timeout_and_cancellation_close_response_without_raw_text():
    class BodyTimeout(Response):
        async def aiter_bytes(self):
            raise TimeoutError("TOP-SECRET response body timeout")
            yield b""

    timed = BodyTimeout([], status=400)
    with pytest.raises(SpeechProviderError) as caught:
        _ = [item async for item in backend(GoogleGeminiTtsRestTransport(Client(timed))).synthesize("你好", "out-1")]
    assert caught.value.code == "invalid_input"
    assert caught.value.details.body_capture_status == "timeout"
    assert "TOP-SECRET" not in repr(caught.value.details) and timed.closed

    class WaitingBody(Response):
        def __init__(self):
            super().__init__([], status=400)
            self.entered = asyncio.Event()

        async def aiter_bytes(self):
            self.entered.set()
            await asyncio.Event().wait()
            yield b""

    waiting = WaitingBody()
    stream = backend(GoogleGeminiTtsRestTransport(Client(waiting))).synthesize("你好", "out-1")
    task = asyncio.create_task(anext(stream))
    await asyncio.wait_for(waiting.entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert waiting.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("message,expected_diagnostic,expected_fields", [
    ("Invalid JSON payload received. Unknown name 'responseFormat' at 'generationConfig': Cannot find field.",
     "unknown_request_field", ("generationConfig.responseFormat",)),
    ("Invalid value for 'generationConfig.speechConfig.voiceConfig.voice'.",
     "invalid_voice", ("generationConfig.speechConfig.voiceConfig.voice",)),
    ("The streamGenerateContent method is not supported for this operation.",
     "unsupported_method", ()),
])
async def test_message_only_provider_errors_normalize_fields_without_retaining_message(
        message, expected_diagnostic, expected_fields):
    message_with_private_echo = (message + " TOP-SECRET access_token=ya29.SENSITIVE "
                                 "你好，这是一次语音连接测试。 https://example.test/projects/synthetic-project")
    body = json.dumps({"error": {"code": 400, "message": message_with_private_echo}}).encode()
    response = Response([body], status=400)
    with pytest.raises(SpeechProviderError) as caught:
        _ = [item async for item in backend(GoogleGeminiTtsRestTransport(Client(response))).synthesize("你好", "out-1")]
    assert caught.value.code == "invalid_input"
    assert caught.value.details.provider_status is None
    assert caught.value.details.field_names == expected_fields
    assert caught.value.details.diagnostic == expected_diagnostic
    serialized = repr(caught.value.details)
    for forbidden in ("TOP-SECRET", "ya29.", "SENSITIVE", "你好，这是一次语音连接测试。", "example.test", "synthetic-project"):
        assert forbidden not in serialized
    assert response.closed


@pytest.mark.asyncio
async def test_unknown_provider_message_is_not_persisted_or_promoted_to_specific_cause():
    body = json.dumps({"error": {"message": "Opaque provider issue echo=TOP-SECRET"}}).encode()
    response = Response([body], status=400)
    with pytest.raises(SpeechProviderError) as caught:
        _ = [item async for item in backend(GoogleGeminiTtsRestTransport(Client(response))).synthesize("你好", "out-1")]
    assert caught.value.details.provider_status is None
    assert caught.value.details.provider_reason is None
    assert caught.value.details.field_names == ()
    assert caught.value.details.diagnostic == "request_rejected"
    assert "Opaque provider issue" not in repr(caught.value.details)
    assert "TOP-SECRET" not in repr(caught.value.details) and response.closed


@pytest.mark.asyncio
async def test_rest_rejects_oversize_and_invalid_events():
    for data, code in [(b"data: " + b"x" * 200 + b"\n\n", "response_limit"), (b"data: not-json\n\n", "invalid_response")]:
        response = Response([data])
        with pytest.raises(SpeechProviderError, match=code):
            _ = [item async for item in backend(GoogleGeminiTtsRestTransport(Client(response), max_event_bytes=100)).synthesize("你好", "out-1")]
        assert response.closed


@pytest.mark.asyncio
async def test_rest_refreshes_injected_token_and_scopes_quota_project():
    response = Response([("data: " + json.dumps(audio(finish="STOP")) + "\n\n").encode()])
    client, tokens = Client(response), []

    async def token_provider():
        tokens.append(1)
        return "synthetic-token-never-real"

    transport = GoogleGeminiTtsRestTransport(client, token_provider=token_provider, quota_project_id="mira-quota")
    _ = [item async for item in backend(transport).synthesize("你好", "out-1")]
    headers = client.calls[0][1]["headers"]
    assert headers["Authorization"] == "Bearer synthetic-token-never-real"
    assert headers["X-Goog-User-Project"] == "mira-quota" and len(tokens) == 1
    assert "synthetic-token" not in repr(transport)


@pytest.mark.asyncio
async def test_invalid_token_never_enters_http_headers():
    client = Client(Response([]))

    async def token_provider():
        return "bad\r\nInjected: value"

    with pytest.raises(SpeechProviderError, match="unauthenticated"):
        _ = [item async for item in backend(GoogleGeminiTtsRestTransport(client, token_provider=token_provider)).synthesize("你好", "out-1")]
    assert client.calls == []


@pytest.mark.asyncio
async def test_rest_whole_stream_deadline_is_enforced():
    class Stalled(Response):
        async def aiter_bytes(self):
            await asyncio.Event().wait()
            yield b""

    response = Stalled([])
    with pytest.raises(SpeechProviderError, match="timeout"):
        _ = [item async for item in backend(GoogleGeminiTtsRestTransport(Client(response)), timeout_seconds=0.01).synthesize("你好", "out-1")]
    assert response.closed


@pytest.mark.asyncio
async def test_concrete_httpx_client_seam_is_offline_and_cancellable():
    import httpx

    closed, sent = asyncio.Event(), []

    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield ("data: " + json.dumps(audio()) + "\n\n").encode()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    async def handler(request):
        sent.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Bytes())

    async def token_provider():
        return "synthetic-google-token"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
        stream = backend(GoogleGeminiTtsRestTransport(client, token_provider=token_provider)).synthesize("你好", "out-1")
        await anext(stream)
        await stream.aclose()
    assert closed.is_set() and len(sent) == 1
    assert sent[0].headers["authorization"] == "Bearer synthetic-google-token"
    assert json.loads(sent[0].content)["generationConfig"]["speechConfig"]["voiceConfig"] == {"voice": "Kore"}


@pytest.mark.asyncio
async def test_sse_multiline_error_truncation_and_compression_are_explicit():
    cases = [
        ([b'data: {"error": {"code": 403, "message": "private-body"}}\n\n'], "permission_denied"),
        ([b'data: {"usageMetadata": {}}\n'], "incomplete_stream"),
        ([b'data: []\n\n'], "invalid_response"),
        ([b'data: \xff\n\n'], "invalid_response"),
    ]
    for chunks, code in cases:
        response = Response(chunks)
        with pytest.raises(SpeechProviderError) as caught:
            _ = [item async for item in backend(GoogleGeminiTtsRestTransport(Client(response))).synthesize("你好", "out-1")]
        assert caught.value.code == code and "private-body" not in str(caught.value)
        assert response.closed
    response = Response([])
    response.headers["content-encoding"] = "gzip"
    with pytest.raises(SpeechProviderError, match="invalid_response"):
        _ = [item async for item in backend(GoogleGeminiTtsRestTransport(Client(response))).synthesize("你好", "out-1")]


@pytest.mark.asyncio
async def test_tts_does_not_retry_or_emit_after_stop():
    transport = Transport([audio(finish="STOP"), audio()])
    with pytest.raises(SpeechProviderError, match="invalid_response"):
        _ = [item async for item in backend(transport).synthesize("你好", "out-1")]
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_tts_suppressed_transport_cancellation_cannot_emit_late_audio():
    class Uncooperative(Transport):
        async def stream(self, **kwargs):
            try:
                self.entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    yield audio(finish="STOP")
            finally:
                self.closed = True

    transport = Uncooperative([])
    stream = backend(transport).synthesize("你好", "out-1")
    task = asyncio.create_task(anext(stream))
    await asyncio.wait_for(transport.entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.closed


@pytest.mark.asyncio
async def test_httpx_timeout_is_distinct_from_service_failure():
    import httpx

    class TimeoutClient:
        def stream(self, *args, **kwargs):
            raise httpx.ReadTimeout("private-request-detail")

    with pytest.raises(SpeechProviderError) as caught:
        _ = [item async for item in backend(GoogleGeminiTtsRestTransport(TimeoutClient())).synthesize("你好", "out-1")]
    assert caught.value.code == "timeout"
    assert "private-request-detail" not in str(caught.value)
