"""Real synthetic PNG pixels and MockHTTP only; no account qualification."""
import base64
from hashlib import sha256
import io
import json

from PIL import Image
import pytest

from tests.contracts.test_native_image_startup import Harness, argv, wait_image
from tests.contracts.test_conversation_first import session, submit, settled
from tests.contracts.test_story_images import image_body
from tests.contracts.test_story_image_adapters import response
from tests.contracts.test_subscription_images import image_body as subscription_body
from tools import live_provider as cli


def landscape_png(size=(1536, 1024), mode='RGB'):
    image = Image.new(mode, size, (10, 20, 30, 255) if mode == 'RGBA' else (10, 20, 30))
    image.paste((180, 60, 20, 255) if mode == 'RGBA' else (180, 60, 20),
                (size[0] - 128, 0, size[0], 128))
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


@pytest.mark.parametrize('size', [(1536, 1024), (1024, 1024), (1024, 1536)])
def test_subscription_actual_dimensions_reach_bound_resource_and_shown_tool_result(tmp_path, monkeypatch, size):
    original = landscape_png(size)
    harness = Harness(monkeypatch, 'chatgpt_subscription')
    def image(request):
        harness.image_requests.append(request)
        body = json.loads(request.content)
        assert (body['size'], body['quality'], body['model'], body['n']) == ('1024x1024', 'auto', 'gpt-image-2', 1)
        return response(subscription_body(original, size='1536x1024'))
    harness.image = image
    review = harness.review
    def checked_review(http):
        body = json.loads(http.content)
        criteria = json.loads(body['input'][0]['content'][0]['text'])
        assert criteria['image_dimensions'] == {'width': size[0], 'height': size[1]}
        return review(http)
    harness.review = checked_review
    def inspect(client):
        path, headers = session(client)
        submit(client, path, headers, text='Please illustrate an empty fictional blue lakeside.')
        state = wait_image(client, path, headers)
        assert state['story_image']['state'] == 'qualified'
        assert len(harness.image_requests) == len(harness.review_requests) == 1
        photo = next(effect for effect in state['active_grants'] if effect['kind'] == 'media')
        resource, body = image_body(photo)
        fetched = client.post(path + '/story-images/' + resource, headers=headers, json=body)
        assert fetched.status_code == 200 and fetched.content == harness.reviewed_pixels
        assert sha256(fetched.content).hexdigest() == body['content_digest']
        with Image.open(io.BytesIO(original)) as source, Image.open(io.BytesIO(fetched.content)) as actual:
            assert actual.size == source.size == size
            assert actual.tobytes() == source.tobytes()
        actor = next(iter(harness.app.state.container.sessions._sessions.values())).actor
        artifact = actor._story_images.artifact(resource)
        assert (artifact.width, artifact.height) == size
        assert not harness.results
        wrong = {**body, 'content_digest': '0' * 64}
        assert client.post(path + '/story-images/' + resource, headers=headers, json=wrong).status_code == 409
        receipt = {key: photo[key] for key in ('digest', 'output_epoch', 'activity_seq')}
        receipt.update(effect_id=photo['id'], presentation_seq=1)
        assert client.post(path + '/receipts', headers=headers, json={**receipt, 'digest': 'wrong'}).status_code in (409, 422)
        assert not harness.results
        assert client.post(path + '/receipts', headers=headers, json=receipt).status_code == 200
        final = settled(client, path, headers)
        assert final['last_error'] is None and final['sealed']
        assert len(harness.results) == 1 and harness.results[0]['shown'] is True
        assert harness.results[0]['status'] == 'shown'
        assert len(harness.image_requests) == len(harness.review_requests) == 1
        assert actor._story_images.attempts == 1
    harness.inspect = inspect
    assert cli.main(argv(tmp_path)) == 0


@pytest.mark.parametrize('size', [(1536, 1024), (1024, 1536)])
def test_api_returned_non_square_fails_before_review_without_refund(tmp_path, monkeypatch, size):
    from tests.contracts.test_story_image_adapters import image_reply
    harness = Harness(monkeypatch, 'openai_api')
    def image(request):
        harness.image_requests.append(request)
        assert json.loads(request.content)['size'] == '1024x1024'
        return response(image_reply(landscape_png(size)))
    harness.image = image
    def inspect(client):
        path, headers = session(client)
        submit(client, path, headers, text='Please illustrate an empty fictional blue lakeside.')
        state = wait_image(client, path, headers)
        assert state['story_image']['state'] == 'failed'
        final = settled(client, path, headers)
        assert not any(e['kind'] == 'media' for e in final['active_grants'])
        assert harness.results[0]['status'] == 'failed' and harness.results[0]['shown'] is False
        actor = next(iter(harness.app.state.container.sessions._sessions.values())).actor
        assert actor._story_images.operation_diagnostic.failure_reason == 'image_png_dimensions'
        assert actor._story_images.operation_readiness() == ('budget_exhausted', 0)
    harness.inspect = inspect
    assert cli.main(argv(tmp_path, 'openai_api')) == 0
    assert len(harness.image_requests) == 1 and len(harness.review_requests) == 0


