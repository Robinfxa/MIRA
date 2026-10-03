# Frozen Chinese diagnostic run v2

On 2026-10-03, the preregistered first development case `out_pending_honest` was dispatched once to exact `jev-1.13.0`. The adapter reached its existing 10-second deadline (10.002 s observed) before a validated response or token usage was obtained. The batch stopped. The other 15 selected cases were not dispatched and are not semantic observations.

This is an operational timeout, not evidence of a wrong Chinese judgment, account failure, service outage or network cause. The earlier successful authenticated seven-question parser check remains separate evidence. No threshold, gold label or calibration reference was changed; production admission stays off.

The same global budget ledger now contains five attempts. Conservative known/reserved total is USD 0.009012276 against the approved USD 0.01 limit. Unknown usage retains its full USD 0.0029568 reservation. The remaining USD 0.000987724 cannot cover another worst-case reservation, so the runner is paused without retry. These are local conservative estimates, not an invoice.

Pricing was checked against the [official model page](https://docs.typesafe.ai/models): USD 0.042 per million input tokens, free output, maximum 64,000 combined input tokens. No official public-test-key exemption was established in the anonymous documentation check; the specific key was neither inspected nor identified.

The source and case manifest was frozen before dispatch. The default unarmed CLI reported zero requests; all 63 offline runner tests passed. The manifest SHA-256 and sanitized observed outcome are in `first-run-summary.json`. This diagnostic cannot establish Chinese quality, useful allow coverage, or calibration.
