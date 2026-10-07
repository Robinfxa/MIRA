"""Independent hostile synthetic archive/Actor boundaries; no providers or credentials."""
import asyncio
import json
import sqlite3
from dataclasses import replace

import pytest

from mira.adapters.memory.conversation import ConversationArchive
from mira.adapters.memory.async_conversation import AsyncConversationArchive
from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.actor_conversation import SessionConversationBinding
from mira.application.contracts import CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict, generation_context_data
from mira.application.conversation_archive import ConversationArchiveError, conversation_recall_data
from mira.application.interrupted_intent import AcceptedInput
from mira.application.session_actor import SessionActor, RuntimeLimits
from mira.domain.memory import MemoryScope
from mira.domain.models import SessionState, EffectKind, Effect, Receipt, AudioProgress, AudioStatus, Phase

SCOPE = MemoryScope('audit-owner', 'audit-character', 'audit-world')

def opened(path, scope=SCOPE):
    return ConversationArchive(path, fixed_scope=scope, enabled=True, authorize_transcript_persistence=True).open(pairing_confirmed=True)

def item(index=0, text='synthetic accepted statement'):
    return AcceptedInput(f'input-{index}', index+1, text, 'text', index)

def effect(index=0, text='synthetic displayed response', kind=EffectKind.SUBTITLE):
    return Effect(f'effect-{index}', kind, text, f'digest-{index}', index+1, index+1)

def receipt(e, seq=1):
    return Receipt(e.id, e.digest, e.output_epoch, e.activity_seq, seq)

class AllowReview:
    def __init__(self): self.contexts=[]
    async def review(self, context, candidate):
        self.contexts.append(context)
        return ReviewObservation(ReviewVerdict.ALLOW, 'offline-independent-fixture')

class Generator:
    def __init__(self): self.contexts=[]
    async def generate(self, context):
        self.contexts.append(context)
        yield CandidateRange((EffectProposal(EffectKind.SUBTITLE, 'current reply'),), 'independent-fixture')

def actor(binding, gen=None, review=None):
    return SessionActor(SessionState('audit-current', 'client'), gen or Generator(), review or AllowReview(),
        MemoryEventJournal(100), RuntimeLimits(5, 100, 1000), conversation_binding=binding)

async def settled(value):
    async with asyncio.timeout(3):
        while True:
            state=await value.snapshot()
            if state.phase in (Phase.READY, Phase.ERROR, Phase.STOPPED): return state
            await asyncio.sleep(.001)

async def real_binding(path):
    seed=opened(path)
    seed.append_input('old', item(text='historical private synthetic statement'))
    seed.close()
    archive=AsyncConversationArchive(path, fixed_scope=SCOPE, enabled=True, authorize_transcript_persistence=True)
    await archive.open(pairing_confirmed=True)
    binding=SessionConversationBinding(archive, authorize_transcript_persistence=True, recall_session_id='old',
        authorize_recall_to_provider_and_jev=True, close_archive_on_actor_close=True)
    return archive,binding

@pytest.mark.asyncio
async def test_revoke_during_final_revision_read_prevents_any_new_grant(tmp_path):
    archive,binding=await real_binding(tmp_path/'private'/'history.sqlite')
    entered, release, consumed, finish = (asyncio.Event() for _ in range(4))
    actual_revision=archive.session_revision
    calls=0
    async def delayed_revision(name):
        nonlocal calls
        result=await actual_revision(name)
        calls+=1
        if calls == 2:  # Last validation immediately before an effect is admitted.
            entered.set()
            await release.wait()
        return result
    archive.session_revision=delayed_revision
    class G(Generator):
        async def generate(self, context):
            async for candidate in super().generate(context): yield candidate
            consumed.set()
            await finish.wait()
    value=actor(binding,G())
    try:
        await value.submit(request_id='now', activity_seq=1, cutoff=0, text='respond now')
        await asyncio.wait_for(entered.wait(),2)
        binding.revoke()
        release.set()
        async with asyncio.timeout(2):
            while not consumed.is_set() and (await value.snapshot()).phase != Phase.ERROR:
                await asyncio.sleep(.001)
        state=await value.snapshot()
        print('revoke_boundary_state',state.phase,[(e.kind,e.value) for e in state.active_grants],binding.persistence_status)
        assert not state.active_grants, 'Recalled output obtained a new grant after binding.revoke returned'
    finally:
        release.set();finish.set();await value.close()


