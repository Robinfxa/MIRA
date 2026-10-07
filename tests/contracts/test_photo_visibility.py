"""Authored photo dismissal is an application fact, never rewritten exposure history."""
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.application.contracts import generation_context_data
from mira.domain.errors import DomainError
from mira.domain.models import EffectKind
from mira.entrypoints.http.app import create_app
from tests.contracts.test_authored_photo_events import actor, receipt, turn
from tests.integration.test_rehearsal_http import settings, wait


@pytest.mark.asyncio
@pytest.mark.parametrize('recall_kind', ['manual', 'archive'])
async def test_photo_close_during_recall_refreshes_current_facts_before_model_dispatch(tmp_path, recall_kind):
    import asyncio
    from mira.adapters.journal.memory import MemoryEventJournal
    from mira.application.actor_memory import SessionMemoryBinding
    from mira.application.actor_conversation import SessionConversationBinding
    from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
    from mira.application.session_actor import SessionActor, RuntimeLimits
    from mira.bootstrap.character_assets import renderer_readiness
    from mira.bootstrap.development_review import create_development_review_providers
    from mira.domain.models import SessionState
    from tests.contracts.test_actor_memory_recall import AsyncReader, SCOPE, finish
    from tests.contracts.test_actor_conversation_archive import archive
    from tests.contracts.test_conversation_archive import opened, accepted
    from tests.contracts.test_conversation_first import Generation, Wire

    entered, release = asyncio.Event(), asyncio.Event()
    manual = conversation = store = None
    if recall_kind == 'manual':
        reader = AsyncReader(blocked_text='second')
        entered, release = reader.entered, reader.release
        manual = SessionMemoryBinding(reader, SCOPE, timeout_ms=1000)
    else:
        seed = opened(tmp_path)
        seed.append_input('past', accepted(text='Synthetic historical statement.'))
        seed.close()
        store = await archive(tmp_path / 'private' / 'conversation.sqlite')
        conversation = SessionConversationBinding(store, authorize_transcript_persistence=True,
            recall_session_id='past', authorize_recall_to_provider_and_jev=True,
            close_archive_on_actor_close=True)

    generation = Generation([('subtitle', 'Synthetic reply.'), ('media', 'trip_photo')])
    wire = Wire()
    providers = create_development_review_providers(generation=generation, input_transport=wire,
        output_transport=wire, authorized=True, decision_policy=USER_DEVELOPMENT_0_6_V2,
        conversation_first=True, input_request_limit=4, output_request_limit=4)
    value = SessionActor(SessionState('photo-memory', 'client'), generation, providers.review,
        MemoryEventJournal(64), RuntimeLimits(5, 4, 64), semantic_review=providers.semantic_review,
        decision_owner=providers.decision_owner, memory_binding=manual,
        conversation_binding=conversation, visual_readiness=renderer_readiness('code-native-review'))
    try:
        await value.submit(request_id='first', activity_seq=1, cutoff=0, text='first')
        shown = await finish(value)
        for sequence, effect in enumerate(shown.active_grants, 1):
            await value.receipt(receipt(effect, sequence))
        before = await value.snapshot()
        assert before.photo_visible
        if store is not None:
            original = store.load_session
            async def delayed(session_id):
                result = await original(session_id)
                if session_id == 'past':
                    entered.set()
                    await release.wait()
                return result
            store.load_session = delayed
        await value.submit(request_id='second', activity_seq=2,
            cutoff=len(shown.active_grants), text='second')
        await asyncio.wait_for(entered.wait(), 1)
        closed = await value.dismiss_photo(request_id='close-during-recall',
            expected_revision=before.photo_visibility_revision, cutoff=len(shown.active_grants))
        assert closed.presented_effects == before.presented_effects
        release.set()
        state = await finish(value)
        context = generation.contexts[-1]
        assert context.photo_visible is False
        assert context.photo_visibility_revision == state.photo_visibility_revision == 1
        facts = generation_context_data(context)['authored_visual_events']['trip_photo']
        assert facts['presented'] is True and facts['visible'] is False
        assert all(effect.kind is not EffectKind.MEDIA for effect in state.active_grants)
    finally:
        release.set()
        await value.close()


