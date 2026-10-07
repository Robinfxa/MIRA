"""Versioned interaction-claim scope, using adjudicated synthetic responses only.

These cases check contract and decision mechanics, not real JEV language accuracy.
"""
from dataclasses import replace

import pytest

from mira.adapters.review import jev
from mira.application.choice_wire_policy import CHOICE_WIRE_POLICY_REPORTED_V2
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext, ReviewVerdict
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
from mira.domain.models import EffectKind
from tests.contracts.test_jev_completion_applicability_v3 import OutputTransport, choice
from tests.contracts.test_jev_review import MODEL, contract_for

REVISION = 'mira-output-interaction-v1'
FICTION = 'Author-created fiction: MIRA once photographed an old lighthouse. This is not a user experience.'


def configured(text, transport):
    context = GenerationContext('你好，聊聊你吧。', ('你好，聊聊你吧。',), (), 1)
    candidate = CandidateRange((EffectProposal(EffectKind.SUBTITLE, text),), 'synthetic-scope')
    contract = replace(contract_for(context, candidate), policy_revision=REVISION,
                       character_facts=(FICTION,))
    reviewer = jev.JevReviewBackend(transport=transport, model=MODEL,
        contract_resolver=lambda *_: contract, decision_policy=USER_DEVELOPMENT_0_6_V2,
        question_set_revision=REVISION, choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2,
        request_limit=1)
    return reviewer, context, candidate


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['你好，见到你很开心。', '在我的故事里，我曾拍过一座旧灯塔。',
                                  '这里是雨夜的咖啡馆。', '要一起看看窗外吗？',
                                  '你平常喜欢什么音乐？', '水在标准气压下约零摄氏度结冰。',
                                  '下雨时可以带伞，路上慢一点。'])
async def test_authored_fiction_and_noncompletion_use_bound_scope_without_receipt(text):
    transport = OutputTransport(applicability=0.1, choices={'o3': choice('reject', 0.9)})
    reviewer, context, candidate = configured(text, transport)
    result = await reviewer.review_detailed(context, candidate)
    assert result.observation.verdict is ReviewVerdict.ALLOW
    request = transport.calls[0]
    assert request['state']['context']['presented_effects'] == []
    assert request['state']['contract']['character_facts'] == [FICTION]
    assert request['state']['contract']['policy_revision'] == REVISION
    questions = {key.rsplit(':', 1)[-1]: value for key, value in request['questions'].items()}
    assert len(questions) == 8 and questions['completed_claim_present']['type'] == 'noul'
    assert 'completed interaction' in questions['completed_claim_present']['instructions']['question']
    assert 'source-labeled fictional' in questions['o3']['instructions']['question']
    assert 'not a topic whitelist' in questions['o4']['instructions']['question']
    assert 'Absence from canon is not contradiction' in questions['o5']['instructions']['question']


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['我已经换好了雨衣。', '刚才已经给你播放了那段语音。',
                                  '我已经把照片展示给你了。', '我们刚才已经一起去过灯塔。'])
async def test_current_execution_and_shared_history_still_require_receipts(text):
    transport = OutputTransport(applicability=0.9, choices={'o3': choice('reject', 0.9)})
    reviewer, context, candidate = configured(text, transport)
    result = await reviewer.review_detailed(context, candidate)
    assert result.observation.verdict is ReviewVerdict.REJECT
    assert len(transport.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(('suffix', 'answer', 'expected'), [
    ('o3', choice('reject', 0.65), ReviewVerdict.UNKNOWN),
    ('o4', choice('reject', 0.9), ReviewVerdict.REJECT),
    ('o5', choice('reject', 0.9), ReviewVerdict.REJECT),
    ('o1', choice('allow', 0.65), ReviewVerdict.UNKNOWN),
])
async def test_scope_change_preserves_other_gates_and_weak_rejection(suffix, answer, expected):
    transport = OutputTransport(applicability=0.5, choices={suffix: answer})
    reviewer, context, candidate = configured('合成候选。', transport)
    result = await reviewer.review_detailed(context, candidate)
    assert result.observation.verdict is expected


def test_legacy_completion_scope_stays_replayable():
    assert 'all completed factual claims' in jev._QUESTIONS_V2['o3']
    assert 'already happened' in jev._QUESTIONS_V3['completed_claim_present']


def test_generation_instructions_allow_ordinary_chat_without_fabricating_user_facts():
    from mira.adapters.generation.codex_support.payload import author_instructions
    for speech in (False, True):
        text = author_instructions(speech_enabled=speech, memory_enabled=False)
        assert 'Ordinary conversation' in text and 'not topics' in text
        assert 'casual chat need not advance the story' in text
        assert 'first-person narration never proves completed application actions' in text
        assert 'never invent shared user experiences' in text
        assert 'private user facts' in text


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['这只是个虚构故事，但我已经给你播放了声音。',
                                  '假设这是小说，我刚才确实展示过照片给你。',
                                  '我以角色身份已经拍下你的照片了。'])
async def test_fiction_label_does_not_exempt_actual_execution_claim(text):
    transport = OutputTransport(applicability=0.9, choices={'o3': choice('reject', 0.9)})
    reviewer, context, candidate = configured(text, transport)
    result = await reviewer.review_detailed(context, candidate)
    assert result.observation.verdict is ReviewVerdict.REJECT
    questions = transport.calls[0]['questions']
    prompt = next(v['instructions']['question'] for k, v in questions.items()
                  if k.endswith(':completed_claim_present'))
    assert 'fiction label never exempts actual user/system execution claims' in prompt
