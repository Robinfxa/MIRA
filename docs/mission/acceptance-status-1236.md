# Product acceptance checkpoint — 2026-10-03 12:36 UTC

This is a status overlay on `requirements-and-acceptance.md`, not a change to the requirements. The original 24-hour deadline remains 2026-10-04 08:53:50 UTC.

## Verified baseline

The frozen 12:36 candidate passed 1,065 Python tests and 161 Node tests across all 12 local release lanes, including an installed-wheel check and actual loopback HTTP startup. The complete 4,107-file capture was unchanged after verification. An earlier attempt failed because this new isolated snapshot did not yet have the existing declared TypeScript dependency linked; that environment failure is preserved. No product source was changed for the passing rerun.

A separate immutable 12:30 usability check launched mock and the three documented replay scenarios in approximately 2.3–2.5 seconds with existing Python/Node dependencies. Actual HTTP responses drove the unchanged application/controller/scene through a deterministic DOM harness. Camera, photo, rain, local Stop, late-result suppression, synthetic generation failure, next-input recovery and disconnect recovery passed. This does not show actual browser pixels, physical sound or microphone input.

## Acceptance gaps

| Scenario | Evidence now | Remaining requirement |
|---|---|---|
| A01 no-key startup/interface | Mock/replay start; restored public archive starts; packaged resources serve byte-exact | Current desktop/mobile interactive browser acceptance; fresh dependency installation timing |
| A02 continuous dialogue | Finite mock commands and state continuity tested | Real relevant multi-turn model dialogue and continuous 3–5-minute recording |
| A03 microphone | PCM capture/transport/Google adapter and teardown contracts tested | Authorized real Google identity/service access and actual microphone input |
| A04 speaking interruption | Software playback, cue and cancellation races tested | Actual audible speech interrupted into a new real voice turn |
| A05 late results | Deterministic stale generation/media/audio facts and repeated cancellation tests pass | Corresponding browser/device observation remains open |
| A06 performance/cause | Original expression assets, camera/scene controls and input-linked DOM effects tested | Current pixel review of three expressions/two actions/environment and interactive observation |
| A07 chosen animation branch | Original SVG/CSS character animation implemented | Actual rendered motion acceptance; no claim of live image/video generation |
| A08 error/recovery | Provider-shaped 401/403/429/timeout, cancellation and safe locators tested; logging failures are bounded | Actual device permission/transport failures and a recorded failure/recovery walkthrough |
| A09 real model/mode honesty | Default live guards hold; official Codex local login completed; JEV connection/parser previously verified | Codex backend authorization returns 401; no completed Luna inference; Google ADC handoff pending; Chinese JEV quality/calibration unestablished |
| A10 delivery | Source archive checkpoint is remotely verified; startup, provenance and restoration instructions exist | Expanded Git source tree, final matching version, continuous demonstration recording and final gap report |

The inherited foundation browser screenshots and browser-smoke report do not match current source hashes or labels. They are historical evidence only and cannot support these current acceptance items.

## Immediate product work

The existing replay is a fixed fixture stream that ignores input and cannot carry the requested interactive walkthrough. A new explicitly offline rehearsal is being implemented separately from this snapshot: finite scenario choices, original fixed speech clips, real application permit/audio/caption machinery, synthetic-listening disclosure, Stop and recovery. It will neither record the microphone nor approve arbitrary real content. Its result must be verified independently before being described as complete.

## User-added observability north star

The candidate includes explicit raw-recording opt-in with a persistent UI notice, bounded private storage, default sanitized diagnostics and export, recursive credential filtering, cancellation cleanup and safe asynchronous diagnostic locators. Bare playback interruption is reported as an unknown cause; it is no longer fabricated as a user Stop click. Explicit Stop and superseding input retain their known cause.

All raw-recording checks used synthetic data. Real raw recording remains OFF. Provider credentials, authorization headers and tokens are never eligible for capture, including in development mode. Independent cross-boundary privacy and diagnostic-usability review is still in progress.
