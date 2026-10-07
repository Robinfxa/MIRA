"""Exact authored events with actual parser, JEV, Actor and receipt reducers; offline."""
import json
from dataclasses import replace

import pytest

from mira.adapters.generation.codex_support.payload import parse_effects, build_prompt
from mira.adapters.generation.codex_support.types import CodexLimits, CodexGenerationError
from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext, generation_context_data
from mira.application.session_actor import SessionActor, RuntimeLimits
from mira.bootstrap.development_review import create_development_review_providers
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V1
from mira.domain.models import EffectKind, Receipt, SessionState
from mira.domain.errors import DomainError
from mira.domain.story import CapabilityRecord, CapabilityState, ReadinessCatalog
from tests.contracts.test_development_review_composition import SyntheticJevTransport, finish


def ready():
    return ReadinessCatalog('synthetic-authored-v1', tuple(CapabilityRecord(key,
        CapabilityState.READY, 'synthetic-v1', (key,), 'synthetic-only') for key in
        ('mira.pose.camera_ready', 'mira.pose.camera_raise', 'mira.media.trip_photo')))


def test_parser_accepts_exact_camera_and_authored_photo_with_chat():
    values=[{'kind':'subtitle','value':'可以看看这张原创海岸插画。'},
            {'kind':'pose','value':'camera_raise'},{'kind':'media','value':'trip_photo'}]
    effects=parse_effects([json.dumps({'effects':values})],CodexLimits(),speech_enabled=False)
    assert [(e.kind.value,e.value) for e in effects] == [(e['kind'],e['value']) for e in values]


@pytest.mark.parametrize('value',['trip_photo_placeholder','https://example.com/photo.jpg','/tmp/photo.svg','user_photo','take_photo'])
def test_parser_rejects_every_other_media_value(value):
    with pytest.raises(CodexGenerationError,match='unsupported'):
        parse_effects([json.dumps({'effects':[{'kind':'media','value':value}]})],CodexLimits())


def test_generator_sees_available_events_and_explicit_fiction_provenance_without_story():
    context=GenerationContext('看照片',('看照片',),(),1,character_assets=ready())
    data=json.loads(build_prompt(context,CodexLimits()))
    assert 'camera_raise' in data['authored_controls']['pose']
    assert data['authored_controls']['media']==['trip_photo']
    facts=data['facts']['authored_visual_events']
    assert facts['trip_photo']['provenance']=='authored_illustration'
    assert facts['trip_photo']['presented'] is False
    assert facts['camera']['meaning']=='raise_held_camera_to_chest_only'
    assert facts['captures_photos'] is False


class Generation:
    def __init__(self,events):self.events=events;self.contexts=[]
    async def generate(self,context):
        self.contexts.append(context)
        yield CandidateRange(tuple(EffectProposal(EffectKind(k),v) for k,v in
            [('subtitle','可以看看这张原创海岸插画。'),*self.events]),'authored-synthetic')


def actor(events,mode='allow',catalog=None):
    generation=Generation(events)
    transport=SyntheticJevTransport(output_choice=mode)
    providers=create_development_review_providers(generation=generation,
        input_transport=transport,output_transport=transport,authorized=True,
        decision_policy=USER_DEVELOPMENT_0_6_V1,input_request_limit=8,output_request_limit=8,
        conversation_first=True)
    instance=SessionActor(SessionState('s','c'),generation,providers.review,
        MemoryEventJournal(100),RuntimeLimits(3,8,64),semantic_review=providers.semantic_review,
        decision_owner=providers.decision_owner,visual_readiness=catalog or ready())
    return instance,generation,transport


async def turn(value,n,cutoff=0):
    await value.submit(request_id=f'i{n}',activity_seq=n,cutoff=cutoff,text='请展示这张插画，抬起手中的相机。')
    return await finish(value)


def receipt(effect,n):
    return Receipt(effect.id,effect.digest,effect.output_epoch,effect.activity_seq,n)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['allow','unknown','reject'])
