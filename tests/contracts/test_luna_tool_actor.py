"""Synthetic actual Actor/tool/permit/receipt contract; no provider or browser IO."""
import asyncio
import json
from dataclasses import replace

import pytest

from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.contracts import CandidateRange, EffectProposal
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V1
from mira.application.ports.generation_tools import GenerationToolCall
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.bootstrap.development_review import create_development_review_providers
from mira.domain.errors import DomainError
from mira.domain.models import EffectKind, SessionState
from mira.domain.story import ReadinessCatalog
from tests.contracts.test_authored_photo_events import ready, receipt
from tests.contracts.test_development_review_composition import SyntheticJevTransport, finish


def text_candidate(*extra):
    return CandidateRange((EffectProposal(EffectKind.SUBTITLE, 'The application result is available.'), *extra), 'tool-synthetic')


class LegacyGeneration:
    def __init__(self): self.calls = 0
    async def generate(self, context):
        self.calls += 1
        yield text_candidate()


class ToolTurn:
    def __init__(self, call=None, *, start_gate=False, continue_gate=False, ignore_cancel=False):
        self.call = call or GenerationToolCall('call-1', 'show_photo', '{"photo_id":"trip_photo"}')
        self.start_count = 0
        self.results = []
        self.started = asyncio.Event()
        self.continued = asyncio.Event()
        self.release = asyncio.Event()
        self.start_gate = start_gate
        self.continue_gate = continue_gate
        self.ignore_cancel = ignore_cancel
        self.closed = 0
        self.candidate = text_candidate()
    async def gate(self):
        try: await self.release.wait()
        except asyncio.CancelledError:
            if not self.ignore_cancel: raise
            await self.release.wait()
    async def start(self):
        self.start_count += 1
        self.started.set()
        if self.start_gate: await self.gate()
        return self.call
    async def continue_after_tool(self, result, current_context):
        self.results.append((result, current_context))
        self.continued.set()
        if self.continue_gate: await self.gate()
        return self.candidate
    def close(self): self.closed += 1


class Tools:
    def __init__(self, *turns): self.turns=list(turns); self.opens=[]
    def open_tool_turn(self, context, tools):
        self.opens.append((context, tools))
        return self.turns[len(self.opens)-1]


class ObservedActor(SessionActor):
    def __init__(self, *args, **kwargs):
        self.changed = asyncio.Event()
        super().__init__(*args, **kwargs)
    def _commit(self, state, kind):
        super()._commit(state, kind)
        self.changed.set()


def actor(turn, *, mode='allow', catalog=None, result_wait=.02, tools=None, runtime=None, character=None):
    legacy=LegacyGeneration(); wire=SyntheticJevTransport(output_choice=mode)
    providers=create_development_review_providers(generation=legacy, input_transport=wire,
        output_transport=wire, authorized=True, decision_policy=USER_DEVELOPMENT_0_6_V1,
        input_request_limit=8, output_request_limit=8, conversation_first=True,
        character_observations=character is not None,story_images=runtime is not None)
    tool_backend=tools or Tools(turn)
    value=ObservedActor(SessionState('s','c'), legacy, providers.review, MemoryEventJournal(200),
        RuntimeLimits(3,8,64), semantic_review=providers.semantic_review,
        decision_owner=providers.decision_owner, visual_readiness=catalog or ready(),
        tool_generation=tool_backend, tool_result_wait_seconds=result_wait,
        story_image_runtime=runtime, character_runtime=character)
    return value, tool_backend, legacy, wire


async def submit(value, n=1, cutoff=0):
    return await value.submit(request_id=f'i{n}', activity_seq=n, cutoff=cutoff, text='Please show a fictional image.')


async def wait_state(value, predicate):
    async with asyncio.timeout(2):
        while True:
            value.changed.clear()
            state=await value.snapshot()
            if predicate(state): return state
            await value.changed.wait()


def result(turn):
    return json.loads(turn.results[-1][0].output_json)


