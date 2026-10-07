"""Offline generated pixels, fake opaque credentials and injected HTTP only."""
import asyncio
import base64
import gzip
from dataclasses import replace
from hashlib import sha256
import json
import random
import zlib
from types import SimpleNamespace

import httpx
from pydantic import SecretStr
import pytest

from mira.adapters.media._openai_http import ImageProviderError
from mira.adapters.media.subscription_vision_review import (
    SubscriptionVisionOptions, SubscriptionVisionReviewBackend,
)
from mira.domain.story_images import REQUIRED_PIXEL_CHECKS
from tests.contracts.test_story_image_adapters import (
    ByteStream, REVIEW_MODEL, artifact, png, request, review_document,
)

ENDPOINT = 'https://chatgpt.com/backend-api/codex/responses'
SECRET = 'synthetic-opaque-token-not-real'


class Credentials:
    def __init__(self):
        self.calls = 0

    async def get_credentials(self):
        self.calls += 1
        return SimpleNamespace(access_token=SecretStr(SECRET),
                               account_id='synthetic-account', residency='synthetic-region')


def event(kind, **value):
    return ('event: ' + kind + '\ndata: ' + json.dumps({'type': kind, **value}) + '\n\n').encode()


def message(text=None, **changes):
    return {'type': 'message', 'id': 'msg-test', 'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': text or json.dumps(review_document())}],
            **changes}


def stream_bytes(document=None, *, text=None, output=None, terminal=None):
    item = message(text=text or json.dumps(document or review_document()))
    return (event('response.output_item.done', output_index=0, item=item)
            + event('response.completed', response={'status': 'completed', 'model': REVIEW_MODEL,
                'output': [item] if output is None else output, **(terminal or {})}))


def response(raw=None, *, status=200, headers=None, stream=None):
    return httpx.Response(status, headers={'content-type': 'text/event-stream', **(headers or {})},
        stream=stream or ByteStream([stream_bytes() if raw is None else raw]))


def reviewer(handler, *, credentials=None, **options):
    return SubscriptionVisionReviewBackend(credential_source=credentials or Credentials(),
        options=SubscriptionVisionOptions(REVIEW_MODEL), transport=httpx.MockTransport(handler),
        **options)


@pytest.mark.asyncio
async def test_exact_multimodal_route_model_headers_and_canonical_pixels():
    art, req, seen = artifact(), request(), []
    credentials = Credentials()
    def handler(http):
        seen.append(http)
        assert str(http.url) == ENDPOINT and http.method == 'POST'
        assert http.headers['authorization'] == 'Bearer ' + SECRET
        assert http.headers['chatgpt-account-id'] == 'synthetic-account'
        assert http.headers['x-openai-internal-codex-residency'] == 'synthetic-region'
        assert http.headers['originator'] == 'mira'
        assert http.headers['user-agent'] == 'MIRA/0.4.1'
        assert http.headers['accept'] == 'text/event-stream'
        assert http.headers['accept-encoding'] == 'identity'
        assert 'x-codex-image-turn-id' not in http.headers
        body = json.loads(http.content)
        assert set(body) == {'model', 'instructions', 'input', 'tools', 'store', 'stream'}
        assert body['model'] == REVIEW_MODEL and body['tools'] == []
        assert body['store'] is False and body['stream'] is True
        assert len(body['input']) == 1 and body['input'][0]['role'] == 'user'
        text, image = body['input'][0]['content']
        assert text['type'] == 'input_text'
        prompt = json.loads(text['text'])
        assert set(prompt) == {'request_id', 'specification_digest', 'checked_content_digest',
            'policy_revision', 'specification', 'required_checks', 'response_schema', 'image_dimensions'}
        assert prompt['image_dimensions'] == {'width': art.width, 'height': art.height}
        assert prompt['specification'] == req.specification
        assert prompt['checked_content_digest'] == art.content_digest
        assert set(prompt['required_checks']) == set(REQUIRED_PIXEL_CHECKS)
        assert set(image) == {'type', 'image_url'} and image['type'] == 'input_image'
        assert image['image_url'].startswith('data:image/png;base64,')
        assert base64.b64decode(image['image_url'].split(',')[1], validate=True) == art.png
        for private in (req.session_id, req.parent_request_id, req.admission_reference, art.resource_id):
            assert private not in http.content.decode()
        return response()
    result = await reviewer(handler, credentials=credentials).review(art, req)
    assert credentials.calls == 1 and len(seen) == 1
    assert result.checked_content_digest == sha256(art.png).hexdigest()
    assert result.specification_digest == req.specification_digest
    assert result.request_id == req.request_id and result.policy_revision == req.policy_revision
    assert all(check.result == 'pass' for check in result.checks)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['empty_snapshot', 'omitted_snapshot_model', 'deltas', 'crlf', 'fragmented'])
