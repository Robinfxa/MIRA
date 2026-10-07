"""Opt-in exact dialogue archive over the existing local SQLite evidence store."""
from dataclasses import replace
import json
import os

import pytest

from mira.application.interrupted_intent import AcceptedInput
from mira.domain.memory import MemoryScope
from mira.domain.models import Effect, EffectKind, Receipt, AudioProgress, AudioStatus


def make_archive(path, **kwargs):
    from mira.adapters.memory.conversation import ConversationArchive
    return ConversationArchive(path, fixed_scope=MemoryScope('synthetic-user', 'mira', 'synthetic-world'), **kwargs)


def opened(tmp_path):
    archive = make_archive(tmp_path / 'private' / 'conversation.sqlite', enabled=True,
        authorize_transcript_persistence=True)
    archive.open(pairing_confirmed=True)
    return archive


def accepted(index=0, text='synthetic original'):
    return AcceptedInput(f'request-{index}', index + 1, text, 'asr_final', index)


def displayed(index=0, kind=EffectKind.SUBTITLE, text='synthetic shown'):
    return Effect(f'effect-{index}', kind, text, f'digest-{index}', index + 1, index + 1)


def receipt(effect, seq=1):
    return Receipt(effect.id, effect.digest, effect.output_epoch, effect.activity_seq, seq)


def test_conversation_store_default_off_requires_distinct_consent_and_pairing(tmp_path):
    from mira.application.conversation_archive import ConversationArchiveError
    path = tmp_path / 'private' / 'conversation.sqlite'
    default = make_archive(path)
    with pytest.raises(ConversationArchiveError): default.open(pairing_confirmed=True)
    assert not path.parent.exists()
    with pytest.raises(ConversationArchiveError):
        make_archive(path, enabled=True).open(pairing_confirmed=True)
    enabled = make_archive(path, enabled=True, authorize_transcript_persistence=True)
    with pytest.raises(ConversationArchiveError): enabled.open()
    assert not path.parent.exists()


def test_exact_original_input_and_actual_receipts_survive_restart(tmp_path):
    archive = opened(tmp_path)
    data = accepted(text='完全原文，包括相同文字。')
    e = displayed(text='已呈现的完整字幕。')
    first = archive.append_input('session-a', data)
    archive.append_input('session-a', data)
    archive.append_receipt('session-a', e, receipt(e))
    archive.append_receipt('session-a', e, receipt(e))
    before = archive.load_session('session-a')
    archive.close()
    reopened = opened(tmp_path)
    try:
        restored = reopened.load_session('session-a')
        assert restored == before
        assert [x.stage for x in restored.records] == ['accepted_input', 'presented_effect']
        assert restored.records[0].entry_id == first.entry_id
        assert restored.records[0].payload()['input'] == {'request_id': data.request_id,
            'output_epoch': 1, 'text': data.text, 'source': 'asr_final', 'user_input_index': 0}
        assert restored.records[1].payload()['effect']['value'] == e.value
        assert restored.records[1].payload()['receipt']['presentation_seq'] == 1
        assert not reopened.load_session('another-session').records
        assert os.stat(reopened.path).st_mode & 0o777 == 0o600
    finally: reopened.close()


def test_partial_audio_is_never_recalled_as_presented_or_heard_words(tmp_path):
    archive = opened(tmp_path)
    try:
        archive.append_input('session-a', accepted())
        e = displayed(kind=EffectKind.SPEECH, text='full planned speech, not all rendered')
        progress = AudioProgress(e.id, e.digest, 1, 1, 1, 24000, 24, AudioStatus.INTERRUPTED)
        archive.append_receipt('session-a', e, progress)
        snapshot = archive.load_session('session-a')
        audio = snapshot.records[-1]
        assert audio.stage == 'audio_progress'
        assert audio.payload()['progress']['status'] == 'interrupted'
        with pytest.raises(ValueError): archive.append_receipt('session-a', e, receipt(e, 2))
        from mira.application.conversation_archive import conversation_recall_data
        recalled = conversation_recall_data(snapshot, request_text='speech', max_bytes=8192)
        assert 'full planned speech' not in json.dumps(recalled)
        assert recalled['physical_hearing_or_understanding_established'] is False
    finally: archive.close()


