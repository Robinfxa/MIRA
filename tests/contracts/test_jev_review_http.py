"""Actual HTTP construction tested with httpx.MockTransport, never sockets."""
import json

import httpx
import pytest
from pydantic import SecretStr

from mira.adapters.review.jev import JevTransportError
from mira.adapters.review.jev_support.http import SYSTEMONE_URL, HttpxJevTransport


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def response(code=200, *, chunks=(b'{"result":"synthetic"}',), headers=None):
    return httpx.Response(code, headers=headers or {"Content-Type": "application/json"},
                          stream=Chunks(chunks))


@pytest.mark.asyncio
async def test_real_transport_uses_only_fixed_origin_and_injected_bearer(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    requests = []
    def handler(request):
        requests.append(request)
        assert str(request.url) == SYSTEMONE_URL
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer synthetic-not-a-key"
        assert request.headers["accept-encoding"] == "identity"
        assert json.loads(request.content) == {"synthetic": "input"}
        return response()
    transport = HttpxJevTransport(SecretStr("synthetic-not-a-key"), transport=httpx.MockTransport(handler))
    result = await transport(b'{"synthetic":"input"}', timeout_seconds=1, max_response_bytes=256)
    assert result.status_code == 200
    assert result.body == b'{"result":"synthetic"}'
    assert len(requests) == 1
    assert "synthetic-not-a-key" not in repr(transport) + repr(result)
    assert "result" not in repr(result)


@pytest.mark.asyncio
async def test_redirect_never_sends_key_to_another_origin():
    requests = []
    def handler(request):
        requests.append(request)
        return response(307, headers={"Location": "https://other.invalid/steal"})
    transport = HttpxJevTransport(SecretStr("synthetic"), transport=httpx.MockTransport(handler))
    result = await transport(b'{}', timeout_seconds=1, max_response_bytes=256)
    assert result.status_code == 307
    assert result.body == b""
    assert len(requests) == 1
    assert str(requests[0].url) == SYSTEMONE_URL


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [
    {"Content-Type": "application/json", "Content-Encoding": "gzip"},
    {"Content-Type": "text/html"},
])
async def test_compressed_or_wrong_content_type_is_rejected(headers):
    transport = HttpxJevTransport(SecretStr("synthetic"), transport=httpx.MockTransport(
        lambda _: response(headers=headers)))
    with pytest.raises(JevTransportError, match="^jev_response_encoding_invalid$"):
        await transport(b'{}', timeout_seconds=1, max_response_bytes=256)


@pytest.mark.asyncio
async def test_stream_read_is_bounded_without_accumulating_whole_response():
    transport = HttpxJevTransport(SecretStr("synthetic"), transport=httpx.MockTransport(
        lambda _: response(chunks=(b'a' * 10, b'b' * 10, b'c' * 10))))
    with pytest.raises(JevTransportError, match="^jev_response_too_large$"):
        await transport(b'{}', timeout_seconds=1, max_response_bytes=15)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 422, 429, 529])
async def test_error_body_is_not_read_or_retained_and_no_retries(code):
    count = 0
    def handler(_):
        nonlocal count
        count += 1
        return response(code, chunks=(b'synthetic-private-provider-error',))
    transport = HttpxJevTransport(SecretStr("synthetic"), transport=httpx.MockTransport(handler))
    result = await transport(b'{}', timeout_seconds=1, max_response_bytes=256)
    assert result.body == b""
    assert result.status_code == code
    assert count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error,expected", [
    (httpx.ReadTimeout("synthetic-private"), TimeoutError),
    (httpx.ConnectError("synthetic-private"), JevTransportError),
])
async def test_http_errors_are_fixed_codes_and_not_logged(error, expected, caplog, capsys):
    def handler(_):
        raise error
    transport = HttpxJevTransport(SecretStr("synthetic"), transport=httpx.MockTransport(handler))
    with pytest.raises(expected) as caught:
        await transport(b'{}', timeout_seconds=1, max_response_bytes=256)
    assert "synthetic-private" not in str(caught.value) + caplog.text + str(capsys.readouterr())


def test_construction_never_creates_http_client_or_reads_secret_files(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Construction must be inert")
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    HttpxJevTransport(SecretStr("synthetic"))


@pytest.mark.parametrize("secret", ["ordinary-string", SecretStr(""), SecretStr("with space")])
def test_invalid_secret_reports_no_secret_value(secret):
    with pytest.raises(ValueError, match="^jev_credential_invalid$"):
        HttpxJevTransport(secret)


@pytest.mark.asyncio
async def test_client_explicitly_disables_proxy_discovery_and_redirect_following(monkeypatch):
    original = httpx.AsyncClient
    observed = []
    def capture(*args, **kwargs):
        observed.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", capture)
    transport = HttpxJevTransport(SecretStr("synthetic"), transport=httpx.MockTransport(lambda _: response()))
    await transport(b'{}', timeout_seconds=1, max_response_bytes=256)
    assert len(observed) == 1
    assert observed[0]["trust_env"] is False
    assert observed[0]["follow_redirects"] is False
    assert observed[0]["timeout"].read == 1


@pytest.mark.asyncio
async def test_invalid_http_representation_is_contract_error_not_network_failure():
    from mira.adapters.review.jev import (
        QUESTION_SET_VERSION, JevReviewBackend, JevReviewContract, candidate_digest, context_digest,
    )
    from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext
    from mira.domain.models import EffectKind
    context = GenerationContext("下雨了吗？", ("下雨了吗？",), (), 1)
    candidate = CandidateRange((EffectProposal(EffectKind.SUBTITLE, "下雨了。"),), "synthetic")
    contract = JevReviewContract("synthetic", QUESTION_SET_VERSION, context_digest(context),
                                 candidate_digest(candidate), (), ("回答天气",), ("正在下雨",), synthetic=True)
    transport = HttpxJevTransport(SecretStr("synthetic"), transport=httpx.MockTransport(
        lambda _: response(headers={"Content-Type": "text/html"})))
    backend = JevReviewBackend(transport=transport, model="jev-1.13.0",
                               contract_resolver=lambda *_: contract, request_limit=1)
    result = await backend.review(context, candidate)
    assert result.reason_code == "jev_response_contract_invalid"
