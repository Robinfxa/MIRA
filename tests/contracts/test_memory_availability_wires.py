"""Actual direct and JEV request serialization with synthetic transports only."""
import json
from dataclasses import replace

import pytest

from mira.application.contracts import CandidateRange, EffectProposal, ReviewVerdict
from mira.application.decision_contracts import ResponseContractProducer, SemanticValue
from mira.domain.models import EffectKind
from tests.contracts.test_actor_memory_recall import valid_past_line
from tests.contracts.test_personal_memory_projection import archive, context, empty_manual, input_record
from tests.contracts.test_direct_codex_responses import (
    ResponsesRoute, backend as direct_backend, collect, response, item_done, completed,
)
from tests.contracts.test_jev_review import (
    backend as review_backend, SyntheticTransport, input_observation, decision_snapshot, jev_module,
)


@pytest.mark.asyncio
@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('kind', ['manual', 'archive'])
@pytest.mark.parametrize('mode', ['absent', 'empty', 'attached', 'unavailable'])
async def test_direct_and_snapshot_jev_preserve_only_available_memory(route, kind, mode):
    marker = 'SYNTHETIC_UNAVAILABLE_SOURCE_MUST_NOT_TRAVEL'
    source = 'memory_evidence' if kind == 'manual' else 'conversation_recall'
    packet = (replace(empty_manual(), past_candidates=(valid_past_line(marker),))
              if kind == 'manual' else archive((input_record(marker),)))
    if mode == 'empty':
        packet = empty_manual() if kind == 'manual' else archive()
    fields = {} if mode == 'absent' else {
        ('memory_packet' if kind == 'manual' else 'conversation_recall'): packet}
    if mode == 'unavailable':
        fields['memory_recall_status' if kind == 'manual' else 'conversation_recall_status'] = 'unavailable'
    value = context(**fields)
    raw_reply = json.dumps({'effects': [{'kind': 'subtitle', 'value': '我们继续聊。'}]}, ensure_ascii=False)
    async def handle(_request):
        return response(item_done(raw_reply) + completed())
    direct, _, requests = direct_backend(handle, route=route)
    candidates = await collect(direct, value)
    assert len(candidates) == 1 and candidates[0].effects[0].value == '我们继续聊。'
    body = json.loads(requests[0].content)
    direct_facts = json.loads(body['input'][0]['content'][0]['text'])['facts']

    # Exercise the actual response-contract snapshot, not merely a dictionary view.
    snap = decision_snapshot(value.user_text)
    review_context = replace(snap.context, **fields)
    snap = replace(snap, context=review_context)
    proposal = CandidateRange((EffectProposal(EffectKind.POSE, 'camera_lowered'),), 'candidate-1')
    observation = input_observation(snap, speech=SemanticValue.NO, display=SemanticValue.NO)
    contract = ResponseContractProducer().produce(review_context, proposal, snapshot=snap, observation=observation)
    assert contract is not None
    wire = SyntheticTransport()
    reviewer = review_backend(wire, resolver=lambda *_: jev_module.map_response_contract(contract))
    result = await reviewer.review_detailed(review_context, proposal)
    assert result.observation.verdict is ReviewVerdict.ALLOW and len(wire.calls) == 1
    state = wire.calls[0]['state']
    for facts in (direct_facts, state['context'], state['contract']['snapshot']['context']):
        assert (source in facts) is (mode in ('empty', 'attached'))
        assert (marker in json.dumps(facts)) is (mode == 'attached')
        if mode == 'unavailable':
            assert facts['memory_recall_status' if kind == 'manual' else 'conversation_recall_status'] == 'unavailable'
    assert (marker in requests[0].content.decode()) is (mode == 'attached')
    assert (marker in json.dumps(wire.calls[0])) is (mode == 'attached')
    assert body['store'] is False and 'tools' not in body
