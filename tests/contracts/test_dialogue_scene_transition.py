"""One acceptance -> actual SCENE grant -> exact receipt; synthetic Actor ports."""
import json
from dataclasses import replace

import pytest

from tests.contracts.test_actor_story_loop import setup, turn, acknowledge, _run
from mira.application.contracts import CandidateRange, EffectProposal
from mira.adapters.generation.codex_support.character_payload import offered_id
from mira.domain.models import EffectKind
from mira.domain.story import CapabilityRecord, CapabilityState, ReadinessCatalog, StoryNode, OfferStatus


class WindowGeneration:
    def __init__(self): self.contexts = []
    async def generate(self, context):
        self.contexts.append(context)
        effects = []
        if context.user_text == 'offer':
            text = '想把视角换到窗边，一起看一会儿雨吗？也可以继续坐在这里聊。'
            proposal = {'transition_id':'t.offer', 'signal':'offer_rain', 'offer_id':offered_id(context), 'draft_cue':text, 'target_capabilities':['cafe.scene.rain_window']}
        elif context.user_text in ('yes', 'force-window'):
            text = '好，我们看看窗边的雨。'
            proposal = {'transition_id':'t.window', 'signal':'look_at_rain',
                'offer_id':context.character_story.active_offer_id or 'absent',
                'target_capabilities':['cafe.scene.rain_window']}
            effects.append(EffectProposal(EffectKind.SCENE, 'rain_window'))
        else:
            text = '我们继续聊你刚才说的事。'
            proposal = {'transition_id':'t.chat','signal':'chat'}
        yield CandidateRange((EffectProposal(EffectKind.SUBTITLE,text), *effects), 'synthetic-window',
            story_proposal_json=json.dumps(proposal,ensure_ascii=False))


def window_setup(*, ready=True, uncertain=False):
    actor, character, _, review = setup(uncertain=uncertain)
    generation = WindowGeneration()
    actor._generation = generation
    character.readiness = ReadinessCatalog('window-test', (CapabilityRecord('cafe.scene.rain_window',
        CapabilityState.READY if ready else CapabilityState.UNAVAILABLE,
        'window-v1' if ready else None, ('scene.rain_window.composition',) if ready else (),
        'synthetic-proof' if ready else None),))
    return actor, character, generation, review


async def offered(actor):
    state = await turn(actor, 'offer', 1)
    await acknowledge(actor, state.active_grants[0], 1)


def test_one_yes_grants_window_without_wardrobe_or_second_turn_and_receipt_drives_shared_context():
    async def run():
        actor, character, generation, review = window_setup()
        try:
            await offered(actor)
            state = await turn(actor, 'yes', 2, 1)
            assert state.sealed, state.last_error
            scene = next(e for e in state.active_grants if e.kind is EffectKind.SCENE)
            assert scene.value == 'rain_window'
            assert not any(e.value.startswith('outfit_') for e in state.active_grants)
            assert character.runtime.story.node is StoryNode.AWAIT_RAIN_CHOICE
            assert character.runtime.story.pending.transition_id == 't.window'
            assert not character.runtime.story.episodes
            subtitle = next(e for e in state.active_grants if e.kind is EffectKind.SUBTITLE)
            await acknowledge(actor, subtitle, 2)
            await acknowledge(actor, scene, 3)
            assert character.runtime.story.node is StoryNode.RAIN_VIEW
            assert character.runtime.story.current_outfit == 'black_jacket'
            assert len(character.runtime.story.episodes) == 1
            assert character.runtime.story.episodes[0].event_code == 'cafe_rain_window_presented'
            await acknowledge(actor, scene, 3)
            assert len(character.runtime.story.episodes) == 1
            await turn(actor, 'chat', 3, 3)
            assert generation.contexts[-1].character_story == review.contexts[-1].character_story
            projection = json.loads(generation.contexts[-1].character_story.context_json)
            assert projection['last_acknowledged_scene'] == 'rain_window'
            assert projection['scene_scope'] == 'historical_software_presentation_not_current_browser_restoration'
        finally: await actor.close()
    _run(run())


