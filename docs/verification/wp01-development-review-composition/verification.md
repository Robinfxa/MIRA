# WP01 development semantic-review composition verification

Status: local, injected synthetic composition verified. No live integration, Chinese
semantic quality or calibration is claimed.

## Supported development-only composition

Import `mira.bootstrap.development_review.create_development_review_providers` and
inject a caller-owned `GenerationBackend`, independent typed `JevTransport` instances
for input and output, `authorized=True`, and the exact
`USER_DEVELOPMENT_0_6_V1` policy. The helper returns a `Providers` bundle containing
the caller's generation backend, `JevReviewBackend` as its review backend,
`JevInputDecisionBackend` and `JevReviewBackend` under the semantic coordinator, and
`DecisionSnapshotOwner(mira26_author_policy())`.

The JEV model is fixed to `jev-1.13.0`. Separate input/output request limits default to
2 and each must be an integer from 1 through 8. Separate timeouts default to 10 seconds
and each must be finite, greater than zero and no more than 30 seconds. The adapters
retain their fixed 16 KiB request and 64 KiB response caps. No calibration reference is
set. No default `create_providers` behavior or service-backed guard was changed.

Construction checks admission values and injected callables only: it does not read
environment or credential state, discover ADC, allocate clients/resources, or call a
transport. The caller remains responsible for independent credential, paid-call and
total-cost admission. This factory is not wired into normal startup.

## TDD and checks

- `runs/004-red-missing-factory`: actual RED, 11 failed / 1 passed because the factory
  module/callable did not exist; this is separate from the earlier recorded setup error
  at `runs/001-red-missing-factory`, where pytest was absent from the incomplete `.venv`.
- `runs/009-green-final-source`: final directed suite, 12 passed on Python 3.13.5; covers
  explicit and omitted authorization, exact-policy rejection, default
  guard preservation, inert composition, valid Actor grant, UNKNOWN/REJECT no-grant,
  capture restriction, Stop during cancellation-suppressing review, and separate
  request/timeout budgets.
- `runs/008-spec-traceability-final`: `tools/check_specs.py` passed, with 139 requirement
  links referencing collected test nodes.
- `var/quality/dev-review-composition-20261003-1946/summary.json`: affected selection
  passed 1,322 offline Python tests across architecture (7), env (107), config (21),
  actor (21), providers (856), HTTP (84) and tooling (226), plus the specs command.
  No source change occurred during that check. Afterward, the final factory/test edit
  only wrapped long lines; the final focused run above passed on that source. Domain,
  web, package and smoke lanes were not run; this is not full or release verification.

The test suite uses in-process synthetic transport responses and a synthetic generation
backend only. No live provider/network call, credential or account state was used; no
paid request, remote CI, audio/device behavior, real-user review, or Chinese calibration
was tested.
