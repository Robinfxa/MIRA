"""Process-admission status through real bootstrap/Actor/HTTP adapters, offline only."""
import asyncio
import json
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from mira.application.ports import media
from mira.bootstrap.character_story import ephemeral_character_factory
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.bootstrap.story_image_provider import create_story_image_factory
from mira.domain.story_images import REQUIRED_PIXEL_CHECKS
from tests.contracts.test_direct_provider_app import arguments
from tests.contracts.test_story_image_adapters import SYNTHETIC_KEY, image_reply, response, review_reply
from tests.contracts.test_story_image_options import options
from tests.contracts.test_story_image_lifecycle_audit import (
    Generation, Wire, actor_for, candidate, image_done, session, settled, submit, wait_until,
)


def process_app(monkeypatch, *, limit='attempts', fail_first=False, blocked=False):
    calls=[]; arrived=threading.Event(); release=threading.Event()
    if not blocked: release.set()
    async def http(request):
        assert request.url.host=='api.openai.com' and request.method=='POST'
        calls.append(request.url.path)
        if request.url.path=='/v1/images/generations':
            arrived.set()
            while not release.is_set():
                try:await asyncio.sleep(.002)
                except asyncio.CancelledError:pass
            return response(image_reply(b'\x89PNG\r\n\x1a\ninvalid' if fail_first else None))
        assert request.url.path=='/v1/responses'
        body=json.loads(request.content)
        binding=json.loads(body['input'][0]['content'][0]['text'])
        document={key:binding[key] for key in ('request_id','specification_digest','checked_content_digest','policy_revision')}
        document.update(checks={key:'pass' for key in REQUIRED_PIXEL_CHECKS},observed_description='Synthetic empty fictional cafe.')
        result=review_reply(document);result['model']=body['model']
        return response(result)
    original=httpx.AsyncClient
    def client(**kwargs):
        assert kwargs.get('transport') is None
        return original(**{**kwargs,'transport':httpx.MockTransport(http)})
    monkeypatch.setattr(httpx,'AsyncClient',client)
    limits={'max_attempts':1 if limit=='attempts' else 4,
        'max_total_bytes':8388608 if limit=='bytes' else 33554432,
        'total_reservation_microusd':60000 if limit=='planning' else 240000}
    make=create_story_image_factory(options=options(**limits),story_enabled=True,
        openai_settings=SimpleNamespace(api_key=SYNTHETIC_KEY))
    generation=Generation();wire=Wire()
    app=create_direct_provider_app(**arguments(generation=generation,input_transport=wire,output_transport=wire,
        character_factory=ephemeral_character_factory(),story_image_factory=make,
        session_turn_limit=8,input_request_limit=8,output_request_limit=8))
    return app,calls,arrived,release,generation


@pytest.mark.parametrize('limit',['attempts','bytes','planning'])
@pytest.mark.parametrize('fail_first',[False,True])
def test_process_exhaustion_after_close_is_held_budget_without_extra_http(monkeypatch,limit,fail_first):
    app,calls,_,_,_=process_app(monkeypatch,limit=limit,fail_first=fail_first)
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);first=image_done(client,path,headers)
        assert first['story_image']['state']==('failed' if fail_first else 'qualified')
        gate=actor_for(app,first,headers)._story_images._operation_admission
        counts=(gate.attempts,gate.reserved_bytes,gate.reserved_microusd)
        expected=['/v1/images/generations']+([] if fail_first else ['/v1/responses'])
        assert calls==expected and gate.active_request is None
        assert client.delete(path,headers=headers).status_code==204
        path,headers=session(client);submit(client,path,headers);state=image_done(client,path,headers)
        assert (state['story_image']['state'],state['story_image']['failure_code'])==('held','budget')
        assert state['last_error'] is None and [effect['kind'] for effect in state['active_grants']]==['subtitle']
        actor=actor_for(app,state,headers);wait_until(lambda:not actor._image_tasks)
        assert calls==expected and (gate.attempts,gate.reserved_bytes,gate.reserved_microusd)==counts
        assert actor._story_images.reserved_bytes==0 and not actor._story_images._artifacts
        assert all(fact.state!='failed' for fact in actor._story_images.facts(actor._state))


