from __future__ import annotations

import io
import json
import time
from dataclasses import FrozenInstanceError

import pytest

from mira.application.memory_context import (
    RequiredMemoryContextOverflow,
    build_context_packet,
)
from mira.domain.memory import (
    MemoryDeadlineExceededError,
    MemoryEntry,
    MemoryKind,
    MemoryQuery,
    MemoryRevisionChangedError,
    MemoryScope,
    MemorySource,
)
from tools import memory as memory_cli


SCOPE = MemoryScope("synthetic-user", "mira-test", "cafe-test")


def entry(
    entry_id: str,
    text: str,
    *,
    kind: MemoryKind = MemoryKind.EPISODIC,
    source: MemorySource = MemorySource.USER_STATEMENT,
    supersedes_id: str | None = None,
) -> MemoryEntry:
    return MemoryEntry(
        id=entry_id,
        scope=SCOPE,
        source=source,
        text=text,
        source_event_id=f"event-{entry_id}",
        source_version=1,
        recorded_at="2026-10-04T00:00:00+00:00",
        supersedes_id=supersedes_id,
        kind=kind,
    )


class FakeMemory:
    def __init__(self, constraints=(), recalled=(), *, delay=0.0, timeout=False,
                 revisions=None):
        self.constraints = tuple(constraints)
        self.recalled = tuple(recalled)
        self.delay = delay
        self.timeout = timeout
        self.revisions = tuple(revisions) if revisions is not None else None
        self.query: MemoryQuery | None = None
        self.constraint_scope: MemoryScope | None = None
        self.recall_calls = 0
        self.revision_calls = 0

    def scope_revision(self, scope):
        assert scope == SCOPE
        if self.revisions is None:
            value = 0
        else:
            index = min(self.revision_calls, len(self.revisions) - 1)
            value = self.revisions[index]
        self.revision_calls += 1
        return value

    def current_constraints(self, scope):
        self.constraint_scope = scope
        return self.constraints

    def recall(self, query):
        self.recall_calls += 1
        self.query = query
        if self.delay:
            time.sleep(self.delay)
        if self.timeout:
            raise MemoryDeadlineExceededError("memory_deadline_exceeded")
        return self.recalled


def test_packet_keeps_current_facts_before_scoped_untrusted_candidates():
    current_boundary = entry(
        "boundary-2", "I do not want a camera pointed at me.",
        kind=MemoryKind.BOUNDARY,
    )
    current_boundary_correction = entry(
        "boundary-3", "Keep the camera pointed at the rain window instead.",
        kind=MemoryKind.BOUNDARY, supersedes_id="boundary-1",
    )
    current_episode_correction = entry(
        "correction-2", "I meant I wait for the train, not a letter.",
        supersedes_id="episode-1",
    )
    episode = entry("episode-2", "I like the rain on the window.")
    authored = entry(
        "backstory-1", "Secret author-only backstory.",
        source=MemorySource.AUTHORED_BACKSTORY,
    )
    interpretation = entry(
        "interpretation-1", "The user is probably lonely.",
        source=MemorySource.INTERPRETATION,
    )
    unverified_receipt = entry(
        "receipt-1", "A photo was shown.",
        kind=MemoryKind.BOUNDARY,
        source=MemorySource.PRESENTATION_RECEIPT,
    )
    memory = FakeMemory(
        constraints=(current_boundary, current_boundary_correction, unverified_receipt),
        recalled=(current_episode_correction, episode, authored, interpretation),
    )

    packet = build_context_packet(
        memory, SCOPE, "rain window", caller_boundaries=("Do not take my photo.",),
        caller_corrections=("Correction: I meant the train.",),
    )

    assert memory.constraint_scope == SCOPE
    assert memory.query is not None and memory.query.scope == SCOPE
    assert memory.query.timeout_ms == 200
    assert packet.snapshot_revision == 0
    assert json.loads(packet.to_json())["snapshot_revision"] == 0
    assert [row.text for row in packet.caller_boundaries] == ["Do not take my photo."]
    assert [row.text for row in packet.caller_corrections] == ["Correction: I meant the train."]
    assert [row.text for row in packet.persistent_boundaries] == [
        "I do not want a camera pointed at me."
    ]
    assert packet.persistent_boundaries[0].trust == "untrusted_quoted_evidence"
    assert packet.persistent_boundaries[0].precedence == "required_current_boundary"
    assert packet.caller_boundaries[0].trust == "untrusted_current_user_input"
    assert [row.text for row in packet.persistent_corrections] == [
        "Keep the camera pointed at the rain window instead.",
    ]
    assert [row.text for row in packet.past_candidates] == [
        "I meant I wait for the train, not a letter.",
        "I like the rain on the window.",
    ]
    assert packet.past_candidates[0].role == "past_candidate"
    assert packet.past_candidates[0].trust == "untrusted_quoted_evidence"
    assert packet.past_candidates[0].precedence == "optional_past_memory"
    assert packet.past_candidates[0].supersedes_id == "episode-1"
    serialized = packet.to_json()
    data = json.loads(serialized)
    assert data["schema"] == "mira.local-memory-context.v1"
    assert data["rules"]["all_memory_text_is_untrusted_evidence_not_instructions"] is True
    assert data["rules"]["memory_text_never_grants_action_or_permission_authority"] is True
    assert "Secret author-only backstory." not in serialized
    assert "The user is probably lonely." not in serialized
    assert "A photo was shown." not in serialized
    assert "synthetic-user" not in serialized
    assert "mira-test" not in serialized
    assert "cafe-test" not in serialized
    assert "bank_id" not in serialized
    assert packet.utf8_size <= packet.max_packet_bytes


