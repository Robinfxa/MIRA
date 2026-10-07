"""Synthetic configuration and mocked ports only; no user credentials/provider calls."""
import asyncio
from dataclasses import replace
import importlib
import json
from types import SimpleNamespace, ModuleType
import sys

from pydantic import SecretStr
import pytest
from tools import live_provider as cli


def module():
    return importlib.import_module('mira.bootstrap.story_image_provider')


def args(tmp_path, *extra, command='check'):
    path = tmp_path / 'synthetic.env'
    path.write_text('MIRA_SERVICES__JEV__API_KEY=synthetic-jev-key\n'
                    'MIRA_SERVICES__JEV__MODEL=jev-1.13.0\n'
                    'MIRA_SERVICES__OPENAI__API_KEY=sk-synthetic-api-key\n')
    path.chmod(0o600)
    return [command, '--provider', 'chatgpt_subscription', '--model', 'gpt-6-luna',
            '--env-file', str(path), *extra]


def image_flags():
    return ['--story', '--story-images', '--story-image-provider', 'openai_api',
        '--story-image-model', 'gpt-image-synthetic-snapshot',
        '--story-image-review-model', 'gpt-review-synthetic-snapshot',
        '--story-image-quality', 'low', '--authorize-story-image-data-to-openai',
        '--authorize-story-image-api-spend', '--story-image-reservation-microusd', '60000',
        '--story-image-total-reservation-microusd', '100000']


def options(**changes):
    return replace(module().StoryImageOptions(enabled=True, provider='openai_api',
        image_model='gpt-image-synthetic-snapshot', review_model='gpt-review-synthetic-snapshot',
        quality='low', authorize_data_to_openai=True, authorize_api_spend=True,
        reservation_microusd=60000, total_reservation_microusd=100000), **changes)


class ForbiddenSettings:
    def __getattribute__(self, name):
        raise AssertionError('disabled image capability must not read settings')


def test_default_check_declares_images_disabled_and_preserves_fast(tmp_path, capsys):
    assert cli.main(args(tmp_path)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['story_images']['status'] == 'disabled'
    assert result['story_images']['live_verified'] is False
    assert result['service_tier']['requested'] == 'fast'
    assert result['service_tier']['subscription_fast_usage_multiplier'] == 2.5


def test_model_alone_never_enables_image_provider(tmp_path, capsys):
    argv = args(tmp_path, '--story-image-model', 'gpt-image-synthetic-snapshot')
    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)['story_images']['status'] == 'disabled'
    m = module()
    disabled = m.StoryImageOptions(image_model='gpt-image-synthetic-snapshot')
    assert m.create_story_image_factory(options=disabled, story_enabled=False,
        openai_settings=ForbiddenSettings()) is None
    assert m.describe_story_images(options=disabled, story_enabled=False,
        openai_settings=ForbiddenSettings())['status'] == 'disabled'


def test_missing_fields_only_are_safe_and_never_allocate(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('no provider allocation'))
    assert cli.main(args(tmp_path, '--story-images')) == 2
    rendered = capsys.readouterr().out
    declaration = json.loads(rendered)['story_images']
    assert declaration['status'] == 'unavailable'
    assert set(declaration['missing_fields']) == {'story',
        'authorize_story_image_data_to_openai', 'authorize_story_image_subscription_usage'}
    assert 'synthetic' not in rendered and str(tmp_path) not in rendered


def test_configured_check_is_not_live_verification_or_spend_cap(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('no generation'))
    m = module()
    monkeypatch.setattr(m, 'create_story_image_factory', lambda **_: pytest.fail('check has no factory'))
    assert cli.main(args(tmp_path, *image_flags())) == 0
    result = json.loads(capsys.readouterr().out)
    declaration = result['story_images']
    assert declaration['status'] == 'configured_not_live_verified'
    assert declaration['provider'] == 'openai_api' and result['provider'] == 'chatgpt_subscription'
    assert declaration['limits_are_dollar_caps'] is False
    assert declaration['planning_reservation_is_provider_limit'] is False
    assert declaration['data_scope'] == 'released_fiction_catalog_only'
    assert declaration['max_attempts_per_process'] == 1
    assert declaration['max_reviews_per_process'] == 1
    assert declaration['automatic_retries'] == 0 and declaration['max_in_flight_jobs'] == 1
    assert declaration['live_verified'] is False
    assert declaration['private_memory_transmitted'] is False


