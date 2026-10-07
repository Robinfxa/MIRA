"""Synthetic semantic-boundary mechanics, not model-quality or live-voice evidence."""
import asyncio
from dataclasses import replace

import pytest

from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext
from mira.application.semantic_chunking import SemanticChunkingGeneration
from mira.domain.models import EffectKind

TEXT = '窗外的雨停了一会儿。 我把相机放在桌边。 你可以慢慢说。 我会在这里听着。'
CONTEXT = GenerationContext('聊聊', ('聊聊',), (), 1)


class Source:
    def __init__(self, text=TEXT, *, speech=False, extra=(), story=None):
        self.candidate = CandidateRange((EffectProposal(EffectKind.SUBTITLE, text),)
            + ((EffectProposal(EffectKind.SPEECH, '原始单一语音。'),) if speech else ()) + extra,
            'synthetic-complete', story_proposal_json=story)
    async def generate(self, context):
        yield self.candidate


class Choice:
    def __init__(self, *, block=False, selected='last'):
        self.requests = []; self.entered = asyncio.Event(); self.release = asyncio.Event()
        self.block = block; self.selected = selected
    async def choose(self, request):
        from mira.application.chunking_contracts import BoundaryChoice, boundary_digest
        self.requests.append(request); self.entered.set()
        if self.block:
            while not self.release.is_set():
                try: await self.release.wait()
                except asyncio.CancelledError: continue
        return BoundaryChoice(boundary_digest(request),
            request.plans[-1].plan_id if self.selected == 'last' else None)


def captions(ranges):
    return [effect.value for part in ranges for effect in part.effects
            if effect.kind is EffectKind.SUBTITLE]


@pytest.mark.asyncio
async def test_first_complete_sentence_does_not_wait_for_boundary_judgment():
    source, judge = Source(), Choice(block=True)
    stream = SemanticChunkingGeneration(source, judge).generate(CONTEXT)
    first = await anext(stream)
    try:
        assert captions([first]) == ['窗外的雨停了一会儿。 ']
    finally:
        judge.release.set(); await stream.aclose()


@pytest.mark.asyncio
async def test_selected_tail_partition_changes_real_ranges_without_text_loss():
    judge = Choice()
    ranges = [r async for r in SemanticChunkingGeneration(Source(), judge).generate(CONTEXT)]
    assert len(judge.requests) == 1
    assert len(captions(ranges)) == 4
    assert ''.join(captions(ranges)) == TEXT
    assert sum(e.kind is EffectKind.SPEECH for r in ranges for e in r.effects) == 0


@pytest.mark.asyncio
async def test_unknown_preserves_exact_remaining_tail_without_repeating_prefix():
    judge = Choice(selected='unknown')
    ranges = [r async for r in SemanticChunkingGeneration(Source(), judge).generate(CONTEXT)]
    assert len(captions(ranges)) == 2
    assert ''.join(captions(ranges)) == TEXT
    assert captions(ranges)[1] == TEXT[len(captions(ranges)[0]):]


@pytest.mark.asyncio
@pytest.mark.parametrize('extra,story', [((EffectProposal(EffectKind.POSE, 'face_calm'),), None),
    ((), '{"transition_id":"t.chat"}')])
async def test_optional_event_candidates_keep_exact_original_cue(extra, story):
    source, judge = Source(extra=extra, story=story), Choice()
    ranges = [r async for r in SemanticChunkingGeneration(source, judge).generate(CONTEXT)]
    assert ranges == [source.candidate] and judge.requests == []


@pytest.mark.asyncio
async def test_timeout_is_hard_even_when_backend_ignores_cancellation_and_late_result_is_discarded():
    judge = Choice(block=True)
    backend = SemanticChunkingGeneration(Source(), judge, timeout_seconds=.01)
    try:
        ranges = await asyncio.wait_for(_collect(backend), .2)
        assert len(captions(ranges)) == 2 and ''.join(captions(ranges)) == TEXT
        assert len(judge.requests) == 1
        second = await asyncio.wait_for(_collect(backend), .2)
        assert len(captions(second)) == 2 and len(judge.requests) == 1
        frozen = tuple(ranges)
        judge.release.set()
        await asyncio.sleep(0)
        assert tuple(ranges) == frozen
    finally:
        judge.release.set()
        await asyncio.sleep(0)


async def _collect(backend):
    return [r async for r in backend.generate(CONTEXT)]


@pytest.mark.asyncio
async def test_cancelled_stream_never_yields_tail_after_uncooperative_judgment():
    judge = Choice(block=True)
    stream = SemanticChunkingGeneration(Source(), judge).generate(CONTEXT)
    await anext(stream)
    pending = asyncio.create_task(anext(stream))
    await judge.entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError): await pending
    judge.release.set()
    await asyncio.sleep(0)
    with pytest.raises(StopAsyncIteration): await anext(stream)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['foreign-binding', 'unknown-plan', 'exception'])
