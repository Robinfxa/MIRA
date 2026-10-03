# OBS-04 design

This slice adds one isolated adapter around the already-existing `Diagnostics.capture` API. It
does not modify the diagnostics event schema, recorder, app runtime, frontend, HTTP, or bootstrap.

The coordinator owns one `bytearray` at a time, enforces PCM frame alignment, a 512 KiB maximum,
and a short hard expiry. Expiry has both an explicit timer cleanup and lazy checks at every public
operation. When discarded, bytes are overwritten before clearing; outstanding read-only views see
zeroed/empty content and cannot authorize a later write.

The human-facing review request gives a read-only view of the exact staged bytes, their SHA-256,
the sample rate, and the session/turn/stream identity. A unique one-use ticket binds that content to
the current coordinator generation and stage. `confirm_save` requires the ticket, matching digest,
an explicit APPROVED attestation, and a separate `persist_consent=True`. Every valid-ticket submit is
consumed once whether it succeeds or is denied. No transcript or regular-expression result counts as
approval. No automatic spoken-secret detection or audio redaction is claimed.

The only persistence operation is existing `capture(ReviewedRecording(kind=AUDIO_INPUT, ...))`.
That sink revalidates known credential material and unsafe envelopes, enforces its queue/storage
limits, writes only to its isolated private raw store, and keeps its existing export confirmation
independent. `capture()` returning true means bounded queue acceptance, not disk durability.

Future runtime integration must visibly opt into recording, pass the current session/turn/stream
identity and real PCM chunks to this module, show/play the exact review buffer through the existing
approved path, and bind Stop/new-input/mode-off/close to invalidation. No second playback authority
is introduced here.