def decoder():
    from mira.adapters.media.png_decoder import PillowPngDecoder
    from mira.domain.story_images import SUBSCRIPTION_OUTPUT_POLICY
    return PillowPngDecoder(output_dimension_policy=SUBSCRIPTION_OUTPUT_POLICY)


@pytest.mark.parametrize('size', [(0, 1024), (1536, 1536), (2048, 1024), (1024, 2048), (1535, 1024), (2**31, 1024)])
def test_dimension_policy_rejects_unsupported_and_oversized_before_decompression(size):
    import struct
    from tests.contracts.test_story_image_adapters import chunk
    from mira.adapters.media._openai_http import ImageProviderError
    data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', *size, 8, 2, 0, 0, 0))
    with pytest.raises(ImageProviderError, match='image_png_dimensions'):
        decoder().canonicalize(data)


@pytest.mark.parametrize('mode,reason', [
    ('crc', 'image_png_crc'), ('truncated', 'image_png_truncated'),
    ('alpha', 'image_png_transparency'), ('animation', 'image_png_animation'),
    ('extra_raster', 'image_png_deflate_limit'), ('short_raster', 'image_png_deflate_incomplete'),
    ('no_adler', 'image_png_deflate_incomplete'), ('second_stream', 'image_png_deflate_trailing'),
    ('extra_tail', 'image_png_deflate_trailing'), ('input_byte_cap', 'image_png_input'),
])
def test_landscape_retains_container_pixel_opacity_and_byte_guards(mode, reason):
    import struct
    import zlib
    from tests.contracts.test_story_image_adapters import chunk, png
    from mira.adapters.media._openai_http import ImageProviderError
    from mira.adapters.media.png_decoder import PillowPngDecoder
    from mira.domain.story_images import SUBSCRIPTION_OUTPUT_POLICY
    data = png(width=1536, height=1024)
    selected = decoder()
    if mode == 'crc':
        data = data[:29] + bytes([data[29] ^ 1]) + data[30:]
    elif mode == 'truncated': data = data[:-5]
    elif mode == 'alpha':
        source = Image.new('RGBA', (1536, 1024), (10, 20, 30, 254))
        output = io.BytesIO(); source.save(output, format='PNG'); data = output.getvalue()
    elif mode == 'animation': data = data[:33] + chunk(b'acTL', struct.pack('>II', 1, 0)) + data[33:]
    elif mode == 'input_byte_cap':
        selected = PillowPngDecoder(max_bytes=len(data)-1, output_dimension_policy=SUBSCRIPTION_OUTPUT_POLICY)
    else:
        length = struct.unpack_from('>I', data, 33)[0]
        compressed = data[41:41+length]
        raster = zlib.decompress(compressed)
        if mode == 'extra_raster': compressed = zlib.compress(raster + b'\0')
        elif mode == 'short_raster': compressed = zlib.compress(raster[:-1])
        elif mode == 'no_adler': compressed = compressed[:-4]
        elif mode == 'second_stream': compressed += zlib.compress(b'another')
        elif mode == 'extra_tail': compressed += b'extra'
        data = data[:33] + chunk(b'IDAT', compressed) + chunk(b'IEND', b'')
    with pytest.raises(ImageProviderError, match=reason): selected.canonicalize(data)