@pytest.mark.parametrize('reply', ['no', 'unrelated'])
def test_decline_and_offtopic_never_change_scene(reply):
    async def run():
        actor, character, _, _ = window_setup()
        try:
            await offered(actor)
            state = await turn(actor, reply, 2, 1)
            assert not any(e.kind is EffectKind.SCENE for e in state.active_grants)
            assert not character.runtime.story.episodes
            assert character.runtime.story.node is (StoryNode.CAFE_CHAT if reply == 'no' else StoryNode.AWAIT_RAIN_CHOICE)
        finally: await actor.close()
    _run(run())


def test_uninvited_scene_proposal_is_not_permission():
    async def run():
        actor, character, _, _ = window_setup()
        try:
            state = await turn(actor, 'force-window', 1)
            assert not any(e.kind is EffectKind.SCENE for e in state.active_grants)
            assert not character.runtime.story.episodes
        finally: await actor.close()
    _run(run())


@pytest.mark.parametrize('cancel', ['stop', 'new-input'])
def test_pending_scene_cancellation_keeps_actual_state_and_has_no_false_episode(cancel):
    async def run():
        actor, character, _, _ = window_setup()
        try:
            await offered(actor)
            state = await turn(actor, 'yes', 2, 1)
            assert any(e.kind is EffectKind.SCENE for e in state.active_grants)
            if cancel == 'stop': await actor.stop(activity_seq=3, cutoff=1)
            else: await turn(actor, 'unrelated', 3, 1)
            assert character.runtime.story.pending is None
            assert not character.runtime.story.episodes
            assert character.runtime.story.current_outfit == 'black_jacket'
        finally: await actor.close()
    _run(run())


def test_unavailable_scene_never_grants_or_records_arrival():
    async def run():
        actor, character, _, _ = window_setup(ready=False)
        try:
            await offered(actor)
            state = await turn(actor, 'yes', 2, 1)
            assert not any(e.kind is EffectKind.SCENE for e in state.active_grants)
            assert not character.runtime.story.episodes
            assert character.runtime.story.offer_status is OfferStatus.CLOSED_CAPABILITY_UNAVAILABLE
        finally: await actor.close()
    _run(run())


@pytest.mark.parametrize('offered_goal,accepted_route', [('wardrobe','window'), ('window','wardrobe')])
def test_acceptance_cannot_cross_presented_offer_goal(offered_goal, accepted_route):
    async def run():
        actor, character, generation, _ = window_setup()
        try:
            original_generate = generation.generate
            async def changed(context):
                async for candidate in original_generate(context):
                    proposal = json.loads(candidate.story_proposal_json)
                    if context.user_text == 'offer' and offered_goal == 'wardrobe':
                        proposal.pop('target_capabilities')
                        text = '想看看我换上琥珀雨衣吗？'
                        proposal['draft_cue'] = text
                        candidate = replace(candidate, effects=(EffectProposal(EffectKind.SUBTITLE,text),))
                    if context.user_text == 'yes' and accepted_route == 'wardrobe':
                        proposal.update(transition_id='t.yes',signal='accept_raincoat',target_capabilities=['mira.outfit.amber_raincoat'])
                        candidate = replace(candidate,effects=(candidate.effects[0],))
                    yield replace(candidate,story_proposal_json=json.dumps(proposal,ensure_ascii=False))
            generation.generate = changed
            character.readiness = replace(character.readiness,records=character.readiness.records+(CapabilityRecord(
                'mira.outfit.amber_raincoat',CapabilityState.READY,'wardrobe-v1',('outer.amber','inner.cream'),'synthetic'),))
            await offered(actor)
            state = await turn(actor,'yes',2,1)
            assert not any(e.kind is EffectKind.SCENE or e.value.startswith('outfit_') for e in state.active_grants)
            assert character.runtime.story.node is StoryNode.AWAIT_RAIN_CHOICE
            assert not character.runtime.story.episodes
        finally: await actor.close()
    _run(run())


