"""Small application façade over the pure story and affect reducers."""
from __future__ import annotations

from dataclasses import dataclass, replace
from mira.domain.xiahe_chapter import cancel_chapter
from mira.domain.story import (
    AffectState, CanonRevision, Reduction, StoryContextProjection, StoryDefinition,
    StoryGraph, StoryState, StoryTurn, Stop, PresentationReceipt,
    project_shared_context, reduce_affect, reduce_story,
    AffectTurn, AffectProposal, begin_story_input, validate_projection_current,
)


class StoryCheckpointUpgradeRequired(RuntimeError):
    """Validated old built-in checkpoint; ordinary loading remains strict."""
    code = "story_checkpoint_canon_upgrade_required"
    guidance = ("Stop the local server. Run python tools/story_checkpoint.py dry-run "
        "with the same --db and --scope and --authorize-story-checkpoint; review "
        "the result before an explicit commit. No checkpoint has been changed.")


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    story: StoryState
    affect: AffectState
    graph_revision: int
    canon_revision: int
    graph_hash: str
    canon_hash: str


@dataclass(frozen=True, slots=True)
class ProjectedCallContext:
    """Pass this same object to the generation adapter and JEV adapter."""
    projection: StoryContextProjection

    @property
    def projection_id(self) -> str:
        return self.projection.projection_id

    @property
    def canonical_json(self) -> str:
        return self.projection.context_json

    @property
    def graph_revision(self) -> int:
        return self.projection.graph_revision

    @property
    def canon_revision(self) -> int:
        return self.projection.canon_revision

    @property
    def canon_hash(self) -> str:
        return self.projection.canon_hash


class StoryRuntime:
    """In-memory deterministic session state; persistence is a separate opt-in call."""
    def __init__(self, definition: StoryDefinition, scope_id: str, *, outfit: str = "black_jacket") -> None:
        self.definition = definition
        self.story = StoryState.initial(definition, scope_id, outfit=outfit)
        self.affect = AffectState.initial(definition)

    @classmethod
    def from_snapshot(cls, definition: StoryDefinition, snapshot: RuntimeSnapshot) -> StoryRuntime:
        runtime = cls(definition, snapshot.story.scope_id, outfit=snapshot.story.current_outfit)
        if (snapshot.graph_revision != definition.graph.revision or snapshot.canon_revision != definition.canon.revision
                or snapshot.graph_hash != definition.graph.content_hash
                or snapshot.canon_hash != definition.canon.content_hash):
            raise ValueError("snapshot graph/canon revision mismatch")
        if (snapshot.story.graph_revision != snapshot.graph_revision or snapshot.story.canon_revision != snapshot.canon_revision
                or snapshot.story.graph_hash != snapshot.graph_hash or snapshot.story.canon_hash != snapshot.canon_hash):
            raise ValueError("snapshot carries inconsistent story revisions")
        if snapshot.affect.canon_revision != snapshot.canon_revision:
            raise ValueError("snapshot carries inconsistent affect revision")
        chapter=cancel_chapter(snapshot.story.chapter, exit_role=True)
        runtime.story = replace(snapshot.story, chapter=chapter,
            revision=snapshot.story.revision + (chapter != snapshot.story.chapter))
        runtime.affect = snapshot.affect
        return runtime

    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(self.story, self.affect, self.definition.graph.revision, self.definition.canon.revision,
                               self.definition.graph.content_hash, self.definition.canon.content_hash)

    def apply_story(self, event: StoryTurn | Stop | PresentationReceipt) -> Reduction:
        reduction = reduce_story(self.story, event, self.definition)
        self.story = reduction.state
        return reduction

    def begin_input(self, input_id: str, epoch: int) -> StoryState:
        """Fence old effects before awaiting generation without consuming input ID."""
        self.story = begin_story_input(self.story, input_id, epoch, self.definition)
        return self.story

    def apply_affect(self, turn: AffectTurn, proposal: AffectProposal | None = None) -> AffectState:
        # Deliberately independent of StoryTurn, JEV will, node, and episode results.
        self.affect = reduce_affect(self.affect, turn, proposal, self.definition)
        return self.affect

    def project(self) -> ProjectedCallContext:
        return ProjectedCallContext(project_shared_context(self.story, self.affect, self.definition))

    def validate_current(self, context: ProjectedCallContext) -> bool:
        return validate_projection_current(context.projection, self.story, self.affect, self.definition)

    def save_explicitly(self, store: object) -> None:
        """Persist only when caller explicitly supplies an authorized story store."""
        store.save(self.story, self.affect)  # type: ignore[attr-defined]


__all__ = ["StoryRuntime", "RuntimeSnapshot", "ProjectedCallContext"]
