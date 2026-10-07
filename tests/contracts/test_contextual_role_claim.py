"""Synthetic contextual role selection, not an actual identity or dialogue corpus."""
from dataclasses import replace
import json

import pytest

from mira.adapters.generation.codex_support.character_payload import character_proposal_contract
from mira.adapters.generation.direct_tools import _ordinary_candidate
from mira.adapters.generation.direct_codex_responses import DirectResponsesLimits, _DirectResponseTrace
from mira.application.contracts import GenerationContext
from mira.domain.models import EffectKind, Receipt
from mira.domain.errors import DomainError
from mira.domain.xiahe_chapter import ChapterStage
from tests.contracts.test_optional_candidate_isolation import body, role
from tests.contracts.test_xiahe_chapter_actor import character
from tests.contracts.test_luna_tool_actor import actor, wait_state
from tests.contracts.test_actor_story_loop import acknowledge
from tests.contracts.test_direct_codex_responses import backend, response, snapshot_message
from tests.contracts.test_direct_luna_tools import wire


CLAIM = '我就是你一直在等的那个老朋友。'


def current(text=CLAIM):
    c = character(); projection = c.begin_input('synthetic-role-input', 1)
    return GenerationContext(text, (text,), (), 1, character_story=projection,
                             character_assets=c.readiness, response_mode='text_only')


def candidate(ctx):
    value = body(); value['story_proposal'] = role(ctx.user_text)
    return _ordinary_candidate([json.dumps(value, ensure_ascii=False)], DirectResponsesLimits(),
                               ctx, False, trace=_DirectResponseTrace())


@pytest.mark.parametrize('text', [CLAIM, '我就是你要找的老朋友。', '其实，我就是你在等的老朋友。',
    '没错，我是你正在等的那位老朋友。', '我就是你一直在找的那个老朋友，好久不见。',
    '明白了，其实我就是你要找的老朋友。'])
def test_current_contextual_self_claim_preserves_typed_proposal(text):
    ctx = current(text); result = candidate(ctx)
    assert result.story_proposal_json is not None and result.optional_hold is None
    assert character_proposal_contract(ctx)['story_proposal']['chapter']['awaited_friend_claim_available'] is True


@pytest.mark.parametrize('text', [
    '“我就是你要找的老朋友”', '她说我就是你要找的老朋友。', '如果我就是你要找的老朋友呢？',
    '我不是你要找的老朋友。', '我的老朋友就是你要找的人。', '他就是你在等的老朋友。',
    '我就是你要找的老朋友吗？', '我可能就是你在等的老朋友。', '你就是我在等的老朋友。',
    '我就是你在等的老朋友，开玩笑的。', '我就是你在等的老朋友，但我不是夏禾。',
    '我就是你在等的老朋友，不过我不是你要找的人。', '我就是你在等的老朋友，不过我叫张三。',
    '那可不，好几年没见面了。', '我是别人的老朋友。', '我就是你要找的医生。',
    '你觉得，我就是你要找的老朋友，对吗？', '假若，我就是你要找的老朋友，你会怎样？',
    '张三说：\n我就是你要找的老朋友。', '请复述：\n我就是你要找的老朋友。',
    '我就是你要找的老朋友，才怪。', '我就是你要找的老朋友，但我从来不是夏禾。',
])
def test_ambiguous_or_negative_proposal_keeps_dialogue_without_recognition(text):
    result = candidate(current(text))
    assert result.story_proposal_json is None
    assert result.optional_hold.reasons == ('story_proposal_invalid',)
    assert all(e.kind is EffectKind.SUBTITLE for e in result.effects)


