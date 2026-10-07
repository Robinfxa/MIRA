"""Direct entry checks and selection use synthetic secrets/objects only."""
import json
from pathlib import Path
from types import SimpleNamespace, ModuleType
import sys
import pytest
from pydantic import SecretStr
from tools import live_provider as cli


def env(tmp_path, *, api=True):
    p=tmp_path/'mira.env'
    text='MIRA_SERVICES__JEV__API_KEY=synthetic-jev-key\nMIRA_SERVICES__JEV__MODEL=jev-1.13.0\n'
    if api:text+='MIRA_SERVICES__OPENAI__API_KEY=synthetic-api-key\n'
    p.write_text(text);p.chmod(0o600);return p


def arguments(path,command='check',provider='chatgpt_subscription'):
    return [command,'--provider',provider,'--model','explicit-model','--env-file',str(path)]


def test_unarmed_does_not_read_config_or_credentials(monkeypatch,capsys):
    monkeypatch.setattr(cli,'_load',lambda *_:(_ for _ in ()).throw(AssertionError('configread')))
    assert cli.main([])==0
    assert json.loads(capsys.readouterr().out)['codex_cli_required'] is False


@pytest.mark.parametrize('route',['chatgpt_subscription','openai_api'])
def test_check_uses_explicit_env_without_auth_network_or_native_admission(tmp_path,monkeypatch,capsys,route):
    path=env(tmp_path)
    monkeypatch.setattr(cli,'_generation',lambda *_:(_ for _ in ()).throw(AssertionError('generation')))
    monkeypatch.setattr(cli,'_serve',lambda *_:(_ for _ in ()).throw(AssertionError('serve')))
    assert cli.main(arguments(path,provider=route))==0
    result=json.loads(capsys.readouterr().out)
    assert result['provider']==route and result['live_ready'] is False
    assert result['auth_store']=='not_loaded' and result['codex_cli_required'] is False
    assert 'synthetic' not in json.dumps(result)


@pytest.mark.parametrize('story',[False,True])
@pytest.mark.parametrize('fallback',[False,True])
def test_new_live_entry_adopts_code_character_and_keeps_explicit_static_fallback(tmp_path,monkeypatch,capsys,story,fallback):
    path=env(tmp_path)
    monkeypatch.setattr(cli,'_generation',lambda *_:pytest.fail('declaration check must not create providers'))
    argv=arguments(path)+(['--story'] if story else [])
    if fallback:argv += ['--character-renderer','static-pixi']
    parsed=cli._parser().parse_args(argv)
    expected='static-pixi' if fallback else 'code-native-review'
    assert parsed.character_renderer==expected
    assert cli.main(argv)==0
    result=json.loads(capsys.readouterr().out)
    assert result['character_renderer']==expected
    assert result['auth_store']=='not_loaded' and result['inference']=='not_run'
    if story:
        from mira.bootstrap.character_assets import renderer_readiness
        assert result['character_story']['catalog_revision']==renderer_readiness(expected).revision
        assert result['character_story']['visual_acceptance']=='pending'


@pytest.mark.parametrize('voice',['Kore','Gacrux'])
def test_voice_check_uses_application_validator_and_discloses_language_auto_mode(tmp_path,monkeypatch,capsys,voice):
    path=env(tmp_path)
    path.write_text(path.read_text() + '\nMIRA_SERVICES__SPEECH__PROJECT_ID=synthetic-project\n'
        + 'MIRA_SERVICES__SPEECH__TTS_VOICE='+voice+'\n'
        + 'MIRA_SERVICES__SPEECH__TTS_LANGUAGE_CODE=cmn-CN\n'
        + 'MIRA_SERVICES__SPEECH__TTS_STYLE="private style not for diagnostics"\n')
    adc=tmp_path/'synthetic-adc.json';adc.write_text('private contents must not be parsed');adc.chmod(0o600)
    monkeypatch.setattr(cli,'_voice_factory',lambda *_:pytest.fail('check must not load ADC or instantiate providers'))
    monkeypatch.setattr(cli,'_generation',lambda *_:pytest.fail('check must not contact a model'))
    assert cli.main(arguments(path)+['--voice','--adc-file',str(adc)])==0
    rendered=capsys.readouterr().out
    selection=json.loads(rendered)['tts_selection']
    assert selection['voice']==voice
    assert selection['language_mode']=='model_auto_detection'
    assert selection['configured_language_applied'] is False
    assert selection['voice_listening_validation']=='not_run'
    assert 'private' not in rendered and 'synthetic' not in rendered


def test_voice_check_rejects_unsupported_selection_before_provider_construction(tmp_path,monkeypatch,capsys):
    path=env(tmp_path)
    path.write_text(path.read_text()+'\nMIRA_SERVICES__SPEECH__PROJECT_ID=synthetic-project\n'
        +'MIRA_SERVICES__SPEECH__TTS_VOICE=NotSupported\n')
    adc=tmp_path/'synthetic-adc.json';adc.write_text('{}');adc.chmod(0o600)
    monkeypatch.setattr(cli,'_voice_factory',lambda *_:pytest.fail('must reject before providers'))
    assert cli.main(arguments(path)+['--voice','--adc-file',str(adc)])==2
    assert 'Kore or Gacrux' in capsys.readouterr().err


