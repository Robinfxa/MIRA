from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from mira.adapters.memory.async_story import (
    AsyncStoryCheckpointStore,
    AsyncStoryCloseTimeout,
    AsyncStoryDeadlineExceeded,
    AsyncStoryStoreBusy,
    AsyncStoryStoreClosed,
)
from mira.adapters.memory.story import ScopeMismatch, VersionMismatch
from mira.application.story import RuntimeSnapshot, StoryRuntime
from mira.domain.story import (
    AffectSignal,
    AffectTurn,
    EpisodeCandidate,
    EvidenceLabel,
    JevEvidence,
    ProposalSignal,
    ReadinessCatalog,
    Relevance,
    StoryNode,
    StoryProposal,
    StoryTurn,
    Will,
    begin_story_input,
    definition_from_documents,
    reduce_story,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "story"
GRAPH = json.loads((FIXTURES / "story-graph.json").read_text())
SEED = json.loads((FIXTURES / "mira.story-seed.v1.json").read_text())


@pytest.fixture
def definition():
    return definition_from_documents(GRAPH, SEED)


def _episode(definition, index: int) -> EpisodeCandidate:
    digest = hashlib.sha256(f"fictional-effect-{index}".encode()).hexdigest()
    component_digest = hashlib.sha256(f"fictional-component-{index}".encode()).hexdigest()
    return EpisodeCandidate(
        candidate_id=f"episode.synthetic.{index}",
        event_code="mira_amber_raincoat_presented",
        receipt_id=f"receipt.synthetic.{index}",
        compiled_effect_id=f"compiled.synthetic.{index}",
        compiled_effect_digest=digest,
        component_id=f"component.synthetic.{index}",
        component_digest=component_digest,
        evidence=EvidenceLabel.SOFTWARE,
        story_id=definition.graph.story_id,
        graph_revision=definition.graph.revision,
        canon_revision=definition.canon.revision,
        character_state=(("outfit_after", "amber_raincoat"),),
    )


def _snapshot(definition, *, scope="scope.synthetic") -> RuntimeSnapshot:
    return StoryRuntime(definition, scope).snapshot()


def _open(path, definition, *, scope="scope.synthetic", **kwargs):
    return AsyncStoryCheckpointStore(
        path,
        fixed_scope=scope,
        definition=definition,
        enabled=True,
        explicitly_authorized=True,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_open_and_missing_load_are_explicit_and_read_only(tmp_path, definition):
    db_path = tmp_path / "new" / "story.sqlite3"
    db_path.parent.mkdir(mode=0o700)
    async def scenario():
        store = _open(db_path, definition)
        assert not db_path.exists()  # construction is inert
        await store.open()
        assert await store.load() is None
        assert await store.load_episodes() == ()
        assert not db_path.exists()  # opening and missing reads do not create
        await store.aclose()
    await scenario()


@pytest.mark.asyncio
async def test_save_load_duplicate_and_equal_revision_conflict(tmp_path, definition):
    db_path = tmp_path / "story.sqlite3"
    db_path.parent.chmod(0o700)
    async def scenario():
        store = _open(db_path, definition)
        await store.open()
        snapshot = _snapshot(definition)
        await store.save(snapshot)
        await store.save(snapshot)  # exact current-revision retry is idempotent
        assert await store.load() == snapshot
        conflict = replace(snapshot, story=replace(snapshot.story, node=StoryNode.RAIN_VIEW))
        with pytest.raises(VersionMismatch):
            await store.save(conflict)
        assert await store.load() == snapshot
        await store.aclose()
    await scenario()


@pytest.mark.asyncio
async def test_wrong_scope_and_story_are_rejected_before_io(tmp_path, definition):
    async def scenario():
        store = _open(tmp_path / "story.sqlite3", definition)
        await store.open()
        with pytest.raises(ScopeMismatch):
            await store.save(_snapshot(definition, scope="scope.other"))
        with pytest.raises(ScopeMismatch):
            await store.load("unrelated.story")
        assert not (tmp_path / "story.sqlite3").exists()
        await store.aclose()
    await scenario()


@pytest.mark.asyncio
async def test_episode_archive_is_append_only_bounded_context_and_idempotent(tmp_path, definition):
    async def scenario():
        store = _open(tmp_path / "story.sqlite3", definition)
        await store.open()
        first = _snapshot(definition)
        first = replace(first, story=replace(first.story, episodes=tuple(_episode(definition, i) for i in range(32))))
        await store.save(first)
        second = replace(
            first,
            story=replace(first.story, revision=first.story.revision + 1,
                          episodes=tuple(_episode(definition, i) for i in range(32, 64))),
        )
        await store.save(second)
        await store.save(second)
        loaded = await store.load()
        archive = await store.load_episodes()
        assert loaded is not None and len(loaded.story.episodes) == 32
        assert len(archive) == 64
        assert archive[0].candidate_id == "episode.synthetic.0"
        assert archive[-1].candidate_id == "episode.synthetic.63"
        assert all(ep.status == "candidate_only" and ep.evidence is EvidenceLabel.SOFTWARE for ep in archive)
        await store.aclose()
    await scenario()


@pytest.mark.asyncio
async def test_episode_same_id_different_payload_is_rejected(tmp_path, definition):
    async def scenario():
        store = _open(tmp_path / "story.sqlite3", definition)
        await store.open()
        initial = _snapshot(definition)
        episode = _episode(definition, 1)
        await store.save(replace(initial, story=replace(initial.story, episodes=(episode,))))
        changed = replace(episode, event_code="changed-but-still-fictional")
        next_snapshot = replace(
            initial,
            story=replace(initial.story, revision=initial.story.revision + 1, episodes=(changed,)),
        )
        with pytest.raises(VersionMismatch, match="episode ID"):
            await store.save(next_snapshot)
        assert (await store.load_episodes())[0] == episode
        await store.aclose()
    await scenario()


@pytest.mark.asyncio
async def test_reentry_preserves_acknowledged_state_and_fences_unacknowledged_pending(tmp_path, definition):
    async def scenario():
        store = _open(tmp_path / "story.sqlite3", definition)
        await store.open()
        acknowledged = _episode(definition, 1)
        base = _snapshot(definition)
        acknowledged_snapshot = replace(
            base,
            story=replace(base.story, node=StoryNode.RAIN_VIEW,
                          current_outfit="amber_raincoat", episodes=(acknowledged,)),
        )
        await store.save(acknowledged_snapshot)
        restored = await store.load()
        assert restored is not None
        assert restored.story.node is StoryNode.RAIN_VIEW
        assert restored.story.current_outfit == "amber_raincoat"
        assert await store.load_episodes() == (acknowledged,)

        # A persisted proposal without a receipt is not acknowledged progress.
        fresh = _snapshot(definition)
        started = begin_story_input(fresh.story, "input.pending", 1, definition)
        proposal = StoryProposal("t.offer", ProposalSignal.OFFER_RAIN, "input.pending", 1,
                                 "offer.pending", draft_cue="A fictional cue.")
        evidence = JevEvidence("input.pending", 1, None, Will.UNKNOWN, Relevance.RELEVANT)
        staged = reduce_story(started, StoryTurn("input.pending", 1, proposal, evidence,
                                                  ReadinessCatalog("empty"), True), definition)
        pending_snapshot = replace(fresh, story=staged.state)
        await store.save(pending_snapshot)
        reentered = await store.load()
        assert reentered is not None and reentered.story.pending is not None
        runtime = StoryRuntime.from_snapshot(definition, reentered)
        runtime.begin_input("input.reentry", 2)
        assert runtime.story.pending is None
        assert runtime.story.node is StoryNode.CAFE_CHAT
        await store.aclose()
    await scenario()


@pytest.mark.asyncio
async def test_blocked_write_keeps_event_loop_responsive_then_times_out_unknown_and_busy(tmp_path, definition):
    async def scenario():
        store = _open(tmp_path / "story.sqlite3", definition, write_timeout_ms=50)
        await store.open()
        snapshot = _snapshot(definition)
        original_save = store._store.save
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def blocking_save(story, affect):
            started.set()
            release.wait(0.4)
            try:
                return original_save(story, affect)
            finally:
                finished.set()

        store._store.save = blocking_save
        task = asyncio.create_task(store.save(snapshot))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.001)
        assert started.is_set()
        # This timer could not run if SQLite were blocking the event loop.
        ticked = False
        async def tick():
            nonlocal ticked
            await asyncio.sleep(0.005)
            ticked = True
        await tick()
        with pytest.raises(AsyncStoryDeadlineExceeded) as caught:
            await task
        assert ticked and caught.value.outcome_unknown
        with pytest.raises(AsyncStoryStoreBusy):
            await store.save(snapshot)
        release.set()
        for _ in range(200):
            if finished.is_set():
                break
            await asyncio.sleep(0.005)
        assert finished.is_set()
        # Completion frees the one worker slot; retrying the exact revision reconciles safely.
        for _ in range(100):
            try:
                await store.save(snapshot)
                break
            except AsyncStoryStoreBusy:
                await asyncio.sleep(0.002)
        assert await store.load() == snapshot
        await store.aclose()
    await scenario()


@pytest.mark.asyncio
async def test_close_is_bounded_and_cannot_resurrect_after_active_write(tmp_path, definition):
    async def scenario():
        store = _open(tmp_path / "story.sqlite3", definition, close_timeout_ms=50)
        await store.open()
        original_save = store._store.save
        started = threading.Event()
        release = threading.Event()

        def blocking_save(story, affect):
            started.set()
            release.wait(0.5)
            return original_save(story, affect)

        store._store.save = blocking_save
        work = asyncio.create_task(store.save(_snapshot(definition)))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.001)
        assert started.is_set()
        with pytest.raises(AsyncStoryCloseTimeout):
            await store.aclose()
        with pytest.raises(AsyncStoryStoreClosed):
            await store.save(_snapshot(definition))
        assert not (tmp_path / "story.sqlite3").exists()
        release.set()
        # The close timed out for the caller, but the accepted write still
        # finishes and reports its actual durable result rather than rollback.
        await work
        await store.aclose()
        with pytest.raises(AsyncStoryStoreClosed):
            await store.open()
    await scenario()


@pytest.mark.asyncio
async def test_canceled_started_write_remains_busy_until_real_completion(tmp_path, definition):
    async def scenario():
        store = _open(tmp_path / "story.sqlite3", definition, write_timeout_ms=500)
        await store.open()
        original_save = store._store.save
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def blocking_save(story, affect):
            started.set()
            release.wait(0.4)
            try:
                return original_save(story, affect)
            finally:
                finished.set()

        store._store.save = blocking_save
        task = asyncio.create_task(store.save(_snapshot(definition)))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.001)
        assert started.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(AsyncStoryStoreBusy):
            await store.save(_snapshot(definition))
        release.set()
        for _ in range(200):
            if finished.is_set():
                break
            await asyncio.sleep(0.005)
        assert finished.is_set()
        for _ in range(100):
            try:
                await store.save(_snapshot(definition))
                break
            except AsyncStoryStoreBusy:
                await asyncio.sleep(0.002)
        assert await store.load() == _snapshot(definition)
        await store.aclose()
    await scenario()
