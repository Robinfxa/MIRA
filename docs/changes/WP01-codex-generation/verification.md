# WP01 Codex generation verification

All commands below used the existing .venv313 Python. No package installation, real
Codex runtime start, authentication-file read, model inference, network provider call,
Git/index operation or publication was performed by this worker.

## Delivered scope

- Concrete default-OFF GenerationBackend implementation with fresh native stdio process
  factory plus explicit offline transport injection.
- Pinned v0.159.2 executable/profile, full effective-config fingerprint gate, managed-policy
  environment confirmation gate, subscription account check and exact low-cost model.
- Strict structured effects for independent downstream review; no parallel Actor/reviewer.
- Bounded asynchronous queued stdio, cancellation/interrupt, TERM/KILL/reap and resource caps.
- Seven linked requirements and three synthetic contract-test files. The director owns
  registration of these files under providers in tests/quality.toml and affected integration.

## Actual RED to GREEN

Evidence is under this directory's runs/ with unique non-overwritten names. JSON receipts
record SHA256 of source and identical test files at each paired stage, plus output hashes.
The early paired receipts are focused source fingerprints taken for that local stage,
not whole-repository immutable-snapshot attestations. The final run is an immutable copy
with complete source_before/source_after maps and source_changed=false.

| Pair | Same selected behavior | Actual RED | Actual GREEN |
|---|---|---:|---:|
| 001-red → 002-green | test_codex_generation.py | 33 failed, 6 passed | 39 passed |
| 003-process-red → 004-process-green | test_codex_generation_process.py, initial 9 tests | 1 failed, 8 passed | 9 passed |
| 006-profile-red → 007-profile-green | native default backend and premium-tier tests | 2 failed | 2 passed |
| 008-cleanup-red → 009-cleanup-green | cancellation during close/reap | 1 failed | 1 passed |

Initial RED used an importable asynchronous adapter stub that raised codex_not_implemented;
it was not a missing-import, dependency or collection failure. Six negative tests passed
against that stub and are not claimed as proof of their final semantics at that stage.
The process RED exposed an actual already-created synthetic child left alive when spawn
was cancelled. The cleanup RED exposed a SIGTERM-ignoring child left alive when cleanup
itself was cancelled. Both RED tests explicitly reaped the child in test teardown; the
fixed production paths retain ownership, force termination as needed and reap it.

The profile RED combined one overstrict check (rejecting the legitimate native default
chatgpt_base_url) and one missing check (accepting a reported premium thread service tier).
Both were corrected from pinned-source/native-metadata evidence, without actual inference.

## Final checks

- 010-final-focused: 86 passed in an immutable temporary source copy, exit 0,
  source_changed=false. Includes an end-to-end adapter run against an actual synthetic
  Python stdio child, not merely an in-memory mock.
- Additional adversarial tests added after earlier implementations are ordinary verification,
  not retroactive RED evidence. Counts across runs are overlapping and must not be summed.
- Architecture suite: 19 passed on the current canonical tree. This was a focused architecture
  check, not an immutable whole-project integration report.
- Owned traceability: all seven requirement mappings resolve to actually collected pytest
  node IDs. Mapping validation is not execution evidence.
- compileall for the adapter and private support modules passed.
- Ruff was not run: .venv313 has no ruff module; no installation was attempted.
- Whole-project affected/full/release, live model/account completion, browser/mobile, audio,
  Chinese semantic calibration and independent human review: not run by this worker.

The authenticated native runtime remains unadmitted: root owns subscription/model smoke,
its effective config digest, exact managed-policy environment preservation, independent
reviewer integration and later explicit activation. The adapter's default flag is false
and budget is zero regardless of the presence of executable/home paths.

## Test registration handoff

Register exactly once under providers:

- tests/contracts/test_codex_generation.py
- tests/contracts/test_codex_generation_process.py
- tests/contracts/test_codex_generation_hardening.py

Owned files: codex_app_server.py and codex_support/ under generation; those three tests;
specs/features/WP01-codex-generation/ and docs/changes/WP01-codex-generation/.
Shared config, loader, bootstrap, actor, domain, HTTP, frontend, auth helpers, dependencies,
quality registry and existing documentation were not edited by this worker.