async def test_untrusted_boundary_results_cannot_rewrite_or_drop_tail(kind):
    from mira.application.chunking_contracts import BoundaryChoice, boundary_digest
    class Invalid:
        async def choose(self, request):
            if kind == 'exception': raise OSError('private-provider-detail')
            return BoundaryChoice('0' * 64 if kind == 'foreign-binding' else boundary_digest(request),
                                  request.plans[-1].plan_id if kind == 'foreign-binding' else 'invented')
    ranges = await _collect(SemanticChunkingGeneration(Source(), Invalid()))
    assert len(captions(ranges)) == 2 and ''.join(captions(ranges)) == TEXT


@pytest.mark.parametrize('text', [
    '短回复。', '没有任何可以确定的句子边界' * 10,
    '“带引号的句子。后文仍在引号内，不能切开。”',
    '（括号尚未闭合。后文不能猜测。' * 3,
    'x' * 4097,
])
def test_short_uncuttable_unbalanced_or_over_limit_candidates_use_complete_cue(text):
    from mira.application.semantic_chunking import make_request
    assert make_request(CONTEXT, Source(text).candidate) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('text', [
    '你好👩🏽\u200d💻，我们听雨吧。 咖啡还温热。 今天适合慢聊。 最后留下e\u0301。',
    '第一句包含“条件。不能拆开。”然后继续。 第二句完整。 第三句完整。 最后也完整。',
    '今天买了3.14千克苹果。 分给朋友两份。 留下一份自己吃。 明天再去。',
])
async def test_original_codepoint_ranges_preserve_emoji_combining_marks_and_qualifiers(text):
    ranges = await _collect(SemanticChunkingGeneration(Source(text), Choice()))
    values = captions(ranges)
    assert ''.join(values) == text
    assert 2 <= len(values) <= 4
    previous = 0
    for index, part in enumerate(ranges):
        chunk = part.caption_chunk
        assert chunk.index == index and chunk.start == previous
        assert text[chunk.start:chunk.end] == captions([part])[0]
        previous = chunk.end
    assert previous == len(text)


def test_compiler_binds_original_metadata_and_keeps_speech_independent():
    import hashlib
    from mira.application.compiler import compile_range
    from mira.domain.models import CaptionChunk
    source = Source(speech=True)
    chunk = CaptionChunk('12345678-1234-1234-1234-123456789abc', 0, 0, len(TEXT), len(TEXT),
                         hashlib.sha256(TEXT.encode()).hexdigest())
    candidate = replace(source.candidate, caption_chunk=chunk)
    text_only = replace(candidate, effects=(source.candidate.effects[0],))
    effect = compile_range(text_only, epoch=1, activity=1)[0]
    assert effect.caption_chunk == chunk and effect.cue_speech_id is None
    speech = compile_range(replace(candidate, effects=(source.candidate.effects[1],)), epoch=1, activity=1)[0]
    assert speech.caption_chunk is None and speech.value == source.candidate.effects[1].value
    from mira.entrypoints.http.schemas import EffectView
    assert EffectView.model_validate(effect, from_attributes=True).caption_chunk.model_dump() == {
        'group_id': chunk.group_id, 'index': 0, 'start': 0, 'end': len(TEXT), 'total': len(TEXT),
        'source_sha256': chunk.source_sha256}


@pytest.mark.asyncio
async def test_speech_bearing_candidate_stays_whole_and_actual_actor_calls_tts_once():
    from mira.adapters.journal.memory import MemoryEventJournal
    from mira.application.decision_contracts import mira26_author_policy
    from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
    from mira.application.session_actor import RuntimeLimits, SessionActor
    from mira.domain.models import SessionState
    from tests.contracts.test_semantic_actor_composition import Output, ForbiddenLegacyReview
    from tests.contracts.test_conversation_first import Wire
    from mira.adapters.review.jev_input import JevInputDecisionBackend
    from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
    from mira.application.decision_contracts import INPUT_QUESTION_SET_V2
    from mira.application.choice_wire_policy import CHOICE_WIRE_POLICY_REPORTED_V2
    from tests.integration.test_voice_http import Tts
    judge, voice = Choice(block=True), Tts()
    # Speech permission now validates actual request binding, not an unbound fixture.
    input_backend = JevInputDecisionBackend(transport=Wire(), model='jev-1.13.0',
        request_limit=1, decision_policy=USER_DEVELOPMENT_0_6_V2,
        question_set_revision=INPUT_QUESTION_SET_V2,
        choice_wire_policy_version=CHOICE_WIRE_POLICY_REPORTED_V2)
    value = SessionActor(SessionState('s', 'c'), SemanticChunkingGeneration(Source(speech=True), judge),
        ForbiddenLegacyReview(), MemoryEventJournal(100), RuntimeLimits(2, 32, 128),
        semantic_review=SemanticReviewCoordinator(input_backend, Output(), conversation_first=True),
        decision_owner=DecisionSnapshotOwner(mira26_author_policy()), speech_synthesis=voice)
    try:
        await value.submit(request_id='r', activity_seq=1, cutoff=0, text='聊聊')
        await asyncio.gather(*tuple(value._tasks))
        state = await value.snapshot()
        assert judge.requests == [] and state.active_grants[0].value == TEXT
        assert [e.kind for e in state.active_grants] == [EffectKind.SUBTITLE, EffectKind.SPEECH]
        speech = state.active_grants[1]
        operation = await value.open_speech(effect_id=speech.id, digest=speech.digest,
            output_epoch=speech.output_epoch, activity_seq=speech.activity_seq)
        packets = [p async for p in operation.values()]
        assert packets and len(voice.calls) == 1 and voice.calls[0][0] == '原始单一语音。'
        await value.close_media(operation)
        judge.release.set()
        await asyncio.gather(*tuple(value._tasks))
        state = await value.snapshot()
        assert state.sealed and sum(e.kind is EffectKind.SPEECH for e in state.active_grants) == 1
        assert ''.join(e.value for e in state.active_grants if e.kind is EffectKind.SUBTITLE) == TEXT
    finally:
        judge.release.set(); await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['stop', 'new-input', 'close'])
