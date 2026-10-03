# Known-issue addendum to the 12:56 rehearsal checkpoint

Recorded 2026-10-03 after the immutable checkpoint and passing local release checks. The archived source and its original evidence remain unchanged.

## Confirmed media-readiness contract gap

An independent deterministic test of the actual scene executor and controller found that a pending or broken travel-image asset can receive a presentation receipt immediately when its figure is unhidden. The application then adds `trip_photo` to presented history, causing the fixed rehearsal response to “照片里有什么” to describe the image as already shown. The same prematurely exposed figure may fill after Stop or newer input when loading eventually finishes.

The test covered incomplete images (`complete=false`, `naturalWidth=0`) and broken images (`complete=true`, `naturalWidth=0`), plus the real application receipt/history and rehearsal-selection functions. A previously ready photo remaining visible after Stop is intentional and must be preserved.

This is a confirmed software contract gap. It is not an observed real-browser incident, proof of pixels being painted, or evidence that a person saw the picture. The earlier passing unit/release checks did not cover this readiness condition.

## Status

A cancel-safe correction is in progress after this snapshot. Required behavior: wait for validated asset readiness without revealing it, recheck current activity and permit before the synchronous reveal/receipt, and suppress late completion after Stop, newer input, revocation or close. Loading failure must be actionable and must not create a presented-history fact.

Do not treat the 12:56 source archive as having this correction. Its original reports saying the independent media audit was pending describe their preparation time; this addendum supplies the newer result. The existing browser/device/live-provider and recording gaps remain open.