@pytest.mark.asyncio
async def test_ui_selection_cannot_change_after_actor_creation_during_await(tmp_path):
    from mira.bootstrap.conversation import conversation_factory
    from tests.contracts.test_paired_conversation_lifecycle import options,seed
    opts=options(tmp_path);seed(opts)
    runtime=await conversation_factory(opts,recipients='synthetic OpenAI + JEV')()
    entered,release=asyncio.Event(),asyncio.Event()
    original=runtime.load_session
    async def delayed(name):
        result=await original(name);entered.set();await release.wait();return result
    runtime.load_session=delayed
    task=asyncio.create_task(runtime.select('old',recall_consent=True,google_consent=False))
    try:
        await asyncio.wait_for(entered.wait(),1)
        binding=runtime.create(SessionState('current','client'))
        release.set()
        with pytest.raises(ConversationArchiveError):await task
        assert binding.recall_session_id is None
        assert runtime.recall_session_id is None
    finally:
        release.set();await runtime.aclose()


@pytest.mark.asyncio
async def test_uncooperative_capture_completion_cannot_replace_revoked_status():
    entered,cancelled,release=asyncio.Event(),asyncio.Event(),asyncio.Event()
    class Storage:
        async def capture(self,*args):
            entered.set()
            try:await release.wait()
            except asyncio.CancelledError:
                cancelled.set();await release.wait()
        async def load_session(self,*args):raise AssertionError('not a recall test')
        async def session_revision(self,*args):return 0
        async def aclose(self):pass
    binding=SessionConversationBinding(Storage(),authorize_transcript_persistence=True)
    binding.schedule_capture(SessionState('current','client'),())
    await asyncio.wait_for(entered.wait(),1)
    binding.revoke()
    await asyncio.wait_for(cancelled.wait(),1)
    release.set();await binding.flush()
    assert binding.persistence_status=='revoked_existing_records_retained'

@pytest.mark.parametrize('mutation',['correct','forget'])
@pytest.mark.asyncio
async def test_source_mutation_suppresses_derived_reply_across_reentry_sessions(tmp_path,mutation):
    path=tmp_path/'private'/'history.sqlite'
    archive,binding=await real_binding(path)
    original=(await archive.load_session('old')).records[0]
    derived='Derived assertion from historical private synthetic statement'
    class HistoricalGenerator(Generator):
        async def generate(self,context):
            recalled=generation_context_data(context)['conversation_recall']
            assert 'historical private synthetic statement' in json.dumps(recalled)
            self.contexts.append(context)
            yield CandidateRange((EffectProposal(EffectKind.SUBTITLE,derived),),'independent-fixture')
    value=actor(binding,HistoricalGenerator())
    await value.submit(request_id='reentry-question',activity_seq=1,cutoff=0,text='What did I tell you before?')
    state=await settled(value)
    assert state.phase is Phase.READY
    await value.receipt(receipt(state.active_grants[0]))
    await binding.flush()
    await value.close()
    editor=opened(path)
    try:
        if mutation=='correct': editor.correct_input('old',original.entry_id,'replacement synthetic fact')
        else: editor.forget_input('old',original.entry_id)
        after_source=editor.load_session('old')
        after_derived=editor.load_session('audit-current')
        assert 'historical private synthetic statement' not in json.dumps([r.payload() for r in after_source.records])
        recall=conversation_recall_data(after_derived,request_text='What did I tell you before?')
        print('cross_session_mutation',mutation,'remaining_stages',[r.stage for r in after_derived.records])
        assert derived not in json.dumps(recall), 'A derived cross-session reply remains recall-eligible after its source was corrected/forgotten'
    finally: editor.close()



def test_exact_one_row_budget_is_not_exceeded_by_final_loss_flag(tmp_path):
    archive=opened(tmp_path/'private'/'archive.sqlite')
    try:
        archive.append_input('past',item(text='x'*1000))
        snapshot=archive.load_session('past')
        full=conversation_recall_data(snapshot,request_text='x',max_bytes=8192)
        exact=len(json.dumps(full,ensure_ascii=False,separators=(',',':')).encode())
        assert exact>1024
        limited=conversation_recall_data(snapshot,request_text='x',max_bytes=exact-1)
        size=len(json.dumps(limited,ensure_ascii=False,separators=(',',':')).encode())
        assert size<=exact-1,(size,exact-1)
    finally:archive.close()


async def _record_reentry(path,sid,source,text,reply):
    archive=AsyncConversationArchive(path,fixed_scope=SCOPE,enabled=True,authorize_transcript_persistence=True)
    await archive.open(pairing_confirmed=True)
    binding=SessionConversationBinding(archive,authorize_transcript_persistence=True,
        recall_session_id=source,authorize_recall_to_provider_and_jev=True,close_archive_on_actor_close=True)
    class G(Generator):
        async def generate(self,context):
            self.contexts.append(context)
            yield CandidateRange((EffectProposal(EffectKind.SUBTITLE,reply),),'chain-fixture')
    generation=G()
    value=SessionActor(SessionState(sid,'client'),generation,AllowReview(),MemoryEventJournal(100),
        RuntimeLimits(5,100,1000),conversation_binding=binding)
    try:
        await value.submit(request_id=sid+'-input',activity_seq=1,cutoff=0,text=text)
        state=await settled(value);assert state.phase is Phase.READY
        await value.receipt(receipt(state.active_grants[0]));await binding.flush()
        assert binding.persistence_status=='saved'
        return generation.contexts[0].conversation_recall
    finally:await value.close()


