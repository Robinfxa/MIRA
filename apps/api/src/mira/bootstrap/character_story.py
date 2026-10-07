"""Opt-in authored character composition. Importing it opens no private state."""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json
from dataclasses import replace
from pathlib import Path

from mira.application.actor_story import SessionCharacterRuntime
from mira.application.story import StoryRuntime
from mira.domain.story import ReadinessCatalog, StoryDefinition, StoryNode, OfferStatus, Stop, definition_from_documents


def builtin_definition() -> StoryDefinition:
    root = files('mira.adapters.story').joinpath('assets')
    seed_bytes = root.joinpath('mira.story-seed.v1.json').read_bytes()
    selection = json.loads(root.joinpath('canon-selection.v1.json').read_text())
    if hashlib.sha256(seed_bytes).hexdigest() != selection['seed_source']['sha256']:
        raise ValueError('authored_canon_selection_mismatch')
    return definition_from_documents(
        json.loads(root.joinpath('story-graph.json').read_text()),
        json.loads(seed_bytes),
        approved_canon_ids=tuple(selection['explicit_composition_selection']),
    )


def reenter_runtime(runtime: StoryRuntime) -> StoryRuntime:
    """Keep acknowledged fiction, never replay an unfinished presentation grant."""
    # A pending offer already has an ID, but that ID is not a presentation.
    # Reuse the reducer's cancellation semantics rather than promoting it.
    runtime.apply_story(Stop(runtime.story.epoch))
    if (runtime.story.node is StoryNode.AWAIT_RAIN_CHOICE
            and runtime.story.active_offer_capability == 'cafe.scene.rain_window'):
        # Scene consent binds the exact cue held only in active RAM. A reopened
        # browser cannot recover that consent from a persisted goal or digest.
        runtime.story = replace(runtime.story, node=StoryNode.CAFE_CHAT,
            active_offer_id=None, active_offer_capability=None,
            offer_status=OfferStatus.SUSPENDED, clarification_used=False)
    runtime.story = replace(runtime.story, epoch=0, active_offer_cue=None,
        reentry_label='qualified_character_presentation_history')
    return runtime


def ephemeral_character_factory(*, readiness: ReadinessCatalog | None = None):
    """Public authored canon only. Nothing survives closing this local process."""
    definition = builtin_definition()
    catalog = readiness or ReadinessCatalog('mira-character-assets-unregistered-v1')
    def create(state):
        return SessionCharacterRuntime(StoryRuntime(definition, state.session_id), catalog)
    return create


class CharacterRuntimeBinding:
    """One paired operator's runtime and owned async checkpoint worker."""
    def __init__(self, definition, scope, catalog, store, loaded=None):
        self.definition=definition
        self.scope=scope
        self.catalog=catalog
        self.store=store
        self.loaded=loaded
        self.current=None
        self.closed=False

    def create(self, state):
        if self.closed: raise ValueError('character_binding_closed')
        snapshot=self.current.runtime.snapshot() if self.current is not None else self.loaded
        runtime=(StoryRuntime.from_snapshot(self.definition,snapshot) if snapshot is not None
                 else StoryRuntime(self.definition,self.scope))
        if snapshot is not None: runtime=reenter_runtime(runtime)
        self.current=SessionCharacterRuntime(runtime,self.catalog,self.store.save)
        return self.current

    async def aclose(self):
        if self.closed:return
        self.closed=True
        await self.store.aclose()


def persistent_character_factory(*, database:Path, scope_id:str, authorized:bool,
                                 readiness:ReadinessCatalog | None = None):
    """Returns an inert factory. The HTTP pairing boundary calls it after pairing."""
    if authorized is not True or type(scope_id) is not str or not scope_id or len(scope_id)>128:
        raise ValueError('character_persistence_consent_or_scope_required')
    definition=builtin_definition()
    catalog=readiness or ReadinessCatalog('mira-character-assets-unregistered-v1')
    async def open_binding():
        from mira.adapters.memory.async_story import AsyncStoryCheckpointStore
        store=AsyncStoryCheckpointStore(database,fixed_scope=scope_id,definition=definition,
            enabled=True,explicitly_authorized=True)
        try:
            await store.open()
            loaded=await store.load()
            return CharacterRuntimeBinding(definition,scope_id,catalog,store,loaded)
        except BaseException:
            await store.aclose()
            raise
    return open_binding


def checkpoint_upgrade(*, database: Path, scope_id: str, authorized: bool):
    """Inert explicit local workflow; preview/commit must be invoked separately."""
    from mira.adapters.memory.story import StoryCheckpointStore
    from mira.adapters.memory.story_upgrade import StoryCanonUpgrade
    if authorized is not True or type(scope_id) is not str or not scope_id or len(scope_id) > 128:
        raise ValueError('character_persistence_consent_or_scope_required')
    store = StoryCheckpointStore(database, enabled=True, explicitly_authorized=True,
        authorized_scope_id=scope_id)
    return StoryCanonUpgrade(store, builtin_definition())