@pytest.mark.parametrize('change,field', [
    ({'provider':'unknown_route'}, 'story_image_provider'),
    ({'image_model':'private-model secret'}, 'story_image_model'),
    ({'review_model':'private-review\nsecret'}, 'story_image_review_model'),
    ({'quality':'auto'}, 'story_image_quality'),
    ({'max_attempts':0}, 'story_image_max_attempts'),
    ({'max_attempts':5}, 'story_image_max_attempts'),
    ({'max_output_bytes':True}, 'story_image_max_output_bytes'),
    ({'max_total_bytes':1023}, 'story_image_max_total_bytes'),
    ({'timeout_seconds':float('nan')}, 'story_image_timeout_seconds'),
    ({'image_timeout_seconds':0}, 'story_image_generation_timeout_seconds'),
    ({'review_timeout_seconds':121}, 'story_image_review_timeout_seconds'),
    ({'image_max_wire_bytes':12000001}, 'story_image_max_wire_bytes'),
    ({'review_max_wire_bytes':65537}, 'story_image_review_max_wire_bytes'),
    ({'review_max_output_tokens':513}, 'story_image_review_max_output_tokens'),
    ({'reservation_microusd':0}, 'story_image_reservation_microusd'),
    ({'total_reservation_microusd':59999}, 'story_image_total_reservation_microusd'),
])
def test_invalid_options_fail_closed_with_names_only(change, field):
    m = module()
    declaration = m.describe_story_images(options=options(**change), story_enabled=True,
        openai_settings=SimpleNamespace(api_key=SecretStr('sk-synthetic-key')))
    assert declaration['status'] == 'unavailable'
    assert field in declaration['invalid_fields']
    assert 'private' not in json.dumps(declaration)
    with pytest.raises(m.StoryImageConfigurationError) as failure:
        m.create_story_image_factory(options=options(**change), story_enabled=True,
            openai_settings=ForbiddenSettings())
    assert field in failure.value.fields
    assert 'private' not in str(failure.value)


def fake_modules(monkeypatch):
    calls = []
    runtime = ModuleType('mira.application.story_images')
    class Admission:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class Runtime:
        def __init__(self, image_backend, vision_backend, decoder, admission, *, operation_admission=None):
            self.image_backend=image_backend; self.vision_backend=vision_backend
            self.decoder=decoder; self.admission=admission
            self.operation_admission=operation_admission
        async def generate_and_review(self, request, phase):
            self.operation_admission.reserve(request)
            try:
                calls.append(('dispatch', request.request_id))
                return await phase('reviewing')
            finally:
                self.operation_admission.release(request.request_id)
        def close(self): calls.append(('close', id(self)))
    runtime.StoryImageAdmission = Admission
    runtime.StoryImageRuntime = Runtime
    monkeypatch.setitem(sys.modules, runtime.__name__, runtime)
    for name, backend, option in [
        ('openai_images', 'OpenAIImageBackend', 'OpenAIImageOptions'),
        ('openai_vision_review', 'OpenAIVisionReviewBackend', 'OpenAIVisionOptions')]:
        mod = ModuleType('mira.adapters.media.' + name)
        def make(**kwargs):
            calls.append(('adapter', kwargs))
            return SimpleNamespace(**kwargs)
        setattr(mod, backend, make)
        setattr(mod, option, lambda **kwargs: SimpleNamespace(**kwargs))
        monkeypatch.setitem(sys.modules, mod.__name__, mod)
    mod = ModuleType('mira.adapters.media.png_decoder')
    mod.PillowPngDecoder = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, mod.__name__, mod)
    return calls


