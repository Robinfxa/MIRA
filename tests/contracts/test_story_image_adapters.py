"""Synthetic pixels and injected HTTP only. No provider/auth/network calls."""
import asyncio
import base64
from dataclasses import replace
from hashlib import sha256
import io
import json
import struct
import zlib

import httpx
from pydantic import SecretStr
import pytest

from mira.adapters.media._openai_http import ImageProviderError
from mira.adapters.media.openai_images import OpenAIImageBackend, OpenAIImageOptions
from mira.adapters.media.openai_vision_review import OpenAIVisionReviewBackend, OpenAIVisionOptions
from mira.adapters.media.png_decoder import PillowPngDecoder
from mira.application.ports.media import MediaArtifact, MediaRequest
from mira.domain.story_images import REQUIRED_PIXEL_CHECKS

IMAGE_MODEL = 'gpt-image-synthetic-snapshot'
REVIEW_MODEL = 'gpt-vision-synthetic-snapshot'
SYNTHETIC_KEY = SecretStr('sk-synthetic-not-a-credential')
SPEC = 'A fictional empty coast with a lighthouse. No people, writing or documents.'


def chunk(kind, value):
    return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value))


def png(*, width=1024, height=1024, metadata=False):
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    row = b'\0' + bytes((10, 20, 30)) * width
    extra = chunk(b'tEXt', b'private_metadata\0must not survive') if metadata else b''
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + extra
            + chunk(b'IDAT', zlib.compress(row * height)) + chunk(b'IEND', b''))


def request(**changes):
    return replace(MediaRequest(
        request_id='image-1', specification=SPEC, allowed_resource_ids=(), output_epoch=7,
        session_id='private-session-never-transmit', parent_request_id='parent-1',
        activity_seq=3, photo_visibility_revision=2,
        specification_digest=sha256(SPEC.encode()).hexdigest(), dependency_digest='d' * 64,
        canon_revision=4, catalog_revision='catalog-v1', policy_revision='pixels-v1',
        admission_reference='admitted-locally-only'), **changes)


def artifact(req=None, **changes):
    req = req or request()
    data = PillowPngDecoder().canonicalize(png()).png
    return replace(MediaArtifact(
        resource_id='local-resource-never-transmit', content_digest=sha256(data).hexdigest(),
        media_type='image/png', png=data, width=1024, height=1024,
        request_id=req.request_id, specification_digest=req.specification_digest,
        policy_revision=req.policy_revision), **changes)


class ByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
    async def __aiter__(self):
        for value in self.chunks:
            yield value
    async def aclose(self):
        self.closed = True


def response(body=None, *, status=200, headers=None, raw=None):
    data = json.dumps(body).encode() if raw is None else raw
    return httpx.Response(status, headers={'content-type': 'application/json', **(headers or {})},
                          stream=ByteStream([data]))


def image_reply(data=None):
    return {'data': [{'b64_json': base64.b64encode(data or png()).decode()}],
            'output_format': 'png', 'size': '1024x1024', 'usage': {'total_tokens': 123}}


def review_document(req=None, art=None):
    req = req or request(); art = art or artifact(req)
    return {'request_id': req.request_id, 'specification_digest': req.specification_digest,
            'checked_content_digest': art.content_digest, 'policy_revision': req.policy_revision,
            'checks': {key: 'pass' for key in REQUIRED_PIXEL_CHECKS},
            'observed_description': 'An empty fictional coast and a distant lighthouse.'}


def review_reply(doc=None):
    return {'status': 'completed', 'model': REVIEW_MODEL, 'error': None,
            'incomplete_details': None, 'output': [{'type': 'message', 'status': 'completed',
            'role': 'assistant', 'content': [{'type': 'output_text',
            'text': json.dumps(doc or review_document())}]}]}


def generator(handler, **kwargs):
    return OpenAIImageBackend(api_key=SYNTHETIC_KEY,
        options=OpenAIImageOptions(model=IMAGE_MODEL, quality='low'),
        transport=httpx.MockTransport(handler), **kwargs)


def reviewer(handler, **kwargs):
    return OpenAIVisionReviewBackend(api_key=SYNTHETIC_KEY,
        options=OpenAIVisionOptions(model=REVIEW_MODEL, max_output_tokens=512),
        transport=httpx.MockTransport(handler), **kwargs)