@pytest.mark.asyncio
async def test_close_preserves_history_and_new_review_sees_hidden_before_reshow():
    value, generation, wire = actor([('media', 'trip_photo')])
    try:
        shown = await turn(value, 1)
        for n, effect in enumerate(shown.active_grants, 1):
            await value.receipt(receipt(effect, n))
        before = await value.snapshot()
        closed = await value.dismiss_photo(request_id='close-1', expected_revision=0, cutoff=2)
        assert closed.photo_visible is False
        assert closed.photo_visibility_revision == 1
        assert closed.presented_effects == before.presented_effects
        assert closed.receipts == before.receipts
        assert closed.output_epoch == before.output_epoch
        assert closed.activity_seq == before.activity_seq
        assert [e for e in closed.active_grants if e.kind != EffectKind.MEDIA] == [
            e for e in before.active_grants if e.kind != EffectKind.MEDIA]
        assert await value.dismiss_photo(request_id='close-1', expected_revision=0, cutoff=2) is closed
        with pytest.raises(DomainError):
            await value.dismiss_photo(request_id='close-1', expected_revision=1, cutoff=2)
        with pytest.raises(DomainError):
            await value.dismiss_photo(request_id='wrong-revision', expected_revision=0, cutoff=2)
        again = await turn(value, 2, 2)
        facts = generation_context_data(generation.contexts[-1])['authored_visual_events']['trip_photo']
        assert facts['presented'] is True and facts['visible'] is False
        reviewed = [body for body, *_ in wire.calls if 'contract' in body['state']][-1]
        assert reviewed['state']['context']['authored_visual_events']['trip_photo'] == facts
        photo = next(e for e in again.active_grants if e.kind is EffectKind.MEDIA)
        for n, effect in enumerate(again.active_grants, 3):
            await value.receipt(receipt(effect, n))
        reshown = await value.snapshot()
        assert reshown.photo_visible is True
        assert len([e for e in reshown.presented_effects if e.kind is EffectKind.MEDIA]) == 2
        # An exact retry of the old UI request cannot close the new display.
        assert await value.dismiss_photo(request_id='close-1', expected_revision=0, cutoff=2) is reshown
        assert (await value.snapshot()).photo_visible is True
        assert photo in reshown.presented_effects
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_pending_photo_close_rejects_late_receipt_and_stop_preserves_dismissal():
    value, generation, _ = actor([('media', 'trip_photo')])
    try:
        state = await turn(value, 1)
        photo = next(e for e in state.active_grants if e.kind is EffectKind.MEDIA)
        closed = await value.dismiss_photo(request_id='close-pending', expected_revision=0, cutoff=0)
        assert closed.presented_effects == () and closed.photo_visible is False
        with pytest.raises(DomainError, match='dismiss'):
            await value.receipt(receipt(photo, 1))
        stopped = await value.stop(activity_seq=2, cutoff=0)
        assert stopped.photo_visible is False
        again = await turn(value, 3)
        assert any(e.kind is EffectKind.MEDIA for e in again.active_grants)
        assert generation_context_data(generation.contexts[-1])['authored_visual_events']['trip_photo']['presented'] is False
    finally:
        await value.close()


def test_asgi_show_close_reshow_authentication_revision_and_speech_grants():
    with TestClient(create_app(settings())) as client:
        created = client.post('/api/v1/sessions', json={'client_instance_id': str(uuid4())}).json()
        path = '/api/v1/sessions/' + created['session']['session_id']
        headers = {'X-Mira-Session-Token': created['session_token']}
        def submit(activity, cutoff):
            response = client.post(path + '/inputs', headers=headers, json={
                'request_id': str(uuid4()), 'activity_seq': activity,
                'presentation_cutoff': cutoff, 'text': '看照片'})
            assert response.status_code == 202
            return wait(client, path, headers)
        def acknowledge(photo, seq):
            return client.post(path + '/receipts', headers=headers, json={
                'effect_id': photo['id'], 'presentation_seq': seq,
                **{key: photo[key] for key in ('digest', 'output_epoch', 'activity_seq')}})
        first = submit(1, 0)
        photo = next(e for e in first['active_grants'] if e['kind'] == 'media')
        shown = acknowledge(photo, 1).json()
        assert shown['photo_visible'] is True
        body = {'request_id': str(uuid4()), 'expected_revision': 0, 'presentation_cutoff': 1}
        route = path + '/photo-dismissals'
        assert client.post(route, json=body, headers={'X-Mira-Session-Token': 'wrong'}).status_code == 404
        other = client.post('/api/v1/sessions', json={'client_instance_id': str(uuid4())}).json()
        assert client.post('/api/v1/sessions/' + other['session']['session_id'] + '/photo-dismissals',
            json=body, headers=headers).status_code == 404
        assert client.post(route, json={**body, 'expected_revision': 3}, headers=headers).status_code == 409
        assert client.post(route, json={**body, 'value': 'https://example.com'}, headers=headers).status_code == 422
        closed = client.post(route, json=body, headers=headers)
        assert closed.status_code == 200
        closed = closed.json()
        assert closed['photo_visible'] is False and closed['photo_visibility_revision'] == 1
        assert closed['presented_effects'] == shown['presented_effects']
        assert [e for e in closed['active_grants'] if e['kind'] != 'media'] == [
            e for e in shown['active_grants'] if e['kind'] != 'media']
        assert client.post(route, json=body, headers=headers).json() == closed
        assert acknowledge(photo, 1).json()['photo_visible'] is False
        # Existing speech still streams through its original capability after dismissal.
        speech = next(e for e in closed['active_grants'] if e['kind'] == 'speech')
        response = client.post(path + '/speech/' + speech['id'] + '/stream', headers=headers,
            json={key: speech[key] for key in ('digest', 'output_epoch', 'activity_seq')})
        assert response.status_code == 200
        again = submit(2, 1)
        new_photo = next(e for e in again['active_grants'] if e['kind'] == 'media')
        reshown = acknowledge(new_photo, 2).json()
        assert reshown['photo_visible'] is True
        assert len([e for e in reshown['presented_effects'] if e['kind'] == 'media']) == 2
        assert client.post(route, json=body, headers=headers).json()['photo_visible'] is True