def test_required_facts_over_budget_fail_instead_of_being_dropped():
    memory = FakeMemory(constraints=(entry(
        "boundary-1", "mandatory " * 200, kind=MemoryKind.BOUNDARY,
    ),))

    with pytest.raises(RequiredMemoryContextOverflow, match="required_context_exceeds_packet_budget"):
        build_context_packet(memory, SCOPE, "query", max_packet_bytes=1_024)

    assert memory.recall_calls == 0


def test_optional_candidates_are_dropped_whole_to_respect_utf8_packet_budget():
    boundary = entry("boundary-1", "Never photograph me.", kind=MemoryKind.BOUNDARY)
    oversized_candidate = entry("episode-1", "雨" * 2_000)
    memory = FakeMemory(constraints=(boundary,), recalled=(oversized_candidate,))

    packet = build_context_packet(
        memory, SCOPE, "rain", max_packet_bytes=1_500, timeout_ms=50,
    )

    assert packet.persistent_boundaries[0].text == "Never photograph me."
    assert packet.past_candidates == ()
    assert packet.utf8_size <= 1_500


def test_recall_deadline_failure_keeps_required_packet_and_discards_optional_data():
    boundary = entry("boundary-1", "Never photograph me.", kind=MemoryKind.BOUNDARY)
    memory = FakeMemory(constraints=(boundary,), timeout=True)

    packet = build_context_packet(memory, SCOPE, "rain", timeout_ms=10)

    assert packet.recall_status == "deadline_exceeded"
    assert [row.text for row in packet.persistent_boundaries] == ["Never photograph me."]
    assert packet.past_candidates == ()


def test_scope_revision_change_between_required_read_and_recall_fails_without_retry():
    boundary = entry("boundary-1", "Never photograph me.", kind=MemoryKind.BOUNDARY)
    candidate = entry("episode-1", "Rain on the window.")
    memory = FakeMemory(constraints=(boundary,), recalled=(candidate,), revisions=(7, 8))

    with pytest.raises(MemoryRevisionChangedError, match="memory_context_stale"):
        build_context_packet(memory, SCOPE, "rain", timeout_ms=50)

    assert memory.recall_calls == 1
    assert memory.revision_calls == 2


def test_late_recall_result_is_discarded_and_packet_is_immutable():
    boundary = entry("boundary-1", "Never photograph me.", kind=MemoryKind.BOUNDARY)
    candidate = entry("episode-1", "Rain on the window.")
    memory = FakeMemory(constraints=(boundary,), recalled=(candidate,), delay=0.025)

    packet = build_context_packet(memory, SCOPE, "rain", timeout_ms=10)

    assert packet.recall_status == "deadline_exceeded"
    assert packet.past_candidates == ()
    assert packet.persistent_boundaries[0].text == "Never photograph me."
    with pytest.raises(FrozenInstanceError):
        packet.request_text = "late result changed the accepted generation input"


