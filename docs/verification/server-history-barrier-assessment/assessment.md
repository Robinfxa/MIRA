# Server receipt-before-input barrier assessment

Date: 2026-10-03 UTC  
Scope: read-only design investigation of `<project-root>`; no production code, tests, schema exports, or runtime state changed. Only this new assessment file is written. The source tree was already dirty at entry; its HEAD was `ebb578d`.

## Recommendation

Use the existing `presentation_cutoff` as an inclusive acknowledged-history watermark. Before `begin_input` mutates a session, require every global presentation sequence `1..cutoff` to exist in the Actor's accepted receipt or audio-progress history. Return a retryable `history_pending` when the prefix has a hole. No new DTO is needed: `InputRequest` and `StopRequest` already carry the cutoff, and both fact types already carry the shared `presentation_seq`.

For a blocked new input while an older branch is still authorized, the Actor must revoke/cancel that branch under its existing lock without consuming the proposed `activity_seq` or `request_id`, appending the input, or fabricating a Stop activity. The caller can then post the missing valid fact and retry the exact same input ID/body. Explicit Stop remains immediate and does not wait on history. If the branch was already stopped, a blocked input is simply not committed; the later receipt still adds history only.

A bounded check can avoid iterating to an untrusted cutoff: after the existing monotonic-cutoff validation, let `n = count(seq for seq in all_receipt_and_audio_sequences if seq <= cutoff)`. Because accepted sequence values are positive and globally unique, the inclusive prefix is complete iff `n == cutoff` (`cutoff == 0` is complete). The current effect and audio-history budgets bound the list; do not write `for seq in range(1, cutoff + 1)`.

## Existing server facts and boundary

- `Effect` carries server-issued `id`, `digest`, `output_epoch`, and `activity_seq` (`apps/api/src/mira/domain/models.py:22-32`). A `Receipt` binds those fields plus client-allocated `presentation_seq`; `AudioProgress` has the same origin/sequence plus typed software-render status and counters (`models.py:35-61`).
- `_presentation_sequences` merges receipt and audio sequence IDs; each transition rejects duplicate IDs (`domain/transitions.py:14-17,117-118,154-156`).
- `_cutoff` currently rejects a cutoff below the greatest accepted sequence or previous cutoff, but permits an unacknowledged gap (`transitions.py:20-24`). `begin_input` calls it, then commits the user text/epochs; there is no prefix-completeness check (`transitions.py:35-49`).
- `SessionActor.submit` calls `begin_input` under `_lock`, then cancels old tasks, stores the request fingerprint/reliable input, commits, and starts generation (`application/session_actor.py:108-140`). A validation error at `begin_input` therefore naturally precedes any new input mutation. If adding history rejection, explicitly preserve old-branch cancellation when relevant; a bare early 409 must not leave a live server generation authorized after the browser already stopped locally.
- Retry identity survives this particular rejection: Actor records `_request_fingerprints` and `_decision_inputs` only after `begin_input` succeeds. For ASR final text, the route's earlier `consume_input_completion` binds the exact request ID idempotently; retrying the same ID/text/stream returns the same match (`entrypoints/http/routes.py:73-86`, `adapters/diagnostics/audio_review.py:293-324`). A new request ID cannot reuse that one-use completion, so retry must preserve the original ID.
- `stop` currently fences the old branch and cancels tasks synchronously without waiting on receipt delivery (`transitions.py:52-63`, `session_actor.py:142-148`). A valid old receipt at/below that fence appends only; it does not reopen grants or phase (`transitions.py:102-132`). Preserve this behavior.
- Receipts and audio progress append to authoritative in-memory session state and are not trimmed. Audio progress rejects at 4096 rather than compacting (`transitions.py:171-174`); effect issuance is also bounded. Session history is process-local, not durable across restart (`application/sessions.py`, root architecture notes).

## Frontend allocation-density check

The sequence is a dense, shared counter in the current canonical browser path (`PresentationGate.presentation`, `permit-gate.ts:13-14`). A presentation ID is allocated only when a typed fact is actually created:

- Visual receipt: `consume` first requires the exact current non-speech permit, then increments (`permit-gate.ts:117-124`). Controller applies the effect and rechecks authorization before calling it (`session/controller.ts:202-210`). Media prepare/load failure, abort, stale callback, rejected permit, or `apply()` exception returns before receipt allocation (`controller.ts:212-245`).
- Audio progress: submitted-only callbacks, stale/invalid origin, unchanged rendered frame counts, and terminal/duplicate callbacks are filtered before `++presentation` (`permit-gate.ts:98-115`). A valid terminal interrupted/failed event may carry zero samples and is still a required typed history fact, not proof that speech was heard.
- Stop/new-input interruption calls `playback.stop()` synchronously before `gate.stop()` / `gate.beginInput()` captures the cutoff (`controller.ts:269-301,326-335`), so a valid terminal progress fact is included.
- One intentional hole source exists: `audioProgress` assigns its sequence before `enqueueFact`; if the local pending count exceeds 4096, `enqueueFact` drops that fact, records `failedFact`, and tells the user to start a fresh session (`controller.ts:434-440`). A rejected network POST also leaves a hole (`controller.ts:444-456`). WP09 already specifies fail-closed behavior for those facts (`specs/features/WP09-presented-fact-barrier/spec.md:14-15`). Close sets `closed` before interrupt and can skip enqueue for a terminal callback, but that controller cannot send later input; reconnect creates a new session (`controller.ts:629-638`).

Thus ordinary non-presentation paths do not consume a number. A missing allocated number means the fact was lost or rejected; silently skipping it would create incomplete history. Current WP09 behavior intentionally requires a fresh session after persistent fact-delivery failure. A future repair path should retry the same immutable fact before clearing the hole.

## Smallest implementation surface

1. `apps/api/src/mira/domain/transitions.py`: add a pure prefix-complete predicate over the existing receipt/audio sequence tuples and call it in `begin_input` after `_cutoff`; raise `DomainError("history_pending", ...)` before constructing a new state when incomplete. Keep Stop free of this gate.
2. `apps/api/src/mira/application/session_actor.py`: catch only that specific error while still under `_lock`. If the current branch has authority, commit a separate internal revoke transition (or equivalent pure transition in `domain/transitions.py`) that clears `request_id`/`active_grants`, advances output and permit epochs, fences at the submitted cutoff, sets stopped state, and cancels old generation/media tasks. It must leave `activity_seq`, `input_epoch`, `user_inputs`, `_request_fingerprints`, and `_decision_inputs` unchanged, so the same request ID/activity can be retried. Do not synthesize an external Stop call/event or report the input as committed. If already stopped/without current authority, do not add a needless epoch transition.
3. `apps/api/src/mira/application/diagnostic_errors.py`: allowlist `history_pending` so the HTTP 409 carries its stable code. `routes.py` and `schemas.py` need no change. Generated contracts should stay byte-identical.
4. Focused tests only in `tests/unit/test_actor.py` or a new unit transition file, plus a real local HTTP regression in `tests/integration/test_rehearsal_http.py` (or a dedicated narrowly owned integration file). Register any new test in `tests/quality.toml` / spec only as part of a later implementation slice; this assessment does not create tests.

## Required backend checks

- Direct HTTP repro: after `看照片`, Stop with cutoff 1, then follow-up input with cutoff 1 before receipt seq 1. Expect 409 `history_pending`, no new `user_inputs`, no new request fingerprint, no new generation context. The delayed valid receipt at seq 1 remains accepted at 200 and history-only; retry with the *same* request ID/activity/text/cutoff returns 202 and captured generation context contains that photo. This should reverse the direct-HTTP failure described in `mira-cancel-stress-audit/postfix/RESULTS.md` without changing the existing frontend rehearsal proof.
- Current-branch cancellation: force a gap while an uncooperative provider is active. Blocked input revokes old authority/cancels its owned work but does not consume its activity or request ID; an ignored/late provider result cannot revive it; after the missing receipt arrives, exact retry starts one generation.
- Sequence cases: cutoff 0 passes; missing seq 1 with cutoff 1 fails; seq 2 accepted before seq 1 with cutoff 2 still fails until seq 1 arrives; interleaved visual receipt/audio-progress sequences complete the same prefix; facts above cutoff are not counted toward that prefix; invalid >fence late fact remains rejected and cannot fill a hole.
- Large cutoffs fail promptly by comparing the count rather than iterating a range. Existing request idempotency/conflict, Stop immediacy, current input cancellation, and late-fact history-only tests must still pass.

## Limits

This is an honest-client consistency barrier, not cryptographic proof. `presentation_seq` and `presentation_cutoff` come from the client; a direct/malicious client can lie or send a smaller cutoff, and neither sequence nor receipt proves a human saw/heard/understood anything. Accepted effect identity and stop fences remain server-validated. If a fact is permanently rejected or lost, the prefix remains incomplete; current UI already requires a fresh session for a known delivery failure. The Actor ledger is in-memory, so this does not add durable recovery or cross-restart replay.

Read-only evidence: direct repro and prior 17-case frontend audit at `<private-evidence-path>`; unchanged direct-HTTP repro at `<private-evidence-path>`. No test was rerun and no source behavior is claimed as repaired.