@pytest.mark.asyncio
async def test_factory_shares_process_limit_across_sessions_without_clients(monkeypatch):
    calls = fake_modules(monkeypatch)
    import httpx
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **_: pytest.fail('factory must not create a client'))
    m = module()
    make = m.create_story_image_factory(options=options(), story_enabled=True,
        openai_settings=SimpleNamespace(api_key=SecretStr('sk-synthetic-key')))
    first, second = make(object()), make(object())
    assert first is not second and first.admission is second.admission
    assert len([x for x in calls if x[0] == 'adapter']) == 2
    async def phase(_): return 'done'
    assert await first.generate_and_review(SimpleNamespace(request_id='one', max_output_bytes=1024), phase) == 'done'
    first.close()
    with pytest.raises(ValueError, match='image_process_budget_exhausted'):
        await second.generate_and_review(SimpleNamespace(request_id='two', max_output_bytes=1024), phase)
    assert [x for x in calls if x[0] == 'dispatch'] == [('dispatch', 'one')]


@pytest.mark.asyncio
async def test_process_gate_spans_whole_job_and_releases_after_cancel_settles(monkeypatch):
    calls = fake_modules(monkeypatch)
    m = module()
    make = m.create_story_image_factory(options=options(max_attempts=4, max_total_bytes=33554432,
        total_reservation_microusd=240000), story_enabled=True,
        openai_settings=SimpleNamespace(api_key=SecretStr('sk-synthetic-key')))
    first, second = make(object()), make(object())
    entered, cancelled, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def ignores_cancellation(_):
        entered.set()
        try: await finish.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await finish.wait()
        return 'late'
    async def phase(_): return 'done'
    task = asyncio.create_task(first.generate_and_review(SimpleNamespace(request_id='one', max_output_bytes=1024), ignores_cancellation))
    await entered.wait()
    task.cancel()
    await cancelled.wait()
    with pytest.raises(ValueError, match='image_process_busy'):
        await second.generate_and_review(SimpleNamespace(request_id='two', max_output_bytes=1024), phase)
    finish.set()
    assert await task == 'late'
    assert await second.generate_and_review(SimpleNamespace(request_id='two', max_output_bytes=1024), phase) == 'done'
    assert [x for x in calls if x[0] == 'dispatch'] == [('dispatch', 'one'), ('dispatch', 'two')]


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'total_reservation_microusd':60000, 'max_total_bytes':33554432},
    {'total_reservation_microusd':240000, 'max_total_bytes':8388608},
])
async def test_failed_job_does_not_refund_process_byte_or_planning_reservation(monkeypatch, changes):
    calls = fake_modules(monkeypatch)
    m = module()
    make = m.create_story_image_factory(options=options(max_attempts=4, **changes), story_enabled=True,
        openai_settings=SimpleNamespace(api_key=SecretStr('sk-synthetic-key')))
    async def failure(_): raise ValueError('synthetic_decode_failure')
    req = SimpleNamespace(request_id='one', max_output_bytes=8388608)
    with pytest.raises(ValueError, match='synthetic_decode_failure'):
        await make(object()).generate_and_review(req, failure)
    with pytest.raises(ValueError, match='image_process_budget_exhausted'):
        await make(object()).generate_and_review(replace_request(req, 'two'), failure)
    assert [x for x in calls if x[0] == 'dispatch'] == [('dispatch', 'one')]


def replace_request(req, request_id):
    return SimpleNamespace(request_id=request_id, max_output_bytes=req.max_output_bytes)


def test_existing_configured_image_models_do_not_enable_or_allocate(tmp_path, monkeypatch, capsys):
    argv = args(tmp_path)
    path = tmp_path / 'synthetic.env'
    path.write_text(path.read_text() + 'MIRA_SERVICES__OPENAI__IMAGE_MODEL=gpt-image-synthetic-snapshot\n'
        + 'MIRA_SERVICES__OPENAI__VISION_MODEL=gpt-review-synthetic-snapshot\n')
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('no provider'))
    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)['story_images']['status'] == 'disabled'


