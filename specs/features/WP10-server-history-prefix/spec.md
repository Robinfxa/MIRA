# WP10 server receipt-before-input prefix

Base: source commit `ebb578dde665c9c7269e4a64b508182680b2fa66`; the shared workspace already contained unrelated uncommitted work. Owner: server history-barrier implementation. The existing `presentation_cutoff` is an inclusive client-asserted watermark over the shared visual-receipt/audio-progress sequence space; no public DTO or generated-contract change is needed.

### WP10-001 A new input requires the complete acknowledged prefix

Given an input with cutoff `N`, when the server has accepted fewer than `N` unique valid presentation facts whose global sequence is at or below `N`, then it returns retryable `history_pending` (HTTP 409) without committing that input. Prefix validation compares the bounded number of accepted unique facts with `N`; it never iterates to a client-supplied cutoff. Cutoff zero is complete. Visual receipts and typed audio progress share one prefix.

### WP10-002 Pending history revokes an authorized old branch without consuming input

Given an older server branch is still authorized and a new input names a cutoff with a missing prefix fact, when the input is rejected as `history_pending`, then the Actor revokes the old branch and cancels its owned generation/media work under its lock. The proposed request ID, activity sequence, input epoch, reliable decision input, fingerprint and user text are not committed. The old append-only history is retained, and a bounded fence lets valid late facts at or below the cutoff add history only. No synthetic local Stop activity is created.

### WP10-003 The exact pending request can retry

Given an input was rejected because its prefix was incomplete, when the missing valid fact arrives and the caller retries the identical request ID, activity sequence, cutoff, text and source, then the request can be accepted and its generation context includes the fact. A request already accepted remains idempotent and returns its normal current state.

### WP10-004 Stop remains immediate and late facts remain history-only

Given presentation history is incomplete, when Stop is received with the local cutoff, then Stop does not wait for the prefix. A later valid fact at or below the stop fence is retained as history only and cannot revive grants, phase, generation or prior authority.

## Scope and evidence

- No HTTP schema, generated contract, route, bootstrap or frontend edits in this feature.
- Consumers: `SessionActor.submit`, the existing HTTP `POST /sessions/{id}/inputs`, `/stop` and `/receipts` endpoints, and generation-context presentation history.
- Test resources: local Python 3.13.5 pytest/asyncio, the in-process `SessionActor`, FastAPI `TestClient` with the offline authored rehearsal fixture, and Event-based provider barriers. The affected tests are registered in the existing `actor` and `http` lanes.
- The receipt sequence/cutoff is client-asserted. This barrier enforces consistency for an honest client; it is not cryptographic authenticity or proof that a human saw, heard or understood anything. A direct/malicious client can lie about its cutoff or sequence.
- Permanently lost or rejected facts leave the prefix incomplete; the caller must recover the fact or create a fresh session. The Actor ledger remains in-memory.
- Tests use only local pure domain transitions, the in-process Actor and a loopback FastAPI rehearsal app. No provider, credential, device or public-network calls.
- Test owner/lane: `tests/unit/test_history_pending.py` in `actor`; `tests/integration/test_history_pending_http.py` in `http`. Contract and generated DTOs remain unchanged.
