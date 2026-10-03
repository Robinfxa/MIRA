# OBS-04 handoff

## Original adapter slice

- Isolated `mira.adapters.diagnostics.audio_review` coordinator for explicit mode, bounded transient
  PCM staging, exact-buffer review tickets, one-use confirmation, cancellation and cleanup.
- One unique providers-lane contract test file and OBS-04 requirement traceability.
- Contracted persistence through the existing `Diagnostics.capture(ReviewedRecording)` API only.

## Runtime/UI integration (source-complete; device acceptance pending)

The coordinator is now wired through authenticated `/reviewed-audio` session routes and generated
DTOs. The frontend exposes an explicit application-scope recording opt-in/off control, an exact
digest/kind/rate/size/duration review ticket, explicit load and manual audition, and a separate
per-buffer private-save confirmation. The shared `CancelSafePlayback` path remains the sole output
owner; raw audition is blocked while generation, capture, scene preparation or normal playback is
active, and it creates no playback fact, caption, history entry or JEV approval.

The completed ASR transcript carries `source_audio_stream_id` only after the owner-scoped status says
that the exact stream has a final server-bound transcript. A mismatched or unavailable raw stage
does not block the ordinary valid transcript. Only an exact HTTP 409 `history_pending` input response
is restored as known-not-sent; arbitrary conflicts and transport/server failures remain unknown.

See [OBS-04 spec](../../specs/features/OBS-04-reviewed-audio-staging/spec.md) and
[verification](verification.md). The final exact web lane and frontend RED/GREEN sensitivity receipts
are listed there.

## Core adapter integration contract

See [OBS-04 spec](../../specs/features/OBS-04-reviewed-audio-staging/spec.md) and
[design](design.md). To integrate, the director may construct `ReviewedAudioCapture` around the
already-injected diagnostics sink. The UI/controller must explicitly call `set_recording(True,
consent=True)`, show the returned/status notice while active, stage bounded PCM, obtain exact-buffer
review, then call `confirm_save(ticket, reviewed_digest=..., review=ContentReview.APPROVED,
persist_consent=True)` only after the operator has reviewed and chosen private local save. New input,
Stop, mode-off and close invalidate pending bytes/tickets. Never infer spoken-secret safety from
the transcript; never route raw audio to ordinary events or exports.

`queued_private_local` means the existing diagnostics sink accepted the item into its bounded local
queue. `written_recordings`, `dropped_recordings`, and `io_failures` determine later writer outcome.
Raw export remains separately consented and is not authorized by this feature.

## Not included / not verified

No live PCM, credentials, browser session, provider call, microphone, speaker or device was used. No
spoken-secret detection is claimed. Synthetic tests prove source behavior only, not what a person
hears or whether the real device path works. `queued_private_local` is queue acceptance only, not
proof of durable disk write. The coordinator does not retain audio outside its bounded pending stage
and existing private raw store, or offer export. Raw export still requires separate consent. No
publication, push, deployment or independent human/device acceptance was performed by this slice.
