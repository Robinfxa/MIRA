# WP03 speech network chunk equivalence

Owner: web. Baseline: frozen mira-response-contract-final-20261006T0522Z.
Write surface: apps/web/src/features/session/audio-transport.ts only. Consumers:
SessionController and its sole CancelSafePlayback sink. Tests use the existing
locked Node/TypeScript toolchain, nonzero synthetic PCM, and fake browser device
callbacks. No credentials, providers, installations, microphone, real user PCM,
account calls or budget increases. The existing tests/quality.toml web wildcard
uniquely owns the new .test.mjs files. This is not physical-device acceptance.

### WP03SPEECHNETWORKCHUNKS-001

Given a valid bounded speech NDJSON stream, arbitrary browser read segmentation
or coalescing must produce identical ordered PCM and verified completion. Decode
incrementally in windows no larger than 16 KiB; keep each line at most 20,000
characters, each raw PCM at most 12,000 bytes, total PCM at most 7,200,000 samples,
and the existing 330-second transport timeout. No new aggregate wire-byte limit is introduced.
The backend's explicitly selected local TTS duration and request budget remain
unchanged, including a selected 30-second cap. The removed 256 KiB limit was a
per-read assumption, never a provider usage limit.

### WP03SPEECHNETWORKCHUNKS-002

Given three cues or an underflow followed by delayed PCM, a network completion
only seals the current cue. Every queued source must naturally end before the
full completion fact or next cue. A first rendered prefix is never a full speech
receipt. Tests use actual compiled transport, controller and playback classes.

### WP03SPEECHNETWORKCHUNKS-003

Given split UTF-8, an oversized line, invalid/extra terminal data, an exceeded
sample budget, cancellation or an invalid late packet, decode safely or fail
explicitly with bounded state. Preserve rendered prefix facts and text. Stop and
new input release blocked backpressure without playing an old tail. A later
valid voice/text turn must remain usable after transport failure.