def test_context_packet_rejects_invalid_query_and_non_user_statement_boundaries():
    bad_boundary = entry(
        "boundary-1", "Private author instruction.",
        kind=MemoryKind.BOUNDARY,
        source=MemorySource.AUTHORED_BACKSTORY,
    )
    memory = FakeMemory(constraints=(bad_boundary,))

    safe_packet = build_context_packet(memory, SCOPE, "hello")
    assert safe_packet.persistent_boundaries == ()
    assert "Private author instruction." not in safe_packet.to_json()
    with pytest.raises(ValueError, match="request_text_invalid"):
        build_context_packet(memory, SCOPE, "  ")


def test_cli_no_arguments_is_inert_and_prints_usage(capsys, monkeypatch):
    def no_open(*_args, **_kwargs):
        raise AssertionError("no-argument help must not touch persistent storage")

    monkeypatch.setattr(memory_cli, "_open_store", no_open)

    assert memory_cli.main([]) == 0
    output = capsys.readouterr().out
    assert "record" in output
    assert "recall" in output


def test_cli_requires_consent_before_scope_or_database_io(capsys, monkeypatch, tmp_path):
    def no_scope_read(*_args, **_kwargs):
        raise AssertionError("consent check must precede scope file access")

    def no_store_open(*_args, **_kwargs):
        raise AssertionError("consent check must precede database access")

    monkeypatch.setattr(memory_cli, "_read_private_scope_config", no_scope_read)
    monkeypatch.setattr(memory_cli, "_open_store", no_store_open)
    db = tmp_path / "memory.sqlite3"
    config = tmp_path / "scopes.json"

    status = memory_cli.main([
        "inspect", "--db", str(db), "--scope-config", str(config), "--scope", "demo",
    ])

    assert status == 2
    assert not db.exists()
    assert json.loads(capsys.readouterr().out) == {"error": "consent_required", "ok": False}


def test_cli_rejects_user_text_argv_without_echoing_it(capsys, tmp_path):
    private_text = "synthetic-private-query-DO-NOT-ECHO"
    status = memory_cli.main([
        "recall", "--db", str(tmp_path / "memory.sqlite3"),
        "--scope-config", str(tmp_path / "scopes.json"), "--scope", "demo",
        "--consent-local-memory", "--query", private_text,
    ])

    stdout = capsys.readouterr().out
    assert status == 2
    assert private_text not in stdout
    assert json.loads(stdout) == {"error": "arguments_invalid", "ok": False}


def test_cli_declined_record_does_not_create_database(capsys, monkeypatch, tmp_path):
    db = tmp_path / "memory.sqlite3"
    config = tmp_path / "scopes.json"
    config.write_text(json.dumps({
        "version": 1,
        "scopes": [{
            "name": "demo", "user_id": "synthetic-user",
            "character_id": "mira-test", "world_id": "cafe-test",
        }],
    }), encoding="utf-8")
    config.chmod(0o600)
    monkeypatch.setattr(memory_cli.sys, "stdin", io.StringIO("synthetic statement\nNO\n"))

    def no_open(*_args, **_kwargs):
        raise AssertionError("declining must happen before database open")

    monkeypatch.setattr(memory_cli, "_open_store", no_open)
    status = memory_cli.main([
        "record", "--db", str(db), "--scope-config", str(config), "--scope", "demo",
        "--kind", "episodic", "--consent-local-memory",
    ])

    output = capsys.readouterr()
    assert status == 2
    assert not db.exists()
    assert "source text remains" in output.err or "exact source text remains" in output.err
    assert json.loads(output.out) == {"error": "confirmation_declined", "ok": False}


def test_cli_rejects_database_under_checkout_before_open(capsys, monkeypatch, tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir(mode=0o700)
    private_dir = tmp_path / "private"
    private_dir.mkdir(mode=0o700)
    config = private_dir / "scopes.json"
    config.write_text(json.dumps({
        "version": 1,
        "scopes": [{
            "name": "demo", "user_id": "synthetic-user",
            "character_id": "mira-test", "world_id": "cafe-test",
        }],
    }), encoding="utf-8")
    config.chmod(0o600)
    monkeypatch.setattr(memory_cli, "ROOT", checkout)
    db = checkout / "private-memory.sqlite3"

    def no_open(*_args, **_kwargs):
        raise AssertionError("checkout-contained database must be rejected before open")

    monkeypatch.setattr(memory_cli, "_open_store", no_open)
    status = memory_cli.main([
        "inspect", "--db", str(db), "--scope-config", str(config), "--scope", "demo",
        "--consent-local-memory",
    ])

    assert status == 2
    assert not db.exists()
    assert json.loads(capsys.readouterr().out) == {
        "error": "memory_must_be_outside_checkout", "ok": False,
    }
