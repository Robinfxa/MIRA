# Verification: WP01 semantic contracts

Completed 2026-10-03. Offline synthetic mechanics only. Interpreter: `.venv313/bin/python`.
Common baseline: ebb578dde665c9c7269e4a64b508182680b2fa66. Original deadline unchanged.

## Executed evidence

Immutable recorder directories are `docs/verification/wp01-semantic-contracts/runs/`.
No result below is model-quality, live-account, physical-audio or product admission.

- 001-red-contracts: collection error from an initial test import, exit 2. NOT behavioral RED.
- 002-red-contracts: 16 failed, 16 passed against interface stubs. Behavioral implementation RED.
- 003-green-contracts-audio-seam: 32 passed. The integration owner's AudioProgress seam was
  then available; the two initial partial-word/evidence-as-rule test assumptions were
  corrected to no word alignment and separate typed facts. Do not claim every test byte
  is identical to 002 or that the invalid initial assumptions are accepted architecture.
- 004-red-evidence-hardening -> 005-green-evidence-hardening: identical tests, 4 failed
  then 4 passed; zero-sample completion/oversized samples and inconsistent accepted IDs.
- 006-green-transport-hardening: 64 passed; extra malformed-response/concurrency/HTTP
  regression coverage added after core implementation, not retrospectively claimed RED.
- 007-red-malformed-local-facts -> 008-green-malformed-local-facts: identical tests,
  2 failed then 2 passed; unhashable nested identities and unencodable Unicode.
- 009-green-final-targeted: 67 passed, including offline corpus structure check.
- 010-spec-links: 50 repository requirements reference collected tests (6 are this slice).
  This is collection/link evidence only, not execution or model-quality evidence.
- 011-existing-output-regression: 97 pre-existing JEV output/HTTP tests passed.
- 012-architecture-guards: 3 relevant application/import/config ownership guards passed.
- 013-red-evidence-repr -> 014-green-evidence-repr: identical test, 1 failed then 1 passed;
  snapshot repr must not accidentally expose partial/presented speech text.
- 015-final-all-targeted: 165 passed = 68 tests in this slice + 97 existing output tests.
  It is a combined final rerun, not 165 new tests; all source-before/after changes = 0.

- 016-final-spec-links: 50 repository requirements linked after the privacy test mapping.
- 017-red-old-prefix -> 018-green-old-prefix: 1 failed then 1 passed for stale accepted-only
  prefix epoch/activity rejection. RED 017 saw concurrent changes to two unrelated frontend
  files; its assertion failure is recorded but it is NOT a frozen-source integration
  result. GREEN 018 had source-before/after changes = 0.
- 019-final-targeted-rerun: 166 passed = 69 tests in this slice + 97 existing output tests;
  source-before/after changes = 0. This is the final code result, superseding 015.

The three strict hardening RED/GREEN pairs retained identical test files at their pair
runs and immutable stdout/report hashes. Initial implementation RED is separately
qualified above. Evidence records are never overwritten.

## Not executed / blockers

- Ruff is absent from the selected .venv313 (`No module named ruff`). No install attempted.
- Shared affected/full/release runs remain the director's responsibility on a frozen
  integrated source snapshot. The changed-file quality plan was attempted but selector
  rejected unowned concurrent voice tests `tests/integration/test_voice_http.py` and
  `tests/unit/test_audio_transitions.py`; director was notified. These are outside this
  slice's write ownership. All four new semantic-contract test files have the existing
  unique providers-lane glob owner. No quality registry edits were made here.
- Chinese evaluation, calibration, live key/account/endpoint, paid calls, latency/cost,
  external network inference, D-M, image identity admission and device/audio checks: not_run.
- No git mutation, commit or push; no installation or credential access.

## Deliverables and remaining integration

New application DTO/producer, input decision port, real typed JEV input adapter using
injected transport; synthetic HTTP coverage; 20-case original Chinese expected corpus;
primary-provider notes and exact integration handoff. See `integration.md`.

The corpus includes negation, quoted restrictions, simultaneous obligations, controlled
referents/ambiguity/unknown exposure, unsupported raw requests, no consent revival, and
explicit local Stop. Expected labels are human-authored synthetic hypotheses for later
bounded evaluation, never model outputs or an accuracy estimate.

Output adapter was not edited. The director must carry ResponseContract.snapshot and
input_observation as separate evidence fields in its trusted JEV mapping. Dropping these
facts or serializing them as effective constraints is prohibited; until that seam is
implemented the resolver must return None. Input and output calibration stay separate
and off by default. No MEDIA candidate receives a contract from this producer.

- 020-final-spec-rerun: final 50-requirement collection/link check passed; source changes = 0.

## Later confidence correction · 2026-10-03 10:45 UTC

The earlier offline evidence remains intact. Both JEV Choice validators now share the
bounded finite-decimal compatibility policy and independent regression cases described
in [the correction addendum](confidence-contract-correction.md). A real 24-test
RED/GREEN pair and 193-test targeted regression passed with no covered-source changes.
This does not supply Chinese calibration or imply an authenticated post-fix parser run.