def test_missing_api_key_is_named_without_fallback_or_secret_unwrapping(tmp_path, capsys, monkeypatch):
    argv = args(tmp_path, *image_flags())
    path = tmp_path / 'synthetic.env'
    path.write_text(path.read_text().replace('MIRA_SERVICES__OPENAI__API_KEY=sk-synthetic-api-key\n', ''))
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('no credentials'))
    assert cli.main(argv) == 2
    report = json.loads(capsys.readouterr().out)['story_images']
    assert report['missing_fields'] == ['MIRA_SERVICES__OPENAI__API_KEY']
    key = SecretStr('not-even-a-provider-key')
    monkeypatch.setattr(SecretStr, 'get_secret_value', lambda *_: pytest.fail('check must not unwrap'))
    assert module().describe_story_images(options=options(), story_enabled=True,
        openai_settings=SimpleNamespace(api_key=key))['status'] == 'configured_not_live_verified'


@pytest.mark.parametrize('remove', ['--story', '--authorize-story-image-data-to-openai', '--authorize-story-image-api-spend'])
def test_serve_denies_missing_image_admission_before_resources(tmp_path, capsys, monkeypatch, remove):
    flags = image_flags()
    flags.remove(remove)
    monkeypatch.setattr(cli, '_prepare_frontend', lambda: pytest.fail('no resources before admission'))
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('no credentials before admission'))
    assert cli.main(args(tmp_path, *flags, '--authorize-provider-data', command='serve')) == 2
    rendered = capsys.readouterr().err
    report = json.loads(rendered)
    assert report['stage'] == 'story_image_configuration'
    assert remove[2:].replace('-', '_') in report['invalid_fields']
    assert 'synthetic' not in rendered and str(tmp_path) not in rendered