def test_busy_process_is_held_ineligible_and_does_not_consume_another_allowance(monkeypatch):
    app,calls,arrived,release,_=process_app(monkeypatch,limit='none',blocked=True)
    with TestClient(app) as client:
        path,headers=session(client);submit(client,path,headers);first=settled(client,path,headers)
        try:
            assert arrived.wait(1)
            first_actor=actor_for(app,first,headers)
            gate=first_actor._story_images._operation_admission
            owner=gate.active_request
            assert client.delete(path,headers=headers).status_code==204
            path2,headers2=session(client);submit(client,path2,headers2);second=image_done(client,path2,headers2)
            assert (second['story_image']['state'],second['story_image']['failure_code'])==('held','ineligible')
            assert second['last_error'] is None and [effect['kind'] for effect in second['active_grants']]==['subtitle']
            assert gate.attempts==1 and gate.active_request==owner and calls==['/v1/images/generations']
        finally:release.set()
        wait_until(lambda:not first_actor._image_tasks)
        submit(client,path2,headers2,activity=2)
        assert image_done(client,path2,headers2)['story_image']['state']=='qualified'
        assert gate.attempts==2 and calls==['/v1/images/generations','/v1/images/generations','/v1/responses']


@pytest.mark.parametrize('message',['image_process_budget_exhausted','image_process_busy'])
def test_untyped_provider_error_text_cannot_impersonate_admission(monkeypatch,message):
    app,calls,_,_,_=process_app(monkeypatch)
    with TestClient(app) as client:
        path,headers=session(client);actor=actor_for(app,client.get(path,headers=headers).json(),headers)
        async def fail(*_):raise ValueError(message)
        monkeypatch.setattr(actor._story_images,'generate_and_review',fail)
        submit(client,path,headers);state=image_done(client,path,headers)
        assert (state['story_image']['state'],state['story_image']['failure_code'])==('failed','generation')
        assert not calls


@pytest.mark.parametrize('reason',['budget','busy'])
def test_admission_error_has_closed_reason_and_legacy_value_error_contract(reason):
    error=media.ImageOperationAdmissionDenied(reason)
    assert isinstance(error,ValueError) and error.reason==reason
    assert str(error)==('image_process_budget_exhausted' if reason=='budget' else 'image_process_busy')
    with pytest.raises(ValueError):media.ImageOperationAdmissionDenied('private-provider-text')


@pytest.mark.parametrize('fence',['stop','new_input','dismiss'])
@pytest.mark.parametrize('reason',['budget','busy'])
def test_late_typed_denial_cannot_relabel_stop_or_new_input(monkeypatch,fence,reason):
    app,calls,_,_,generation=process_app(monkeypatch,limit='none')
    arrived=threading.Event();release=threading.Event();denied=threading.Event()
    with TestClient(app) as client:
        path,headers=session(client);actor=actor_for(app,client.get(path,headers=headers).json(),headers)
        async def late_denial(*_):
            arrived.set()
            while not release.is_set():
                try:await asyncio.sleep(.002)
                except asyncio.CancelledError:pass
            denied.set()
            raise media.ImageOperationAdmissionDenied(reason)
        monkeypatch.setattr(actor._story_images,'generate_and_review',late_denial)
        try:
            submit(client,path,headers);settled(client,path,headers);assert arrived.wait(1)
            if fence=='stop':
                assert client.post(path+'/stop',headers=headers,json={'activity_seq':2,'presentation_cutoff':0}).status_code==200
            elif fence=='dismiss':
                # Dismissal stays in the same epoch; reservation/visibility still fence it.
                from uuid import uuid4
                assert client.post(path+'/photo-dismissals',headers=headers,json={'request_id':str(uuid4()),'expected_revision':0,'presentation_cutoff':0,'target':'all_photos'}).status_code==200
                assert actor._state.output_epoch==1
            else:
                generation.rows=[candidate(image=False)]
                submit(client,path,headers,activity=2);settled(client,path,headers)
            expected=actor._state
        finally:release.set()
        assert denied.wait(1);wait_until(lambda:not actor._image_tasks)
        if fence=='new_input':
            assert actor._state.story_image.state=='held'
            assert actor._state.story_image.failure_code==('budget' if reason=='budget' else 'ineligible')
            assert actor._state.story_image_facts[0].state=='held'
            submit(client,path,headers,activity=3);settled(client,path,headers)
            assert generation.contexts[-1].story_images[0].state=='held'
        else:assert actor._state==expected
        assert not calls
        assert actor._story_images.reserved_bytes==0 and not actor._story_images._artifacts
