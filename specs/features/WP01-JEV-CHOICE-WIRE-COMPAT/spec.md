# WP01 JEV Choice wire compatibility

Status: strict mathematical compatibility for independently rounded Choice wire
values. This does not normalize or mutate the provider's reported values and does
not change output or input admission thresholds.

### WP01JEVCHOICEWIRECOMPAT-001 Probability sums accept only feasible wire representations

Given a finite Choice probability mapping with at least two options and values in
`[0, 1]`, when its sum is within the existing `1e-5` full-precision tolerance, keep
the legacy branch. Otherwise, accept it only when every value is exactly on the
decimal-cent grid and the clipped closed intervals `reported ± 0.005` can contain a
single normalized vector. Thus sums `.99` and `1.01` can be compatible; `.98` and
`1.02` are not for three cent-grid options. A compatible vector is never rescaled.

### WP01JEVCHOICEWIRECOMPAT-002 Rounded confidence shares one latent normalized vector

Given a cent-grid probability mapping and cent-grid confidence, when checking the
TypeSafe Choice statistic `(p_max - 1/n) / (1 - 1/n)`, accept only if one normalized
latent vector can simultaneously lie within every probability rounding interval,
have a maximum compatible with the reported maximum, and place its derived
confidence within the reported confidence interval. Infeasible separate loose
checks do not suffice. The existing full-precision confidence tolerance remains
unchanged. Non-cent values cannot enter the new branch.

### WP01JEVCHOICEWIRECOMPAT-003 Parsers and diagnostics preserve original numbers

Given valid input-referent or output-review Choice data, when parsing a compatible
rounded representation, retain the provider's raw probabilities and confidence for
all existing policy thresholds. When it is malformed or jointly infeasible, fail
closed as before. Diagnostics retain the raw bounded probability sum while their
compatibility/confidence facts agree with canonical parsing. Weak reject and
unknown answers cannot become allow through wire-precision handling. Existing
receipts are not rewritten.

### Wire compatibility evidence

The [official OpenAPI schema](https://api.typesafe.ai/openapi.json) describes Choice
probabilities as values that sum to approximately 1 and the choice as the
highest-probability criterion. The pinned [TypeSafe Python SDK model](https://raw.githubusercontent.com/typesafe-ai/typesafe-sdk-python/v0.7.2/src/typesafe_sdk/_schemas/models.py)
uses ordinary required fields for `choice`, `confidence`, and `probabilities`; it
does not declare a sum validator. The [official confidence guide](https://docs.typesafe.ai/confidence)
defines Choice confidence using the maximum probability and actual option count.
The official [Choice guide](https://docs.typesafe.ai/primitives/choice) describes
the mathematical distribution as summing to 1. This implementation preserves that
mathematical requirement by demanding one normalized latent vector in the closed
rounding intervals, while allowing the independently serialized two-decimal fields
to sum to `.99` or `1.01` when feasible. This rule is limited to direct API wire
precision; it does not infer or depend on behavior in any separate adapter.
