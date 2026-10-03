# WP03 Browser audio and explicit microphone capture

Status: implementation slice; live providers and real-device qualification remain separate.
Base: ebb578dde665c9c7269e4a64b508182680b2fa66. Mission deadline: 2026-10-04 08:53:50 UTC; no T0 reset.

## Ownership and consumers

Owned: `apps/web/src/features/audio/**`, `apps/web/public/audio/capture-worklet.js`, `tests/web/audio*.test.mjs`, this spec and `docs/changes/WP03-browser-audio/**`.
Consumer: the integration owner's existing session controller, presentation gate and eventual STT/TTS transport. No edits to those shared surfaces, generated contracts, dependencies or server providers in this slice.
Test owner: existing web lane (`tests/web/*.test.mjs`); no new quality registration required. Tests compile to a unique output directory and use `MIRA_TEST_WEB_DIST`. Resources: local TypeScript and Node, deterministic injected browser primitives, no network/devices. Affected/full/release belong to the integration owner on a coherent integrated snapshot.

## Requirements

### WP03-A01 One generation-bound queue
Given approved mono PCM16 at 24 kHz, opening an authorized origin and pushing ordered chunks submits audio through one Web Audio sink. Caller-owned PCM is copied; chunk and total queue sizes are bounded. An overflow fails the stream rather than silently losing speech. A stream must be explicitly finished; underflow is not completion.

### WP03-A02 Current authority and cancellation
Given a pending resume, queued audio or active source, stop/new-input/error/revoke/close immediately invalidates the generation, disconnects/stops active sound and drops the queue. Late promises, old handles and saved callbacks cannot restart playback or emit completion. Repeated stop/close is safe. Before each source starts, on subsequent progress and on explicit authorization reconciliation, the supplied current-authority callback must approve the exact immutable origin. Timer checks are defense-in-depth; the controller must synchronously stop/reconcile known invalidations.

### WP03-A03 Honest observations
Submitted means accepted by Web Audio start; rendered means a naturally ended buffer reported by Web Audio. Completed means a finished stream drained without failure or revocation. These are software observations, never proof of physical hearing or exact spoken text. Interrupted in-flight frames remain uncertain. Foundation DOM receipts are unchanged and must not be used as audio facts.

### WP03-A04 Explicit capture and lifetime
Constructing a capture object never asks for microphone access. Only explicit start invokes getUserMedia. Stop/close releases all tracks, disconnects nodes, closes ports/context, and rejects late permission/worklet/resume success. Permission rejection, unavailable AudioWorklet/browser APIs, device end and processing errors surface as typed errors while text input remains available to the consumer. No automatic permissions, provider requests, browser speech-synthesis fallback or ScriptProcessor fallback.

### WP03-A05 Accurate bounded PCM capture
AudioWorklet downmixes to mono and emits credit-bounded chunks. Input rate comes from the running AudioContext; source track rate is reported separately when available. Stateful resampling creates PCM16LE at 16 kHz with monotonic sample positions. Chunk credits are acknowledged only after the consumer settles; overflow or consumer error fails closed instead of silently skipping audio. No partial chunk is flushed after cancellation.

### WP03-A06 Evidence limits
Actual targeted behavioral RED and GREEN runs are saved with unique IDs, hashes and commands. Synthetic Web Audio/worklet execution is not a real-device, mobile, acoustic-tail or live Google pass. Browser loopback blocking is respected; no alternate host/port bypass.

## Observable test mapping

- A01: `audio-playback.test.mjs` → `audio queue submits PCM24k sequentially and completes only after finish and natural end`; `invalid and oversized PCM fails closed instead of skipping content`; `an empty finished stream fails explicitly instead of reporting silent completion`.
- A02: playback stop-before-resume, active-stop/saved-onended, new-origin takeover, authorization/revocation, close, observer-stop and immutable-origin tests.
- A03: playback progress test plus `a source start failure cannot claim any submitted or uncertain rendered frames`.
- A04: `audio-capture.test.mjs` explicit start/resource release, delayed permission/module completion, permission denial/unsupported, callback staleness and processing/device-error tests.
- A05: capture PCM metadata/positions, bounded pending deliveries, discontinuity, resampler equivalence; all five `audio-worklet.test.mjs` tests.
- A06: `docs/changes/WP03-browser-audio/verification.md` and unique run records. Evidence is not a behavioral product test.

The inherited traceability checker accepts pytest node IDs only. This Node-only feature intentionally does not invent a `traceability.json` with uncollectable Python nodes. The exact Node test titles are visible in actual execution output and covered by the already-owned web lane. Machine traceability-tool expansion is outside this slice.
