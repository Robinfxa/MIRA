# Continuous listening terminal preview retention

## Scope and implementation

This narrow change starts from the immutable 0703 restored source. The Google SDK
transport may produce final pieces and then EOF or failure before the WebSocket
writer runs. Previously `ListeningLease.stop()` cleared those queued previews, so
only `stopped` arrived. The recognition consumer now retains one last validated
transcript event at provider EOF/failure; the HTTP writer sends that existing
revision/finality once before `stopped`, if not already sent. It does not drain
more audio, wait for another final, retry recognition, renew the lease, or commit
text. Explicit cancellation clears this snapshot even after EOF. A completed
Stop/disconnect control takes precedence over a simultaneous terminal event.

A repeated final with the same offset and text is ignored before changing the
revision or interim suffix. A first late final is retained, and identical words
at a later offset remain new text. Missing offsets do not acquire synthetic
identity or automatic input authority.

## Tasks and verification

- [x] Added WP03-009 and exact collected node mappings. Existing continuous lane
  uniquely owns both edited test files; no quality catalog changes are needed.
- [x] Actual directed RED: four failures (EOF, provider failure, duplicate final
  erasing a newer interim, and combined production Google SDK terminal flow).
- [x] Same four directed cases GREEN after the two-file implementation.
- [x] Actual additional RED: simultaneous ASGI Stop/EOF exposed a preview before
  cancellation. Same test GREEN after control precedence repair.
- [x] Focused regression: 65 passed across continuous unit/HTTP, installed Google
  SDK contracts, diagnostics, and startup-buffer contracts.
- [ ] Merged affected acceptance and independent compiled-client acceptance are
  integration-owner responsibilities; this document does not claim they passed.

Append-only receipts are outside the source snapshot in the task evidence folder
`mira-continuous-evidence-20261005T1238Z`, runs `001-red`, `002-green`,
`003-stop-tie-red`, `004-stop-tie-green`, and `005-focused-regression`.
Each receipt records exact commands, stdout/stderr hashes, source fingerprints,
JUnit counts, and whether source changed during execution.

## Handoff and limits

Only the continuous application service, its existing WebSocket route, existing
Python test files, and documentation/specification change. Actor, schema,
generated contracts, SDK adapters, frontend, budgets and provider authorization
are unchanged. This is synthetic installed-SDK/local-ASGI evidence, not live
Google access, a real microphone, audible playback, or automatic natural turns.
The continuous interface still requires explicit manual submission.
