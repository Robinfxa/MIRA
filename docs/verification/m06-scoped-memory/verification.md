# M06 scoped evidence store verification

**State:** first bounded local storage slice; not full M06 implementation or integrated default runtime.
**Source:** next-stage working tree `mira-recovery-20261003`.
**Timestamp:** 2026-10-04 UTC.

## Implemented boundary

- `mira.domain.memory` defines immutable scope, source, kind, entry, query, ISO-8601 timezone-qualified timestamp strings, and soft-forget event values. A row needs an explicit `user_id` / `character_id` / `world_id`, source event ID, and positive source version.
- `mira.application.ports.memory.MemoryPort` is the narrow seam. `SQLiteMemoryStore` is a concrete, synchronous local adapter which is opt-in and performs no constructor I/O. It is not constructed by the default app.
- Exact scoped source-event/version retries return the original row only when source and payload are unchanged; conflicting source labels or payloads fail. New versions of a source event must continue its supersession chain. Corrections cannot change source authority; only a user-statement boundary can enter `current_constraints`.
- Recall is local, lexical, deterministic, limited by item count, returned characters and a 10–1000ms query budget. It returns latest valid heads, including an updated head when an obsolete version matched the wording. `history(scope, entry_id)` exposes the bounded correction chain and related forget/restore events.
- `scope_revision(scope)` reads the latest append-only `memory_history.seq` for the exact scope. Context assembly can bracket mandatory and optional reads with that revision and fail closed if it changes.
- `forget` is an append-only, reversible suppression event. It suppresses the target and transitive explicit dependents. `undo_forget` appends a restore event; overlapping forgets remain active until each event is undone. No physical purge is offered, so forgetting here does not erase original text from the private database.
- New databases/files are created under an owner-private directory and with mode 0600 on POSIX. Unsafe owner/mode, symlink, hardlink, sidecar or unknown-existing-schema cases fail closed; existing unsafe files are not chmodded. Existing content passes the project `PrivacyFilter`; any changed or rejected text is refused. This is only a second defense for known credential shapes, not general secret detection.

## Test evidence

The focused module uses synthetic facts and pytest temporary directories only. No live user record, `.env`, credential, provider, UI or network was read or exercised.

Latest recorded command:

`/workspace/shared/mira-combined-runtime-0947/.venv/bin/python -m pytest tests/unit/test_scoped_memory.py tests/architecture/test_boundaries.py::test_domain_has_no_framework_config_or_adapter_dependencies -q`

Latest run `002-domain-clean-green` exited 0: **22 passed in 0.11s**. Append-only output, hashes and source-before/after fingerprints are saved beside this file under `runs/002-domain-clean-green/`. Earlier run `001-core-green` recorded 20 storage tests before the final pure-domain import and revision-guard changes; it is retained as historical evidence, not treated as validation of the latest source.

`python -m py_compile apps/api/src/mira/domain/memory.py apps/api/src/mira/application/ports/memory.py apps/api/src/mira/adapters/memory/*.py tests/unit/test_scoped_memory.py` exited 0. The Python `ruff` executable was not installed in the supplied baseline environment, so no Ruff result is claimed. Full affected quality, integration CLI, packaging and release checks were not part of this focused run.

During an earlier unsaved development iteration, focused execution produced genuine failing cases while correction-history and interpretation-order behavior was incomplete. Those intermediate terminal results were not captured as a record_check RED/GREEN pair; this note does not claim a formal saved RED/GREEN pair.

## Architectural limit

This is storage/projection plumbing only. It is not an asynchronous index/organizer or Hindsight adapter; it does not auto-extract from conversations, form a ContextPacket, write an outbox, or enter the live response path. Source-label authenticity, confirmed user intent and server/operator scope assignment remain caller responsibilities. A `presentation_receipt` must only be supplied by a trusted adapter after an actual client display/playback receipt; generated or approved content is not evidence of presentation. Recall never grants actions or overrides current permissions.

The existing fixed author policy / `AuthorPolicy` is an earlier partial substrate; this slice does not turn it into a full versioned Canon/CoreSpec, implement LearnedStance or automatic personality learning, or replace current application authority. `MemoryEventJournal` remains ephemeral bounded diagnostic metadata, not persistent memory. The user/device acceptance gap remains separate and open.