async def test_actor_cancellation_preserves_only_actual_prefix_receipt(action):
    from mira.adapters.journal.memory import MemoryEventJournal
    from mira.application.decision_contracts import mira26_author_policy
    from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
    from mira.application.session_actor import RuntimeLimits, SessionActor
    from mira.domain.models import Receipt, SessionState
    from tests.contracts.test_semantic_actor_composition import Input, Output, ForbiddenLegacyReview
    judge = Choice(block=True)
    value = SessionActor(SessionState('s', 'c'), SemanticChunkingGeneration(Source(speech=False), judge),
        ForbiddenLegacyReview(), MemoryEventJournal(100), RuntimeLimits(2, 32, 128),
        semantic_review=SemanticReviewCoordinator(Input(), Output(), conversation_first=True),
        decision_owner=DecisionSnapshotOwner(mira26_author_policy()))
    try:
        await value.submit(request_id='r', activity_seq=1, cutoff=0, text='聊聊')
        await judge.entered.wait()
        first = (await value.snapshot()).active_grants[0]
        await value.receipt(Receipt(first.id, first.digest, 1, 1, 1))
        if action == 'stop': await value.stop(activity_seq=2, cutoff=1)
        elif action == 'new-input': await value.submit(request_id='r2', activity_seq=2, cutoff=1, text='新话题')
        else: await value.close()
        judge.release.set()
        await asyncio.gather(*tuple(value._tasks), return_exceptions=True)
        state = await value.snapshot()
        assert [e for e in state.presented_effects if e.output_epoch == 1] == [first]
        assert [e for e in state.issued_effects if e.output_epoch == 1] == [first]
    finally:
        judge.release.set(); await value.close()


@pytest.mark.asyncio
async def test_speech_permission_timeout_never_drops_caption_tail():
    from mira.adapters.journal.memory import MemoryEventJournal
    from mira.application.decision_contracts import mira26_author_policy
    from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
    from mira.application.session_actor import RuntimeLimits, SessionActor
    from mira.domain.models import SessionState
    from tests.contracts.test_semantic_actor_composition import Input, Output, ForbiddenLegacyReview
    from tests.integration.test_voice_http import Tts
    class BlockedInput(Input):
        async def observe(self, snapshot): await asyncio.Event().wait()
    judge = Choice()
    value = SessionActor(SessionState('s', 'c'), SemanticChunkingGeneration(Source(speech=True), judge),
        ForbiddenLegacyReview(), MemoryEventJournal(100), RuntimeLimits(.03, 32, 128),
        semantic_review=SemanticReviewCoordinator(BlockedInput(), Output(), conversation_first=True),
        decision_owner=DecisionSnapshotOwner(mira26_author_policy()), speech_synthesis=Tts())
    try:
        await value.submit(request_id='r', activity_seq=1, cutoff=0, text='聊聊')
        await asyncio.gather(*tuple(value._tasks))
        state = await value.snapshot()
        assert state.sealed
        assert ''.join(e.value for e in state.active_grants if e.kind is EffectKind.SUBTITLE) == TEXT
    finally:
        await value.close()


def test_single_quoted_sentences_are_not_split_inside_and_apostrophes_do_not_open_quotes():
    from mira.application.semantic_chunking import legal_boundaries
    quoted = "She said 'Keep this. And its condition.' Then paused. Next sentence."
    assert quoted.index(' And') + 1 not in legal_boundaries(quoted)
    normal = "Don't split contractions. Keep the rest together. A final sentence."
    assert normal.index(' Keep') + 1 in legal_boundaries(normal)


@pytest.mark.parametrize('text,first_end', [
    ('总价（含税。以明细为准。）尚未确认。 明天我们会收到报价。 最后再决定是否出发。', '总价（含税。以明细为准。）尚未确认。 '),
    ('她说“可以一起看雨。”，然后收好相机。 我们还没出发。 先继续聊聊。', '她说“可以一起看雨。”，然后收好相机。 '),
    ('She said "Hello." and then stayed. We kept talking. It was late.', 'She said "Hello." and then stayed. '),
])
def test_inner_punctuation_cannot_detach_outer_sentence_qualification(text, first_end):
    from mira.application.semantic_chunking import legal_boundaries
    edges = legal_boundaries(text)
    assert text[:edges[0]] == first_end
