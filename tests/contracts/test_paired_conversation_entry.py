"""Synthetic consent and local paired archive entry checks."""
from fastapi.testclient import TestClient
import pytest
from tools import live_provider
from mira.entrypoints.http.app import create_app


def test_direct_cli_accepts_separate_conversation_recording_choice():
    args = live_provider._parser().parse_args(['check', '--provider', 'openai_api',
        '--model', 'synthetic', '--env-file', '/synthetic/not-read.env',
        '--conversation-db', '/synthetic/conversations.sqlite',
        '--conversation-scope-config', '/synthetic/scopes.json', '--conversation-scope', 'local',
        '--authorize-conversation-persistence', '--create-local-operator-pairing'])
    assert args.authorize_conversation_persistence is True
    assert args.authorize_conversation_to_selected_provider_and_jev is False
    assert args.recall_conversation_session is None


def test_default_conversation_status_is_disabled_without_a_database(settings):
    with TestClient(create_app(settings), base_url='http://127.0.0.1:8000') as client:
        response = client.get('/api/v1/conversations/status')
        assert response.status_code == 200
        assert response.json()['persistence_status'] == 'disabled'
        assert response.json()['recall_session_id'] is None


def test_conversation_check_creates_no_database_or_pairing_material(tmp_path,monkeypatch,capsys):
    import json
    from mira.config.settings import Settings
    private=tmp_path/'private';private.mkdir(mode=0o700)
    config=private/'scopes.json'
    config.write_text(json.dumps({'version':1,'scopes':[{'name':'local','user_id':'synthetic-user',
        'character_id':'mira','world_id':'synthetic-world'}]}));config.chmod(0o600)
    database=private/'conversations.sqlite'
    monkeypatch.setattr(live_provider,'_load',lambda args:(Settings(),None))
    monkeypatch.setattr(live_provider,'_prepare_frontend',lambda:pytest.fail('check must not build'))
    before=set(private.iterdir())
    args=['check','--provider','openai_api','--model','synthetic','--env-file','/not-read.env',
        '--conversation-db',str(database),'--conversation-scope-config',str(config),'--conversation-scope','local',
        '--authorize-conversation-persistence','--create-local-operator-pairing']
    assert live_provider.main(args)==0
    result=json.loads(capsys.readouterr().out)['conversation_archive']
    assert result['database_opened'] is False and result['pairing_file_created'] is False
    assert result['recall_authorized'] is False and result['recall_selected'] is False
    assert set(private.iterdir())==before and not database.exists()
    assert str(private) not in json.dumps(result) and 'synthetic-user' not in json.dumps(result)


def test_legacy_manual_or_story_flags_do_not_enable_transcript_recording():
    args=live_provider._parser().parse_args(['check','--provider','openai_api','--model','synthetic',
        '--env-file','/not-read.env','--authorize-memory-to-selected-provider-and-jev',
        '--authorize-story-persistence-and-recall'])
    assert live_provider._conversation_options(args) is None


def test_direct_composition_installs_same_paired_archive_factory_without_opening_database(tmp_path):
    from tests.contracts.test_direct_provider_app import arguments
    from tests.contracts.test_paired_conversation_lifecycle import options,CODE,ORIGIN
    from mira.bootstrap.direct_provider_app import create_direct_provider_app
    from mira.entrypoints.http.operator_pairing import OperatorPairing
    opts=options(tmp_path)
    app=create_direct_provider_app(**arguments(conversation_options=opts,
        operator_pairing=OperatorPairing(CODE,(ORIGIN,'http://localhost:8000'))))
    assert not opts.database.exists()
    with TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN}) as client:
        assert client.get('/api/v1/conversations/status').status_code==401
        assert not opts.database.exists()
        assert client.post('/api/v1/operator/pair',json={'code':CODE}).status_code==204
        assert client.get('/api/v1/conversations/status').json()['recipients']=='OpenAI ChatGPT 订阅服务与 TypeSafe/JEV 输出审核'
        assert opts.database.exists()
