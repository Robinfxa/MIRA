# JEV response-validation diagnostic repeat: pending review

This proposed single-case diagnostic experiment is separate from the stopped v2 development run. It is prepared for director/root review and has **not** been dispatched. The prior result remains terminal and unchanged.

## Purpose and bound

The stopped case was `out_old_boundary_voice`. Its report retained HTTP status 200, `response_invalid`, runtime reason `jev_transport_error`, no usage, and the full USD 0.0029568 reservation. The response body and parser exception were not retained; the exact historical cause is unknown and must not be reconstructed.

One explicitly reviewed repeat of that same registered case would exercise the newly added sanitized response-validation diagnostics on a fresh response. It can establish the parser reason/known field, response byte count and SHA-256, registered question suffix/type, bounded structural counts, and any valid bounded numeric/usage facts for the new response only. It cannot retroactively identify the cause of the earlier response. The new report stays separate and is excluded from quality metrics; it does not replace or erase the prior stopped result.

The repeat must use the same frozen v2 case, labels, prompt/question bytes, thresholds, `jev-1.13.0`, approved endpoint, 30-second evaluation timeout, and reserve-before-call ledger. It is exactly one request, sequential, with no automatic retry. A new timeout, invalid response, unsafe qualified result, drift, or budget block ends the probe. No holdout or other case is selected.

## Budget and execution gate

Existing approval permits at most 30 additional attempts and USD 0.10 total; the experiment retains the stricter USD 0.05 effective aggregate ceiling, 35 global attempt ceiling, and USD 0.0029568 per-attempt worst-case reserve. At preparation time the canonical ledger has 11 attempts and USD 0.0126051870 reserved or charged, leaving room for this single reserve under the effective cap. Pricing and MCA tax caveats remain as recorded in the preceding continuation plan; estimates are not an invoice or all-in billing guarantee.

The frozen diagnostic manifest requires both `--approved-continuation` and the new `--root-reviewed-diagnostic-repeat` gate, plus `--max-cases 1`. Do not dispatch before director/root reviews this exact plan and manifest. No UI, credential, private-chat, calibration, threshold, corpus-label, production-default, or provider configuration changes are part of the experiment.