@pytest.mark.asyncio
async def test_tool_shown_requires_exact_receipt_and_refreshes_same_turn_context():
    turn=ToolTurn();value,tools,legacy,_=actor(turn,result_wait=1)
    try:
        await submit(value)
        state=await wait_state(value,lambda s:s.fixed_photo.state=='granted')
        photo=next(e for e in state.active_grants if e.kind is EffectKind.MEDIA)
        assert not turn.results and not state.presented_effects
        with pytest.raises(DomainError): await value.receipt(replace(receipt(photo,1),digest='wrong'))
        assert not turn.results
        await value.receipt(receipt(photo,1));state=await finish(value)
        data=result(turn)
        assert data['status']=='shown' and data['shown'] is True and data['visible'] is True
        assert data['receipt']=={'effect_id':photo.id,'digest':photo.digest,'output_epoch':1,'activity_seq':1,'presentation_seq':1}
        assert data['provenance']=='authored_illustration'
        context=turn.results[0][1]
        assert context.output_epoch==1 and context.photo_visible and photo in context.presented_effects
        assert context.fixed_photo.state=='presented' and context.accepted_prefix==(photo,)
        assert state.sealed and state.last_error is None
        assert legacy.calls==0 and turn.start_count==1 and len(turn.results)==1 and turn.closed==1
        assert [x.name for x in tools.opens[0][1]]==['show_photo']
    finally: await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,expected',[('unknown','held'),('reject','held'),('allow','pending')])
async def test_optional_result_is_truthful_and_does_not_block_followup_text(mode,expected):
    value,turn,_,_,_,_=image_actor(mode=mode)
    try:
        await submit(value);state=await finish(value)
        assert result(turn)['status']==expected and result(turn)['shown'] is False
        assert 'receipt' not in result(turn) and not state.presented_effects
        assert any(e.kind is EffectKind.SUBTITLE for e in state.active_grants)
        assert state.sealed and state.last_error is None
    finally: await value.close()


@pytest.mark.asyncio
async def test_visible_photo_reuses_accepted_receipt_without_render_or_second_review():
    first,second=ToolTurn(),ToolTurn();tools=Tools(first,second)
    value,_,_,wire=actor(first,tools=tools,result_wait=1)
    try:
        await submit(value);state=await wait_state(value,lambda s:s.fixed_photo.state=='granted')
        photo=state.active_grants[0];await value.receipt(receipt(photo,1));state=await finish(value)
        text=next(e for e in state.active_grants if e.kind is EffectKind.SUBTITLE)
        await value.receipt(receipt(text,2));reviews=len(wire.calls)
        await submit(value,2,2);state=await finish(value)
        assert result(second)['status']=='reused' and result(second)['shown'] is True
        assert result(second)['receipt']['effect_id']==photo.id
        assert len([e for e in state.issued_effects if e.kind is EffectKind.MEDIA])==1
        assert len(wire.calls)==reviews
    finally: await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('call',[
    GenerationToolCall('x','show_photo','{"photo_id":"trip_photo","receipt":"fake"}'),
    GenerationToolCall('x','show_photo','{"photo_id":"trip_photo","photo_id":"trip_photo"}'),
    GenerationToolCall('x','show_photo','{"photo_id":"https://bad.invalid/image"}'),
    GenerationToolCall('x','invented_tool','{}'),
])
async def test_invalid_tool_arguments_never_execute_and_continue_as_held(call):
    turn=ToolTurn(call);value,_,_,wire=actor(turn)
    try:
        await submit(value);state=await finish(value)
        assert result(turn)['status'] in ('held','unavailable')
        assert not any(e.kind is EffectKind.MEDIA for e in state.issued_effects)
        assert not wire.calls and state.last_error is None
    finally: await value.close()


@pytest.mark.asyncio
async def test_unavailable_tool_is_not_advertised_or_executed():
    turn=ToolTurn();value,tools,_,wire=actor(turn,catalog=ReadinessCatalog('empty'))
    try:
        await submit(value);state=await finish(value)
        assert tools.opens[0][1]==() and result(turn)['status']=='unavailable'
        assert not wire.calls and not any(e.kind is EffectKind.MEDIA for e in state.issued_effects)
    finally: await value.close()


@pytest.mark.asyncio
async def test_continuation_cannot_execute_old_media_or_image_proposals_again():
    turn=ToolTurn();turn.candidate=replace(text_candidate(EffectProposal(EffectKind.MEDIA,'trip_photo')),
        image_proposal_json='malformed',story_proposal_json='malformed',affect_proposal_json='malformed')
    value,_,_,wire=actor(turn)
    try:
        await submit(value);state=await finish(value)
        assert state.last_error=='invalid_response'
        assert len([e for e in state.issued_effects if e.kind is EffectKind.MEDIA])==1
        assert wire.calls==[] and len(turn.results)==1
    finally: await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('fence',['stop','new_input','dismiss','close'])
