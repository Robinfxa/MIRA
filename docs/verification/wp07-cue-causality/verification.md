# WP07 cue-causality correction verification

2026-10-03 UTC. Original mission T0 unchanged. Synthetic offline software validation only; this report does not establish physical hearing, word-level synchronization, real browser/mobile acceptance, acoustic Stop latency, or live LLM/JEV/Google service behavior.

## Result and bounded design

The application compiler now owns a fresh `cue_id` for each accepted CandidateRange and `cue_speech_id` for that range's exact speech effect. A speech cue permits one speech and at most one explicit subtitle; independent text/visual ranges have a null speech dependency. The effect digest binds cue metadata. Model output cannot assign identities, and both the Codex parser and compiler reject ambiguous speech ranges.

The existing gate withholds only speech-associated non-speech effects until that exact speech's first actual software source submission, emitted by the existing single playback sink after source.start(). Opening transport, granting output, queued PCM, and a stalled context.resume() do not release captions. Source submission is not a rendered/completed audio receipt and does not prove hearing. No caption is derived from text equality, no speech is fabricated from a subtitle, and independent visual cues remain immediate.

Stop, error, revocation, close and superseding input retain the local cancellation latch. Already shown photo/environment persist through the existing SceneEffectExecutor. The tests explicitly inspect its state after Stop. Metadata is immutable across revisions and caller substitutions; duplicate IDs, wrong or missing peers, mixed dependencies, multiple speech/caption members, invalid field types and mixed legacy speech/visual payloads fail closed. Legacy visual-only grants and isolated legacy speech stay compatible. Presented-history captions can omit a speech peer because visible captions and completed audio are different facts.

Session phase errors now pass through safeSessionError after view.update. A reviewer additionally found prototype-name codes returned inherited object members; own-property lookup makes constructor/toString/__proto__ use the same actionable fallback. Safe HTTP diagnostic request IDs survive unchanged. Fixed character policy now comes from existing mira26_author_policy(), not duplicated or user-inferred biography.

## Actual RED / GREEN sequence

1. `red-node.txt`: first new 19-test suite, 18 failed / 1 passed on inherited dist. One backpressure assertion's early exit also exposed an unhandled test cleanup promise; the test then attached its expected rejection handler without changing the assertions.
2. `red-node-isolated.txt`: same 19 tests on freshly compiled retained `red-dist`, 18 failed / 1 passed. Failures were early captions/receipts, unsafe session errors, malformed cue acceptance and mutable cue metadata, not import/collection failures.
3. `red-python.txt`: 8 compiler/parser tests, 7 failed / 1 passed for absent cue identity, ambiguous candidate acceptance and unbound digest.
4. `green-node-1.txt` and `green-python-1.txt`: identical corresponding tests, 19 and 8 passed after implementation.
5. `red-author-policy.txt` -> `green-author-policy.txt`: requested authoritative-policy test fails on missing author_policy, then passes from the existing typed source. Nine total cue Python cases pass.
6. Five additional regression cases, recorded honestly as baseline coverage rather than invented RED, yield 24/24 in `green-node-extended.txt`. They inspect actual SceneEffectExecutor preservation, malformed replacement disconnection, superseding input, submitted-origin validation and safe HTTP request IDs.
7. Independent review found prototype-name unknown-code failures. `red-error-prototypes.txt` records three real failures; `green-error-prototypes.txt` records 27/27 cue Node cases after the own-property fix.

`red-manifest.json` records pre-implementation production/test hashes. `red-controller-cues.mjs` and `red-cue-compilation.py` preserve the exact original test prefixes; their SHA256 hashes were verified against the RED manifest after subsequent tests were appended. Retained red-dist, green-dist and final-dist are isolated software builds, not served browser acceptance artifacts. Existing evidence was not overwritten.

## Scoped regression results

- `regression-node-1.txt`: 134/134 then-existing web tests.
- `regression-node-final.txt`: 139/139 with added scene/supersede/identity regressions.
- `regression-node-prototypes.txt`: final 142/142 web tests, using retained final-dist after prototype-key correction.
- `regression-python-2.txt`: 266/266 scoped Python tests (cue compiler, Codex generation/hardening/process, fixture port, actor, domain/audio transitions, replay actor, HTTP/replay/audio/voice, semantic composition, JEV input corpus, architecture).
- TypeScript noEmit and canonical export drift check pass (`typecheck.txt`, `contract-check.txt`). Generated files were produced only by tools/export_contracts.py. Existing mapper already propagates dataclass fields through asdict; no duplicate mapper was added.

These counts are cumulative runs and must not be summed as unique test coverage. Concurrent director work exists in this integrated tree; a coherent final affected/full integration run remains the director's responsibility.

## Explicit representation migration and boundaries

`regression-python-1.txt` had 335 passing and 23 failing tests. All 23 failures were frozen-v1 evaluation exact-dictionary comparisons receiving added cue_id:null/cue_speech_id:null on old synthetic Effect records. No frozen gold rows, manifests or labels were rewritten by this worker. The director owns a documented versioned evaluation representation migration; this report does not call that earlier run green.

Application contracts, Actor stage/seal/diagnostics hooks, decision_runtime, diagnostic-event privacy adapters, config/bootstrap, dependency locks and live admission remain outside this change. Canonical schema/export ownership was released to the director at 11:34 UTC for the separately owned HTTP 422 description portability correction. No further schema/export writes by this worker.

No live calls, credential access, native/browser localhost attempts, Git operations, publication, generic timeline framework or new playback authority were performed. Source submitted means only software source submitted. Associated captions stay withheld if speech never submits; standalone text/visual cues remain available immediately.

## Re-run commands

From the canonical repository with its existing dependencies:

    node node_modules/typescript/bin/tsc -p apps/web/tsconfig.json --outDir <temporary-evidence-path>
    MIRA_TEST_WEB_DIST=<temporary-evidence-path> node --test tests/web/*.test.mjs
    .venv313/bin/python -m pytest tests/contracts/test_cue_compilation.py -q
    .venv313/bin/python tools/export_contracts.py --check

For the real historical caption RED without modifying current production source, use retained red-dist with retained test-prefix copy from this evidence directory. Because that copy's relative default build path differs, set MIRA_TEST_WEB_DIST explicitly.
