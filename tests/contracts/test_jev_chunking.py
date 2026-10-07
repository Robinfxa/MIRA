"""Exact fake JEV wire; no provider credentials/network or semantic-quality claims."""
import json
from copy import deepcopy

import pytest

from mira.adapters.review.jev import JevHttpResponse
from mira.adapters.review.jev_chunking import JevBoundaryBackend
from mira.application.semantic_chunking import make_request
from tests.contracts.test_semantic_chunking import CONTEXT, Source


class Wire:
    def __init__(self, mutate=None): self.calls = []; self.mutate = mutate
    async def __call__(self, payload, **kwargs):
        request = json.loads(payload); self.calls.append(request)
        key, question = next(iter(request['questions'].items()))
        options = list(question['criteria']); choice = options[-2]
        doc = {'model': request['model'], 'answers': {key: {'type': 'choice', 'choice': choice,
            'confidence': .7, 'probabilities': {option: (1 if option == choice else 0) for option in options}}},
            'usage': {'input_tokens': 100, 'output_tokens': 10}}
        if self.mutate is not None: doc = self.mutate(doc, key)
        return JevHttpResponse(200, doc if type(doc) is bytes else json.dumps(doc).encode())


@pytest.mark.asyncio
async def test_jev_selects_exact_application_partition_without_grading_text_or_permissions():
    request, wire = make_request(CONTEXT, Source().candidate), Wire()
    result = await JevBoundaryBackend(transport=wire, request_limit=1).choose(request)
    assert result.plan_id == request.plans[-1].plan_id
    sent = wire.calls[0]
    assert sent['state']['text'] == request.text
    assert len(sent['questions']) == 1
    question = next(iter(sent['questions'].values()))
    assert 'do not grade truth' in question['instructions']['question']
    assert set(question['criteria']) == {p.plan_id for p in request.plans} | {'unknown'}


@pytest.mark.asyncio
async def test_boundary_budget_defaults_to_zero_and_attempts_never_retry():
    request, wire = make_request(CONTEXT, Source().candidate), Wire()
    assert (await JevBoundaryBackend(transport=wire).choose(request)).plan_id is None
    backend = JevBoundaryBackend(transport=wire, request_limit=1)
    await backend.choose(request); assert (await backend.choose(request)).plan_id is None
    assert len(wire.calls) == 1


def mutation(mode):
    def alter(doc, key):
        answer = doc['answers'][key]
        if mode == 'model': doc['model'] = 'jev-0.0.0'
        elif mode == 'binding': doc['answers']['foreign'] = doc['answers'].pop(key)
        elif mode == 'extra': doc['answers']['foreign'] = deepcopy(answer)
        elif mode == 'rewrite': answer['text'] = 'rewritten'
        elif mode == 'offset': answer['choice'] = 17
        elif mode == 'unknown': answer['choice'] = 'unknown'
        elif mode == 'confidence': answer['confidence'] = .5
        elif mode == 'bool': answer['confidence'] = True
        elif mode == 'nan': answer['confidence'] = float('nan')
        elif mode == 'huge': answer['confidence'] = 10 ** 400
        elif mode == 'probability': answer['probabilities'][answer['choice']] = .1
        elif mode == 'missing': answer['probabilities'].pop('unknown')
        elif mode == 'maximum':
            answer['probabilities']['unknown'] = .9
            answer['probabilities'][answer['choice']] = .1
        elif mode == 'usage': doc['usage']['input_tokens'] = True
        elif mode == 'duplicate': return b'{"model":"jev-1.13.0","model":"jev-1.13.0"}'
        elif mode == 'oversize': return b'x' * 17000
        elif mode == 'utf8': return b'\xff'
        return doc
    return alter


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['model', 'binding', 'extra', 'rewrite', 'offset', 'unknown',
    'confidence', 'bool', 'nan', 'huge', 'probability', 'missing', 'maximum', 'usage',
    'duplicate', 'oversize', 'utf8'])
async def test_invalid_or_uncertain_wire_keeps_the_original_tail(mode):
    request, wire = make_request(CONTEXT, Source().candidate), Wire(mutation(mode))
    result = await JevBoundaryBackend(transport=wire, request_limit=1).choose(request)
    assert result.plan_id is None and len(wire.calls) == 1


@pytest.mark.asyncio
async def test_replayed_answer_cannot_bind_to_next_attempt():
    wire = Wire(); captured = []
    async def replay(payload, **kwargs):
        if not captured: captured.append(await wire(payload, **kwargs))
        return captured[0]
    backend = JevBoundaryBackend(transport=replay, request_limit=2)
    request = make_request(CONTEXT, Source().candidate)
    assert (await backend.choose(request)).plan_id is not None
    assert (await backend.choose(request)).plan_id is None
