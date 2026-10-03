# Backend voice runtime integration

This slice implements typed software-audio history and browser media transport. It is not live Google/device qualification, physical-hearing evidence, word alignment, reliable semantic-turn detection or approval to use credentials/paid inference. Existing generation/review defaults remain fixture-only; voice defaults remain absent. No provider adapter implementation was changed.

## Public transport

All paths begin `/api/v1`. Canonical models are in `entrypoints/http/schemas.py`; generated OpenAPI/TypeScript include the WebSocket and NDJSON models through the app's schema extension. Never hand-edit generated contracts.

- `GET /voice-capabilities`: actual configured generation mode (`mock`, `replay`, `injected`), `speech_enabled`, `microphone_enabled`, fixed 24-kHz output / 16-kHz input rates, and `qualification: injected_unverified|unavailable`. Presence is not proof of a successful live call. Legacy `/health.mode` continues to classify fixture replay as `mock` for compatibility; use capabilities for the exact mode.
- `POST /sessions/{id}/audio-progress`: ordinary session-token header; body `effect_id,digest,output_epoch,activity_seq,presentation_seq,sample_rate_hz,rendered_samples,status`. Status is `rendered|completed|interrupted|failed`. Map browser `stopped` to `interrupted`. Do not send `submitted` as rendered. Rendered/completed require positive rendered samples; interruption/failure may truthfully report zero. Facts represent completed software buffers only, never the uncertain device tail. Full exact identity, stable rate, monotonic samples and shared visual/audio sequence uniqueness are checked. Terminal facts are immutable, identical duplicates idempotent, history bounded to 4096.
- `POST /sessions/{id}/speech/{effect_id}/stream`: session-token header; body only `digest,output_epoch,activity_seq`. Text comes from the actor's exact current approved speech grant. Response is NDJSON `SpeechAudioFrame` packets (`type:audio`, full origin, `stream_id=effect_id`, `sequence` from one, `first_sample`, `sample_rate_hz:24000`, `pcm_base64`), at most 12,000 decoded bytes of mono PCM16 LE per packet. Completion is a separate `type:complete,total_samples` origin-bound trailer. Failure is `type:error,code` with the same origin and sanitized code. No automatic retry/replay of an already consumed grant.
- `WS /sessions/{id}/microphone`: allowed browser Origin is mandatory; all URL parameters are rejected. First message is `MicrophoneStart`: `type:start,session_token,stream_id:UUID,activity_seq,input_epoch,sample_rate_hz:16000`. Token is never in a URL, log or transcript. Server replies `ready,stream_id,activity_seq,input_epoch`. Then send `type:audio,sequence,first_sample,pcm_base64`, or `type:finish|cancel`. Audio sequence starts at one, samples at zero, offsets remain contiguous. Audio is ephemeral, not journaled or persisted.

Microphone controls and output:

- `finish` ends input and drains STT; it does not itself submit a turn. Socket cancel/close remains observed throughout final drain.
- `transcript,stream_id,revision,text,is_final` carries bounded cumulative revisions. Revision increases strictly; current session authority is rechecked for every output.
- `complete,stream_id,revision,text,had_final` carries usable text only when the last accepted revision is final and nonblank. Empty/interim-ending streams have `text:''`, `had_final:false`. Concrete Google STT additionally rejects an incomplete interim tail. Completion never creates a session input automatically.
- `error,code` is sanitized. There is no raw provider exception, token, audio, private header or upstream response body in errors.

Application JSON messages are at most 20,000 characters; each PCM frame is at most 12,000 decoded bytes. Microphone queue is eight frames, total duration at most 60 seconds, at most one second audio lead and 100 messages/sec plus a bounded initial burst. The CLI additionally configures 32-KiB WebSocket ingress frames/eight queued frames and disables access logging. A custom ASGI deployment must preserve equivalent ingress/logging controls. Per-operation output queue is four chunks; a session allows at most four still-terminating media operations, one uncancelled recognition stream and one uncancelled synthesis operation. Total recognition route lifetime is bounded to 75 seconds; media producer lifetime to 90 seconds.

## Required browser ordering

1. Close local presentation latch and stop the single audio sink synchronously.
2. Allocate any final partial audio fact before taking the global local presentation cutoff.
3. Increment activity and POST Stop; use its authoritative `activity_seq/input_epoch` for the WS start. Capture may begin in the user gesture while awaiting the bounded transport, but stale callbacks must remain fenced.
4. Stream receipt facts in order. Post-Stop facts at/below the old cutoff can add history only. They cannot revive the old phase or grant.
5. Current failed/interrupted facts independently revoke current grants and cancel generation/media; all terminal facts independently cancel the matching synthesis. If a terminal interruption arrives before Stop, the temporary server error state is safe and subsequent causal Stop wins.
6. Recheck exact origin and latest local activity at every final browser push/finish. The server also rechecks every packet, but does not substitute for local Stop.
7. Pace PCM ingestion below the sink's five-second capacity. Frontend integration reports a four-second high-water mark plus one bounded held packet; server backpressure alone does not imply device playout pacing.

GenerationContext.audio_progress retains explicit AudioProgress facts. Partial speech is absent from presented_effects; no word prefix is inferred from a sample ratio. Completed speech remains a software-render fact, not proof of hearing or understanding. The actor remains the sole state writer; the media helper only owns bounded queues and cancellation.

## Explicit app composition

Use `create_app(settings, providers=approved_generation_and_review, voice_factory=make_voice)` for real async SDK clients. `make_voice` runs on the application lifespan event loop and calls `create_google_voice(settings.services.speech, credentials=approved_credentials, token_provider=approved_async_token_source, authorized=True, http_client=optional_approved_client)`.

The factory's admission flag is an integration guard, not a substitute for user/organization approval of capability, data, destination and spend. It requires explicit project/voice and an already-authorized credential/token source; it never discovers ADC, reads credentials/environment, changes cloud services/IAM/proxy/DNS or falls back to another model. Quota project is optional and only passed if configured; no billing target is invented. STT uses its configured V2 location/model/language; TTS remains exact `gemini-3.8-flash-tts` in global.

Default HTTP client verifies TLS, uses `trust_env=False` and disables redirects. An explicitly injected client can carry an already-approved proxy/CA route and remains caller-owned. The bundle closes its own default HTTP client and STT transport once. The app closes sessions/operations before the bundle. Raw explicit `speech_synthesis`, `speech_recognition` and optional `media_shutdown` injection remain available for synthetic providers; they cannot be combined with voice_factory. Factory construction outside a running event loop fails early to avoid cross-loop gRPC resources.

## Known qualification limits

No live account/authentication, real inference, microphone permission, speech intelligibility, hardware acoustic tail, word/subtitle alignment, mobile browser, phone/network-latency or original product acceptance case was executed. Stop revokes local/server authority independently; cleanup cannot guarantee that a remote provider has ceased charging/computing. Deliberately cancellation-resistant test providers are bounded and suppressed until termination; no claim is made that arbitrary hostile in-process code can be forcibly killed.
