# Known issues: MIRA 20261003T1104Z checkpoint

Supplement to source archive commit `7416e1e66cf420699a3a351d5a5da0bc67eea947`. This additive note preserves the archive and original acceptance evidence unchanged.

## Stage status

Offline automated tests passed: **741 Python and 115 Node**, across 10 selected lanes. New adversarial interaction/privacy checks identified open defects outside that recorded run. **Interaction and raw-recording privacy acceptance are incomplete.**

## Open defects in this frozen checkpoint

1. Multi-range subtitle and visual effects can present before queued speech.
2. A safe Chinese error message is overwritten by a stable error code.
3. The raw-recording privacy filter can miss credential-shaped text escaped inside model context. The reproduction used synthetic data only; no real credentials were exposed. Raw recording is **OFF by default and must remain disabled until this issue is fixed and verified**. Do not enable development recording or recording consent for this checkpoint.

Corrections are assigned to a later source checkpoint; this note does not claim they are already present here. The original automated result remains valid, but it is not complete product acceptance.

## Immutable backup

Archive: `mira-integration-20261003T1104Z.zip`

SHA256: `7ef256926c3d2003ffac4e923d7174ea89ca4b9566f11fd40a79ad87fac011b1`

This note supplements the outer README/manifest and the archive's embedded metadata with the latest known findings. Packaging, smoke, live-provider, browser/device audio, original architecture acceptance and remote CI success are not established for this checkpoint.