def test_offer_goal_checkpoint_roundtrip_and_schema4_read_does_not_infer_scene_consent(tmp_path):
    import sqlite3
    from mira.adapters.memory.story import StoryCheckpointStore
    from mira.domain.story import StoryTurn, JevEvidence, Will, Relevance, parse_story_proposal, reduce_story
    async def run():
        actor, character, _, _ = window_setup()
        try:
            await offered(actor)
            private = tmp_path / 'private';private.mkdir(mode=0o700)
            path = private / 'story.sqlite3'
            store = StoryCheckpointStore(path,enabled=True,explicitly_authorized=True,authorized_scope_id='synthetic-scope')
            story = character.runtime.story
            store.save(story,character.runtime.affect)
            params = dict(graph_id=story.graph_id,graph_revision=story.graph_revision,canon_revision=story.canon_revision,
                graph_hash=story.graph_hash,canon_hash=story.canon_hash)
            loaded, affect = store.load(story.scope_id,story.story_id,**params)
            assert loaded == replace(story,active_offer_cue=None) and loaded.active_offer_capability == 'cafe.scene.rain_window'
            assert loaded.active_offer_cue is None
            with sqlite3.connect(path) as db:
                value=json.loads(db.execute('SELECT story_json FROM story_checkpoint').fetchone()[0])
                value.pop('active_offer_capability');value.pop('active_offer_cue_digest')
                raw=json.dumps(value)
                db.execute('UPDATE story_checkpoint SET schema_version=4,story_json=?',(raw,))
            old, _ = store.load(story.scope_id,story.story_id,**params)
            assert old.current_outfit == story.current_outfit and old.receipt_ids == story.receipt_ids and old.node == story.node
            assert old.active_offer_capability is None and old.active_offer_cue is None
            with sqlite3.connect(path) as db:
                assert db.execute('SELECT schema_version,story_json FROM story_checkpoint').fetchone() == (4,raw)
            proposal=parse_story_proposal({'transition_id':'t.window','signal':'look_at_rain','offer_id':old.active_offer_id,
                'target_capabilities':['cafe.scene.rain_window']},input_id='fresh',epoch=old.epoch+1)
            result=reduce_story(old,StoryTurn('fresh',old.epoch+1,proposal,JevEvidence('fresh',old.epoch+1,
                old.active_offer_id,Will.YES,Relevance.RELEVANT),character.readiness,True),character.runtime.definition)
            assert result.effect_plan is None and not result.state.episodes
        finally: await actor.close()
    _run(run())


@pytest.mark.parametrize('uncertain',[False,True])
def test_real_jev_wire_and_conversation_first_actor_share_exact_offer_and_preserve_chat(uncertain):
    from uuid import uuid4
    from mira.adapters.journal.memory import MemoryEventJournal
    from mira.application.session_actor import SessionActor, RuntimeLimits
    from mira.bootstrap.development_review import create_development_review_providers
    from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
    from mira.domain.models import SessionState
    from tests.contracts.test_jev_character_observations import Transport
    from tests.contracts.test_development_review_composition import SyntheticJevTransport
    async def run():
        base, character, generation, _ = window_setup()
        await base.close()
        transport=Transport({'story_relevance':{'type':'noul','noul':1},
            'story_willingness':{'type':'noul','noul':.5 if uncertain else 1},
            'story_refusal':{'type':'noul','noul':0}})
        providers=create_development_review_providers(generation=generation,input_transport=SyntheticJevTransport(),
            output_transport=transport,authorized=True,input_request_limit=4,output_request_limit=6,conversation_first=True,decision_policy=USER_DEVELOPMENT_0_6_V2)
        actor=SessionActor(SessionState(str(uuid4()),str(uuid4())),generation,providers.review,MemoryEventJournal(100),
            RuntimeLimits(3,10,30),semantic_review=providers.semantic_review,decision_owner=providers.decision_owner,
            character_runtime=character)
        try:
            await offered(actor)
            state=await turn(actor,'yes',2,1)
            assert state.sealed and state.last_error is None
            assert any(e.kind is EffectKind.SUBTITLE for e in state.active_grants)
            assert any(e.kind is EffectKind.SCENE for e in state.active_grants) is (not uncertain)
            wire=transport.calls[-1]
            assert wire['state']['context']['character_story']['active_offer_capability']=='cafe.scene.rain_window'
            assert wire['state']['context']['character_story']['active_offer_cue']==generation.contexts[-1].character_story.active_offer_cue
            question=next(v for k,v in wire['questions'].items() if k.endswith(':story_willingness'))
            assert 'active_offer_capability' in question['instructions']['question']
            assert not character.runtime.story.episodes
        finally: await actor.close()
    _run(run())


