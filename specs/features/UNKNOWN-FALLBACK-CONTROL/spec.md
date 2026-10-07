# UNKNOWN fallback control

Status: a normal clarification presentation is permitted only for explicit semantic
uncertainty. All candidates remain fail-closed and receive no authority unless their
ordinary review completes successfully.

Owner: application semantic classification and session actor failure path.
Test block: providers (`tests/contracts/test_semantic_unknown_fallback.py`).
Consumers: `diagnostic_errors.py`, `decision_runtime.py`, `session_actor.py`, the existing
HTTP session snapshot, and the independently owned system-notice UI.
Resources: synthetic in-process JEV transports and ASGI `TestClient`; no live provider,
credentials, microphone, browser, or paid call. No schema, domain transition, or new
wire field is introduced.

## Given / When / Then

### UFBCTRL-001 — Explicit semantic output uncertainty

Given a real JEV adapter returns a well-formed semantic UNKNOWN because it selects
`unknown` or fails the selected confidence threshold, when the session actor records the
review failure, then the existing snapshot reports `phase=error` and
`last_error=review_uncertain`. It issues no grant for that candidate, retains only any
previously presented prefix, makes no semantic-review retry, and accepts a later input.

### UFBCTRL-002 — Input semantic uncertainty is propagated

Given the input decision returns the fixed `jev_input_semantic_unknown` result, when the
output coordinator observes it, then that exact semantic-uncertainty provenance reaches
the actor and maps to `review_uncertain` without an output-review dispatch or grant.

### UFBCTRL-003 — Consecutive clarification turns remain usable

Given successive turns each produce semantic UNKNOWN, when a later turn's input and
output reviews both allow, then each uncertain turn makes only its ordinary bounded
review calls, the new input clears prior error state, and the later turn can seal normally.
No fallback effect, permit, retry, or speech is fabricated.

### UFBCTRL-004 — Prefix and cancellation fences remain authoritative

Given a candidate prefix has already received an actual presentation receipt and a later
candidate returns semantic UNKNOWN, when the actor fails that turn, then the presented
prefix remains in history and the uncertain remainder is not granted. If Stop or a newer
input supersedes an in-flight review, a late UNKNOWN cannot overwrite the resulting state.

### UFBCTRL-005 — Technical and policy failures are not soft clarification

Given a review is rejected, malformed, unavailable, over budget, uncalibrated, missing a
valid contract, or returns an unclassified UNKNOWN, when the actor records the result,
then it stays on its existing fail-closed error path (`review_not_allowed`,
`invalid_response`, `unavailable`, `review_budget_exhausted`, or generic `unknown` as
applicable), never `review_uncertain`. Such results produce no grant or fallback effect.

## Verification boundary

The tests use the actual HTTP application, session actor, input/output JEV adapters, and
typed semantic coordinator, with deterministic synthetic transports and generated text.
They verify software-level request counts, snapshot transitions, receipts, and cancellation
fences only. They do not establish Chinese semantic quality, model calibration, live service
readiness, user understanding, or audio playback.
