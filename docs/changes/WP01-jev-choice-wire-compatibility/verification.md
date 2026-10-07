# WP01 JEV Choice wire compatibility verification

Date: 2026-10-04 UTC

## Scope

Implemented `jev-choice-cent-interval-v1` in application-level math and wired its
sum precheck into only the output and input JEV numeric parsers. Diagnostics retain
the observed raw probability sum and use the same compatibility predicate. No
question wording, thresholds, binding, retries, adapters outside the direct JEV
input/output parsers, or prior receipts were changed.

## Mathematical check

For `n` options, the official Choice confidence formula is
`(p_max - 1/n) / (1 - 1/n)`. Each cent-reported `p_i` and `c` becomes its exact
closed interval `[max(0, value - 1/200), min(1, value + 1/200)]`, represented by
`Fraction`. Inverting the confidence formula yields the feasible interval for a
latent maximum `x`.

For each index at the reported maximum (ties have the same interval), the solver
intersects `x` with its probability interval, the inverse confidence interval, all
other probability lower bounds (so `x` remains a maximum), and
`x <= 1 - sum(other lower bounds)`. At a fixed `x`, each other probability may lie
in `[lower_i, min(upper_i, x)]`; its attainable sum is a contiguous interval.
Capacity `x + sum(min(upper_i, x))` is monotone in `x`, so one exact comparison at
the greatest allowed `x` determines whether the remaining mass can be assigned.
This is O(n), uses exact rationals, and proves existence of one normalized latent
vector rather than independent loose checks.

The legacy normalized full-precision sum check (`1e-5`) and confidence comparison
(`1e-4`) run first and are unchanged. The cent path requires all probabilities and
confidence to be exact decimal multiples of `.01`, with no conversion of values
used for decisions. The legacy confidence shortcut is taken only when the raw sum
is itself within the existing `1e-5` tolerance; sums accepted only as cent-grid
compatible must pass the joint interval solver.

## Source basis

- Official [TypeSafe OpenAPI](https://api.typesafe.ai/openapi.json): Choice
  probabilities “sum to approximately 1”; `choice` identifies a highest-probability option.
- Official [Choice guide](https://docs.typesafe.ai/primitives/choice): describes
  the mathematical full distribution as summing to 1.
- Pinned official [TypeSafe Python SDK model v0.7.2](https://raw.githubusercontent.com/typesafe-ai/typesafe-sdk-python/v0.7.2/src/typesafe_sdk/_schemas/models.py): required Choice fields are plain Pydantic fields, without a declared probability-sum validator.
- Official [confidence guide](https://docs.typesafe.ai/confidence): Choice confidence formula uses the maximum probability and actual option count.

These claims are reconciled by distinguishing the normalized mathematical
distribution from its independently rounded JSON fields: acceptance requires a
normalized latent vector inside all reported intervals. The confidence guide gives
the statistic for that vector. No behavior of an LLM adapter or other intermediary
is used as evidence for direct API requirements.

## Tests

- RED: before the legacy shortcut fix, the new regression assertions failed for
  `(.50, .49), confidence .00` at `n=2` and `(.00, .03, .98), confidence .97`
  at `n=3`; both have a cent-compatible sum but no joint normalized vector matching
  confidence.
- GREEN: `./.venv/bin/python -m pytest tests/contracts/test_jev_choice_wire_compatibility.py -q` — 31 passed.
- Regression: `./.venv/bin/python -m pytest tests/contracts/test_jev_review.py tests/contracts/test_jev_input.py tests/contracts/test_jev_response_diagnostics.py tests/contracts/test_jev_transport_diagnostics.py tests/contracts/test_jev_choice_wire_compatibility.py tests/unit/test_jev_evaluator.py -q` — 314 passed.

The old diagnostics fixtures treated sums `0.99` and `1.01` as malformed. They
were replaced with `0.98` (`0.70, 0.28, 0.00`) and `1.02`
(`0.70, 0.31, 0.01`), whose cent intervals cannot contain total probability 1.
New assertions explicitly accept feasible `0.99` and `1.01` and reject `0.98` and
`1.02`. Existing input-referent coverage still checks that raw `.99` probability
and `.98` confidence do not cross the unchanged `.99` / `.985` admission gates.

Not run: full affected/release lanes, live provider/account behavior, and any
real-content semantic assessment.
