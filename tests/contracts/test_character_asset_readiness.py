import json
from dataclasses import replace

import pytest

from mira.application.actor_story import SessionCharacterRuntime
from mira.application.contracts import GenerationContext,CandidateRange,EffectProposal
from mira.application.story import StoryRuntime
from mira.bootstrap.character_story import builtin_definition
from mira.domain.models import EffectKind
from mira.domain.story import ReadinessCatalog
from mira.domain.story import CapabilityRecord, CapabilityState
from mira.domain.errors import DomainError


def context_and_runtime():
    catalog=ReadinessCatalog('nothing-registered')
    runtime=SessionCharacterRuntime(StoryRuntime(builtin_definition(),'synthetic-scope'),catalog)
    projection=runtime.begin_input('input-1',1)
    return GenerationContext('chat',('chat',),(),1,character_story=projection,character_assets=catalog),runtime


@pytest.mark.parametrize('value',['emotion_normal','emotion_guarded','emotion_happy','emotion_shy','accessory_star_clip','accessory_camera_clip'])
def test_unavailable_optional_character_control_is_not_presented_as_a_label(value):
    context,runtime=context_and_runtime()
    text=EffectProposal(EffectKind.SUBTITLE,'我们接着聊。')
    candidate=CandidateRange((text,EffectProposal(EffectKind.POSE,value)),'synthetic')
    result=runtime.prepare_candidate(context,candidate,'input-1')
    assert result.effects==(text,)
    only=replace(candidate,effects=(candidate.effects[1],))
    with pytest.raises(DomainError,match='No available'):
        runtime.prepare_candidate(context,only,'input-1')


def test_changed_asset_catalog_invalidates_captured_character_context():
    context,runtime=context_and_runtime()
    runtime.readiness=ReadinessCatalog('new-registration')
    with pytest.raises(DomainError,match='changed'):
        runtime.ensure_definition(context)


def test_explicit_unavailable_legacy_pose_is_removed_before_review_without_losing_text():
    context,runtime=context_and_runtime()
    catalog=ReadinessCatalog('selected-renderer-v1',(
        CapabilityRecord('mira.face.warm',CapabilityState.UNAVAILABLE),))
    runtime.readiness=catalog
    context=replace(context,character_assets=catalog)
    text=EffectProposal(EffectKind.SUBTITLE,'我们继续聊。')
    pose=EffectProposal(EffectKind.POSE,'face_warm')
    result=runtime.prepare_candidate(context,CandidateRange((text,pose),'synthetic'),'input-1')
    assert result.effects == (text,)
    with pytest.raises(DomainError,match='No available'):
        runtime.prepare_candidate(context,CandidateRange((pose,),'synthetic'),'input-1')


def test_unregistered_legacy_renderer_keeps_its_existing_pose_contract():
    context,runtime=context_and_runtime()
    pose=EffectProposal(EffectKind.POSE,'face_warm')
    assert runtime.prepare_candidate(context,CandidateRange((pose,),'synthetic'),'input-1').effects==(pose,)
