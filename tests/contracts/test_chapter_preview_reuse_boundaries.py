import asyncio
from dataclasses import replace
import pytest
from mira.application.actor_story import SessionCharacterRuntime
from mira.application.story import StoryRuntime
from mira.bootstrap.character_story import builtin_definition
from mira.domain.models import EffectKind
from mira.domain.xiahe_chapter import ChapterState,ChapterStage
from tests.contracts.test_luna_tool_actor import ToolTurn,Tools,actor,submit,wait_state,result
from tests.contracts.test_development_review_composition import finish
from tests.contracts.test_authored_photo_events import ready,receipt

async def setup():
    turns=[ToolTurn(),ToolTurn(),ToolTurn()];tools=Tools(*turns)
    character=SessionCharacterRuntime(StoryRuntime(builtin_definition(),'scope.synthetic.reuse-boundaries'),ready())
    value,_,_,_=actor(turns[0],tools=tools,result_wait=1,character=character)
    await submit(value,1);state=await wait_state(value,lambda s:s.fixed_photo.state=='granted')
    photo=next(e for e in state.active_grants if e.kind is EffectKind.MEDIA)
    await value.receipt(receipt(photo,1));state=await finish(value)
    await value.receipt(receipt(next(e for e in state.active_grants if e.kind is EffectKind.SUBTITLE),2))
    milestones=tuple((name,'synthetic.prior.'+name) for name in ('recognition','old_friend','old_friend_2','old_friend_3','photo_promise'))
    character.runtime.story=replace(character.runtime.story,chapter=ChapterState(stage=ChapterStage.PROMISE,role_active=True,milestones=milestones))
    return value,character,turns,photo


@pytest.mark.asyncio
async def test_reuse_preserves_original_epoch_sequence_and_is_idempotent():
    value,character,turns,photo=await setup()
    try:
        before=character.runtime.story
        await submit(value,2,2);state=await finish(value)
        chapter=character.runtime.story.chapter;reference=chapter.preview_reference
        assert chapter.stage is ChapterStage.PREVIEWED and reference.mode=='reused_visible'
        assert (reference.effect_id,reference.output_epoch,reference.activity_seq,reference.presentation_seq)==(photo.id,1,1,1)
        assert character.runtime.story.receipt_ids==before.receipt_ids
        assert character.runtime.story.episodes==before.episodes
        await value.receipt(receipt(next(e for e in state.active_grants if e.kind is EffectKind.SUBTITLE),3))
        await submit(value,3,3);state=await finish(value)
        assert result(turns[2])['status']=='reused'
        assert character.runtime.story.chapter==chapter
        assert len([e for e in state.issued_effects if e.kind is EffectKind.MEDIA])==1
    finally:await value.close()


@pytest.mark.asyncio
async def test_dismissed_photo_requires_new_presentation_not_old_reuse():
    value,character,turns,photo=await setup()
    try:
        state=await value.snapshot()
        await value.dismiss_photo(request_id='dismiss.audit',expected_revision=state.photo_visibility_revision,cutoff=2)
        await submit(value,2,2)
        state=await wait_state(value,lambda s:s.fixed_photo.state=='granted')
        fresh=next(e for e in state.active_grants if e.kind is EffectKind.MEDIA)
        assert fresh.id!=photo.id and character.runtime.story.chapter.stage is ChapterStage.PROMISE
        await value.receipt(receipt(fresh,3));await finish(value)
        reference=character.runtime.story.chapter.preview_reference
        assert reference.mode=='new_presentation' and reference.effect_id==fresh.id and reference.output_epoch==2
        assert result(turns[1])['status']=='shown'
    finally:await value.close()


@pytest.mark.parametrize('fence',['stop','dismiss'])
@pytest.mark.asyncio
async def test_fence_while_reuse_checkpoint_waits_cannot_resume_tool_continuation(fence):
    value,character,turns,photo=await setup();entered=asyncio.Event();release=asyncio.Event();saved=[]
    async def persist(snapshot):
        saved.append(snapshot);entered.set()
        try:await release.wait()
        except asyncio.CancelledError:await release.wait()
    character._checkpoint=persist
    try:
        await submit(value,2,2)
        async with asyncio.timeout(2):await entered.wait()
        assert character.runtime.story.chapter.stage is ChapterStage.PREVIEWED
        state=await value.snapshot()
        if fence=='stop':await value.stop(activity_seq=3,cutoff=2)
        else:await value.dismiss_photo(request_id='dismiss.wait.audit',expected_revision=state.photo_visibility_revision,cutoff=2)
        release.set()
        async with asyncio.timeout(2):
            while value._tasks:await asyncio.sleep(0)
        state=await value.snapshot()
        assert not turns[1].continued.is_set()
        assert not any(e.kind is EffectKind.MEDIA and e.id!=photo.id for e in state.issued_effects)
        assert 'photo_handover' not in dict(character.runtime.story.chapter.milestones)
        assert saved[0].story.chapter.preview_reference.output_epoch==1
        if fence=='dismiss':assert not state.photo_visible
    finally:release.set();await value.close()
