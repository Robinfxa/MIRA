"""Real paired ASGI/Actor/SQLite, synthetic text and provider ports only."""
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import json
import time
import os
import pytest
from fastapi.testclient import TestClient
from mira.application.contracts import CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict
from mira.application.interrupted_intent import AcceptedInput
from mira.bootstrap.providers import Providers
from mira.bootstrap.conversation import conversation_factory
from mira.config.conversation import ConversationArchiveOptions, load_conversation_options, validate_conversation_options
from mira.config.loader import ConfigurationError
from mira.domain.memory import MemoryScope
from mira.domain.models import EffectKind
from mira.entrypoints.http.app import create_app
from mira.entrypoints.http.operator_pairing import OperatorPairing
from mira.adapters.memory.conversation import ConversationArchive

ORIGIN='http://127.0.0.1:8000'
CODE='synthetic-conversation-pair-code-00000000'
SCOPE=MemoryScope('synthetic-owner','mira','synthetic-world')

class Generation:
    def __init__(self):self.contexts=[]
    async def generate(self,context):
        self.contexts.append(context)
        yield CandidateRange((EffectProposal(EffectKind.SUBTITLE,'synthetic visible reply'),),'fixture')
class Review:
    def __init__(self):self.contexts=[]
    async def review(self,context,candidate):
        self.contexts.append(context)
        return ReviewObservation(ReviewVerdict.ALLOW,'synthetic')

def options(tmp_path,**kwargs):
    folder=tmp_path/'private';folder.mkdir(mode=0o700,exist_ok=True)
    return ConversationArchiveOptions(folder/'archive.sqlite',SCOPE,tmp_path/'checkout',
        authorize_persistence=True,authorize_management=True,**kwargs)

def app_for(settings,opts):
    configured=settings.model_copy(update={'runtime':settings.runtime.model_copy(update={'max_sessions':1})})
    generation,review=Generation(),Review()
    app=create_app(configured,providers=Providers(generation,review),
        operator_pairing=OperatorPairing(CODE,tuple(configured.http.allowed_origins)),
        conversation_runtime_factory=conversation_factory(opts,recipients='synthetic selected OpenAI route and TypeSafe/JEV'))
    return app,generation,review

def client_for(app):return TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN})
def pair(client):assert client.post('/api/v1/operator/pair',json={'code':CODE}).status_code==204

def turn(client,text='synthetic accepted exact input'):
    created=client.post('/api/v1/sessions',json={'client_instance_id':str(uuid4())})
    assert created.status_code==201,created.text
    data=created.json();sid=data['session']['session_id'];path='/api/v1/sessions/'+sid
    headers={'X-Mira-Session-Token':data['session_token']}
    assert client.post(path+'/inputs',headers=headers,json={'request_id':str(uuid4()),'activity_seq':1,'presentation_cutoff':0,'text':text}).status_code==202
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        state=client.get(path,headers=headers).json()
        if state['phase']=='error' or (state['phase']=='ready' and state['sealed']):break
        time.sleep(.005)
    assert state['phase']=='ready',state
    return sid,path,headers,state

def page(client,sid):
    response=client.get('/api/v1/conversations/entries',params={'session_id':sid})
    assert response.status_code==200,response.text
    return response.json()

def seed(opts,sid='old',text='synthetic old tea preference'):
    with_archive=ConversationArchive(opts.database,fixed_scope=opts.scope,enabled=True,authorize_transcript_persistence=True)
    with_archive.open(pairing_confirmed=True)
    with_archive.append_input(sid,AcceptedInput('old-input',1,text,'text',0));with_archive.close()


def test_pairing_precedes_any_database_open_and_default_capture_is_actual(tmp_path,settings):
    opts=options(tmp_path);app,generation,review=app_for(settings,opts)
    assert not opts.database.exists()
    with client_for(app) as client:
        for path in ('/status','/sessions','/entries?session_id=old'):
            assert client.get('/api/v1/conversations'+path).status_code==401
        assert client.post('/api/v1/operator/pair',json={'code':CODE},headers={'Origin':'http://evil.invalid'}).status_code==403
        assert not opts.database.exists()
        html=client.get('/').text
        assert 'data-conversation-archive="enabled"' in html
        assert '对话只保留在当前页面，刷新后清空。' not in html
        pair(client);assert opts.database.exists()
        sid,path,headers,state=turn(client)
        first=page(client,sid)
        assert [r['text'] for r in first['entries']]==['synthetic accepted exact input']
        assert generation.contexts[0].conversation_recall is None
        grant=state['active_grants'][0]
        payload={key:grant[key] for key in ('id','digest','output_epoch','activity_seq')}
        payload['effect_id']=payload.pop('id');payload['presentation_seq']=1
        assert client.post(path+'/receipts',headers=headers,json=payload).status_code==200
        after=page(client,sid)
        assert [r['stage'] for r in after['entries']]==['accepted_input','presented_effect']
        assert client.get('/api/v1/conversations/status').json()['persistence_status']=='saved'
        public=json.dumps(client.get('/api/v1/conversations/status').json())
        assert 'synthetic-owner' not in public and str(opts.database) not in public
        assert client.delete(path,headers=headers).status_code==204
    reopened=ConversationArchive(opts.database,fixed_scope=SCOPE,enabled=True,authorize_transcript_persistence=True).open(pairing_confirmed=True)
    try:assert len(reopened.load_session(sid).records)==2
    finally:reopened.close()


