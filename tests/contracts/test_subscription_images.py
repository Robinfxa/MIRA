"""Offline internal-client compatibility contract; no entitlement or live-service test."""
import asyncio
import base64
import gzip
import json
from types import SimpleNamespace
from uuid import UUID

import httpx
from pydantic import SecretStr
import pytest

from mira.adapters.media._openai_http import ImageProviderError
from mira.adapters.media.openai_images import OpenAIImageBackend
from mira.adapters.media.png_decoder import PillowPngDecoder
from mira.adapters.media.subscription_images import SubscriptionImageBackend
from tests.contracts.test_story_image_adapters import ByteStream, SPEC, png, request


class Credentials:
    def __init__(self, **changes):
        self.calls = 0
        self.value = SimpleNamespace(access_token=SecretStr('synthetic-subscription-token'),
                                     account_id='synthetic-account', residency=None)
        self.value.__dict__.update(changes)

    async def get_credentials(self):
        self.calls += 1
        return self.value


def image_body(data=None, **changes):
    return {'created': 123, 'data': [{'b64_json': base64.b64encode(
        png() if data is None else data).decode('ascii')}], **changes}


def response(body=None, *, raw=None, status=200, encoding='identity', headers=None, split=73):
    raw = json.dumps(image_body() if body is None else body).encode() if raw is None else raw
    if encoding == 'gzip':
        raw = gzip.compress(raw)
    return httpx.Response(status, headers={'content-type': 'application/json',
        'content-encoding': encoding, **(headers or {})},
        stream=ByteStream([raw[i:i + split] for i in range(0, len(raw), split)]))


def backend(handler, *, credentials=None, **kwargs):
    return SubscriptionImageBackend(credential_source=credentials or Credentials(),
        transport=httpx.MockTransport(handler), **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize('encoding', ['identity', 'gzip'])
async def test_exact_subscription_request_and_single_inline_png(encoding, monkeypatch):
    seen = []
    async def forbidden_api(*args, **kwargs):
        pytest.fail('API fallback was invoked')
    monkeypatch.setattr(OpenAIImageBackend, 'generate', forbidden_api)
    def handler(http):
        seen.append(http)
        assert str(http.url) == 'https://chatgpt.com/backend-api/codex/images/generations'
        assert json.loads(http.content) == {'model': 'gpt-image-2', 'prompt': SPEC,
            'background': 'opaque', 'quality': 'auto', 'size': '1024x1024', 'n': 1}
        assert http.headers['authorization'] == 'Bearer synthetic-subscription-token'
        assert http.headers['chatgpt-account-id'] == 'synthetic-account'
        assert http.headers['originator'] == 'mira'
        assert http.headers['accept-encoding'] == 'identity, gzip'
        assert str(UUID(http.headers['x-codex-image-turn-id'])) == http.headers['x-codex-image-turn-id']
        assert 'openai-beta' not in http.headers
        assert 'private-session' not in http.content.decode()
        return response(encoding=encoding)
    source = Credentials()
    result = await backend(handler, credentials=source).generate(request())
    assert result.data == png()
    assert (result.provider, result.model, result.media_type, result.usage_units) == (
        'chatgpt_subscription', 'gpt-image-2', 'image/png', None)
    assert PillowPngDecoder().canonicalize(result.data).width == 1024
    assert len(seen) == source.calls == 1


@pytest.mark.asyncio
async def test_optional_auth_headers_and_independent_turn_identity():
    seen = []
    def handler(http):
        seen.append(http)
        assert 'chatgpt-account-id' not in http.headers
        assert http.headers['x-openai-internal-codex-residency'] == 'synthetic-region'
        return response()
    instance = backend(handler, credentials=Credentials(account_id=None, residency='synthetic-region'))
    await instance.generate(request())
    await instance.generate(request())
    assert seen[0].headers['x-codex-image-turn-id'] != seen[1].headers['x-codex-image-turn-id']


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', [
    {'specification': ''}, {'specification': 'x' * 4097},
    {'specification_digest': '0' * 64}, {'allowed_resource_ids': ('image-ref',)},
    {'width': 512}, {'height': 1536}, {'max_output_bytes': 8_388_609},
    {'required_checks': ('allowed_scene',)}, {'admission_reference': ''},
])
async def test_invalid_request_never_resolves_credentials_or_dispatches(mutation):
    source = Credentials(); seen = []
    with pytest.raises(ImageProviderError):
        await backend(lambda http: seen.append(http), credentials=source).generate(request(**mutation))
    assert not seen and source.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'access_token': 'raw-token'}, {'access_token': SecretStr('')},
    {'access_token': SecretStr('sk-synthetic-api-key')},
    {'access_token': SecretStr('token\r\nInjected: bad')},
    {'access_token': SecretStr('x' * 8193)}, {'account_id': ''},
    {'account_id': 'bad\naccount'}, {'account_id': 'x' * 257}, {'residency': '\u2603'},
])
async def test_invalid_subscription_credentials_are_safe_and_never_dispatch(change):
    seen = []; source = Credentials(**change)
    with pytest.raises(ImageProviderError, match='image_subscription_auth'):
        await backend(lambda http: seen.append(http), credentials=source).generate(request())
    assert not seen and source.calls == 1


