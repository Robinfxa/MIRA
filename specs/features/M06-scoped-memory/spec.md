# M06 scoped evidence store

Status: bounded local storage plumbing; not a complete character-memory feature.

## Boundary

This slice adds an explicitly opened, opt-in SQLite evidence store. It is not integrated into the default runtime or current response path. It does not implement Hindsight, async summarization, semantic embeddings, a ContextPacket, LearnedStance, a full versioned Canon/CoreSpec, storylets, personality learning, or current permissions/action authorization. Existing fixed author policy remains separate. `MemoryEventJournal` remains the existing ephemeral diagnostic journal and is not renamed or treated as durable memory.

The store accepts only typed source labels and an explicit server/local-supplied `(user_id, character_id, world_id)` scope. Its caller remains responsible for authenticating scope and source provenance. In particular, `presentation_receipt` must only be written by a trusted adapter after a real presentation receipt; generation, approval, or storage of a candidate is not a presentation receipt. Model-generated text cannot select scope or source labels. The local CLI, if composed separately, is limited to explicitly confirmed user statements.

Recall is optional evidence only. It preserves source and source-event version, excludes interpretations unless explicitly requested, and never authorizes actions, changes permissions, or upgrades an interpretation into a source fact. No live/user data is included in this feature's tests.

## Requirements

### M06MEM-001: explicit opening and private local storage

Given a new `SQLiteMemoryStore(path)`, when constructed, then no file is created until `open()` is called. Opening a safe new path creates a private owner-only database. Existing files and parent directories must be owned by the current user, private, and non-symlink; unsafe existing permissions are rejected without being changed. Storage is local SQLite only.

### M06MEM-002: scope and typed provenance

Given an entry with explicit user, character, and world scope plus a typed source, source-event ID, and positive source version, when it is stored, then retrieval is constrained to an exact matching scope and preserves all source/provenance fields. Scope/source-event ID/version is the idempotency key: exact matching retries return the original row; any changed source label or payload for the same event/version conflicts. This first slice stores one memory row per source event version; callers needing separate projections provide separate immutable event IDs. Invalid or missing scope/provenance is rejected. The store does not infer authenticity from a label.

### M06MEM-003: persistence and deterministic bounded recall

Given records in a scope, when a lexical query is recalled after close/reopen, then matching entries are returned in deterministic relevance order, with exact scope isolation and caller-enforced result-count, character, and 10–1000ms time budgets. Recall does not use a model, network, or ambient data source. It returns current heads only; when old wording matches, it can return the new head, whose supersession reference can be inspected using bounded correction history.

`scope_revision(scope)` is the latest monotonic append-only history sequence for that exact scope (or 0 when empty). A context assembler may read the revision before constraints/recall and re-check after; any mismatch must fail closed, without retry or treating the mixed packet as coherent.

### M06MEM-004: correction and supersession

Given a live entry and an explicit replacement that cites it with `supersedes_id`, when the replacement is appended, then the replacement is retrievable and the superseded ancestor is not. If the replacement is later forgotten, the ancestor still does not reappear. Other unrelated entries remain recallable.

`supersede(scope, old_id, replacement)` carries forward the original `MemoryKind`; history lookup from either side of the correction returns the bounded bidirectional chain and related tombstone events. Recall returns the current head with its source event/version and direct `supersedes_id`, never the old text as a current record.

### M06MEM-005: reversible soft forget

Given an entry and entries that explicitly depend on it, when `forget` records a tombstone, then the entry and its transitive dependents are suppressed from recall without physically deleting or rewriting their original rows. When `undo_forget` references that active forget event, then the event history records the restoration and the previously suppressed rows can be recalled again, subject to any other active tombstone or supersession. A prior ancestor never resurfaces in place of a superseding entry. No physical purge API is provided.

### M06MEM-006: hard storage and query bounds

Given oversize text, excessive record/event count, invalid query limits, unrecognized existing SQLite schema, or an unsafe existing filesystem object, when storage or recall is attempted, then the operation fails closed with a bounded, non-content-revealing error and does not modify existing unsafe permissions. Stored text is passed through the existing project `PrivacyFilter`; any filtering or error rejects the write unchanged. This is a second defense against known credential shapes, not a universal secret detector.

### M06MEM-007: interpretations remain typed and optional

Given an interpretation alongside source evidence, when a default recall is made, then interpretation entries are omitted. If explicitly requested, they are returned with `source=interpretation`, never merged into or relabeled as the underlying source. No recall entry conveys a permission or action.

`MemoryKind.BOUNDARY` is a separate explicit axis from provenance and only `user_statement` rows can enter `current_constraints(scope)`. Constraint recall returns latest valid heads and fails closed if its hard item/character budget is exceeded rather than silently truncating. Caller confirmation and provenance authentication remain caller responsibilities.

## Limits and non-goals

The first slice uses deterministic lexical matching rather than semantic retrieval. It is synchronous local SQLite plumbing with an append-only entry/mutation history, not the asynchronous history organizer proposed by M06. Forgetting is a reversible suppression event, not physical erasure; the original text remains in the private database until a separately specified purge/deletion lifecycle exists. Exact time mapping, trustworthy client receipt validation, multi-device conflict handling, outbox delivery, automatic extraction, and user-facing memory controls beyond the integration's explicit workflow remain out of scope.

## Test and consumer mapping

The implementation is owned by the existing `providers` test block for the storage contract; any separately composed CLI belongs to `tooling`. The new evidence is scoped to synthetic entries and temporary local databases. Existing release or device results do not count as M06 validation.
