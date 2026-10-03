# WP01 JEV verification · 2026-10-03

## Result

Final focused run: **100 passed** = 97 JEV synthetic review/HTTP contract tests and
3 selected architecture guards. Spec-link collection: 44 requirements across currently
registered features, including the 7 WP01 JEV requirements. Compile check passed.
The final report's covered source fingerprints did not change during the run.

Evidence: `runs/007-final-focused/report.json`, command stdout/stderr and JUnit.
Python: shared .venv313 (3.13); httpx 0.28.1, pytest 9.0.2. No installation was performed.

## Actual TDD sequence

| Run | Observed result | Scope |
|---|---|---|
| 001-red-core | 8 failed | Collected behavior assertions against initial inert implementation |
| 002-green-core | Identical 8 passed | Real adapter implementation; test source hash matches 001 |
| 003-red-confidence | 1 failed, 1 passed | Uncertain reject was incorrectly labeled substantive reject |
| 004-green-confidence | Identical 2 passed | Low-confidence reject is UNKNOWN |
| 005-red-http-contract | 1 failed | Malformed HTTP representation conflated with network failure |
| 006-green-http-contract | Identical 1 passed | Typed response-contract failure keeps causes distinct |
| 007-final-focused | 100 passed | 97 provider tests + 3 layer guards, then links and compile |

These are cumulative/regression runs, not additive independent sample counts. They
validate deterministic plumbing and synthetic schemas; they do not measure model
accuracy. Earlier and later evidence is retained under unique names. Each receipt
hashes only the relevant owned scope (the final receipt also includes shared contract
and effect-enum dependencies), rather than pretending concurrent unrelated edits are
part of one immutable repository-wide snapshot.

## Coverage

Exact candidate/context/accepted/presented identity; request-unique answer coverage;
missing/extra/replayed answers; wrong model and primitive; duplicate JSON keys;
NaN/Infinity/bool/out-of-range/nonmaximum probabilities; bad usage; malformed UTF-8 /
JSON; depth and size failures; controls and explicit SPEECH versus SUBTITLE; MEDIA
rejection; missing/stale/unvalidated policy; semantic reject versus unknown;
finite concurrent request admission; deadline/cancellation including uncooperative
late responses; fixed-origin Bearer HTTP construction; no redirects/proxies/retries;
response encoding/stream bounds; redacted errors and inert construction.

The focused HTTP tests use httpx.MockTransport plus synthetic async byte streams, never
an external socket. Synthetic API strings are not real secrets. No .env, credential
cache, ADC file or authentication file was read. No real model catalogue/inference,
paid request, account change, Git mutation or push occurred.

## Integration status and limitations

A read-only `tools/check.py --files <owned code/tests/specs> --plan` attempt after the
focused run exited 2 because `tests/unit/test_mira_auth.py` was not yet assigned in the
shared test registry. The integration owner was immediately told; this worker did not
edit the shared registry. That planner failure does not invalidate the focused test
result, and the focused result is not a passing affected/full integration run.

Not run: authenticated catalogue, inference, Chinese policy calibration, input-decision
quality, production factory activation, full/affected snapshot integration, remote CI,
real speech, pixels, devices or mobile delivery. No live_ready claim is made.

The director owns the final shared contract producer, loader/bootstrap admission,
runtime dependency packaging and immutable-snapshot aggregate checks. Parent/user
owns secure credential entry and the bounded smoke approval. The separate Input
Decision slice is proposed in integration.md and is still not implemented.

## Later confidence correction · 2026-10-03 10:45 UTC

The historical statements above describe that earlier run. Input Decision was since
implemented separately. The confidence wire-precision mismatch now has an independent
primary-example/observed-numeric RED/GREEN pair and a 193-test targeted rerun. See
[the correction addendum](confidence-contract-correction.md). Authenticated HTTP 200
connectivity is established by director-owned diagnostics; post-fix live parser and
Chinese semantic-calibration success are not claimed by this offline correction.