async def test_optional_mixed_review_never_blocks_chat(mode):
    value,generation,wire=actor([('pose','camera_raise'),('media','trip_photo')],mode)
    state=await turn(value,1)
    assert state.sealed and state.last_error is None
    assert [e.kind.value for e in state.active_grants] == (['subtitle','pose','media'] if mode=='allow' else ['subtitle'])
    assert state.presented_effects==()
    output=[item[0] for item in wire.calls if 'contract' in item[0]['state']]
    assert len(output)==1
    assert output[0]['state']['context']['authored_visual_events']['captures_photos'] is False
    await value.close()


@pytest.mark.asyncio
async def test_missing_readiness_holds_optional_actions_and_preserves_chat():
    value,_,wire=actor([('pose','camera_raise'),('media','trip_photo')],catalog=ReadinessCatalog('empty'))
    state=await turn(value,1)
    assert [e.kind.value for e in state.active_grants]==['subtitle']
    assert wire.calls==[]
    await value.close()


@pytest.mark.asyncio
async def test_valid_receipts_only_and_same_target_does_not_issue_repeated_action():
    value,generation,_=actor([('pose','camera_raise'),('media','trip_photo')])
    state=await turn(value,1)
    text,camera,photo=state.active_grants
    with pytest.raises(DomainError,match='Receipt identity'):
        await value.receipt(replace(receipt(camera,1),digest='wrong'))
    assert not (await value.snapshot()).presented_effects
    for n,e in enumerate((text,camera,photo),1):await value.receipt(receipt(e,n))
    await value.receipt(receipt(photo,3))
    next_state=await turn(value,2,3)
    assert [e.kind.value for e in next_state.active_grants]==['subtitle']
    facts=generation_context_data(generation.contexts[-1])['authored_visual_events']
    assert facts['camera']['last_acknowledged_endpoint']=='camera_raise'
    assert facts['camera']['status']=='acknowledged'
    assert facts['trip_photo']['presented'] is True
    assert len([e for e in next_state.presented_effects if e.kind is EffectKind.MEDIA])==1
    await value.close()


@pytest.mark.asyncio
async def test_cancelled_raise_does_not_suppress_return_to_old_ready_endpoint():
    value,generation,_=actor([('pose','camera_ready')])
    first=await turn(value,1)
    for n,e in enumerate(first.active_grants,1):await value.receipt(receipt(e,n))
    generation.events=[('pose','camera_raise')]
    second=await turn(value,2,2)
    cancelled=next(e for e in second.active_grants if e.kind is EffectKind.POSE)
    await value.stop(activity_seq=3,cutoff=2)
    with pytest.raises(DomainError,match='after its stop fence'):
        await value.receipt(receipt(cancelled,3))
    generation.events=[('pose','camera_ready')]
    recovered=await turn(value,4,2)
    facts=generation_context_data(generation.contexts[-1])['authored_visual_events']
    assert facts['camera']['last_acknowledged_endpoint']=='camera_ready'
    assert facts['camera']['status']=='uncertain'
    assert [(e.kind.value,e.value) for e in recovered.active_grants][-1]==('pose','camera_ready')
    for n,e in enumerate(recovered.active_grants,3):await value.receipt(receipt(e,n))
    again=await turn(value,5,4)
    assert [e.kind.value for e in again.active_grants]==['subtitle']
    assert generation_context_data(generation.contexts[-1])['authored_visual_events']['camera']['status']=='acknowledged'
    await value.close()


def copy_authored_web_root(tmp_path):
    import shutil
    from pathlib import Path
    root=Path(__file__).resolve().parents[2] / 'apps/web'
    for path in [root/'public/scene/code-native/readiness-catalog.json',
                 root/'public/scene/trip-memory.svg',
                 *list((root/'src/features/presentation/code-native-vendor').glob('*.js')),
                 root/'src/features/presentation/code-native-character-renderer.ts']:
        target=tmp_path/path.relative_to(root)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)
    return tmp_path


