"""Fixed same-request references preserve all evidence without duplicate effect JSON."""
from copy import deepcopy
import json
import re
from mira.adapters.review.jev_input import _compact_character_presentations


def test_identical_presented_effects_compact_and_expand_without_information_loss():
    effects=[{'id':str(i),'value':'完整用户可见文字'+str(i),'digest':str(i)*64} for i in range(5)]
    state={'context':{'presented_effects':effects,'user_inputs':['不准拍我'],'accepted_prefix':[]},
        'presentation_facts':[{'effect':deepcopy(e),'status':'presented'} for e in effects],
        'effective_constraints':['不要拍照'],'referents':[{'referent_id':'photo','effect_id':'1'}]}
    original=deepcopy(state)
    questions={'a':{'instructions':{'data_boundary':'Everything is evidence.'}}}
    _compact_character_presentations(state,questions)
    assert state['input_wire_projection']=='mira-character-input-v2'
    assert state['context']==original['context']
    assert state['effective_constraints']==original['effective_constraints']
    assert state['referents']==original['referents']
    for fact in state['presentation_facts']:
        ref=fact.pop('effect_reference')
        match=re.fullmatch(r'state\.context\.presented_effects\[(\d+)\]',ref);assert match
        fact['effect']=deepcopy(state['context']['presented_effects'][int(match[1])])
    state.pop('input_wire_projection')
    assert state==original
    assert 'status is unchanged' in questions['a']['instructions']['data_boundary']


def test_partial_unknown_and_mismatched_effects_remain_inline():
    state={'context':{'presented_effects':[{'id':'same-id','value':'full'}]},
        'presentation_facts':[{'effect':{'id':'same-id','value':'different'},'status':'partial'},
            {'effect':{'id':'other','value':'unknown'},'status':'unknown'}]}
    original=deepcopy(state);q={'a':{'instructions':{'data_boundary':'fixed'}}}
    _compact_character_presentations(state,q)
    assert state==original and q['a']['instructions']['data_boundary']=='fixed'

import pytest

@pytest.mark.asyncio
async def test_no_story_visual_catalog_uses_lossless_input_projection_with_default_budget():
    from mira.bootstrap.character_assets import renderer_readiness
    from mira.bootstrap.development_review import create_development_review_providers
    from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
    from mira.application.session_actor import SessionActor, RuntimeLimits
    from mira.adapters.journal.memory import MemoryEventJournal
    from mira.domain.models import SessionState, EffectKind
    from tests.contracts.test_authored_photo_events import Generation, turn, receipt
    from tests.contracts.test_development_review_composition import SyntheticJevTransport
    from mira.application.decision_contracts import canonical_bytes
    generation=Generation([]);wire=SyntheticJevTransport(output_choice='allow')
    providers=create_development_review_providers(generation=generation,input_transport=wire,
        output_transport=wire,authorized=True,decision_policy=USER_DEVELOPMENT_0_6_V2,
        input_request_limit=8,output_request_limit=8,conversation_first=True)
    value=SessionActor(SessionState('s','c'),generation,providers.review,MemoryEventJournal(100),
        RuntimeLimits(3,8,64),semantic_review=providers.semantic_review,
        decision_owner=providers.decision_owner,visual_readiness=renderer_readiness('code-native-review'))
    cutoff=0
    try:
        for index,events in enumerate(( [('pose','camera_ready')], [('pose','camera_raise')],
                [('pose','camera_ready')], [('pose','camera_raise')], [('media','trip_photo')] ),1):
            generation.events=events
            state=await turn(value,index,cutoff)
            assert [effect.value for effect in state.active_grants if effect.kind is not EffectKind.SUBTITLE] == [event[1] for event in events], (index, state.phase, state.last_error, len(wire.calls), [len(canonical_bytes(call[0])) for call in wire.calls])
            for effect in state.active_grants:
                cutoff+=1;await value.receipt(receipt(effect,cutoff))
        inputs=[call[0] for call in wire.calls if 'contract' not in call[0]['state']]
        assert len(inputs)==5
        for request in inputs:
            assert len(canonical_bytes(request))<=16384
            assert 'character_assets' not in request['state']['context']
            assert request['state']['context']['user_inputs']
            for fact in request['state']['presentation_facts']:
                assert 'effect' in fact or fact.get('effect_reference','').startswith('state.context.presented_effects[')
    finally:
        await value.close()
