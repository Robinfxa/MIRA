# Frontend voice integration handoff

The composition root now uses one `SessionController`, one `PresentationGate`, one `SceneEffectExecutor`, one `CancelSafePlayback` and one `MicrophoneCapture`. No provider/browser speech-synthesis fallback exists. Browser resources are created only by explicit input/PTT gestures; tests do not operate actual devices.

## Stable endpoints and wire

- `GET /api/v1/voice-capabilities`: generated `VoiceCapabilities`, including actual `generation_mode` (`mock`, `replay`, or custom `injected`), speech/microphone enable flags, fixed 24k/16k rates and `injected_unverified`/`unavailable` qualification. UI labels do not infer live acceptance from animation or capability presence.
- `POST /sessions/{sid}/speech/{effect_id}/stream` under `/api/v1`, session token only in `X-Mira-Session-Token`, JSON `{digest,output_epoch,activity_seq}`. The frontend sends no duplicate text. NDJSON `audio` frames require exact effect/digest/activity/output/stream origin, sequence starting at1, contiguous `first_sample`, sample rate24000, canonical base64, nonempty even raw PCM16LE ≤12000 decoded bytes. WAV containers are rejected. `complete` must match total received samples and be the terminal line; EOF without complete, trailing packets, mismatches and malformed JSON fail closed. Provider error payload content is not reflected in user-visible errors.
- `WS /api/v1/sessions/{sid}/microphone`: no URL query auth; first JSON is generated `MicrophoneStart` with token, UUID stream, the server Stop acknowledgement's activity/input epoch and rate16000. Browser supplies Origin. `ready` echoes identity; PCM uses1-based sequence, contiguous `first_sample` and base64. `finish` follows queued PCM drain; `cancel` or close cancels. Only `complete {stream_id,revision,text,had_final}` after finish may become a new input. Interim packets cannot create turns.
- `POST /sessions/{sid}/audio-progress`: generated `AudioProgressRequest`. Shared presentation sequence, immutable speech identity, sample_rate_hz24000, naturally rendered sample count and `rendered`/`completed`/`interrupted`/`failed`. `submitted` is not sent as rendered. Explicit speech is never posted to `/receipts`.

## Sequencing and lifecycle

1. New text/PTT/Stop/error closes the local latch and stops physical Web Audio first. Sink terminal callbacks allocate their fact sequence synchronously. Only then does `beginInput`/`stop` capture the presentation cutoff and initiate network work.
2. Current authorization is independent of one-shot claiming. Claiming prevents replay, but an admitted running stream remains authorized until its exact current grant is revoked or local activity/latch changes.
3. Facts are serialized so an audio terminal cannot overtake earlier rendered counters. New activity does not cancel already-established facts; server fences admit valid late history. Failed delivery of old history warns about incompleteness without stopping a newer speech stream.
4. All async input, stream, microphone, poll and unlock continuations are guarded by local generation/closed state. Stop/revoke invalidates handles and wakes blocked PCM feeds. Late requests, packets, source callbacks, capture readiness and final transcripts cannot revive old output or submit an old turn.
5. PTT capture starts in the original user gesture, while server Stop acknowledgement is pending. Its bounded startup queue is flushed only through the authenticated transport. Releasing PTT stops capture immediately, discards only the runtime's partial worklet tail, then drains accepted PCM and waits for final recognition. Empty, interim-only, punctuation-only and explicit `[noise]`/`[silence]`-style results create no turn.
6. Close permanently disables the controller, cancels timers/poll/fetch/socket and closes the sole sink/capture. A create response arriving after close is deleted best-effort; failed deletion is not called confirmed server cleanup. A stale microphone AudioContext-close rejection is ignored after a newer capture starts, while current cleanup warnings remain available from the runtime.

## Bounds and backpressure

- Speech: one NDJSON read/PCM callback at a time; maximum line20k characters, read chunk256KiB, packet6000 samples, total300s of24k samples, request deadline330s. Controller waits when accepted minus naturally rendered samples would exceed96000 (4s), below sink's120000-frame (5s) hard bound. Stop/cancel wakes the wait. Backend has its own smaller lifetime bound; client limits do not extend server permission or duration.
- Microphone: frontend startup ≤100 copied chunks and64KiB PCM; transport queue ≤100 packets and64KiB encoded JSON. Maximum input60s. Auth deadline10s, connection lifetime90s, final-transcript deadline15s after sending finish. All timers are released on completion/error/cancel/close.
- Microphone send pacing is measured from monotonic WS-ready/send time, not old capture timestamps. It allows at most120ms sample lead and one packet per packet-duration, with no new PCM send while browser bufferedAmount is nonzero. A delayed startup therefore cannot burst its entire backlog into the backend's8-frame queue. Finish waits for the paced queue and browser buffer to drain.
- Provider consumption or network stalls can still exceed bounded queues and produce an explicit error. No samples are silently dropped to continue the tail. An acknowledged server credit window would be a stronger later live-network refinement; it is not claimed here.

## Scene and input controls

Scene listening/speaking follows actual capture/playback callbacks. Ready/idle snapshots do not override active audio. Existing stop/prepareInput preserves already shown photo/environment/actions. PTT supports pointer, keyboard and assistive click start/finish; loss of capture/focus cancels. Empty form submission cannot orphan a held microphone. Text remains available after audio/recognition failures.

## Qualification and remaining work

Final stable-source scoped run:108 Node tests plus strict TypeScript compile. This is software integration with synthetic transports and injected browser primitives. No actual permission grant, speaker/microphone, acoustic cutoff tail, word-aligned subtitle, mobile/Safari/browser rendering, live Google/LLM/review request, credentials, paid API, loopback bypass, deployment or remote CI run occurred. Full/affected/release and original164 product acceptance cases remain the integration director's responsibility.

`main.ts` and related frontend files are released to the integration director after this handoff. Subsequent OBS-01 recording-banner work is a separate change and must obtain real backend status; static public TypeScript configuration fields alone do not prove recording state.
