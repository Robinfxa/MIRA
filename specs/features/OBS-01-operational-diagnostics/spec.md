# OBS-01 — Safe operational diagnostics and explicit development recording

Status: offline implementation and focused verification complete; no real recording activation or provider calls.
Source: explicit user addendum on 2026-10-03, distinct from PDF engineering suggestions.
Baseline: imported foundation 0.4.1, active 24-hour delivery plan; deadline unchanged.
Owner: diagnostics core worker, new adapters/diagnostics, diagnostic port/events, export tool.
Test owner registration: director assigns contracts to providers and export tests to tooling.
Consumers: narrow Actor/media/HTTP/bootstrap/config hooks and visible frontend runtime-status banner
are integrated under explicit owner assignment. Live provider and browser visual verification remain separate.
Resources: Python standard library, existing pytest, synthetic temporary files only; no installs/network.

### OBS01-001 — Safe correlated event contract
Given request/session/turn/effect identities, when an operational event is accepted, then its
allowlisted fields preserve correlation through pseudonymous IDs with stage, outcome, known error
code, bounded duration and explicit cancellation reason. Arbitrary payloads, exception messages,
headers, dialogue, credentials and raw media never enter ordinary records.

### OBS01-002 — Honest actionable failures
Given 401, 403, 429, timeout, permission denial, unknown failure, user Stop or disconnect, then a
stable code and actionable Chinese message distinguish known failure class and cancellation reason.
A provider status is evidence of that class only, never proof of an unobserved underlying cause.

### OBS01-003 — Bounded resilient local recording
Given a full queue, quota, retention expiry, invalid record or filesystem failure, when diagnostic
recording runs, then it drops safely and exposes bounded counters without crashing service work.
Writes are JSONL, bounded, rotated, private and symlink-resistant. No network telemetry.

### OBS01-004 — Explicit development-recording mode
Given default configuration, raw capture is off. When explicitly opted into with operator consent,
status visibly identifies active development recording. Disabling revokes pending raw writes.
Original dialogue/model text and audio are eligible only after a separate content review; uncertain
or rejected records are dropped. Credential-shaped text is removed even in this mode. Credentials,
auth tokens, Authorization headers and unreviewed binary audio are never eligible. Automated
spoken-secret detection is not universal; audio requires explicit reviewed-safe attestation and
cannot be automatically approved solely by an ASR transcript. Existing files expire/delete under
bounded private retention, and no raw files belong in Git or ordinary diagnostics exports.

### OBS01-005 — Safe reproducible diagnostic export
Given local diagnostic files, one command exports revalidated sanitized events and fixed metadata.
It never opens arbitrary paths, environment files or credentials; symlinks and malformed/injected
records are skipped. Raw inclusion needs a separate explicit consent switch and warning; normal
exports exclude raw files even while recording is active. Export is local, not automatic sharing.

## Acceptance limits

Core offline tests prove contract/IO boundaries, not live integration, browser UI visibility, true
provider entitlement or universal secret detection. A reviewed raw record can retain only approved
content; credential-like text may be redacted and uncertain records are lost intentionally. Logging
is best-effort operational evidence, not durable session history or a second state authority.