def test_photo_readiness_checks_fixed_bytes_and_never_camera_static_label(tmp_path):
    from mira.bootstrap.character_assets import renderer_readiness
    root=copy_authored_web_root(tmp_path)
    catalog=renderer_readiness('static-pixi',web_root=root)
    assert catalog.state_for('mira.media.trip_photo') is CapabilityState.READY
    assert catalog.state_for('mira.pose.camera_raise') is not CapabilityState.READY
    (root/'public/scene/trip-memory.svg').write_text('<svg>different authored content</svg>')
    assert renderer_readiness('static-pixi',web_root=root).state_for('mira.media.trip_photo') is CapabilityState.UNAVAILABLE
    (root/'public/scene/trip-memory.svg').unlink()
    assert renderer_readiness('static-pixi',web_root=root).state_for('mira.media.trip_photo') is CapabilityState.UNAVAILABLE


def test_camera_label_without_motion_sources_and_renderer_is_never_ready(tmp_path):
    from mira.bootstrap.character_assets import renderer_readiness
    root=copy_authored_web_root(tmp_path)
    path=root/'public/scene/code-native/readiness-catalog.json'
    data=json.loads(path.read_text())
    data['assets']['mira.pose.camera_raise']={'status':'review_only','reason':'name alone is not evidence'}
    data['sources'].pop('motion',None)
    data.pop('rendererSource',None)
    path.write_text(json.dumps(data))
    assert renderer_readiness('code-native-review',web_root=root).state_for('mira.pose.camera_raise') is CapabilityState.UNAVAILABLE


def test_changed_source_bytes_cannot_claim_renderable_geometry(tmp_path):
    from mira.bootstrap.character_assets import renderer_readiness
    root=copy_authored_web_root(tmp_path)
    (root/'src/features/presentation/code-native-vendor/body.js').write_text('changed source')
    with pytest.raises(ValueError,match='character_readiness_catalog_invalid'):
        renderer_readiness('code-native-review',web_root=root)


def test_motion_readiness_binds_renderer_and_all_five_sources(tmp_path):
    from mira.bootstrap.character_assets import renderer_readiness
    root=copy_authored_web_root(tmp_path)
    catalog=renderer_readiness('code-native-review',web_root=root)
    assert catalog.state_for('mira.pose.camera_raise') is CapabilityState.READY
    renderer=root/'src/features/presentation/code-native-character-renderer.ts'
    renderer.write_text(renderer.read_text()+'\n// changed implementation\n')
    assert renderer_readiness('code-native-review',web_root=root).state_for('mira.pose.camera_raise') is CapabilityState.UNAVAILABLE


@pytest.mark.asyncio
async def test_shipped_source_capabilities_drive_actual_jev_photo_camera_grants():
    from mira.bootstrap.character_assets import renderer_readiness
    value,_,_=actor([('pose','camera_raise'),('media','trip_photo')],catalog=renderer_readiness('code-native-review'))
    state=await turn(value,1)
    assert [e.kind.value for e in state.active_grants]==['subtitle','pose','media']
    await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('proposed,expected', [
    (['camera_raise','camera_ready'], ['camera_raise','camera_ready']),
    (['camera_raise','camera_ready','camera_raise'], ['camera_raise','camera_ready','camera_raise']),
    (['camera_ready','camera_raise','camera_raise','camera_ready','camera_ready','camera_raise'],
     ['camera_raise','camera_ready','camera_raise']),
])
async def test_camera_sequence_deduplicates_only_unchanged_projected_targets(proposed,expected):
    value,generation,_=actor([('pose','camera_ready')])
    first=await turn(value,1)
    for n,e in enumerate(first.active_grants,1):await value.receipt(receipt(e,n))
    generation.events=[('pose',target) for target in proposed]
    state=await turn(value,2,2)
    assert [e.value for e in state.active_grants if e.kind is EffectKind.POSE]==expected
    assert all(e.value=='camera_ready' for e in state.presented_effects if e.kind is EffectKind.POSE)
    await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('proposed,expected', [
    (['camera_ready','camera_ready','camera_raise','camera_ready','camera_raise'],
     ['camera_ready','camera_raise','camera_ready','camera_raise']),
    (['camera_ready','camera_ready'], ['camera_ready']),
    (['camera_raise','camera_raise','camera_ready','camera_raise'],
     ['camera_raise','camera_ready','camera_raise']),
    (['camera_ready','camera_raise','camera_ready'], ['camera_ready','camera_raise','camera_ready']),
])
async def test_uncertain_sequence_keeps_first_recovery_then_tracks_every_retained_target(proposed,expected):
    value,generation,_=actor([('pose','camera_ready')])
    first=await turn(value,1)
    for n,e in enumerate(first.active_grants,1):await value.receipt(receipt(e,n))
    generation.events=[('pose','camera_raise')]
    await turn(value,2,2)
    await value.stop(activity_seq=3,cutoff=2)
    generation.events=[('pose',target) for target in proposed]
    state=await turn(value,4,2)
    assert generation.contexts[-1].visual_action_uncertain is True
    assert [e.value for e in state.active_grants if e.kind is EffectKind.POSE]==expected
    await value.close()


