# Offline evaluation preparation evidence · 2026-10-03

## Result

- 20 original input examples audited without modifying the original corpus.
- 16 new input fixtures: 8 development / 8 procedurally reserved holdout.
- 35 output fixtures: development 10 compatible + 9 violating + 1 ambiguous;
  holdout 6 compatible + 4 violating + 2 ambiguous; 3 separate no-call guards.
- 93 targeted corpus/DTO/adapter-mechanics tests passed using `.venv313/bin/python`.
- Repository spec checker collected 84 requirement links. Collection is not execution.
- Zero live calls, credential reads, threshold/prompt edits, calibration references,
  external actions, factory activation, or changes to existing semantic corpus.

## Exact recorded commands and limits

`001-red-integrity.txt` and `002-red-integrity.txt` are dependency failures from the
incomplete `.venv/bin/python` and default Python respectively. Neither is behavioral
RED. No dependency installation was attempted.

`003-red-integrity.txt` is the first actual assertion failure under `.venv313/bin/python`
for the missing frozen release artifact. More tests were added after that run, so this
is not a same-file RED/GREEN pair.

`004-red-frozen-release.txt` records the same final test-file version failing the explicit
frozen-manifest assertion before the manifest existed:

`.venv313/bin/python -m pytest tests/contracts/test_jev_evaluation_corpus.py::test_evaluation_release_exists_and_is_frozen -q`

This is an artifact-integrity RED, not a semantic-quality RED. `004-red-test.sha256`
records the final test-file hash. Creating the actual corpus release manifest supplied
the missing artifact; tests were not weakened to generate success.

`005-green-corpus.txt` and `005-green-corpus.junit.xml` record:

`.venv313/bin/python -m pytest tests/contracts/test_jev_evaluation_corpus.py -q --junitxml=specs/features/WP01-jev-evaluation/005-green-corpus.junit.xml`

Exit 0, 93 passed in 0.17 s. These 93 are structural/mechanical pytest cases, never
93 live model observations. The fabricated transport returns all-allow solely to check
exact effect coverage and that absent calibration still yields UNKNOWN. It does not
validate the human semantic gold labels.

`006-spec-links.txt`: `.venv313/bin/python tools/check_specs.py`, exit 0,
84 requirement links collected. No full product or quality-lane execution implied.

`007-lint.txt`: `.venv313/bin/python -m ruff check tests/contracts/test_jev_evaluation_corpus.py`,
exit 1 because `ruff` is not installed. Lint is not_run; no claim of a pass.

## Source identity and integration limitation

`release-manifest.v1.json` freezes corpus artifacts, per-case hashes and source fingerprints;
`release-manifest.v1.sha256` records its own digest externally. The test-file digest matches
the final RED hash. These files are local verifiable records, not signed attestation.

The shared checkout was changing under other assigned owners. After the 93-test run,
`apps/api/src/mira/application/contracts.py` no longer matched its v1 source fingerprint.
The parent was notified immediately. The targeted pass is a real executed result, but
must NOT be described as an immutable integrated snapshot or final full/affected pass.
Do not run live evaluation from this source manifest until the director reconciles and
pins a final source snapshot with a new run/source manifest. Corpus artifacts themselves
retain their frozen hashes. No adapter or source file was changed by this worker.

The director owns frozen-source affected/full integration. No remote CI, real device,
D-M pixels, physical hearing, Chinese live quality, second-adjudicator agreement or
calibration admission was run by this worker. A live runner and metric accumulator are
specified only; traceability tests verify corpus dimensions, partitions, accounting
invariants and disabled defaults, not an unimplemented live metric pipeline.

## Independent review still needed

Every gold dimension remains a proposed human label, not a provider result. A second
Chinese reviewer must adjudicate the overlapping O1/O4/O5 dimensions and stage/seal
interpretations before scored calls. Existing source/threshold policy is not silently
tuned to these proposed labels. The holdout is procedurally reserved and visible to its
authors, so it must not be advertised as independent blinded validation.

`008-green-frozen-release.txt` reruns the exact single node from 004 against the same
unchanged test-file hash after the manifest exists: exit 0, 1 passed. This completes the
narrow actual artifact-integrity RED/GREEN pair. It adds no model-quality evidence.
