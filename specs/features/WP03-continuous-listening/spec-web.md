# WP03 continuous-listening frontend requirements

Owner: web lane. Synthetic tests do not establish browser, microphone, acoustics or Google acceptance.

### WP03-009 Click-start, silence, and PTT compatibility
  - Given an explicit click on the continuous control, when permission is granted, then continuous capture starts under that user gesture, sends 16kHz silence frames, displays transient text and remains distinct from ordinary PTT/rehearsal behavior.
- **Client cases:** continuous WebSocket/token/audio-silence manual flow; preview remains unsent until explicit commit-ready.

### WP03-010 Explicit revision-bound manual send
  - Given the displayed preview has a new revision or a provider tail arrived after the last commit, when the user clicks send, then the client submits the exact `commit_ready` text once through the ordinary receipt-prefix controller barrier, retains late tails for the next explicit click and never retries an unknown request result.
  - Given the backend returns `stale_revision`, when the click caller receives it, then no automatic retry occurs; the current text remains visible and a new click is required.

### WP03-011 Local Stop, permission and callback fencing
  - Given permission is pending or capture is live, when permission is denied/lost, transport fails, Stop, Close or finite duration occurs, then local capture is released and late transcript/commit events are fenced. New reply/input turn generation leaves the continuous lease open until an explicit Stop.

### WP03-012 Readiness and bounded manual mode
  - Given a server ready frame, when the client parses it, then only declared finite limits and `manual_commit_required:true` are accepted. An unusable provider mode fails closed, the limit is displayed, the client sends one Stop and never rolls into another lease.

### WP03-013 Ordinary input, reply turns and typed fallback
  - Given a successful manual commit, when the frontend sends it through `SessionController.input()` using current activity/cutoff and the receipt-prefix barrier, then a reply turn does not tear down continuous capture. When a typed input is selected instead, capture is stopped first.

### WP03-014 Reply-only interruption while the lease survives
  - Given an explicit click to start continuous listening while MIRA has an active reply, when the click is accepted, then a synchronous local-only interruption fences the current reply before microphone capture begins; the global Stop path is not called and the new lease remains open.
  - Given a current stable transcript and a manual Send click while MIRA is replying, when commit approval is still pending, then playback is cut locally before the commit await; the exact text still waits for the server's one-use `commit_ready` confirmation.
  - Given a continuous lease is capturing, when fresh 16 kHz PCM stays above a bounded local RMS floor for the configured sample threshold, then the current reply is locally interrupted at most once until a bounded quiet interval rearms the detector. Interim/final ASR revisions never cause interruption, including late tails after a prior commit.
  - The detector measures energy, not speech. It may miss speech or react to environmental noise / speaker echo; device, acoustic and physical-latency behavior remain unverified. No onset creates a model request or auto-commits text.
  - Global Stop, Close, permission loss and capture failures still revoke the lease and release audio resources. A reply-only interruption never calls the global Stop hook.

## Wire

WebSocket `/api/v1/sessions/{session_id}/continuous-listening`; no query string. First JSON frame `{type:"start",session_token,lease_id}`. Later client frames are `{type:"audio",lease_id,sequence,first_sample,pcm_base64}`, `{type:"commit",lease_id,commit_id,revision}`, or `{type:"stop",lease_id,reason?}`. Server frames are `ready`, `transcript`, `endpoint_pending` (UI hint only), `commit_ready`, `commit_rejected` and terminal `stopped`.

`commit_id` is passed unchanged as `InputRequest.listening_utterance_id`; standard frontend input additionally supplies the current controller `activity_seq` and presentation cutoff. Tokens are sent only in the initial WebSocket frame after Origin/Host validation, never in a URL. Audio is headerless mono PCM16LE at 16 kHz; clients keep sending silence and prefer roughly 100 ms chunks.

## Provider offsets

Google V2 `speech_event_offset` is a duration offset from stream start marking event emission. `StreamingRecognitionResult.result_end_offset` is the end offset of one result, also relative to stream start. The adapter preserves per-result offsets and `SPEECH_ACTIVITY_BEGIN/END` event offsets, and uses integer sample conversion for installed SDK proto-plus `timedelta` values while checking field presence. Offsets need not be equal; endpoint hints require a final inside the same VAD interval with <=3s lag. The server never treats that hint as a final conversation boundary. `END_OF_SINGLE_UTTERANCE` and `voice_activity_timeout` are not used because they close the stream.

