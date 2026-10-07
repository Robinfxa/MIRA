"""Actual CLI to ASGI lifecycle and image ports, with only synthetic IO transports."""
import base64
import json
import time
from hashlib import sha256

import httpx
import pytest
from fastapi.testclient import TestClient

from mira.bootstrap import story_image_provider
from mira.bootstrap.providers import GoogleVoiceProviders
from mira.domain.story_images import REQUIRED_PIXEL_CHECKS
from tests.contracts.test_conversation_first import session, submit, settled
from tests.contracts.test_direct_codex_responses import response as text_response
from tests.contracts.test_direct_luna_tools import message, tool, wire
from tests.contracts.test_story_image_adapters import image_reply, png, response, review_reply
from tests.contracts.test_story_images import image_body
from tests.contracts.test_subscription_images import Credentials, image_body as subscription_image_body
from tests.contracts.test_subscription_vision_review import response as vision_response, stream_bytes
from tools import live_provider as cli


def argv(tmp_path, route='chatgpt_subscription'):
    env = tmp_path / 'synthetic.env'
    env.write_text('MIRA_SERVICES__SPEECH__PROJECT_ID=synthetic-project\n'
        'MIRA_SERVICES__SPEECH__TTS_VOICE=Gacrux\n'
        'MIRA_SERVICES__OPENAI__API_KEY=sk-synthetic-api-key\n'
        'MIRA_SERVICES__JEV__API_KEY=synthetic-legacy-key\n'
        'MIRA_SERVICES__JEV__MODEL=jev-1.13.0\n')
    env.chmod(0o600)
    adc = tmp_path / 'synthetic-adc.json'
    adc.write_text('This synthetic file must never be parsed.')
    adc.chmod(0o600)
    result = ['serve', '--provider', route, '--model', 'gpt-6-luna', '--env-file', str(env),
        '--authorize-provider-data', '--voice', '--adc-file', str(adc),
        '--authorize-google-voice-data-and-spend', '--story', '--story-images',
        '--authorize-story-image-data-to-openai', '--authorize-story-image-custom-brief']
    if route == 'chatgpt_subscription':
        return result + ['--authorize-story-image-subscription-usage']
    return result + ['--authorize-api-billing', '--story-image-provider', 'openai_api',
        '--story-image-model', 'gpt-image-synthetic-snapshot', '--story-image-quality', 'low',
        '--story-image-review-model', 'gpt-6-luna', '--authorize-story-image-api-spend',
        '--story-image-reservation-microusd', '60000',
        '--story-image-total-reservation-microusd', '60000']


