# JEV development decision policy v2 verification

This verification covers only the opt-in, immutable `user-development-0.6-v2`
threshold policy. It does not change defaults, contact a provider, establish model
quality, or assert a saved candidate's semantic root cause.

## TDD evidence

- Specification: `specs/features/WP01-jev-user-development-policy-v2/spec.md`.
- RED run `jev-policy-v2-red-behavior-20261004t0414z`: 4 failures / 1 pass on the
  exact REJECT boundary parameter set when an isolated temporary copy used the former
  unconditional development REJECT rule. The repository source was unchanged during
  this run. The temporary overlay is only a negative control and was not applied to the
  repository.
- GREEN run `jev-policy-v2-green-behavior-20261004t0414z`: the same five collected
  parameter cases passed against the current adapter. Repository source was unchanged
  during this run.
- An earlier collection check observed the missing v2 policy symbol; because it stopped
  at import collection, it is not counted as behavioral RED.

## Focused checks

- New v2 and historical v1 development-policy tests: 55 passed before the final
  additional malformed-number / safety cases.
- Impacted review, request-bound, semantic-fallback, contract and input tests: 225
  passed.
- Provider lane `b5ca239566c44a7987775dcf8ddefadf`: 1,080 passed, zero failures or
  errors; source digest unchanged during run. Other lanes were not run.
- Spec collection found all 174 referenced requirements/tests collectable. This is
  linkage, not execution evidence.

The provider-lane run preceded the later test-only adjustment of the ASGI weak-REJECT
fixture to the captured rounded probability/confidence pair (`0.52` / `0.29`). That
adjusted fixture has its own direct passing test. Rerun the provider lane after any
additional merged source edits. Production changes are confined to `decision_policy.py`,
`decision_contracts.py`, `jev.py`, `jev_input.py` and `diagnostic_errors.py`; no
bootstrap, prompt/question text, provider or network behavior was changed in this slice.
