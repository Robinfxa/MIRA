# Independent audit: first JEV Chinese diagnostic timeout

**Audit date:** 2026-10-03 UTC  
**Scope:** Offline-only inspection and synthetic-transport verification of the frozen run `jev-zh-v2-20261003T1229Z`. No `.env`, screenshot, credential value, or provider endpoint was accessed.

## Finding

The run is a single operational timeout, not a Chinese semantic-quality observation. The sanitized report has manifest SHA-256 `8c6db4005da11c2ee3d25013c916419973ae0ca72ee6a7447148f2d81201f94c`; the frozen `frozen-run.json` hashes to that value. Its source digest also recomputes to the report's `1e11877f036db95dd06713ba13004fa40b52db073af995bbba77ddb556111803` from the pinned source-file hash map. The five frozen runtime/evaluator source files inspected have the same hashes in the frozen manifest and the canonical checkout.

The report records one dispatched case, `out_pending_honest`, with `jev_timeout` after 10.002257 seconds. It has no validated response, token usage, or semantic score. The other 15 selected cases were not dispatched. The separate earlier HTTP 200 / parser-verified postfix remains distinct evidence and does not reveal why this request timed out.

The shared ledger has 5 attempts and USD 0.0090122760 conservatively reserved or charged against the USD 0.01 cap. A new full reserve is USD 0.0029568000, making USD 0.0119690760, above the cap; only USD 0.0009877240 remains. The current run is therefore not dispatchable again under this ledger.

## Offline verification

- `pytest -q tests/unit/test_jev_evaluator.py tests/contracts/test_jev_review.py tests/contracts/test_jev_input.py tests/contracts/test_jev_review_http.py tests/contracts/test_jev_input_http.py`: **222 passed**. These tests use temporary ledgers and synthetic transports or `httpx.MockTransport`; no provider call is made.
- A separate run of the frozen evaluator with a synthetic transport that immediately raises `TimeoutError` recorded exactly one transport invocation and one reserved attempt, returned `jev_timeout`, retained the full USD 0.0029568000 reserve, and dispatched none of the remaining 15 cases. With the four historical entries copied into an isolated test ledger, its total was USD 0.0090122760, matching the real report.
- A second synthetic run copied the current five-entry ledger into a temporary directory, used a new test run ID to avoid the duplicate-run guard, and attempted no network transport. The evaluator returned `local_budget_exhausted`, with 0 calls, 0 added attempts, and the copied total still USD 0.0090122760.
- Adapter tests independently confirm a deadline cancels the pending synthetic transport, consumes the one-request budget, and does not retry; cancellation propagates or is recorded as cancelled, and a second request is not made. The HTTP transport is configured with retries disabled.

## Reporting caveats

The metrics implementation first filters to `dispatched` rows, so undispatched cases do not enter transport, class, or latency denominators. Semantic abstention is computed only from `response_valid` rows; its denominator is 0 here. `operational_abstention` is 1/1. The `exact_vector_match` denominator includes the dispatched timeout (0/1), while `exact_vector_match_parser_valid` has denominator 0; these should not be read as evidence that Jev made a wrong judgment.

`safe_non_allow` is also 1/1 because the timeout did not produce `would_allow_if_admitted=True`. This is a fail-closed operational outcome, not a Jev safety/quality success. Existing run documentation correctly says there is no semantic-quality observation and makes no Chinese quality or useful-coverage claim. One schema clarity issue remains: after a batch stop, the evaluator copies the batch-level `response_unavailable_or_invalid` status onto all undispatched rows even though `dispatched=false`; a future report could label those rows `not_dispatched` and retain the batch stop reason separately.

## Cause and test-key check

The available artifacts establish that the application deadline fired, but they cannot distinguish provider latency, intermediary/network delay, or another cause. There is no validated response or usage record and no provider-side acknowledgement that upstream work was cancelled. The timeout is not evidence of a wrong model answer, account failure, service outage, or network fault.

The current official [TypeSafe model documentation](https://docs.typesafe.ai/models) lists Jev 1.13 at USD 0.042 per million input tokens, free output, and a 64K token request context, and advises testing CJK workloads because English is the primary language. Anonymous searches limited to TypeSafe's official documentation did not find a public/free test-key exemption. A key's visible prefix alone cannot establish that it is public; this audit did not inspect the entered key.

## Smallest next experiment, if separately authorized

Do not retry within the present USD 0.01 cap. The existing run authorization also says no retries, so a repeat requires fresh explicit authorization as well as a budget increase. If separately authorized, the smallest follow-up would be a new immutable one-case run (new run ID) using the same synthetic case, pinned `jev-1.13.0`, same ten-second timeout and request controls, reserve before dispatch, and stop after that one response or timeout. It would be a sixth call overall, with zero retries after that call. The minimum additional budget required to cover its full reserve is **USD 0.001969076**, bringing the cumulative local cap to **USD 0.011969076**; the added attempt reserve itself is **USD 0.002956800**. This single observation could show whether the timeout recurs, but would not by itself establish its cause. No experiment was run as part of this audit.
