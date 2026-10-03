# WP01 Chinese JEV evaluation preregistration

Status: offline synthetic corpus and evaluation protocol only. No live inference,
credentials, threshold changes, production calibration reference, or workload activation.
Common base: `ebb578dde665c9c7269e4a64b508182680b2fa66`; the original delivery deadline is
unchanged. Single writer owns this feature directory, the evaluation plan, and
`tests/contracts/test_jev_evaluation_corpus.py`. The existing `providers` glob is the
unique test owner. Consumers: input/output adapters, ResponseContractProducer and the
integration director. No shared application, adapter, schema, threshold or registry edits.
Offline tests use existing application DTOs and injected transports. Resources: no
network or credentials; one pytest process. The director owns frozen integrated affected
checks; this slice's source/evidence manifests never claim other workers' tests passed.

### WP01EVAL-001 Audit human labels independently
Given the 20 existing exposed input examples, preserve their source bytes and audit each
expectation, its scope and missing context. Semantic gold labels must be separate from
uncalibrated runtime UNKNOWN. Add explicit old directives, accepted-only and partial-audio
facts without inventing hearing, consent or external capabilities.

### WP01EVAL-002 Exact application fixtures and dimensions
Given a new input/output case, materialize GenerationContext, DecisionSnapshot,
CandidateRange and related DTOs without guessing defaults. Every output has O1–O6 and
one ordered effect label per effect; compatible, violating and ambiguous labels have
stated rationales. A local deterministic guard is not a successful model rejection.

### WP01EVAL-003 Frozen partitions and integrity
Given the release manifest, every corpus file and case has a SHA-256 digest. Scenario
families and exact request contents cannot cross development/holdout. Existing exposed
cases remain development. Holdout is procedurally reserved, not secretly blinded. Any
look/tune consumes that holdout, and revisions need a new manifest and untouched families.

### WP01EVAL-004 Preregister metrics and fail-closed admission
Given any returned observations, retain failures and abstentions in denominators;
report raw semantic, thresholded and operational results separately. Compatible-response
coverage prevents an always-UNKNOWN judge being called useful. Small samples cannot
establish broad Chinese safety, even at zero observed dangerous passes. Missing evidence,
label disagreement, structural error or budget uncertainty prevents admission.

### WP01EVAL-005 Bounded sequential first run
Given the director-owned remaining 16 attempts and USD 0.003944524 reserve, first recheck
the shared ledger, then reserve one worst-case call before every request. Never reserve
16 calls, retry a failure, tune from one result, reduce a confidence threshold, or call a
provider for Stop/unsupported controls/MEDIA. Connectivity sentinels remain separate.
