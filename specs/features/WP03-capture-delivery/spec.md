# WP03 capture delivery and quiet handoff

Owner: web, through the existing unique `tests/web/*.test.mjs` owner in `tests/quality.toml`. Consumers: MicrophoneCapture, the production AudioWorklet and PCM resampler, ContinuousListeningController, BrowserAudioTransport, and the unchanged ASGI listening lease. Base: immutable `mira-silence-conversation-capture-20261005T1551Z`. No schema, backend, provider budget, credentials, device access, or permissions change. Evidence is append-only outside source.

## Requirements

- CAPTUREDELIVERY-001: Given real 128-frame worklet quanta at 44.1 or 48 kHz, and 20 or 40 ms batches accumulated before readiness, send contiguous PCM through a finite FIFO paced from ready time. An endpoint follows its exact sample frontier; no synchronous startup burst may consume the WebSocket buffer. The existing 65,536-byte and 100-packet capture bounds remain finite. A failed startup drain must not publish listening again.
- CAPTUREDELIVERY-002: Given resumed voice before an endpoint leaves the FIFO, remove only that endpoint and retain every audio sample. Given resumed voice after provider half-close starts, cancel the candidate for automatic submission, preserve/hold its text, and resume recognition on the same microphone. Stop and declared limits remain visible terminal boundaries.
- CAPTUREDELIVERY-003: Given only low measured room noise during reply playback, the quiet prefix of a later clean utterance must not require manual review. Potentially audible overlap, unknown/malformed PCM, and playback still active at finalization remain conservative. The threshold uses existing bounded background energy with a low capped floor; it does not identify speakers or echoes. PCM delivery is unchanged.
- CAPTUREDELIVERY-004: Given an unexpected consumer or acknowledgement failure, release capture and expose only a closed stage enum and emitted chunk/sample counts. Never expose an exception string, transcript, audio, path, header, or token. Queue and declared duration limits retain their existing specific visible terminal paths.

## Verification boundary

### Browser timer receiver regression (1712 base)

Given browser-native timers with their required global receiver, the default continuous controller must call setTimeout and clearTimeout through that global. Injected test timers remain supported. Speech-to-quiet must request an endpoint without throwing or releasing the physical microphone, and endpoint settlement, renewed speech, Stop and reply-quiet cancellation must clear timers correctly. Tests must include browser receiver rules rather than only Node timers. On failure, recognized text remains recoverable in the visible previous-preview list, with a clear recovery notice; it is never silently submitted or discarded. No silence threshold or provider budget changes.

Behavioral RED preceded the corresponding repair: delayed-ready burst, pure-quiet overlap, and missing stage diagnostics. The source-worklet tests simulate browser primitives and timers; the >60-second capture cases use a synthetic sample clock. A separate composed fixture drives the compiled browser controller/transport into production ASGI and the Google adapter with a synthetic RPC. Neither proves an actual user's browser, microphone, acoustic environment, or Google service quality. The reported installed-version generic failure remains unattributed without matching version/diagnostic evidence. Full/release and real-device acceptance remain the integration owner's responsibility.