@pytest.mark.parametrize('enabled', [False, True])
def test_serve_composes_only_explicit_image_factory_independent_of_text(tmp_path, monkeypatch, capsys, enabled):
    calls = fake_modules(monkeypatch)
    from mira.bootstrap import direct_provider_app, development_app
    from tools import live_voice
    captured = {}
    def make_app(**kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setattr(direct_provider_app, 'create_direct_provider_app', make_app)
    monkeypatch.setattr(development_app, 'jev_transport_from_settings', lambda _: object())
    monkeypatch.setattr(cli, '_prepare_frontend', lambda: None)
    generation = object()
    monkeypatch.setattr(cli, '_generation', lambda *_: generation)
    monkeypatch.setattr(live_voice, '_run_uvicorn', lambda *a, **kw: None)
    argv = args(tmp_path, '--authorize-provider-data', *(image_flags() if enabled else []), command='serve')
    assert cli.main(argv) == 0
    assert captured['generation'] is generation and captured['route'] == 'chatgpt_subscription'
    assert captured['api_billing_authorized'] is False
    if enabled:
        first, second = captured['story_image_factory'](object()), captured['story_image_factory'](object())
        assert first is not second and first.operation_admission is second.operation_admission
        assert len([x for x in calls if x[0] == 'adapter']) == 2
        assert first.admission.cost_per_attempt_microunits == 60000
        assert first.admission.max_cost_microunits == 100000
        assert first.image_backend.timeout_seconds == 90
        assert first.vision_backend.timeout_seconds == 45
    else:
        assert 'story_image_factory' not in captured
        assert calls == []
    rendered = capsys.readouterr().out
    assert 'sk-synthetic' not in rendered and str(tmp_path) not in rendered


# Subscription compatibility remains offline only; synthetic injected constructors
# make credential reads and accidental API fallback observable.
def subscription_flags():
    return ['--story', '--story-images', '--authorize-story-image-data-to-openai',
        '--authorize-story-image-subscription-usage']


def subscription_options(**changes):
    return replace(module().StoryImageOptions(enabled=True, provider='chatgpt_subscription',
        image_model='gpt-image-2', review_model='gpt-6-luna', quality='auto',
        authorize_data_to_openai=True, authorize_subscription_usage=True,
        review_max_output_tokens=None), **changes)


class SyntheticCredentials:
    async def get_credentials(self):
        pytest.fail('composition must not retrieve credentials')


def fake_subscription_modules(monkeypatch):
    calls = fake_modules(monkeypatch)
    for name, backend in [('subscription_images', 'SubscriptionImageBackend'),
            ('subscription_vision_review', 'SubscriptionVisionReviewBackend')]:
        mod = ModuleType('mira.adapters.media.' + name)
        def make(_name=name, **kwargs):
            calls.append((_name, kwargs))
            return SimpleNamespace(**kwargs)
        setattr(mod, backend, make)
        if name == 'subscription_vision_review':
            mod.SubscriptionVisionOptions = lambda **kw: SimpleNamespace(**kw)
        monkeypatch.setitem(sys.modules, mod.__name__, mod)
    auth = ModuleType('mira.adapters.auth.openai_codex')
    def source(**kwargs):
        calls.append(('credentials', kwargs))
        return SyntheticCredentials()
    auth.CodexOAuthCredentialSource = source
    monkeypatch.setitem(sys.modules, auth.__name__, auth)
    return calls


def test_subscription_default_check_never_constructs_auth_or_reads_api_settings(tmp_path, capsys, monkeypatch):
    calls = fake_subscription_modules(monkeypatch)
    parsed = cli._parser().parse_args(args(tmp_path, *subscription_flags()))
    settings = SimpleNamespace(services=SimpleNamespace(openai=ForbiddenSettings()))
    description = cli._story_image_declaration(parsed, settings)
    assert description['status'] == 'configured_not_live_verified'
    assert description['provider'] == 'chatgpt_subscription'
    assert description['image_model'] == 'gpt-image-2' and description['quality'] == 'auto'
    assert description['review_model'] == 'gpt-6-luna'
    assert description['planning_reservation_microusd_per_job'] is None
    assert description['planning_reservation_microusd_per_process'] is None
    assert description['planning_reservation_status'] == 'not_applicable'
    assert description['review_max_output_tokens'] is None
    assert description['review_remote_token_cap'] == 'unavailable'
    assert description['subscription_quota_consumption'] == 'unknown'
    assert description['subscription_entitlement'] == 'not_checked'
    assert description['limits_are_plan_caps'] is False
    assert description['compatibility'] == 'internal_unverified'
    assert description['automatic_fallback'] is False
    assert cli.main(args(tmp_path, *subscription_flags())) == 0
    assert json.loads(capsys.readouterr().out)['service_tier']['requested'] == 'fast'
    assert calls == []


@pytest.mark.parametrize('remove', ['--story', '--authorize-story-image-data-to-openai',
    '--authorize-story-image-subscription-usage'])
def test_subscription_serve_denies_before_either_credential_route_or_adapter(tmp_path, capsys, monkeypatch, remove):
    calls = fake_subscription_modules(monkeypatch)
    monkeypatch.setattr(cli, 'ApiCredentialSource', lambda *_: pytest.fail('no API credentials'))
    monkeypatch.setattr(cli, '_prepare_frontend', lambda: pytest.fail('no frontend before consent'))
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('no generation before consent'))
    flags = subscription_flags()
    flags.remove(remove)
    assert cli.main(args(tmp_path, *flags, '--authorize-provider-data', command='serve')) == 2
    rendered = capsys.readouterr().err
    assert json.loads(rendered)['stage'] == 'story_image_configuration'
    assert calls == [] and 'synthetic' not in rendered and str(tmp_path) not in rendered


def test_subscription_factory_requires_injected_source_without_api_discovery(monkeypatch):
    calls = fake_subscription_modules(monkeypatch)
    with pytest.raises(module().StoryImageConfigurationError) as failure:
        module().create_story_image_factory(options=subscription_options(), story_enabled=True,
            openai_settings=ForbiddenSettings())
    assert failure.value.fields == ('story_image_subscription_credentials',)
    assert calls == []


