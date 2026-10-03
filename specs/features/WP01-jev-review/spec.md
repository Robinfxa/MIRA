# WP01 JEV / TypeSafe review adapter

Status: offline adapter slice, not production semantic approval or a connected account.
Common baseline: ebb578dde665c9c7269e4a64b508182680b2fa66. Deadline remains
2026-10-04 08:53:50 UTC; this work does not restart it.

## Ownership and test scope

Owned code: adapters/review/jev.py and jev_support; tests/contracts/test_jev_review*.py.
Provider lane owns these tests. Consumers: bootstrap composition, ReviewBackend,
SessionActor; guards: architecture/config/actor/http. Shared contracts, configuration,
loader, actor, domain, HTTP and registry are unchanged. Synthetic tests use injected
transport and no account, credentials, network, media or device. The director owns
an immutable-snapshot affected integration run and any shared producer integration.

### WP01JEV-001 Exact content and contract binding
Given a trusted immutable contract for a frozen context and candidate, review sends
those exact values with O1–O6 and every candidate effect covered. Changing any context,
accepted/presented prefix, candidate, or policy invalidates binding. A fixture name has
no authority here. Missing or invalid contract means UNKNOWN before external calls.

### WP01JEV-002 Strict current request response
Given a response, model, question-key set and primitive shapes must match this exact
request. Keys include a unique nonce and digest. Missing/extra/stale answers, malformed
JSON, duplicate keys, nonfinite/bool/out-of-range probabilities, unsupported choice,
bad sums/confidence, invalid usage and oversized bodies yield UNKNOWN.

### WP01JEV-003 Semantic outcomes remain distinct
All necessary choices must be confidently allow. Reject stays reject with no alternate
judge or retry; ambiguity and low confidence stay UNKNOWN. Provisional thresholds do
not imply Chinese calibration. A caller-supplied calibration admission references the
fixed model and question policy; absent admission can test connectivity but never ALLOW.

### WP01JEV-004 Bounded transport and costs
Explicit finite request budget defaults to zero; each attempt consumes a slot before
awaiting, including timeout/error/cancellation. No automatic retries, redirects,
environment proxies, key discovery or model-alias changes. Deadline and body limits
apply; cancellation propagates. Caller owns provider-wide spend and admission.

### WP01JEV-005 Capability limits
JEV is text-only. MEDIA always UNKNOWN pending separate real-pixel D-M. POSE/SCENE
must exactly match trusted contract controls and also receive semantic review. Subtitle and distinct SPEECH
text are reviewed, not whitelisted. Empty or unsupported effects cannot get ALLOW.

### WP01JEV-006 Privacy and diagnostics
Key enters a dedicated injected transport, never the context, model questions, result,
repr or logs. Fixed reason codes never echo response/exception data. Detailed results
contain only verdict, model, token counts and opaque request/contract digests.

### WP01JEV-007 Integration remains honest
Existing ReviewBackend.review signature is unchanged. No automatic factory activation,
no missing facts invented, no fixture path applied to live data. HTTP/schema, live audio,
Chinese quality, rate/latency and account authorization remain independently unverified.
