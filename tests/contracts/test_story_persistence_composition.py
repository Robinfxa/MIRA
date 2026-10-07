"""Paired checkpoint lifecycle using synthetic ports and temporary private files."""
import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.bootstrap.character_story import builtin_definition,persistent_character_factory,reenter_runtime
from mira.application.story import StoryRuntime
from mira.application.actor_story import SessionCharacterRuntime
from mira.application.session_actor import SessionActor,RuntimeLimits
from mira.adapters.journal.memory import MemoryEventJournal
from mira.domain.models import SessionState,Receipt
from mira.domain.story import ReadinessCatalog,CapabilityRecord,CapabilityState,StoryNode,OfferStatus
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.entrypoints.http.operator_pairing import OperatorPairing
from tests.contracts.test_actor_story_loop import Generation,Review,turn,acknowledge
from tests.contracts.test_direct_story_http import SemanticWire
from tests.contracts.test_direct_provider_app import arguments
from tools import live_provider as cli

ORIGIN='http://127.0.0.1:8000'
CODE='synthetic-character-pairing-code-00000000'


def ready():
    return ReadinessCatalog('synthetic-ready',(
        CapabilityRecord('mira.outfit.amber_raincoat',CapabilityState.READY,'test-assets',
            ('outer.amber','inner.cream'),'synthetic-proof'),))


def app_for(db):
    wire=SemanticWire()
    factory=persistent_character_factory(database=db,scope_id='synthetic-scope',authorized=True,readiness=ready())
    return create_direct_provider_app(**arguments(generation=Generation(),input_transport=wire,output_transport=wire,
        character_binding_factory=factory,operator_pairing=OperatorPairing(CODE,(ORIGIN,'http://localhost:8000')),
        generation_request_limit=3,session_turn_limit=3,input_request_limit=6,output_request_limit=6))


def open_session(client):
    assert client.post('/api/v1/operator/pair',headers={'Origin':ORIGIN},json={'code':CODE}).status_code==204
    created=client.post('/api/v1/sessions',headers={'Origin':ORIGIN},json={'client_instance_id':str(uuid4())})
    assert created.status_code==201,created.text
    value=created.json()
    return '/api/v1/sessions/'+value['session']['session_id'],{'X-Mira-Session-Token':value['session_token'],'Origin':ORIGIN}


def submit(client,path,headers,text,activity,cutoff):
    response=client.post(path+'/inputs',headers=headers,json={'request_id':str(uuid4()),'activity_seq':activity,
        'presentation_cutoff':cutoff,'text':text})
    assert response.status_code==202,response.text
    until=time.monotonic()+3
    while time.monotonic()<until:
        state=client.get(path,headers=headers).json()
        if state['sealed'] or state['last_error']:return state
        time.sleep(.003)
    pytest.fail('bounded synthetic turn timeout')


def test_pairing_precedes_private_story_open_and_revoke_closes_runtime(tmp_path):
    private=tmp_path/'private';private.mkdir(mode=0o700);db=private/'story.sqlite3'
    app=app_for(db)
    with TestClient(app,base_url=ORIGIN) as client:
        assert app.state.container is None and not db.exists()
        page=client.get('/');assert 'OpenAI ChatGPT' in page.text
        assert client.post('/api/v1/sessions',headers={'Origin':ORIGIN},json={'client_instance_id':str(uuid4())}).status_code==401
        assert not db.exists()
        path,headers=open_session(client)
        assert not db.exists(),'read-only missing checkpoint must not create database'
        assert client.post('/api/v1/operator/revoke',headers={'Origin':ORIGIN}).status_code==204
        assert app.state.container is None
        assert client.get(path,headers=headers).status_code==401


