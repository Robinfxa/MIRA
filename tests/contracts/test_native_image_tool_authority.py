"""Default native brief authority keeps independent exact-pixel review; offline only."""
import json
import pytest
from mira.application.ports.generation_tools import GenerationToolCall
from mira.application.story_images import StoryImageRuntime,StoryImageAdmission
from mira.application.session_actor import RuntimeLimits
from mira.adapters.journal.memory import MemoryEventJournal
from mira.bootstrap.character_story import ephemeral_character_factory
from mira.domain.models import SessionState,EffectKind
from tests.contracts.test_native_character_tools import NeverReview
from tests.contracts.test_luna_tool_actor import ImageBackend,ToolTurn,Tools,LegacyGeneration,ObservedActor,wait_state,result
from tests.contracts.test_authored_photo_events import ready,receipt
from tests.contracts.test_story_images import Decoder,Vision
from tests.contracts.test_development_review_composition import finish

@pytest.mark.asyncio
@pytest.mark.parametrize('case,expected',[('shown','shown'),('unauthorized','unavailable'),
    ('generation_failed','failed'),('pixels_rejected','failed')])
async def test_native_image_tool_never_calls_jev_and_keeps_pixel_and_consent_gates(case,expected):
    image=ImageBackend(fail=case=='generation_failed');vision=Vision('reject' if case=='pixels_rejected' else 'allow')
    runtime=StoryImageRuntime(image,vision,Decoder(),StoryImageAdmission('synthetic-native',True,
        timeout_seconds=1,authorized_custom_brief=case!='unauthorized'))
    c=ephemeral_character_factory(readiness=ready())(SessionState('s','c'))
    t=ToolTurn(GenerationToolCall('image','generate_story_image',json.dumps({
        'brief':'An empty imaginary blue lakeside.','framing':'wide','lighting':'warm'})))
    a=ObservedActor(SessionState('s','c'),LegacyGeneration(),NeverReview(),MemoryEventJournal(200),
        RuntimeLimits(3,8,64),tool_generation=Tools(t),native_tool_authority=True,
        character_runtime=c,story_image_runtime=runtime,tool_result_wait_seconds=1)
    try:
        await a.submit(request_id='i1',activity_seq=1,cutoff=0,text='想象一片空湖面')
        if case=='shown':
            s=await wait_state(a,lambda s:s.story_image.state=='qualified')
            e=next(e for e in s.active_grants if e.kind is EffectKind.MEDIA)
            assert not t.results and len(vision.calls)==1 and vision.calls[0][0].png
            await a.receipt(receipt(e,1))
        s=await finish(a)
        assert result(t)['status']==expected and result(t)['shown']==(case=='shown')
        assert len(image.requests)==int(case!='unauthorized')
        assert len(vision.calls)==int(case in {'shown','pixels_rejected'})
        assert s.last_error is None and any(e.kind is EffectKind.SUBTITLE for e in s.active_grants)
    finally:await a.close()
