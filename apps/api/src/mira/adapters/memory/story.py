"""Narrow, explicit, scope-bound SQLite checkpoint for story session state.

Construction is lazy and does not touch disk. No database is read or written
unless a caller has both enabled the adapter and explicitly authorized its exact
private scope, then calls save/load/tombstone. There is intentionally no purge API.
"""
from __future__ import annotations

from mira.domain.xiahe_chapter import ChapterState, chapter_to_dict, chapter_from_dict

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import json
import hashlib
import os
import stat
import sqlite3
from typing import Any
from urllib.parse import quote

from mira.domain.story import (
    Affect, AffectSignal, AffectState, AffectTurn, EpisodeCandidate, EvidenceLabel,
    OfferStatus, PendingTransition, ReceiptComponent, ReceiptKind, ReceiptRequirement, StoryNode, StoryState,
)

SCHEMA_VERSION = 6
_READABLE_SCHEMA_VERSIONS = (3, 4, 5, SCHEMA_VERSION)


class StoryStoreError(RuntimeError):
    pass


class StoreDisabled(StoryStoreError):
    pass


class ScopeMismatch(StoryStoreError):
    pass


class VersionMismatch(StoryStoreError):
    pass


class Tombstoned(StoryStoreError):
    pass


class StoryCheckpointStore:
    def __init__(self, path: str | Path, *, enabled: bool = False,
                 explicitly_authorized: bool = False, authorized_scope_id: str | None = None) -> None:
        self._path = Path(path)
        if type(enabled) is not bool or type(explicitly_authorized) is not bool:
            raise StoreDisabled("enablement and authorization must be exact booleans")
        self._enabled = enabled
        self._authorized = explicitly_authorized
        self._scope = authorized_scope_id
        if not self._path.is_absolute():
            raise StoreDisabled("story store path must be absolute")
        if self._enabled and (not self._authorized or not self._scope):
            raise StoreDisabled("enabled story persistence requires explicit authorization for one exact scope")
        if self._scope is not None and (not isinstance(self._scope, str) or not self._scope or len(self._scope) > 256):
            raise ScopeMismatch("authorized scope must be a bounded nonempty string")

    def _guard(self, scope_id: str) -> None:
        if not self._enabled or not self._authorized or not self._scope:
            raise StoreDisabled("story persistence is disabled or unauthorized")
        if scope_id != self._scope:
            raise ScopeMismatch("requested scope differs from the explicitly authorized scope")

    def _check_private_path(self, *, create: bool) -> bool:
        path = self._path.absolute()
        if path.resolve(strict=False) != path:
            raise StoreDisabled("story database path must not traverse a symlink")
        try:
            parent = os.lstat(path.parent)
        except FileNotFoundError as exc:
            raise StoreDisabled("private parent directory must already exist") from exc
        if not stat.S_ISDIR(parent.st_mode) or stat.S_ISLNK(parent.st_mode):
            raise StoreDisabled("story database parent must be a real directory")
        if parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) & 0o077:
            raise StoreDisabled("story database parent must be owner-controlled and private")
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            if not create:
                return False
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(path, flags, 0o600)
                os.close(fd)
            except FileExistsError:
                return self._check_private_path(create=False)
            info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise StoreDisabled("story database must be a regular non-symlink file")
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise StoreDisabled("existing story database must already be owner-only; permissions are never changed")
        return True

    @contextmanager
    def _db(self, *, write: bool):
        if write:
            self._check_private_path(create=True)
            uri = f"file:{quote(self._path.as_posix(), safe='/')}?mode=rw"
        else:
            if not self._check_private_path(create=False):
                yield None
                return
            uri = f"file:{quote(self._path.as_posix(), safe='/')}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
        connection.row_factory = sqlite3.Row
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except Exception:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    def save(self, story: StoryState, affect: AffectState) -> None:
        self._guard(story.scope_id)
        if affect.story_id != story.story_id or affect.canon_revision != story.canon_revision:
            raise VersionMismatch("story and affect snapshots do not share story/canon revisions")
        story_json = json.dumps(_story_to_dict(story), sort_keys=True, separators=(",", ":"))
        affect_json = json.dumps(_affect_to_dict(affect), sort_keys=True, separators=(",", ":"))
        with self._db(write=True) as db:
            archive_existed = _qualified_episode_table_exists(db)
            db.execute("""CREATE TABLE IF NOT EXISTS story_checkpoint (
                scope_id TEXT NOT NULL, story_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
                graph_id TEXT NOT NULL, graph_revision INTEGER NOT NULL, canon_revision INTEGER NOT NULL,
                graph_hash TEXT NOT NULL, canon_hash TEXT NOT NULL,
                story_revision INTEGER NOT NULL, story_json TEXT NOT NULL, affect_json TEXT NOT NULL,
                tombstoned INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(scope_id, story_id))""")
            # Keep receipt-qualified fictional episode records outside the
            # bounded (32 item) checkpoint context. The table is additive to
            # schema 3, append-only, and written in the same transaction as
            # the checkpoint so an acknowledged snapshot cannot lose its
            # archival episode on a crash.
            db.execute("""CREATE TABLE IF NOT EXISTS story_qualified_episode (
                scope_id TEXT NOT NULL, story_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL, episode_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(scope_id, story_id, candidate_id))""")
            old = db.execute("SELECT * FROM story_checkpoint WHERE scope_id=? AND story_id=?",
                             (story.scope_id, story.story_id)).fetchone()
            if old is not None:
                if old["schema_version"] not in _READABLE_SCHEMA_VERSIONS:
                    raise VersionMismatch("checkpoint schema version differs; explicit migration is required")
                if old["tombstoned"]:
                    raise Tombstoned("tombstone prevents implicit checkpoint resurrection")
                _assert_versions(old, story.graph_id, story.graph_revision, story.canon_revision,
                                 story.graph_hash, story.canon_hash)
                if story.revision < old["story_revision"]:
                    raise VersionMismatch("refusing to overwrite a newer acknowledged checkpoint")
                if not archive_existed:
                    # Preserve the last bounded set from a pre-archive schema-3
                    # checkpoint before a caller can replace or rotate it.
                    legacy_episodes = _story_from_dict(_migrate_story_payload(old)).episodes
                    _append_qualified_episodes(db, story, episodes=legacy_episodes)
                if story.revision == old["story_revision"]:
                    old_payload = _migrate_story_payload(old)
                    old_story = _story_from_dict(old_payload)
                    old_affect = _affect_from_dict(json.loads(old["affect_json"]))
                    # The raw cue is RAM-only. Repeated receipts must compare
                    # durable state plus its digest, not RAM text to absent text.
                    same_cue = (story.active_offer_cue is None or
                        old_payload.get("active_offer_cue_digest") ==
                        hashlib.sha256(story.active_offer_cue.encode()).hexdigest())
                    if old_story != replace(story, active_offer_cue=None) or not same_cue or old_affect != affect:
                        raise VersionMismatch("same revision cannot be rewritten with different contents")
                    _append_qualified_episodes(db, story)
                    return
            _append_qualified_episodes(db, story)
            db.execute("""INSERT INTO story_checkpoint
                (scope_id,story_id,schema_version,graph_id,graph_revision,canon_revision,graph_hash,canon_hash,story_revision,story_json,affect_json,tombstoned)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,0)
                ON CONFLICT(scope_id,story_id) DO UPDATE SET
                schema_version=excluded.schema_version, graph_id=excluded.graph_id,
                graph_revision=excluded.graph_revision, canon_revision=excluded.canon_revision,
                graph_hash=excluded.graph_hash, canon_hash=excluded.canon_hash,
                story_revision=excluded.story_revision, story_json=excluded.story_json,
                affect_json=excluded.affect_json, updated_at=CURRENT_TIMESTAMP""",
                (story.scope_id, story.story_id, SCHEMA_VERSION, story.graph_id, story.graph_revision,
                 story.canon_revision, story.graph_hash, story.canon_hash, story.revision, story_json, affect_json))

    def load_episodes(self, scope_id: str, story_id: str, *, graph_id: str,
                      graph_revision: int, canon_revision: int, graph_hash: str,
                      canon_hash: str) -> tuple[EpisodeCandidate, ...]:
        """Read all persisted qualified fictional episodes without expanding context.

        Missing databases and missing checkpoints are read-only misses. For a
        schema-3 store written before the append-only table existed, the
        current bounded episode tuple is returned as a safe legacy fallback.
        """
        self._guard(scope_id)
        if not isinstance(story_id, str) or not story_id or len(story_id) > 128:
            raise ScopeMismatch("story ID must be a bounded nonempty string")
        with self._db(write=False) as db:
            if db is None or not _table_exists(db):
                return ()
            row = db.execute("SELECT * FROM story_checkpoint WHERE scope_id=? AND story_id=?",
                             (scope_id, story_id)).fetchone()
            if row is None:
                return ()
            if row["tombstoned"]:
                raise Tombstoned("checkpoint has a tombstone and is not reentry eligible")
            if row["schema_version"] not in _READABLE_SCHEMA_VERSIONS:
                raise VersionMismatch("checkpoint schema version mismatch")
            _assert_versions(row, graph_id, graph_revision, canon_revision, graph_hash, canon_hash)
            if not _qualified_episode_table_exists(db):
                return tuple(_episode_from_dict(item) for item in
                             json.loads(row["story_json"]).get("episodes", ()))
            rows = db.execute("""SELECT episode_json FROM story_qualified_episode
                WHERE scope_id=? AND story_id=? ORDER BY rowid""", (scope_id, story_id)).fetchall()
        return tuple(_episode_from_dict(json.loads(item["episode_json"])) for item in rows)

    def load(self, scope_id: str, story_id: str, *, graph_id: str,
             graph_revision: int, canon_revision: int, graph_hash: str,
             canon_hash: str) -> tuple[StoryState, AffectState] | None:
        self._guard(scope_id)
        if not isinstance(story_id, str) or not story_id or len(story_id) > 128:
            raise ScopeMismatch("story ID must be a bounded nonempty string")
        with self._db(write=False) as db:
            if db is None or not _table_exists(db):
                return None
            row = db.execute("SELECT * FROM story_checkpoint WHERE scope_id=? AND story_id=?",
                             (scope_id, story_id)).fetchone()
        if row is None:
            return None
        if row["tombstoned"]:
            raise Tombstoned("checkpoint has a tombstone and is not reentry eligible")
        if row["schema_version"] not in _READABLE_SCHEMA_VERSIONS:
            raise VersionMismatch("checkpoint schema version mismatch")
        _assert_versions(row, graph_id, graph_revision, canon_revision, graph_hash, canon_hash)
        story = _story_from_dict(_migrate_story_payload(row))
        affect = _affect_from_dict(json.loads(row["affect_json"]))
        if story.scope_id != scope_id or story.story_id != story_id:
            raise ScopeMismatch("checkpoint payload identity mismatch")
        return story, affect

    def tombstone(self, scope_id: str, story_id: str) -> bool:
        """Mark an existing checkpoint non-reentrant while retaining it; never purges."""
        self._guard(scope_id)
        if not isinstance(story_id, str) or not story_id or len(story_id) > 128:
            raise ScopeMismatch("story ID must be a bounded nonempty string")
        if not self._check_private_path(create=False):
            return False
        with self._db(write=True) as db:
            if not _table_exists(db):
                return False
            cur = db.execute("UPDATE story_checkpoint SET tombstoned=1, updated_at=CURRENT_TIMESTAMP WHERE scope_id=? AND story_id=?",
                             (scope_id, story_id))
            return cur.rowcount > 0


