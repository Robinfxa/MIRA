# WP06 frontend voice verification

Final scoped execution:2026-10-03 10:25:09–10:25:10 UTC. Base:`ebb578dde665c9c7269e4a64b508182680b2fa66`. Node v24.19.0, TypeScript5.8.3.

## Result

Strict TypeScript compile and108 Node tests passed,0 failed. The receipt hashes source/test inputs before and after; `source_changed:false`.

- [Final receipt](runs/wp06-final-web-20261003T102509Z/receipt.json)
- [Final test output](runs/wp06-final-web-20261003T102509Z/test.log)
- [Integration contract](integration.md)
- [Specification](../../../specs/features/WP06-frontend-voice/spec.md)

The108 include65 inherited gate/audio/scene tests and43 added integration/race cases (including two narrowly authorized capture-cleanup cases). Repeated runs are regression evidence, not additive independent test counts. The earlier85-test checkpoint and107-test near-final run remain distinct snapshots. The final WAV negative control was added after107 and is included in108.

## Actual behavioral RED → GREEN

Unique folders under `runs/` retain terminal output and selected actual compiled RED artifacts. These are not retroactively claimed to have full `record_check.py` metadata, identical complete later-expanded test files, or a self-contained historical source replay bundle. The final run has complete selected frontend/test hashes. Tests added after implementation without a failing predecessor are honestly regression/baseline checks.

| Case | Actual RED | GREEN evidence |
|---|---|---|
| Independent speech gate/audio facts | `wp06-gate-red-20261003T094342Z`:5 failed | `wp06-gate-green-20261003T094446Z`:25 including20 inherited |
| Authenticated voice transport | `wp06-transport-red-20261003T094847Z`:4 failed/1 passed | `wp06-transport-green-20261003T095143Z`:5 passed |
| Controller causal voice lifecycle | `wp06-controller-red-20261003T095441Z`:6 failed | `wp06-controller-green-20261003T095840Z`:6 passed |
| Speech/audio protocol | `wp06-protocol-red-20261003T095928Z`:2 failed | `wp06-protocol-green-20261003T100015Z`:22 including20 inherited |
| Scene composition and PTT | `wp06-ui-red-20261003T100139Z`:2 failed | `wp06-ui-green-20261003T100255Z`:2 passed |
| Old history failure/foreign session | `wp06-races-red-20261003T100721Z`:2 failed | `wp06-races-green-20261003T100820Z`:33 focused regression |
| Stale capture cleanup | `wp06-capture-race-red-20261003T100751Z`:1 failed/1 passed | same33-case run and final108 |
| Server delete failure | `wp06-transport-safety-red-20261003T101023Z`:1 failed | `wp06-transport-safety-green-20261003T101138Z`:21 focused regression |
| Raw JSON error leakage | `wp06-transport-sanitization-red-20261003T101044Z`:1 failed | same21-case run and final108 |
| Empty submit during PTT | `wp06-empty-submit-red-20261003T101834Z`:1 failed | `wp06-empty-submit-green-20261003T101848Z`:3 passed |
| Startup microphone pacing | `wp06-mic-pacing-red-20261003T102039Z`:1 failed | `wp06-mic-pacing-green-20261003T102140Z`:28 focused regression |
| WAV is not raw PCM | `wp06-raw-pcm-red-20261003T102447Z`:1 failed | `wp06-raw-pcm-green-20261003T102508Z`:12 passed; final108 |

The initial transport build at09:47:13 failed while API consumer stubs were incomplete; this is explicitly preparation/compile failure, not a behavioral RED. The first too-long JSON leakage marker did not expose V8's truncated error excerpt and passed; the tightened short marker then produced the recorded actual RED before fixing parsing.

## Deterministic integration coverage

Real CancelSafePlayback with injected Web Audio primitives verifies long7.5s synthetic speech,4s backpressure, explicit completion only after all naturally ended sources, interrupt wakeup, rendered/terminal ordering and cutoff, stale onended suppression and idle snapshot behavior. Injected WebSocket/fetch and clocks establish auth-first/no token URL, bounded queue, paced drain, finality, malformed/truncated streams, canceled fetch, late create cleanup, resource close and PTT races. UI gesture tests execute the compiled composition code with synthetic DOM/controller primitives; they are not browser-rendering tests.

Each TS build used a unique `var/voice-evidence/<run>/dist` directory and `MIRA_TEST_WEB_DIST`. No shared `apps/web/dist`, Git/index, locks, generated contracts, backend or scene assets were written by this slice. One audio/capture cleanup race change and its tests were explicitly reassigned by the director.

## Not run / not established

No full/release/backend suite, actual browser/device, microphone permission acceptance, live provider/account, acoustic latency/instantaneous silence, gapless playback, text-to-sample alignment, remote CI, deployment or original164-case acceptance claim. Source controls and bindings do not establish a successful live voice product. Default unavailable voice stays unavailable; no mock/provider fallback disguises it.