async def test_supported_complete_stream_shapes(mode):
    raw = stream_bytes(output=[])
    if mode == 'omitted_snapshot_model':
        raw = event('response.output_item.done', output_index=0, item=message())
        raw += event('response.completed', response={'status': 'completed'})
    elif mode == 'deltas':
        value = json.dumps(review_document())
        raw = event('response.output_text.delta', output_index=0, content_index=0,
                    item_id='msg-test', delta=value) + raw
    elif mode == 'crlf':
        raw = raw.replace(b'\n', b'\r\n')
    chunks = [bytes([value]) for value in raw] if mode == 'fragmented' else [raw]
    stream = ByteStream(chunks)
    result = await reviewer(lambda _: response(stream=stream)).review(artifact(), request())
    assert result.checked_content_digest == artifact().content_digest and stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('result', ['fail', 'unassessable'])
async def test_negative_observations_are_preserved(result):
    doc = review_document(); doc['checks']['allowed_scene'] = result
    observed = await reviewer(lambda _: response(stream_bytes(doc))).review(artifact(), request())
    assert observed.checks[0].result == result


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', [
    {'request_id': 'other'}, {'specification_digest': '0' * 64},
    {'checked_content_digest': '0' * 64}, {'policy_revision': 'other'}, {'extra': 'unsafe'},
    {'checks': {}}, {'checks': {key: 'unknown' for key in REQUIRED_PIXEL_CHECKS}},
    {'checks': {key: True for key in REQUIRED_PIXEL_CHECKS}},
    {'observed_description': 'x' * 513}, {'observed_description': '\ud800'},
])
async def test_bad_binding_or_unknown_check_never_yields_observation(mutation):
    doc = {**review_document(), **mutation}
    with pytest.raises(ImageProviderError):
        await reviewer(lambda _: response(stream_bytes(doc))).review(artifact(), request())


def invalid_stream(mode):
    if mode == 'missing_terminal': return event('response.output_item.done', output_index=0, item=message())
    if mode == 'delta_only': return event('response.output_text.delta', output_index=0,
        delta=json.dumps(review_document())) + event('response.completed', response={'status': 'completed'})
    if mode == 'partial_json': return stream_bytes(text='{"checks":')
    if mode == 'duplicate_json': return stream_bytes(text='{"checks":{},"checks":{}}')
    if mode == 'nan_json': return stream_bytes(text='{"value":NaN}')
    if mode == 'unknown_event': return event('response.future_unknown') + stream_bytes()
    if mode == 'event_type_mismatch': return b'event: response.completed\ndata: {"type":"response.failed"}\n\n'
    if mode == 'partial_sse': return stream_bytes() + b'data: {"type":'
    if mode == 'utf8': return stream_bytes() + b'\xff\n\n'
    if mode == 'wrong_model': return stream_bytes(terminal={'model': 'different'})
    if mode == 'incomplete': return stream_bytes(terminal={'status': 'incomplete'})
    if mode == 'incomplete_details': return stream_bytes(terminal={'incomplete_details': {'reason': 'limit'}})
    if mode == 'error': return stream_bytes(terminal={'error': {'message': 'RAW_PROVIDER_SECRET'}})
    if mode == 'duplicate_terminal': return stream_bytes() + stream_bytes()
    if mode == 'snapshot_mismatch': return stream_bytes(output=[message(text='{}')])
    if mode == 'unmatched_delta': return event('response.output_text.delta', output_index=7, delta='x') + stream_bytes()
    if mode == 'delta_mismatch': return event('response.output_text.delta', output_index=0, delta='x') + stream_bytes()
    if mode == 'tool': return event('response.output_item.added', output_index=1,
        item={'type': 'image_generation_call'}) + stream_bytes()
    if mode == 'unknown_item': return event('response.output_item.added', output_index=1,
        item={'type': 'future_tool'}) + stream_bytes()
    if mode == 'two_messages': return event('response.output_item.done', output_index=1,
        item=message(id='second')) + stream_bytes(output=[])
    if mode == 'commentary': return event('response.output_item.done', output_index=1,
        item=message(phase='commentary')) + stream_bytes(output=[])
    if mode == 'refusal': return event('response.refusal.delta', delta='not allowed') + stream_bytes()
    if mode == 'output_limit': return stream_bytes(text='x' * 8193)
    if mode == 'line_limit': return b':' + b'x' * 16385 + b'\n\n' + stream_bytes()
    if mode == 'event_limit': return b'data:{"type":"response.created"}\n\n' * 1025 + stream_bytes()
    raise AssertionError(mode)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['missing_terminal', 'delta_only', 'partial_json', 'duplicate_json',
    'nan_json', 'unknown_event', 'event_type_mismatch', 'partial_sse', 'utf8',
    'incomplete', 'incomplete_details', 'error', 'duplicate_terminal', 'snapshot_mismatch',
    'unmatched_delta', 'delta_mismatch', 'tool', 'unknown_item', 'two_messages',
    'refusal', 'output_limit', 'line_limit', 'event_limit'])
