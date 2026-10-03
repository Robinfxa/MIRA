# Choice confidence wire-contract investigation · 2026-10-03

This addendum preserves the historical verification record. The prior offline tests
were deterministic adapter tests, not verification of real response precision.

## Primary-source facts checked at 10:31–10:34 UTC

- [Confidence](https://docs.typesafe.ai/confidence) defines Choice confidence as
  `(p_max - 1/n) / (1 - 1/n)`. The original three-choice formula is mathematically
  correct. Noul has no separate confidence. Score uses a different statistic.
- [API reference, Choice answer](https://docs.typesafe.ai/api) publishes
  a three-option example with probabilities `(0.88, 0.12, 0.0)` and confidence `0.81`.
  Recomputing from the displayed probability gives `0.82`, not `0.81`.
- [OpenAPI](https://api.typesafe.ai/openapi.json) describes confidence within `[0,1]`
  and probability sums approximately equal to one. It does not specify the decimal
  precision, rounding mode, or a client-side relationship tolerance.
- The [official Python response model](https://github.com/typesafe-ai/typesafe-sdk-python/blob/main/src/typesafe_sdk/_schemas/models.py)
  exposes the returned confidence and probabilities without asserting this equation
  at a particular wire precision. This is not evidence of a different equation.
- [Models](https://docs.typesafe.ai/models) still identifies `jev-1.13.0`; it explicitly
  requires workload testing for CJK languages. Connectivity and parsing cannot supply
  that language-quality evidence.

## Diagnosis and evidence boundary

`test_jev_review.answer()` synthesizes confidence by the exact implementation formula.
Most input fixtures use probability/confidence `1.0`. These tests are useful for
mechanics but never exercised independently serialized/rounded fields. Their passing
results could not validate the `1e-4` relationship tolerance against the service.

The director's existing sanitized diagnostic
`var/mission/jev-smoke/20261003T102638553606Z.json` reports authenticated HTTP 200,
the requested fixed model, seven answers and expected field types, followed by
`inconsistent_confidence`. No original numeric values remain, so it cannot establish
the size or cause of that mismatch. It is evidence of connectivity, not successful
parser execution or Chinese semantic calibration.

Independent rounding to two decimal places could explain the published example, but
the sources checked do not document that serialization policy. A later director-owned
350-byte diagnostic returned HTTP 200 with the exact fixed model, three options,
selected probability `0.95`, confidence `0.93`, sum `1.00` and two decimal places in
each selected numeric field. Exact recomputation gives `0.925`. The safe evidence is
`var/mission/jev-smoke/20261003T103917836466Z-numeric.json`. Usage was 382 input / 40
output tokens; the published-rate estimate is USD 0.000016044, not an invoice.
This supports finite-decimal compatibility but does not prove a universal rounding
rule or explain every field of the two discarded earlier responses. The director
alone owns authorized live calls and total budget. This worker performed zero live
inference calls and read no private credentials.

## Narrow compatibility policy

Both adapters now share `_choice_confidence_consistent`; their mathematical formula
has not changed. Precisely matching responses keep the existing `1e-4` check. For a
response that misses that check, compatibility applies only if every returned
probability and the confidence are exact multiples of `0.01`. Values with unexplained
finer precision do not receive a wider tolerance.

For that cent-grid representation only, treat each numeric field as a possible
independently nearest-cent-rounded value. Let `h = 0.005`, `p` be the returned maximum
probability and `c` the returned confidence. Intersect:

- `P = [max(1/n, p-h), min(1, p+h)]`
- `C = [max(0, c-h), min(1, c+h)]`
- the formula image `F(P)`, with `F(x) = (n*x-1)/(n-1)`

The response is consistent only if `C` and `F(P)` overlap. Exact rational arithmetic
handles interval boundaries without another floating-point epsilon. This is an
explicit local compatibility policy grounded in the primary example plus the observed
numeric sample, not a provider guarantee about rounding or hidden probabilities.
Gross discrepancies still fail closed. Visible probability bounds, sums and maxima
retain their previous strict checks; probabilities are never renormalized.

Original returned numbers continue to drive the unchanged `0.99` probability and
`0.985` confidence thresholds. In particular, `(p=.99, c=.98)` parses but remains
UNKNOWN, even though recomputing the displayed probability yields `.985`. Neither
adapter substitutes a calculated or rounded-up confidence. Calibration remains absent
by default. No schema, model pin, nonce, content identity, coverage, policy, transport,
budget or production-admission setting changed.

## Actual regression evidence

`runs/008-red-wire-confidence/`: two collected tests failed against the unchanged
adapters. They use the primary API example's literal numeric fields, changing only
option labels to each adapter's known options. Both should remain semantic UNKNOWN
because their evidence is below the unchanged thresholds; current code instead
classifies their wire representation as invalid. Test and adapter hashes, actual
stdout, JUnit and exit status are retained. This is behavioral RED, not a collection
or dependency error. The run covers only these two tests, not the integrated snapshot.

`runs/009-red-observed-wire-confidence/` ->
`runs/010-green-observed-wire-confidence/`: the identical 24 confidence tests produced
12 failed / 12 passed, then 24 passed. Both test files have identical hashes across
the pair. Cases cover the literal public example, retained live numeric fields with
explicitly synthetic allocation of the remaining probability, two/four-option
synthetic rounding, gross mismatch, unsupported precision, unchanged thresholding and
absent calibration. The original two discarded responses have not been reconstructed.

`runs/011-green-all-jev-contracts/`: 193 passed, comprising both complete JEV
review/input/HTTP suites, corpus integrity, decision-contract mechanics and three
architecture guards. Covered source hashes did not change during any of these runs.
Compile checks passed. Ruff was unavailable (`No module named ruff`); no install was
attempted. This is a targeted offline rerun, not full/affected integration or remote CI.

The existing files retain their `providers` lane owner. Aggregate checks on the
integrated immutable snapshot remain the director's responsibility.
The read-only affected plan exited 2 because concurrent
`tests/unit/test_diagnostic_export.py` had no quality-lane owner. The director was
notified; no shared registry or diagnostics file was edited in this correction.

## Three distinct outcomes

1. Authenticated connectivity: established by the director's HTTP 200 diagnostics.
2. Parser compatibility: the observed numeric shape and primary example now pass
   offline parsing; no post-fix authenticated seven-question parser run is claimed.
3. Chinese semantic calibration: not established. The tiny probes and synthetic
   mechanics do not admit the input or output policy for production.
