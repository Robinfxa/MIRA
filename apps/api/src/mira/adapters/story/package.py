"""Explicit filesystem adapter for the isolated authored story package.

This module is called only by composition/bootstrap/tests. It does no import-time
reads and accepts file paths only at this adapter boundary.
"""
from __future__ import annotations

import json
from pathlib import Path
from mira.domain.story import StoryDefinition, definition_from_documents


def load_story_definition(graph_path: str | Path, seed_path: str | Path, *,
                          approved_canon_ids: tuple[str, ...] | None = None) -> StoryDefinition:
    graph_doc = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    seed_doc = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    return definition_from_documents(graph_doc, seed_doc, approved_canon_ids=approved_canon_ids)
