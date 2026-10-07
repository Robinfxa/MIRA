"""Private evaluation diagnostics use v2 facts and bounded numeric operations."""
import json
import pytest
from tools import jev_evaluation_support as support
from mira.adapters.review.jev import JevHttpResponse


@pytest.mark.parametrize('value',[10**400,-(10**400),float('inf')])
def test_probability_diagnostics_never_overflow_on_invalid_numeric_input(value):
    assert support._bounded_probability(value) is False


def test_v2_required_referent_probability_is_observable_without_unknown_strings():
    payload=json.dumps({'questions':{'synthetic:referent_required':{'type':'noul'}}}).encode()
    response=JevHttpResponse(200,json.dumps({'model':'jev-1.13.0','answers':{
        'synthetic:referent_required':{'type':'noul','noul':0.1,'private':'DO_NOT_KEEP_9245'}},
        'usage':{'input_tokens':1,'output_tokens':1}}).encode())
    result=support.safe_response_diagnostics(response,payload,'input',ValueError('noul_shape'))
    assert result['answer_facts'][0]['suffix']=='referent_required'
    assert result['answer_facts'][0]['noul_probability']==0.1
    assert 'DO_NOT_KEEP_9245' not in json.dumps(result)