def test_project_env_is_supported_and_unsafe_file_is_rejected(tmp_path,monkeypatch,capsys):
    path=env(tmp_path)
    # No artificial outside-checkout policy is used for an explicitly chosen .env.
    monkeypatch.setattr(cli,'ROOT',tmp_path)
    assert cli._private_file(path,'env')==path
    path.chmod(0o644)
    with pytest.raises(cli.EntryError,match='owner-only'):cli._private_file(path,'env')


def test_api_missing_key_does_not_fall_back_to_subscription(tmp_path,capsys):
    assert cli.main(arguments(env(tmp_path,api=False),provider='openai_api'))==2
    rendered=capsys.readouterr().err
    assert 'no OAuth fallback' in rendered and 'synthetic' not in rendered


def test_serve_checks_data_and_api_billing_before_frontend_or_credentials(tmp_path,monkeypatch,capsys):
    path=env(tmp_path)
    monkeypatch.setattr(cli,'_prepare_frontend',lambda:(_ for _ in ()).throw(AssertionError('build')))
    assert cli.main(arguments(path,'serve'))==2
    assert 'transmission consent' in capsys.readouterr().err
    assert cli.main(arguments(path,'serve','openai_api')+['--authorize-provider-data'])==2
    assert 'API-billing' in capsys.readouterr().err


def test_explicit_route_selection_never_loads_other_credentials(tmp_path,monkeypatch):
    module=ModuleType('mira.adapters.generation.direct_codex_responses');seen=[]
    module.ResponsesRoute=lambda value:value
    module.DirectCodexResponsesGenerationBackend=lambda **kw:seen.append(kw) or object()
    monkeypatch.setitem(sys.modules,module.__name__,module)
    auth=ModuleType('mira.adapters.auth.openai_codex');auth_calls=[]
    auth.CodexOAuthCredentialSource=lambda **kw:auth_calls.append(kw) or object()
    monkeypatch.setitem(sys.modules,auth.__name__,auth)
    path=env(tmp_path);args=cli._parser().parse_args(arguments(path,'serve','openai_api'))
    settings,_=cli._load(args);cli._generation(args,settings)
    assert len(seen)==1 and seen[0]['route']=='openai_api' and not auth_calls
    assert isinstance(seen[0]['credential_source'],cli.ApiCredentialSource)
    args.provider='chatgpt_subscription';cli._generation(args,settings)
    assert seen[1]['route']=='chatgpt_subscription' and len(auth_calls)==1
    assert not isinstance(seen[1]['credential_source'],cli.ApiCredentialSource)


@pytest.mark.asyncio
async def test_api_credential_wrapper_repr_does_not_expose_key():
    source=cli.ApiCredentialSource(SecretStr('synthetic-api-secret'))
    value=await source.get_credentials()
    assert value.account_id is None and value.residency is None
    assert value.access_token.get_secret_value()=='synthetic-api-secret'
    assert 'synthetic' not in repr(value)+repr(source)

@pytest.mark.asyncio
async def test_voice_wrapper_preserves_continuous_port_shared_budget_and_closes(tmp_path,monkeypatch):
    import httpx
    from tools import live_voice
    from mira.bootstrap import development_voice
    from mira.bootstrap.providers import GoogleVoiceProviders
    from mira.config.settings import Settings
    sentinel_stt, sentinel_tts, continuous, budget = object(),object(),object(),object()
    calls=[]
    async def close_bundle():calls.append('bundle_closed')
    bundle=GoogleVoiceProviders(sentinel_stt,sentinel_tts,close_bundle,
        continuous_speech_recognition=continuous,stt_request_budget=budget)
    class Client:
        def __init__(self,**_):pass
        async def aclose(self):calls.append('http_closed')
    monkeypatch.setattr(httpx,'AsyncClient',Client)
    monkeypatch.setattr(live_voice,'_make_google_stt_tls',lambda _:object())
    monkeypatch.setattr(live_voice,'_load_google_credentials',lambda _:object())
    monkeypatch.setattr(live_voice,'_make_google_token_provider',lambda _:object())
    monkeypatch.setattr(development_voice,'create_development_voice_factory',lambda **_:lambda:bundle)
    adc=tmp_path/'synthetic-adc.json';adc.write_text('{}');adc.chmod(0o600)
    factory,client=cli._voice_factory(SimpleNamespace(adc_file=adc),Settings(),object())
    wrapped=factory()
    assert wrapped.continuous_speech_recognition is continuous
    assert wrapped.stt_request_budget is budget
    assert wrapped.speech_recognition is sentinel_stt and wrapped.speech_synthesis is sentinel_tts
    await wrapped.close();await wrapped.close()
    assert calls==['bundle_closed','http_closed']

