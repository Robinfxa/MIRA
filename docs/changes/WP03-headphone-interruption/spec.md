# Explicit headphone interruption

This next-stage software feature builds on immutable MIRA1935. It does not establish
speaker echo cancellation, human speech identity, physical hearing or device latency.
The default remains guarded speaker/unknown playback; explicit headphones is a local
choice for the next microphone lease. No extra provider, request, retry, spend cap,
microphone permission, raw audio persistence or external diagnostic data is introduced.

## Requirements

### HEADPHONE-001 Bounded interruption and continuous input
Given an explicitly selected headphone lease, a fresh 160 ms sustained PCM activity
candidate may synchronously interrupt the reply. Only after successful interruption
and an idle software sink can its exact sample range lose the playback-overlap hold.
Capture remains active; ordinary quiet/drain/commit/continuation fences still govern
submission. AEC supported/reported booleans provide information, never permission.

### HEADPHONE-002 Conservative boundaries
Default guarded mode, stale or invalid PCM, a short impulse, unknown prior overlap,
failed interruption and different earlier overlap cannot gain automatic-submission
eligibility. Mode is fixed per lease. Stop/close/revoke discard detector state and
processing status, keep already accepted input and actual presentation facts, and
never restart microphone capture automatically. Headphone selection is an assumption
the user can change, not acoustic proof. Speaker mode retains explicit interruption.

The web owner covers `tests/web/continuous-headphones.test.mjs` against the actual
compiled continuous controller and UI; the audio owner
separately covers its detector and processing-status capture contract. Final behavior
needs independent race checks and real microphone/speaker/headphone validation.