def _table_exists(db: sqlite3.Connection) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='story_checkpoint'").fetchone() is not None


def _qualified_episode_table_exists(db: sqlite3.Connection) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='story_qualified_episode'").fetchone() is not None


def _episode_to_dict(e: EpisodeCandidate) -> dict[str, Any]:
    return {
        "candidate_id": e.candidate_id, "event_code": e.event_code,
        "receipt_id": e.receipt_id, "compiled_effect_id": e.compiled_effect_id,
        "compiled_effect_digest": e.compiled_effect_digest,
        "component_id": e.component_id, "component_digest": e.component_digest,
        "evidence": e.evidence.value, "story_id": e.story_id,
        "graph_revision": e.graph_revision, "canon_revision": e.canon_revision,
        "character_state": [list(x) for x in e.character_state],
        "claim_boundary": list(e.claim_boundary), "status": e.status,
    }


def _episode_from_dict(e: dict[str, Any]) -> EpisodeCandidate:
    return EpisodeCandidate(
        candidate_id=e["candidate_id"], event_code=e["event_code"],
        receipt_id=e["receipt_id"], compiled_effect_id=e["compiled_effect_id"],
        compiled_effect_digest=e["compiled_effect_digest"],
        component_id=e["component_id"], component_digest=e["component_digest"],
        evidence=EvidenceLabel(e["evidence"]), story_id=e["story_id"],
        graph_revision=int(e["graph_revision"]), canon_revision=int(e["canon_revision"]),
        character_state=tuple(tuple(x) for x in e["character_state"]),
        claim_boundary=tuple(e["claim_boundary"]), status=e["status"],
    )


