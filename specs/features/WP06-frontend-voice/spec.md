# WP06 frontend voice integration

Base: `ebb578dde665c9c7269e4a64b508182680b2fa66`. Mission deadline: 2026-10-04 08:53:50 UTC; original T0 is unchanged.

## Ownership, consumers and resources

Owner: frontend voice integrator. Owned surfaces: session controller/API client/ports/audio transport; presentation gate/ports; shared protocol parser; app composition; controller*, gate-audio* and transport* Node tests. Integration owner additionally authorized one narrow capture cleanup race fix and its two capture tests. Generated contracts, backend, scene/assets/CSS, dependency locks and quality ownership remain with their existing owners.

Test block: existing `web` lane (`tests/web/*.test.mjs` already assigns these tests once). Consumers: generated HTTP protocol, session endpoints, scene executor, browser audio. Resources: synthetic fetch/WebSocket/Web Audio/media/worklet primitives, TypeScript and Node; unique build output for each run. No device permission automation, live provider, browser loopback bypass or full/release suite. Integrated affected/full checking belongs to the director on a coherent combined snapshot.

## Requirements and observable tests

### WP06-001 Independent authority and honest facts
Given an approved speech effect, one-shot claiming does not remove continuing authorization. Speech never reaches the visual executor or DOM receipt endpoint. Each accepted naturally rendered/completed/interrupted/failed software fact shares the monotonic presentation sequence with visual receipts. Submitted/in-flight samples are never reported as rendered. Tests: `gate-audio.test.mjs` (all five), `gate-audio-protocol.test.mjs` (both), and controller `new text stops locally before request and explicit speech never reaches DOM receipt`.

### WP06-002 Local cutoff and history delivery
Given active sound, a new text input, PTT, Stop, error, revocation or close first closes the latch and stops the sink. Synchronous terminal facts obtain their sequence before the next input/Stop cutoff. Already established facts are delivered serially and can arrive after the fence; an old fact's delivery failure cannot stop a newer output. Tests: controller `stop terminal fact is sequenced within stop cutoff before network`, `late failure saving old terminal history does not stop newer input playback`, `software rendered facts precede terminal delivery while Stop is immediately local`.

### WP06-003 Bounded speech transport and playout
Given an authenticated speech POST, the browser verifies NDJSON origin, sequence, contiguous offsets, canonical PCM16LE mono24k payload and explicit matching completion. Truncation, malformed encoding, unsupported rate, foreign identity or trailing packets fail closed. A single held packet and rendered-sample-based 4s backpressure avoid overflowing the 5s sink. Tests: `transport-audio.test.mjs` speech cases; controller `real single sink backpressures long speech to four seconds and stop releases blocked packet` and `real long speech completes only after every naturally ended source`.

### WP06-004 Causal microphone finish
Given an explicit user gesture, capture starts once immediately while prior output is stopped; PCM is bounded while the network Stop acknowledgement is pending. The WebSocket uses that acknowledgement's activity/input epoch and authenticates only in its first message. Ordered PCM drains before finish. Only a nonempty reliable final transcript, with no newer activity/Stop/close, creates a new causal input. Interim-only, empty, punctuation-only and explicit noise-marker results create no turn. Tests: controller PTT, pending-stop acknowledgement, late capture readiness, empty/interim/noise and pending final transcript cases; transport microphone auth/drain/disconnect/bounds cases.

### WP06-005 Lifetime and late callbacks
Given close or a newer activity during connect, fetch, permission, playback, socket or poll, old continuations cannot reconnect, push, finish, present or submit. Close releases the single sink/capture/socket/fetch and timer state; a returned late created session is deleted best-effort. Failed server deletion is not reported as confirmed cleanup. Tests: controller close/old-input/late-packet/revoke cases; `transport-client.test.mjs`; capture `old context close rejection cannot report failure into a newer capture` and its current-cleanup warning control.

### WP06-006 Actual local phase and usable fallback
Given actual capture/playback events, the scene shows listening/speaking; ready/idle snapshots alone do not stop an active speaking phase. Stop keeps the existing photo/environment via the scene executor. Microphone, autoplay, transport and cleanup problems are surfaced with text controls still available. Mode labels come from actual capability metadata, never animation. Pointer/keyboard PTT supports release and cancellation. Tests: controller idle/revoke cases, `controller-main.test.mjs`, and inherited scene/audio regression tests.

## Qualification and traceability boundary

Tests establish offline software behavior, never physical acoustic output, word timing, hardware cutoff latency, human hearing/understanding, live Google/LLM/review behavior or real-browser/mobile acceptance. Main-thread scheduling and browser background throttling remain unqualified. Capture Stop discards partial worklet/resampler tails; finish covers only PCM already accepted by the bounded frontend path.

The inherited machine traceability tool collects pytest nodes only. This Node-only slice uses exact observable test titles and actual run outputs instead of inventing an uncollectable `traceability.json`. Historical RED logs and retained compiled snapshots are evidence of actual runs; later added baseline tests are not retrospectively called TDD REDs.
