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

## Reconstructed v2 referent applicability · 2026-10-03 22:20 UTC

Reconstructed in the verified recovery tree from baseline
`424b3bfbb4a9b21db9ffe15bf025cdbddfd10650`. The unpublished original bytes and its
receipts were unavailable after reset. The earlier direct iteration had 3 failing
assertions and 14 passing test instances against the in-progress reconstruction; those
failures exposed missing v2 checks and were fixed. That output was not recorded as an
immutable run and is not the lost historical RED. No prior hashes, RED, or receipts are
being claimed for these files.

- `recovery-v2-referent-006-final-fixture`: 17 passed; exit 0; source changes during
  run = 0. This covers empty-set NO relevance with preserved uncertainty, missing-item
  and display blockers, nonempty ambiguity, presented/unpresented identity, generated
  text, prohibition/Stop controls, strict marker/probability validation, output review,
  two distinct presented items in the ambiguity fixture, v1 helper compatibility, and
  v2 factory selection.
- `recovery-v2-referent-005-final-consumers`: 214 passed; exit 0. Covers existing JEV
  input, decision-contract, development-policy/composition, and evaluator consumers.
  One unrelated OBS-02 traceability manifest changed during the run; the pass count is
  retained with that exact source-drift caveat for the director's integrated check.
- `recovery-v2-referent-003-spec-links`: blocked, exit 1. The repository-wide collector
  rejects a separate OBS-02 mapping to a `.mjs` test; its `.py`-only constraint is not
  caused by the WP01SEM-007 mapping. The director owns the integrated spec check.

Current reconstruction hashes (SHA-256):

| File | Hash |
| --- | --- |
| `apps/api/src/mira/adapters/review/jev_input.py` | `ccf3d12e9068454516209610266e1bb200d9dd4c0198701f0bf4e3f9862973e5` |
| `apps/api/src/mira/application/decision_contracts.py` | `b0c8128ba78daf47076dd248f5bb866951dc537a2aac9bbc1a9525bcb8f6eb97` |
| `apps/api/src/mira/bootstrap/development_review.py` | `2bd99b897841f3c40aebafa9e1fb25a34df0d503e69422aafa05134b58b24133` |
| `tests/contracts/test_jev_referent_relevance_v2.py` | `a326e3ea9d8f73e72c70471bc02e3bd3723f5323ab2ad3fd4fb482f78fa72f77` |
| `specs/features/WP01-semantic-contracts/spec.md` | `da5080bb8f6e44c162f6f8b3e8cb9bd74bab46114588f04ff18be2724aff220d` |
| `specs/features/WP01-semantic-contracts/traceability.json` | `770f0a4e9e14c8f1afe5ad96ddfc0efb44d84f93c88f9edfbbc3d9a10dfa17c1` |

The original user-selected `.6` boundary is unchanged. Only a definite relevance NO
(`<= .4`) plus display-request NO permits the exact unresolved referent marker; the
input observation and response contract retain the raw probability and ambiguous/unknown
identity evidence. Required or midband relevance, absent-item requests without a binding,
and display of existing content without a presented target remain blocked. Synthetic
output rejection checks evidence routing only and makes no claim about real-model
semantic accuracy. No provider, UI, account, credential, or authorization action ran.