def test_scene_readiness_requires_both_real_plates_and_the_authored_composition(tmp_path):
    import shutil
    from pathlib import Path
    from mira.bootstrap.character_assets import renderer_readiness
    root=Path(__file__).resolve().parents[2]/'apps/web'
    assert renderer_readiness('static-pixi').state_for('cafe.scene.rain_window') is CapabilityState.READY
    for name in ('public/scene/cafe-night.svg','public/scene/cafe-painterly-lighting-v3-table-free.png','public/scene-view.css'):
        target=tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/name,target)
    assert renderer_readiness('static-pixi',web_root=tmp_path).state_for('cafe.scene.rain_window') is CapabilityState.READY
    (tmp_path/'public/scene-view.css').write_text('not the authored composition')
    assert renderer_readiness('static-pixi',web_root=tmp_path).state_for('cafe.scene.rain_window') is CapabilityState.UNAVAILABLE


def test_late_pre_stop_scene_receipt_records_actual_history_without_reviving_graph():
    async def run():
        actor, character, _, _ = window_setup()
        try:
            await offered(actor)
            state=await turn(actor,'yes',2,1)
            subtitle=next(e for e in state.active_grants if e.kind is EffectKind.SUBTITLE)
            scene=next(e for e in state.active_grants if e.kind is EffectKind.SCENE)
            await acknowledge(actor,subtitle,2)
            await actor.stop(activity_seq=3,cutoff=3)
            assert character.runtime.story.pending is None
            assert not character.runtime.story.episodes
            await acknowledge(actor,scene,3)
            assert character.runtime.story.node is StoryNode.CAFE_CHAT
            assert character.runtime.story.pending is None
            assert character.runtime.story.episodes[-1].event_code=='cafe_rain_window_presented'
            assert json.loads(character.runtime.project().canonical_json)['last_acknowledged_scene']=='rain_window'
        finally:await actor.close()
    _run(run())


def test_checkpoint_stores_only_cue_digest_and_reentry_cancels_unanswered_scene_consent(tmp_path):
    import hashlib
    import sqlite3
    from mira.adapters.memory.story import StoryCheckpointStore, VersionMismatch
    from mira.bootstrap.character_story import reenter_runtime
    from mira.application.story import StoryRuntime
    async def run():
        actor, character, _, _ = window_setup()
        try:
            await offered(actor)
            private=tmp_path/'private';private.mkdir(mode=0o700)
            path=private/'story.sqlite3'
            text='窗边看雨好吗？刚才你说 PRIVATE_USER_SENTINEL 不想让别人知道。'
            story=replace(character.runtime.story,active_offer_cue=text)
            store=StoryCheckpointStore(path,enabled=True,explicitly_authorized=True,authorized_scope_id=story.scope_id)
            store.save(story,character.runtime.affect)
            store.save(story,character.runtime.affect)  # Same receipt retry remains idempotent.
            with pytest.raises(VersionMismatch):
                store.save(replace(story,active_offer_cue=text+'changed'),character.runtime.affect)
            with sqlite3.connect(path) as db:
                raw=db.execute('SELECT story_json FROM story_checkpoint').fetchone()[0]
                payload=json.loads(raw)
                assert 'active_offer_cue' not in payload
                assert payload['active_offer_cue_digest']==hashlib.sha256(text.encode()).hexdigest()
                assert 'PRIVATE_USER_SENTINEL' not in raw
            assert b'PRIVATE_USER_SENTINEL' not in path.read_bytes()
            loaded,affect=store.load(story.scope_id,story.story_id,graph_id=story.graph_id,
                graph_revision=story.graph_revision,canon_revision=story.canon_revision,
                graph_hash=story.graph_hash,canon_hash=story.canon_hash)
            assert loaded.active_offer_cue is None
            store.save(loaded,affect)  # A read-only reconstruction cannot erase the saved digest.
            with sqlite3.connect(path) as db:
                assert db.execute('SELECT story_json FROM story_checkpoint').fetchone()[0]==raw
            resumed=StoryRuntime(character.runtime.definition,story.scope_id)
            resumed.story,resumed.affect=loaded,affect
            reenter_runtime(resumed)
            assert resumed.story.active_offer_id is None and resumed.story.active_offer_cue is None
            assert resumed.story.node is StoryNode.CAFE_CHAT
            assert resumed.story.current_outfit==story.current_outfit
            assert resumed.story.receipt_ids==story.receipt_ids and resumed.story.episodes==story.episodes
        finally:await actor.close()
    _run(run())
