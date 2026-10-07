# M06 paired local memory management

Status: implementation candidate; synthetic offline tests only. This feature is
separate from the accepted read-only Actor-memory boundary.

Only an explicitly enabled local-management launch combined with successful
same-origin operator pairing may open a writer. The server fixes the database
path and `MemoryScope` before startup. A browser request cannot select a
database, scope, source label, actor session, or evidence provenance. Without
the separate management launch opt-in, status reports disabled without opening
or creating a database.

The UI may display a bounded page of current `USER_STATEMENT` heads and their
direct reversible soft-forget tombstones. Older corrected entries and all
other provenance classes are excluded. Operations are exact, manually entered
records/corrections, soft-forgets, or restores. They require `confirmed: true`
and a scope revision from the current page. These operations do not perform
automatic extraction, transmission to a model, or physical deletion.

### M06LOCALMEMORYMANAGEMENT-001 Separate management opt-in and paired lifecycle

Given memory recall is configured, opening management requires an independent
local-management opt-in and a successfully paired operator. The disabled status
path performs no private-store I/O. An enabled manager owns a single bounded
writer worker, opens only an existing private database, and closes on revoke
and application shutdown.

### M06LOCALMEMORYMANAGEMENT-002 Bounded, provenance-safe current list

Given a fixed server scope, listing returns at most the requested bounded page
of current correction heads sourced from `USER_STATEMENT`, ordered by newest
history sequence. It never returns authored backstory, interpretations,
presentation receipts, generated visualizations, or superseded ancestors.
Active direct forget tombstones expose only the exact reversible event ID and
timestamp. A revision-bound opaque cursor fails closed when the scope changes.

### M06LOCALMEMORYMANAGEMENT-003 Explicit CAS mutations only

Given a strict operation record with a valid UUID operation ID, expected scope
revision, and `confirmed: true`, the server may record or correct bounded UTF-8
text, soft-forget a current user statement, or restore one active forget event.
Source, scope, IDs, event versions, timestamps, and supersession links are
server-owned. Expected revision comparison and mutation occur in one SQLite
transaction, so an external CLI edit cannot be overwritten.

### M06LOCALMEMORYMANAGEMENT-004 Idempotent operation reconciliation

Given an operation may have committed before the connection was cancelled, a
retry with the same UUID and exact payload returns the committed result without
adding another event. A different payload with that UUID returns a fixed
conflict. A stale uncommitted operation returns a stale-revision error and the
current revision. Retried soft-forgets never create duplicate forget events.

### M06LOCALMEMORYMANAGEMENT-005 Pairing, origin, and fixed scope

Given management endpoints, only the paired app cookie plus the established
same-origin semantics authorizes access. Session tokens do not authorize these
endpoints. Cross-scope IDs behave as not found. Unknown request fields, source
labels, scope overrides, and arbitrary file paths are rejected.

### M06LOCALMEMORYMANAGEMENT-006 Bounded asynchronous worker and shutdown

Given any number of concurrent callers, the manager admits at most one active
or queued store operation; further calls fail as busy rather than building an
unbounded queue. SQLite never runs on the event loop. Stop of character output
does not falsely cancel a submitted durable edit. Revoke closes management
authority; a late result cannot re-open it. An uncertain mutation outcome is
reconciled by its durable operation ID, not described as rolled back.

### M06LOCALMEMORYMANAGEMENT-007 Safe responses and diagnostics

Given validation, conflict, timeout, cancellation, or storage failure, public
responses and normal diagnostics contain fixed codes and request IDs only.
They never reflect memory text, pairing codes, database paths, or credential
content.
