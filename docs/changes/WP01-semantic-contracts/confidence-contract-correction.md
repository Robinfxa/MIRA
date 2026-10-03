# Input Choice confidence correction · 2026-10-03

See the [shared primary-source investigation and immutable regression evidence](../WP01-jev-review/confidence-contract-correction.md).
The Input Decision adapter has the same strict wire-precision assumption as Output
Review, with a variable number of reference options instead of a fixed three.

Its existing one-hot `(1,0,0)` synthetic fixtures cannot establish real confidence
serialization precision. The added independent API-example regression first failed
and now passes: a parseable low-confidence Choice produces semantic UNKNOWN with
original provider numbers retained, rather than an invalid-response classification.

The shared validator retains exact-formula validation and adds a bounded cent-grid
interval compatibility policy. It is grounded in the primary API example plus the
director's numeric-only `(n=3, p_max=.95, confidence=.93)` diagnostic, and explicitly
is not a provider rounding guarantee. Actual option count is used: synthetic two- and
four-option cases exercise the referent Choice path. Invalid precision and intervals
remain invalid; raw confidence below admission threshold is never increased.

The same 24 confidence regressions went from 12 failed / 12 passed to 24 passed,
with both test files identical across RED/GREEN. The final combined relevant suite
passed 193 tests with no covered-source changes during execution. See the linked
evidence for the exact commands and hashes. These counts are cumulative regression
coverage, not 193 new tests or Chinese evaluation samples.

No Noul confidence is introduced. Exact request/model/option coverage, snapshot
freshness, finite normalized probabilities, provisional thresholds and the absent-
calibration guard are unchanged. No live input observation or Chinese calibration
has been performed by this worker. Historical `verification.md` entries remain
evidence for their actual earlier offline runs only.
