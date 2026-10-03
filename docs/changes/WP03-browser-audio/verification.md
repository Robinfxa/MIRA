# WP03 browser audio verification

Final targeted execution: 2026-10-03 09:32:01–09:32:02 UTC. Node v24.19.0; TypeScript 5.8.3. Base `ebb578dde665c9c7269e4a64b508182680b2fa66`. This is a focused browser-runtime slice, not the full original voice product or a live-provider pass.

## Delivered

- One cancel-safe Web Audio PCM16/24-kHz queue, immutable origins, generation-bound stream handles, bounded copied buffers, current-authorization checks, synchronous local cancellation and explicit software progress facts.
- Explicit-user-start AudioWorklet microphone capture, resource cleanup across delayed permission/module/resume operations, truthful rate metadata, stateful 16-kHz PCM16LE conversion and credit-bounded delivery.
- 27 deterministic tests: 12 playback, 10 capture/resampling and 5 VM-executed worklet tests.
- Exact integration contract: [integration.md](integration.md).

## Actual RED → GREEN

All commands ran offline with synthetic samples. RED stubs retained the public API so failures were behavioral assertions, not missing-import/collection failures. Later hardening REDs were real defects found before changing implementation. Existing passing cases in those groups are regression coverage, not independent RED evidence.

| Records in `runs/` | Target | Actual RED | Same-target GREEN |
|---|---|---:|---:|
| 001 → 002 | playback initial queue/cancellation group | 8 failed | 8 passed |
| 003 → 004 | capture/resampling | 10 failed | 10 passed |
| 005 → 006 | actual worklet script in VM | 5 failed | 5 passed |
| 007 → 008 | playback with start-failure accounting | 1 failed, 10 passed | 11 passed |
| 009 → 010 | playback with empty-stream rejection | 1 failed, 11 passed | 12 passed |
| 011 JSON | final strict compile + all audio tests | not a RED run | 27 passed, 0 failed |

Do not sum repeated passes as independent test counts. Final source/test hashes and exact commands, exit codes, runtime versions and timestamps are in `runs/011-audio-final-20261003T0932.json`; no included source changed during that run. Historical terminal outputs are saved, alongside RED source/test snapshots and hashes. Early runs have terminal exit evidence and retained snapshots, rather than an invented retrospective full-source recorder receipt. The artifact manifest includes output hashes.

## Commands

Every TypeScript test run compiled to a unique `<temporary-evidence-path>` directory and set `MIRA_TEST_WEB_DIST` to it. No shared `apps/web/dist` was written.

```sh
node_modules/.bin/tsc -p apps/web/tsconfig.json --outDir <temporary-evidence-path>
MIRA_TEST_WEB_DIST=<temporary-evidence-path> node --test tests/web/audio-playback.test.mjs tests/web/audio-capture.test.mjs tests/web/audio-worklet.test.mjs
```

The worklet-only RED/GREEN commands were `node --test tests/web/audio-worklet.test.mjs`. Other paired commands selected the corresponding single Node test file following isolated TS compilation. Tests are already registered by the web lane's `tests/web/*.test.mjs` glob; no quality-owner file was edited.

## Explicitly not established

- No actual microphone permission, physical speaker output, acoustic stop-tail timing, mobile browser, Safari/Chrome worklet behavior or ASR-quality measurements were performed.
- No Google STT/TTS call, account check, model availability claim, browser speech-synthesis fallback, deployment or network transport implementation is included.
- Sequential Web Audio source starts can have main-thread gaps. PCM resampling uses a basic box filter, not a qualified high-order audio resampler. Capture stop discards partial tails and is not graceful server STT finish/drain.
- The inherited DOM receipt was not reinterpreted. The controller/gate/progress wire integration remains with its single owner, who must wire every invalidation path.
- Full/affected/release checks, real-browser smoke and original 164-case acceptance catalogue are not run by this slice. The known loopback browser restriction was respected. Final integrated checks must run against the integration owner's coherent final snapshot.