@pytest.mark.asyncio
async def test_auth_refresh_failure_is_safe_single_attempt_and_never_falls_back(monkeypatch):
    class FailedCredentials(Credentials):
        async def get_credentials(self):
            self.calls += 1
            raise RuntimeError('private-refresh-token provider-secret')
    async def forbidden_api(*args, **kwargs):
        pytest.fail('API fallback was invoked')
    monkeypatch.setattr(OpenAIImageBackend, 'generate', forbidden_api)
    source = FailedCredentials(); seen = []
    with pytest.raises(ImageProviderError) as error:
        await backend(lambda http: seen.append(http), credentials=source).generate(request())
    assert str(error.value) == 'image_subscription_auth'
    assert source.calls == 1 and not seen


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'created': None}, {'created': -1}, {'created': True}, {'created': 2**64},
    {'data': []}, {'data': [{}, {}]}, {'data': [{'b64_json': ''}]},
    {'data': [{'b64_json': 'malformed*'}]}, {'data': [{'b64_json': 1}]},
    {'data': [{'b64_json': 'AA==', 'url': 'https://outside.invalid/image.png'}]},
    {'data': [{'partial_image_b64': 'AA=='}]},
    {'error': {'message': 'provider-private'}}, {'status': 'incomplete'},
    {'refusal': 'provider-private'}, {'incomplete_details': {}},
    {'background': 'unknown'}, {'quality': []}, {'size': False},
    {'data': [{'b64_json': 'AA==', 'generation_id': 5}]},
])
async def test_response_must_be_one_complete_source_dto_image(change):
    seen = []
    def handler(http):
        seen.append(http)
        return response(image_body(**change))
    with pytest.raises(ImageProviderError) as error:
        await backend(handler).generate(request())
    assert 'provider-private' not in str(error.value)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_optional_response_metadata_is_accepted_without_entitlement_or_usage_claims():
    body = image_body(background='opaque', quality='high', size='1024x1024')
    body['data'][0]['generation_id'] = 'synthetic-id'
    result = await backend(lambda _: response(body)).generate(request())
    assert result.usage_units is None and not hasattr(result, 'generation_id')


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['metadata', 'missing-mime', 'null-metadata', 'passive-hints'])
async def test_source_serde_ignores_benign_metadata_and_does_not_require_mime(change):
    body = image_body()
    if change == 'metadata':
        body.update(model='future-model-metadata', usage={'total_tokens': 12}, output_format='png',
                    revised_prompt='untrusted private description', future_metadata={'version': 2})
        body['data'][0].update(revised_prompt='also untrusted', output_format='png',
                               unknown_benign_metadata=['safe', 1])
    if change == 'null-metadata':
        body.update(error=None, refusal=None, status=None, size=None, background=None,
                    incomplete_details=None, output_format=None)
        body['data'][0].update(status=None, error=None, refusal=None, generation_id=None)
    if change == 'passive-hints':
        body.update(size='auto', background='auto', quality='auto',
                    url='https://outside.invalid/metadata-only')
        body['data'][0].update(url='https://outside.invalid/never-fetch')
    seen = []
    def handler(_):
        seen.append(True)
        if change == 'missing-mime':
            return httpx.Response(200, stream=ByteStream([json.dumps(body).encode()]))
        return response(body)
    result = await backend(handler).generate(request())
    assert result.data == png() and result.usage_units is None
    assert result.model == 'gpt-image-2' and not hasattr(result, 'revised_prompt')
    assert len(seen) == 1 and not hasattr(result, 'url')


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'output_format': 'jpeg'}, {'status': 'in_progress'}, {'partial_image_b64': 'AA=='},
    {'error': {'message': 'private'}},
    {'refusal': 'private'}, {'incomplete_details': {'reason': 'limit'}},
])
@pytest.mark.parametrize('target', ['body', 'item'])
async def test_benign_metadata_does_not_hide_explicit_failure_or_external_resource(change, target):
    body = image_body()
    (body if target == 'body' else body['data'][0]).update(change)
    with pytest.raises(ImageProviderError):
        await backend(lambda _: response(body)).generate(request())


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['base64-bound', 'bytes-bound', 'not-png', 'bad-base64'])
async def test_image_byte_and_base64_bounds(kind):
    body = image_body()
    req = request()
    if kind == 'base64-bound': req = request(max_output_bytes=32)
    if kind == 'bytes-bound':
        body = image_body(b'\x89PNG\r\n\x1a\n' + b'x' * 24); req = request(max_output_bytes=31)
    if kind == 'not-png': body = image_body(b'not png')
    if kind == 'bad-base64': body['data'][0]['b64_json'] = 'A===\n'
    with pytest.raises(ImageProviderError):
        await backend(lambda _: response(body)).generate(req)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['truncated', 'wrong-dimensions', 'trailing', 'broken-crc'])
