"""Known authored-canon upgrade on synthetic private stores only."""
from dataclasses import replace
import hashlib
import json
import sqlite3

import pytest

from mira.adapters.memory.story import StoryCheckpointStore, VersionMismatch
from mira.application.story import RuntimeSnapshot, StoryRuntime
from mira.bootstrap import character_story
from mira.domain.story import AffectState, EvidenceLabel, EpisodeCandidate, StoryNode, Stop

OLD_HASH = '92ac138690f5c9cc83b58037f7a9d20c857c6a2ab242d415931c7da68464812b'
SCOPE = 'synthetic-checkpoint-scope'


def synthetic_old_snapshot():
    current = character_story.builtin_definition()
    initial = StoryRuntime(current, SCOPE).snapshot()
    episode = EpisodeCandidate('episode.original', 'mira_amber_raincoat_presented',
        'receipt.original', 'compiled.original', 'a' * 64, 'component.original',
        'b' * 64, EvidenceLabel.SOFTWARE, current.graph.story_id, 1, 2,
        (('outfit_after', 'amber_raincoat'),))
    story = replace(initial.story, canon_revision=2, canon_hash=OLD_HASH,
        node=StoryNode.RAIN_VIEW, current_outfit='amber_raincoat', revision=9, epoch=3,
        last_acknowledged_outfit='amber_raincoat', last_acknowledged_emotion='happy',
        receipt_ids=('receipt.original',), episodes=(episode,),
        last_input_ids=('input.original',), released_story_events=('story.amber_raincoat',))
    return replace(initial, story=story, affect=replace(initial.affect, canon_revision=2),
        canon_revision=2, canon_hash=OLD_HASH)


def synthetic_store(tmp_path):
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    path = private / 'story.sqlite3'
    store = StoryCheckpointStore(path, enabled=True, explicitly_authorized=True, authorized_scope_id=SCOPE)
    snapshot = synthetic_old_snapshot()
    store.save(snapshot.story, snapshot.affect)
    return path, store, snapshot


def upgrade(path):
    factory = getattr(character_story, 'checkpoint_upgrade', None)
    assert callable(factory), 'explicit known-canon checkpoint upgrade is missing'
    return factory(database=path, scope_id=SCOPE, authorized=True)


def dump(path):
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        row = dict(db.execute('SELECT * FROM story_checkpoint').fetchone())
        episodes = list(db.execute('SELECT candidate_id,episode_json,created_at FROM story_qualified_episode ORDER BY rowid'))
        return row, [tuple(x) for x in episodes]


def load_current(store):
    d = character_story.builtin_definition()
    story, affect = store.load(SCOPE, d.graph.story_id, graph_id=d.graph.graph_id,
        graph_revision=d.graph.revision, canon_revision=d.canon.revision,
        graph_hash=d.graph.content_hash, canon_hash=d.canon.content_hash)
    return StoryRuntime.from_snapshot(d, RuntimeSnapshot(story, affect,
        d.graph.revision, d.canon.revision, d.graph.content_hash, d.canon.content_hash))


def test_preview_is_read_only_and_strict_default_load_stays_closed(tmp_path):
    path, store, original = synthetic_store(tmp_path)
    before = path.read_bytes()
    with pytest.raises(VersionMismatch):
        load_current(store)
    report = upgrade(path).preview()
    assert report.status == 'ready' and report.source_canon_revision == 2 and report.target_canon_revision == 3
    assert report.episodes_preserved == 1 and not report.pending_grant_canceled
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match='revision mismatch'):
        StoryRuntime.from_snapshot(character_story.builtin_definition(), original)


