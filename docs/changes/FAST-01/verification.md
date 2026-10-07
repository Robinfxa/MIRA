# FAST-01 verification

Frozen source baseline: mira-integration-20261005T2238Z (no Git metadata). Isolated implementation: mira-fast-tier-20261005T2244Z.

- 001-red: original 41 tests, 39 failed/2 passed before implementation.
- 002-green: real failed attempt, 40 passed/1 failed because the HTTPX JSON fixture was eagerly consumed instead of streamed; retained unchanged.
- 003-final-tests-baseline-red: corrected/extended final test file against copied original implementation, 46 failed/3 passed. This is a baseline negative control after the initial implementation, not a claim that all added tests preceded implementation.
- 004-final-tests-green: identical final test file, 49 passed.
- 005-regression-green: original direct transport/diagnostic/header/terminal/CLI cases, 128 passed.
- 006-returned-fast-red: added documented returned Fast alias and standalone SSE error cases, 2 failed/49 passed.
- 007-returned-fast-green: same final 51-test file, 51 passed.
- 008-recovery-expectation-green: all final 51 tier tests plus 24 original recovery cases, 75 passed.

Raw run receipts are retained separately as external development evidence by the integration owner; they are not promised as part of the public source projection. Each retained receipt has real output, exit code and source hashes. All reported runs have zero source changes during execution. Source pin, optional-tier semantics and bounded user-local instructions are in docs/development/DIRECT_SERVICE_TIER.md.

The first affected aggregate passed ten lanes but found 21 recovery cases whose mock still asserted the old five-field request. Their expected request now explicitly includes priority; all recovery assertions remain. The corrected affected rerun completed with all ten other lanes passed and providers 2551 passed/1 failed. The remaining failure was the unchanged story-persistence close test `test_audit_session_replacement_waits_for_close_and_has_isolated_actor_epoch`: its checkpoint thread was still alive immediately after close. All tier/recovery cases passed. This unresolved aggregate failure is handed to the integration owner; no full-green or release claim is made. Both aggregate receipts are retained externally. The catalog ownership comment intentionally triggers the repository's conservative full offline selection. Package/release/live/device checks are not part of this worker's scope; the integration owner controls release.