@pytest.mark.parametrize('changes,field', [
    ({'image_model': 'gpt-image-api'}, 'story_image_model'),
    ({'quality': 'low'}, 'story_image_quality'),
    ({'reservation_microusd': 1}, 'story_image_reservation_microusd'),
    ({'total_reservation_microusd': 1}, 'story_image_total_reservation_microusd'),
    ({'review_max_output_tokens': 512}, 'story_image_review_max_output_tokens'),
    ({'max_attempts': 5}, 'story_image_max_attempts'),
])
def test_subscription_rejects_unsupported_declarations_without_route_fallback(monkeypatch, changes, field):
    calls = fake_subscription_modules(monkeypatch)
    with pytest.raises(module().StoryImageConfigurationError) as failure:
        module().create_story_image_factory(options=subscription_options(**changes), story_enabled=True,
            openai_settings=ForbiddenSettings(), credential_source=SyntheticCredentials())
    assert field in failure.value.fields
    assert calls == []


@pytest.mark.asyncio
async def test_subscription_shares_opaque_credentials_and_process_gate_without_dollar_reservations(monkeypatch):
    calls = fake_subscription_modules(monkeypatch)
    source = SyntheticCredentials()
    make = module().create_story_image_factory(options=subscription_options(), story_enabled=True,
        openai_settings=ForbiddenSettings(), credential_source=source)
    first, second = make(object()), make(object())
    assert first.image_backend.credential_source is source
    assert first.vision_backend.credential_source is source
    assert first.vision_backend.options.model == 'gpt-6-luna'
    assert first.admission.cost_per_attempt_microunits == 0
    assert first.admission.max_cost_microunits == 0
    assert first.operation_admission is second.operation_admission
    assert first.image_backend.timeout_seconds == 90 and first.vision_backend.timeout_seconds == 45
    assert not any(name in ('adapter', 'credentials') for name, *_ in calls)
    async def phase(_): return 'done'
    assert await first.generate_and_review(SimpleNamespace(request_id='sub-one', max_output_bytes=1024), phase) == 'done'
    first.close()
    with pytest.raises(ValueError, match='image_process_budget_exhausted'):
        await second.generate_and_review(SimpleNamespace(request_id='sub-two', max_output_bytes=1024), phase)
    assert first.operation_admission.reserved_microusd == 0
    assert first.operation_admission.reserved_bytes == 8388608


@pytest.mark.asyncio
async def test_subscription_failure_never_falls_back_and_keeps_process_reservation(monkeypatch):
    calls = fake_subscription_modules(monkeypatch)
    make = module().create_story_image_factory(options=subscription_options(max_attempts=4),
        story_enabled=True, credential_source=SyntheticCredentials(), openai_settings=ForbiddenSettings())
    async def failed(_): raise ValueError('subscription_unavailable')
    with pytest.raises(ValueError, match='subscription_unavailable'):
        await make(object()).generate_and_review(SimpleNamespace(request_id='failed', max_output_bytes=1024), failed)
    with pytest.raises(ValueError, match='image_process_budget_exhausted'):
        await make(object()).generate_and_review(SimpleNamespace(request_id='next', max_output_bytes=1024), failed)
    assert not any(name == 'adapter' for name, *_ in calls)
    assert [x for x in calls if x[0] == 'dispatch'] == [('dispatch', 'failed')]


def test_api_text_requires_explicit_image_route_before_subscription_auth(tmp_path, capsys, monkeypatch):
    calls = fake_subscription_modules(monkeypatch)
    argv = args(tmp_path, *subscription_flags())
    argv[argv.index('--provider') + 1] = 'openai_api'
    assert cli.main(argv) == 2
    description = json.loads(capsys.readouterr().out)['story_images']
    assert 'story_image_provider' in description['missing_fields']
    assert calls == []
    assert cli.main(argv + ['--story-image-provider', 'chatgpt_subscription']) == 0
    assert json.loads(capsys.readouterr().out)['story_images']['provider'] == 'chatgpt_subscription'
    assert calls == []


