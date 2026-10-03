"""Cumulative context facts must not grow once per audio packet; ledger stays intact."""
import asyncio

import pytest

from mira.adapters.generation.codex_support.payload import build_prompt
from mira.adapters.generation.codex_support.types import CodexLimits
from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.contracts import (
    CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict, audio_context_progress,
)
from mira.application.decision_contracts import ReliableUserInput, mira26_author_policy, valid_snapshot
from mira.application.decision_runtime import DecisionSnapshotOwner
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.domain.models import AudioProgress, AudioStatus, EffectKind, Phase, SessionState


class PromptCheckedGeneration:
    def __init__(self):
        self.contexts = []

    async def generate(self, context):
        self.contexts.append(context)
        build_prompt(context, CodexLimits())  # Validation only: no subprocess or network.
        yield CandidateRange((EffectProposal(EffectKind.SPEECH, "合成语音。"),), "synthetic")


class SyntheticReview:
    async def review(self, *_):
        return ReviewObservation(ReviewVerdict.ALLOW, "synthetic-test-only")


async def with_long_audio():
    generation = PromptCheckedGeneration()
    actor = SessionActor(SessionState("synthetic-session", "synthetic-client"), generation,
        SyntheticReview(), MemoryEventJournal(512), RuntimeLimits(2, 64, 128))
    await actor.submit(request_id="input-1", activity_seq=1, cutoff=0, text="第一句。")
    await asyncio.gather(*tuple(actor._tasks))
    effect = (await actor.snapshot()).active_grants[0]
    for sequence in range(1, 129):
        await actor.audio_progress(AudioProgress(effect.id, effect.digest, 1, 1, sequence,
            24000, sequence * 6000, AudioStatus.RENDERED))
    await actor.audio_progress(AudioProgress(effect.id, effect.digest, 1, 1, 129,
        24000, 128 * 6000, AudioStatus.COMPLETED))
    return actor, generation


@pytest.mark.asyncio
async def test_next_generation_uses_latest_cumulative_audio_fact_but_preserves_full_ledger():
    actor, generation = await with_long_audio()
    try:
        before = await actor.snapshot()
        await actor.submit(request_id="input-2", activity_seq=2, cutoff=129, text="请继续。")
        await asyncio.gather(*tuple(actor._tasks))
        state = await actor.snapshot()
        assert state.phase != Phase.ERROR
        assert [len(context.audio_progress) for context in generation.contexts] == [0, 1]
        assert generation.contexts[-1].audio_progress == (before.audio_progress[-1],)
        assert state.audio_progress == before.audio_progress and len(state.audio_progress) == 129
        assert generation.contexts[-1].audio_progress[0].rendered_samples == 768000
        assert generation.contexts[-1].presented_effects == before.presented_effects
    finally:
        await actor.close()


@pytest.mark.asyncio
async def test_semantic_snapshot_uses_same_latest_fact_without_inventing_heard_words():
    actor, _ = await with_long_audio()
    try:
        state = await actor.snapshot()
        snapshot = DecisionSnapshotOwner(mira26_author_policy()).snapshot(state,
            (ReliableUserInput("input-1", "第一句。"),))
        assert snapshot is not None and valid_snapshot(snapshot)
        assert snapshot.context.audio_progress == (state.audio_progress[-1],)
        assert len(state.audio_progress) == 129
        assert snapshot.presentation_facts[0].status == "presented"
        assert snapshot.presentation_facts[0].observed_text is None
    finally:
        await actor.close()


@pytest.mark.parametrize("status", [AudioStatus.RENDERED, AudioStatus.INTERRUPTED, AudioStatus.FAILED])
def test_projection_preserves_partial_terminal_status_and_other_effects(status):
    first = AudioProgress("a", "digest-a", 1, 1, 1, 24000, 100, AudioStatus.RENDERED)
    other = AudioProgress("b", "digest-b", 1, 1, 2, 24000, 200, AudioStatus.COMPLETED)
    latest = AudioProgress("a", "digest-a", 1, 1, 3, 24000, 300, status)
    ledger = (first, other, latest)
    assert audio_context_progress(ledger) == (other, latest)
    assert ledger == (first, other, latest)
    assert audio_context_progress(ledger)[-1] is latest


def test_projection_does_not_hide_conflicting_imported_effect_identity():
    first = AudioProgress("a", "digest-a", 1, 1, 1, 24000, 100, AudioStatus.RENDERED)
    conflicting = AudioProgress("a", "digest-b", 1, 1, 2, 24000, 200, AudioStatus.RENDERED)
    assert audio_context_progress((first, conflicting)) == (first, conflicting)