async def test_invalid_or_partial_stream_never_approves(mode, capsys, caplog):
    seen = []
    def handler(http):
        seen.append(http)
        return response(invalid_stream(mode))
    with pytest.raises(ImageProviderError) as caught:
        await reviewer(handler).review(artifact(), request())
    assert len(seen) == 1 and str(seen[0].url) == ENDPOINT
    assert 'RAW_PROVIDER_SECRET' not in str(caught.value)
    assert SECRET not in caplog.text + capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['http401', 'http403', 'http429', 'http500', 'redirect',
    'json_mime', 'bad_mime_parameter', 'encoding', 'length_invalid', 'length_oversized',
    'length_mismatch', 'wire_limit', 'transport'])
async def test_http_failures_are_safe_and_single_attempt(mode):
    seen = []
    def handler(http):
        seen.append(http)
        if mode.startswith('http'): return response(status=int(mode[4:]))
        if mode == 'redirect': return response(status=302, headers={'location': 'https://api.openai.com/v1/responses'})
        if mode == 'transport': raise httpx.ConnectError('RAW_TRANSPORT_SECRET')
        headers = {'json_mime': {'content-type': 'application/json'},
            'bad_mime_parameter': {'content-type': 'text/event-stream;invalid'},
            'encoding': {'content-encoding': 'gzip'}, 'length_invalid': {'content-length': 'bad'},
            'length_oversized': {'content-length': '65537'},
            'length_mismatch': {'content-length': '1'}}.get(mode, {})
        return response(b':' + b'x' * 65536 if mode == 'wire_limit' else None, headers=headers)
    with pytest.raises(ImageProviderError) as caught:
        await reviewer(handler).review(artifact(), request())
    assert len(seen) == 1 and str(seen[0].url) == ENDPOINT
    assert 'RAW_TRANSPORT_SECRET' not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['bad_digest', 'wrong_request', 'wrong_spec', 'wrong_policy',
    'wrong_width', 'wrong_mime', 'corrupt_pixels', 'noncanonical', 'resources', 'bad_spec_digest'])
async def test_invalid_inputs_fail_before_credentials_or_http(mode):
    art, req, credentials, seen = artifact(), request(), Credentials(), []
    if mode == 'bad_digest': art = replace(art, content_digest='0' * 64)
    if mode == 'wrong_request': art = replace(art, request_id='other')
    if mode == 'wrong_spec': art = replace(art, specification_digest='0' * 64)
    if mode == 'wrong_policy': art = replace(art, policy_revision='other')
    if mode == 'wrong_width': art = replace(art, width=512)
    if mode == 'wrong_mime': art = replace(art, media_type='image/jpeg')
    if mode in ('corrupt_pixels', 'noncanonical'):
        data = b'\x89PNG\r\n\x1a\nwrong' if mode == 'corrupt_pixels' else png(metadata=True)
        art = replace(art, png=data, content_digest=sha256(data).hexdigest())
    if mode == 'resources': req = replace(req, allowed_resource_ids=('unapproved',))
    if mode == 'bad_spec_digest': req = replace(req, specification_digest='0' * 64)
    with pytest.raises(ImageProviderError):
        await reviewer(lambda http: seen.append(http), credentials=credentials).review(art, req)
    assert not seen and credentials.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['credentials', 'bytes', 'cleanup'])
@pytest.mark.parametrize('cancel', ['external', 'timeout'])
async def test_suppressed_cancellation_never_revives_late_review(stage, cancel):
    entered = asyncio.Event()
    credentials, seen = Credentials(), []
    async def block():
        entered.set()
        try: await asyncio.Future()
        except asyncio.CancelledError: pass
    class LateCredentials(Credentials):
        async def get_credentials(self):
            await block()
            return await super().get_credentials()
    class LateStream(ByteStream):
        async def __aiter__(self):
            if stage == 'bytes': await block()
            yield stream_bytes()
        async def aclose(self):
            if stage == 'cleanup': await block()
            await super().aclose()
    if stage == 'credentials': credentials = LateCredentials()
    def handler(http):
        seen.append(http)
        return response(stream=LateStream([]))
    backend = reviewer(handler, credentials=credentials, timeout_seconds=.15 if cancel == 'timeout' else 2)
    task = asyncio.create_task(backend.review(artifact(), request()))
    await asyncio.wait_for(entered.wait(), 2)
    if cancel == 'external': task.cancel()
    expected = asyncio.CancelledError if cancel == 'external' else ImageProviderError
    with pytest.raises(expected): await asyncio.wait_for(task, 2)
    assert len(seen) == (0 if stage == 'credentials' else 1)