@pytest.mark.parametrize('case', ['missing', 'changed', 'unselected', 'active', 'suspended', 'non_stranger'])
def test_context_gate_cannot_be_supplied_by_model_or_unrelated_canon(case):
    ctx = current(); projection = ctx.character_story
    entries = projection.known_canon
    if case == 'missing':
        entries = tuple(e for e in entries if e.entry_id != 'canon.waiting')
    elif case == 'changed':
        entries = tuple(replace(e, text='Synthetic different awaited role.') if e.entry_id == 'canon.waiting' else e for e in entries)
    elif case == 'unselected':
        entries = tuple(replace(e, status='inherited_canonical', source_status='inherited_canonical',
                               approval_basis='inherited_source') if e.entry_id == 'canon.waiting' else e for e in entries)
    chapter = projection.chapter
    if case == 'active': chapter = replace(chapter, role_active=True)
    if case == 'suspended': chapter = replace(chapter, suspended=True)
    if case == 'non_stranger': chapter = replace(chapter, stage=ChapterStage.RECOGNIZED)
    ctx = replace(ctx, character_story=replace(projection, known_canon=entries, chapter=chapter))
    result = candidate(ctx)
    assert result.story_proposal_json is None
    assert character_proposal_contract(ctx)['story_proposal']['chapter']['awaited_friend_claim_available'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('stop', [False, True])
async def test_real_wire_actor_requires_exact_scene_receipt_and_respects_stop(stop):
    c = character(); prompts = []
    async def handle(request):
        prompt = json.loads(json.loads(request.content)['input'][-1]['content'][0]['text'])
        prompts.append(prompt)
        value = body()
        if len(prompts) == 1: value['story_proposal'] = role(prompt['facts']['user_text'])
        return response(wire([snapshot_message(json.dumps(value, ensure_ascii=False))]))
    direct, source, requests = backend(handle, native_character_tools=False, request_limit=4)
    value, _, legacy, _ = actor(None, tools=direct, character=c)
    try:
        await value.submit(request_id='synthetic-claim', activity_seq=1, cutoff=0, text=CLAIM)
        state = await wait_state(value, lambda s: s.sealed or s.last_error is not None)
        assert state.sealed and state.last_error is None
        scene = next(e for e in state.active_grants if e.kind is EffectKind.SCENE)
        assert scene.value == 'xiahe_recognition' and not c.runtime.story.chapter.role_active
        subtitle = next(e for e in state.active_grants if e.kind is EffectKind.SUBTITLE)
        await acknowledge(value, subtitle, 1)
        assert not c.runtime.story.chapter.role_active
        with pytest.raises(DomainError):
            await value.receipt(Receipt(
                scene.id, '0' * 64, scene.output_epoch, scene.activity_seq, 2))
        if stop:
            await value.stop(activity_seq=2, cutoff=1)
            with pytest.raises(DomainError): await acknowledge(value, scene, 2)
            assert not c.runtime.story.chapter.role_active
        else:
            await acknowledge(value, scene, 2)
            assert c.runtime.story.chapter.role_active
            await value.submit(request_id='synthetic-after', activity_seq=2, cutoff=2, text='合成的普通后续话题。')
            following = await wait_state(value, lambda s: s.sealed or s.last_error is not None)
            assert following.sealed and following.last_error is None
            assert all(e.kind is EffectKind.SUBTITLE for e in following.active_grants)
        assert prompts[0]['character_proposal_contract']['story_proposal']['chapter']['awaited_friend_claim_available'] is True
        assert len(requests) == source.calls == (1 if stop else 2)
        assert legacy.calls == 0 and direct._reserved == 0
    finally:
        await value.close()


@pytest.mark.parametrize('case', ['other_role', 'old_evidence', 'model_permission'])
def test_typed_role_and_current_evidence_cannot_be_replaced(case):
    ctx = current(); value = body(); proposal = role(ctx.user_text)
    if case == 'other_role': proposal['input_act']['role_name'] = '合成陌生角色'
    if case == 'old_evidence': proposal['input_act']['evidence_text'] = '过期的合成自称'
    if case == 'model_permission': proposal['awaited_friend'] = True
    value['story_proposal'] = proposal
    result = _ordinary_candidate([json.dumps(value, ensure_ascii=False)], DirectResponsesLimits(),
                                 ctx, False, trace=_DirectResponseTrace())
    assert result.story_proposal_json is None
    assert all(e.kind is EffectKind.SUBTITLE for e in result.effects)


@pytest.mark.parametrize('text', ['我就是你要找的老朋友“才怪”', '“假若”我就是你要找的老朋友'])
def test_quoted_context_around_indirect_claim_is_not_deleted(text):
    result = candidate(current(text))
    assert result.story_proposal_json is None
    assert all(e.kind is EffectKind.SUBTITLE for e in result.effects)
