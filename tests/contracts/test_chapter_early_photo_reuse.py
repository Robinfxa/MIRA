"""Focused actual Actor tool reuse with synthetic preexisting chapter facts."""
import pytest
from dataclasses import replace
from mira.application.actor_story import SessionCharacterRuntime
from mira.application.story import StoryRuntime
from mira.bootstrap.character_story import builtin_definition
from mira.domain.story import ReadinessCatalog
from mira.domain.models import EffectKind
from mira.domain.xiahe_chapter import ChapterState,ChapterStage
from tests.contracts.test_luna_tool_actor import ToolTurn,Tools,actor,submit,wait_state,result
from tests.contracts.test_development_review_composition import finish
from tests.contracts.test_authored_photo_events import ready,receipt


@pytest.mark.asyncio
async def test_existing_preview_receipt_can_support_explicit_current_show_photo_after_promise():
    first,second=ToolTurn(),ToolTurn();tools=Tools(first,second)
    character=SessionCharacterRuntime(StoryRuntime(builtin_definition(),'scope.synthetic.early-photo'),ready())
    value,_,_,_=actor(first,tools=tools,result_wait=1,character=character)
    try:
        await submit(value,1)
        state=await wait_state(value,lambda s:s.fixed_photo.state=='granted')
        photo=next(e for e in state.active_grants if e.kind is EffectKind.MEDIA)
        await value.receipt(receipt(photo,1));state=await finish(value)
        text=next(e for e in state.active_grants if e.kind is EffectKind.SUBTITLE)
        await value.receipt(receipt(text,2))
        assert character.runtime.story.chapter.stage is ChapterStage.STRANGER
        # Precondition: later chapter beats have already been acknowledged.
        # This focused test isolates the real tool reuse boundary, not how those beats arose.
        milestones=tuple((name,'synthetic.prior.'+name) for name in ('recognition','old_friend','old_friend_2','old_friend_3','photo_promise'))
        character.runtime.story=replace(character.runtime.story,chapter=ChapterState(
            stage=ChapterStage.PROMISE,role_active=True,milestones=milestones))
        await submit(value,2,2);state=await finish(value)
        assert result(second)['status']=='reused' and result(second)['shown'] is True
        assert result(second)['receipt']['effect_id']==photo.id
        assert len([e for e in state.issued_effects if e.kind is EffectKind.MEDIA])==1
        assert character.runtime.story.chapter.stage is ChapterStage.PREVIEWED
        assert 'photo_handover' not in dict(character.runtime.story.chapter.milestones)
    finally:await value.close()
