# Public archive recovery rehearsal

Date: 2026-10-03. Target: published checkpoint commit `54c1457cd897133e9ca0b3035fcd0a73ba8bef22`; archive SHA-256 `cac357c3e5c21b283321a938a7c5d35e1ecaded5e65869d9aa21d7439f3ae37b`.

## Verified from public artifact files

- Verified the seven published sidecars/archive against `SHA256SUMS-20261003T1158Z.txt`; every listed file returned `OK`.
- Ran the published Python-standard-library restore utility into a new throwaway destination. It verified 439 nested paths, sizes, hashes and stored modes, then confirmed Unix-restored modes. The archive has 439 regular files; `scripts/dev` is 0644, confirming it must be invoked through `sh` on Unix.
- In that restored tree, ran the documented replay-profile command with the already available local Python and TypeScript dependencies explicitly reused as verification dependencies. `GET /api/v1/health` returned HTTP 200; the compatibility response intentionally reports replay under `mode: "mock"`, with all `live_*` flags false.
- Repeated the health check in mock mode: HTTP 200, mode `mock`, all `live_*` flags false.
- Ran the ordinary diagnostics export command against the recovered tree. Its manifest reported `raw_included: false`; the archive contained only `manifest.json` and `events.jsonl`.
- Scanned the recovered setup/command/configuration scope (52 files) for private workspace paths, PEM private-key headers, AWS access-key shapes, OpenAI live-key shapes, JWT shapes and Google service-account email shapes. No candidates were found. This scan is a heuristic, not a general secret detector.
- The published development environment template's Google project and quota-project settings are empty; no project/account identifiers are configured there.

Existing release and startup verification reports record previous mock/replay and broad local release checks. This rehearsal adds archive extraction and direct mock/replay startup evidence for the recovered public snapshot; it does not repeat the broad suite.

## Deliberate limits and findings

- No fresh Python or Node dependency install was run. Existing local Python/Node/TypeScript installs were used only as declared local verification dependencies; this is not a fresh-machine installation claim.
- The archive contains offline `mock` and `replay` profiles. A separate newer-profile rehearsal is upcoming and remains unverified here.
- `package.json` records `0.4.0`, while `package-lock.json` records root package version `0.4.1`. Since `npm ci` was not run, the impact of that metadata drift is unknown; fresh install remains unverified.
- The backup instructions already documented hashing, safe extraction, modes and offline startup. They did not provide official runtime download references, practical startup failure codes, a default diagnostic-export command, or the unsupported historical-evidence warning in one recovery guide; `docs/development/INSTALL-RECOVERY.md` fills those gaps.
- The checkpoint intentionally omits raw historical FND-02 logs, so `tools/verify_tdd_evidence.py` is not supported from this projection. README and checkpoint notes document other verification limits: remote CI, live providers, browser/device audio, long continuous acceptance, fresh installs, deployment and merge were not verified.

No source, README, shared production files, archive contents, credentials, account identifiers, or private paths were changed or published by this rehearsal.
