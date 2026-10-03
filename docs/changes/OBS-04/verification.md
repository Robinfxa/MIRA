# OBS-04 verification

Source/test/procedure: `apps/api/src/mira/adapters/diagnostics/audio_review.py`,
`tests/contracts/test_diagnostics_audio_review.py`, and the OBS-04 contract/spec.
All fixtures use synthetic PCM, fake sinks or a temporary private diagnostics directory. No
microphone, UI, provider, network, `.env`, credential file or live account was touched. Raw recording
was exercised only with a synthetic buffer in `tmp_path`.

## Evidence

The initial missing-module probe `001-red-audio-review` failed during test collection with pytest
exit 2 while the recorder expected exit 1. It is not a behavioral RED.

`002-red-audio-review-contract` is the behavioral RED: the importable behaviorless scaffold made all
11 original contract tests fail. Its test-file SHA-256 is
`7df3996be623a4e8960dd8d16edc4eb3988f7242f52d2995281d094db6da5d03`.
The first implementation run then showed 10 passed and one test assertion expecting English wording
from a Chinese safe failure message. That assertion was corrected to match the actual user-facing
Chinese result, and two additional ownership/cancellation/limit regression cases were added.

After implementation, `003-red-audio-review-final-contract` ran all 13 final cases against a
temporary behaviorless baseline scaffold as a sensitivity check (13 failed as expected). This is
not described as historical TDD. `004-green-audio-review-final-contract` restored the implementation
and passed all 13 final contract tests; the final test-file SHA-256 was
`8e5416f6dccaf4164b29f1c44d8d23812b4e30dc7f939d7ba5919426aec3d5bb`. Both reports record zero
source changes during their own command. The RED/GREEN statuses and stdout/stderr are under
`docs/verification/obs04/runs/` by those run IDs.

`005-final-diagnostics-regression` passed **111 tests** across the new audio-review contract plus
the existing diagnostics, raw-recording, runtime, and structured-privacy contracts. Its recorder
reported `changes=0`. `tools/check_specs.py` separately collected 122 traceable requirements; that
checks links only, not behavior. Ruff was not run because it is not installed in the selected
offline environment; no dependency install was attempted.

Unselected quality lanes remain not run; this is not full/affected/release verification. The
director owns broader integration checks and may rerun the contract against the final integrated
snapshot.

## Frontend integration

The reviewed-audio flow is now source-integrated with the authenticated session API, visible
opt-in/off controls, one exact-buffer ticket/preview flow, and a review-only audition path on the
existing `CancelSafePlayback` owner. The web lane includes the new frontend files through its
existing `tests/web/*.test.mjs` glob. These Node test IDs are recorded here separately from the
machine-checked pytest traceability manifest:

- `tests/web/controller-reviewed-audio.test.mjs`: `successful final microphone transcript preserves only a server-bound owner-matching raw-audio stream ID`; `mismatched, non-final, wrong-kind or disabled raw staging never prevents a valid transcript`; `a newer text input aborts a pending owner-status lookup before the old transcript can overwrite it`; `only the explicit HTTP 409 history_pending rejection is returned as known not-sent`; `central audition is blocked by active work, emits no session audio facts, and Stop revokes it synchronously`
- `tests/web/reviewed-audio.test.mjs`: `reviewed audio status strictly requires owner-scoped pending identity and the server transcript binding`; `mode enable requires an explicit app-wide consent checkbox and can be explicitly switched off`; `exact clip must be loaded and fully auditioned before matching-digest private queue confirmation`; `digest mismatch, owner change, expiry, Stop and close erase the preview and revoke audition actions`; `a stale review response after newer input is discarded and never authorizes a later save`; `central CancelSafePlayback auditions reviewed PCM without character facts and stops on normal audio, Stop and close`; `audition is refused while character playback owns the sink and after a stale asynchronous resume`; `review UI stays secondary, default-off and separate from export, with exact-buffer privacy copy`
- `tests/web/transport-reviewed-audio.test.mjs`: `reviewed-audio API uses the in-memory session capability, strict metadata and same-origin preview path`; `preview rejects path substitution, content mismatch, wrong owner metadata and oversized binary before review approval`; `only an exact HTTP 409 history_pending body code is retained as safe typed input-rejection metadata`
- Existing composition harnesses were updated and included in that run: `tests/web/controller-main.test.mjs` and `tests/web/error-locators.test.mjs`.

The final-panel RED/GREEN sensitivity pair is recorded under `docs/verification/obs04/runs/`: `008-red-reviewed-audio-ui-final-sensitivity` ran the nine panel/playback tests against a temporary behaviorless frontend shim (six failed as expected; three unaffected playback/markup cases passed), and `010-green-reviewed-audio-panel` ran the same nine tests against the actual compiled frontend (all nine passed). This is a behaviorless-shim sensitivity check, not a claim of historical TDD. `009-green-reviewed-audio-ui-final` separately passed all 17 focused panel, controller and API-client cases, including exact `history_pending` handling. All three reports record `changes=0`.

Final focused quality receipt: `python tools/check.py --lane web --jobs 1 --output-dir var/quality/obs04-reviewed-audio-web-20261003T1820Z` passed in 7.10 seconds. It performed the fresh strict TypeScript build and Node suite; **214 tests passed**. `source_changed` was empty and the before/after source digests matched. Architecture, backend, tooling, package and smoke lanes were not run by this exact-lane check. An earlier full web attempt timed out because the synthetic `error-locators` page harness did not yet provide the new panel elements; the harness was corrected and the bounded full web lane then passed above.

## Limits

Source wiring and synthetic frontend behavior are covered above; actual browser rendering, physical
microphone capture, a human review of a real clip, privacy review of real audio, universal
spoken-secret detection, durable disk success, export safety under future changes and browser/device
behavior are still unverified. Underlying `Diagnostics.capture(True)` reports queue acceptance only.
