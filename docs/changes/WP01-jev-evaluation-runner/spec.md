# Bounded diagnostic JEV runner

This standalone CLI has no application wiring, calibration reference or admission power.
It preserves v1 and holdout bytes. No live execution is part of its implementation/testing.

- Given an unarmed invocation, return an unarmed zero-request report without reading configuration, credentials, manifests or network.
- Given explicitly armed execution, require an externally pinned manifest binding all safety-critical sources, exact model/origin/question sets, corpus, preregistration and eligible adjudication. Selected rows must be development-only, lossless DTOs, exact gold coverage, no deterministic no-call guards. Revalidate immediately before/after each dispatch; mutation stops the run.
- Given an eligible request, hold the smoke runner's same global fcntl lock, validate the existing ledger, persist USD0.0029568 and one attempt before dispatch, use concurrency one and no retries. Never create/reset a budget ledger. Reconcile only complete validated actual usage, at published input price times1.5 with USD0.00001 floor; unknown usage retains the reservation.
- Given a complete parsed response, retain only allowlisted numeric/enum scoring, synthetic IDs, hashes, timing/status/usage. Separate exact raw vectors and threshold diagnostics from actual uncalibrated runtime outcomes. Never issue ALLOW, grant permission or fabricate calibration_ref.
- Given malformed/wrong-model/stale/binding/unsafe response, stop. A qualified violating/ambiguous all-allow, confident boundary false-NO or unsafe referent stops for incident review. Four preregistered compatible all-abstentions stop for futility.
- Metrics count attempted cases, including invalid/timeouts in coverage denominators. No-call guards and not-dispatched cases never become successes. Raw exact-vector agreement, threshold reject and safe non-allow are separate. Report rates with explicit numerator/denominator and small-sample intervals as synthetic diagnostics only.

Ownership: tools/jev_evaluate.py, tools/jev_evaluation_support.py, tests/unit/test_jev_evaluator.py. Parent registers unique quality owner. Source base ebb578dde665c9c7269e4a64b508182680b2fa66. Consumers: existing JEV input/output adapters and application DTOs; no adapter/runtime changes. Tests use injected synthetic transports and temporary budget ledgers only. Full/release/live are not run by this worker.
