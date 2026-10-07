"""Legacy schema-5 SQLite fixtures, with no real stores or account access."""
from dataclasses import replace
import json
import sqlite3
import pytest

from mira.adapters.memory.story import VersionMismatch
from mira.domain.story import Stop
from tests.contracts.test_story_canon_upgrade import synthetic_store,upgrade,dump,load_current


def legacy_schema5_store(tmp_path):
    path,store,snapshot=synthetic_store(tmp_path)
    with sqlite3.connect(path) as db:
        payload=json.loads(db.execute('select story_json from story_checkpoint').fetchone()[0])
        payload.pop('chapter')
        db.execute('update story_checkpoint set schema_version=5,story_json=?',
            (json.dumps(payload,sort_keys=True,separators=(',',':')),))
    return path,store,snapshot


def test_documented_schema5_canon2_preview_commit_keeps_schema_until_new_save(tmp_path):
    path,store,snapshot=legacy_schema5_store(tmp_path)
    before=dump(path);before_bytes=path.read_bytes()
    with pytest.raises(VersionMismatch):load_current(store)
    flow=upgrade(path);plan=flow.preview()
    assert plan.status=='ready' and plan.episodes_preserved==1
    assert path.read_bytes()==before_bytes
    assert flow.commit(expected_digest=plan.checkpoint_digest).status=='upgraded'
    after=dump(path)
    assert after[0]['schema_version']==5 and after[0]['canon_revision']==3
    assert 'chapter' not in json.loads(after[0]['story_json'])
    assert after[1]==before[1]
    with sqlite3.connect(path) as db:
        saved=db.execute("select before_row_json from story_canon_upgrade_history where action='upgrade'").fetchone()[0]
        assert json.loads(saved)==before[0]
    assert flow.commit(expected_digest=plan.checkpoint_digest).status=='already_upgraded'
    runtime=load_current(store)
    assert runtime.story.episodes==snapshot.story.episodes
    assert runtime.story.chapter.compatibility=='legacy_story_schema_5'
    bytes_after=path.read_bytes();runtime.save_explicitly(store)
    assert path.read_bytes()==bytes_after
    assert dump(path)[0]['schema_version']==5
    runtime.apply_story(Stop(runtime.story.epoch));runtime.save_explicitly(store)
    assert dump(path)[0]['schema_version']==6
    assert dump(path)[1]==before[1]
    with pytest.raises(VersionMismatch):flow.preview_rollback()


def test_schema5_rollback_and_old_completed_upgrade_history_are_lossless(tmp_path):
    path,store,_=legacy_schema5_store(tmp_path)
    before=dump(path);flow=upgrade(path)
    plan=flow.preview();flow.commit(expected_digest=plan.checkpoint_digest)
    after=dump(path)
    # A schema-5 completed upgrade must still be recognized by the new runtime.
    assert flow.preview().status=='already_upgraded'
    rollback=flow.preview_rollback();assert rollback.status=='rollback_ready'
    assert flow.rollback(expected_digest=rollback.checkpoint_digest).status=='restored'
    assert dump(path)==before
    assert flow.rollback(expected_digest=rollback.checkpoint_digest).status=='already_restored'
    with sqlite3.connect(path) as db:
        history=list(db.execute('select before_row_json,after_row_json from story_canon_upgrade_history order by rowid'))
    assert json.loads(history[0][1])==after[0]
    assert json.loads(history[1][1])==before[0]


@pytest.mark.parametrize('schema',[3,4,7,99])
def test_explicit_canon_upgrade_does_not_expand_to_undocumented_or_unknown_schemas(tmp_path,schema):
    path,_,_=legacy_schema5_store(tmp_path)
    with sqlite3.connect(path) as db:db.execute('update story_checkpoint set schema_version=?',(schema,))
    before=path.read_bytes()
    with pytest.raises(VersionMismatch):upgrade(path).preview()
    assert path.read_bytes()==before


@pytest.mark.parametrize('mutation',['extra_field','duplicate_key','missing_field','wrong_scalar','chapter_in_legacy','archive_missing'])
def test_schema5_corruption_still_refuses_without_writing(tmp_path,mutation):
    path,_,_=legacy_schema5_store(tmp_path)
    with sqlite3.connect(path) as db:
        raw=db.execute('select story_json from story_checkpoint').fetchone()[0]
        value=json.loads(raw)
        if mutation=='extra_field':value['unknown']=1
        elif mutation=='missing_field':value.pop('last_acknowledged_outfit')
        elif mutation=='wrong_scalar':value['revision']=str(value['revision'])
        elif mutation=='chapter_in_legacy':value['chapter']={}
        elif mutation=='archive_missing':db.execute('delete from story_qualified_episode')
        raw=json.dumps(value,sort_keys=True,separators=(',',':'))
        if mutation=='duplicate_key':raw=raw[:-1]+',"revision":9}'
        db.execute('update story_checkpoint set story_json=?',(raw,))
    before=path.read_bytes()
    with pytest.raises(VersionMismatch):upgrade(path).preview()
    assert path.read_bytes()==before


@pytest.mark.parametrize('corrupt',[False,True])
def test_actual_pairing_routes_only_valid_schema5_to_explicit_upgrade(tmp_path,corrupt):
    from fastapi.testclient import TestClient
    from tests.contracts.test_story_persistence_composition import app_for,ORIGIN,CODE
    path,_,_=legacy_schema5_store(tmp_path)
    with sqlite3.connect(path) as db:
        payload=json.loads(db.execute('select story_json from story_checkpoint').fetchone()[0])
        payload['scope_id']='synthetic-scope'
        db.execute("update story_checkpoint set scope_id='synthetic-scope',story_json=?",(json.dumps(payload),))
        db.execute("update story_qualified_episode set scope_id='synthetic-scope'")
        if corrupt:db.execute('update story_checkpoint set graph_hash=?',('e'*64,))
    before=path.read_bytes()
    with TestClient(app_for(path),base_url=ORIGIN) as client:
        response=client.post('/api/v1/operator/pair',headers={'Origin':ORIGIN},json={'code':CODE})
        if corrupt:
            assert response.status_code==503
            assert 'story_checkpoint_canon_upgrade_required' not in response.text
        else:
            assert response.status_code==409
            assert response.json()['code']=='story_checkpoint_canon_upgrade_required'
        assert str(path) not in response.text and 'receipt.original' not in response.text
    assert path.read_bytes()==before
