"""Synthetic Actor archive/reentry wiring; no credentials or network."""
import asyncio
import json

import pytest

from mira.adapters.memory.async_conversation import AsyncConversationArchive
from mira.adapters.memory.conversation import ConversationArchive
from mira.application.actor_conversation import SessionConversationBinding
from mira.application.conversation_archive import ConversationArchiveError
from mira.application.contracts import generation_context_data
from mira.application.interrupted_intent import AcceptedInput
from mira.application.session_actor import SessionActor, RuntimeLimits
from mira.adapters.journal.memory import MemoryEventJournal
from mira.domain.memory import MemoryScope
from mira.domain.models import SessionState, Phase, Receipt
from tests.contracts.test_bounded_conversation_context import Generation, Review

async def idle(value):
    async with asyncio.timeout(3):
        while True:
            state = await value.snapshot()
            if state.phase in (Phase.READY, Phase.ERROR, Phase.STOPPED):
                return state
            await asyncio.sleep(.001)


SCOPE = MemoryScope('synthetic-user', 'mira', 'synthetic-world')


async def archive(path):
    value = AsyncConversationArchive(path, fixed_scope=SCOPE, enabled=True,
        authorize_transcript_persistence=True)
    await value.open(pairing_confirmed=True)
    return value


def actor(binding, generation=None, session='current'):
    return SessionActor(SessionState(session, 'client'), generation or Generation(), Review(),
        MemoryEventJournal(32), RuntimeLimits(2, 100, 1000), conversation_binding=binding)


def test_recording_provider_and_google_authorizations_are_independent(tmp_path):
    store = AsyncConversationArchive(tmp_path / 'private' / 'db', fixed_scope=SCOPE)
    with pytest.raises(ConversationArchiveError): SessionConversationBinding(store)
    with pytest.raises(ConversationArchiveError):
        SessionConversationBinding(store, authorize_transcript_persistence=True, recall_session_id='old')
    with pytest.raises(ConversationArchiveError):
        SessionConversationBinding(store, authorize_transcript_persistence=True, recall_session_id='old',
            authorize_recall_to_provider_and_jev=True, speech_enabled=True)
    assert not (tmp_path / 'private').exists()


@pytest.mark.asyncio
async def test_actor_records_only_accepted_and_actual_then_reentry_is_separately_labelled(tmp_path):
    path = tmp_path / 'private' / 'conversation.sqlite'
    store = await archive(path)
    binding = SessionConversationBinding(store, authorize_transcript_persistence=True,
        close_archive_on_actor_close=True)
    value = actor(binding, session='old-session')
    await value.submit(request_id='r1', activity_seq=1, cutoff=0, text='原始可靠输入')
    state = await idle(value)
    assert state.phase is Phase.READY
    await binding.flush()
    snapshot = await store.load_session('old-session')
    assert [row.stage for row in snapshot.records] == ['accepted_input']
    effect = state.active_grants[0]
    await value.receipt(Receipt(effect.id, effect.digest, effect.output_epoch, effect.activity_seq, 1))
    await binding.flush()
    assert [row.stage for row in (await store.load_session('old-session')).records] == ['accepted_input','presented_effect']
    await value.close()
    reopened = await archive(path)
    linked = SessionConversationBinding(reopened, authorize_transcript_persistence=True,
        recall_session_id='old-session', authorize_recall_to_provider_and_jev=True,
        close_archive_on_actor_close=True)
    generator = Generation()
    current = actor(linked, generator)
    try:
        await current.submit(request_id='r2', activity_seq=1, cutoff=0, text='新会话的当前输入')
        assert (await idle(current)).phase is Phase.READY
        data = generation_context_data(generator.contexts[0])
        assert data['user_inputs'] == ('新会话的当前输入',)
        assert data['presented_effects'] == ()
        recalled = data['conversation_recall']
        assert '原始可靠输入' in json.dumps(recalled,ensure_ascii=False)
        assert recalled['physical_hearing_or_understanding_established'] is False
        assert recalled['evidence_status'].startswith('historical_')
    finally: await current.close()


