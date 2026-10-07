"""Independent offline acceptance of immutable 0142 source; synthetic private state only.

Owner: providers (existing tests/contracts/test_*.py quality target). Baseline audit,
not invented RED/GREEN. No provider, credential, real DB, installation, or network.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
import sqlite3
import threading
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from mira.adapters.memory.async_story import (
    AsyncStoryCheckpointStore, AsyncStoryCloseTimeout, AsyncStoryDeadlineExceeded,
    AsyncStoryStoreBusy, AsyncStoryStoreClosed,
)
from mira.adapters.memory.story import StoryCheckpointStore, ScopeMismatch, VersionMismatch
from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.actor_story import SessionCharacterRuntime
from mira.application.session_actor import SessionActor, RuntimeLimits
from mira.application.sessions import SessionRegistry
from mira.application.story import StoryRuntime
from mira.bootstrap.character_story import builtin_definition, persistent_character_factory
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.config.settings import Settings
from mira.config.loader import ConfigurationError
from mira.domain.errors import DomainError
from mira.domain.models import SessionState, EffectKind
from mira.domain.story import StoryNode, OfferStatus, EvidenceLabel
from mira.entrypoints.http.operator_pairing import OperatorPairing
from tests.contracts.test_actor_story_loop import Generation, Review, turn, acknowledge
from tests.contracts.test_direct_provider_app import arguments
from tests.contracts.test_direct_story_http import SemanticWire
from tests.contracts.test_story_persistence_composition import ready, submit
from tools import live_provider as cli

ORIGIN = 'http://127.0.0.1:8000'
CODE = 'independent-story-pairing-synthetic-00001'
SCOPE = 'independent.synthetic.scope'


def private_db(tmp_path):
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    return private / 'story.sqlite3'


def make_app(db):
    opened = []
    original = persistent_character_factory(database=db, scope_id=SCOPE,
                                            authorized=True, readiness=ready())
    async def tracked():
        binding = await original()
        opened.append(binding)
        return binding
    wire = SemanticWire()
    app = create_direct_provider_app(**arguments(generation=Generation(),
        input_transport=wire, output_transport=wire, character_binding_factory=tracked,
        operator_pairing=OperatorPairing(CODE, (ORIGIN, 'http://localhost:8000')),
        generation_request_limit=3, session_turn_limit=3,
        input_request_limit=6, output_request_limit=6))
    return app, opened


def pair_and_create(client):
    paired = client.post('/api/v1/operator/pair', headers={'Origin': ORIGIN}, json={'code': CODE})
    assert paired.status_code == 204, paired.text
    created = client.post('/api/v1/sessions', headers={'Origin': ORIGIN},
                          json={'client_instance_id': str(uuid4())})
    assert created.status_code == 201, created.text
    value = created.json()
    return '/api/v1/sessions/' + value['session']['session_id'], {
        'Origin': ORIGIN, 'X-Mira-Session-Token': value['session_token']}


def make_actor(store):
    character = SessionCharacterRuntime(StoryRuntime(builtin_definition(), SCOPE), ready(), store.save)
    actor = SessionActor(SessionState(str(uuid4()), str(uuid4())), Generation(), Review(),
                         MemoryEventJournal(100), RuntimeLimits(3, 10, 30), character_runtime=character)
    return actor, character


async def advance_to_wardrobe(actor):
    offered = await turn(actor, 'offer', 1)
    assert offered.sealed and offered.last_error is None
    await acknowledge(actor, offered.active_grants[0], 1)
    accepted = await turn(actor, 'yes', 2, 1)
    assert accepted.sealed and accepted.last_error is None
    subtitle = next(effect for effect in accepted.active_grants if effect.kind is EffectKind.SUBTITLE)
    outfit = next(effect for effect in accepted.active_grants if effect.value == 'outfit_amber_raincoat')
    await acknowledge(actor, subtitle, 2)
    return outfit


def open_store(db, **kwargs):
    return AsyncStoryCheckpointStore(db, fixed_scope=SCOPE, definition=builtin_definition(),
                                    enabled=True, explicitly_authorized=True, **kwargs)


def block_saves(store):
    loop = asyncio.get_running_loop()
    entered, finished = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    original = store._store.save
    def blocked(story, affect):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(3), 'test cleanup failed to release synthetic write'
        try:
            return original(story, affect)
        finally:
            loop.call_soon_threadsafe(finished.set)
    store._store.save = blocked
    return entered, release, finished, original


async def wait_idle(store):
    async with asyncio.timeout(2):
        while store._active is not None or store._request is not None:
            await asyncio.sleep(0)


def test_audit_cli_partial_consent_never_constructs_private_runtime(monkeypatch, capsys):
    monkeypatch.setattr(cli, '_load', lambda _: (Settings(), None))
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('check built generation'))
    monkeypatch.setattr(StoryCheckpointStore, '_check_private_path',
                        lambda *_a, **_k: pytest.fail('check touched story path'))
    base = ['check', '--provider', 'chatgpt_subscription', '--model', 'synthetic',
            '--env-file', '/never-opened.env']
    complete = ['--story', '--story-db', '/never-opened/story.sqlite3', '--story-scope', 'synthetic',
                '--authorize-story-persistence-and-recall', '--create-local-operator-pairing']
    # Each independent prerequisite is mandatory, even with the others present.
    for flag, width in [('--story', 1), ('--story-db', 2), ('--story-scope', 2),
                        ('--authorize-story-persistence-and-recall', 1),
                        ('--create-local-operator-pairing', 1)]:
        missing = complete.copy(); offset = missing.index(flag); del missing[offset:offset + width]
        assert cli.main(base + missing) == 2
        assert json.loads(capsys.readouterr().err)['status'] == 'blocked'
    assert cli.main(base + complete) == 0
    story = json.loads(capsys.readouterr().out)['character_story']
    assert story['persistent_history'] is True and story['database_opened'] is False
    assert story['pairing_file_created'] is False and story['automatic_user_recording'] is False
    assert cli.main(base + ['--story']) == 0
    assert json.loads(capsys.readouterr().out)['character_story']['persistent_history'] is False
    with pytest.raises(ConfigurationError, match='character_operator_pairing_required'):
        create_direct_provider_app(**arguments(character_binding_factory=lambda: None))


def test_audit_http_identity_boundary_and_revocation_do_not_touch_private_state(tmp_path, monkeypatch):
    db = private_db(tmp_path); touches = []
    check = StoryCheckpointStore._check_private_path
    def watched(self, **kwargs):
        touches.append(kwargs['create'])
        return check(self, **kwargs)
    monkeypatch.setattr(StoryCheckpointStore, '_check_private_path', watched)
    app, bindings = make_app(db)
    with TestClient(app, base_url=ORIGIN) as client:
        assert not bindings and not touches
        for headers in ({'Origin': ORIGIN}, {'Origin': 'http://evil.invalid'}, {}):
            assert client.post('/api/v1/sessions', headers=headers,
                               json={'client_instance_id': str(uuid4())}).status_code in (401, 403)
        assert client.post('/api/v1/operator/pair', headers={'Origin': ORIGIN},
                           json={'code': 'wrong-synthetic-code'}).status_code == 401
        assert not bindings and not touches and not db.exists()
        path, headers = pair_and_create(client)
        assert len(bindings) == 1 and touches and not any(touches) and not db.exists()
        calls = len(touches)
        for target, bad in [(path, {**headers, 'Origin': 'http://localhost:8000'}),
                            (path, {**headers, 'X-Mira-Session-Token': 'wrong'}),
                            ('/api/v1/sessions/' + str(uuid4()), headers),
                            (path, {'Origin': ORIGIN})]:
            assert client.get(target, headers=bad).status_code in (401, 404, 422)
        assert client.get(path, headers={**headers, 'Cookie': 'mira_operator_session=wrong'}).status_code == 401
        assert len(touches) == calls and not db.exists()
        binding = bindings[0]
        assert client.post('/api/v1/operator/revoke', headers={'Origin': ORIGIN}).status_code == 204
        assert binding.closed and not binding.store._thread.is_alive() and app.state.container is None
        after_close = len(touches)
        assert client.get(path, headers=headers).status_code == 401
        assert client.post('/api/v1/operator/pair', headers={'Origin': ORIGIN},
                           json={'code': CODE}).status_code == 423
        assert len(touches) == after_close and len(bindings) == 1


@pytest.mark.asyncio
async def test_audit_timeout_then_stop_then_duplicate_receipt_has_one_durable_episode(tmp_path):
    db = private_db(tmp_path)
    async def scenario():
        store = open_store(db, write_timeout_ms=50); await store.open()
        actor, character = make_actor(store)
        release = None
        try:
            outfit = await advance_to_wardrobe(actor)
            entered, release, finished, original = block_saves(store)
            pending = asyncio.create_task(acknowledge(actor, outfit, 3))
            await asyncio.wait_for(entered.wait(), 1)
            assert character.runtime.story.node is StoryNode.RAIN_VIEW
            stopped = await asyncio.wait_for(actor.stop(activity_seq=3, cutoff=3), .2)
            assert not stopped.active_grants and not pending.done()
            with pytest.raises(DomainError, match='retry the same receipt') as result:
                await pending
            assert result.value.code == 'story_checkpoint_pending'
            with pytest.raises(AsyncStoryStoreBusy):
                await store.load()
            with pytest.raises(DomainError) as retry:
                await acknowledge(actor, outfit, 3)
            assert retry.value.code == 'story_checkpoint_pending'
            release.set(); await asyncio.wait_for(finished.wait(), 1); await wait_idle(store)
            store._store.save = original
            await acknowledge(actor, outfit, 3)
            await acknowledge(actor, outfit, 3)
            archive = await store.load_episodes()
            assert len(archive) == 1 and len(character.runtime.story.episodes) == 1
            assert archive[0].compiled_effect_id == outfit.id
            assert archive[0].evidence is EvidenceLabel.CLIENT_REPORT
            assert 'not_user_fact_or_shared_experience' in archive[0].claim_boundary
            assert (await store.load()).story.node is StoryNode.RAIN_VIEW
        finally:
            if release: release.set()
            await actor.close(); await store.aclose()
        assert not store._thread.is_alive()
        with sqlite3.connect(db) as connection:
            assert connection.execute('select count(*) from story_qualified_episode').fetchone()[0] == 1
    await scenario()


@pytest.mark.asyncio
async def test_audit_cancelled_receipt_retains_capacity_and_close_drains_owned_worker(tmp_path):
    db = private_db(tmp_path)
    async def scenario():
        store = open_store(db, write_timeout_ms=1000, close_timeout_ms=50); await store.open()
        actor, character = make_actor(store)
        release = None
        try:
            outfit = await advance_to_wardrobe(actor)
            entered, release, finished, _ = block_saves(store)
            pending = asyncio.create_task(acknowledge(actor, outfit, 3))
            await asyncio.wait_for(entered.wait(), 1)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError): await pending
            with pytest.raises(AsyncStoryStoreBusy): await store.save(character.runtime.snapshot())
            await asyncio.wait_for(actor.close(), .2)
            assert actor._closed
            with pytest.raises(AsyncStoryCloseTimeout): await store.aclose()
            with pytest.raises(AsyncStoryStoreClosed): await store.load()
            release.set(); await asyncio.wait_for(finished.wait(), 1); await store.aclose()
            assert not store._thread.is_alive()
            with pytest.raises(AsyncStoryStoreClosed): await store.open()
            resumed = await persistent_character_factory(database=db, scope_id=SCOPE,
                              authorized=True, readiness=ready())()
            try:
                state = resumed.create(SessionState(str(uuid4()), str(uuid4()))).runtime.story
                assert state.node is StoryNode.RAIN_VIEW and len(state.episodes) == 1
                assert state.pending is None and state.epoch == 0
            finally: await resumed.aclose()
        finally:
            if release: release.set()
            await store.aclose()
    await scenario()


def test_audit_new_app_reentry_preserves_fiction_without_recording_user_text(tmp_path, monkeypatch):
    from mira.adapters.review import jev, jev_input
    sizes = []
    for module, attribute, label in ((jev, '_canonical', 'output'), (jev_input, 'canonical_bytes', 'input')):
        original = getattr(module, attribute)
        def watched(value, _original=original, _label=label):
            payload = _original(value)
            if type(value) is dict and 'questions' in value and 'state' in value:
                sizes.append((_label, len(payload)))
            return payload
        monkeypatch.setattr(module, attribute, watched)
    db = private_db(tmp_path)
    app, bindings = make_app(db)
    canary = '独立测试雨'
    chat_result = None
    with TestClient(app, base_url=ORIGIN) as client:
        path, headers = pair_and_create(client)
        sequence = 0
        for activity, text in enumerate(['offer', 'yes', canary], 1):
            state = submit(client, path, headers, text, activity, sequence)
            if text == canary:
                chat_result = (state['sealed'], state['last_error'], sizes[-1])
            else:
                assert state['sealed'] and state['last_error'] is None, (text, state['last_error'], sizes[-3:])
            for effect in state['active_grants']:
                sequence += 1
                response = client.post(path + '/receipts', headers=headers, json={
                    'effect_id': effect['id'], 'digest': effect['digest'],
                    'output_epoch': effect['output_epoch'], 'activity_seq': effect['activity_seq'],
                    'presentation_seq': sequence})
                assert response.status_code == 200, response.text
        assert bindings[0].current.runtime.story.node is StoryNode.RAIN_VIEW
    assert canary.encode() not in db.read_bytes()
    restored, new_bindings = make_app(db)
    with TestClient(restored, base_url=ORIGIN) as client:
        assert not new_bindings
        pair_and_create(client)
        runtime = new_bindings[0].current.runtime
        state = runtime.story
        assert state.node is StoryNode.RAIN_VIEW and state.current_outfit == 'amber_raincoat'
        assert state.pending is None and state.epoch == 0 and len(state.episodes) == 1
        assert state.reentry_label == 'qualified_character_presentation_history'
        projection = runtime.project().projection.context_json
        assert canary not in projection and 'not_user_fact_or_shared_experience' in projection
        assert state.episodes[0].evidence is EvidenceLabel.CLIENT_REPORT
    assert all(binding.closed and not binding.store._thread.is_alive() for binding in bindings + new_bindings)
    assert chat_result is not None and chat_result[:2] == (True, None), chat_result


@pytest.mark.asyncio
async def test_audit_restart_discards_unseen_offer_even_if_snapshot_was_persisted(tmp_path):
    db = private_db(tmp_path)
    async def scenario():
        first = await persistent_character_factory(database=db, scope_id=SCOPE,
                            authorized=True, readiness=ready())()
        assert not db.exists()
        runtime = first.create(SessionState(str(uuid4()), str(uuid4())))
        actor = SessionActor(SessionState(str(uuid4()), str(uuid4())), Generation(), Review(),
            MemoryEventJournal(100), RuntimeLimits(3, 5, 20), character_runtime=runtime)
        state = await turn(actor, 'offer', 1)
        assert state.sealed and runtime.runtime.story.pending
        await first.store.save(runtime.runtime.snapshot())
        # Simulate process loss: do not ask Actor.close to pre-sanitize the saved pending grant.
        await first.aclose()
        second = await persistent_character_factory(database=db, scope_id=SCOPE,
                             authorized=True, readiness=ready())()
        try:
            resumed = second.create(SessionState(str(uuid4()), str(uuid4()))).runtime.story
            assert resumed.node is StoryNode.CAFE_CHAT and resumed.pending is None
            assert resumed.active_offer_id is None and resumed.offer_status is OfferStatus.SUSPENDED
            assert not resumed.receipt_ids and not resumed.episodes
        finally:
            await second.aclose(); await actor.close()
    await scenario()


@pytest.mark.asyncio
async def test_audit_restart_discards_pending_wardrobe_but_keeps_prior_offer_receipt(tmp_path):
    db = private_db(tmp_path)
    async def scenario():
        store = open_store(db); await store.open()
        actor, character = make_actor(store)
        outfit = await advance_to_wardrobe(actor)
        before = await store.load()
        assert before.story.pending and before.story.pending.compiled_effect_id == outfit.id
        accepted_receipts = before.story.receipt_ids
        assert accepted_receipts and before.story.current_outfit == 'black_jacket'
        await store.aclose()
        binding = await persistent_character_factory(database=db, scope_id=SCOPE,
                            authorized=True, readiness=ready())()
        try:
            resumed = binding.create(SessionState(str(uuid4()), str(uuid4()))).runtime.story
            assert resumed.pending is None and resumed.current_outfit == 'black_jacket'
            assert resumed.node is StoryNode.CAFE_CHAT and resumed.active_offer_id is None
            assert resumed.receipt_ids == accepted_receipts and not resumed.episodes
            assert await binding.store.load_episodes() == ()
        finally:
            await binding.aclose(); await actor.close()
    await scenario()


@pytest.mark.asyncio
async def test_audit_scope_and_hash_drift_fail_without_overwriting_checkpoint(tmp_path):
    db = private_db(tmp_path)
    async def scenario():
        store = open_store(db); await store.open()
        initial = StoryRuntime(builtin_definition(), SCOPE).snapshot()
        await store.save(initial)
        digest = hashlib.sha256(db.read_bytes()).hexdigest()
        with pytest.raises(ScopeMismatch):
            await store.save(replace(initial, story=replace(initial.story, scope_id='attacker-selected')))
        for field in ('graph_hash', 'canon_hash'):
            altered = replace(initial, **{field: 'f' * 64})
            with pytest.raises(ValueError): await store.save(altered)
        with pytest.raises(ScopeMismatch): await store.load('attacker-selected-story')
        assert hashlib.sha256(db.read_bytes()).hexdigest() == digest
        await store.aclose()
        # Alter metadata in our synthetic DB; matching numerical revisions alone must not authorize recall.
        with sqlite3.connect(db) as connection:
            connection.execute("update story_checkpoint set canon_hash=?", ('e' * 64,))
        changed = hashlib.sha256(db.read_bytes()).hexdigest()
        with pytest.raises(VersionMismatch):
            await persistent_character_factory(database=db, scope_id=SCOPE, authorized=True)()
        assert hashlib.sha256(db.read_bytes()).hexdigest() == changed
    await scenario()


@pytest.mark.asyncio
async def test_audit_session_replacement_waits_for_close_and_has_isolated_actor_epoch(tmp_path):
    db = private_db(tmp_path)
    async def scenario():
        binding = await persistent_character_factory(database=db, scope_id=SCOPE,
                            authorized=True, readiness=ready())()
        journal = MemoryEventJournal(100)
        def factory(state):
            return SessionActor(state, Generation(), Review(), journal, RuntimeLimits(3, 5, 20),
                                character_runtime=binding.create(state))
        registry = SessionRegistry(factory, journal, 1)
        actor, token = registry.create(str(uuid4()))
        offered = await turn(actor, 'offer', 1); await acknowledge(actor, offered.active_grants[0], 1)
        entered, release, finished, original = block_saves(binding.store)
        try:
            closing = asyncio.create_task(registry.delete(actor._state.session_id, token))
            await asyncio.wait_for(entered.wait(), 1)
            with pytest.raises(DomainError) as error: registry.create(str(uuid4()))
            assert error.value.code == 'session_capacity'
            release.set(); await closing; await wait_idle(binding.store)
            binding.store._store.save = original
            replacement, new_token = registry.create(str(uuid4()))
            assert replacement is not actor and new_token != token
            story = replacement._character_runtime.runtime.story
            assert story.node is StoryNode.AWAIT_RAIN_CHOICE and story.pending is None
            assert story.epoch == 0 and len(story.receipt_ids) == 1
            with pytest.raises(DomainError): registry.get(actor._state.session_id, token)
        finally:
            release.set(); await registry.close(); await binding.aclose()
        assert binding.closed and not binding.store._thread.is_alive()
    await scenario()


@pytest.mark.asyncio
async def test_audit_revocation_fences_already_authenticated_request_before_lazy_open(tmp_path):
    """A delayed authenticated request must not reopen a runtime after successful revoke."""
    db = private_db(tmp_path)
    async def scenario():
        app, bindings = make_app(db)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                response = await client.post('/api/v1/operator/pair', headers={'Origin': ORIGIN}, json={'code': CODE})
                assert response.status_code == 204
                original = app.state.ensure_runtime
                entered, release = asyncio.Event(), asyncio.Event()
                async def held():
                    entered.set(); await release.wait(); await original()
                app.state.ensure_runtime = held
                pending = asyncio.create_task(client.post('/api/v1/sessions', headers={'Origin': ORIGIN},
                                 json={'client_instance_id': str(uuid4())}))
                await asyncio.wait_for(entered.wait(), 1)
                revoked = await client.post('/api/v1/operator/revoke', headers={'Origin': ORIGIN})
                assert revoked.status_code == 204 and app.state.container is None
                assert len(bindings) == 1 and bindings[0].closed
                release.set()
                delayed = await asyncio.wait_for(pending, 2)
                assert delayed.status_code in (401, 403, 503), {
                    'status': delayed.status_code, 'private_bindings_opened': len(bindings),
                    'runtime_reopened': app.state.container is not None,
                    'operator_revoked': app.state.operator_pairing.status()['revoked']} 
                assert app.state.container is None and len(bindings) == 1
    await scenario()