def test_paired_selection_recall_requires_new_consent_and_restart_uses_exact_session(tmp_path,settings):
    opts=options(tmp_path);seed(opts);seed(opts,'other','synthetic other session should not leak')
    app,generation,review=app_for(settings,opts)
    with client_for(app) as client:
        pair(client)
        assert client.post('/api/v1/conversations/selection',json={'session_id':'old','authorize_selected_provider_and_jev':False}).status_code==409
        assert client.post('/api/v1/conversations/selection',json={'session_id':'missing','authorize_selected_provider_and_jev':True}).status_code==409
        assert client.post('/api/v1/conversations/selection',json={'session_id':'old','authorize_selected_provider_and_jev':True,'scope':'other'}).status_code==422
        assert client.post('/api/v1/conversations/selection',json={'session_id':'old','authorize_selected_provider_and_jev':True}).status_code==200
        sid,path,headers,state=turn(client,'what tea preference?')
        packet=generation.contexts[0].conversation_recall
        assert packet is not None and review.contexts[0].conversation_recall is packet
        assert 'synthetic old tea preference' in packet.context_json
        assert 'synthetic other session' not in packet.context_json
        assert 'synthetic-owner' not in packet.context_json
        actor=app.state.container.sessions.get(sid,headers['X-Mira-Session-Token'])
        assert client.portal.call(actor.snapshot).user_inputs==('what tea preference?',)
        assert client.post('/api/v1/conversations/selection',json={'session_id':'other','authorize_selected_provider_and_jev':True}).status_code==409
    restart,generation,_=app_for(settings,replace(opts,recall_session_id='old',authorize_recall_to_provider_and_jev=True))
    with client_for(restart) as client:
        pair(client);turn(client,'tea again')
        assert generation.contexts[0].conversation_recall.source_session_id=='old'


def test_revision_bound_correction_forget_restore_replay_and_session_scope_checks(tmp_path,settings):
    opts=options(tmp_path);seed(opts);seed(opts,'other','synthetic untouched')
    app,_,_=app_for(settings,opts)
    with client_for(app) as client:
        pair(client);initial=page(client,'old');entry=initial['entries'][0]
        command={'session_id':'old','operation_id':str(uuid4()),'expected_revision':initial['revision'],
            'operation':'correct','entry_id':entry['entry_id'],'text':'synthetic corrected tea','confirmed':True}
        invalid=client.post('/api/v1/conversations/operations',json={**command,'session_id':'other'})
        assert invalid.status_code==409
        assert client.post('/api/v1/conversations/operations',json={**command,'confirmed':1}).status_code==422
        assert client.post('/api/v1/conversations/operations',json={**command,'expected_revision':0}).status_code==409
        changed=client.post('/api/v1/conversations/operations',json=command)
        assert changed.status_code==200,changed.text
        assert client.post('/api/v1/conversations/operations',json=command).json()['replayed'] is True
        current=page(client,'old');active=[x for x in current['entries'] if x['active']][0]
        assert active['text']=='synthetic corrected tea' and len(current['entries'])==2
        forget={'session_id':'old','operation_id':str(uuid4()),'expected_revision':current['revision'],
            'operation':'forget','entry_id':active['entry_id'],'confirmed':True}
        assert client.post('/api/v1/conversations/operations',json=forget).status_code==200
        forgotten=page(client,'old');target=[r for r in forgotten['entries'] if r['forget_event_id']][0]
        restore={'session_id':'old','operation_id':str(uuid4()),'expected_revision':forgotten['revision'],
            'operation':'restore','forget_event_id':target['forget_event_id'],'confirmed':True}
        assert client.post('/api/v1/conversations/operations',json={**restore,'session_id':'other'}).status_code==409
        assert client.post('/api/v1/conversations/operations',json=restore).status_code==200
        restored=page(client,'old');assert any(r['active'] and r['text']=='synthetic corrected tea' for r in restored['entries'])
        assert page(client,'other')['entries'][0]['text']=='synthetic untouched'
        revoked=client.post('/api/v1/conversations/revoke',json={'confirmed':True})
        assert revoked.json()['persistence_status']=='revoked_existing_records_retained'
        assert client.get('/api/v1/conversations/sessions').status_code==409
        assert client.post('/api/v1/conversations/operations',json=restore).status_code==409
        assert client.post('/api/v1/operator/revoke').status_code==204
        assert client.get('/api/v1/conversations/status').status_code==401


