"""Explicit recording/recall binding; no adapter, transport or permission authority."""
from __future__ import annotations

import asyncio
import json

from mira.application.conversation_archive import (
    ConversationArchiveError, ConversationArchiveBusyError, ConversationRecallPacket, ConversationProvenance, conversation_recall_data,
)


class SessionConversationBinding:
    def __init__(self, archive, *, authorize_transcript_persistence=False,
                 recall_session_id=None, authorize_recall_to_provider_and_jev=False,
                 speech_enabled=False, authorize_recalled_speech_to_google=False,
                 close_archive_on_actor_close=False):
        flags = (authorize_transcript_persistence, authorize_recall_to_provider_and_jev,
                 speech_enabled, authorize_recalled_speech_to_google, close_archive_on_actor_close)
        if any(type(value) is not bool for value in flags) or authorize_transcript_persistence is not True:
            raise ConversationArchiveError('conversation_persistence_not_authorized')
        if recall_session_id is not None:
            if type(recall_session_id) is not str or not 1 <= len(recall_session_id) <= 128:
                raise ConversationArchiveError('conversation_reentry_invalid')
            if not authorize_recall_to_provider_and_jev:
                raise ConversationArchiveError('conversation_recall_transmission_not_authorized')
            if speech_enabled and not authorize_recalled_speech_to_google:
                raise ConversationArchiveError('conversation_google_transmission_not_authorized')
        if not all(callable(getattr(archive, name, None)) for name in
                   ('capture', 'load_session', 'session_revision', 'aclose')):
            raise ConversationArchiveError('conversation_archive_invalid')
        self.archive = archive
        self._recall_session_id = recall_session_id
        self._close_archive = close_archive_on_actor_close
        self.authorize_recalled_speech_to_google = authorize_recalled_speech_to_google
        self._pending = None
        self._provenance = {}
        self._retry = None
        self._writer = None
        self._closed = False
        self._revoked = False
        self.persistence_status = 'enabled_no_committed_records'

    @property
    def recall_session_id(self):
        return self._recall_session_id

    def revoke(self):
        """Immediately disable future capture/recall; in-flight write outcome can be unknown."""
        self._closed = True
        self._revoked = True
        self._pending = None
        if self._writer is not None and not self._writer.done():
            self._writer.cancel()
        if self._retry is not None and not self._retry.done():
            self._retry.cancel()
        self.persistence_status = 'revoked_existing_records_retained'

    def schedule_capture(self, state, accepted_inputs):
        if self._closed:
            return
        self.persistence_status = 'pending'
        retained_epochs = {fact.output_epoch for fact in (*state.receipts, *state.audio_progress)} | {state.output_epoch}
        self._provenance = {epoch: proof for epoch, proof in self._provenance.items() if epoch in retained_epochs}
        self._pending = (state.session_id, accepted_inputs, state.issued_effects,
                         state.receipts, state.audio_progress)
        if self.recall_session_id is not None:
            # Receipts keep the provenance of their own generation epoch, including
            # late old-epoch receipts after a newer input has begun.
            epochs=sorted({fact.output_epoch for fact in (*state.receipts,*state.audio_progress)})
            proof=tuple(self._provenance.get(epoch) or ConversationProvenance(
                epoch,self.recall_session_id,0,(),False) for epoch in epochs)
            self._pending += (proof,)
        if self._writer is None or self._writer.done():
            self._writer = asyncio.create_task(self._drain())

    async def _drain(self):
        while self._pending is not None:
            value, self._pending = self._pending, None
            try:
                if self._revoked:return
                await self.archive.capture(*value)
            except asyncio.CancelledError:
                if not self._closed:
                    self.persistence_status = 'write_outcome_unknown'
                raise
            except ConversationArchiveBusyError:
                if not self._revoked:
                    self.persistence_status='pending'
                    self._pending=self._pending or value
                    if self._retry is None or self._retry.done():
                        self._retry=asyncio.create_task(self._retry_after_idle())
                return
            except (OSError, TimeoutError):
                if not self._revoked:
                    self.persistence_status = 'unavailable_or_write_outcome_unknown'
            except Exception:
                # No raw errors/text. Privacy/version failures never become saved.
                if not self._revoked:
                    self.persistence_status = 'rejected'
                self._pending = None
                return
            else:
                if not self._revoked:
                    self.persistence_status = 'saved'

    async def _retry_after_idle(self):
        try:
            await self.archive.wait_idle()
            if not self._revoked and self._pending is not None and (self._writer is None or self._writer.done()):
                self._writer=asyncio.create_task(self._drain())
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self._revoked:self.persistence_status='unavailable_or_write_outcome_unknown'

    async def flush(self, *, wait_for_retry=True):
        # Generation does not wait for a prior cancelled read to finish physically.
        # Management/close may explicitly reconcile the bounded pending snapshot.
        while True:
            writer=self._writer
            if writer is not None:
                try:await asyncio.shield(writer)
                except asyncio.CancelledError:
                    if not (self._closed and writer.cancelled()):raise
            retry=self._retry
            if wait_for_retry and retry is not None and retry is not asyncio.current_task():
                try:await asyncio.shield(retry)
                except asyncio.CancelledError:
                    if not (self._closed and retry.cancelled()):raise
                if self._retry is retry:self._retry=None
                if self._writer is not writer:continue
            return

    async def build_packet(self, request_text, *, output_epoch):
        if self._closed:
            raise ConversationArchiveError('conversation_binding_revoked')
        if self.recall_session_id is None:
            return None
        await self.flush(wait_for_retry=False)
        snapshot = await self.archive.load_session(self.recall_session_id)
        if snapshot.session_id != self.recall_session_id:
            raise ConversationArchiveError("conversation_scope_invalid")
        data = conversation_recall_data(snapshot, request_text=request_text)
        if self._closed:
            raise ConversationArchiveError('conversation_binding_revoked')
        proof=ConversationProvenance(output_epoch,self.recall_session_id,snapshot.snapshot_revision,
            tuple((row['source_entry_id'],row['source_event_id'],row['source_version'])
                for row in data['recalled_records']))
        previous=self._provenance.get(output_epoch)
        if previous is not None and previous!=proof:
            raise ConversationArchiveError('conversation_epoch_provenance_changed')
        self._provenance[output_epoch]=proof
        return ConversationRecallPacket(self.recall_session_id, snapshot.snapshot_revision,
            json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')))

    async def ensure_current(self, packet):
        if self._closed or type(packet) is not ConversationRecallPacket or packet.source_session_id != self.recall_session_id:
            raise ConversationArchiveError('conversation_binding_revoked')
        await self.flush(wait_for_retry=False)
        revision = await self.archive.session_revision(self.recall_session_id)
        # Revocation may happen while an uncancellable storage read finishes.
        if self._closed:
            raise ConversationArchiveError('conversation_binding_revoked')
        if revision != packet.snapshot_revision:
            raise ConversationArchiveError('conversation_context_stale')

    async def aclose(self):
        self._closed = True
        try:
            await self.flush(wait_for_retry=True)
        finally:
            if self._close_archive:
                await self.archive.aclose()