async def test_downstream_pillow_still_rejects_invalid_raster(kind):
    data = png()
    if kind == 'truncated': data = data[:-5]
    if kind == 'wrong-dimensions': data = png(width=1536)
    if kind == 'trailing': data += b'trailing'
    if kind == 'broken-crc': data = data[:29] + b'xxxx' + data[33:]
    generated = await backend(lambda _: response(image_body(data))).generate(request())
    with pytest.raises(ImageProviderError):
        PillowPngDecoder().canonicalize(generated.data)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', [
    'redirect', 'auth-status', 'rate', 'mime', 'encoding', 'length', 'short-length',
    'wire', 'gzip-bomb', 'gzip-truncated', 'gzip-trailing', 'gzip-invalid',
    'duplicate', 'nan', 'not-json', 'missing-created', 'not-object', 'transport',
])
async def test_http_is_bounded_redacted_and_never_retried_or_redirected(kind, monkeypatch):
    seen = []
    async def forbidden_api(*args, **kwargs):
        pytest.fail('API fallback was invoked')
    monkeypatch.setattr(OpenAIImageBackend, 'generate', forbidden_api)
    def handler(http):
        seen.append(http)
        if kind == 'redirect': return response(status=307, headers={'location': 'https://outside.invalid'})
        if kind == 'auth-status': return response({'error': 'private-token'}, status=401)
        if kind == 'rate': return response({'error': 'private-token'}, status=429)
        if kind == 'mime': return response(headers={'content-type': 'text/html'})
        if kind == 'encoding': return response(encoding='br')
        if kind == 'length': return response(headers={'content-length': '999999999'})
        if kind == 'short-length': return response(headers={'content-length': '1'})
        if kind == 'wire': return response(raw=b' ' * 65_537)
        if kind == 'gzip-bomb': return response(raw=b' ' * 65_537, encoding='gzip')
        if kind.startswith('gzip-'):
            raw = gzip.compress(json.dumps(image_body()).encode())
            if kind == 'gzip-truncated': raw = raw[:-1]
            if kind == 'gzip-trailing': raw += gzip.compress(b'{}')
            if kind == 'gzip-invalid': raw = b'private-token'
            return response(raw=raw, headers={'content-encoding': 'gzip'})
        if kind == 'duplicate': return response(raw=b'{"created":1,"created":2,"data":[]}')
        if kind == 'nan': return response(raw=b'{"created":NaN,"data":[]}')
        if kind == 'not-json': return response(raw=b'private-token')
        if kind == 'missing-created': return response({'data': []})
        if kind == 'not-object': return response([])
        raise RuntimeError('private-token provider-payload')
    with pytest.raises(ImageProviderError) as error:
        await backend(handler, max_wire_bytes=65_536).generate(request())
    assert 'private-token' not in str(error.value)
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('where', ['credentials', 'handler', 'body', 'stream_close', 'client_close'])
@pytest.mark.parametrize('trigger', ['cancel', 'deadline'])
async def test_swallowed_cancellation_and_deadline_cannot_return_late_image(where, trigger):
    entered = asyncio.Event(); calls = []
    async def swallow():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
    class LateCredentials(Credentials):
        async def get_credentials(self):
            if where == 'credentials': await swallow()
            return await super().get_credentials()
    class LateStream(ByteStream):
        async def __aiter__(self):
            if where == 'body': await swallow()
            yield json.dumps(image_body()).encode()
        async def aclose(self):
            if where == 'stream_close': await swallow()
            self.closed = True
    stream = LateStream([])
    class LateTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, http):
            calls.append(http)
            if where == 'handler': await swallow()
            return httpx.Response(200, headers={'content-type': 'application/json'}, stream=stream)
        async def aclose(self):
            if where == 'client_close': await swallow()
    instance = SubscriptionImageBackend(credential_source=LateCredentials(), transport=LateTransport(),
                                       timeout_seconds=0.05 if trigger == 'deadline' else 5)
    task = asyncio.create_task(instance.generate(request()))
    if trigger == 'cancel':
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    else:
        with pytest.raises(ImageProviderError, match='timeout'):
            await asyncio.wait_for(task, 2)
    assert len(calls) == (0 if where == 'credentials' else 1)
    if calls: assert stream.closed


@pytest.mark.parametrize('options', [
    {'credential_source': None}, {'timeout_seconds': 0}, {'timeout_seconds': True},
    {'timeout_seconds': float('nan')}, {'timeout_seconds': 121},
    {'max_wire_bytes': 1023}, {'max_wire_bytes': 12_000_001}, {'transport': object()},
])
def test_construction_requires_bounded_injected_dependencies(options):
    with pytest.raises(ValueError):
        SubscriptionImageBackend(**{'credential_source': Credentials(), **options})


def test_no_endpoint_model_or_api_key_override_exists():
    for field in ('endpoint', 'base_url', 'api_key', 'model', 'quality'):
        with pytest.raises(TypeError):
            SubscriptionImageBackend(credential_source=Credentials(), **{field: 'unsupported'})
