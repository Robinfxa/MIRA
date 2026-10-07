"""Explicit stored-evidence voice consent and lazy paired resource ownership.

All credentials, memories and transports are synthetic. No provider is contacted.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.application.actor_memory import SessionMemoryBinding
from mira.bootstrap.providers import GoogleVoiceProviders
from mira.config.loader import ConfigurationError
from mira.domain.memory import MemoryScope
from mira.entrypoints.http.app import create_app
from mira.entrypoints.http.operator_pairing import OperatorPairing
from tests.contracts.test_memory_recall_app_lifecycle import (
    Reader, single_operator, ORIGIN, CODE,
)


def resources(settings, *, broken_memory=False):
    reader = Reader()
    calls = []

    class Speech:
        async def synthesize(self, *_args):
            raise AssertionError('No synthesis request in resource test')
            yield

    class Recognition:
        async def transcribe(self, *_args):
            raise AssertionError('No recognition request in resource test')
            yield

    async def shutdown():
        calls.append('voice_close')

    def voice():
        calls.append('voice_open')
        return GoogleVoiceProviders(Recognition(), Speech(), shutdown)

    async def memory():
        calls.append('memory_open')
        if broken_memory:
            raise RuntimeError('synthetic startup failure')
        return SessionMemoryBinding(reader, MemoryScope('synthetic-user','mira','synthetic-world'))

    args = dict(settings=single_operator(settings), memory_factory=memory,
        voice_factory=voice,
        operator_pairing=OperatorPairing(CODE, tuple(settings.http.allowed_origins)))
    return args, reader, calls


def test_authorized_memory_voice_stays_inert_until_pair_and_closes_on_revoke(settings):
    args, reader, calls = resources(settings)
    app = create_app(**args, authorize_memory_to_speech_provider=True)
    assert calls == []
    with TestClient(app, base_url=ORIGIN, headers={'Origin':ORIGIN}) as client:
        assert client.get('/api/v1/voice-capabilities').status_code == 401
        assert calls == [] and reader.reads == 0
        assert client.post('/api/v1/operator/pair',json={'code':CODE}).status_code == 204
        assert calls == ['voice_open','memory_open']
        created=client.post('/api/v1/sessions',json={'client_instance_id':str(uuid4())})
        assert created.status_code == 201
        assert app.state.container.speech_enabled and app.state.container.microphone_enabled
        assert client.post('/api/v1/operator/revoke').status_code == 204
        assert reader.closed == 1 and calls.count('voice_close') == 1
        assert client.get('/api/v1/voice-capabilities').status_code == 401
    assert reader.closed == 1 and calls.count('voice_close') == 1


@pytest.mark.parametrize('consent',[False, None, 'yes', 1])
def test_google_memory_consent_is_not_inherited_from_other_options(settings,consent):
    args, reader, calls = resources(settings)
    with pytest.raises(ConfigurationError):
        create_app(**args, authorize_memory_to_speech_provider=consent)
    assert calls == [] and reader.reads == 0


def test_memory_open_failure_closes_voice_without_granting_session(settings):
    args, reader, calls = resources(settings, broken_memory=True)
    app=create_app(**args, authorize_memory_to_speech_provider=True)
    with TestClient(app, base_url=ORIGIN,headers={'Origin':ORIGIN}) as client:
        assert client.post('/api/v1/operator/pair',json={'code':CODE}).status_code == 503
        assert client.post('/api/v1/sessions',json={'client_instance_id':str(uuid4())}).status_code == 401
    assert calls==['voice_open','memory_open','voice_close'] and reader.reads==0


def test_voice_memory_cli_requires_distinct_ack_before_loading_config(monkeypatch):
    from tools import live_provider as cli
    from tests.contracts.test_direct_memory_entry import arguments, complete_flags
    from mira.config import memory
    monkeypatch.setattr(memory,'load_memory_recall_options',lambda **_:pytest.fail('read before consent'))
    args=cli._parser().parse_args(arguments(*complete_flags(),'--voice'))
    with pytest.raises(cli.EntryError,match='Google'):
        cli._memory_options(args)


@pytest.mark.parametrize('review_mode',['luna_tools','legacy_jev'])
def test_voice_memory_check_declares_tts_recipient_without_creating_any_resource(monkeypatch,capsys,review_mode):
    import json
    from tools import live_provider as cli
    from tests.contracts.test_direct_memory_entry import arguments,complete_flags
    from mira.config.settings import Settings
    from mira.config import memory
    monkeypatch.setattr(memory,'load_memory_recall_options',lambda **_:object())
    monkeypatch.setattr(cli,'_load',lambda _:(Settings(),None))
    monkeypatch.setattr(cli,'_voice_factory',lambda *_:pytest.fail('voice created by check'))
    assert cli.main(arguments(*complete_flags(),'--voice','--authorize-memory-derived-speech-to-google','--action-review-mode',review_mode))==0
    block=json.loads(capsys.readouterr().out)['memory_recall']
    assert block['recipients']==['OpenAI ChatGPT subscription backend']+(['TypeSafe/JEV output review'] if review_mode=='legacy_jev' else [])+['Google Cloud TTS (approved generated speech may contain recalled evidence)']
    assert block['database_opened'] is False and block['pairing_file_created'] is False


async def speech_actor():
    import asyncio
    from mira.application.contracts import CandidateRange, EffectProposal
    from mira.application.session_actor import SessionActor, RuntimeLimits
    from mira.adapters.journal.memory import MemoryEventJournal
    from mira.domain.models import EffectKind, SessionState
    from tests.contracts.test_actor_memory_recall import AsyncReader, CaptureLegacyReview, SCOPE
    from tests.integration.test_voice_http import Tts
    reader=AsyncReader(); tts=Tts()
    class Generation:
        async def generate(self, context):
            yield CandidateRange((EffectProposal(EffectKind.SPEECH,'Synthetic recalled tea.'),),'synthetic')
    actor=SessionActor(SessionState(str(uuid4()),str(uuid4())),Generation(),CaptureLegacyReview(),MemoryEventJournal(100),
        RuntimeLimits(3,5,20),speech_synthesis=tts,memory_binding=SessionMemoryBinding(reader,SCOPE))
    await actor.submit(request_id=str(uuid4()),activity_seq=1,cutoff=0,text='synthetic request')
    async with asyncio.timeout(2):
        while not (state:=await actor.snapshot()).sealed:
            await asyncio.sleep(.005)
    return actor,reader,tts,state.active_grants[0]


def speech_args(effect):
    return dict(effect_id=effect.id,digest=effect.digest,output_epoch=effect.output_epoch,
        activity_seq=effect.activity_seq)


@pytest.mark.asyncio
async def test_forget_after_grant_blocks_tts_before_any_transmission():
    from mira.domain.errors import DomainError
    actor,reader,tts,effect=await speech_actor()
    try:
        reader.revision+=1
        with pytest.raises(DomainError) as error:
            await actor.open_speech(**speech_args(effect))
        assert error.value.code=='memory_context_stale' and tts.calls==[]
    finally:
        await actor.close()


@pytest.mark.asyncio
async def test_stop_remains_immediate_during_speech_memory_revision_check():
    import asyncio
    from mira.domain.errors import DomainError
    actor,reader,tts,effect=await speech_actor()
    entered=asyncio.Event();release=asyncio.Event()
    async def blocked(_scope):
        entered.set();await release.wait();return reader.revision
    reader.scope_revision=blocked
    task=asyncio.create_task(actor.open_speech(**speech_args(effect)))
    try:
        await asyncio.wait_for(entered.wait(),.2)
        await asyncio.wait_for(actor.stop(activity_seq=2,cutoff=0),.2)
        release.set()
        with pytest.raises(DomainError):await task
        assert tts.calls==[]
    finally:
        release.set();task.cancel();await actor.close()


@pytest.mark.asyncio
async def test_revision_change_stops_further_output_without_claiming_unsent_provider_text():
    from mira.domain.errors import DomainError
    actor,reader,tts,effect=await speech_actor()
    operation=None
    try:
        operation=await actor.open_speech(**speech_args(effect))
        await actor.validate_media(operation)
        reader.revision+=1
        with pytest.raises(DomainError) as error:await actor.validate_media(operation)
        assert error.value.code=='memory_context_stale'
        assert operation.cancelled.is_set()
    finally:
        if operation is not None:await actor.close_media(operation)
        await actor.close()