@pytest.mark.parametrize('phase',['start','continuation'])
async def test_uncooperative_tool_turn_cannot_revive_after_fence(fence,phase):
    turn=ToolTurn(start_gate=phase=='start',continue_gate=phase=='continuation',ignore_cancel=True)
    replacement=ToolTurn(call=text_candidate())
    value,_,_,_=actor(turn,tools=Tools(turn,replacement))
    try:
        await submit(value)
        await asyncio.wait_for(turn.started.wait() if phase=='start' else turn.continued.wait(),1)
        if fence=='stop': await value.stop(activity_seq=2,cutoff=0)
        elif fence=='new_input': await submit(value,2)
        elif fence=='dismiss': await value.dismiss_photo(request_id='dismiss',expected_revision=0,cutoff=0,target='all_photos')
        else: await value.close()
        assert turn.closed>=1
        turn.release.set();await finish(value)
        state=await value.snapshot()
        assert not state.presented_effects
        assert not any(e.kind is EffectKind.SUBTITLE and e.output_epoch==1 for e in state.issued_effects)
        assert len(turn.results)==(1 if phase=='continuation' else 0)
    finally: turn.release.set();await value.close()


class ImageBackend:
    def __init__(self, *, blocked=False, fail=False, ignore_cancel=False):
        self.requests=[];self.entered=asyncio.Event();self.release=asyncio.Event()
        self.blocked=blocked;self.fail=fail;self.ignore_cancel=ignore_cancel
    async def generate(self,request):
        from mira.application.ports.media import GeneratedImage
        from tests.contracts.test_story_images import png
        self.requests.append(request);self.entered.set()
        if self.blocked:
            try: await self.release.wait()
            except asyncio.CancelledError:
                if not self.ignore_cancel: raise
                await self.release.wait()
        if self.fail: raise ValueError('synthetic generation failed')
        return GeneratedImage(png(),'image/png','synthetic','fixture')


def image_actor(*, result_wait=.02, blocked=False, authorized=True, mode='allow',fail=False,vision_mode='allow',ignore_cancel=False):
    from mira.application.story_images import StoryImageRuntime,StoryImageAdmission
    from mira.bootstrap.character_story import ephemeral_character_factory
    from tests.contracts.test_story_images import Decoder,Vision
    images=ImageBackend(blocked=blocked,fail=fail,ignore_cancel=ignore_cancel);vision=Vision(vision_mode)
    runtime=StoryImageRuntime(images,vision,Decoder(),StoryImageAdmission('synthetic-only',True,
        timeout_seconds=1,authorized_custom_brief=authorized))
    character=ephemeral_character_factory(readiness=ready())(SessionState('s','c'))
    turn=ToolTurn(GenerationToolCall('image-1','generate_story_image',json.dumps({
        'brief':'A small imagined blue boat on a moonlit empty lake.','framing':'wide','lighting':'scene_default'})))
    value,tools,legacy,wire=actor(turn,result_wait=result_wait,runtime=runtime,character=character,mode=mode)
    return value,turn,images,vision,tools,wire


@pytest.mark.asyncio
async def test_generated_image_qualifies_exact_bytes_before_receipted_shown_result():
    value,turn,images,vision,tools,wire=image_actor(result_wait=1)
    try:
        await submit(value)
        state=await wait_state(value,lambda s:s.story_image.state in ('qualified','held','failed'))
        assert state.story_image.state=='qualified' and not turn.results
        photo=next(e for e in state.active_grants if e.kind is EffectKind.MEDIA)
        from mira.domain.story_images import parse_generated_photo
        resource,digest=parse_generated_photo(photo.value)
        data=await value.story_image_resource(resource_id=resource,content_digest=digest,
            effect_id=photo.id,digest=photo.digest,output_epoch=photo.output_epoch,activity_seq=photo.activity_seq)
        assert data==vision.calls[0][0].png
        assert not state.presented_effects
        await value.receipt(receipt(photo,1));state=await finish(value)
        assert result(turn)['status']=='shown' and result(turn)['provenance']=='generated_visualization'
        assert result(turn)['receipt']['effect_id']==photo.id
        assert turn.results[0][1].story_images[0].visible is True
        assert len(images.requests)==1 and len(vision.calls)==1
        assert images.requests[0].allowed_resource_ids==()
        assert images.requests[0].parent_request_id=='i1' and images.requests[0].output_epoch==1
        assert images.requests[0].catalog_revision=='mira-fiction-brief-v1'
        assert [d.name for d in tools.opens[0][1]]==['show_photo','generate_story_image']
        review=[item[0] for item in wire.calls if 'contract' in item[0]['state']][0]
        assert review['state']['candidate']['effects']==[]
        assert review['state']['candidate']['image_intent']['specification_digest']==images.requests[0].specification_digest
        assert state.last_error is None and state.sealed
    finally: await value.close()


