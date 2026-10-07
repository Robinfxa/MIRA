# WP03 — Google voice provider adapters

Status: offline implementation and scoped verification complete; no live entitlement or audio claim.

Scope: Google Speech-to-Text V2 and the exact user-selected `gemini-3.8-flash-tts`.
Consumer: existing `SpeechRecognitionBackend` / `SpeechSynthesisBackend` media ports.
Owner lane: `providers`, already covering `tests/contracts/test_*.py`. Downstream integration
requires `config`, `actor`, `http`, `architecture`, and frontend playback verification.
Baseline: imported foundation 0.4.1 in the 2026-10-03 24-hour project, no git commit assumed.
Resources: google-cloud-speech 2.40.0, google-auth 2.59.1 and httpx 0.28.1 were installed and
pinned by the composition owner. SDK/client construction remains explicit. One pytest process, offline.

## Boundaries

No environment access, ADC discovery, login, project mutation, billing enablement, live request,
fixture approval of arbitrary output, model fallback, second player, or shared schema change.
Transports are injected and carry explicit timeout and cancellation contracts. Caller owns global
output epoch and playback permits. Generator cancellation is not proof of audible device stop.

### WP03GOOGLE-001 — Exact TTS request
Given approved text and an explicit prebuilt voice, when synthesis starts, then the request goes
only to `aiplatform.googleapis.com`, `global`, `gemini-3.8-flash-tts:streamGenerateContent`, with
verbatim text, the new `voiceConfig.voice` shape, optional `speechMetadata.style`, and AUDIO_L16.
Old models, non-global locations and unsupported voices fail without opening a transport.

### WP03GOOGLE-002 — Honest PCM output
Given valid audio/l16 base64 SSE chunks, when consumed, then emit contiguous mono signed
little-endian 16-bit 24-kHz AudioPackets. Metadata does not become audio. Malformed base64,
odd PCM samples, unexpected formats, safety blocks, size limits, empty audio or missing STOP
fail explicitly; a partially emitted stream never becomes a successful completion.

### WP03GOOGLE-003 — STT V2 request and input contract
Given contiguous mono PCM16 packets, when transcription starts, then send a full explicit
configuration first and only audio thereafter over injected gRPC; chunk audio below 15,000
bytes (the strictest current official field limit). Enforce one input stream, fixed rate,
contiguous samples, bounded duration, and no request for empty input.

### WP03GOOGLE-004 — Transcript semantics
Given STT interim and final segments, when responses arrive, then emit monotone revisions of
cumulative transcript preserving finalized segments. ASR final is never semantic turn completion.
No-result silence is valid, but malformed responses, unfinished interim tails and explicit provider
failures are not silence.

### WP03GOOGLE-005 — Cancellation and cleanup
Given pending or partially consumed audio/transcript streams, when the consumer cancels or
closes, then propagate cancellation and close/cancel the upstream RPC/HTTP stream. No hidden
retry, fallback, or late packet can revive the cancelled generator. Caller must close early exits.

### WP03GOOGLE-006 — Safe errors and auth isolation
Given auth, quota, timeout, HTTP/gRPC or unknown failures, then return bounded typed reason codes
without credentials, response bodies, raw exception text, text/audio logging or fallback content.
Constructing/importing these adapters never discovers credentials or connects a network.

## Deferred acceptance

Composition wiring, enabled APIs, preview terms, IAM, quota, approved bounded spend, runtime
ADC/token refresh, actual model entitlement, Chinese intelligibility, acoustic latency, microphone
capture, browser playback, device Stop tail and 3–5-minute end-to-end session remain separate
checks. Offline green is not `live_ready`.

### Diagnostic-only TTS timing

Given a future approved-final diagnostic TTS run, when observable stream and private artifact-write
boundaries are reached, then the report uses monotonic elapsed milliseconds for dispatch, HTTP
headers, first and last valid PCM, stream terminal, and artifact-write completion. Invalid PCM does
not start the first-valid-PCM clock. `total_samples` is the sum across valid PCM packets; a full
drain completion does not label that value `first_packet_samples`. Stream terminal and artifact-write
outcome remain separate. Cancellation after PCM is reported as cancellation, not a normal full
drain. Missing headers, PCM, save, authentication, browser scheduling, or physical-playback
observations remain null or `unobserved`; no value is inferred from adjacent events. The existing
approved-final receipt is preserved unchanged.

Offline verification uses fake clocks and fake streams only. Coverage includes non-audio before
audio, multiple PCM packets, invalid initial PCM, timeout before and after PCM, cancellation, a
completed empty stream, successful timing through artifact save, and a failed artifact write. These
tests do not make a provider request or establish a new real-world timing measurement. The earlier
approved-final receipt reported 14.7693 seconds from dispatch to headers and 16.0560 seconds from
dispatch to `tts_completed` after artifact writing; it has no separate first-valid-PCM or
artifact-write timestamp.
