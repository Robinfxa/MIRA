# TypeSafe Input Decision contract, checked 2026-10-03

Primary sources: [API](https://docs.typesafe.ai/api),
[OpenAPI](https://api.typesafe.ai/openapi.json),
[confidence](https://docs.typesafe.ai/confidence).
Read-only public documentation only; no authenticated request occurred.

POST /v1/systemone accepts state, model and typed questions. Noul questions use
instructions plus optional true/false criteria, and return only type/noul. Choice
questions use an option map; replies contain choice, full probabilities and confidence.
The Choice statistic is (selected_probability - 1/n) / (1 - 1/n). Noul does not have
confidence. The adapter validates each primitive independently, including exact option
coverage, bounds, sums and the Choice statistic. Question IDs include nonce and digest.

This slice uses three independent Noul predicates and one separate controlled-reference
Choice; questions never depend on a sibling result. Provisional positive/negative Noul
cutoffs are 0.99/0.01; selected referent probability >=0.99 and confidence >=0.985.
These constants are intentionally uncalibrated. Missing admission produces unknown,
even after syntactically perfect responses. They must not become production thresholds
merely because the tests pass or a synthetic smoke returns sensible values.

Budget defaults to zero; constructor accepts at most 100 attempts for an instance.
Construction is inert. Per-attempt deadline defaults to 10s, max 30s. Request <=16KiB,
response <=64KiB, no retry, redirect or route fallback. Shared HttpxJevTransport accepts
only an injected SecretStr and fixed provider endpoint. Synthetic HTTP tests use
httpx.MockTransport with a nonsecret placeholder, not actual credentials or a network.

Input statuses distinguish unavailable, invalid response, semantic unknown, stale and
observed. Status observed means calibrated, complete observation only. It is never an
execution permit, input-turn handover, external-data approval or cancellation authority.
No raw response body or provider exception survives into the result. Raw user facts are
retained only in the owner-built snapshot and unresolved input field; repr hides raw
input/constraints/obligations. Logging whole serialized snapshots is not authorized here.

## Confidence precision correction · 2026-10-03 10:45 UTC

Choice statistic validation now also handles bounded independently rounded cent-grid
fields, using the actual option count and unchanged original values for admission.
This is a local compatibility policy, not a documented provider rounding guarantee.
See [source and RED/GREEN correction](confidence-contract-correction.md). No Noul,
snapshot/model binding, normalized-probability or default calibration guard changed.