Primary sources: [Google V2 StreamingRecognize RPC](https://cloud.google.com/speech-to-text/v2/docs/reference/rpc/google.cloud.speech.v2) and [VAD events sample](https://docs.cloud.google.com/speech-to-text/docs/samples/speech-transcribe-streaming-voice-activity-events). Pinned installed SDK descriptor/object conversion was tested offline. Live/model VAD quality and real microphone/browser behavior remain unverified.

## Consumers/resources

- Consumer: frontend `SessionController.input()` after user commit; existing receipt-prefix barrier remains authoritative.
- Ports/service: `ContinuousSpeechRecognitionBackend`, `ContinuousListeningRegistry`, `ListeningLease`, one-use commit bindings.
- HTTP: separate WebSocket route and global Stop/delete/app-close lifecycle hooks.
- Ordinary PTT: unchanged `MediaOperation`/`open_microphone` validation.
- Tests: synthetic buffers, fake SDK-shaped messages and ASGI/WebSocket only; no live accounts, credentials or devices.


## Reply audio preparation within a send gesture

Status: offline software contract; no Safari, Edge, real microphone, acoustic or phone acceptance.
Base: immutable restored 0703 source (2026-10-05), before this isolated patch.
Owner: web lane (existing tests/web/*.test.mjs ownership). Consumers: page composition, session controller, continuous listening; existing playback sink only. No backend/protocol/config/provider/dependency changes.
Resources: shared locked TypeScript/Node and Python runtime, compiled main and real session/continuous/playback modules with injected browser primitives. Results stay outside the source tree. Integration owner runs the coherent affected/release checks.

## Requirements

### WP03-015 Gesture placement
Given a valid composer/preset send with an active continuous lease, or a manual stable-transcript send, when the user acts, the old reply is synchronously fenced and the existing playback sink receives its first resume request before waiting for lease teardown or server commit. Creating/preparing that context submits no PCM and opens no microphone. Starting continuous capture alone need not prepare playback.

### WP03-016 Lifetime and authority
Given teardown, commit or resume is pending, Stop, newer input, Close and pagehide fence the older continuation and playback. A late resume never restores an old source. Server-confirmed current input alone may obtain a new speech grant. Continuous Send preserves its independent lease; composer/preset send stops it.

### WP03-017 Failure and retry
Given denied playback or microphone access, retained text stays editable/recoverable, there is no automatic microphone start or retry, and an explicit retry may prepare the same playback owner. A stale commit retains the live lease and preview for an explicit next send. Ordinary Stop/error/Close ownership and one-use commit fences remain unchanged.

## Browser evidence boundary
Chrome's official autoplay guidance shows resume() in a click handler, but also allows resume after user interaction. The Web Audio 1.1 editor draft permits a sticky-activation condition and may leave a disallowed resume promise pending. These sources do not establish that each await loses audio permission, nor that this bug reproduces on Safari or Edge. The deterministic tests deliberately use a stricter first-activation model to verify our explicit synchronous-placement contract, not to emulate any named browser.

- https://developer.chrome.com/blog/autoplay/#web-audio
- https://webaudio.github.io/web-audio-api/#dom-audiocontext-resume

### WP03-018 A whole speech cue drains bounded PCM packets
Given one authorized speech cue with ordered 24 kHz PCM packets, a short first packet and delayed later packets do not mark underflow as completion. A validated transport complete frame seals the queue; playback reports completion only after every accepted packet naturally ends. Both the existing 96000-frame controller budget and the sink's actual packet/frame capacity must be respected. At capacity the transport callback waits for rendered progress, without dropping content, increasing the 50-packet bound, or starting a second playback owner. Stop, a newer input, Close, revocation and playback failure wake/cancel the waiter, and a late callback cannot render the old tail. An impossible packet fails instead of waiting forever. The synthetic tests use BrowserAudioTransport, SessionController and CancelSafePlayback together; PCM packets inside one whole speech cue are not JEV text chunks. This does not establish the cause of any user/device audio observation.

### WP03-019 Conservative playback ownership observation
Given a caller deciding whether another software action may proceed, replyPlaybackBusy is true before connection, after Close, while a speech run waits/fetches/plays/drains, or while review audition owns the single sink. It is false only when the connected controller has no speech run and the sink explicitly reports quiescent. It does not claim acoustic silence, identify speaker echo, or change dispatch authority.

### WP03-020 An endpoint hint preserves the observed preview
Given a transcript preview and endpoint hint share the same lease and revision, the hint changes only endpoint information. It cannot replace a richer interim suffix, lower known finality, or clear truncation to enable sending. Natural EOF retains that unchanged preview in previous previews, without submitting it. An endpoint hint is not a recognition replacement.
