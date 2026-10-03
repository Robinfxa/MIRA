# Verification: semantic composition

Offline synthetic mechanics, 2026-10-03. Common source baseline
`ebb578dde665c9c7269e4a64b508182680b2fa66`; interpreter `.venv313/bin/python`.
No claim of model-quality calibration, actual provider readiness or physical audio.
Evidence directories: `docs/verification/wp01-semantic-composition/runs/`.

## Actual ordered evidence

- 001-red-composition → 002-green-composition: 17 failed/1 passed against interface
  stubs and old output behavior → same 18 passed. Includes actual old raw-only
  contract ALLOW becoming fail-closed without explicit synthetic mode.
- 003-core-regression: 215 passed, source changes 0; existing JEV/input/producer,
  new composition and seven architecture guards.
- 004-red-owner-identity → 005-green-owner-identity: same three tests failed then
  passed for unknown/mismatched receipt and accepted-but-unissued identities.
- 006-composition-regression: 24 passed, source changes 0.
- 007-red-actor-seam → 008-green-actor-seam: same seven Actor behavior tests failed
  for the missing injection seam then passed. Event-barrier races cover local Stop,
  one-in-flight/latest-pending, context refresh, UNKNOWN no-fallback and seal rejection.
- 009-red-bootstrap-injection → 010-green-bootstrap-injection: missing Providers
  injection failed, then the same test passed. Existing live rejection stays intact.
- 011-semantic-actor-regression: 141 passed. NOT frozen integration evidence because
  concurrent `tools/quality_run.py` changed during the run.
- 012-final-scoped-regression: 351 passed. NOT frozen integration evidence because
  three concurrent tooling/spec files changed; exact paths are retained in its report.
- 013-red-cancelled-review-diagnostic → 014-green-cancelled-review-diagnostic: same
  one test failed then passed; a swallowed cancellation must not log late input success.
- 015-red-input-diagnostic-aliases → 016-green-input-diagnostic-aliases: same six
  fixed diagnostic fault mappings failed then passed; unrecognized suffixed text
  remains UNKNOWN, no raw error reflection.
- 017-final-scoped-stable: 361 passed, source changes 0. Includes both semantic
  timeout-suppression controls, input/output receipt races, exact ASR source/idempotence,
  existing JEV/input/producer, all three diagnostics suites, Actor/replay, HTTP/replay,
  voice/audio-progress and seven architecture guards. This is the final scoped rerun,
  not 361 new tests, not full/release.

RED/GREEN paired targeted tests retained their test-file bytes. Initial interface
stubs were collectable; missing module/import collection errors are not claimed RED.
Records were never overwritten. No source was reverted merely to manufacture RED.

## Remaining verification

Director owns frozen-source affected/full/release runs after integration. This slice
made no frontend/schema changes and did not independently rerun browser/Node checks.
No git mutation, push, provider network calls, credentials, grants or installation.
Input/output calibration is separate and absent by default. Representative Chinese
semantic evaluation is independent work, not substituted by these parser/state tests.

Implementation paths were released to the integration owner at 11:12 UTC. Exact
construction, runtime currentness and narrower ASR provenance gap are in integration.md.
- 018-spec-links: 79 repository requirements reference collectable tests, source
  changes 0. Collection/link evidence only; not additional test execution or calibration.