def test_shared_decoder_uses_each_validated_raster_dimensions_without_cross_job_state():
    from concurrent.futures import ThreadPoolExecutor
    sizes = [(1536, 1024), (1024, 1024), (1024, 1536)] * 3
    inputs = [landscape_png(size) for size in sizes]
    selected = decoder()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(selected.canonicalize, inputs))
    for size, source, result in zip(sizes, inputs, results):
        assert (result.width, result.height) == size
        with Image.open(io.BytesIO(source)) as original, Image.open(io.BytesIO(result.png)) as actual:
            assert actual.size == size and actual.tobytes() == original.tobytes()


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['wrong_dimensions', 'wrong_content', 'unbound_policy', 'api_policy'])
async def test_review_rejects_unbound_dimensions_pixels_or_route_policy_before_http(mutation):
    from dataclasses import replace
    from mira.adapters.media._openai_http import ImageProviderError
    from mira.domain.story_images import SUBSCRIPTION_OUTPUT_POLICY
    from tests.contracts.test_story_image_adapters import request, artifact, SYNTHETIC_KEY, REVIEW_MODEL
    from tests.contracts.test_subscription_vision_review import reviewer
    from mira.adapters.media.openai_vision_review import OpenAIVisionReviewBackend, OpenAIVisionOptions
    import httpx
    req = request(output_dimension_policy=SUBSCRIPTION_OUTPUT_POLICY,
        policy_revision='pixels-v1:' + SUBSCRIPTION_OUTPUT_POLICY)
    canonical = decoder().canonicalize(landscape_png())
    art = artifact(req, png=canonical.png, content_digest=sha256(canonical.png).hexdigest(), width=1536)
    backend = reviewer(lambda _: pytest.fail('invalid binding cannot reach review HTTP'))
    if mutation == 'wrong_dimensions': art = replace(art, width=1024)
    elif mutation == 'wrong_content': art = replace(art, content_digest='0'*64)
    elif mutation == 'unbound_policy': req = replace(req, policy_revision='pixels-v1')
    else:
        backend = OpenAIVisionReviewBackend(api_key=SYNTHETIC_KEY,
            options=OpenAIVisionOptions(REVIEW_MODEL, 512),
            transport=httpx.MockTransport(lambda _: pytest.fail('API cannot admit subscription output policy')))
    with pytest.raises(ImageProviderError): await backend.review(art, req)


def test_declaration_distinguishes_requested_shape_and_bounded_returned_sizes():
    from dataclasses import replace
    from mira.bootstrap.story_image_provider import StoryImageOptions, describe_story_images
    options = StoryImageOptions(enabled=True, provider='chatgpt_subscription', image_model='gpt-image-2',
        review_model='gpt-6-luna', quality='auto', authorize_data_to_openai=True,
        authorize_subscription_usage=True, review_max_output_tokens=None)
    value = describe_story_images(options=options, story_enabled=True)
    assert value['size'] == '1024x1024'
    assert value['accepted_output_sizes'] == ['1024x1024', '1536x1024', '1024x1536']
    assert value['automatic_retries'] == 0 and value['max_output_bytes_per_image'] == 8388608
    assert value['max_attempts_per_process'] == value['max_reviews_per_process'] == 1
    assert value['subscription_entitlement'] == 'not_checked' and value['live_verified'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['generation', 'review'])