def test_configuration_rejects_database_aliases_and_google_recall_without_separate_consent(tmp_path):
    opts=options(tmp_path)
    validate_conversation_options(opts)
    assert not opts.database.exists()
    with pytest.raises(ConfigurationError):validate_conversation_options(replace(opts,excluded_databases=(opts.database,)))
    seed(opts)
    alias=opts.database.parent/'alias.sqlite';os.link(opts.database,alias)
    with pytest.raises(ConfigurationError):validate_conversation_options(replace(opts,excluded_databases=(alias,)))
    with pytest.raises(ConfigurationError):validate_conversation_options(replace(opts,recall_session_id='old',authorize_recall_to_provider_and_jev=True),speech_enabled=True)


def test_operator_factory_opens_no_database_until_called_and_fixed_scope_catalog_excludes_other_user(tmp_path,settings):
    opts=options(tmp_path);seed(opts)
    other=replace(opts,scope=MemoryScope('different-owner','mira','synthetic-world'));seed(other,'foreign','synthetic foreign private')
    app,_,_=app_for(settings,opts)
    with client_for(app) as client:
        pair(client)
        assert client.get('/api/v1/conversations/sessions').json()['sessions']==['old']
        assert page(client,'foreign')['entries']==[]
        assert client.post('/api/v1/conversations/selection',json={'session_id':'foreign','authorize_selected_provider_and_jev':True}).status_code==409


def test_operational_archive_failure_is_visible_and_ordinary_chat_still_runs(tmp_path,settings,monkeypatch):
    from mira.adapters.memory.async_conversation import AsyncConversationArchive
    async def unavailable(self,**kwargs):raise OSError('synthetic offline storage')
    monkeypatch.setattr(AsyncConversationArchive,'open',unavailable)
    opts=options(tmp_path);app,generation,_=app_for(settings,opts)
    with client_for(app) as client:
        pair(client)
        state=client.get('/api/v1/conversations/status').json()
        assert state['persistence_status']=='unavailable'
        assert client.post('/api/v1/conversations/selection',json={'session_id':None,'authorize_selected_provider_and_jev':False}).status_code==200
        turn(client)
        assert generation.contexts[0].conversation_recall is None
        assert not opts.database.exists()


def test_catalog_and_source_pages_are_bounded_and_old_cursors_reject_changes(tmp_path,settings):
    opts=options(tmp_path)
    for index in range(22):seed(opts,f'session-{index:03}')
    app,_,_=app_for(settings,opts)
    with client_for(app) as client:
        pair(client)
        first=client.get('/api/v1/conversations/sessions').json()
        assert len(first['sessions'])==20 and first['next_cursor'] is not None
        second=client.get('/api/v1/conversations/sessions',params={'cursor':first['next_cursor']}).json()
        assert len(second['sessions'])==2 and second['next_cursor'] is None
        old=page(client,'session-000')
        changed=client.post('/api/v1/conversations/operations',json={'session_id':'session-000',
            'operation_id':str(uuid4()),'expected_revision':old['revision'],'operation':'correct',
            'entry_id':old['entries'][0]['entry_id'],'text':'synthetic changed','confirmed':True})
        assert changed.status_code==200
        assert client.get('/api/v1/conversations/sessions',params={'cursor':first['next_cursor']}).status_code==409
        assert len(client.get('/api/v1/conversations/sessions').content)<4096


def test_database_and_scope_paths_cannot_escape_operator_configuration(tmp_path):
    opts=options(tmp_path)
    with pytest.raises(ConfigurationError):validate_conversation_options(replace(opts,database=Path('relative.sqlite')))
    checkout=tmp_path/'checkout';checkout.mkdir(mode=0o700)
    with pytest.raises(ConfigurationError):validate_conversation_options(replace(opts,database=checkout/'archive.sqlite'))
    link=tmp_path/'private-link';link.symlink_to(opts.database.parent,target_is_directory=True)
    with pytest.raises(ConfigurationError):validate_conversation_options(replace(opts,database=link/'archive.sqlite'))
    scope=opts.database.parent/'scopes.json';scope.write_text(json.dumps({'version':1,'scopes':[{'name':'local','user_id':'synthetic-owner','character_id':'mira','world_id':'synthetic-world'}]}));scope.chmod(0o600)
    with pytest.raises(ConfigurationError):load_conversation_options(database=opts.database,scope_config=scope,
        scope_alias='missing',checkout_root=checkout,authorize_persistence=True)
    with pytest.raises(ConfigurationError):load_conversation_options(database=opts.database,scope_config=scope,
        scope_alias='local',checkout_root=checkout,authorize_persistence=False)
    assert not opts.database.exists()