@pytest.mark.parametrize('model',['space model','model\nheader','x'*201])
def test_check_rejects_model_that_adapter_cannot_construct(tmp_path,capsys,model):
    args=arguments(env(tmp_path));args[args.index('--model')+1]=model
    assert cli.main(args)==2
    assert json.loads(capsys.readouterr().err)['status']=='blocked'


@pytest.mark.parametrize('command', ['check', 'serve'])
def test_invalid_tts_location_reports_only_safe_field_before_adc_or_resources(tmp_path, monkeypatch, capsys, command):
    path = env(tmp_path)
    path.write_text(path.read_text() + '\nMIRA_SERVICES__SPEECH__PROJECT_ID=synthetic-project\n'
        + 'MIRA_SERVICES__SPEECH__TTS_VOICE=Kore\n'
        + 'MIRA_SERVICES__SPEECH__TTS_LOCATION=Gacrux\n')
    original_private_file = cli._private_file
    def private_file(actual, label):
        assert label != 'Google ADC file', 'invalid config must fail before ADC metadata'
        return original_private_file(actual, label)
    monkeypatch.setattr(cli, '_private_file', private_file)
    monkeypatch.setattr(cli, '_voice_factory', lambda *_: pytest.fail('no provider allocation'))
    monkeypatch.setattr(cli, '_prepare_frontend', lambda: pytest.fail('no frontend build'))
    assert cli.main(arguments(path, command) + ['--voice', '--adc-file', str(tmp_path/'not-read.json')]) == 2
    rendered = capsys.readouterr().err
    result = json.loads(rendered)
    assert result['stage'] == 'config_validation'
    assert result['invalid_field'] == 'TTS_LOCATION'
    assert result['invalid_fields'] == ['TTS_LOCATION']
    assert 'global' in result['message']
    assert all(value not in rendered for value in ('Gacrux', 'synthetic', str(tmp_path), 'Traceback'))


@pytest.mark.parametrize('field,value,expected', [
    ('MIRA_SERVICES__SPEECH__TTS_ENDPOINT', 'private-endpoint-marker', 'TTS_ENDPOINT'),
    ('MIRA_SERVICES__SPEECH__TTS_MODEL', 'private-model-marker', 'TTS_MODEL'),
    ('MIRA_SERVICES__JEV__API_KEY', 'private key marker', 'MIRA_SERVICES__JEV__API_KEY'),
])
def test_config_diagnostics_allowlist_fields_without_echoing_values(tmp_path, capsys, field, value, expected):
    path = env(tmp_path)
    path.write_text(path.read_text() + f'\n{field}={value}\n')
    assert cli.main(arguments(path) + (['--action-review-mode', 'legacy_jev'] if field.startswith('MIRA_SERVICES__JEV__') else [])) == 2
    rendered = capsys.readouterr().err
    result = json.loads(rendered)
    assert result['stage'] == 'config_validation'
    assert result['invalid_fields'] == [expected]
    assert value not in rendered and str(tmp_path) not in rendered and 'synthetic' not in rendered


@pytest.mark.parametrize('message', [
    'Unknown configuration variable: MIRA_PRIVATE_SECRET_MARKER',
    'Missing configuration file: PRIVATE_SECRET_MARKER.toml',
    'Invalid configuration fields: PRIVATE_SECRET_MARKER, services.speech.tts_location',
    'Invalid configuration fields: ' + 'PRIVATE_SECRET_MARKER'*1000,
])
def test_config_diagnostics_reject_unknown_exception_fields_and_bound_output(tmp_path, monkeypatch, capsys, message):
    from mira.config import loader
    def invalid(**_):
        raise loader.ConfigurationError(message)
    monkeypatch.setattr(loader, 'load_settings', invalid)
    assert cli.main(arguments(env(tmp_path))) == 2
    rendered = capsys.readouterr().err
    result = json.loads(rendered)
    assert result['stage'] == 'config_validation'
    assert 'PRIVATE_SECRET_MARKER' not in rendered and len(rendered) < 1024
    assert set(result.get('invalid_fields', [])) <= {'TTS_LOCATION'}


@pytest.mark.parametrize('stage', ['env_file_metadata', 'adc_file_metadata'])
def test_private_file_failure_identifies_metadata_stage_without_path_or_read(tmp_path, monkeypatch, capsys, stage):
    path = env(tmp_path)
    args = arguments(path)
    if stage == 'env_file_metadata':
        path.chmod(0o644)
    else:
        path.write_text(path.read_text() + '\nMIRA_SERVICES__SPEECH__PROJECT_ID=synthetic-project\n'
            + 'MIRA_SERVICES__SPEECH__TTS_VOICE=Gacrux\n')
        args += ['--voice', '--adc-file', str(tmp_path/'private-missing-adc.json')]
    monkeypatch.setattr(cli, '_voice_factory', lambda *_: pytest.fail('metadata check must not read ADC'))
    assert cli.main(args) == 2
    rendered = capsys.readouterr().err
    assert json.loads(rendered)['stage'] == stage
    assert str(tmp_path) not in rendered and 'private-missing-adc' not in rendered