@pytest.mark.asyncio
async def test_image_request_is_one_explicit_official_png_without_private_context():
    seen = []
    def handler(http):
        seen.append(http)
        body = json.loads(http.content)
        assert str(http.url) == 'https://api.openai.com/v1/images/generations'
        assert body == {'model': IMAGE_MODEL, 'prompt': SPEC, 'n': 1, 'size': '1024x1024',
                        'quality': 'low', 'output_format': 'png', 'background': 'opaque',
                        'stream': False}
        assert http.headers['accept-encoding'] == 'identity'
        assert http.headers['authorization'] == 'Bearer sk-synthetic-not-a-credential'
        assert 'private-session' not in http.content.decode()
        return response(image_reply())
    result = await generator(handler).generate(request())
    assert result.data == png()
    assert (result.media_type, result.provider, result.model, result.usage_units) == (
        'image/png', 'openai_api', IMAGE_MODEL, 123)
    assert not hasattr(result, 'resource_id') and not hasattr(result, 'content_digest')
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', [
    {'data': []}, {'data': [{}, {}]}, {'data': [{'url': 'https://outside.invalid/photo.png'}]},
    {'data': [{'b64_json': 'not base64'}]}, {'data': [{'b64_json': ''}]},
    {'data': [{'b64_json': base64.b64encode(b'not PNG').decode()}]},
    {'data': [{'b64_json': base64.b64encode(png()).decode(), 'url': 'https://outside.invalid'}]},
    {'data': [{'b64_json': base64.b64encode(png()).decode()}], 'output_format': 'jpeg'},
    {'data': [{'b64_json': base64.b64encode(png()).decode()}], 'size': '1536x1024'},
    {'data': [{'b64_json': base64.b64encode(png()).decode()}], 'error': {'message': 'secret'}},
    {'data': [{'b64_json': base64.b64encode(png()).decode()}], 'status': 'incomplete'},
    {'data': [{'b64_json': base64.b64encode(png()).decode()}], 'usage': {'total_tokens': True}},
])
async def test_image_rejects_non_final_single_png_without_trusting_provider_description(bad):
    with pytest.raises(ImageProviderError):
        await generator(lambda _: response(bad)).generate(request())


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', [
    {'specification': ''}, {'specification': 'x' * 4097},
    {'specification_digest': '0' * 64}, {'allowed_resource_ids': ('external-ref',)},
    {'width': 512}, {'height': 2048}, {'max_output_bytes': 8_388_609},
    {'required_checks': ('allowed_scene',)}, {'admission_reference': ''},
])
async def test_invalid_image_request_never_dispatches(mutation):
    seen = []
    with pytest.raises(ImageProviderError):
        await generator(lambda http: seen.append(http)).generate(request(**mutation))
    assert not seen


@pytest.mark.asyncio
async def test_image_base64_bound_is_checked_before_decode():
    with pytest.raises(ImageProviderError):
        await generator(lambda _: response(image_reply())).generate(request(max_output_bytes=32))


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['image', 'review'])
@pytest.mark.parametrize('bad', ['redirect', 'rate', 'server', 'mime', 'encoding', 'length',
                                 'wire', 'duplicate', 'nan', 'not_json'])
async def test_http_rejects_bad_transport_once_and_redacts_provider_body(kind, bad):
    seen = []
    def handler(http):
        seen.append(http)
        if bad == 'redirect': return response({}, status=307, headers={'location': 'https://outside.invalid'})
        if bad == 'rate': return response({'error': {'message': 'private-secret'}}, status=429)
        if bad == 'server': return response({}, status=503)
        if bad == 'mime': return response({}, headers={'content-type': 'text/html'})
        if bad == 'encoding': return response({}, headers={'content-encoding': 'gzip'})
        if bad == 'length': return response({}, headers={'content-length': '999999999'})
        if bad == 'wire': return response(raw=b' ' * 65_537)
        if bad == 'duplicate': return response(raw=b'{"data":[],"data":[]}')
        if bad == 'nan': return response(raw=b'{"data":NaN}')
        return response(raw=b'private-secret')
    backend = generator(handler, max_wire_bytes=65_536) if kind == 'image' else reviewer(handler)
    with pytest.raises(ImageProviderError) as error:
        if kind == 'image': await backend.generate(request())
        else: await backend.review(artifact(), request())
    assert 'private-secret' not in str(error.value)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_review_transmits_exact_png_and_only_bounded_spec_and_checks():
    art = artifact(); req = request(); seen = []
    def handler(http):
        seen.append(http)
        body = json.loads(http.content)
        assert str(http.url) == 'https://api.openai.com/v1/responses'
        assert body['model'] == REVIEW_MODEL
        assert body['store'] is False and body['stream'] is False
        assert body['max_output_tokens'] == 512
        assert 'tools' not in body and 'previous_response_id' not in body
        assert 'conversation' not in body
        assert body['text']['format']['strict'] is True
        image = body['input'][0]['content'][1]
        assert image['type'] == 'input_image' and image['detail'] == 'high'
        assert base64.b64decode(image['image_url'].split(',', 1)[1]) == art.png
        assert 'private-session' not in http.content.decode()
        assert 'local-resource' not in http.content.decode()
        assert SPEC in body['input'][0]['content'][0]['text']
        return response(review_reply())
    result = await reviewer(handler).review(art, req)
    assert result.checked_content_digest == sha256(art.png).hexdigest()
    assert tuple(x.check_id for x in result.checks) == REQUIRED_PIXEL_CHECKS
    assert all(x.result == 'pass' for x in result.checks)
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', [
    {'request_id': 'other'}, {'specification_digest': '0' * 64},
    {'checked_content_digest': '0' * 64}, {'policy_revision': 'other'},
    {'checks': {}}, {'checks': {key: 'allow' for key in REQUIRED_PIXEL_CHECKS}},
    {'observed_description': 'x' * 513}, {'observed_description': 12}, {'extra': 'approval'},
])
async def test_review_rejects_unbound_or_malformed_observations(mutation):
    document = {**review_document(), **mutation}
    with pytest.raises(ImageProviderError):
        await reviewer(lambda _: response(review_reply(document))).review(artifact(), request())


