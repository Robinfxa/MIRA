# Natural endpoint candidate

## Behavior and evidence boundary

An explicit natural-mode start enables automatic eligibility on capable Google
continuous streams. Legacy starts still use manual mode. A final recognition
portion is not by itself a sentence boundary. This implementation requires a
closed latest VAD activity, complete provider batch, no outstanding interim, and
unambiguous contiguous final coverage reaching its END within received audio.
The client may then commit that exact lease/utterance/revision snapshot through
the existing one-use input binding and normal Actor input path. Manual Send remains
available when evidence is insufficient. No timer or punctuation proves closure.

Primary Google references inspected on 2026-10-05:
- [Streaming RPC and result semantics](https://docs.cloud.google.com/speech-to-text/docs/reference/rpc/google.cloud.speech.v2)
- [Voice activity events](https://docs.cloud.google.com/speech-to-text/docs/voice-activity-events)
- [Result offsets and finality](https://docs.cloud.google.com/speech-to-text/docs/reference/rest/v2/StreamingRecognitionResult)

Google specifies finals for consecutive audio portions and VAD events that often
precede recognition. Its event-emission and result-end offsets need not align.
Thus this is a conservative supported automatic branch, not a guarantee every
real utterance will qualify. Missing/misaligned/ambiguous evidence remains manual.
Provider models, credentials, requests, budgets and one-stream lifecycle do not change.

The SDK bridge validates complete response structure, carries batch completion
and pending-interim flags, and concatenates consecutive interim portions. A
malformed multiple-final or final-after-interim SDK response fails before partial
eligibility escapes. Generic application events can carry multiple batch portions,
but only the last may make the endpoint eligible.

## Late text and submission facts

A late final for a snapshotted natural activity yields a review-needed correction
with the same utterance UUID and commit UUID. It does not become the next turn.
Pending/reserved authority is revoked; accepted history remains factual and exact
accepted retries remain valid. The reserved state records an in-flight boundary:
validation and Actor.submit are not atomic, and a later successful Actor submission
cannot be described as undone. Corrections are not automatically submitted.

Current provisional text and old-utterance corrections are retained independently
across EOF/error, with bounded per-entity deduplication. Explicit cancellation
fences all retained terminal forms. The frontend must display corrections by
utterance identity rather than replace a newer current preview.

## Tasks and verification

- [x] WP03-010/011 requirements and collected test mappings.
- [x] Directed natural RED: five missing-eligibility failures and five safe fallback
  controls; same ten cases GREEN after implementation.
- [x] SDK batch RED: three failures; same three cases GREEN after repair.
- [x] Focused final regression: 89 cases passed across continuous unit/HTTP,
  production Google SDK contracts, diagnostics and startup buffers.
- [x] Actual local ASGI plus production Google adapter and injected SDK client:
  two natural commits accepted as two Actor inputs; late first-utterance amendment
  retains its identity and does not create a third turn; one synthetic RPC only.
- [ ] Independent combined backend/compiled-client audit and merged affected/full
  acceptance are integration-owner checks, not claimed here.

Append-only evidence folder: `mira-continuous-natural-evidence-20261005T1254Z`, runs
`001-natural-red`, `002-natural-green`, `003-sdk-batch-red`, `004-sdk-batch-green`,
`005-natural-asgi-and-regression` (one expected older flag assertion then updated),
`006-natural-asgi-and-regression-green` and `007-natural-directed-final`.
These are local synthetic software checks, not live Google, real microphone,
physical audible interruption, or user-device acceptance.

## Handoff

Shared schemas and continuous ports have one backend writer by director approval.
Generated TypeScript/OpenAPI come only from `tools/export_contracts.py`.
New wire types are `utterance_ready` and `utterance_revision`; natural commits add
`utterance_id`, separate from the existing client commit/input-binding ID.
The frontend owner receives the generated contract and owns actual automatic
submission, gesture/audio preparation, playback guarding and correction display.
