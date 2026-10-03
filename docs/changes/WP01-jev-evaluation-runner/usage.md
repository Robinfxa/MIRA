# Standalone diagnostic runner handoff

## Safety boundary

Default invocation is unarmed, returns zero requests and reads no configuration or credentials:

```sh
.venv313/bin/python tools/jev_evaluate.py
```

This implementation was exercised only with injected synthetic transports and temporary ledgers.
It does not change application factories, thresholds or calibration. Output contracts explicitly use
`synthetic=True`; input/output adapters receive `calibration_ref=None`. Actual runtime `unknown` or
`reject` is kept separately from counterfactual `would_allow_if_admitted`. The input track never
produces an output-allow value. A transport/parser success or apparent diagnostic success cannot
produce an admission record.

## Director-owned manifest freeze

Use a new JSON run manifest with these fields:

- `schema_version: 1`
- `run_id`: unique synthetic ASCII identifier, maximum101 characters, letters/digits/underscore/hyphen
- `model: "jev-1.13.0"`
- `origin: "https://api.typesafe.ai/v1/systemone"`
- `production_calibration_admitted: false`
- `question_sets: {"input":"mira-input-v1","output":"mira-output-v1"}`
- `corpora`: `input` and `output` repository-relative v2 corpus paths
- `preregistration`: repository-relative final preregistration path
- `adjudication`: repository-relative final adjudication path
- `selected`: exactly the final preregistration's ordered_first_run list, not a rearranged queue
- `file_sha256`: every path from `tools.jev_evaluation_support.REQUIRED_SOURCES`, plus both corpora,
  preregistration and adjudication, mapped to SHA-256 of exact file bytes. Additional public
  source/artifact paths may also be pinned. Paths cannot leave the checkout or enter hidden paths.

Adjudication entries use the current v2 fields: `case_id`, `track` (`input`/`new_input` or `output`),
`source_case_sha256`, `review_disposition` (`agreed` or `adjudicated`),
`semantic_score_eligible: true`, and `frozen_labels`. Every selected row must have exact matching
case digest and gold vector. Unreviewed/disputed/guard/holdout/local-Stop rows fail before transport.
Every DTO must round-trip exactly, including cue metadata and complete audio/presentation context.

Pin the manifest itself using `--manifest-sha256`; do not rewrite it in place. No v1 file or holdout
was changed by this runner work. This content-addressed freeze is an integrity contract, not a
signature or new authorization. Live execution remains a director/user-authorized action.

## Explicit armed entry (not executed in this implementation)

```sh
.venv313/bin/python tools/jev_evaluate.py \
  --allow-live \
  --manifest /absolute/path/to/frozen-run.json \
  --manifest-sha256 EXACT_FROZEN_SHA256 \
  --approved-config-root /absolute/explicitly/approved/config/root \
  --max-cases 16
```

The config root is mandatory and only consulted after manifest validation and reservation.
`load_settings(root=..., env_file=.../.env, environ={})` is the sole credential-loading route;
there is no search or fallback. An unset config model is permitted only because the validated
immutable manifest and runner select exact `jev-1.13.0`; any different explicit model or alias
rejects. The selected config must retain the exact fixed origin.
The approved opaque `tools.jev_smoke.approved_transport` is reused without changing proxy, CA,
credentials or account settings. It posts only to the hard-coded adapter origin, with no retries.

A smaller max-cases merely ends earlier; it does not change the frozen queue. After any attempt
with a run_id, that same run_id cannot be replayed. This prevents retries or duplicated case evidence;
it is not an automatic resume mechanism. A further authorized diagnostic needs a new frozen run
with explicit preregistration rather than silently retrying a spent or uncertain request.

## Budget and reports

Live CLI always uses the existing global private `var/mission/jev-live-budget.json` and
`var/mission/jev-live-budget.lock` under the exact `--approved-config-root`. It never copies a ledger
into a source snapshot and does not rely on ledger or lock symlinks. The script ROOT remains the
immutable source/corpus/manifest validation root; canonical application source changes therefore
do not alter the frozen experiment. The injected `run_batch` API takes explicit `budget_root`,
defaulting to its source `root` only for existing callers/tests. It never creates or resets a missing budget. The same nonblocking
fcntl exclusive lock is held for the whole sequential run. Reserve USD0.0029568 and one attempt
before any potential provider request. Global caps remain20 attempts/USD0.01. Only a fully validated
exact-model/question response reconciles token usage, at input tokens × USD0.042/1M ×1.5,
minimum USD0.00001. Unknown usage keeps the complete reserve. Actual invoice is unverified.

Source/manifest/case/question bindings are checked before dispatch and after the response. A late,
stale or mismatched runtime result cannot override the parser diagnostic. Malformed, wrong-model,
missing-question, HTTP/timeout/error, stale, binding, budget, unsafe-qualified or cancellation failures
stop the batch without retries. Four predefined compatible semantic abstentions stop for futility;
actual uncalibrated UNKNOWN alone does not erase a threshold-qualified counterfactual result.

Reports are new timestamped files under the approved config root’s `var/mission/jev-evaluation/`,
updated after each reserved attempt. Frozen source trees receive no accounting or report writes. They retain only synthetic IDs, hashes, status/timing, usage and validated numeric/enum
answers. No response bodies, raw dialogue, headers or credentials are retained. NOUL answers have
no provider-supplied categorical label: raw numbers are retained exactly and the registered0.99/0.01
thresholds produce the scored categorical predicate, explicitly labelled in `label_basis`.

Coverage denominators include attempted malformed/timeout cases. Not-dispatched rows receive no
semantic success. Raw exact-vector agreement, thresholded rejection, semantic abstention, operational
abstention, runtime UNKNOWN, dangerous allowance and safe non-allow remain distinct. Inputs are not
reported as safe output non-allows. Dimension/effect confusion matrices and original probabilities /
confidence are included. Wilson95% intervals and zero-event one-sided bounds are descriptive only:
these small selected correlated synthetic cases do not establish population quality or calibration.
