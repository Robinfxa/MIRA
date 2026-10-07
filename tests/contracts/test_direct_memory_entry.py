"""Direct-provider memory opt-in preserves pairing, scope and recipient boundaries."""
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from tools import live_provider as cli


def arguments(*extra, command='check', provider='chatgpt_subscription'):
    return [command,'--provider',provider,'--model','synthetic-model',
        '--env-file','/synthetic/private.env',*extra]


def complete_flags():
    return ['--memory-db','/synthetic/private/memory.sqlite3',
        '--memory-scope-config','/synthetic/private/scopes.json','--memory-scope','local',
        '--authorize-memory-to-selected-provider-and-jev','--create-local-operator-pairing']


def test_no_memory_flags_never_reads_memory_configuration(monkeypatch):
    from mira.config import memory
    monkeypatch.setattr(memory,'load_memory_recall_options',lambda **_:pytest.fail('unexpected memory read'))
    assert cli._memory_options(cli._parser().parse_args(arguments())) is None


@pytest.mark.parametrize('flags',[
    ['--memory-db','/synthetic/private/memory.sqlite3'],
    ['--authorize-memory-to-selected-provider-and-jev'],
    complete_flags()[:-2], complete_flags()[:-1],
    ['--create-local-operator-pairing'], ['--authorize-local-memory-management'],
    complete_flags()+['--voice'],
])
def test_incomplete_or_voice_memory_fails_before_reads(monkeypatch,capsys,flags):
    from mira.config import memory
    monkeypatch.setattr(cli,'_load',lambda _:pytest.fail('settings read before validation'))
    monkeypatch.setattr(memory,'load_memory_recall_options',lambda **_:pytest.fail('memory read before consent'))
    assert cli.main(arguments(*flags))==2
    text=capsys.readouterr().err
    assert 'synthetic/private' not in text


def test_complete_memory_options_preserve_existing_scoped_loader(monkeypatch):
    from mira.config import memory
    seen={};sentinel=object()
    def load(**kwargs):seen.update(kwargs);return sentinel
    monkeypatch.setattr(memory,'load_memory_recall_options',load)
    assert cli._memory_options(cli._parser().parse_args(arguments(*complete_flags()))) is sentinel
    assert seen['authorized_transmission'] is True and seen['scope_alias']=='local'
    assert seen['checkout_root']==cli.ROOT and seen['database']==Path('/synthetic/private/memory.sqlite3')


@pytest.mark.parametrize('route,recipient',[
    ('chatgpt_subscription','OpenAI ChatGPT subscription backend'),
    ('openai_api','OpenAI official API'),
])
@pytest.mark.parametrize('review_mode', ['luna_tools', 'legacy_jev'])
def test_memory_check_discloses_selected_recipient_but_never_creates_pairing(monkeypatch,capsys,route,recipient,review_mode):
    from mira.config.settings import Settings
    from tools import operator_pairing_file
    monkeypatch.setattr(cli,'_memory_options',lambda _:object())
    monkeypatch.setattr(cli,'_load',lambda _:(Settings(),None))
    monkeypatch.setattr(operator_pairing_file,'create_pairing_material',lambda *_a,**_k:pytest.fail('pairing created'))
    monkeypatch.setattr(cli,'_generation',lambda *_:pytest.fail('auth/generation prepared'))
    assert cli.main(arguments(*complete_flags(),'--action-review-mode',review_mode,provider=route))==0
    block=json.loads(capsys.readouterr().out)['memory_recall']
    assert block['recipients']==[recipient]+(['TypeSafe/JEV output review'] if review_mode=='legacy_jev' else [])
    assert block['database_opened'] is False and block['pairing_file_created'] is False
    assert block['automatic_recording'] is False


def test_direct_memory_help_separates_local_recording_and_transmission(capsys):
    with pytest.raises(SystemExit):cli._parser().parse_args(['serve','--help'])
    text=' '.join(capsys.readouterr().out.split())
    assert '--authorize-memory-to-selected-provider' in text and 'explicit legacy_jev mode' in text
    assert 'does not record' in text and 'local save/correct/soft-forget/restore' in text


