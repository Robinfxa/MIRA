# JEV user-selected 0.6 development policy verification

Scope: explicit `user-development-0.6-v1` adapter selection; no bootstrap/factory
activation, provider request, account change, or production calibration. All transports
in these checks are injected synthetic test doubles.

## Source change

- `apps/api/src/mira/application/decision_policy.py`: immutable typed/versioned policy descriptor
- `apps/api/src/mira/application/decision_contracts.py`: exact allow-listed policy provenance and application contract admission
- `apps/api/src/mira/application/choice_confidence.py`: provider-neutral exact/cent-grid consistency check shared by adapter parsing and application validation; it does not replace reported values
- `apps/api/src/mira/adapters/review/jev.py`: explicit policy selection for output Choice; in development mode every selected `reject` remains REJECT, while old calibrated/default behavior is unchanged
- `apps/api/src/mira/adapters/review/jev_input.py`: explicit policy selection for NOUL/referent observations; rejects unsupported/unpresented referents
- `tests/contracts/test_jev_user_development_policy.py`: new provider-lane behavior and safeguard tests
- `specs/features/WP01-jev-user-development-policy/`: additive specification and test traceability; historical WP01 policies/results are unchanged

## Actual RED / GREEN

- `runs/001-red-0-6`: actual pre-adapter RED, 23 failures, exit 1 as expected. The selected policy was not accepted by either adapter; tests reached the missing behavior (`decision_policy` was an unexpected argument). `report.json` includes the exact command, run time, Git base, before/after source hashes, and stdout hash.
- `runs/016-red-label-rounding-findings`: second actual RED before fixes; two failures and one pass. Weak reject was UNKNOWN; `.73/.14/.13` plus `.60` failed application contract admission; `.72/.14/.14` remained correctly rejected.
- `runs/017-green-label-rounding-findings`: the same three targeted cases passed: weak development reject is REJECT, compatible `.73/.14/.13` plus `.60` proceeds, and incompatible `.72/.14/.14` is still invalid.
- `runs/018-focused-consumers-final`: 272 tests passed across the complete new policy suite, output/input adapters, HTTP transport seams, decision contracts, semantic composition/coordinator, and architecture boundaries. `report.json` records matching code/test hashes and `changed_during_run=[]`.
- Feature-local traceability validation collected all 4 requirements. The concurrent global `tools/check_specs.py` run (`019-spec-links-final`) failed on a different composer-owned manifest referencing an uncollected node; composer subsequently corrected its metadata. No global recheck was performed in this slice.

The initial RED/GREEN run pair remains recorded (`001-red-0-6`, `002-green-0-6`). A later synthetic fixture assertion failed at `007-green-control-isolation` because its input double left speech at its default YES value; the test was corrected and passed in `010-green-control-isolation`. Stop/stale regressions passed in `013`–`015`; the independent findings then received the exact RED/GREEN pair `016`–`017` and final focused run `018`.

The provider reports `confidence = 1.5 * p_max - 0.5` for the three-choice output. Therefore both explicit thresholds are preserved exactly as selected; with this wire statistic, confidence 0.6 corresponds to p about 0.7333. No response statistic or precision was altered to make p=0.6 appear admissible.

The rounded referent `.73/.14/.13` and confidence `.60` is consistent under the same cent-grid interval rule used by the parser and application validator. Its original reported `.73` and `.60` values drive the selected `.6` gates. `.72/.14/.14` with `.60` remains inconsistent and invalid. Development-mode selected `reject` remains REJECT even when confidence is below `.6`; the prior low-confidence UNKNOWN behavior remains in the legacy/default mode.

## Not run / limits

Full affected/workspace integration and release checks are not claimed; the integration director owns composition and the immutable-snapshot affected run. No real JEV calls, Chinese quality recalibration, live factory activation, production-readiness claim, HTTP schema/generated contract change, or historical-policy rewrite was performed.
