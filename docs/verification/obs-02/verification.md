# OBS-02 verification — synthetic structured privacy repair

## Scope and root cause

Independent 11:04 audit found that `capture_text` rejected a direct synthetic `api_key`
object, while `capture_model_safely` wrapped the same text in a `GenerationContext` JSON
string. Flat regex review missed escaped inner keys, allowing an `approved` model-input
record and explicit raw export to retain the marker. Default recording was off; no real
credentials, private configuration, authentication caches, real user content or live calls
were used. Original audit evidence is retained under `var/mission/independent-audit/1104`.

Only production file changed: `apps/api/src/mira/adapters/diagnostics/privacy.py`.
The existing capture and export paths share this filter, so no port, Actor, bootstrap,
HTTP, frontend, wire schema, recording activation or audio-admission change is required.
Logical model serialization remains transient in memory. The privacy boundary now reviews
its decoded structure before raw enqueue and persisted JSONL serialization.

## Actual directed sequence

| Receipt | Actual outcome |
|---|---|
| 001, 002 | Infrastructure failures: current python and `.venv` lack pytest. Not behavioral RED. |
| 003-red-structured-privacy | Genuine behavioral RED: 56 failed, 5 passed. Exact GenerationContext repro included. |
| 004-green-structured-privacy | Same 61 tests/identical file hash: 61 passed. |
| 005-obs-regression | Existing OBS + new 61 + architecture: 108 passed. |
| 006-red-flat-pattern-budget | Two inherited regex CPU regressions: isolated subprocesses exceeded 3 seconds. |
| 007-green-flat-pattern-budget | Same two tests/file hash: 2 passed, 61 deselected, 0.15 seconds total. |
| 008-final-obs-regression | Final existing OBS + new 63 + architecture: 110 passed. |
| 009-spec-links | 88 requirements link to collectible tests; collection only, not behavioral acceptance. |

All usable test runs used the explicit existing `.venv313/bin/python`. No installation or
private environment scan. Each receipt preserves stdout/stderr, command, timestamp, exit
code and before/after hashes of the owned privacy seam and new test file. No owned source
changed during a recorded run. Unrelated source changes in this shared workspace are not
claimed covered by these narrow receipts. `pair-integrity.json` confirms identical test
hashes and stdout integrity for both RED/GREEN pairs. Counts are overlapping, not additive.

The new file is uniquely owned by the existing `providers` lane glob `tests/contracts/test_*.py`.
No quality catalog change was required. Aggregate affected/full/release remains director-owned.

## Implemented safety checks

- Recursively inspect bounded JSON objects, arrays and JSON-encoded string values, including
  decoded Unicode escape sequences and compatibility-width credential keys.
- Reject recognized credential/header/cookie keys, quoted credential assignments, duplicate
  keys, nonfinite JSON values, malformed/ambiguous structure and unsupported escape syntax.
- Inspect JSON fragments inside prose; malformed bracket/brace fragments fail closed.
- Redact injected active secrets and recognized assignment values after JSON decoding.
  A transformed raw record is labelled `redacted`, including direct reviewed capture/export.
- Enforce 128 KiB input/output UTF-8, depth 16, 4,096 visits and 1 MiB cumulative reviewed
  characters. Preserve bounded ordinary dialogue and logical model JSON when unchanged.
- Tighten inherited assignment/JWT regex token boundaries so long hyphenated nonmatches do
  not restart an unbounded prefix search at every hyphen.
- Existing uncertain/rejected text and unreviewed audio rejection, raw default off, explicit
  consent, queue revocation, retention, correlation and ordinary export behavior still pass.

These are conservative eligibility checks, not universal DLP, arbitrary encoding detection,
a spoken-secret detector, or a hard real-time performance guarantee. Audio admission is unchanged.
Safe-looking raw records still require the existing review/consent boundary. Some ordinary text
with ambiguous braces, brackets or escape syntax is intentionally dropped from development logs.

## Independent candidate validation

The 11:23 frozen candidate passed the independent unchanged 24-case matrix: original 18
credential-retention failures became zero. Two benign records and default-off behavior were
preserved. Adjacent independent tests confirmed quote/newline-containing injected-secret
redaction, rejection of uncertain audio, explicit consent, and export dropping a manually
injected historical unsafe nested record. Evidence: `var/mission/independent-audit/privacy-candidate-1123`.

Final source adds the tested regex token-boundary hardening. Frozen final candidate:
`var/mission/obs-02-candidate-1127`, with source, contract tests and owned hashes. Final privacy
SHA256: `e02331f91faf7b04e6b75a986121e1fe80794b3af7bbb9617eec7b4df5678d7b`.
Independent final-hash retest passed: unchanged 24-case matrix has zero credential retention,
two benign records preserved, and raw default off; all adjacent controls passed. The auditor
also independently ran all 63 supplied contract tests, including both subprocess guards:
63 passed in 0.37 seconds. All five candidate manifest files exist and hashes were independently
verified. Evidence: `var/mission/independent-audit/privacy-candidate-1127/{summary.json,
adjacent-summary.json,tests.log,junit.xml}`. Final canonical owned source/test hashes were
compared again with that immutable candidate and matched at 11:29 UTC. This is independent
agent verification of the narrow repair, not human/device/product-wide acceptance.

## Not run / not claimed

No Git commands, publish, deployment, real credential access, provider calls, raw real content,
actual audio privacy review, true-device tests, or product-wide acceptance. Existing OBS-01
verification remains historical evidence; it is not rewritten as if this defect had been absent.
