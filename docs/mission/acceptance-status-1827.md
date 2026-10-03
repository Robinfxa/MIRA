# Current integration candidate — 2026-10-03 18:27 UTC

The published1756 stage at6ab19a8b8d82dce5268c005ab1b99f071464bdf9 is verified:1,248 Python +197 Node tests and all12 local release lanes, repeated from the restored public projection; remote push and manual CI also passed, including package/smoke in the manual run. This later integration candidate has not yet inherited that release result.

## Changes ready for combined verification

- **M01/M07 history boundary:** the server now returns retryable409 `history_pending` when the claimed input cutoff contains missing acknowledged facts. Old authority is revoked without consuming the proposed request/activity/input. A late receipt remains history-only; the exact request can retry into the detail branch. Seven directed domain/Actor/real loopback cases passed. The frontend recognizes only this exact409/code as not-sent. Independent combined verification is pending. A dishonest cutoff is still not proof of what someone saw.
- **M08 development recording:** the backend and UI are wired for explicit app-wide opt-in, owner-scoped bounded PCM staging, exact-buffer preview, separate review/save confirmation and private queueing. Default recording stays off. Backend26 focused and892 consumer checks, independent30 ownership/lifecycle/export cases, and214 final frontend cases passed on their named snapshots. These are not yet one combined release. Owner confirmation is an attestation; the server cannot prove listening or automatically screen spoken secrets. Queue acceptance does not prove a durable write.
- **M03/M09 generation:** the frozen1756 actual native adapter completed speech+subtitle+pose in6.32 seconds. This is a candidate-only result, with no review/presentation/voice admission. See the [explicit-caption smoke](../verification/env04/caption-smoke.md).
- **M02 JEV diagnostics:** six new synthetic calls were attempted under the approved continuation. Five parsed; one compatible output matched its gold vector but remained below the allow threshold. The sixth failed response validation and stopped the run. Its exact historical cause was discarded. Safe parser diagnostics now have90 offline tests; a separately counted one-case diagnostic repeat is prepared but unrun. No calibration, holdout use or threshold reduction occurred.
- **M05 voice:** real STT is verified only for one6.135-second synthetic English fixture. Exact TTS has no usable audio yet. Non-inline-part parsing is corrected offline; the earlier real stream was closed on its first text part, so later events are unknown. Additional Google spend is awaiting the user's decision; no call is implied by code readiness.

## Still required

The combined source release, independent frontend/backend interaction checks, human-observed browser/phone layout and sound, microphone interruption/recovery and a continuous3–5minute live interaction remain pending. Full personality/long-term memory/storylets, G06 image generation and D-M scope are incomplete. Original164 product-acceptance entries remain `not_run`; test totals do not promote them.

No deployment, credential copying, model substitution or automatic payable fallback is enabled. Historical snapshots and their failed/passed receipts retain their original scope.
