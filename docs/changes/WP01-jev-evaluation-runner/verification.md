# Offline verification — 2026-10-03

No credentials read, private live ledger read or modified, provider call, application wiring,
Git publication, threshold change or admission record was performed by this worker.
Only temporary copied public artifacts and temporary ledgers were used by evaluator tests.

## Actual evidence

Evidence is append-only under `docs/verification/jev-evaluation-runner/runs/`:

- `20261003-1142-red-contract`:2 expected assertion failures. The initial executable stub did not
  report unarmed zero-request behavior or expose injected bounded execution. This was a collected
  behavioral failure, not an import/collection error.
- `20261003-1150-green-contract`:the same2 tests passed, unchanged test source.
- `20261003-1154-offline-invariants`:36 passed on their first execution. The recorder invocation
  mistakenly expected exit1, so its own expectation flag is false; the actual pytest exit0/output
  remain intact. This is baseline/invariant coverage, not falsely claimed historical RED.
- `20261003-1155-red-runtime-binding`:6 failures and36 passed. Newly added negative controls proved
  parsed wire answers could outlive a stale/mismatched runtime result and that an unregistered0.5
  NOUL categorization had been introduced. Both issues were fixed.
- `20261003-1155-green-runtime-binding`:the exact same42 tests passed, unchanged test source.
- `20261003-1158-offline-expanded`:53 passed. This adds usage multiplier/minimum, cancellation,
  exact reserve boundary, corrupted ledger, unarmed no-read, request mutation and report privacy.

All six recorded runs report zero source mutations during their execution. Their receipts contain
source and test hashes, exact commands, timestamps, exit statuses and full synthetic-only output.
Initial RED/GREEN and runtime-binding RED/GREEN are separate genuine cycles; added passing tests
are not represented as having a RED that did not occur.

Final scoped aggregate:

```sh
.venv313/bin/python tools/check.py --files tools/jev_evaluate.py \
  tools/jev_evaluation_support.py tests/unit/test_jev_evaluator.py --jobs 3
```

Passed architecture, env, providers and tooling, report:
`var/quality/3f12a249c4ea43d9abb1e78895e8fbc0/summary.json`.
Not run by this scoped check:domain, config, actor, http, specs, web, package, smoke.
The parent is responsible for its broader integration/base-diff verification and any approved live run.
A separate Ruff attempt was unavailable (`No module named ruff`); no software was installed to obtain it.
Full/release, live semantic evaluation, holdout, human adjudication and population calibration were not run.

## Covered negative boundaries

- Global existing ledger, full reserve before transport, same fcntl lock, no concurrency/retries
- Global20-attempt/USD0.01 caps; no ledger initialization/reset; corrupt/negative/nonfinite charges
- Actual validated usage with1.5 buffer and minimum charge; unknown usage retaining full reserve
- Frozen source/artifact/manifest mutation before/after dispatch; fresh nonce and exact payload binding
- Exact full DTO/question/effect coverage; adjudication label/hash eligibility; excluded holdout/guard
- Wrong model, malformed response, missing question, inconsistent confidence, missing usage,
  timeout, HTTP errors, transport exceptions, cancellation, runtime stale/binding/model/usage mismatch
- Unsafe violating or ambiguous allowance, boundary false-NO, unsupported referent resolve
- Four preregistered compatible abstentions; raw cent-grid confidence preserved without threshold tuning
- Runtime uncalibrated outcomes separate from diagnostic threshold results and exact-vector score
- No raw dialogue/provider body/header/key in reports; no credential/config/file reads when unarmed
- Attempted-case quality denominators, per-dimension confusion, latency and limited sample intervals


## Immutable source / canonical accounting correction — 12:09 UTC

The approved accounting/config root is now explicit and independent of the frozen source root.
CLI uses the exact approved config root for existing ledger, shared lock, credentials and reports;
manifest/corpora/source validation remains rooted at the immutable script ROOT. No ledger copying,
ledger initialization, symlink accounting, credential reads or live request occurred in this change.
An absent config model uses the already validated manifest’s exact fixed model, as in the original
smoke tool. Different explicit models and aliases remain rejected without a transport request.

Additional evidence (same append-only run directory):

- `20261003-1207-red-shared-budget-root`:6 failures/53 passes showed the missing API and CLI budget
  routing. The added synchronous main test also exposed pytest event-loop cleanup warnings; these
  were a test-harness issue and were removed by inspecting the async entry without creating a loop.
  This original receipt is preserved, not used as the clean behavioral RED/GREEN pair.
- `20261003-1208-red-shared-budget-behavior`:6 failures/53 passes, clean behavioral evidence after
  adding the parameter without implementing routing. Separate snapshots wrongly tried their own
  lock location; CLI omitted canonical budget routing.
- `20261003-1209-red-root-and-unset-model`:7 failures/56 passes, adding the valid unset-config-model
  regression before fixing either behavior.
- `20261003-1209-green-root-and-unset-model`:the identical63 tests passed with zero source mutations.

New tests prove two distinct frozen roots use one canonical ledger, contend on the same fcntl lock,
share attempt and dollar caps, and create no snapshot ledger or lock; canonical source edits do not
invalidate the immutable copy. The original53 tests remain passing, including unarmed no-file-read.
Opaque synthetic stand-ins test absent/exact/different/alias config model cases without reading
any config file or invoking any actual provider transport.

Scoped aggregate `var/quality/db7f849fbe664614ad3482a7e3dd503b/summary.json`:
architecture7, env96 and tooling152 passed. Providers654 passed and3 failed in existing
`test_session_token_boundary.py:25`:microphone error responses now have an extra `diagnostic_id`
from concurrent application work. These failures are unrelated to evaluator accounting code and
were reported to the integration director; they were not edited or hidden. Source did not change
during this aggregate run. The prior aggregate remains valid historical evidence only.

Stable source hashes after this correction:

- tools/jev_evaluate.py:1509994b5a02b5891959e1677eeb375f6d7b2141118597857e5d2bc7186cf0c2
- tools/jev_evaluation_support.py:e8f349c78bfe6e736b52db726bc748d5d716e0415b3f60c359c833764d55e383
- tests/unit/test_jev_evaluator.py:3a788d04d956a569f6bb4289def7e9342f6fbd00926593edbe5b2fee33ea4c79