class Harness:
    def __init__(self, monkeypatch, route, *, outcome='pass', legacy=False):
        from mira.adapters.generation import direct_codex_responses as generation_module
        from mira.bootstrap import development_app, development_review
        from tools import live_voice
        self.route = route
        self.outcome = outcome
        self.text_requests = []
        self.image_requests = []
        self.review_requests = []
        self.results = []
        self.closed = []
        self.created = []
        self.app = None
        self.credentials = Credentials()
        monkeypatch.setattr(cli, '_prepare_frontend', lambda: None)
        monkeypatch.setattr(cli, '_subscription_credentials', self.credentials_for_route)
        monkeypatch.setattr(cli, '_voice_factory', self.voice_factory)
        monkeypatch.setattr(live_voice, '_run_uvicorn', self.run)
        actual_generation = generation_module.DirectCodexResponsesGenerationBackend
        monkeypatch.setattr(generation_module, 'DirectCodexResponsesGenerationBackend',
            lambda **kwargs: actual_generation(**kwargs, transport=httpx.MockTransport(lambda request: self.dialogue(request))))
        actual_images = story_image_provider.create_story_image_factory
        def images(**kwargs):
            self.created.append('images')
            return actual_images(**kwargs, image_transport=httpx.MockTransport(self.image),
                review_transport=httpx.MockTransport(self.review))
        monkeypatch.setattr(story_image_provider, 'create_story_image_factory', images)
        if not legacy:
            monkeypatch.setattr(development_app, 'jev_transport_from_settings',
                lambda *_: pytest.fail('native startup must not construct JEV transport'))
            monkeypatch.setattr(development_review, 'create_development_review_providers',
                lambda **_: pytest.fail('native startup must not construct JEV review'))
        self.inspect = lambda client: None

    def credentials_for_route(self, _args):
        assert self.route == 'chatgpt_subscription', 'API route cannot load subscription credentials'
        self.created.append('subscription')
        return self.credentials

    def voice_factory(self, *_):
        self.created.append('voice')
        async def close(): self.closed.append('voice')
        class Voice:
            def __getattr__(self, name):
                raise AssertionError('No actual microphone or TTS operation in startup test: ' + name)
        bundle = GoogleVoiceProviders(Voice(), Voice(), close,
            continuous_speech_recognition=Voice())
        return lambda: bundle, None

    def dialogue(self, request):
        self.text_requests.append(request)
        body = json.loads(request.content)
        assert request.url.host == ('chatgpt.com' if self.route == 'chatgpt_subscription' else 'api.openai.com')
        if len(self.text_requests) == 1:
            names = {item['name'] for item in body['tools']}
            assert 'generate_story_image' in names
            return text_response(wire([tool(name='generate_story_image', arguments=json.dumps({
                'brief': 'An empty fictional blue lakeside.', 'framing': 'wide', 'lighting': 'warm'}))]))
        outputs = [item for item in body['input'] if item.get('type') == 'function_call_output']
        assert len(outputs) == 1
        self.results.append(json.loads(outputs[0]['output']))
        return text_response(wire([message('这是虚构画面工具的实际结果。')]))

    def image(self, request):
        self.image_requests.append(request)
        assert str(request.url) == ('https://chatgpt.com/backend-api/codex/images/generations'
            if self.route == 'chatgpt_subscription' else 'https://api.openai.com/v1/images/generations')
        assert 'An empty fictional blue lakeside.' in json.loads(request.content)['prompt']
        if self.outcome == 'generation_failed': return response({}, status=503)
        return response(subscription_image_body() if self.route == 'chatgpt_subscription' else image_reply())

    def review(self, request):
        self.review_requests.append(request)
        body = json.loads(request.content)
        assert str(request.url) == ('https://chatgpt.com/backend-api/codex/responses'
            if self.route == 'chatgpt_subscription' else 'https://api.openai.com/v1/responses')
        prompt, image = body['input'][0]['content']
        binding = json.loads(prompt['text'])
        pixels = base64.b64decode(image['image_url'].split(',', 1)[1], validate=True)
        assert pixels.startswith(b'\x89PNG\r\n\x1a\n')
        assert binding['checked_content_digest'] == sha256(pixels).hexdigest()
        self.reviewed_pixels = pixels
        document = {key: binding[key] for key in ('request_id', 'specification_digest',
            'checked_content_digest', 'policy_revision')}
        document.update(checks={key: self.outcome for key in REQUIRED_PIXEL_CHECKS},
            observed_description='An empty fictional blue lakeside.')
        if self.route == 'chatgpt_subscription':
            return vision_response(stream_bytes(document, terminal={'model': 'gpt-6-luna'}))
        return response({**review_reply(document), 'model': 'gpt-6-luna'})

    def run(self, app, **_kwargs):
        self.app = app
        from mira.config.loader import ConfigurationError
        try:
            with TestClient(app) as client:
                assert app.state.container.speech_enabled
                assert app.state.container.microphone_enabled
                assert app.state.container.continuous_listening_enabled
                self.inspect(client)
        except ConfigurationError as error:
            raise AssertionError('actual app lifespan failed: ' + str(error)) from error
        assert app.state.container.sessions._sessions == {}


def wait_image(client, path, headers):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        state = client.get(path, headers=headers).json()
        if state['story_image']['state'] in ('qualified', 'failed', 'held'): return state
        time.sleep(.003)
    pytest.fail('image did not settle: ' + str(state))


@pytest.mark.parametrize('route', ['chatgpt_subscription', 'openai_api'])
def test_exact_cli_native_voice_story_images_enters_and_closes_lifespan(tmp_path, monkeypatch, route):
    harness = Harness(monkeypatch, route)
    def inspect(client):
        path, headers = session(client)
        actor = next(iter(harness.app.state.container.sessions._sessions.values())).actor
        assert actor._native_tool_authority and actor._semantic_review is None
        assert actor._story_images is not None and actor._character_runtime is not None
        assert actor._story_images.admission.authorized_custom_brief
        assert harness.app.state.usage_declaration.input_jev_requests == 0
        assert harness.app.state.usage_declaration.output_jev_requests == 0
        assert client.get(path, headers=headers).status_code == 200
    harness.inspect = inspect
    assert cli.main(argv(tmp_path, route)) == 0
    assert harness.closed == ['voice']
    assert not harness.text_requests and not harness.image_requests and not harness.review_requests
    assert harness.credentials.calls == 0


