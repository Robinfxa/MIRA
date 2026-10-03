# OBS-02 — Bounded structured privacy review

Status: narrow implementation and directed verification complete; raw defaults remain off, synthetic tests only.
Baseline: canonical working source on 2026-10-03, OBS-01 plus independent 11:04 audit.
Owner: diagnostics privacy/recording seam and provider-owned contract tests.
Consumers: existing capture_model_safely, raw capture, and export revalidation.
Resources: standard library, existing pytest, isolated synthetic temporary files; no network,
private configuration, authentication files, or real audio/content. Full/affected integration
remains the director's responsibility. No Actor, HTTP, frontend, schema or bootstrap changes.

### OBS02-001 — Escaped model envelopes never persist
Given a synthetic credential envelope as user text or model output, when logical model content
serializes it inside a dataclass/JSON string, then raw capture rejects the record before enqueue
and persisted-raw serialization, including nested dict/list/string JSON, Unicode-escaped keys,
recognized credential assignments and embedded JSON fragments. Export revalidates legacy or
injected records with the same defense and skips uncertain records despite prior approval.

### OBS02-002 — Bounded conservative eligibility
Given malformed/ambiguous JSON-shaped text, duplicate keys, excessive nesting, nodes, processing
or buffer size, when privacy review cannot establish eligibility within fixed budgets, then it
rejects the whole record. It does not decode arbitrary non-JSON escape formats. This is a bounded
recognizer for specific credential envelopes, not universal DLP or novel-secret detection.

### OBS02-003 — Preserve existing safe behavior
Given safe ordinary dialogue or bounded logical model content, capture remains available only
under explicit raw consent. Injected active secrets and recognized credential values are removed
from decoded text values, including JSON escape forms. Uncertain/rejected review and unreviewed
audio remain ineligible. Existing OBS-01 event, retention, queue and export contracts remain.

## Eligibility limits

Review caps are 128 KiB UTF-8 input/output, depth 16, 4,096 visited nodes and 1 MiB total
reviewed characters. Plain-text bracket/brace fragments and escape-like syntax that cannot be
validated as bounded JSON are conservatively ineligible. Known active values are redacted after
JSON decoding. Existing raw audio attestation remains unchanged; no automatic audio admission.
Logical-model JSON exists only transiently before this check; no rejected text reaches the raw
queue, disk JSONL or revalidated export. Flat key/JWT patterns use token boundaries to avoid
restarting an unbounded key scan at every hyphen. These are eligibility limits, not universal
secret detection or a hard real-time CPU guarantee.