@pytest.mark.asyncio
async def test_auth_failure_is_sanitized_before_http():
    class BadCredentials(Credentials):
        async def get_credentials(self):
            raise RuntimeError('RAW_AUTH_SECRET')
    seen = []
    with pytest.raises(ImageProviderError) as caught:
        await reviewer(lambda http: seen.append(http), credentials=BadCredentials()).review(artifact(), request())
    assert not seen and 'RAW_AUTH_SECRET' not in str(caught.value)


@pytest.mark.parametrize('options', [{'timeout_seconds': 0}, {'timeout_seconds': float('nan')},
    {'max_wire_bytes': 65537}, {'max_wire_bytes': True}])
def test_invalid_limits_rejected(options):
    with pytest.raises(ValueError): reviewer(lambda _: response(), **options)


def test_invalid_model_rejected():
    with pytest.raises(ValueError): SubscriptionVisionOptions('unsafe\nmodel')


@pytest.mark.asyncio
@pytest.mark.parametrize('suffix', [b'', b'\n'])
async def test_complete_json_at_sse_eof_matches_existing_subscription_transport(suffix):
    raw = stream_bytes().rstrip(b'\n') + suffix
    result = await reviewer(lambda _: response(raw)).review(artifact(), request())
    assert result.checked_content_digest == artifact().content_digest


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['missing_mime', 'gzip', 'deflate', 'raw_deflate',
    'resolved_model', 'split_final_messages', 'commentary_then_final',
    'codex.response.metadata', 'response.metadata', 'responsesapi.websocket_timing'])
async def test_grounded_subscription_transport_compatibility(mode):
    raw, headers = stream_bytes(), {'content-type': 'text/event-stream'}
    if mode == 'missing_mime': headers = {}
    if mode == 'gzip':
        raw = gzip.compress(raw); headers['content-encoding'] = 'gzip'
    if mode in ('deflate', 'raw_deflate'):
        raw = zlib.compress(raw)
        if mode == 'raw_deflate': raw = raw[2:-4]
        headers['content-encoding'] = 'deflate'
    if mode == 'resolved_model': raw = stream_bytes(terminal={'model': REVIEW_MODEL + '-2026-10-06'})
    if mode == 'split_final_messages':
        text = json.dumps(review_document()); split = len(text) // 2
        raw = (event('response.output_item.done', output_index=0, item=message(text=text[:split]))
               + event('response.output_item.done', output_index=1, item=message(text=text[split:], id='second'))
               + event('response.completed', response={'status': 'completed', 'output': []}))
    if mode == 'commentary_then_final':
        raw = event('response.output_item.done', output_index=1, item=message(
            text='Inspecting the image.', id='comment', phase='commentary')) + stream_bytes(output=[])
    if mode in ('codex.response.metadata', 'response.metadata', 'responsesapi.websocket_timing'):
        raw = event(mode, data={'synthetic_counter': 1}) + stream_bytes()
    headers['content-length'] = str(len(raw))
    result = await reviewer(lambda _: httpx.Response(200, headers=headers,
        stream=ByteStream([raw]))).review(artifact(), request())
    assert result.checked_content_digest == artifact().content_digest


@pytest.mark.asyncio
@pytest.mark.parametrize('encoding', ['gzip', 'deflate'])
async def test_compressed_response_bounds_both_wire_and_decoded_bytes(encoding):
    raw = b':' + b'x' * 100_000 + b'\n\n' + stream_bytes()
    packed = gzip.compress(raw) if encoding == 'gzip' else zlib.compress(raw)
    assert len(packed) < 65_536
    with pytest.raises(ImageProviderError):
        await reviewer(lambda _: response(packed, headers={'content-encoding': encoding})).review(
            artifact(), request())


