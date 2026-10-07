"""Explicit, one-shot migration of the reviewed built-in canon 2 -> 3 pair.

No ordinary load writes. The caller must preview, then supply the exact preview
fingerprint to commit or restore. Original checkpoint and episode bytes remain
available; a restore may not erase any progress made after the upgrade.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json

from mira.adapters.memory.story import (
    ScopeMismatch, StoryCheckpointStore, Tombstoned, VersionMismatch,
    _affect_from_dict, _affect_to_dict, _episode_from_dict, _episode_to_dict,
    _story_from_dict, _story_to_dict, _table_exists, _qualified_episode_table_exists,
)
from mira.application.story import RuntimeSnapshot, StoryRuntime, StoryCheckpointUpgradeRequired
from mira.domain.story import OfferStatus, StoryDefinition, StoryNode, Stop
from mira.domain.xiahe_chapter import ChapterState, chapter_to_dict

# Disk compatibility is an explicit reviewed set, not the latest writer version.
# Schema 3/4 remain ordinary read-compatible; this upgrade never supported them.
UPGRADE_SCHEMA_VERSIONS = (5, 6)
MIGRATION_ID = 'mira-authored-canon-2-to-3-v1'
STORY_ID = 'mira.rain_window.unfinished_print'
GRAPH_ID = 'mira.rain_window.raincoat_invitation'
GRAPH_HASH = '534220e479209be3c7d1050f0b0e8ec93d7152adf89b6bc77b8c5b1a7b9d286a'
SOURCE_CANON_HASH = '92ac138690f5c9cc83b58037f7a9d20c857c6a2ab242d415931c7da68464812b'
TARGET_CANON_HASH = '4c1a0a992359fbe1d574175f837b72267fbbe2b246bea14e253c4d6e72f3b41d'
MAX_EPISODES = 4096
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024


class CanonUpgradeRequired(VersionMismatch, StoryCheckpointUpgradeRequired):
    pass


@dataclass(frozen=True, slots=True)
class UpgradeReport:
    status: str
    checkpoint_digest: str
    source_canon_revision: int
    target_canon_revision: int
    source_story_revision: int
    target_story_revision: int
    episodes_preserved: int
    pending_grant_canceled: bool
    scene_consent_canceled: bool
    migration_id: str = MIGRATION_ID

    def to_dict(self):
        return asdict(self)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _parse(raw, maximum):
    if type(raw) is not str or len(raw.encode()) > maximum:
        raise VersionMismatch('story_checkpoint_upgrade_payload_limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise VersionMismatch('story_checkpoint_upgrade_duplicate_json_key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, KeyError) as error:
        raise VersionMismatch('story_checkpoint_upgrade_corrupt_payload') from error


def _same_json(a, b):
    # JSON serialization keeps bool, integer and string types distinct.
    return _json(a) == _json(b)


def _valid_digest(value):
    return type(value) is str and len(value) == 64 and all(x in '0123456789abcdef' for x in value)


def _story_payload_for_schema(story, schema):
    payload = _story_to_dict(story)
    if schema == 5:
        # Preserve the existing canon-only upgrade's on-disk shape. Ordinary
        # store.save writes schema 6 only after a new state revision is accepted.
        payload.pop('chapter')
    return payload


def _validate_row(row, scope, revision, canon_hash):
    if (row['scope_id'] != scope or row['story_id'] != STORY_ID):
        raise ScopeMismatch('story_checkpoint_upgrade_scope_mismatch')
    if row['tombstoned'] != 0:
        raise Tombstoned('story_checkpoint_upgrade_tombstoned')
    schema = row['schema_version']
    if (schema not in UPGRADE_SCHEMA_VERSIONS or
            (row['graph_id'], row['graph_revision'], row['graph_hash'],
             row['canon_revision'], row['canon_hash']) !=
            (GRAPH_ID, 1, GRAPH_HASH, revision, canon_hash)):
        raise VersionMismatch('story_checkpoint_upgrade_unknown_identity')
    try:
        story_payload = _parse(row['story_json'], 256 * 1024)
        affect_payload = _parse(row['affect_json'], 16 * 1024)
        runtime_payload = dict(story_payload)
        if schema == 5:
            if 'chapter' in runtime_payload:
                raise ValueError('schema 5 has no chapter field')
            runtime_payload['chapter'] = chapter_to_dict(
                ChapterState(compatibility='legacy_story_schema_5'))
        story = _story_from_dict(runtime_payload)
        affect = _affect_from_dict(affect_payload)
        normalized = _story_payload_for_schema(story, schema)
        cue_digest = story_payload.get('active_offer_cue_digest')
        if cue_digest is not None and not _valid_digest(cue_digest):
            raise ValueError('invalid cue digest')
        normalized['active_offer_cue_digest'] = cue_digest
        if (not _same_json(story_payload, normalized)
                or not _same_json(affect_payload, _affect_to_dict(affect))):
            raise ValueError('noncanonical payload types or fields')
        if (story.scope_id, story.story_id, story.graph_id, story.graph_revision,
                story.graph_hash, story.canon_revision, story.canon_hash, story.revision) != (
                scope, STORY_ID, GRAPH_ID, 1, GRAPH_HASH, revision, canon_hash, row['story_revision']):
            raise ValueError('inconsistent story header')
        if affect.story_id != STORY_ID or affect.canon_revision != revision:
            raise ValueError('inconsistent affect header')
        for values in (story.last_input_ids, story.receipt_ids, story.released_story_events):
            if any(type(value) is not str or not value or len(value) > 128 for value in values):
                raise ValueError('invalid bounded history ID')
        if story.reentry_label not in {'session_state_only', 'qualified_character_presentation_history'}:
            raise ValueError('invalid checkpoint provenance label')
        for episode in story.episodes:
            _validate_episode(episode, revision)
        if len({ep.candidate_id for ep in story.episodes}) != len(story.episodes):
            raise ValueError('duplicate episode')
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise VersionMismatch('story_checkpoint_upgrade_corrupt_payload') from error
    return story, affect


def _validate_episode(episode, revision):
    # Canon-1 records may legitimately have survived the previous authored
    # revision. Existing provenance is retained, never upgraded in place.
    if (episode.story_id != STORY_ID or episode.graph_revision != 1
            or episode.canon_revision not in range(1, revision + 1)):
        raise VersionMismatch('story_checkpoint_upgrade_episode_provenance')
    expected = ('software_character_state_only', 'no_claim_of_physical_action',
        'no_claim_that_a_human_heard_or_understood', 'not_user_fact_or_shared_experience')
    if episode.claim_boundary != expected:
        raise VersionMismatch('story_checkpoint_upgrade_episode_boundary')


class StoryCanonUpgrade:
    def __init__(self, store: StoryCheckpointStore, definition: StoryDefinition):
        if (definition.graph.story_id, definition.graph.graph_id, definition.graph.revision,
                definition.graph.content_hash, definition.canon.revision, definition.canon.content_hash) != (
                STORY_ID, GRAPH_ID, 1, GRAPH_HASH, 3, TARGET_CANON_HASH):
            raise VersionMismatch('story_checkpoint_upgrade_unknown_target')
        self.store = store
        self.definition = definition

    def _read(self, db):
        if db is None or not _table_exists(db):
            raise VersionMismatch('story_checkpoint_upgrade_missing')
        sizes = db.execute('SELECT length(CAST(story_json AS BLOB)), length(CAST(affect_json AS BLOB)) '
            'FROM story_checkpoint WHERE scope_id=? AND story_id=?',
            (self.store._scope, STORY_ID)).fetchone()
        if sizes is not None and (type(sizes[0]) is not int or type(sizes[1]) is not int
                or sizes[0] > 256 * 1024 or sizes[1] > 16 * 1024):
            raise VersionMismatch('story_checkpoint_upgrade_payload_limit')
        row = db.execute('SELECT * FROM story_checkpoint WHERE scope_id=? AND story_id=?',
            (self.store._scope, STORY_ID)).fetchone()
        if row is None:
            raise VersionMismatch('story_checkpoint_upgrade_missing')
        row = dict(row)
        archive = []
        if _qualified_episode_table_exists(db):
            sizes = db.execute('SELECT length(CAST(candidate_id AS BLOB)), '
                'length(CAST(episode_json AS BLOB)), length(CAST(created_at AS BLOB)) '
                'FROM story_qualified_episode WHERE scope_id=? AND story_id=? '
                'ORDER BY rowid LIMIT ?', (self.store._scope, STORY_ID, MAX_EPISODES + 1)).fetchall()
            if (len(sizes) > MAX_EPISODES
                    or any(any(type(value) is not int for value in item)
                        or item[0] > 640 or item[1] > 16 * 1024 or item[2] > 128 for item in sizes)
                    or sum(sum(item) for item in sizes) > MAX_ARCHIVE_BYTES):
                raise VersionMismatch('story_checkpoint_upgrade_archive_limit')
            rows = db.execute('SELECT candidate_id,episode_json,created_at FROM story_qualified_episode '
                'WHERE scope_id=? AND story_id=? ORDER BY rowid LIMIT ?',
                (self.store._scope, STORY_ID, MAX_EPISODES + 1)).fetchall()
            archive = [tuple(item) for item in rows]
        else:
            raise VersionMismatch('story_checkpoint_upgrade_archive_missing')
        if len(archive) > MAX_EPISODES or len(_json(archive).encode()) > MAX_ARCHIVE_BYTES:
            raise VersionMismatch('story_checkpoint_upgrade_archive_limit')
        history = []
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='story_canon_upgrade_history'").fetchone():
            history = [dict(item) for item in db.execute('SELECT * FROM story_canon_upgrade_history '
                'WHERE scope_id=? AND story_id=? AND migration_id=? ORDER BY rowid LIMIT 3',
                (self.store._scope, STORY_ID, MIGRATION_ID))]
        return row, archive, history

    def _archive(self, archive, story):
        known = {}
        for candidate_id, raw, _created_at in archive:
            payload = _parse(raw, 16 * 1024)
            try:
                episode = _episode_from_dict(payload)
            except (ValueError, TypeError, KeyError) as error:
                raise VersionMismatch('story_checkpoint_upgrade_corrupt_episode') from error
            if (candidate_id != episode.candidate_id or not _same_json(payload, _episode_to_dict(episode))
                    or raw != _json(_episode_to_dict(episode))):
                raise VersionMismatch('story_checkpoint_upgrade_corrupt_episode')
            _validate_episode(episode, story.canon_revision)
            known[candidate_id] = payload
        # Missing archive tables/rows are corruption for this schema-5 workflow.
        # Never invent or silently backfill evidence while changing canon.
        for ep in story.episodes:
            if not _same_json(known.get(ep.candidate_id), _episode_to_dict(ep)):
                raise VersionMismatch('story_checkpoint_upgrade_archive_mismatch')

    def _plan(self, row, archive):
        story, affect = _validate_row(row, self.store._scope, 2, SOURCE_CANON_HASH)
        self._archive(archive, story)
        bound = replace(story, canon_revision=3, canon_hash=TARGET_CANON_HASH)
        snapshot = RuntimeSnapshot(bound, replace(affect, canon_revision=3), 1, 3,
            GRAPH_HASH, TARGET_CANON_HASH)
        runtime = StoryRuntime.from_snapshot(self.definition, snapshot)
        # This is cancellation, never an acknowledged presentation.
        runtime.apply_story(Stop(story.epoch))
        scene = (runtime.story.node is StoryNode.AWAIT_RAIN_CHOICE
            and runtime.story.active_offer_capability == 'cafe.scene.rain_window')
        if scene:
            runtime.story = replace(runtime.story, node=StoryNode.CAFE_CHAT,
                active_offer_id=None, active_offer_capability=None,
                offer_status=OfferStatus.SUSPENDED, clarification_used=False)
        runtime.story = replace(runtime.story, epoch=0, active_offer_cue=None,
            reentry_label='qualified_character_presentation_history')
        target = dict(row)
        target.update(canon_revision=3, canon_hash=TARGET_CANON_HASH,
            story_revision=runtime.story.revision,
            story_json=_json(_story_payload_for_schema(runtime.story, row['schema_version'])),
            affect_json=_json(_affect_to_dict(runtime.affect)))
        # Keep original updated_at in the checkpoint; migration timestamp is
        # recorded separately in immutable history, so reversal is exact.
        report = UpgradeReport('ready', _digest((row, archive)), 2, 3, story.revision,
            runtime.story.revision, len(archive), story.pending is not None, scene)
        return target, report

    def preview(self):
        self.store._guard(self.store._scope)
        with self.store._db(write=False) as db:
            if db is not None:
                db.execute("BEGIN")
            row, archive, history = self._read(db)
            if history:
                return self._repeat(row, archive, history, None, rollback=False)
            return self._plan(row, archive)[1]

    def commit(self, *, expected_digest):
        return self._change(expected_digest, rollback=False)

    def preview_rollback(self):
        self.store._guard(self.store._scope)
        with self.store._db(write=False) as db:
            if db is not None:
                db.execute("BEGIN")
            row, archive, history = self._read(db)
            return self._restore_plan(row, archive, history)[1]

    def rollback(self, *, expected_digest):
        return self._change(expected_digest, rollback=True)

    def _history(self, history):
        if not history or len(history) > 2 or history[0]['action'] != 'upgrade':
            raise VersionMismatch('story_checkpoint_upgrade_history_invalid')
        first = history[0]
        before = _parse(first['before_row_json'], 512 * 1024)
        after = _parse(first['after_row_json'], 512 * 1024)
        source, _ = _validate_row(before, self.store._scope, 2, SOURCE_CANON_HASH)
        _validate_row(after, self.store._scope, 3, TARGET_CANON_HASH)
        if not _valid_digest(first['archive_digest']):
            raise VersionMismatch('story_checkpoint_upgrade_history_invalid')
        if len(history) == 2 and (history[1]['action'] != 'rollback'
                or history[1]['before_row_json'] != first['after_row_json']
                or history[1]['after_row_json'] != first['before_row_json']
                or history[1]['archive_digest'] != first['archive_digest']):
            raise VersionMismatch('story_checkpoint_upgrade_history_invalid')
        return before, after, source

    def _repeat(self, row, archive, history, expected_digest, *, rollback):
        before, after, _source = self._history(history)
        restored = len(history) == 2
        current = before if restored else after
        expected = {_digest((before, archive)), _digest((after, archive))}
        if (row != current or history[0]['archive_digest'] != _digest(archive)
                or (expected_digest is not None and expected_digest not in expected)):
            raise VersionMismatch('story_checkpoint_upgrade_changed_since_preview')
        if rollback != restored:
            raise VersionMismatch('story_checkpoint_upgrade_already_restored' if restored
                else 'story_checkpoint_upgrade_not_restored')
        _target, report = self._plan(before, archive)
        if _target != after:
            raise VersionMismatch('story_checkpoint_upgrade_history_invalid')
        return replace(report, status='already_restored' if restored else 'already_upgraded',
            checkpoint_digest=_digest((row, archive)))

    def _restore_plan(self, row, archive, history):
        before, after, _source = self._history(history)
        if len(history) == 2:
            return before, self._repeat(row, archive, history, None, rollback=True)
        if row != after or history[0]['archive_digest'] != _digest(archive):
            raise VersionMismatch('story_checkpoint_upgrade_progress_prevents_restore')
        _target, report = self._plan(before, archive)
        # Validate that the saved after-row is exactly the deterministic result.
        if _target != after:
            raise VersionMismatch('story_checkpoint_upgrade_history_invalid')
        return before, replace(report, status='rollback_ready', checkpoint_digest=_digest((row, archive)))

    def _change(self, expected_digest, *, rollback):
        self.store._guard(self.store._scope)
        if not _valid_digest(expected_digest):
            raise VersionMismatch('story_checkpoint_upgrade_preview_digest_required')
        if not self.store._check_private_path(create=False):
            raise VersionMismatch('story_checkpoint_upgrade_missing')
        with self.store._db(write=True) as db:
            row, archive, history = self._read(db)
            if history and (not rollback or len(history) == 2):
                return self._repeat(row, archive, history, expected_digest, rollback=rollback)
            target, report = (self._restore_plan(row, archive, history) if rollback
                else self._plan(row, archive))
            if report.checkpoint_digest != expected_digest:
                raise VersionMismatch('story_checkpoint_upgrade_changed_since_preview')
            db.execute('CREATE TABLE IF NOT EXISTS story_canon_upgrade_history ('
                'scope_id TEXT NOT NULL, story_id TEXT NOT NULL, migration_id TEXT NOT NULL, '
                'action TEXT NOT NULL, before_row_json TEXT NOT NULL, after_row_json TEXT NOT NULL, '
                'archive_digest TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, '
                'PRIMARY KEY(scope_id,story_id,migration_id,action))')
            db.execute('INSERT INTO story_canon_upgrade_history '
                '(scope_id,story_id,migration_id,action,before_row_json,after_row_json,archive_digest) '
                'VALUES(?,?,?,?,?,?,?)', (self.store._scope, STORY_ID, MIGRATION_ID,
                'rollback' if rollback else 'upgrade', _json(row), _json(target), _digest(archive)))
            columns = ('schema_version','graph_id','graph_revision','canon_revision','graph_hash',
                'canon_hash','story_revision','story_json','affect_json','tombstoned','updated_at')
            db.execute('UPDATE story_checkpoint SET ' + ','.join(name + '=?' for name in columns)
                + ' WHERE scope_id=? AND story_id=?',
                tuple(target[name] for name in columns) + (self.store._scope, STORY_ID))
            return replace(report, status='restored' if rollback else 'upgraded')
