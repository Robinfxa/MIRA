# DEV-ENTRY-01 verification

Recovery checkout baseline: `424b3bf` (`Publish verified 1955 checkpoint with user 0.6 policy and audition fixes`). Verification was run against reconstructed sources in `<project-root>` using the already-installed Python and Node dependencies. No test result from the lost cloud workspace is reused.

## Focused current-source checks

- Final grouped command, using the already-installed Python 3.13 environment: the seven entry/Codex contract modules plus `tests/contracts/test_runtime_admission_preparation.py` → 115 passed. These are offline synthetic transports, including a real FastAPI `TestClient` lifespan and HTTP input, one-session/one-turn limits, unknown and reject stops, Stop cancellation, shutdown close, huge timeout rejection, an inert subprocess without `PYTHONPATH`, private config declarations, a clean temporary checkout with no `apps/web/dist` that builds and serves `/dist/app/main.js`, and the public admission writer-to-reader round trip.
- `node --test tests/web/text-only-entry.test.mjs` → 2 passed. The existing `PresentationGate` and `SceneEffectExecutor` display the generated standalone subtitle and pose without audio. A legacy speech-bound caption remains blocked without audio submission.
- `tools/check_specs.py` → 149 requirement links collected; this checks collection/link integrity, not behavior.
- No live inference, TypeSafe call, Google call, login, credential-cache read, UI/browser call, grant, or paid spend was performed. The admission preflight implementation is a separate explicit metadata operation; its no-argument path remains inert.

## Scope and remaining checks

- This is focused functional verification, not the director-owned `tools/check.py --affected` integration run or full/release run.
- No paired historical RED is claimed for this reconstruction. The registered route/parser contracts are green on the recovered baseline plus rebuilt files; their exact final-source hashes are provided by the implementation owner.
- The CLI's request and turn ceilings are per running process. Restarting with the same Admission creates fresh process-local allowances; they are not a persistent spending ledger and do not cap dollars.
- The cloud context's earlier successful inference does not establish this user's Codex/Google/JEV account entitlement, quota ownership, or portability to another machine. The CLI is text-only unless an admitted in-process voice bundle is used directly; its `--voice-required` option refuses without that factory.
