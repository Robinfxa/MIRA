# M06 Actor recall, explicit and opt-in

Status: implementation specification for the next bounded M06 slice. This is
read-only turn context assembly; it does not implement automatic recording,
Hindsight, learned personality, or a new authority source.

## Boundary

The existing SQLite store and immutable `ContextPacket` remain optional. A
trusted composition may inject one async, read-only `SessionMemoryBinding` into
an Actor. The binding owns a fixed `MemoryScope` and bounded read/packet
budgets. Default construction passes no binding and performs no memory I/O.
Only explicitly configured readers are reachable. There is no append, forget,
correction, or source-label operation on the Actor binding.

Every recalled string is untrusted evidence. It cannot change reliable user
inputs, current presented-item facts, author policy, current permissions,
presentation history, or a permit. It is carried as a separately labelled
`memory_evidence` field to generation and the output/review snapshot. Input
decision questions and their payload exclude memory text; the full local
snapshot digest still binds the immutable packet. No automatic recording is
introduced.

## Requirements

### M06AR-001: Default-off and compatible

Given no memory binding, when an Actor accepts a turn, then it performs no
memory reads, preserves the legacy generation/review projection and digests,
and does not create or write a memory store.

### M06AR-002: Fixed scope and independently bounded query

Given an explicitly composed binding, when the Actor starts a turn, then the
same trusted immutable scope is used for capture and revision checks; input
text cannot choose scope. The full actual request (up to the product's 8192
character limit) remains intact in `ContextPacket.request_text`. A separate
deterministic lexical retrieval query is bounded to 256 characters. Required
current facts and boundaries either fit or fail closed; only optional past
candidates may be omitted to satisfy the packet bound.

### M06AR-003: One packet across generation and review

Given a successfully captured packet, when generation and semantic input/output
review run, then generation and each `DecisionSnapshot` receive the identical
immutable packet object for that turn. Legacy output review also receives that
packet on its `GenerationContext`. Rebuilt state snapshots after receipt/audio
updates may refresh state facts, but they reuse the same memory packet.

### M06AR-004: Read races cannot revive canceled turns

Given a read that is pending or returns after Stop, new input/supersession, or
Close, when that result arrives (including after a reader suppresses task
cancellation), then the result is discarded and cannot invoke generation or
review or issue a grant. Reader I/O is async and bounded by the reader's single
worker; Actor transition locks are not held across packet assembly or revision
checks. Reader resources close only when ownership was explicitly transferred,
and cleanup is bounded.

### M06AR-005: Freshness before each new grant

Given the memory revision changes during generation or either review stage,
when a candidate would otherwise be accepted or the plan sealed, then an
out-of-lock revision check detects the stale packet before the grant/seal
transition. The turn fails closed with a stable safe code. This optimistic
snapshot check does not retroactively revoke grants already committed before
the revision change; no database transaction spans a model call.

### M06AR-006: Trust and privacy

Given any packet text, when it enters generation or output review, then it stays
typed as untrusted quoted evidence and cannot modify authoritative/current
facts. Input-JEV payloads omit memory text, while the locally checked snapshot
identity includes the same packet hash. Existing default diagnostics and
optional raw-dialogue capture do not record stored memory text. Reader failures
surface fixed actionable codes without raw error messages or stored content.

## Verification mapping

Tests use synthetic packets and event barriers only. They do not open a live
user database, call providers, send data, or write memory. The focused tests are
registered to the existing `providers` quality lane by the quality-registry
owner; Actor/application consumer lanes are run at handoff. This feature does
not validate production composition, a user's local database, or real-device
behavior.
