# JEV Chinese diagnostic continuation: 2026-10-03

This is an explicitly approved, bounded continuation of the synthetic development diagnostic registered as `mira-jev-zh-eval-v2`. It does not change the corpus, labels, question bytes, threshold policy, production workload, or calibration state.

## Approval and effective cap

The user approved up to 30 additional synthetic requests, with a USD 0.10 aggregate ceiling including the prior attempts. The actual shared accounting ledger has five attempts and USD 0.009012276 reserved or charged. This run uses a stricter effective aggregate ceiling of USD 0.05 and a global ceiling of 35 attempts. The 0.10 approval is not a spend target or guarantee of final billing. Only 15 already-registered remaining development cases are selected here; a timeout or any stop condition ends execution without retry or case substitution. The 64K per-request reserve remains USD 0.0029568 and is entered before network access. Existing rows, reservations, and unknown charges are retained.

Published pricing was rechecked at 2026-10-03 17:12 UTC: [Typesafe model pricing](https://docs.typesafe.ai/models), JEV input USD 0.042 per million tokens, output free, 64K maximum. The [Typesafe MCA](https://typesafe.ai/legal/mca), section 8.4, excludes taxes. Token estimates and this local aggregate ledger are not an invoice, provider hard cap, tax calculation, or all-in billing guarantee. Stop if new billing risk or an unbounded fee is discovered.

## Frozen selection

The v2 queue order and labels remain unchanged. The previously dispatched `out_pending_honest` timeout remains only in its original frozen report and accounting row; it is explicitly excluded from this run and will never be resubmitted. The 15 selected rows are the remaining v2 development cases in original relative order. No holdout, guard, new candidate, or new label is included. The first-four compatible futility set is the first four compatible output cases among those remaining rows. No result from this diagnostic creates `calibration_ref`; every adapter call uses `calibration_ref=None`, and normal runtime remains uncalibrated/UNKNOWN.

The per-call adapter timeout is 30 seconds for this continuation only, up from its former 10-second setting. Production adapter defaults and unrelated smoke tools are unchanged. Execution is sequential, has no automatic retry, preserves the first response, and stops on malformed/stale/wrong-model response, timeout, invalid binding, unsafe qualified result, source drift, cancellation, futility, or budget exhaustion. A timeout or absent/unknown usage keeps the full reservation.

## Frozen artifacts and implementation

`preregistration.continuation-20261003.v1.json` and `frozen-run.continuation-20261003.v1.json` freeze the exact selection, source hashes, threshold policy, model, question sets, adjudication, and continuation budget policy. The runner's legacy 20-attempt / USD 0.01 behavior remains the default. Continuation requires both this pinned continuation manifest and the explicit `--approved-continuation` invocation flag; the accounting ledger is widened under its existing global lock without replacing any history.

The only permitted live destination is `https://api.typesafe.ai/v1/systemone` with `jev-1.13.0`, through the existing approved transport/configuration path. TLS verification and the inherited approved proxy/CA remain intact. No UI/auth changes, private-chat data, calibration, presentation, or production admission is part of this evaluation.