@pytest.mark.parametrize('route,label',[
    ('chatgpt_subscription','OpenAI ChatGPT 订阅服务'),
    ('openai_api','OpenAI 官方 API'),
])
def test_pairing_page_discloses_exact_memory_recipient_before_any_database_read(tmp_path,monkeypatch,route,label):
    from fastapi.testclient import TestClient
    from mira.config.settings import Settings
    from mira.config.memory import MemoryRecallOptions
    from mira.domain.memory import MemoryScope
    from mira.entrypoints.http.operator_pairing import OperatorPairing
    from mira.bootstrap import development_memory
    from mira.bootstrap.direct_provider_app import create_direct_provider_app
    from tests.contracts.test_direct_provider_app import arguments
    def factory(_options):
        return lambda:pytest.fail('private database opened before pairing')
    monkeypatch.setattr(development_memory,'create_development_memory_factory',factory)
    options=MemoryRecallOptions(tmp_path/'synthetic.sqlite3',MemoryScope('test-user','mira','test-world'),'local',True)
    pairing=OperatorPairing('synthetic-code-for-testing-00000000',
        ('http://127.0.0.1:8000','http://localhost:8000'))
    app=create_direct_provider_app(**arguments(route=route,api_billing_authorized=route=='openai_api',
        memory_options=options,operator_pairing=pairing,authorize_memory_to_direct_provider_and_jev=True))
    with TestClient(app,base_url='http://127.0.0.1:8000') as client:
        response=client.get('/')
        assert response.status_code==200 and label in response.text
        assert 'TypeSafe/JEV 输出审核' in response.text
        assert 'test-user' not in response.text and 'test-world' not in response.text
        assert client.get('/api/v1/operator/status').status_code==200
        assert not options.database.exists()


def _fake_entry(monkeypatch,tmp_path):
    from mira.config.settings import Settings
    from mira.config.memory import MemoryRecallOptions
    from mira.domain.memory import MemoryScope
    private=tmp_path/'private';private.mkdir(mode=0o700)
    options=MemoryRecallOptions(private/'synthetic.sqlite3',MemoryScope('user-test','mira','world-test'),'local',True)
    monkeypatch.setattr(cli,'_memory_options',lambda _:options)
    monkeypatch.setattr(cli,'_load',lambda _:(Settings(),None))
    monkeypatch.setattr(cli,'ROOT',tmp_path/'synthetic-checkout')
    return private,options


def test_serving_memory_creates_only_explicit_synthetic_pairing_and_no_secret_output(monkeypatch,tmp_path,capsys):
    from tools import operator_pairing_file,live_voice
    from mira.bootstrap import direct_provider_app,development_app
    private,options=_fake_entry(monkeypatch,tmp_path)
    secret='synthetic-test-pairing-code-0000000000';seen={}
    original=operator_pairing_file.create_pairing_material
    monkeypatch.setattr(operator_pairing_file,'create_pairing_material',lambda directory,**kwargs:
        original(directory,**kwargs,code_factory=lambda:secret))
    monkeypatch.setattr(cli,'_prepare_frontend',lambda:None)
    monkeypatch.setattr(cli,'_generation',lambda *_:object())
    monkeypatch.setattr(development_app,'jev_transport_from_settings',lambda _:object())
    monkeypatch.setattr(direct_provider_app,'create_direct_provider_app',lambda **kwargs:seen.update(kwargs) or object())
    monkeypatch.setattr(live_voice,'_run_uvicorn',lambda *_a,**_k:None)
    assert cli.main(arguments(*complete_flags(),'--authorize-provider-data',command='serve'))==0
    assert seen['memory_options'] is options and seen['operator_pairing'] is not None
    assert seen['authorize_memory_to_direct_provider_and_jev'] is True
    files=list(private.glob('mira-operator-*.txt'));assert len(files)==1
    output=capsys.readouterr().out
    assert secret not in output and str(files[0]) in output
    assert 'five minutes' in output and 'OpenAI ChatGPT subscription backend' in output


def test_failed_build_or_missing_dialogue_consent_never_creates_pairing(monkeypatch,tmp_path):
    from tools import operator_pairing_file
    _fake_entry(monkeypatch,tmp_path)
    monkeypatch.setattr(operator_pairing_file,'create_pairing_material',lambda *_a,**_k:pytest.fail('premature pairing'))
    def failed():raise cli.EntryError('synthetic build failure')
    monkeypatch.setattr(cli,'_prepare_frontend',failed)
    assert cli.main(arguments(*complete_flags(),command='serve'))==2
    assert cli.main(arguments(*complete_flags(),'--authorize-provider-data',command='serve'))==2
