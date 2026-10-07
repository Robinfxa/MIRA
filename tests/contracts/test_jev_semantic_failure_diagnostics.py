"""Well-formed semantic failures remain observable even without confidence warnings."""
import json
from dataclasses import asdict, replace
import pytest
from mira.adapters.review.jev import JevReviewBackend, OUTPUT_QUESTION_SET_V3
from mira.application.choice_wire_policy import CHOICE_WIRE_POLICY_REPORTED_V2
from mira.application.contracts import ReviewVerdict
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
from tests.contracts.test_jev_completion_applicability_v3 import OutputTransport, choice
from tests.contracts.test_jev_review import MODEL, contract_for, inputs


@pytest.mark.asyncio
@pytest.mark.parametrize('label,probability,expected', [
    ('allow',0.6,ReviewVerdict.UNKNOWN),('reject',0.8,ReviewVerdict.REJECT),
])
async def test_shape_valid_nonallow_retains_numeric_facts_without_mismatch_warning(label,probability,expected):
    context,candidate=inputs()
    contract=replace(contract_for(context,candidate),policy_revision=OUTPUT_QUESTION_SET_V3)
    transport=OutputTransport(applicability=0.0,choices={'o6':choice(label,probability)})
    backend=JevReviewBackend(transport=transport,model=MODEL,contract_resolver=lambda *_:contract,
        decision_policy=USER_DEVELOPMENT_0_6_V2,question_set_revision=OUTPUT_QUESTION_SET_V3,
        choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2,request_limit=1)
    result=await backend.review(context,candidate)
    assert result.verdict==expected
    assert result.response_diagnostics is not None
    facts=result.response_diagnostics.answer_facts
    assert not any(fact.confidence_mismatch_warning for fact in facts)
    target=next(fact for fact in facts if fact.question_suffix=='o6')
    assert target.choice==label and target.selected_probability==probability
    assert len(transport.calls)==1
    safe=json.dumps(asdict(result.response_diagnostics))
    assert context.user_text not in safe and candidate.fixture_id not in safe