def _append_qualified_episodes(db: sqlite3.Connection, story: StoryState, *,
                               episodes: tuple[EpisodeCandidate, ...] | None = None) -> None:
    seen: dict[str, str] = {}
    for episode in story.episodes if episodes is None else episodes:
        payload = json.dumps(_episode_to_dict(episode), sort_keys=True, separators=(",", ":"))
        prior_payload = seen.get(episode.candidate_id)
        if prior_payload is not None and prior_payload != payload:
            raise VersionMismatch("same episode ID cannot carry different contents")
        seen[episode.candidate_id] = payload
        old = db.execute("""SELECT episode_json FROM story_qualified_episode
            WHERE scope_id=? AND story_id=? AND candidate_id=?""",
            (story.scope_id, story.story_id, episode.candidate_id)).fetchone()
        if old is not None:
            if old["episode_json"] != payload:
                raise VersionMismatch("persisted episode ID cannot be rewritten with different contents")
            continue
        db.execute("""INSERT INTO story_qualified_episode
            (scope_id, story_id, candidate_id, episode_json) VALUES(?,?,?,?)""",
            (story.scope_id, story.story_id, episode.candidate_id, payload))


def _assert_versions(row: sqlite3.Row, graph_id: str, graph_revision: int, canon_revision: int,
                     graph_hash: str, canon_hash: str) -> None:
    if (row["graph_id"] != graph_id or row["graph_revision"] != graph_revision
            or row["canon_revision"] != canon_revision or row["graph_hash"] != graph_hash
            or row["canon_hash"] != canon_hash):
        raise VersionMismatch("checkpoint graph or canon revision differs; explicit migration is required")