def test_scope_and_session_isolation_and_receipt_identity(tmp_path):
    from mira.adapters.memory.conversation import ConversationArchive
    archive = opened(tmp_path)
    try:
        archive.append_input('session-a', accepted(text='alpha private synthetic'))
        archive.append_input('session-b', accepted(text='beta private synthetic'))
        assert 'beta' not in str(archive.load_session('session-a').records[0].payload())
        e = displayed()
        with pytest.raises(ValueError):
            archive.append_receipt('session-a', e, replace(receipt(e), digest='wrong'))
        with pytest.raises(ValueError): archive.append_receipt('unknown-session', e, receipt(e))
        other = ConversationArchive(archive.path, fixed_scope=MemoryScope('other', 'mira', 'synthetic-world'),
            enabled=True, authorize_transcript_persistence=True)
        other.open(pairing_confirmed=True)
        try: assert not other.load_session('session-a').records
        finally: other.close()
    finally: archive.close()


def test_correct_forget_and_replayed_old_capture_never_revive_derived_history(tmp_path):
    archive = opened(tmp_path)
    try:
        original = archive.append_input('session-a', accepted(text='synthetic old error'))
        archive.append_receipt('session-a', displayed(text='reply based on old error'), receipt(displayed()))
        later = archive.append_input('session-a', accepted(1, 'synthetic later input'))
        e2 = displayed(1, text='later reply possibly derived from old error')
        archive.append_receipt('session-a', e2, receipt(e2, 2))
        archive.correct_input('session-a', original.entry_id, 'synthetic corrected fact')
        snapshot = archive.load_session('session-a')
        assert 'old error' not in json.dumps([x.payload() for x in snapshot.records])
        assert [x.stage for x in snapshot.records] == ['corrected_input', 'accepted_input']
        assert snapshot.records[1].entry_id == later.entry_id
        archive.append_input('session-a', accepted(text='synthetic old error'))
        assert 'old error' not in json.dumps([x.payload() for x in archive.load_session('session-a').records])
        corrected = snapshot.records[0]
        archive.forget_input('session-a', corrected.entry_id)
        assert 'corrected fact' not in json.dumps([x.payload() for x in archive.load_session('session-a').records])
        archive.forget_session('session-a')
        assert not archive.load_session('session-a').records
        with pytest.raises(Exception): archive.append_input('session-a', accepted(2))
    finally: archive.close()


def test_revoke_and_sensitive_input_failure_do_not_persist_new_transcript(tmp_path):
    from mira.application.conversation_archive import ConversationArchiveError
    from mira.adapters.memory.errors import MemoryPrivacyError
    archive = opened(tmp_path)
    try:
        with pytest.raises(MemoryPrivacyError):
            archive.append_input('session-a', accepted(text='password=synthetic-password-value'))
        assert not archive.load_session('session-a').records
        archive.revoke()
        with pytest.raises(ConversationArchiveError): archive.append_input('session-a', accepted())
        with pytest.raises(ConversationArchiveError): archive.load_session('session-a')
    finally: archive.close()


def test_session_revision_is_not_changed_by_other_session_capture(tmp_path):
    archive = opened(tmp_path)
    try:
        archive.append_input('old',accepted())
        old = archive.load_session('old')
        archive.append_input('current',accepted(text='new unrelated session'))
        assert archive.load_session('old') == old
        assert archive.session_revision('old') == old.snapshot_revision
    finally: archive.close()


def test_maximum_source_text_and_full_legal_audio_progress_are_not_shortened(tmp_path):
    archive = opened(tmp_path)
    try:
        original = '合' * 8192
        archive.append_input('session-a', accepted(text=original))
        e = displayed(kind=EffectKind.SPEECH,text='语' * 4096)
        progress = AudioProgress(e.id,e.digest,1,1,1,24000,24000*300,AudioStatus.COMPLETED)
        archive.append_receipt('session-a',e,progress)
        records = archive.load_session('session-a').records
        assert records[0].payload()['input']['text'] == original
        assert records[1].payload()['effect']['value'] == e.value
        assert records[1].payload()['progress']['rendered_samples'] == 7200000
    finally: archive.close()
