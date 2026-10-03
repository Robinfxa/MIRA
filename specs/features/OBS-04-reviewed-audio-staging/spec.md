# OBS-04 — Bounded reviewed-audio staging and local persistence

Status: bounded staging adapter and authenticated explicit review UI are source-integrated; all
functional tests use synthetic PCM. No live microphone, browser, provider, or device verification.
Owners: diagnostics audio-review worker (`mira.adapters.diagnostics.audio_review`) for staging and
HTTP route/contracts; director-assigned frontend owner for the review panel, API client and shared
playback audition hook.
Baseline: uncommitted shared source snapshot inspected 2026-10-03; OBS-01 `capture(ReviewedRecording)`
is the persistence boundary and remains the only raw-file sink.
Test blocks: providers for `tests/contracts/test_diagnostics_audio_review.py`; web for the existing
`tests/web/*.test.mjs` lane, including `reviewed-audio.test.mjs`,
`controller-reviewed-audio.test.mjs`, and `transport-reviewed-audio.test.mjs`.
Consumers: same-session capability client, SessionController, the single CancelSafePlayback owner,
and the local review panel. Resources: standard library, existing pytest/Node/TypeScript tools,
synthetic PCM bytes and private temporary directories only. No actual microphone, provider, `.env`,
credential, account, or device use.

## Observable requirements

### OBS04-001 — Recording opt-in is visible and revocable
Given recording is disabled by default, when a caller explicitly opts into development recording
with consent, then the existing local diagnostics sink is enabled and status clearly says raw audio
may be staged/reviewed for local persistence. The browser exposes this option only for an explicitly
injected development voice mode; mock/replay/rehearsal continue to keep microphone and recording off.
The authenticated status identifies that opt-in applies to the local application scope. Without a
separate checked consent, recording remains disabled. Turning the mode off, closing the review
coordinator, or starting newer input invalidates outstanding review tickets and wipes the pending
transient buffer. The module does not start capture itself.

### OBS04-002 — Transient PCM staging is strictly bounded
Given an active explicit development-recording mode, when a caller stages PCM16LE chunks, then only
one bounded buffer (at most 512 KiB by default) is held in memory and it expires no later than the
configured short TTL. Invalid, empty, over-budget, odd-length, stale, or canceled input fails closed
with a clear status and buffer cleanup. Nothing is written to disk before review and save confirmation.

### OBS04-003 — Review ticket binds the exact original buffer and owner
Given completed staged audio, when review is requested, then the reviewer receives a read-only view
of that exact buffer and its SHA-256 digest, sample rate, and owner tuple (session, turn, stream).
Confirmation must echo the exact digest and is bound internally to the stage token, coordinator
recording generation, owner, expiry, and one-use review ticket. Any mutation, mismatch, stale ticket,
newer input, mode-off, close, or repeated submit cannot reuse approval. Only an explicit human
attestation for the exact buffer may enter the save path. The UI displays kind, byte count, sample rate,
duration and digest, then requires an explicit, user-started playback through the existing single
audio owner. Playback is blocked while normal generation, microphone capture, scene preparation or
character playback is active. Lifecycle admission allows the exact fresh-session state (`idle`,
unsealed, no request or grants/history, and zero revisions/epochs), an empty post-Stop state
(`stopped`, unsealed, no request or current grants), or a completed response (`idle`, sealed, with a
request identity and every current grant fully represented in `presented_effects`). The backend
retains presented grants in `active_grants`, so their presence alone does not mean work is pending;
speech appears in presented history only after completed audio progress. Generation/intermediate,
error, unpresented, or inconsistent lifecycle states fail closed. The audition emits no character
audio-progress fact, caption, history entry or JEV permission. The operator must review the actual
clip, not just an ASR transcript; the module performs no spoken-secret or semantic detection and does
not transform/redact audio.

### OBS04-004 — Private save needs separate per-buffer confirmation
Given the exact-buffer review is still valid, when the operator explicitly confirms private local
persistence for an approved-safe original, then the module calls the existing diagnostics capture
port with one `AUDIO_INPUT` `ReviewedRecording`. The sink rechecks known-secret bytes and unsafe
envelopes and enforces its existing queue, raw-file and retention budgets. A capture result means
accepted into the bounded local queue, not durable disk success. Missing consent, rejected/uncertain
review, known credential bytes, sink refusal, or storage error is reported as a concrete failure.

### OBS04-005 — Raw audio stays isolated from ordinary export
Given audio is accepted by the existing diagnostics sink, then the record is routed only through its
private raw store. The audio-review module exposes no event-emission, export, network, Git, or generic
logging operation. Existing raw-export consent remains a separate action; recording opt-in and
per-buffer persistence confirmation do not authorize export or sharing.

## Integration contract and limits

Use only after the application visibly enables recording through the new coordinator. The runtime
owner must supply identity values from the active session/turn/audio stream, bounded captured chunks,
and a human review surface for the exact provided PCM. Route Stop, new input, mode-off and close to
the coordinator's invalidation methods. Never directly call `Diagnostics.capture` for runtime audio.
The caller should report `queued_private_local` as queue acceptance only, then use diagnostics status
to observe later writes/failures. The frontend explicitly reports queue acceptance as not proof of a
durable disk write; ordinary raw export remains a separate permission. Its temporary exact-buffer
copy, digest, actions and shared-sink audition are synchronously cleared on mode-off, expiry,
ownership change, new input, Stop and close. The close-session flow does not silently toggle the
application-wide recording mode, and clearly warns if that mode is still active. Current recorder
schema supports mono signed PCM16LE at 16/24/48 kHz, but does not encode channel count or codec metadata.

The source-level Node/TypeScript tests exercise consent, pending/review/confirm, digest mismatch,
stale response, expiry, cancellation, session capability use and audio-owner teardown. They do not
prove that the real browser rendered the UI, that a physical microphone was used, that a person heard
or understood a clip, or that a raw buffer was durably written. No browser/device verification was run.
