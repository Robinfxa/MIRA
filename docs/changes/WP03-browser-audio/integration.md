# Browser audio integration contract

Import the public APIs from `features/audio/index.js`. Instantiate exactly one `CancelSafePlayback` for role voice. This slice does not edit or take ownership of session/gate/controller/provider logic.

## Playback

`new CancelSafePlayback({isAuthorized, onFact, onError})`

- `unlock(): Promise<boolean>` resumes Web Audio. Call directly from a user gesture (the text-send or microphone-start gesture is suitable). Browser autoplay policy can reject or defer resume; no synthetic voice replacement occurs.
- `open(origin): PlaybackStream | null` admits a fresh effect. `origin` has the existing effect field names `id`, `digest`, `activity_seq`, `output_epoch`. Origin identity is copied/frozen. A second authorized origin takes over and stops the previous one. Reopening the active identical origin is rejected.
- `stream.push(pcm16: Int16Array): boolean` accepts copied, raw signed PCM16 mono **24,000 Hz**. The transport must validate the actual provider format and decode little-endian bytes correctly; WAV headers, encoded audio, different rates and stereo must not be fed as PCM. The handle is generation-bound: after stop, its future writes/finish return false.
- `stream.finish(): boolean` seals the input; natural drain then emits `completed`. Empty, invalid and overfull streams fail explicitly. Temporary queue underflow never means completion. Do not create a new stream handle per packet.
- `stop('stop' | 'new-input' | 'revoked' | 'error' | 'close')` disconnects/stops the active Web Audio source and clears queued frames synchronously. Repeated calls are safe. Device/hardware buffered acoustic tail is not measured or promised to disappear instantaneously.
- `reconcileAuthorization()` must be called immediately after installing a new grant snapshot, including empty grants. A 20-ms timer is defense-in-depth, not a hard real-time revocation guarantee. Browser timers can be delayed/throttled.
- `close(): Promise<void>` stops first, then closes the AudioContext and permanently rejects new streams. A pending resume cannot restart it.

Default bounds: 24,000 frames/chunk (1 s), 120,000 buffered frames including active source (5 s), 50 queued/active chunks. Overflow stops the whole stream; it never skips a missing qualifying part and continues its tail. Configurable bounds have hard maxima.

### Gate/controller work required from the integration owner

1. Add a current-authorization query that matches the active exact immutable grant and local activity/latch **without consulting the consumed-ID set**. `gate.allows` currently becomes false after `consume`, so it cannot be the continuing authorization callback.
2. Continue one-shot consumption separately. Opening audio is asynchronous; legacy `ReceiptRequest` documents synchronous DOM application only. Do not send it as if it proves rendered/played speech.
3. On reliable input or microphone takeover: close the old presentation latch, call sink.stop('new-input') before any request/permission wait, then start the new input path.
4. On explicit stop: local latch first, sink.stop immediately, then network stop.
5. On any transport/presentation failure, invalid snapshot, server revocation, session close or reconnect: stop/reconcile locally before awaiting network cleanup. Every path must suppress old provider/chunk/completion callbacks.
6. Cancel the old TTS request upstream too, but do not confuse upstream cancellation with local output suppression. Late packets still target their invalidated old handle.
7. Do not reopen a consumed/completed origin. If the sink fails, use an explicit causal retry with current authority; do not silently replay stale speech.

### Facts are not acoustic or text-alignment evidence

`PlaybackFact.stage` is `submitted`, `rendered`, `completed`, `stopped` or `failed`.

- `submittedFrames`: frames on which Web Audio source.start returned successfully.
- `renderedFrames`: full buffers whose natural `onended` callback was accepted while current authorization still held. This is software completion, not a speaker/microphone measurement.
- `inFlightFramesUncertain`: submitted minus fully naturally-ended frames. Stop does not turn that unknown tail into an exact audible prefix.
- `completed`: explicitly finished stream drained normally. It does not prove the user heard/understood content, supply word timing, or turn the entire text into heard history.
- Stops and failures preserve previously established counters and never emit a late completed fact. If revocation makes the callback stale, no new rendered/completed fact is recorded.

One source is submitted at a time, with the next source started from the previous end callback. This favors simple final-sink revalidation and cancellation; main-thread scheduling can create small packet gaps. Gapless playout and real-device latency remain unqualified.

## Microphone

`new MicrophoneCapture({onChunk, onState, onError})`

- Constructing it has no browser side effects. `start(): Promise<boolean>` must be called from an explicit user action. It checks AudioWorklet support before requesting microphone permission, then obtains audio-only media.
- `onChunk(chunk)` receives bounded `pcm16le: Uint8Array`, `sampleRate: 16000`, `channels: 1`, sequential `sequence`, target-rate `[startSample, endSample)`, actual `captureSampleRate`, optional device-reported `sourceSampleRate`, and AudioContext `captureStartFrame`.
- The normalizer is a stateful weighted box-filter resampler. It handles 44.1/48-kHz input without timestamp drift, but high-order anti-aliasing/ASR quality and microphone hardware are not validated here.
- `onChunk` may return a promise. Resolve it when the downstream transport accepts the chunk into its own **bounded** buffer. Do not resolve immediately while appending to an unbounded external queue. Default chunks are 20 ms with 8 outstanding bridge credits. The worklet and main-thread consumer both enforce bounds and stop on overflow.
- The worklet is `/assets/audio/capture-worklet.js`, matching the existing `/assets` public mount. It emits mono samples and writes zero to every output channel, so there is no local microphone-to-speaker monitoring. No ScriptProcessor fallback is added.
- `stop()` immediately releases held tracks/nodes/port, starts context closure and invalidates callbacks. It is cancellation semantics: it discards partial worklet/resampler tails and does not await/flush pending delivery. Do not interpret it as a server STT finish/drain acknowledgement. The transport owns explicit STT input-end semantics.
- `close()` permanently disables capture and awaits already-held context closures. A permission dialog can remain unresolved; close does not wait indefinitely, and late granted tracks are immediately stopped.
- Permission denial, unsupported APIs, unexpected track end, malformed/discontinuous samples, processor/transport errors and overflow emit typed sanitized errors. Keep text input available in the UI. These callbacks do not send/submit any transcript.

Test seams are the actual browser primitive constructors/functions (`createContext`, `getUserMedia`, `createWorkletNode`, interval functions), not a fake renderer masquerading as an audio implementation.

## Scope and qualification

No provider is selected or invoked, no permission prompt is accepted automatically, no browser speech synthesis exists, and no shared wire/receipt/controller file is changed. Exact Google model capability belongs to the separate provider worker. All tests use synthetic PCM and injected primitives or a VM-hosted worklet; microphone/speaker/browser/device/live-provider qualification is **not run**. The known browser loopback restriction was respected.

Primary API contracts consulted 2026-10-03: [Web Audio](https://www.w3.org/TR/webaudio/) and [Media Capture and Streams](https://www.w3.org/TR/mediacapture-streams/). These references do not establish device/browser behavior in this environment.