@pytest.mark.asyncio
async def test_photo_duplicates_stay_idempotent_across_camera_sequence_and_receipts():
    value,generation,_=actor([('media','trip_photo'),('pose','camera_raise'),
        ('media','trip_photo'),('pose','camera_ready'),('media','trip_photo')])
    first=await turn(value,1)
    assert [(e.kind.value,e.value) for e in first.active_grants if e.kind is not EffectKind.SUBTITLE]==[
        ('media','trip_photo'),('pose','camera_raise'),('pose','camera_ready')]
    for n,e in enumerate(first.active_grants,1):await value.receipt(receipt(e,n))
    generation.events=[('pose','camera_raise'),('media','trip_photo'),('pose','camera_ready')]
    second=await turn(value,2,len(first.active_grants))
    assert [e.value for e in second.active_grants if e.kind is EffectKind.POSE]==['camera_raise','camera_ready']
    assert all(e.kind is not EffectKind.MEDIA for e in second.active_grants)
    await value.close()


@pytest.mark.asyncio
async def test_uncompleted_photo_can_retry_after_stop_and_only_duplicate_in_same_sequence_is_held():
    value,generation,_=actor([('media','trip_photo')])
    await turn(value,1)
    await value.stop(activity_seq=2,cutoff=0)
    generation.events=[('media','trip_photo'),('media','trip_photo')]
    state=await turn(value,3)
    assert [e.value for e in state.active_grants if e.kind is EffectKind.MEDIA]==['trip_photo']
    assert generation_context_data(generation.contexts[-1])['authored_visual_events']['trip_photo']['presented'] is False
    await value.close()


def test_unrelated_or_empty_catalog_does_not_expand_legacy_story_wire():
    from mira.application.decision_contracts import character_author_policy, mira26_author_policy
    from tests.contracts.test_character_control_bridge import ready_catalog
    for catalog in (ReadinessCatalog('empty'),ready_catalog()):
        context=GenerationContext('聊天',('聊天',),(),1,character_assets=catalog)
        assert 'authored_visual_events' not in generation_context_data(context)
        assert character_author_policy(None,readiness=catalog)==mira26_author_policy()


def test_visual_projection_keeps_only_available_or_actually_relevant_dimensions():
    from mira.domain.models import Effect
    photo_only=ReadinessCatalog('photo-only',tuple(record for record in ready().records
        if record.capability_id=='mira.media.trip_photo'))
    context=GenerationContext('看看插画',('看看插画',),(),1,character_assets=photo_only)
    facts=generation_context_data(context)['authored_visual_events']
    assert set(facts)=={'trip_photo','captures_photos'}
    assert facts['trip_photo']['provenance']=='authored_illustration'
    camera=Effect('camera-1',EffectKind.POSE,'camera_ready','digest-1',1,1)
    historical=replace(context,character_assets=None,presented_effects=(camera,),visual_action_uncertain=True)
    facts=generation_context_data(historical)['authored_visual_events']
    assert set(facts)=={'camera','captures_photos'}
    assert facts['camera']['status']=='uncertain'
    assert facts['camera']['last_acknowledged_endpoint']=='camera_ready'


