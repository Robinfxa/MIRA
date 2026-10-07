"""Reconsideration references stay in the session, outside persisted chapter schema."""
import json
import sqlite3
from dataclasses import replace
import pytest

from mira.adapters.memory.story import StoryCheckpointStore
from mira.application.story import StoryRuntime
from tests.contracts.test_native_photo_handover_flow import Flow
from tests.contracts.test_native_followthrough import declined, reconsider, RECONSIDER


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['dormant','declined'])
async def test_checkpoint_omits_transient_reference_without_changing_live_authority(tmp_path,kind):
    s=Flow()
    try:
        original=await declined(s) if kind=='declined' else None
        saved=s.c.runtime.snapshot();definition=s.c.runtime.definition
        private=tmp_path/'private';private.mkdir(mode=0o700)
        path=private/'synthetic.sqlite3'
        store=StoryCheckpointStore(path,enabled=True,explicitly_authorized=True,
            authorized_scope_id=saved.story.scope_id)
        store.save(saved.story,saved.affect)
        with sqlite3.connect(path) as db:
            version,raw=db.execute('select schema_version,story_json from story_checkpoint').fetchone()
        assert version==6
        assert 'declined_gift_offer' not in json.loads(raw)['chapter']
        assert s.c.runtime.snapshot()==saved
        before=path.read_bytes()
        loaded,affect=store.load(saved.story.scope_id,saved.story.story_id,
            graph_id=definition.graph.graph_id,graph_revision=definition.graph.revision,
            canon_revision=definition.canon.revision,graph_hash=definition.graph.content_hash,
            canon_hash=definition.canon.content_hash)
        assert path.read_bytes()==before
        assert loaded.chapter.declined_gift_offer is None
        restored=StoryRuntime.from_snapshot(definition,replace(saved,story=loaded,affect=affect))
        assert restored.story.chapter.declined_gift_offer is None
        assert restored.story.chapter.active_gift_offer_id is None
        assert not restored.story.chapter.role_active
        if original is not None:
            assert s.c.runtime.story.chapter.declined_gift_offer is not None
            result,_=await s.say(RECONSIDER,reconsider(original))
            assert result['status']=='shown'
    finally:await s.close()