@pytest.mark.asyncio
async def test_dismissal_during_event_review_holds_stale_grant_but_keeps_text():
    import asyncio
    from tests.contracts.test_development_review_composition import finish
    value, _, wire = actor([('media', 'trip_photo')])
    wire.output_gate = True
    try:
        await value.submit(request_id='input', activity_seq=1, cutoff=0, text='看照片')
        await asyncio.wait_for(wire.entered.wait(), 1)
        before = await value.snapshot()
        assert [e.kind for e in before.active_grants] == [EffectKind.SUBTITLE]
        await value.dismiss_photo(request_id='close-during-review', expected_revision=0, cutoff=0)
        wire.release.set()
        state = await finish(value)
        assert state.sealed and [e.kind for e in state.active_grants] == [EffectKind.SUBTITLE]
        assert state.output_epoch == 1 and state.request_id == 'input'
        assert state.photo_visible is False and state.presented_effects == ()
    finally:
        wire.release.set()
        await value.close()


@pytest.mark.asyncio
async def test_rehearsal_exposure_does_not_claim_closed_photo_is_still_here():
    from mira.application.contracts import GenerationContext
    from tests.contracts.test_rehearsal_generation import selected, photo
    providers = selected()
    context = GenerationContext('照片里有什么', ('照片里有什么',), (photo(),), 2,
        photo_visible=False, photo_visibility_revision=1)
    rows = [row async for row in providers.generation.generate(context)]
    assert rows[0].fixture_id == 'rehearsal:closed'
    assert '已收起' in rows[0].effects[0].value
    assert not any(effect.kind is EffectKind.SPEECH for effect in rows[0].effects)


def test_asgi_dismissal_does_not_cancel_microphone_or_listening_lease(monkeypatch):
    app = create_app(settings())
    with TestClient(app) as client:
        container = app.state.container
        calls = []
        monkeypatch.setattr(container.listening_leases, 'stop_session', lambda *a, **k: calls.append('stop'))
        monkeypatch.setattr(container.reviewed_audio, 'cancel_session', lambda *a, **k: calls.append('cancel'))
        created = client.post('/api/v1/sessions', json={'client_instance_id': str(uuid4())}).json()
        path = '/api/v1/sessions/' + created['session']['session_id']
        headers = {'X-Mira-Session-Token': created['session_token']}
        result = client.post(path + '/photo-dismissals', headers=headers, json={
            'request_id': str(uuid4()), 'expected_revision': 0, 'presentation_cutoff': 0})
        assert result.status_code == 200
        assert result.json()['activity_seq'] == 0 and result.json()['output_epoch'] == 0
        assert calls == []


@pytest.mark.asyncio
async def test_dismissal_during_generation_drops_same_turn_photo_but_finishes_chat():
    import asyncio
    from mira.application.contracts import CandidateRange, EffectProposal
    from tests.contracts.test_development_review_composition import finish
    value, generation, wire = actor([('media', 'trip_photo')])
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(context):
        generation.contexts.append(context)
        entered.set()
        await release.wait()
        yield CandidateRange((EffectProposal(EffectKind.SUBTITLE, 'Still chatting.'),
            EffectProposal(EffectKind.MEDIA, 'trip_photo')), 'synthetic-late-photo')
    generation.generate = delayed
    try:
        await value.submit(request_id='input', activity_seq=1, cutoff=0, text='看照片')
        await asyncio.wait_for(entered.wait(), 1)
        await value.dismiss_photo(request_id='close-during-generation', expected_revision=0, cutoff=0)
        release.set()
        state = await finish(value)
        assert state.sealed and [e.kind for e in state.active_grants] == [EffectKind.SUBTITLE]
        assert state.request_id == 'input' and state.photo_visible is False
        assert wire.calls == []
    finally:
        release.set()
        await value.close()