@pytest.mark.asyncio
async def test_long_image_returns_pending_then_finishes_without_third_generation_call():
    value,turn,images,vision,_,_=image_actor(blocked=True)
    try:
        await submit(value);await asyncio.wait_for(images.entered.wait(),1);state=await finish(value)
        assert result(turn)['status']=='pending' and result(turn)['phase']=='generating'
        assert state.sealed and not vision.calls and len(turn.results)==1
        images.release.set();state=await wait_state(value,lambda s:s.story_image.state=='qualified')
        photo=next(e for e in state.active_grants if e.kind is EffectKind.MEDIA)
        await value.receipt(receipt(photo,1))
        assert len(turn.results)==1 and turn.start_count==1 and len(images.requests)==1
    finally: images.release.set();await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('case,expected',[('unauthorized','unavailable'),('review_unknown','held'),('review_reject','held'),('generation_failed','failed'),('pixels_rejected','failed')])
async def test_image_failures_are_truthful_nonfatal_and_respect_call_scope(case,expected):
    value,turn,images,vision,tools,_=image_actor(result_wait=1,authorized=case!='unauthorized',
        mode='unknown' if case=='review_unknown' else 'reject' if case=='review_reject' else 'allow',
        fail=case=='generation_failed',vision_mode='reject' if case=='pixels_rejected' else 'allow')
    try:
        await submit(value);state=await finish(value)
        assert result(turn)['status']==expected and not result(turn)['shown']
        assert not state.presented_effects and state.last_error is None
        assert any(e.kind is EffectKind.SUBTITLE for e in state.active_grants)
        assert len(images.requests)==int(case in ('generation_failed','pixels_rejected'))
        assert len(vision.calls)==int(case=='pixels_rejected')
        if case=='unauthorized': assert [d.name for d in tools.opens[0][1]]==['show_photo']
    finally: await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('fence',['stop','new_input','dismiss','close'])
async def test_pending_uncooperative_image_cannot_revive_after_fence(fence):
    value,turn,images,vision,tools,_=image_actor(blocked=True,ignore_cancel=True)
    try:
        await submit(value);await asyncio.wait_for(images.entered.wait(),1);await finish(value)
        if fence=='stop': await value.stop(activity_seq=2,cutoff=0)
        elif fence=='new_input': tools.turns.append(ToolTurn(call=text_candidate()));await submit(value,2)
        elif fence=='dismiss': await value.dismiss_photo(request_id='dismiss',expected_revision=0,cutoff=0,target='all_photos')
        else: await value.close()
        images.release.set();await asyncio.gather(*tuple(value._image_tasks),return_exceptions=True)
        await finish(value);state=await value.snapshot()
        if fence=='new_input':
            assert state.story_image.state=='qualified'
            assert any(e.kind is EffectKind.MEDIA and e.output_epoch==2 for e in state.active_grants)
            assert len(vision.calls)==1
        else:
            assert not any(e.kind is EffectKind.MEDIA for e in state.active_grants)
            assert not vision.calls
        assert len(turn.results)==1
    finally: images.release.set();await value.close()


@pytest.mark.asyncio
async def test_invalid_continuation_preserves_real_shown_photo_history_and_visibility():
    turn=ToolTurn();turn.candidate=text_candidate(EffectProposal(EffectKind.MEDIA,'trip_photo'))
    value,_,_,_=actor(turn,result_wait=1)
    try:
        await submit(value);state=await wait_state(value,lambda s:s.fixed_photo.state=='granted')
        photo=state.active_grants[0];await value.receipt(receipt(photo,1));state=await finish(value)
        assert state.last_error=='invalid_response' and state.photo_visible
        assert state.presented_effects==(photo,) and len(state.receipts)==1
        assert result(turn)['shown'] is True
    finally: await value.close()


@pytest.mark.asyncio
async def test_optional_review_timeout_returns_held_and_still_continues_once():
    value,turn,_,_,_,wire=image_actor()
    wire.output_gate=True
    try:
        await submit(value);state=await finish(value)
        assert result(turn)['status']=='held' and result(turn)['reason']=='review_timeout'
        assert state.last_error is None and state.sealed and len(turn.results)==1
        assert not any(e.kind is EffectKind.MEDIA for e in state.issued_effects)
    finally: wire.release.set();await value.close()