def test_commit_resume_resave_keeps_exact_episode_provenance_and_backup(tmp_path):
    path, store, original = synthetic_store(tmp_path)
    old_row, old_episodes = dump(path)
    workflow = upgrade(path)
    plan = workflow.preview()
    result = workflow.commit(expected_digest=plan.checkpoint_digest)
    assert result.status == 'upgraded'
    restored = load_current(store)
    assert restored.story.node is StoryNode.RAIN_VIEW and restored.story.current_outfit == 'amber_raincoat'
    assert restored.story.episodes == original.story.episodes
    assert restored.story.receipt_ids == original.story.receipt_ids
    assert restored.story.last_input_ids == original.story.last_input_ids
    assert restored.story.released_story_events == original.story.released_story_events
    assert restored.story.canon_revision == 3 and restored.story.episodes[0].canon_revision == 2
    assert dump(path)[1] == old_episodes
    with sqlite3.connect(path) as db:
        saved = db.execute("SELECT before_row_json FROM story_canon_upgrade_history WHERE action='upgrade'").fetchone()[0]
        assert json.loads(saved) == old_row
    restored.apply_story(Stop(restored.story.epoch))
    restored.save_explicitly(store)
    assert load_current(store).snapshot() == restored.snapshot()
    assert dump(path)[1] == old_episodes


def test_commit_retry_is_idempotent_and_stale_preview_rejects(tmp_path):
    path, store, old = synthetic_store(tmp_path)
    workflow = upgrade(path)
    plan = workflow.preview()
    store.save(replace(old.story, revision=old.story.revision + 1), old.affect)
    before = path.read_bytes()
    with pytest.raises(VersionMismatch):
        workflow.commit(expected_digest=plan.checkpoint_digest)
    assert path.read_bytes() == before
    plan = workflow.preview()
    workflow.commit(expected_digest=plan.checkpoint_digest)
    before = path.read_bytes()
    assert workflow.commit(expected_digest=plan.checkpoint_digest).status == 'already_upgraded'
    assert path.read_bytes() == before


def test_rollback_is_explicit_lossless_idempotent_and_refuses_later_progress(tmp_path):
    path, store, old = synthetic_store(tmp_path)
    original = dump(path)
    workflow = upgrade(path)
    workflow.commit(expected_digest=workflow.preview().checkpoint_digest)
    rollback = workflow.preview_rollback()
    assert workflow.rollback(expected_digest=rollback.checkpoint_digest).status == 'restored'
    assert dump(path) == original
    assert workflow.rollback(expected_digest=rollback.checkpoint_digest).status == 'already_restored'
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM story_canon_upgrade_history').fetchone()[0] == 2


def test_rollback_refuses_new_progress_and_keeps_backup(tmp_path):
    path, store, old = synthetic_store(tmp_path)
    workflow = upgrade(path)
    workflow.commit(expected_digest=workflow.preview().checkpoint_digest)
    rollback = workflow.preview_rollback()
    runtime = load_current(store)
    runtime.apply_story(Stop(runtime.story.epoch))
    runtime.save_explicitly(store)
    before = path.read_bytes()
    with pytest.raises(VersionMismatch):
        workflow.rollback(expected_digest=rollback.checkpoint_digest)
    assert path.read_bytes() == before


@pytest.mark.parametrize('column,value', [('canon_revision', 1), ('canon_revision', 4),
    ('canon_hash', 'c' * 64), ('graph_revision', 2), ('graph_hash', 'd' * 64),
    ('schema_version', 999), ('story_json', '{broken')])