@pytest.mark.parametrize('route', ['chatgpt_subscription', 'openai_api'])
@pytest.mark.parametrize('outcome', ['pass', 'fail', 'unassessable', 'generation_failed'])
def test_exact_cli_native_image_chain_requires_pixels_and_renderer_receipt(tmp_path, monkeypatch, route, outcome):
    harness = Harness(monkeypatch, route, outcome=outcome)
    def inspect(client):
        path, headers = session(client)
        submit(client, path, headers, text='Please illustrate an empty fictional blue lakeside.')
        state = wait_image(client, path, headers)
        assert len(harness.image_requests) == 1
        assert len(harness.review_requests) == int(outcome != 'generation_failed')
        assert state['presented_effects'] == []
        if outcome == 'pass':
            assert state['story_image']['state'] == 'qualified'
            photo = next(effect for effect in state['active_grants'] if effect['kind'] == 'media')
            resource, body = image_body(photo)
            fetched = client.post(path + '/story-images/' + resource, headers=headers, json=body)
            assert fetched.status_code == 200 and fetched.content == harness.reviewed_pixels
            assert not harness.results, 'qualified image is not shown without a matching receipt'
            receipt = {key: photo[key] for key in ('digest', 'output_epoch', 'activity_seq')}
            receipt.update(effect_id=photo['id'], presentation_seq=1)
            assert client.post(path + '/receipts', headers=headers,
                json={**receipt, 'digest': 'wrong'}).status_code in (409, 422)
            assert not harness.results
            assert client.post(path + '/receipts', headers=headers, json=receipt).status_code == 200
        else:
            assert state['story_image']['state'] == 'failed'
            assert not any(e['kind'] == 'media' for e in state['active_grants'])
        final = settled(client, path, headers)
        assert final['sealed'] and final['last_error'] is None
        assert len(harness.text_requests) == 2 and len(harness.results) == 1
        assert harness.results[0]['status'] == ('shown' if outcome == 'pass' else 'failed')
        assert harness.results[0]['shown'] is (outcome == 'pass')
        assert any(e['kind'] == 'subtitle' for e in final['active_grants'])
    harness.inspect = inspect
    assert cli.main(argv(tmp_path, route)) == 0
    assert harness.closed == ['voice']


@pytest.mark.parametrize('missing', ['--authorize-provider-data', '--authorize-google-voice-data-and-spend',
    '--authorize-story-image-data-to-openai', '--authorize-story-image-subscription-usage'])
def test_exact_cli_missing_consent_prevents_provider_allocation(tmp_path, monkeypatch, missing):
    harness = Harness(monkeypatch, 'chatgpt_subscription')
    arguments = argv(tmp_path)
    arguments.remove(missing)
    assert cli.main(arguments) == 2
    assert harness.app is None and harness.created == []
    assert not harness.text_requests and not harness.image_requests and not harness.review_requests


def test_exact_cli_missing_custom_brief_keeps_tool_unavailable(tmp_path, monkeypatch):
    harness = Harness(monkeypatch, 'chatgpt_subscription')
    def inspect(client):
        path, headers = session(client)
        actor = next(iter(harness.app.state.container.sessions._sessions.values())).actor
        assert not actor._story_images.admission.authorized_custom_brief
        def no_image_tool(request):
            harness.text_requests.append(request)
            assert 'generate_story_image' not in {item['name'] for item in json.loads(request.content)['tools']}
            return text_response(wire([message()]))
        # The existing transport invokes this bound callback dynamically below.
        harness.dialogue = no_image_tool
        submit(client, path, headers, text='Please illustrate an empty fictional blue lakeside.')
        state = settled(client, path, headers)
        assert state['last_error'] is None and state['story_image']['state'] == 'idle'
    harness.inspect = inspect
    arguments = argv(tmp_path)
    arguments.remove('--authorize-story-image-custom-brief')
    assert cli.main(arguments) == 0
    assert not harness.image_requests and not harness.review_requests


def test_exact_cli_explicit_legacy_voice_story_images_still_enters_lifespan(tmp_path, monkeypatch):
    harness = Harness(monkeypatch, 'chatgpt_subscription', legacy=True)
    def inspect(client):
        session(client)
        actor = next(iter(harness.app.state.container.sessions._sessions.values())).actor
        assert not actor._native_tool_authority
        assert actor._semantic_review is not None and actor._semantic_review.conversation_first
        assert actor._story_images is not None and not actor._story_images.admission.authorized_custom_brief
    harness.inspect = inspect
    arguments = argv(tmp_path)
    arguments.remove('--authorize-story-image-custom-brief')
    arguments += ['--action-review-mode', 'legacy_jev', '--legacy-media-proposals']
    assert cli.main(arguments) == 0
    assert harness.closed == ['voice']
    assert not harness.text_requests and not harness.image_requests and not harness.review_requests


@pytest.mark.parametrize('missing', ['--authorize-api-billing', '--authorize-story-image-api-spend'])
def test_exact_cli_api_requires_both_explicit_spend_consents(tmp_path, monkeypatch, missing):
    harness = Harness(monkeypatch, 'openai_api')
    arguments = argv(tmp_path, 'openai_api')
    arguments.remove(missing)
    assert cli.main(arguments) == 2
    assert harness.app is None and harness.created == []
    assert not harness.text_requests and not harness.image_requests and not harness.review_requests


def test_non_native_image_composition_still_requires_optional_intent_review():
    from mira.bootstrap.container import build_container
    from mira.bootstrap.character_story import ephemeral_character_factory
    from mira.config.settings import Settings
    from mira.config.loader import ConfigurationError
    with pytest.raises(ConfigurationError, match='story_images_require_optional_intent_review'):
        build_container(Settings(), character_factory=ephemeral_character_factory(),
            story_image_factory=lambda _: pytest.fail('must reject before allocating image runtime'))