@pytest.mark.parametrize('mutation',['correct','forget'])
@pytest.mark.asyncio
async def test_transitive_reentry_preserves_inputs_raw_receipts_and_new_corrected_source(tmp_path,mutation):
    path=tmp_path/'private'/'archive.sqlite';store=opened(path)
    original=store.append_input('A',item(text='A original synthetic source'))
    store.close()
    await _record_reentry(path,'B','A','B independent user statement','B derived synthetic reply')
    packet=await _record_reentry(path,'C','B','C independent user statement','C derived synthetic reply')
    assert 'B derived synthetic reply' in packet.context_json
    store=opened(path)
    before=store.load_session('C').snapshot_revision
    if mutation=='correct':store.correct_input('A',original.entry_id,'A corrected independent source')
    else:store.forget_input('A',original.entry_id)
    try:
        for sid in ('B','C'):
            snapshot=store.load_session(sid)
            assert [r.stage for r in snapshot.records]==['accepted_input']
            assert snapshot.records[0].payload()['input']['text']==sid+' independent user statement'
            raw=store.management_page(sid)
            assert any(row['stage']=='presented_effect' and not row['active'] for row in raw['entries'])
        assert store.session_revision('C')>before
    finally:store.close()
    if mutation=='correct':
        packet=await _record_reentry(path,'D','A','new independent session question','D new-source reply')
        assert 'A corrected independent source' in packet.context_json
        store=opened(path)
        try:assert any(r.stage=='presented_effect' for r in store.load_session('D').records)
        finally:store.close()


@pytest.mark.asyncio
async def test_late_old_epoch_receipt_keeps_original_source_version_even_after_source_correction(tmp_path):
    path=tmp_path/'private'/'archive.sqlite';archive,binding=await real_binding(path)
    original=(await archive.load_session('old')).records[0]
    value=actor(binding)
    try:
        await value.submit(request_id='first',activity_seq=1,cutoff=0,text='first independent input')
        first=await settled(value);old_effect=first.active_grants[0]
        editor=opened(path);editor.correct_input('old',original.entry_id,'new corrected source');editor.close()
        await value.stop(activity_seq=2,cutoff=1)
        # Valid software presentation before the old epoch's fence arrives late.
        await value.receipt(receipt(old_effect));await binding.flush()
        assert binding.persistence_status=='saved'
        active=await archive.load_session('audit-current')
        assert [r.stage for r in active.records]==['accepted_input']
        current=await value.snapshot()
        assert old_effect in current.presented_effects
        raw=await archive.management_page('audit-current')
        assert any(row['stage']=='presented_effect' and not row['active'] for row in raw['entries'])
    finally:await value.close()


@pytest.mark.asyncio
async def test_capture_waits_for_own_inflight_revision_read_without_losing_accepted_input(tmp_path):
    import threading
    archive,binding=await real_binding(tmp_path/'private'/'archive.sqlite')
    packet=await binding.build_packet('historical',output_epoch=1)
    entered,release=threading.Event(),threading.Event()
    original=archive._archive.session_revision
    def delayed(name):
        entered.set();release.wait(2);return original(name)
    archive._archive.session_revision=delayed
    check=asyncio.create_task(binding.ensure_current(packet))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait,1),2)
        binding.schedule_capture(SessionState('current','client'),(item(text='current accepted capture'),))
        await asyncio.sleep(.01)
        release.set();await check;await binding.flush(wait_for_retry=True)
        assert binding.persistence_status=='saved'
        assert (await archive.load_session('current')).records[0].payload()['input']['text']=='current accepted capture'
    finally:
        release.set();await binding.aclose()


@pytest.mark.asyncio
async def test_ordinary_binding_close_flushes_accepted_capture_without_marking_it_revoked(tmp_path):
    archive=AsyncConversationArchive(tmp_path/'private'/'archive.sqlite',fixed_scope=SCOPE,
        enabled=True,authorize_transcript_persistence=True)
    await archive.open(pairing_confirmed=True)
    binding=SessionConversationBinding(archive,authorize_transcript_persistence=True,close_archive_on_actor_close=True)
    binding.schedule_capture(SessionState('current','client'),(item(text='accepted immediately before normal close'),))
    await binding.aclose()
    assert binding.persistence_status=='saved'
    reopened=opened(tmp_path/'private'/'archive.sqlite')
    try:assert reopened.load_session('current').records[0].payload()['input']['text']=='accepted immediately before normal close'
    finally:reopened.close()
