"""Optional character uncertainty is separate from content permission, one batch."""
import asyncio
import json

import pytest

from mira.adapters.review import jev
from mira.application.contracts import CandidateRange,EffectProposal,GenerationContext,ReviewVerdict,CharacterSemanticValue as V
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
from mira.application.choice_wire_policy import CHOICE_WIRE_POLICY_REPORTED_V2
from mira.domain.models import EffectKind
from tests.contracts.test_story_context_composition import authored_projection


def fixture():
    context=GenerationContext('一起看看窗外吧。',('一起看看窗外吧。',),(),1,character_story=authored_projection())
    candidate=CandidateRange((EffectProposal(EffectKind.SUBTITLE,'一起听雨吧。'),),'synthetic',
        affect_proposal_json='{"candidate":"happy","signal":"pleasant_shared_attention"}')
    contract=jev.JevReviewContract('synthetic-contract',jev.OUTPUT_QUESTION_SET_V4,
        jev.context_digest(context),jev.candidate_digest(candidate),(),('Reply briefly.',),
        ('MIRA is a fictional adult photographer.',),synthetic=True)
    return context,candidate,contract


class Transport:
    def __init__(self,updates=None):self.calls=[];self.updates=updates or {}
    async def __call__(self,payload,**_):
        request=json.loads(payload);self.calls.append(request);answers={}
        for key,question in request['questions'].items():
            suffix=key.rsplit(':',1)[-1]
            if question['type']=='noul':
                answers[key]={'type':'noul','noul':0 if suffix=='completed_claim_present' else .5}
            else:answers[key]={'type':'choice','choice':'allow','confidence':.85,
                'probabilities':{'allow':.9,'reject':.05,'unknown':.05}}
            if suffix in self.updates:
                if self.updates[suffix] is None:del answers[key]
                else:answers[key]=self.updates[suffix]
        return jev.JevHttpResponse(200,json.dumps({'model':'jev-1.13.0','answers':answers,
            'usage':{'input_tokens':10,'output_tokens':2}}).encode())


def observe(updates=None):
    context,candidate,contract=fixture();transport=Transport(updates)
    reviewer=jev.JevReviewBackend(transport=transport,model='jev-1.13.0',
        contract_resolver=lambda *_:contract,decision_policy=USER_DEVELOPMENT_0_6_V2,
        request_limit=1,question_set_revision=jev.OUTPUT_QUESTION_SET_V4,
        choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2)
    # Keep this synchronous helper from replacing pytest-asyncio's policy loop.
    with asyncio.Runner(loop_factory=asyncio.new_event_loop) as runner:
        result=runner.run(reviewer.review(context,candidate))
    assert len(transport.calls)==1
    return result,context,candidate


def test_story_unknown_does_not_turn_allowed_ordinary_text_into_rejection():
    result,context,candidate=observe()
    assert result.verdict is ReviewVerdict.ALLOW
    evidence=result.character_evidence
    assert evidence.context_digest==jev.context_digest(context)
    assert evidence.candidate_digest==jev.candidate_digest(candidate)
    assert evidence.willingness is V.UNKNOWN and evidence.refusal is V.UNKNOWN
    assert evidence.affect_supported is V.YES


@pytest.mark.parametrize('probability,label',[(.5999,V.UNKNOWN),(.6,V.YES),(.6001,V.YES),(.4,V.NO)])
def test_character_noul_threshold_uses_original_value(probability,label):
    result,_,_=observe({'story_willingness':{'type':'noul','noul':probability}})
    assert result.character_evidence.willingness is label


def test_strong_refusal_is_separate_evidence_and_never_willingness():
    result,_,_=observe({'story_refusal':{'type':'noul','noul':.95},
                        'story_willingness':{'type':'noul','noul':.05}})
    assert result.verdict is ReviewVerdict.ALLOW
    assert result.character_evidence.refusal is V.YES
    assert result.character_evidence.willingness is V.NO


def test_weak_affect_reject_holds_affect_without_rejecting_chat():
    result,_,_=observe({'affect_supported':{'type':'choice','choice':'reject','confidence':.4,
        'probabilities':{'allow':.2,'reject':.7,'unknown':.1}}})
    assert result.verdict is ReviewVerdict.ALLOW and result.character_evidence.affect_supported is V.UNKNOWN


def test_hard_content_reject_still_rejects_with_positive_story_answers():
    result,_,_=observe({'o1':{'type':'choice','choice':'reject','confidence':.9,
        'probabilities':{'allow':.02,'reject':.95,'unknown':.03}},
        'story_willingness':{'type':'noul','noul':1}})
    assert result.verdict is ReviewVerdict.REJECT


@pytest.mark.parametrize('answer',[None,{'type':'noul','noul':float('nan')},{'type':'noul','noul':True},
                                  {'type':'noul','noul':1,'execute':'now'}])
def test_malformed_character_answer_is_contract_error_not_soft_semantic_unknown(answer):
    result,_,_=observe({'story_willingness':answer})
    assert result.verdict is ReviewVerdict.UNKNOWN
    assert result.reason_code=='jev_response_contract_invalid'
    assert result.character_evidence is None and result.response_diagnostics is not None
