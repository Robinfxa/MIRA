# M06 bounded current-session conversation projection

Source baseline: immutable `mira-silence-conversation-capture-20261005T1551Z`.
Owner lane: providers (`tests/contracts/test_bounded_conversation_context.py`, covered
by its unique existing glob). Consumers: Actor, direct/Codex generator, JEV input
and output, interrupted intent, story dialogue references. Application contracts
expand affected verification to all offline consumers; no public HTTP schema or
new dependency is introduced. Offline synthetic resources only. Actual semantic
quality, user devices, accounts and live providers remain unverified.

### M06BC-001: Whole evidence rows within existing budgets

Given 5/20/65/100 accepted turns and 2-, 1200- or 4096-character CJK replies,
when the production Actor and prompt builder run, then the existing 65536-byte
prompt ceiling is respected. The full in-process input/presentation ledgers remain
unchanged. Wire context keeps up to 32 recent inputs, 24 recent presented effects,
16 cumulative audio records and exact latest receipts for each control; smaller
byte budgets remove whole optional rows. No summarizer call is added.

### M06BC-002: Required present intent and qualified state

Given identical repeated input text and a linked ASR/text continuation separated
by Stop epochs, when history is projected, then every current linked input remains
verbatim with exact request/source/epoch identity, and source indices are mapped
to the bounded view. Current text, linked inputs, accepted prefix, explicit
boundaries/constraints and receipt-backed control state cannot be evicted.
Required evidence too large still fails closed. First-person quote references are
rebased or omitted, never pointed at a different row. Generated drafts are the
first optional data removed and are never presentation or hearing evidence.

The history descriptor records exact counts, source indices, a full source-history
binding digest and explicit loss of older detail. These are structural historical
facts, not an LLM or deterministic semantic summary. Latest control receipts mean
latest software presentation for each named control, not inferred physical state.
There is no claim that all earlier user meaning survives compaction.

### M06BC-003: Review preserves permission evidence

Given a long session, when production JEV input/output adapters assemble a review,
then full reliable input strings and explicit application constraints remain in
review evidence so an old restriction is not silently removed. Whole optional
presentation history can be omitted with counts and original history digest;
referent evidence remains included. Internal snapshots continue to bind the full
Actor state; current grant/Stop comparisons do not compare a shortened ledger.
JEV input and output stay under their existing request ceilings in the covered
small-input, large-reply cases. If required full restriction evidence alone is too
large, optional actions can still be held; ordinary conversation has no JEV gate.

### M06BC-004: Operational no-recall is honest and fenced

Given an optional local recall reader raises an operational OSError or timeout
before a packet is accepted, when the turn remains current, generation proceeds
once with no recalled evidence and `memory_recall_status=unavailable`. Permission
denial, malformed packet, scope, version, consent and privacy failures still fail
closed. A previously accepted packet that cannot be revalidated also fails closed.
Stop/new input/close fences run after await even when a reader ignores cancellation.

## Persistence boundary

This freeze adds no database, no automatic recording and no cross-session recall.
Full ledgers here are in-process only. Durable opt-in archive/reentry is a separate
slice requiring independent path/scope, pairing and recording/recipient consent.
Manual memory or story checkpoint consent cannot authorize transcript recording.

### M06BC-005 Recent visible referent retention
Given bounded history with old optional user rows and a recent acknowledged reply, when the wire is trimmed, retain that latest dialogue group before older optional inputs, while preserving exact current/linked input and actual control receipts. Never manufacture missing speech or summarize omitted evidence. If the latest reply itself cannot fit, it remains optional and may be wholly omitted; the current input must not be blocked by that optional history. The same existing count and byte ceilings apply.