def _migrate_story_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Read schemas 3–5 conservatively; only a later ordinary revision writes v6.

    Old outfit and episode evidence stay intact. No missing visual slot is
    guessed from internal affect, authored defaults, or an old episode label.
    """
    payload = json.loads(row["story_json"])
    if row["schema_version"] == 3:
        for slot in ("outfit", "accessory", "emotion"):
            payload["last_acknowledged_" + slot] = None
    elif row["schema_version"] not in (4, 5, SCHEMA_VERSION):
        raise VersionMismatch("checkpoint schema version mismatch")
    if row["schema_version"] in (3, 4):
        # Older schema versions never recorded a scene-specific invitation.
        # Preserve old bytes on disk, and grant no new scene consent on read.
        payload["active_offer_capability"] = None
        payload["active_offer_cue"] = None
    if row["schema_version"] in (3, 4, 5):
        payload.setdefault("chapter", chapter_to_dict(ChapterState(compatibility="legacy_story_schema_" + str(row["schema_version"]))))
    return payload


def _story_to_dict(s: StoryState) -> dict[str, Any]:
    chapter = chapter_to_dict(s.chapter)
    # This current-session reference cannot survive reentry. Keep the persisted
    # chapter shape readable by the existing schema-6 reader, even when null.
    chapter.pop('declined_gift_offer', None)
    return {
        "chapter": chapter,
        "scope_id": s.scope_id, "story_id": s.story_id, "graph_id": s.graph_id,
        "graph_revision": s.graph_revision, "canon_revision": s.canon_revision,
        "graph_hash": s.graph_hash, "canon_hash": s.canon_hash,
        "node": s.node.value, "epoch": s.epoch, "revision": s.revision,
        "active_offer_id": s.active_offer_id, "offer_status": s.offer_status.value,
        "current_outfit": s.current_outfit,
        "active_offer_capability": s.active_offer_capability,
        "active_offer_cue_digest": (hashlib.sha256(s.active_offer_cue.encode()).hexdigest()
                                    if s.active_offer_cue is not None else None),
        "last_acknowledged_outfit": s.last_acknowledged_outfit,
        "last_acknowledged_accessory": s.last_acknowledged_accessory,
        "last_acknowledged_emotion": s.last_acknowledged_emotion,
        "relationship_delta": s.relationship_delta,
        "pending": ({
            "transition_id": s.pending.transition_id, "grant_id": s.pending.grant_id,
            "receipt_kind": s.pending.receipt_kind.value, "epoch": s.pending.epoch,
            "input_id": s.pending.input_id, "offer_id": s.pending.offer_id,
            "source_node": s.pending.source_node.value, "admitted_node": s.pending.admitted_node.value,
            "target_node": s.pending.target_node.value, "capability_id": s.pending.capability_id,
            "capability_revision": s.pending.capability_revision,
            "draft_cue_digest": s.pending.draft_cue_digest,
            "compiled_effect_id": s.pending.compiled_effect_id,
            "compiled_effect_digest": s.pending.compiled_effect_digest,
            "receipt_requirement": ({
                "component": s.pending.receipt_requirement.component.value,
                "component_id": s.pending.receipt_requirement.component_id,
                "component_digest": s.pending.receipt_requirement.component_digest,
                "cue_digest": s.pending.receipt_requirement.cue_digest,
            } if s.pending.receipt_requirement else None),
        } if s.pending else None),
        "clarification_used": s.clarification_used, "last_input_ids": list(s.last_input_ids),
        "input_fence_id": s.input_fence_id, "released_story_events": list(s.released_story_events),
        "receipt_ids": list(s.receipt_ids), "episodes": [_episode_to_dict(e) for e in s.episodes],
        "reentry_label": s.reentry_label,
    }


def _story_from_dict(d: dict[str, Any]) -> StoryState:
    p = d["pending"]
    pending = None
    if p:
        req = p.get("receipt_requirement")
        pending = PendingTransition(
            transition_id=p["transition_id"], grant_id=p["grant_id"],
            receipt_kind=ReceiptKind(p["receipt_kind"]), epoch=int(p["epoch"]),
            input_id=p["input_id"], offer_id=p["offer_id"],
            source_node=StoryNode(p["source_node"]), admitted_node=StoryNode(p["admitted_node"]),
            target_node=StoryNode(p["target_node"]), capability_id=p["capability_id"],
            capability_revision=p["capability_revision"],
            draft_cue_digest=p.get("draft_cue_digest"),
            compiled_effect_id=p.get("compiled_effect_id"),
            compiled_effect_digest=p.get("compiled_effect_digest"),
            receipt_requirement=(ReceiptRequirement(ReceiptComponent(req["component"]), req["component_id"],
                                 req["component_digest"], req.get("cue_digest")) if req else None),
        )
    episodes = tuple(EpisodeCandidate(
        candidate_id=e["candidate_id"], event_code=e["event_code"], receipt_id=e["receipt_id"],
        compiled_effect_id=e["compiled_effect_id"], compiled_effect_digest=e["compiled_effect_digest"],
        component_id=e["component_id"], component_digest=e["component_digest"],
        evidence=EvidenceLabel(e["evidence"]), story_id=e["story_id"],
        graph_revision=int(e["graph_revision"]), canon_revision=int(e["canon_revision"]),
        character_state=tuple(tuple(x) for x in e["character_state"]),
        claim_boundary=tuple(e["claim_boundary"]), status=e["status"],
    ) for e in d.get("episodes", ()))
    return StoryState(
        chapter=chapter_from_dict(d["chapter"]),
        scope_id=d["scope_id"], story_id=d["story_id"], graph_id=d["graph_id"],
        graph_revision=int(d["graph_revision"]), canon_revision=int(d["canon_revision"]),
        graph_hash=d["graph_hash"], canon_hash=d["canon_hash"],
        node=StoryNode(d["node"]), epoch=int(d["epoch"]), revision=int(d["revision"]),
        active_offer_id=d["active_offer_id"], offer_status=OfferStatus(d["offer_status"]),
        current_outfit=d["current_outfit"], pending=pending,
        active_offer_capability=d.get("active_offer_capability"),
        active_offer_cue=None,  # Exact generated dialogue stays in active RAM, never checkpointed.
        last_acknowledged_outfit=d["last_acknowledged_outfit"],
        last_acknowledged_accessory=d["last_acknowledged_accessory"],
        last_acknowledged_emotion=d["last_acknowledged_emotion"],
        relationship_delta=int(d.get("relationship_delta", 0)),
        clarification_used=bool(d["clarification_used"]),
        last_input_ids=tuple(d["last_input_ids"]), receipt_ids=tuple(d["receipt_ids"]),
        input_fence_id=d.get("input_fence_id"), released_story_events=tuple(d.get("released_story_events", ())),
        episodes=episodes, reentry_label=d["reentry_label"],
    )


def _affect_to_dict(a: AffectState) -> dict[str, Any]:
    return {
        "story_id": a.story_id, "canon_revision": a.canon_revision, "emotion": a.emotion.value,
        "seen_input_ids": list(a.seen_input_ids),
        "recent_turns": [{"input_id": t.input_id, "signal": t.signal.value,
                          "reliable": t.reliable, "specific_notice": t.specific_notice} for t in a.recent_turns],
        "unknown_streak": a.unknown_streak, "neutral_streak": a.neutral_streak,
        "shy_cue_remaining": a.shy_cue_remaining, "smoothing_level": a.smoothing_level,
        "boundary_active": a.boundary_active, "revision": a.revision,
    }


def _affect_from_dict(d: dict[str, Any]) -> AffectState:
    return AffectState(
        story_id=d["story_id"], canon_revision=int(d["canon_revision"]), emotion=Affect(d["emotion"]),
        seen_input_ids=tuple(d.get("seen_input_ids", ())),
        recent_turns=tuple(AffectTurn(t["input_id"], AffectSignal(t["signal"]),
                                      bool(t["reliable"]), bool(t["specific_notice"]))
                           for t in d["recent_turns"]),
        unknown_streak=int(d["unknown_streak"]), neutral_streak=int(d["neutral_streak"]),
        shy_cue_remaining=int(d["shy_cue_remaining"]), smoothing_level=int(d["smoothing_level"]),
        boundary_active=bool(d["boundary_active"]), revision=int(d["revision"]),
    )