@pytest.mark.parametrize('action', ['stop', 'new_input', 'close'])
async def test_landscape_transport_retains_job_on_input_and_cancels_explicit_fences(stage, action):
    import asyncio
    import httpx
    from mira.bootstrap.story_image_provider import StoryImageOptions, create_story_image_factory
    from tests.contracts.test_image_operation_diagnostics import native_actor, image_turn
    from tests.contracts.test_luna_tool_actor import ToolTurn, text_candidate
    from tests.contracts.test_subscription_images import Credentials
    from tests.contracts.test_subscription_vision_review import response as vision_response, stream_bytes
    from mira.domain.story_images import REQUIRED_PIXEL_CHECKS
    from mira.domain.models import EffectKind
    entered, resume, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []
    async def barrier():
        entered.set()
        try: await resume.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await resume.wait()
    async def image(http):
        calls.append('image')
        if stage == 'generation': await barrier()
        return response(subscription_body(landscape_png()))
    async def review(http):
        calls.append('review')
        body = json.loads(http.content)
        criteria = json.loads(body['input'][0]['content'][0]['text'])
        pixels = base64.b64decode(body['input'][0]['content'][1]['image_url'].split(',')[1])
        with Image.open(io.BytesIO(pixels)) as raster: assert raster.size == (1536, 1024)
        assert criteria['checked_content_digest'] == sha256(pixels).hexdigest()
        if stage == 'review': await barrier()
        document = {key: criteria[key] for key in ('request_id', 'specification_digest',
            'checked_content_digest', 'policy_revision')}
        document.update(checks={key: 'pass' for key in REQUIRED_PIXEL_CHECKS}, observed_description='Empty lake.')
        return vision_response(stream_bytes(document))
    options = StoryImageOptions(enabled=True, provider='chatgpt_subscription', image_model='gpt-image-2',
        review_model='gpt-6-luna', quality='auto', authorize_data_to_openai=True,
        authorize_subscription_usage=True, authorize_custom_brief=True, review_max_output_tokens=None)
    runtime = create_story_image_factory(options=options, story_enabled=True, credential_source=Credentials(),
        image_transport=httpx.MockTransport(image), review_transport=httpx.MockTransport(review))(None)
    text_turn = ToolTurn(); text_turn.call = text_candidate()
    actor = native_actor(runtime, [image_turn('old'), text_turn])
    closing = None
    try:
        await actor.submit(request_id='turn1', activity_seq=1, cutoff=0, text='Imagine an empty lake.')
        await asyncio.wait_for(entered.wait(), 2)
        pending = tuple(actor._image_tasks)
        if action == 'stop': await actor.stop(activity_seq=2, cutoff=0)
        elif action == 'new_input': await actor.submit(request_id='turn2', activity_seq=2, cutoff=0, text='Just talk.')
        else: closing = asyncio.create_task(actor.close())
        if action=='new_input':assert not cancelled.is_set()
        else:await asyncio.wait_for(cancelled.wait(),2)
        assert runtime.operation_readiness() == ('busy', 0)
        resume.set()
        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 2)
        if closing is not None: await closing
        state = await actor.snapshot()
        if action=='new_input':
            assert state.story_image.state=='qualified'
            assert any(e.kind is EffectKind.MEDIA and e.output_epoch==2 for e in state.active_grants)
            assert calls==['image','review'] and len(runtime._artifacts)==1
        else:
            assert not any(e.kind is EffectKind.MEDIA for e in (*state.active_grants,*state.presented_effects))
            assert calls==(['image'] if stage=='generation' else ['image','review']) and not runtime._artifacts
        assert runtime.operation_readiness()==('budget_exhausted',0)
        assert runtime.attempts==1
    finally:
        resume.set()
        if closing is not None: await closing
        await actor.close()


@pytest.mark.asyncio
async def test_failed_image_fact_survives_new_input_cleanup_without_refund():
    from dataclasses import replace
    from tests.contracts.test_image_operation_diagnostics import runtime, native_actor, image_turn
    from tests.contracts.test_luna_tool_actor import ToolTurn, text_candidate, wait_state, finish
    value, image, review = runtime(landscape_png((512, 512)))
    value.admission = replace(value.admission, authorized_custom_brief=True, max_attempts=1)
    text_turn = ToolTurn(); text_turn.call = text_candidate()
    actor = native_actor(value, [image_turn('failed'), text_turn])
    try:
        await actor.submit(request_id='turn1', activity_seq=1, cutoff=0, text='Imagine an empty lake.')
        state = await wait_state(actor, lambda s: s.story_image.state == 'failed')
        await finish(actor)
        request_id = state.story_image.request_id
        assert value._facts[request_id].state == 'failed'
        assert value.attempts == 1 and value.reserved_bytes == 0
        await actor.submit(request_id='turn2', activity_seq=2, cutoff=0, text='Just talk.')
        state = await finish(actor)
        assert value._facts[request_id].state == 'failed'
        assert next(f for f in state.story_image_facts if f.request_id == request_id).state == 'failed'
        value.release(request_id)
        assert value._facts[request_id].state == 'failed'
        assert value.attempts == 1 and value.reserved_bytes == 0
        assert image.calls == 1 and review.calls == 0
    finally: await actor.close()


@pytest.mark.parametrize('terminal', ['failed', 'cancelled'])
def test_terminal_release_is_idempotent_but_pending_release_cancels(terminal):
    from mira.domain.story_images import StoryImageFact
    from tests.contracts.test_image_operation_diagnostics import runtime, png
    value, _, _ = runtime(png())
    value._facts['active'] = StoryImageFact('active', 'cafe_rain_window', 'pending')
    value._reservations.add('active'); value.reserved_bytes = value.admission.max_output_bytes
    value.attempts = 1; value.cost_reserved = 100
    value.release('active', terminal)
    assert value._facts['active'].state == terminal
    value.release('active', 'cancelled' if terminal == 'failed' else 'failed')
    assert value._facts['active'].state == terminal
    assert value.reserved_bytes == 0 and value.attempts == 1 and value.cost_reserved == 100
    value._facts['pending'] = StoryImageFact('pending', 'cafe_rain_window', 'pending')
    value._reservations.add('pending'); value.reserved_bytes = value.admission.max_output_bytes
    value.release('pending')
    assert value._facts['pending'].state == 'cancelled' and value.reserved_bytes == 0