@pytest.mark.asyncio
@pytest.mark.parametrize('referent_required',[0.0,1.0])
async def test_first_explicit_authored_photo_request_resolves_available_not_presented(referent_required):
    from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
    from mira.adapters.review.jev import JevHttpResponse
    class ExplicitPhotoWire(SyntheticJevTransport):
        async def __call__(self,payload,**kwargs):
            response=await super().__call__(payload,**kwargs)
            request=json.loads(payload);body=json.loads(response.body)
            if 'contract' not in request['state']:
                for key,question in request['questions'].items():
                    if key.endswith(':display_request'):body['answers'][key]={'type':'noul','noul':1.0}
                    elif key.endswith(':referent_required'):body['answers'][key]={'type':'noul','noul':referent_required}
                    elif key.endswith(':referent'):
                        options=list(question['criteria'])
                        chosen='authored.trip_photo' if 'authored.trip_photo' in options else 'ambiguous'
                        body['answers'][key]={'type':'choice','choice':chosen,'confidence':1.0,
                            'probabilities':{option:float(option==chosen) for option in options}}
            return JevHttpResponse(200,json.dumps(body).encode())
    wire=ExplicitPhotoWire();generation=Generation([('media','trip_photo')])
    providers=create_development_review_providers(generation=generation,input_transport=wire,
        output_transport=wire,authorized=True,decision_policy=USER_DEVELOPMENT_0_6_V2,
        input_request_limit=2,output_request_limit=2,conversation_first=True)
    value=SessionActor(SessionState('s','c'),generation,providers.review,MemoryEventJournal(100),
        RuntimeLimits(3,4,32),semantic_review=providers.semantic_review,
        decision_owner=providers.decision_owner,visual_readiness=ready())
    try:
        await value.submit(request_id='first-photo',activity_seq=1,cutoff=0,text='给我看照片。')
        state=await finish(value)
        assert [e.value for e in state.active_grants if e.kind is EffectKind.MEDIA]==['trip_photo']
        assert not state.presented_effects
        request=next(call[0] for call in wire.calls if 'contract' not in call[0]['state'])
        referent=next(item for item in request['state']['referents'] if item['referent_id']=='authored.trip_photo')
        assert referent['presentation_effect_id'] is None
        assert referent['authored_capability_id']=='mira.media.trip_photo'
        assert request['state']['context']['authored_visual_events']['trip_photo']['presented'] is False
    finally:
        await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation',[
    'unknown_identity','wrong_capability','fake_presentation','missing_catalog',
    'unavailable_asset','unknown_asset','untyped_catalog',
])
async def test_authored_identity_cannot_bypass_current_bound_readiness(mutation):
    from mira.adapters.review.jev_input import JevInputDecisionBackend
    from mira.application.decision_contracts import (
        ControlledReferent, INPUT_QUESTION_SET_AUTHORED, InputDecisionStatus,
    )
    from tests.contracts.test_decision_contracts import snapshot
    ref=ControlledReferent('authored.trip_photo','A shipped illustration, not yet shown.',
        None,'mira.media.trip_photo')
    catalog=ready()
    if mutation=='unknown_identity':ref=replace(ref,referent_id='authored.user_photo')
    if mutation=='wrong_capability':ref=replace(ref,authored_capability_id='mira.pose.camera_raise')
    if mutation=='fake_presentation':ref=replace(ref,presentation_effect_id='invented-receipt')
    if mutation=='missing_catalog':catalog=None
    if mutation in ('unavailable_asset','unknown_asset'):
        state=CapabilityState.UNAVAILABLE if mutation=='unavailable_asset' else CapabilityState.UNKNOWN
        catalog=replace(catalog,records=tuple(replace(item,state=state) if
            item.capability_id=='mira.media.trip_photo' else item for item in catalog.records))
    if mutation=='untyped_catalog':catalog={'mira.media.trip_photo':'ready'}
    original=snapshot('给我看那张插画。')
    snap=replace(original,context=replace(original.context,character_assets=catalog),referents=(ref,))
    calls=[]
    async def forbidden_transport(*args,**kwargs):
        calls.append(True)
        raise AssertionError('Invalid bound object must fail before any provider request.')
    backend=JevInputDecisionBackend(transport=forbidden_transport,model='jev-1.13.0',
        calibration_ref='synthetic-test-only',request_limit=1,
        question_set_revision=INPUT_QUESTION_SET_AUTHORED)
    result=await backend.observe(snap)
    assert result.status is InputDecisionStatus.INVALID
    assert calls==[]
    assert snap.context.presented_effects==original.context.presented_effects


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy',[False,True])
async def test_authored_first_display_semantics_are_versioned_without_inventing_exposure(legacy):
    from mira.adapters.review.jev import JevHttpResponse
    from mira.adapters.review.jev_input import JevInputDecisionBackend
    from mira.application.decision_contracts import (
        ControlledReferent, INPUT_QUESTION_SET_AUTHORED, INPUT_QUESTION_SET_V2,
        InputDecisionStatus,
    )
    from tests.contracts.test_decision_contracts import snapshot
    original=snapshot('展示那张已有的插画。')
    snap=replace(original,context=replace(original.context,character_assets=ready()),
        referents=(ControlledReferent('authored.trip_photo','Available authored illustration; not seen.',
            None,'mira.media.trip_photo'),))
    async def transport(payload,**kwargs):
        request=json.loads(payload)
        answers={}
        for key,q in request['questions'].items():
            if q['type']=='noul':
                answers[key]={'type':'noul','noul':float(key.endswith((':display_request',':referent_required')))}
            else:
                answers[key]={'type':'choice','choice':'authored.trip_photo','confidence':1.0,
                    'probabilities':{option:float(option=='authored.trip_photo') for option in q['criteria']}}
        return JevHttpResponse(200,json.dumps({'model':'jev-1.13.0','answers':answers,
            'usage':{'input_tokens':10,'output_tokens':10}}).encode())
    backend=JevInputDecisionBackend(transport=transport,model='jev-1.13.0',
        calibration_ref='synthetic-test-only',request_limit=1,
        question_set_revision=INPUT_QUESTION_SET_V2 if legacy else INPUT_QUESTION_SET_AUTHORED)
    result=await backend.observe(snap)
    assert result.status is (InputDecisionStatus.UNKNOWN if legacy else InputDecisionStatus.OBSERVED)
    assert snap.context.presented_effects==original.context.presented_effects
    assert all(item.effect.id!='authored.trip_photo' for item in snap.presentation_facts)


@pytest.mark.parametrize('authored_mode',[False,True])
def test_snapshot_owner_only_advertises_authored_identity_in_explicit_versioned_mode(authored_mode):
    from mira.application.decision_contracts import ReliableUserInput, mira26_author_policy
    from mira.application.decision_runtime import DecisionSnapshotOwner
    state=replace(SessionState('s','c'),request_id='input-1',revision=1,activity_seq=1,
        input_epoch=1,output_epoch=1,user_inputs=('看看插画。',))
    owner=DecisionSnapshotOwner(mira26_author_policy(),include_authored_referents=authored_mode)
    snap=owner.snapshot(state,(ReliableUserInput('input-1','看看插画。'),),character_assets=ready())
    assert snap is not None
    assert [item.referent_id for item in snap.referents]==(['authored.trip_photo'] if authored_mode else [])
    assert snap.presentation_facts==() and snap.context.presented_effects==()