@pytest.mark.asyncio
async def test_corrected_source_during_generation_fences_stale_recall(tmp_path):
    path = tmp_path / 'private' / 'conversation.sqlite'
    seed = ConversationArchive(path, fixed_scope=SCOPE, enabled=True, authorize_transcript_persistence=True)
    seed.open(pairing_confirmed=True)
    original = seed.append_input('old', AcceptedInput('old-input',1,'synthetic original','text',0))
    seed.close()
    store = await archive(path)
    binding = SessionConversationBinding(store, authorize_transcript_persistence=True, recall_session_id='old',
        authorize_recall_to_provider_and_jev=True, close_archive_on_actor_close=True)
    entered, release = asyncio.Event(), asyncio.Event()
    class Gated(Generation):
        async def generate(self, context):
            entered.set()
            await release.wait()
            async for item in super().generate(context): yield item
    value = actor(binding, Gated())
    try:
        await value.submit(request_id='now', activity_seq=1, cutoff=0, text='current')
        await asyncio.wait_for(entered.wait(), 1)
        editor = ConversationArchive(path, fixed_scope=SCOPE, enabled=True, authorize_transcript_persistence=True)
        editor.open(pairing_confirmed=True)
        editor.correct_input('old', original.entry_id, 'synthetic corrected')
        editor.close()
        release.set()
        state = await idle(value)
        assert state.phase is Phase.ERROR and state.last_error == 'memory_context_stale'
        assert not state.active_grants
    finally:
        release.set()
        await value.close()


@pytest.mark.asyncio
async def test_stop_never_waits_for_archive_read_and_late_read_cannot_generate():
    from mira.application.conversation_archive import ConversationSnapshot
    entered, release = asyncio.Event(), asyncio.Event()
    class Slow:
        async def capture(self, *_): pass
        async def load_session(self, name):
            entered.set()
            try: await release.wait()
            except asyncio.CancelledError: await release.wait()
            return ConversationSnapshot(name, 0, ())
        async def session_revision(self, *_): return 0
        async def aclose(self): pass
    binding = SessionConversationBinding(Slow(), authorize_transcript_persistence=True,
        recall_session_id='old', authorize_recall_to_provider_and_jev=True)
    gen = Generation()
    value = actor(binding, gen)
    try:
        await value.submit(request_id='now', activity_seq=1, cutoff=0, text='current')
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.wait_for(value.stop(activity_seq=2, cutoff=0), .1)
        release.set()
        await asyncio.sleep(.01)
        assert not gen.contexts
        assert (await value.snapshot()).phase is Phase.STOPPED
    finally: release.set(); await value.close()


@pytest.mark.asyncio
async def test_100_turn_archive_retains_oldest_source_while_wire_is_bounded(tmp_path):
    path = tmp_path / 'private' / 'conversation.sqlite'
    store = await archive(path)
    binding = SessionConversationBinding(store, authorize_transcript_persistence=True,
        close_archive_on_actor_close=True)
    gen = Generation(1200)
    value = actor(binding, gen, session='full-session')
    try:
        for turn in range(1, 101):
            await value.submit(request_id=f'r{turn}', activity_seq=turn, cutoff=turn-1,
                text=f'original reliable input {turn}')
            state = await idle(value)
            assert state.phase is Phase.READY
            e = state.active_grants[0]
            await value.receipt(Receipt(e.id,e.digest,e.output_epoch,e.activity_seq,turn))
        await asyncio.wait_for(binding.flush(), 10)
        assert binding.persistence_status == 'saved'
        snapshot = await store.load_session('full-session')
        assert len(snapshot.records) == 200
        assert snapshot.records[0].payload()['input']['text'] == 'original reliable input 1'
        assert snapshot.records[-1].payload()['effect']['value'] == '合' * 1200
        assert len(gen.prompts[-1].encode()) <= 65536
    finally: await value.close()


@pytest.mark.asyncio
async def test_operational_archive_absence_degrades_without_extra_generation():
    class Unavailable:
        async def capture(self,*_): raise OSError('synthetic absent')
        async def load_session(self,*_): raise OSError('synthetic absent')
        async def session_revision(self,*_): raise OSError('synthetic absent')
        async def aclose(self): pass
    binding = SessionConversationBinding(Unavailable(), authorize_transcript_persistence=True,
        recall_session_id='old', authorize_recall_to_provider_and_jev=True)
    generator = Generation()
    value = actor(binding, generator)
    try:
        await value.submit(request_id='now',activity_seq=1,cutoff=0,text='hello')
        assert (await idle(value)).phase is Phase.READY
        assert len(generator.contexts) == 1
        data = generation_context_data(generator.contexts[0])
        assert 'conversation_recall' not in data
        assert data['conversation_recall_status'] == 'unavailable'
        assert binding.persistence_status == 'unavailable_or_write_outcome_unknown'
    finally: await value.close()