def test_empty_image_contract_is_opt_in_and_empty_or_forged_candidates_stay_closed():
    from mira.application.decision_contracts import ResponseContractProducer
    from mira.application.story_images import compile_image_intent
    from mira.domain.story_images import ImageProposal
    from tests.contracts.test_story_images import story
    from tests.contracts.test_decision_contracts import snapshot,observation
    snap=snapshot();snap=replace(snap,context=replace(snap.context,character_story=story()))
    candidate=CandidateRange((),'image-only',image_intent=compile_image_intent(ImageProposal('cafe_rain_window'),snap.context.character_story))
    producer=ResponseContractProducer();kwargs={'snapshot':snap,'observation':observation(snap)}
    assert producer.produce(snap.context,candidate,**kwargs) is None
    assert producer.produce(snap.context,candidate,optional_image_only=True,**kwargs) is not None
    for empty in (replace(candidate,image_intent=None),replace(candidate,image_intent={'permission':True})):
        assert producer.produce(snap.context,empty,optional_image_only=True,**kwargs) is None
    assert producer.produce(snap.context,candidate,scope='seal',optional_image_only=True,**kwargs) is None

@pytest.mark.asyncio
async def test_real_photo_receipt_arriving_after_result_wait_is_reprojected_with_context():
    turn=ToolTurn();value,_,_,_=actor(turn)
    execute=value._execute_tool
    async def receipt_before_continuation(*args):
        result=await execute(*args)
        state=await value.snapshot();photo=state.active_grants[0]
        await value.receipt(receipt(photo,1))
        return result
    value._execute_tool=receipt_before_continuation
    try:
        await submit(value);await finish(value)
        assert result(turn)['status']=='shown' and turn.results[0][1].photo_visible
        assert turn.results[0][1].fixed_photo.state=='presented'
    finally: await value.close()


@pytest.mark.asyncio
async def test_late_accepted_receipt_after_stop_updates_history_without_continuation():
    turn=ToolTurn();value,_,_,_=actor(turn,result_wait=1)
    try:
        await submit(value);state=await wait_state(value,lambda s:s.fixed_photo.state=='granted')
        photo=state.active_grants[0]
        await value.stop(activity_seq=2,cutoff=1)
        state=await value.receipt(receipt(photo,1));await finish(value)
        assert state.presented_effects==(photo,) and state.fixed_photo.state=='presented'
        assert not turn.results and not state.active_grants
    finally: await value.close()


@pytest.mark.asyncio
async def test_duplicate_input_does_not_repeat_tool_or_optional_review():
    turn=ToolTurn();value,tools,_,wire=actor(turn)
    try:
        await submit(value);await submit(value);await finish(value);await submit(value)
        assert len(tools.opens)==1 and turn.start_count==1 and len(turn.results)==1
        assert wire.calls==[]
    finally: await value.close()


@pytest.mark.asyncio
async def test_ordinary_start_candidate_preserves_optional_character_controls():
    turn=ToolTurn(call=text_candidate(EffectProposal(EffectKind.POSE,'camera_raise')))
    value,_,_,wire=actor(turn)
    try:
        await submit(value);state=await finish(value)
        assert [e.kind for e in state.active_grants]==[EffectKind.SUBTITLE,EffectKind.POSE]
        assert not turn.results and len(wire.calls)==2
    finally: await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('tool_call',[False,True])
async def test_tool_path_uses_existing_caption_chunker_once(tool_call):
    turn=ToolTurn() if tool_call else ToolTurn(call=text_candidate())
    value,_,_,_=actor(turn)
    class Chunker:
        def __init__(self): self.calls=[]
        async def expand(self,context,candidate):
            self.calls.append((context,candidate))
            yield replace(candidate,effects=(EffectProposal(EffectKind.SUBTITLE,'First complete sentence.'),))
            yield replace(candidate,effects=(EffectProposal(EffectKind.SUBTITLE,'Second complete sentence.'),))
    chunker=Chunker();value._tool_caption_chunker=chunker
    try:
        await submit(value);state=await finish(value)
        assert len(chunker.calls)==1
        assert [e.value for e in state.active_grants if e.kind is EffectKind.SUBTITLE]==[
            'First complete sentence.','Second complete sentence.']
        assert len(turn.results)==int(tool_call)
    finally: await value.close()


def test_escaped_unicode_brief_uses_protocol_envelope_bound_and_decoded_character_limit():
    from mira.application.generation_tool_execution import parse_tool_arguments
    arguments={'brief':'🌙'*600,'framing':'wide','lighting':'warm'}
    raw=json.dumps(arguments)
    assert 4096<len(raw.encode())<8192
    assert parse_tool_arguments(GenerationToolCall('x','generate_story_image',raw))==arguments
    with pytest.raises(ValueError):
        parse_tool_arguments(GenerationToolCall('x','generate_story_image',json.dumps({**arguments,'brief':'🌙'*601})))
    with pytest.raises(ValueError):
        parse_tool_arguments(GenerationToolCall('x','generate_story_image',' '*8193))