def test_real_receipts_persist_fiction_and_reopen_with_no_pending_grant(tmp_path):
    private=tmp_path/'private';private.mkdir(mode=0o700);db=private/'story.sqlite3'
    app=app_for(db)
    with TestClient(app,base_url=ORIGIN) as client:
        path,headers=open_session(client)
        first=submit(client,path,headers,'offer',1,0);assert first['sealed'],first
        seq=0
        def ack(effect):
            nonlocal seq
            seq+=1
            receipt={k:effect[k] for k in ('digest','output_epoch','activity_seq')}
            receipt.update(effect_id=effect['id'],presentation_seq=seq)
            response=client.post(path+'/receipts',headers=headers,json=receipt)
            assert response.status_code==200,response.text
        ack(first['active_grants'][0]);assert db.exists()
        second=submit(client,path,headers,'yes',2,1);assert second['sealed'],second
        for effect in second['active_grants']:ack(effect)
        actor=app.state.container.sessions.get(path.rsplit('/',1)[-1],headers['X-Mira-Session-Token'])
        assert actor._character_runtime.runtime.story.node is StoryNode.RAIN_VIEW
    app2=app_for(db)
    with TestClient(app2,base_url=ORIGIN) as client:
        path,headers=open_session(client)
        actor=app2.state.container.sessions.get(path.rsplit('/',1)[-1],headers['X-Mira-Session-Token'])
        state=actor._character_runtime.runtime.story
        assert state.node is StoryNode.RAIN_VIEW and state.current_outfit=='amber_raincoat'
        assert state.pending is None and state.epoch==0 and len(state.episodes)==1
        assert state.episodes[0].receipt_id.startswith('visual.')
        assert 'not_user_fact_or_shared_experience' in state.episodes[0].claim_boundary
        assert getattr(state,'user_facts',None) is None


@pytest.mark.asyncio
async def test_unpresented_offer_is_not_promoted_on_reentry():
    async def run():
        runtime=StoryRuntime(builtin_definition(),'synthetic-scope')
        character=SessionCharacterRuntime(runtime,ready())
        actor=SessionActor(SessionState(str(uuid4()),str(uuid4())),Generation(),Review(),MemoryEventJournal(50),
            RuntimeLimits(3,5,20),character_runtime=character)
        try:
            first=await turn(actor,'offer',1);assert first.sealed and runtime.story.pending
            restored=reenter_runtime(StoryRuntime.from_snapshot(runtime.definition,runtime.snapshot()))
            assert restored.story.node is StoryNode.CAFE_CHAT
            assert restored.story.active_offer_id is None and restored.story.pending is None
            assert restored.story.offer_status is OfferStatus.SUSPENDED
        finally:await actor.close()
    await run()


@pytest.mark.asyncio
async def test_checkpoint_wait_never_holds_actor_stop_lock():
    async def run():
        entered=asyncio.Event();release=asyncio.Event()
        async def save(snapshot):entered.set();await release.wait()
        character=SessionCharacterRuntime(StoryRuntime(builtin_definition(),'scope'),ready(),save)
        actor=SessionActor(SessionState(str(uuid4()),str(uuid4())),Generation(),Review(),MemoryEventJournal(50),
            RuntimeLimits(3,5,20),character_runtime=character)
        try:
            first=await turn(actor,'offer',1);effect=first.active_grants[0]
            pending=asyncio.create_task(acknowledge(actor,effect,1));await entered.wait()
            stopped=await asyncio.wait_for(actor.stop(activity_seq=2,cutoff=1),.2)
            assert stopped.output_epoch>effect.output_epoch and not pending.done()
            release.set();await pending
            assert character.runtime.story.node is StoryNode.AWAIT_RAIN_CHOICE
        finally:release.set();await actor.close()
    await run()


def test_story_check_is_inert_and_discloses_persistence(monkeypatch,capsys):
    from mira.config.settings import Settings
    monkeypatch.setattr(cli,'_load',lambda _:(Settings(),None))
    monkeypatch.setattr(cli,'_generation',lambda *_:pytest.fail('model credential read'))
    args=['check','--provider','chatgpt_subscription','--model','synthetic','--env-file','/synthetic.env',
        '--story','--story-db','/synthetic/story.sqlite3','--story-scope','local',
        '--authorize-story-persistence-and-recall','--create-local-operator-pairing']
    assert cli.main(args)==0
    value=json.loads(capsys.readouterr().out)['character_story']
    assert value['persistent_history'] and not value['database_opened'] and not value['pairing_file_created']