@pytest.mark.asyncio
async def test_new_turn_discards_old_late_reentry_read():
    from mira.application.conversation_archive import ConversationSnapshot
    entered, release = asyncio.Event(), asyncio.Event()
    class Slow:
        calls = 0
        async def capture(self,*_): pass
        async def load_session(self,name):
            self.calls += 1
            if self.calls == 1:
                entered.set()
                try: await release.wait()
                except asyncio.CancelledError: await release.wait()
            return ConversationSnapshot(name,0,())
        async def session_revision(self,*_): return 0
        async def aclose(self): pass
    binding = SessionConversationBinding(Slow(), authorize_transcript_persistence=True,
        recall_session_id='old', authorize_recall_to_provider_and_jev=True)
    generator = Generation()
    value = actor(binding, generator)
    try:
        await value.submit(request_id='first',activity_seq=1,cutoff=0,text='old current')
        await asyncio.wait_for(entered.wait(),1)
        await value.submit(request_id='second',activity_seq=2,cutoff=0,text='new current')
        assert (await idle(value)).phase is Phase.READY
        release.set()
        await asyncio.sleep(.01)
        assert [c.user_text for c in generator.contexts] == ['new current']
    finally: release.set(); await value.close()


@pytest.mark.asyncio
async def test_cross_session_reader_packet_fails_before_generation():
    from mira.application.conversation_archive import ConversationSnapshot
    class Forged:
        async def capture(self,*_): pass
        async def load_session(self,*_): return ConversationSnapshot('not-authorized-session',0,())
        async def session_revision(self,*_): return 0
        async def aclose(self): pass
    binding = SessionConversationBinding(Forged(), authorize_transcript_persistence=True,
        recall_session_id='old', authorize_recall_to_provider_and_jev=True)
    gen = Generation(); value = actor(binding,gen)
    try:
        await value.submit(request_id='now',activity_seq=1,cutoff=0,text='hello')
        assert (await idle(value)).phase is Phase.ERROR
        assert not gen.contexts
    finally: await value.close()


@pytest.mark.asyncio
async def test_revoke_during_generation_prevents_recalled_output(tmp_path):
    path = tmp_path / 'private' / 'conversation.sqlite'
    seed = ConversationArchive(path,fixed_scope=SCOPE,enabled=True,authorize_transcript_persistence=True)
    seed.open(pairing_confirmed=True)
    seed.append_input('old',AcceptedInput('old-input',1,'synthetic private past','text',0))
    seed.close()
    store = await archive(path)
    binding = SessionConversationBinding(store,authorize_transcript_persistence=True,
        recall_session_id='old',authorize_recall_to_provider_and_jev=True,close_archive_on_actor_close=True)
    entered,release=asyncio.Event(),asyncio.Event()
    class Gated(Generation):
        async def generate(self,context):
            entered.set(); await release.wait()
            async for result in super().generate(context): yield result
    value=actor(binding,Gated())
    try:
        await value.submit(request_id='now',activity_seq=1,cutoff=0,text='current')
        await asyncio.wait_for(entered.wait(),1)
        binding.revoke();release.set()
        state=await idle(value)
        assert state.phase is Phase.ERROR and not state.active_grants
        assert binding.persistence_status.startswith('revoked_')
    finally: release.set();await value.close()


@pytest.mark.asyncio
async def test_canceled_started_write_retains_capacity_and_can_commit_exact_input(tmp_path,monkeypatch):
    import threading
    path=tmp_path/'private'/'conversation.sqlite'
    store=await archive(path)
    entered,release=threading.Event(),threading.Event()
    original=store._archive.capture
    def blocked(*args):
        entered.set();release.wait(2)
        return original(*args)
    monkeypatch.setattr(store._archive,'capture',blocked)
    accepted=(AcceptedInput('captured',1,'synthetic accepted before cancellation','text',0),)
    task=asyncio.create_task(store.capture('write-session',accepted,(),(),()))
    try:
        async with asyncio.timeout(1):
            while not entered.is_set():await asyncio.sleep(.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        with pytest.raises(OSError,match='busy'):
            await store.capture('write-session',accepted,(),(),())
        release.set()
        async with asyncio.timeout(2):
            while not store._active.done():await asyncio.sleep(.001)
        snapshot=await store.load_session('write-session')
        assert snapshot.records[0].payload()['input']['text']=='synthetic accepted before cancellation'
        assert len(snapshot.records)==1
    finally:release.set();await store.aclose()
