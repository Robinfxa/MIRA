# BUDGET-RECOVERY-01: explicit historical consumption

### BUDGETRECOVERY01-001 Preserve count and conservative reserved cost through recovery

Given historical per-request rows were lost but verified aggregate count and conservative reserved/charged amount survived, the evaluator may read an explicit versioned `historical_aggregate` separate from new rows. Global attempt sequence, cap checks, charge checks, continuation upgrade and reports include both parts. Recovery must not fabricate old request records or refund unknown costs. Malformed versions/counts/amounts/duplicate fields fail closed, and a missing operational ledger is never automatically initialized. Existing ledgers with no aggregate retain their original meaning. This is offline accounting compatibility, not approval of another provider request.

Owner: tools/jev_evaluate.py and its existing tooling tests. No provider calls, credentials or operational ledger are touched by the contract tests. Historical corpus/release files remain byte-identical; a new live evaluation needs a separately reviewed source manifest.