@pytest.mark.asyncio
@pytest.mark.parametrize('result', ['fail', 'unassessable'])
async def test_review_preserves_failed_or_unassessable_checks(result):
    document = review_document(); document['checks']['allowed_scene'] = result
    observed = await reviewer(lambda _: response(review_reply(document))).review(artifact(), request())
    assert observed.checks[0].result == result


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['incomplete', 'refusal', 'tool', 'multi', 'model', 'duplicate_json'])
async def test_review_requires_exactly_one_completed_structured_message(change):
    body = review_reply()
    if change == 'incomplete': body['status'] = 'incomplete'
    elif change == 'refusal': body['output'][0]['content'] = [{'type': 'refusal', 'refusal': 'private-secret'}]
    elif change == 'tool': body['output'][0]['type'] = 'image_generation_call'
    elif change == 'multi': body['output'].append(body['output'][0])
    elif change == 'model': body['model'] = 'unselected-model'
    else: body['output'][0]['content'][0]['text'] = '{"checks":{},"checks":{}}'
    with pytest.raises(ImageProviderError):
        await reviewer(lambda _: response(body)).review(artifact(), request())


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', [
    {'png': b'not PNG'}, {'content_digest': '0' * 64}, {'request_id': 'other'},
    {'specification_digest': '0' * 64}, {'policy_revision': 'other'},
    {'media_type': 'image/jpeg'}, {'width': 512}, {'height': 512},
])
async def test_review_refuses_wrong_pixel_binding_before_dispatch(mutation):
    seen = []
    with pytest.raises(ImageProviderError):
        await reviewer(lambda http: seen.append(http)).review(artifact(**mutation), request())
    assert not seen


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['image', 'review'])
async def test_cancellation_propagates_and_closes_stream_without_retry(kind):
    entered = asyncio.Event(); released = asyncio.Event(); seen = []
    class BlockingStream(ByteStream):
        async def __aiter__(self):
            entered.set()
            await released.wait()
            yield b'{}'
    stream = BlockingStream([])
    def handler(http):
        seen.append(http)
        return httpx.Response(200, headers={'content-type': 'application/json'}, stream=stream)
    backend = generator(handler) if kind == 'image' else reviewer(handler)
    task = asyncio.create_task(backend.generate(request()) if kind == 'image'
                               else backend.review(artifact(), request()))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert stream.closed and len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['image', 'review'])
async def test_total_deadline_includes_waiting_for_body_without_retry(kind):
    seen = []
    async def handler(http):
        seen.append(http)
        await asyncio.Event().wait()
    backend = generator(handler, timeout_seconds=0.01) if kind == 'image' else reviewer(handler, timeout_seconds=0.01)
    with pytest.raises(ImageProviderError, match='timeout'):
        if kind == 'image': await backend.generate(request())
        else: await backend.review(artifact(), request())
    assert len(seen) == 1


def test_decoder_strips_metadata_preserves_exact_pixels_and_is_idempotent():
    source = png(metadata=True)
    decoded = PillowPngDecoder().canonicalize(source)
    assert (decoded.width, decoded.height) == (1024, 1024)
    assert b'private_metadata' not in decoded.png
    assert PillowPngDecoder().canonicalize(decoded.png).png == decoded.png
    from PIL import Image
    with Image.open(io.BytesIO(decoded.png)) as image:
        assert image.mode == 'RGB' and image.getpixel((42, 42)) == (10, 20, 30)
        assert not image.info