def test_subscription_serve_reuses_one_source_for_text_and_both_image_transports(tmp_path, capsys, monkeypatch):
    calls = fake_subscription_modules(monkeypatch)
    from mira.bootstrap import direct_provider_app, development_app
    from tools import live_voice
    captured = {}
    monkeypatch.setattr(direct_provider_app, 'create_direct_provider_app', lambda **kw: captured.update(kw) or object())
    monkeypatch.setattr(development_app, 'jev_transport_from_settings', lambda _: object())
    monkeypatch.setattr(cli, '_prepare_frontend', lambda: None)
    def generation(_args, _settings, credential_source=None):
        calls.append(('text_credentials', credential_source))
        return object()
    monkeypatch.setattr(cli, '_generation', generation)
    monkeypatch.setattr(live_voice, '_run_uvicorn', lambda *a, **kw: None)
    assert cli.main(args(tmp_path, *subscription_flags(), '--authorize-provider-data', command='serve')) == 0
    runtime = captured['story_image_factory'](object())
    source = runtime.image_backend.credential_source
    assert runtime.vision_backend.credential_source is source
    assert [x[1] for x in calls if x[0] == 'text_credentials'] == [source]
    assert len([x for x in calls if x[0] == 'credentials']) == 1
    assert not any(x[0] == 'adapter' for x in calls)
    assert 'synthetic' not in capsys.readouterr().out


@pytest.mark.parametrize('selection', ['disabled', 'subscription', 'denied_api'])
def test_unselected_or_denied_cli_image_settings_are_not_even_accessed(tmp_path, monkeypatch, selection):
    calls = fake_subscription_modules(monkeypatch)
    flags = subscription_flags() if selection == 'subscription' else image_flags() if selection == 'denied_api' else []
    if selection == 'denied_api':
        flags.remove('--authorize-story-image-api-spend')
    parsed = cli._parser().parse_args(args(tmp_path, *flags))
    declaration = cli._story_image_declaration(parsed, ForbiddenSettings())
    assert declaration['status'] == {'disabled': 'disabled', 'subscription': 'configured_not_live_verified',
        'denied_api': 'unavailable'}[selection]
    assert calls == []


@pytest.mark.asyncio
async def test_subscription_four_job_ceiling_is_shared_across_new_sessions(monkeypatch):
    calls = fake_subscription_modules(monkeypatch)
    make = module().create_story_image_factory(options=subscription_options(max_attempts=4,
        max_total_bytes=33554432), story_enabled=True, credential_source=SyntheticCredentials(),
        openai_settings=ForbiddenSettings())
    async def phase(_): return 'done'
    for index in range(4):
        runtime = make(object())
        assert await runtime.generate_and_review(SimpleNamespace(request_id=f'job-{index}', max_output_bytes=1024), phase) == 'done'
        runtime.close()
    with pytest.raises(ValueError, match='image_process_budget_exhausted'):
        await make(object()).generate_and_review(SimpleNamespace(request_id='job-4', max_output_bytes=1024), phase)
    assert len([x for x in calls if x[0] == 'dispatch']) == 4
    assert runtime.operation_admission.reserved_bytes == 33554432
    assert runtime.operation_admission.reserved_microusd == 0


@pytest.mark.parametrize('subscription', [False, True])
def test_factory_forwards_only_explicit_injected_transports(monkeypatch, subscription):
    calls = fake_subscription_modules(monkeypatch)
    image_transport, review_transport = object(), object()
    make = module().create_story_image_factory(
        options=subscription_options() if subscription else options(), story_enabled=True,
        credential_source=SyntheticCredentials() if subscription else None,
        openai_settings=ForbiddenSettings() if subscription else SimpleNamespace(api_key=SecretStr('sk-synthetic-key')),
        image_transport=image_transport, review_transport=review_transport)
    runtime = make(object())
    assert runtime.image_backend.transport is image_transport
    assert runtime.vision_backend.transport is review_transport
    assert not any(x[0] in ('credentials', 'dispatch') for x in calls)