@pytest.mark.asyncio
async def test_large_canonical_png_uses_image_request_budget():
    import io
    from PIL import Image
    from mira.adapters.media.png_decoder import PillowPngDecoder
    # Seeded synthetic pixels; the real PNG exceeds the text route's request cap.
    data = random.Random(191).randbytes(1024 * 1024 * 3)
    out = io.BytesIO()
    with Image.frombytes('RGB', (1024, 1024), data) as image:
        image.save(out, format='PNG')
    canonical = PillowPngDecoder().canonicalize(out.getvalue()).png
    art = artifact(png=canonical, content_digest=sha256(canonical).hexdigest())
    assert len(canonical) > 262_144
    def handler(http):
        assert len(http.content) > 262_144
        body = json.loads(http.content)
        sent = body['input'][0]['content'][1]['image_url'].split(',')[1]
        assert base64.b64decode(sent, validate=True) == canonical
        return response(stream_bytes(review_document(art=art)))
    result = await reviewer(handler).review(art, request())
    assert result.checked_content_digest == sha256(canonical).hexdigest()


def partitioned_review(document, parts):
    text = json.dumps(document)
    assert 1 <= parts <= len(text)
    deltas = [text[len(text) * i // parts:len(text) * (i + 1) // parts]
              for i in range(parts)]
    assert ''.join(deltas) == text and all(deltas)
    return (b''.join(event('response.output_text.delta', output_index=0,
                          content_index=0, item_id='msg-test', delta=delta)
                     for delta in deltas) + stream_bytes(document))


@pytest.mark.asyncio
@pytest.mark.parametrize('parts', [1, 126, 127, 128, 256])
@pytest.mark.parametrize('encoding', ['identity', 'gzip'])
async def test_small_strict_review_is_invariant_to_valid_delta_partition(parts, encoding):
    raw = partitioned_review(review_document(), parts)
    assert len(raw) < 65_536
    if encoding == 'gzip': raw = gzip.compress(raw)
    seen = []
    def handler(http):
        seen.append(http)
        return response(raw, headers={'content-encoding': encoding})
    result = await reviewer(handler).review(artifact(), request())
    assert len(seen) == 1
    assert result.checked_content_digest == artifact().content_digest
    assert all(check.result == 'pass' for check in result.checks)


@pytest.mark.asyncio
@pytest.mark.parametrize('count', [1024, 1025])
async def test_review_event_budget_remains_bounded_and_has_exact_error(count):
    raw = b'data:{"type":"response.created"}\n\n' * (count - 2) + stream_bytes()
    assert len(raw) < 65_536
    backend = reviewer(lambda _: response(raw))
    if count == 1024:
        result = await backend.review(artifact(), request())
        assert result.request_id == request().request_id
    else:
        with pytest.raises(ImageProviderError, match='^subscription_review_event_limit$'):
            await backend.review(artifact(), request())


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation,code', [
    ({'request_id': 'different-synthetic-request'}, 'subscription_review_observation_binding'),
    ({'checked_content_digest': '0' * 64}, 'subscription_review_observation_binding'),
    ({'unexpected': 'field'}, 'subscription_review_observation_binding'),
    ({'checks': {}}, 'subscription_review_checks'),
])
async def test_fragmented_review_preserves_strict_schema_and_request_binding(mutation, code):
    raw = partitioned_review({**review_document(), **mutation}, 160)
    with pytest.raises(ImageProviderError, match='^' + code + '$'):
        await reviewer(lambda _: response(raw)).review(artifact(), request())


@pytest.mark.asyncio
async def test_fragmented_review_still_rejects_unknown_metadata():
    raw = event('response.future_unknown') + partitioned_review(review_document(), 160)
    with pytest.raises(ImageProviderError, match='^subscription_review_event$'):
        await reviewer(lambda _: response(raw)).review(artifact(), request())


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,code', [
    ('wire', 'subscription_review_wire_limit'),
    ('decoded', 'subscription_review_decoded_limit'),
    ('line', 'subscription_review_line_limit'),
    ('output', 'subscription_review_output_limit'),
    ('protocol', 'subscription_review_response'),
])
async def test_review_event_limit_does_not_replace_other_closed_errors(mode, code):
    raw = (b':' + b'x' * 65_536 if mode == 'wire' else
           event('response.output_text.delta', output_index=7, delta='x') + stream_bytes())
    headers = {}
    if mode == 'decoded':
        raw = gzip.compress(b':' + b'x' * 100_000 + b'\n\n' + stream_bytes())
        headers = {'content-encoding': 'gzip'}
    if mode == 'line': raw = b':' + b'x' * 16_385 + b'\n\n' + stream_bytes()
    if mode == 'output': raw = stream_bytes(text='x' * 8193, output=[])
    with pytest.raises(ImageProviderError, match='^' + code + '$'):
        await reviewer(lambda _: response(raw, headers=headers)).review(artifact(), request())
