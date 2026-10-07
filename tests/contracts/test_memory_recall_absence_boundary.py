"""Two-turn synthetic failure and actual shared JEV serializer boundaries."""
import json
from dataclasses import replace

import pytest

from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.actor_conversation import SessionConversationBinding
from mira.application.actor_memory import SessionMemoryBinding
from mira.application.contracts import generation_context_data
from mira.application.conversation_archive import ConversationSnapshot
from mira.application.decision_contracts import ReliableUserInput, decision_snapshot_data, mira26_author_policy
from mira.application.decision_runtime import DecisionSnapshotOwner
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.domain import transitions
from mira.domain.memory import MemoryScope
from mira.domain.models import Phase, Receipt, SessionState
from tests.contracts.test_actor_memory_recall import valid_past_line
from tests.contracts.test_bounded_conversation_context import Generation, Review, idle
from tests.contracts.test_personal_memory_projection import archive, context, empty_manual, input_record


@pytest.mark.parametrize('kind', ['manual', 'archive'])
def test_unavailable_omits_leftover_record_from_jev_shared_wire(kind):
    marker = 'SYNTHETIC_STALE_JEV_RECALL'
    fields = ({'memory_packet': replace(empty_manual(), past_candidates=(valid_past_line(marker),)),
               'memory_recall_status': 'unavailable'} if kind == 'manual' else
              {'conversation_recall': archive((input_record(marker),)),
               'conversation_recall_status': 'unavailable'})
    value = context(**fields)
    state = transitions.begin_input(SessionState('synthetic', 'client'), request_id='now',
        activity_seq=1, cutoff=0, text=value.user_text)
    snapshot = DecisionSnapshotOwner(mira26_author_policy()).snapshot(state,
        (ReliableUserInput('now', value.user_text),), character_story=value.character_story, **fields)
    assert marker not in json.dumps(decision_snapshot_data(snapshot)), 'Unavailable record still serialized for JEV'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['manual', 'archive'])
async def test_success_then_operational_failure_clears_previous_packet_and_chat_continues(kind):
    marker = 'SYNTHETIC_PREVIOUS_SUCCESS_ONLY'
    class Reader:
        calls = 0
        async def build_packet(self, **kwargs):
            self.calls += 1
            if self.calls > 1:
                raise OSError('synthetic read absence')
            return replace(empty_manual(), request_text=kwargs['request_text'],
                timeout_ms=kwargs['timeout_ms'], max_packet_bytes=kwargs['max_packet_bytes'],
                past_candidates=(valid_past_line(marker),))
        async def scope_revision(self, _scope): return 2
        async def aclose(self): pass
    class Archive:
        calls = 0
        async def capture(self, *_args): pass
        async def load_session(self, session):
            self.calls += 1
            if self.calls > 1:
                raise OSError('synthetic read absence')
            return ConversationSnapshot(session, 3, (input_record(marker),))
        async def session_revision(self, _session): return 3
        async def aclose(self): pass
    options = ({'memory_binding': SessionMemoryBinding(Reader(), MemoryScope('user', 'mira', 'world'))}
        if kind == 'manual' else {'conversation_binding': SessionConversationBinding(Archive(),
            authorize_transcript_persistence=True, recall_session_id='old',
            authorize_recall_to_provider_and_jev=True)})
    generation = Generation()
    actor = SessionActor(SessionState('synthetic-current', 'client'), generation, Review(),
        MemoryEventJournal(50), RuntimeLimits(3, 100, 1000), **options)
    try:
        for turn in (1, 2):
            await actor.submit(request_id=f'r{turn}', activity_seq=turn, cutoff=turn-1, text=f'synthetic turn {turn}')
            state = await idle(actor)
            assert state.phase is Phase.READY
            effect, = state.active_grants
            await actor.receipt(Receipt(effect.id, effect.digest, effect.output_epoch, effect.activity_seq, turn))
        assert len(generation.contexts) == 2
        assert marker in generation.prompts[0]
        assert marker not in generation.prompts[1]
        data = generation_context_data(generation.contexts[1])
        field = 'memory_evidence' if kind == 'manual' else 'conversation_recall'
        status = 'memory_recall_status' if kind == 'manual' else 'conversation_recall_status'
        assert field not in data
        assert data[status] == 'unavailable'
    finally:
        await actor.close()
