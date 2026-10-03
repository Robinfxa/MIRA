# OBS-03 — Audio interruption facts and cancellation causes

Owner: assigned interruption-diagnostics worker, narrow SessionActor.audio_progress correction.
Baseline: working source at 2026-10-03T12:28Z, Git ancestor ebb578dde665c9c7269e4a64b508182680b2fa66;
exact pre-change Actor retained in docs/verification/obs-03-audio-interruption-causes/baseline-source/.
Test block: providers (tests/contracts/test_audio_interruption_diagnostics.py), already covered by
its exclusive contracts glob. Consumers: Actor, domain audio authority, media cancellation/teardown,
async error locators, HTTP, audio context and cue sequencing. Integration director owns aggregate
snapshot verification. Resources: existing Python 3.13/pytest and synthetic event barriers; no
network, credentials, actual providers, browser or physical audio. No wire/enum/domain changes.

### OBS03-001 — Interruption is a fact, not a Stop attribution
Given current granted speech and running generation/review/media, when an accepted INTERRUPTED
software-render report revokes the current branch, then the playback event is cancelled with cause
UNKNOWN. Dependent work is cancelled with PERMIT_REVOKED, the observed server-side consequence.
A bare interrupted status cannot establish that the user clicked Stop, supplied new input, lost a
connection, or intended anything. Samples and exact effect history stay intact, no full-speech
completion is inferred, and the existing safe diagnostic locator still points to the report.

### OBS03-002 — Explicit causes survive late facts
Given Stop or new input has already cancelled running work with USER_STOP or SUPERSEDED,
when the matching old interrupted report arrives within its presentation fence (or is repeated),
then it contributes history only. It neither relabels the existing cause nor cancels a newer branch.
Given the report arrives before Stop, the report's unknown playback cause and resulting permit
revocation remain immutable; the later Stop clears error metadata and establishes its usual fence.

### OBS03-003 — Other terminal semantics remain unchanged
Given a failed playback report, then it remains a failed event with UNKNOWN error code and no
cancellation reason; dependent work remains PERMIT_REVOKED. Duplicate accepted terminal reports
must not emit extra terminal diagnostics or revive authority. Existing microphone teardown,
monotonic samples, presentation sequencing, explicit Stop and async locators remain authoritative.
