# Paired local-memory management panel

This is a small user-managed browser surface for the nextstage local-memory
service. It is a separate opt-in from Actor recall and from provider
transmission permission. No real user data, credentials, provider, or browser
are used by this feature's tests.

The panel may mount only after the operator pairing gate has succeeded and
only when the server marks the page with the exact management-enabled
declaration. Without both conditions, the app performs no memory-management
request. The ordinary mock, replay, rehearsal, and no-memory flows remain
unchanged. The panel is a secondary collapsed disclosure; opening it requests
one bounded page from the paired same-origin service.

## Requirements

### M06MMUI-001: disabled by default and paired-only

Given a page without both the operator-pairing marker and the exact
management-enabled marker, when the UI starts, then it does not mount the panel
or request memory-management data. When both markers exist, it still waits for
successful pairing before mounting. Local write consent is distinct from
launch configuration and from existing permission to transmit selected recall
evidence to Codex and TypeSafe/JEV. The page must never claim that a local
record is guaranteed to remain local forever.

### M06MMUI-002: bounded manual records and revisions

Given a paired enabled panel, opening the collapsed disclosure fetches a
bounded page from the fixed same-origin service. It first verifies the
management status, then reads `/api/v1/memory-management/entries` with a page
limit of 20 and an optional opaque cursor, with at most 20 pages in one panel
visit; if more pages remain, the UI says so rather than implying completion.
The page response body is capped at 512 KiB, each stored entry at 16,384
Unicode code points and 64 KiB UTF-8, and the combined page text at 128 KiB.
The manual write editor separately caps new text at 4,096 Unicode code points
and 16 KiB UTF-8. The page contains only current USER_STATEMENT correction
heads and active-forget event metadata needed for
restore. A continuation cursor is accepted only when it is canonical base64url
for the displayed revision and next sequence, so private text and arbitrary
server strings are never copied into request URLs. The UI never loads unbounded
history. The server-selected scope is never selected by browser fields,
database paths, IDs for user/character/world, source labels, or
presentation/history claims. Record text is manually typed; there is no
transcript extraction, automatic capture, model inference, or summary
generation. The kind selector distinguishes ordinary optional-recall memory
from an explicitly selected boundary retained in every packet; ordinary
preferences are not silently upgraded to boundaries. Existing records at the
larger store limit remain readable even when the new write editor is stricter.

### M06MMUI-003: readable explicit confirmation per operation

Given a proposed record, correction, soft-forget, or restore, when the user
requests the operation, then the UI first shows a readable exact summary and
requires a separate explicit confirmation before sending it. Each mutation
includes a new operation UUID, the currently displayed expected revision and
`confirmed: true`, and only operation-specific target/text data: `record`
contains text and kind, `correct` contains an entry ID and replacement text,
`forget` contains an entry ID, and `restore` contains a forget-event ID.
Duplicate submission is fenced while confirmation or a request is pending.
The browser never sends database/scope authority or source provenance.
Restore cancels one named forget event; if another active forget still applies,
the UI does not imply that the record became recallable.

### M06MMUI-004: safe outcomes, Stop, close, and revoke

Given a stale revision, duplicate/conflicting operation, rejected request, or
uncertain transport outcome, when the response is handled, then the UI does not
invent success or automatically retry a write. A user-triggered retry of an
uncertain operation uses the exact frozen request body and operation ID so the
server's idempotency contract can report its result; if that request was not
committed, it may execute the original operation. Reconciliation requires
current local-write consent; withdrawing it prevents replay and does not imply
that a previously sent operation was undone. Conflict/rejection outcomes
require an explicit read refresh before another write. Raw response
bodies, memory text and internal errors are not used as diagnostics. Only a
validated UUID-shaped `X-Request-ID` may be shown as a diagnostic locator.
Stop cancels unsubmitted confirmation and clears the unsubmitted draft while
immediately stopping character output. It never presents an already submitted
write as undone. Close/revoke aborts pending browser work, clears all private
memory text from the panel, fences late callbacks, and leaves the server-side
operator revocation to the existing pairing gate. A paired-management 401/403
also clears the private list and drafts and disables writes until refreshed.

### M06MMUI-005: private rendering and retention disclosure

Given returned or user-entered memory text, the UI renders it only via
`textContent` and never puts it in a URL, local/session storage, clipboard,
console, or default diagnostics. The panel explains that forgotten text remains
in local append-only history and may be restored; forgetting is not secure
erasure and cannot recall earlier provider transmission. Future enabled recall
may send selected evidence to Codex generation and TypeSafe/JEV output review.

## Verification scope

Tests use fake DOM/fetch with the real HTML selector ordering and semantics and
synthetic memory strings only. They do not use a real browser, loopback app,
database, user memory, pairing code, model, or provider. The actual interface
layout and rendered pixels remain subject to later user acceptance.