@pytest.mark.parametrize('bad', [b'', b'not png', png()[:-1], png()[:-12],
                                png(width=1023), png(width=1, height=1)],
                         ids=['empty', 'wrong-format', 'last-byte-missing', 'missing-end', 'wrong-width', 'tiny'])
def test_decoder_rejects_non_png_truncation_and_wrong_dimensions(bad):
    with pytest.raises(ImageProviderError): PillowPngDecoder().canonicalize(bad)


def test_decoder_rejects_animation_and_dimension_bomb():
    source = png()
    animated = source[:33] + chunk(b'acTL', struct.pack('>II', 2, 0)) + source[33:]
    with pytest.raises(ImageProviderError): PillowPngDecoder().canonicalize(animated)
    bomb_header = struct.pack('>IIBBBBB', 100_000, 100_000, 8, 2, 0, 0, 0)
    bomb = source[:8] + chunk(b'IHDR', bomb_header) + source[33:]
    with pytest.raises(ImageProviderError): PillowPngDecoder().canonicalize(bomb)


def test_decoder_rejects_bad_crc_trailing_data_and_input_byte_overflow():
    source = png()
    corrupted = bytearray(source); corrupted[-1] ^= 1
    for bad in (bytes(corrupted), source + b'private trailing content'):
        with pytest.raises(ImageProviderError): PillowPngDecoder().canonicalize(bad)
    with pytest.raises(ImageProviderError): PillowPngDecoder(max_bytes=32).canonicalize(source)


@pytest.mark.asyncio
async def test_review_refuses_noncanonical_or_mislabeled_pixels_before_dispatch():
    seen = []
    for data in (png(metadata=True), png(width=1, height=1), png()[:-1]):
        art = artifact(png=data, content_digest=sha256(data).hexdigest())
        with pytest.raises(ImageProviderError):
            await reviewer(lambda http: seen.append(http)).review(art, request())
    assert not seen


def test_decoder_accepts_only_fully_opaque_alpha_without_changing_pixels():
    from PIL import Image
    for alpha in (255, 128):
        output = io.BytesIO()
        with Image.new('RGBA', (1024, 1024), (12, 34, 56, alpha)) as image:
            image.save(output, format='PNG')
        if alpha != 255:
            with pytest.raises(ImageProviderError):
                PillowPngDecoder().canonicalize(output.getvalue())
            continue
        decoded = PillowPngDecoder().canonicalize(output.getvalue())
        with Image.open(io.BytesIO(decoded.png)) as image:
            assert image.mode == 'RGB' and image.getpixel((99, 99)) == (12, 34, 56)


def test_decoder_rejects_truncation_tolerance_without_mutating_global_settings(monkeypatch):
    from PIL import ImageFile
    monkeypatch.setattr(ImageFile, 'LOAD_TRUNCATED_IMAGES', True)
    with pytest.raises(ImageProviderError):
        PillowPngDecoder().canonicalize(png())
    assert ImageFile.LOAD_TRUNCATED_IMAGES is True


def test_decoder_rejects_truncated_deflate_with_valid_container_crc():
    source = png()
    size = struct.unpack_from('>I', source, 33)[0]
    compressed = source[41:41 + size]
    truncated = source[:33] + chunk(b'IDAT', compressed[:len(compressed) // 2]) + chunk(b'IEND', b'')
    with pytest.raises(ImageProviderError):
        PillowPngDecoder().canonicalize(truncated)


@pytest.mark.parametrize('factory,options', [
    (OpenAIImageOptions, {'model': '', 'quality': 'low'}),
    (OpenAIImageOptions, {'model': 'chatgpt-subscription', 'quality': 'low'}),
    (OpenAIImageOptions, {'model': IMAGE_MODEL, 'quality': 'auto'}),
    (OpenAIVisionOptions, {'model': REVIEW_MODEL, 'max_output_tokens': 513}),
    (OpenAIVisionOptions, {'model': REVIEW_MODEL, 'max_output_tokens': True}),
])
def test_options_require_explicit_bounded_model_and_quality(factory, options):
    with pytest.raises(ValueError): factory(**options)


@pytest.mark.parametrize('kind', ['image', 'review'])
@pytest.mark.parametrize('key', ['plain-secret', SecretStr('oauth-token-not-api-key')])
def test_transports_do_not_accept_raw_or_subscription_credentials(kind, key):
    with pytest.raises(ValueError):
        if kind == 'image':
            OpenAIImageBackend(api_key=key, options=OpenAIImageOptions(IMAGE_MODEL, 'low'))
        else:
            OpenAIVisionReviewBackend(api_key=key, options=OpenAIVisionOptions(REVIEW_MODEL, 512))
