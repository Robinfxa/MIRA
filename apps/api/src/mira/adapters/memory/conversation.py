"""Explicit full-input/actual-receipt archive over the existing SQLite ledger.

No new schema or general memory platform. Session anchors and bounded dependency
chains let the existing supersession/tombstone semantics hide derived replies
when an earlier accepted statement is corrected or forgotten. Original bytes are
retained locally; tombstones are suppression, never physical deletion.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

from mira.adapters.memory.sqlite import SQLiteMemoryStore
from mira.application.conversation_archive import ConversationArchiveError, ConversationRecord, ConversationSnapshot, ConversationProvenance, valid_record_payload
from mira.application.interrupted_intent import AcceptedInput
from mira.domain.memory import MemoryEntry, MemoryScope, MemorySource
from mira.domain.transitions import MAX_AUDIO_SECONDS
from mira.domain.models import AudioProgress, AudioStatus, Effect, EffectKind, Receipt

_SCHEMA = 'mira.conversation-source.v1'


def _id(value):
    if (type(value) is not str or not 1 <= len(value) <= 128
            or any(ord(c) < 33 or ord(c) == 127 for c in value)):
        raise ConversationArchiveError('conversation_identity_invalid')
    return value


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class ConversationArchive:
    """Inert until explicit recording consent and verified local pairing.

    The synchronous object belongs to one IO worker. HTTP and model text cannot
    select its path/scope. Old manual-memory and story consent are not accepted.
    """
    def __init__(self, path, *, fixed_scope: MemoryScope, enabled=False,
                 authorize_transcript_persistence=False):
        if type(fixed_scope) is not MemoryScope:
            raise ConversationArchiveError('conversation_scope_invalid')
        if type(enabled) is not bool or type(authorize_transcript_persistence) is not bool:
            raise ConversationArchiveError('conversation_consent_invalid')
        self.path = Path(path)
        self._scope = fixed_scope
        self._enabled = enabled
        self._authorized = authorize_transcript_persistence
        self._revoked = False
        self._opened = False
        self._capture_seen = {}
        self._store = SQLiteMemoryStore(path, max_records=10000, max_entry_chars=16384)

    def _guard(self):
        if not self._enabled or not self._authorized or self._revoked:
            raise ConversationArchiveError('conversation_persistence_not_authorized')
        if not self._opened:
            raise ConversationArchiveError('conversation_archive_not_paired')

    def open(self, *, pairing_confirmed=False):
        if (not self._enabled or not self._authorized or self._revoked
                or pairing_confirmed is not True):
            raise ConversationArchiveError('conversation_persistence_not_authorized')
        self._store.open()
        self._opened = True
        return self

    def close(self):
        self._store.close()
        self._opened = False

    def revoke(self):
        """Disable this recording/reentry authority; does not erase stored records."""
        self._revoked = True
        self.close()

    def scope_revision(self):
        self._guard()
        return self._store.scope_revision(self._scope)

    def _identity(self, session_id, stage, identity):
        return 'conversation-' + sha256(_json((asdict(self._scope), session_id, stage, identity)).encode()).hexdigest()

    def _entry(self, session_id, stage, identity, payload, *, depends_on=(),
               source=MemorySource.INTERPRETATION):
        _id(session_id)
        identity = self._identity(session_id, stage, identity)
        return MemoryEntry(identity, self._scope, source,
            _json({'schema': _SCHEMA, 'session_id': session_id, 'stage': stage, 'payload': payload}),
            identity, 1, depends_on=tuple(sorted(depends_on)))

    def _anchor(self, session_id):
        return self._entry(session_id, 'session_anchor', session_id, {})

    def _read(self, session_id):
        self._guard()
        if session_id is not None: _id(session_id)
        # Same concrete-adapter layer uses the existing ledger's transaction and
        # suppression implementation; no SQL schema or second suppression index.
        db = self._store._db()
        db.execute('BEGIN')
        try:
            heads, all_entries, suppressed = self._store._snapshot(db, self._scope)
            envelopes = {}
            for entry in all_entries.values():
                try:
                    doc = json.loads(entry.text)
                except (ValueError, TypeError):
                    raise ConversationArchiveError('conversation_database_not_dedicated') from None
                if (type(doc) is not dict or set(doc) != {'schema', 'session_id', 'stage', 'payload'}
                        or doc['schema'] != _SCHEMA or type(doc['payload']) is not dict):
                    raise ConversationArchiveError('conversation_database_not_dedicated')
                stages = {'session_anchor','context_marker','recall_provenance','accepted_input','corrected_input','presented_effect','audio_progress'}
                if doc['stage'] not in stages:
                    raise ConversationArchiveError('conversation_source_invalid')
                expected_source = (MemorySource.USER_STATEMENT if doc['stage'] in ('accepted_input','corrected_input')
                    else MemorySource.PRESENTATION_RECEIPT if doc['stage'] in ('presented_effect','audio_progress')
                    else MemorySource.INTERPRETATION)
                if entry.source is not expected_source:
                    raise ConversationArchiveError('conversation_source_invalid')
                if doc['stage'] in ('accepted_input','corrected_input','presented_effect','audio_progress'):
                    if not valid_record_payload(doc['stage'], doc['payload']):
                        raise ConversationArchiveError('conversation_source_invalid')
                elif doc['stage'] == 'session_anchor' and doc['payload'] != {}:
                    raise ConversationArchiveError('conversation_source_invalid')
                elif doc['stage'] == 'context_marker' and (
                        set(doc['payload']) != {'output_epoch'} or type(doc['payload']['output_epoch']) is not int
                        or doc['payload']['output_epoch'] < 1):
                    raise ConversationArchiveError('conversation_source_invalid')
                elif doc['stage']=='recall_provenance':
                    payload=doc['payload']
                    if set(payload)!={'output_epoch','source_session_id','snapshot_revision','sources','available'}:
                        raise ConversationArchiveError('conversation_provenance_invalid')
                    try: ConversationProvenance(**{**payload,'sources':tuple(tuple(row) for row in payload['sources'])})
                    except (TypeError,ValueError):raise ConversationArchiveError('conversation_provenance_invalid') from None
                envelopes[entry.id] = (entry, doc)
            active = {entry.id for entry in heads if entry.id in envelopes}
            dependencies={key:set(row[0].depends_on) for key,row in envelopes.items()}
            provenance={}
            invalid=set()
            for key,(entry,doc) in envelopes.items():
                if doc['stage']!='recall_provenance':continue
                payload=doc['payload'];identity=(doc['session_id'],payload['output_epoch'])
                if identity in provenance:raise ConversationArchiveError('conversation_provenance_conflict')
                provenance[identity]=key
                if not payload['available']:invalid.add(key)
                for source_id,event_id,version in payload['sources']:
                    source=envelopes.get(source_id)
                    if (source is None or source[1]['session_id']!=payload['source_session_id']
                            or source[0].source_event_id!=event_id or source[0].source_version!=version
                            or source[1]['stage'] not in ('accepted_input','corrected_input','presented_effect','audio_progress')):
                        raise ConversationArchiveError('conversation_provenance_source_invalid')
                    dependencies[key].add(source_id)
            # Prior recalled output remains in the current Actor's actual history.
            # Conservatively retain its dependencies for later receipts, without
            # making independently accepted user statements derived evidence.
            by_session={}
            for (sid,epoch),key in sorted(provenance.items()):
                previous=by_session.get(sid)
                if previous is not None:dependencies[key].add(previous)
                by_session[sid]=key
            for key,(_,doc) in envelopes.items():
                if doc['stage'] in ('presented_effect','audio_progress'):
                    epoch=doc['payload']['effect']['output_epoch']
                    dependencies[key].add(self._identity(doc['session_id'],'context_marker',epoch))
                    proof=provenance.get((doc['session_id'],epoch))
                    if proof is not None:dependencies[key].add(proof)
            # Closure runs across the fixed local scope, so A -> B -> C can be
            # suppressed transitively. A queue avoids a quadratic full scan.
            dependents={}
            for key,parents in dependencies.items():
                for parent in parents:dependents.setdefault(parent,set()).add(key)
                if any(parent not in active for parent in parents):invalid.add(key)
            queue=list(invalid)
            while queue:
                key=queue.pop()
                if key not in active:continue
                active.remove(key);queue.extend(dependents.get(key,()))
            selected={key for key,(_,doc) in envelopes.items() if session_id is None or doc['session_id']==session_id}
            relevant_sessions={envelopes[key][1]['session_id'] for key in selected}
            pending=list(selected);visited=set()
            while pending:
                key=pending.pop()
                if key in visited:continue
                visited.add(key)
                for parent in dependencies[key]:
                    if parent in envelopes:
                        relevant_sessions.add(envelopes[parent][1]['session_id']);pending.append(parent)
            # Any later source correction in an upstream session changes the
            # consumer revision. Unrelated sessions do not change it.
            relevant={key for key,(_,doc) in envelopes.items() if doc['session_id'] in relevant_sessions}
            history = db.execute("""SELECT h.seq,e.id,m.target_entry_id
                FROM memory_history h LEFT JOIN memory_entries e ON e.id=h.event_id
                LEFT JOIN memory_mutations m ON m.id=h.event_id
                WHERE h.user_id=? AND h.character_id=? AND h.world_id=?""",
                (self._scope.user_id, self._scope.character_id, self._scope.world_id)).fetchall()
            revision = max((int(row[0]) for row in history
                            if row[1] in relevant or row[2] in relevant), default=0)
            db.execute('COMMIT')
            return revision, {key:envelopes[key] for key in selected}, active & selected
        except BaseException:
            if db.in_transaction: db.execute('ROLLBACK')
            raise

    @staticmethod
    def _record(entry, doc):
        return ConversationRecord(entry.id, entry.source_event_id, entry.source_version,
                                  doc['stage'], _json(doc['payload']))

    def append_input(self, session_id: str, accepted: AcceptedInput):
        self._guard()
        if (type(accepted) is not AcceptedInput or not _id(accepted.request_id)
                or type(accepted.output_epoch) is not int or accepted.output_epoch < 1
                or type(accepted.user_input_index) is not int or accepted.user_input_index < 0
                or accepted.source not in ('text', 'asr_final')
                or type(accepted.text) is not str or not accepted.text.strip() or len(accepted.text) > 8192):
            raise ValueError('conversation_input_invalid')
        _, existing_rows, _ = self._read(session_id)
        for old, doc in existing_rows.values():
            if doc['stage'] not in ('accepted_input', 'corrected_input'):
                continue
            previous = doc['payload']['input']
            if (previous['request_id'] != accepted.request_id and
                    (previous['user_input_index'] == accepted.user_input_index
                     or previous['output_epoch'] == accepted.output_epoch)):
                raise ConversationArchiveError('conversation_input_identity_conflict')
        anchor = self._anchor(session_id)
        entry = self._entry(session_id, 'accepted_input', accepted.request_id,
            {'input': asdict(accepted)}, depends_on=(anchor.id,), source=MemorySource.USER_STATEMENT)
        # Check text before even creating the anchor for an ineligible input.
        self._store._privacy_check(entry)
        self._store.append(anchor)
        original = self._store.append(entry)
        all_rows = existing_rows
        prior = [(row[1]['payload']['output_epoch'], row[0].id) for row in all_rows.values()
                 if row[1]['stage'] == 'context_marker'
                 and row[1]['payload']['output_epoch'] < accepted.output_epoch]
        dependencies = (anchor.id, original.id) + ((max(prior)[1],) if prior else ())
        marker = self._entry(session_id, 'context_marker', accepted.output_epoch,
            {'output_epoch': accepted.output_epoch}, depends_on=dependencies)
        self._store.append(marker)
        return self._record(original, json.loads(original.text))

    def append_receipt(self, session_id: str, effect: Effect, fact: Receipt | AudioProgress):
        self._guard()
        if (type(effect) is not Effect or type(effect.kind) is not EffectKind
                or type(effect.value) is not str or not effect.value.strip() or len(effect.value) > 4096
                or type(fact) not in (Receipt, AudioProgress)
                or (effect.id, effect.digest, effect.output_epoch, effect.activity_seq)
                   != (fact.effect_id, fact.digest, fact.output_epoch, fact.activity_seq)
                or type(fact.presentation_seq) is not int or fact.presentation_seq < 1):
            raise ValueError('conversation_receipt_invalid')
        if type(fact) is Receipt and effect.kind is EffectKind.SPEECH:
            raise ValueError('conversation_speech_requires_audio_progress')
        if type(fact) is AudioProgress and (
                effect.kind is not EffectKind.SPEECH or type(fact.status) is not AudioStatus
                or type(fact.rendered_samples) is not int or fact.rendered_samples < 0
                or type(fact.sample_rate_hz) is not int or not 8000 <= fact.sample_rate_hz <= 48000
                or fact.rendered_samples > fact.sample_rate_hz * MAX_AUDIO_SECONDS
                or fact.status in (AudioStatus.RENDERED, AudioStatus.COMPLETED) and fact.rendered_samples == 0):
            raise ValueError('conversation_audio_progress_invalid')
        _, rows, active = self._read(session_id)
        marker_id = self._identity(session_id, 'context_marker', effect.output_epoch)
        if marker_id not in rows:
            raise ValueError('conversation_source_input_unavailable')
        stage, field = ('presented_effect', 'receipt') if type(fact) is Receipt else ('audio_progress', 'progress')
        entry = self._entry(session_id, stage, (effect.id, fact.presentation_seq),
            {'effect': asdict(effect), field: asdict(fact)},
            # Preserve this actual historical fact even if its input or recalled
            # source was suppressed before IO. _read computes its eligibility.
            depends_on=(),
            source=MemorySource.PRESENTATION_RECEIPT)
        previous=rows.get(entry.id)
        if previous is not None:
            # Earlier archive versions carried the local marker as a physical
            # ledger link. Preserve exact source replay without rewriting it.
            if previous[1]['payload']!=json.loads(entry.text)['payload']:
                raise ConversationArchiveError('conversation_capture_identity_conflict')
            return self._record(*previous)
        stored = self._store.append(entry)
        return self._record(stored, json.loads(stored.text))

    def load_session(self, session_id):
        revision, envelopes, active = self._read(session_id)
        eligible = ('accepted_input', 'corrected_input', 'presented_effect', 'audio_progress')
        records = []
        for entry_id in active:
            entry, doc = envelopes[entry_id]
            if doc['stage'] in eligible:
                record = self._record(entry, doc)
                payload = doc['payload']
                epoch = payload['input']['output_epoch'] if 'input' in payload else payload['effect']['output_epoch']
                seq = 0 if 'input' in payload else payload.get('receipt', payload.get('progress'))['presentation_seq']
                records.append(((epoch, seq, entry.id), record))
        inactive = sum(key not in active and doc['stage'] in eligible
                       for key, (_, doc) in envelopes.items())
        return ConversationSnapshot(session_id, revision,
            tuple(record for _, record in sorted(records)), inactive)

    def _input(self, session_id, entry_id):
        _, rows, active = self._read(session_id)
        if entry_id not in active or rows[entry_id][1]['stage'] not in ('accepted_input', 'corrected_input'):
            raise ConversationArchiveError('conversation_input_not_current')
        return rows[entry_id]

    def correct_input(self, session_id, entry_id, replacement_text):
        entry, doc = self._input(session_id, entry_id)
        if type(replacement_text) is not str or not replacement_text.strip() or len(replacement_text) > 8192:
            raise ValueError('conversation_correction_invalid')
        corrected = {**doc, 'stage': 'corrected_input', 'payload': {'input': {
            **doc['payload']['input'], 'text': replacement_text}}}
        replacement = replace(entry, id=self._identity(session_id, 'correction', (entry.id, replacement_text)),
            text=_json(corrected), source_version=entry.source_version + 1,
            supersedes_id=entry.id, recorded_at=None)
        stored = self._store.supersede(self._scope, entry.id, replacement)
        return self._record(stored, corrected)

    def forget_input(self, session_id, entry_id):
        self._input(session_id, entry_id)
        return self._store.forget(self._scope, entry_id)

    def forget_session(self, session_id):
        self._guard()
        return self._store.forget(self._scope, self._anchor(session_id).id)

    def session_revision(self, session_id):
        return self._read(session_id)[0]

    def capture(self, session_id, inputs, effects, receipts, audio_progress, provenance=None):
        """Persist only accepted source rows and actual software receipts.

        Retries are exact/idempotent. A partial failure does not claim rollback;
        another exact snapshot can reconcile already committed source identities.
        """
        self._guard()
        for accepted in inputs:
            key = (session_id, 'input', accepted.request_id)
            digest = sha256(_json(asdict(accepted)).encode()).hexdigest()
            previous = self._capture_seen.get(key)
            if previous is not None and previous != digest:
                raise ConversationArchiveError('conversation_capture_identity_conflict')
            if previous is None:
                self.append_input(session_id, accepted)
                self._capture_seen[key] = digest
        proofs={}
        if provenance is not None:
            if type(provenance) is not tuple or len(provenance)>10000:
                raise ConversationArchiveError('conversation_provenance_invalid')
            for proof in provenance:
                if type(proof) is not ConversationProvenance or proof.output_epoch in proofs:
                    raise ConversationArchiveError('conversation_provenance_invalid')
                proofs[proof.output_epoch]=proof
        issued = {effect.id: effect for effect in effects}
        for fact in sorted((*receipts, *audio_progress), key=lambda row: row.presentation_seq):
            effect = issued.get(fact.effect_id)
            if effect is None:
                raise ConversationArchiveError('conversation_receipt_effect_missing')
            key = (session_id, type(fact).__name__, fact.effect_id, fact.presentation_seq)
            digest = sha256(_json((asdict(effect), asdict(fact))).encode()).hexdigest()
            previous = self._capture_seen.get(key)
            if previous is not None and previous != digest:
                raise ConversationArchiveError('conversation_capture_identity_conflict')
            if previous is None:
                if provenance is not None:
                    proof=proofs.get(effect.output_epoch)
                    if proof is None:raise ConversationArchiveError('conversation_provenance_missing')
                    self._append_provenance(session_id,proof)
                self.append_receipt(session_id, effect, fact)
                self._capture_seen[key] = digest


    def _append_provenance(self,session_id,proof):
        # This is an exact local fact about generation's evidence, not a new
        # semantic derivation. Sources may already be suppressed by the time a
        # real late presentation receipt reaches durable storage.
        _,rows,_=self._read(None)
        for source_id,event_id,version in proof.sources:
            source=rows.get(source_id)
            if (source is None or source[1]['session_id']!=proof.source_session_id
                    or source[0].source_event_id!=event_id or source[0].source_version!=version):
                raise ConversationArchiveError('conversation_provenance_source_invalid')
        entry=self._entry(session_id,'recall_provenance',proof.output_epoch,asdict(proof))
        self._store.append(entry)


    def list_sessions(self, *, cursor=None):
        """Bounded local identifiers only; fixed scope comes from construction."""
        revision, rows, active = self._read(None)
        sessions=sorted({doc['session_id'] for _,doc in rows.values() if doc['stage']=='session_anchor'})
        index=self._page_index(cursor,revision)
        page=sessions[index:index+20]
        return dict(revision=revision,sessions=page,
            next_cursor=f'{revision}:{index+len(page)}' if index+len(page)<len(sessions) else None)

    @staticmethod
    def _page_index(cursor,revision):
        if cursor is None:return 0
        try:
            rev,index=map(int,cursor.split(':'))
            if cursor != f'{rev}:{index}' or index<0 or index>10000 or rev!=revision: raise ValueError()
            return index
        except (ValueError,AttributeError):
            from mira.domain.memory import MemoryRevisionChangedError
            raise MemoryRevisionChangedError('conversation_page_stale') from None

    def management_page(self, session_id, *, cursor=None):
        revision=self.scope_revision()
        _,rows,active=self._read(session_id)
        eligible=[(entry,doc) for entry,doc in rows.values()
            if doc['stage'] in ('accepted_input','corrected_input','presented_effect','audio_progress')]
        eligible.sort(key=lambda pair:(pair[1]['payload'].get('input',pair[1]['payload'].get('effect'))['output_epoch'],
            pair[0].recorded_at,pair[0].id))
        index=self._page_index(cursor,revision)
        forgets=self._store._active_management_forgets(self._store._db(),self._scope,tuple(rows))
        result=[]
        used=1024
        for entry,doc in eligible[index:]:
            payload=doc['payload']; source=payload.get('input'); effect=payload.get('effect')
            row=dict(entry_id=entry.id,source_version=entry.source_version,stage=doc['stage'],active=entry.id in active,
                text=source['text'] if source else effect['value'],
                output_epoch=source['output_epoch'] if source else effect['output_epoch'],
                request_id=source['request_id'] if source else None,
                input_source=source['source'] if source else None,
                effect_kind=effect['kind'] if effect else None,
                rendered_samples=payload['progress']['rendered_samples'] if 'progress' in payload else None,
                sample_rate_hz=payload['progress']['sample_rate_hz'] if 'progress' in payload else None,
                audio_status=payload['progress']['status'] if 'progress' in payload else None,
                forget_event_id=forgets.get(entry.id,(None,None))[0])
            size=len(_json(row).encode())
            if result and (len(result)>=20 or used+size>65536):break
            result.append(row);used+=size
        if self.scope_revision()!=revision:
            from mira.domain.memory import MemoryRevisionChangedError
            raise MemoryRevisionChangedError('conversation_page_stale')
        after=index+len(result)
        return dict(session_id=session_id,revision=revision,entries=result,
            next_cursor=f'{revision}:{after}' if after<len(eligible) else None)

    def management_apply(self, session_id, command):
        """Reuse the ledger's atomic CAS/idempotent local-management transaction.

        Only explicit inputs can be edited; receipt facts cannot be fabricated.
        Old correction versions remain readable for an explicit later correction.
        """
        from mira.application.ports.memory_management import MemoryManagementOperation
        from dataclasses import replace
        _,rows,_=self._read(session_id)
        operation=command.operation
        if operation is MemoryManagementOperation.RECORD:
            raise ConversationArchiveError('conversation_source_must_be_accepted_input')
        target=command.entry_id
        if operation is MemoryManagementOperation.RESTORE:
            row=self._store._db().execute(
                'SELECT target_entry_id FROM memory_mutations WHERE id=? AND user_id=? AND character_id=? AND world_id=?',
                (command.forget_event_id,self._scope.user_id,self._scope.character_id,self._scope.world_id)).fetchone()
            target=row[0] if row else None
        if target not in rows or rows[target][1]['stage'] not in ('accepted_input','corrected_input'):
            raise ConversationArchiveError('conversation_input_not_in_session')
        if operation is MemoryManagementOperation.CORRECT:
            if type(command.text) is not str or not command.text.strip() or len(command.text)>8192:
                raise ConversationArchiveError('conversation_correction_invalid')
            doc=rows[target][1]
            replacement={**doc,'stage':'corrected_input','payload':{'input':{**doc['payload']['input'],'text':command.text}}}
            command=replace(command,text=_json(replacement))
        return self._store.management_apply(self._scope,command)