def test_unknown_identity_or_corruption_never_changes_store(tmp_path, column, value):
    path, store, old = synthetic_store(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute(f'UPDATE story_checkpoint SET {column}=?', (value,))
    before = path.read_bytes()
    with pytest.raises((VersionMismatch, ValueError)):
        upgrade(path).preview()
    assert path.read_bytes() == before


def test_mismatched_internal_version_and_episode_archive_corruption_reject(tmp_path):
    path, store, old = synthetic_store(tmp_path)
    with sqlite3.connect(path) as db:
        row = json.loads(db.execute('SELECT story_json FROM story_checkpoint').fetchone()[0])
        row['canon_revision'] = 3
        db.execute('UPDATE story_checkpoint SET story_json=?', (json.dumps(row),))
    before = path.read_bytes()
    with pytest.raises(VersionMismatch):
        upgrade(path).preview()
    assert path.read_bytes() == before


def test_pending_grant_is_fenced_without_becoming_episode(tmp_path):
    from mira.domain.story import (PendingTransition, ReceiptKind, OfferStatus)
    path, store, old = synthetic_store(tmp_path)
    pending = PendingTransition(transition_id='t.yes', grant_id='grant.pending',
        receipt_kind=ReceiptKind.WARDROBE_COMPLETED, epoch=old.story.epoch,
        input_id='input.pending', offer_id='offer.pending', source_node=StoryNode.AWAIT_RAIN_CHOICE,
        admitted_node=StoryNode.RAINCOAT_PENDING, target_node=StoryNode.RAIN_VIEW,
        capability_id='mira.outfit.amber_raincoat', capability_revision='synthetic')
    state = replace(old.story, pending=pending, node=StoryNode.RAINCOAT_PENDING,
        revision=10, active_offer_id='offer.pending', offer_status=OfferStatus.PRESENTED)
    store.save(state, old.affect)
    workflow = upgrade(path)
    plan = workflow.preview()
    assert plan.pending_grant_canceled
    workflow.commit(expected_digest=plan.checkpoint_digest)
    current = load_current(store).story
    assert current.pending is None and current.node is StoryNode.CAFE_CHAT
    assert current.offer_status is OfferStatus.SUSPENDED
    assert current.episodes == old.story.episodes


def test_duplicate_old_receipt_and_new_receipt_keep_distinct_canon_provenance(tmp_path):
    from mira.domain.story import PresentationReceipt, ReceiptKind, ReceiptComponent, ResultCode
    path, store, old = synthetic_store(tmp_path)
    workflow = upgrade(path)
    workflow.commit(expected_digest=workflow.preview().checkpoint_digest)
    runtime = load_current(store)
    receipt = PresentationReceipt(receipt_id='receipt.original', scope_id=SCOPE,
        story_id=runtime.story.story_id, graph_revision=1, canon_revision=2,
        epoch=3, grant_id='old.grant', transition_id='t.yes',
        kind=ReceiptKind.WARDROBE_COMPLETED, evidence=EvidenceLabel.SOFTWARE,
        outcome='complete', compiled_effect_id='compiled.original', compiled_effect_digest='a'*64,
        component=ReceiptComponent.WARDROBE, component_id='component.original', component_digest='b'*64)
    before = runtime.snapshot()
    assert runtime.apply_story(receipt).code is ResultCode.DUPLICATE
    assert runtime.snapshot() == before
    runtime.save_explicitly(store)
    new = replace(old.story.episodes[0], candidate_id='episode.new', receipt_id='receipt.new',
        compiled_effect_id='compiled.new', canon_revision=3)
    runtime.story = replace(runtime.story, revision=runtime.story.revision+1,
        receipt_ids=runtime.story.receipt_ids+('receipt.new',), episodes=runtime.story.episodes+(new,))
    runtime.save_explicitly(store)
    assert [ep.canon_revision for ep in load_current(store).story.episodes] == [2, 3]
    assert len(dump(path)[1]) == 2


@pytest.mark.parametrize('corruption', ['archive_payload', 'archive_missing', 'json_bool', 'json_extra', 'json_duplicate', 'history_payload'])
def test_additional_corruption_is_never_hidden_or_repaired(tmp_path, corruption):
    path, store, old = synthetic_store(tmp_path)
    workflow = upgrade(path)
    if corruption == 'history_payload':
        workflow.commit(expected_digest=workflow.preview().checkpoint_digest)
    with sqlite3.connect(path) as db:
        if corruption == 'archive_payload':
            db.execute("UPDATE story_qualified_episode SET episode_json='{}'")
        elif corruption == 'archive_missing':
            db.execute("UPDATE story_qualified_episode SET scope_id='foreign'")
        elif corruption == 'history_payload':
            db.execute("UPDATE story_canon_upgrade_history SET after_row_json='{}'")
        else:
            raw = db.execute('SELECT story_json FROM story_checkpoint').fetchone()[0]
            if corruption == 'json_bool':
                value=json.loads(raw);value['clarification_used']='false';raw=json.dumps(value)
            elif corruption == 'json_extra':
                value=json.loads(raw);value['unrecognized_field']='private marker';raw=json.dumps(value)
            else:
                raw=raw.replace('"epoch":3', '"epoch":3,"epoch":4')
            db.execute('UPDATE story_checkpoint SET story_json=?', (raw,))
    before = path.read_bytes()
    with pytest.raises((VersionMismatch, ValueError, KeyError)):
        workflow.preview()
    assert path.read_bytes() == before


def test_cli_requires_preview_token_and_never_echoes_private_values(tmp_path, capsys):
    from tools.story_checkpoint import main
    path, store, old = synthetic_store(tmp_path)
    args=['--db',str(path),'--scope',SCOPE,'--authorize-story-checkpoint']
    before=path.read_bytes()
    assert main(['dry-run',*args]) == 0
    plan=json.loads(capsys.readouterr().out)
    assert path.read_bytes() == before
    assert main(['commit',*args]) == 2
    failed=capsys.readouterr().out
    assert str(path) not in failed and SCOPE not in failed
    assert path.read_bytes() == before
    assert main(['commit',*args,'--expected-digest',plan['checkpoint_digest']]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'upgraded'
    assert load_current(store).story.episodes == old.story.episodes


@pytest.mark.parametrize('corrupt', [False, True])
def test_pairing_reports_only_validated_known_upgrade_and_preserves_store(tmp_path, corrupt):
    from fastapi.testclient import TestClient
    from tests.contracts.test_story_persistence_composition import app_for, ORIGIN, CODE
    path, store, old = synthetic_store(tmp_path)
    # The established HTTP fixture fixes this different scope locally.
    with sqlite3.connect(path) as db:
        row=json.loads(db.execute('SELECT story_json FROM story_checkpoint').fetchone()[0])
        row['scope_id']='synthetic-scope'
        db.execute("UPDATE story_checkpoint SET scope_id='synthetic-scope',story_json=?",(json.dumps(row),))
        db.execute("UPDATE story_qualified_episode SET scope_id='synthetic-scope'")
        if corrupt:
            db.execute("UPDATE story_checkpoint SET graph_hash=?", ('e'*64,))
    before=path.read_bytes()
    with TestClient(app_for(path),base_url=ORIGIN) as client:
        denied=client.post('/api/v1/operator/pair',headers={'Origin':ORIGIN},json={'code':'wrong'})
        assert denied.status_code == 401
        response=client.post('/api/v1/operator/pair',headers={'Origin':ORIGIN},json={'code':CODE})
        if corrupt:
            assert response.status_code == 503
            assert 'story_checkpoint_canon_upgrade_required' not in response.text
        else:
            assert response.status_code == 409 and response.json()['code']=='story_checkpoint_canon_upgrade_required'
            assert 'dry-run' in response.json()['message'] and 'No checkpoint has been changed' in response.text
            assert 'Cache-Control' in response.headers
        assert str(path) not in response.text and SCOPE not in response.text
        assert 'receipt.original' not in response.text
    assert path.read_bytes() == before


@pytest.mark.parametrize('field,value', [('last_input_ids',[17]), ('receipt_ids',[True]),
    ('last_input_ids',['']), ('receipt_ids',['x'*129]), ('reentry_label','invented-history')])
def test_history_identifiers_and_labels_remain_exact_bounded_strings(tmp_path, field, value):
    path, store, old = synthetic_store(tmp_path)
    with sqlite3.connect(path) as db:
        raw=json.loads(db.execute('SELECT story_json FROM story_checkpoint').fetchone()[0])
        raw[field]=value
        db.execute('UPDATE story_checkpoint SET story_json=?',(json.dumps(raw),))
    before=path.read_bytes()
    with pytest.raises(VersionMismatch):
        upgrade(path).preview()
    assert path.read_bytes()==before


def test_upgrade_transaction_failure_retains_original_row_and_no_partial_history(tmp_path):
    path, store, old=synthetic_store(tmp_path)
    workflow=upgrade(path)
    plan=workflow.preview()
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER synthetic_failure BEFORE UPDATE ON story_checkpoint BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
    before=path.read_bytes()
    with pytest.raises(sqlite3.IntegrityError):
        workflow.commit(expected_digest=plan.checkpoint_digest)
    assert path.read_bytes()==before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='story_canon_upgrade_history'").fetchone() is None
