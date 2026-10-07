"""Suggestions cannot smuggle execution IDs or alter legacy effect payloads."""
import json

import pytest

from mira.application.contracts import CandidateRange,EffectProposal,GenerationContext,candidate_data
from mira.domain.models import EffectKind
from mira.adapters.generation.codex_support.character_payload import parse_character_candidate,offered_id
from mira.adapters.generation.codex_support.types import CodexLimits,CodexGenerationError
from tests.contracts.test_story_context_composition import authored_projection


def context():
    return GenerationContext('Would you like to look at rain?',('Would you like to look at rain?',),(),1,
        character_story=authored_projection())


def test_no_proposal_keeps_exact_legacy_candidate_wire():
    value=CandidateRange((EffectProposal(EffectKind.SUBTITLE,'Hello'),),'synthetic')
    assert candidate_data(value)=={'effects':({'kind':EffectKind.SUBTITLE,'value':'Hello'},),'fixture_id':'synthetic'}


def test_exact_story_and_affect_suggestions_remain_separate_data():
    ctx=context()
    raw={'effects':[{'kind':'subtitle','value':'一起看看窗外的雨吗？'}],
        'story_proposal':{'transition_id':'t.offer','signal':'offer_rain','offer_id':offered_id(ctx),
                          'draft_cue':'一起看看窗外的雨吗？'},
        'affect_proposal':{'candidate':'happy','signal':'pleasant_shared_attention'}}
    effects,story,affect=parse_character_candidate([json.dumps(raw)],CodexLimits(),ctx,speech_enabled=False)
    assert len(effects)==1 and effects[0].kind is EffectKind.SUBTITLE
    result=candidate_data(CandidateRange(effects,'synthetic',story,affect))
    assert result['story_proposal']==raw['story_proposal']
    assert result['affect_proposal']==raw['affect_proposal']


@pytest.mark.parametrize('field,proposal',[
    ('story_proposal',{'transition_id':'t.offer','signal':'offer_rain','offer_id':'invented'}),
    ('story_proposal',{'transition_id':'t.yes','signal':'accept_raincoat','offer_id':'invented',
                       'target_capabilities':['mira.outfit.amber_raincoat']}),
    ('story_proposal',{'transition_id':'t.chat','signal':'chat','grant_id':'pretend-grant'}),
    ('affect_proposal',{'candidate':'shy','signal':'personal_attention','confidence':1}),
    ('affect_proposal',{'candidate':'shy','signal':'personal_attention','evidence_input_ids':['invented']}),
    ('affect_proposal',{'candidate':'shy','signal':'personal_attention','canon_reason_id':'hidden-canon'}),
])
def test_unknown_authority_fields_or_unbound_offer_are_rejected(field,proposal):
    raw={'effects':[{'kind':'subtitle','value':'Hello'}],field:proposal}
    with pytest.raises(CodexGenerationError):
        parse_character_candidate([json.dumps(raw)],CodexLimits(),context(),speech_enabled=False)


def test_suggestions_are_rejected_when_story_mode_is_not_admitted():
    raw={'effects':[{'kind':'subtitle','value':'Hello'}],
         'affect_proposal':{'candidate':'happy','signal':'pleasant_shared_attention'}}
    with pytest.raises(CodexGenerationError):
        parse_character_candidate([json.dumps(raw)],CodexLimits(),GenerationContext('hi',('hi',),(),1))
