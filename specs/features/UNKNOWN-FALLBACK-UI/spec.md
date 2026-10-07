# UNKNOWN semantic fallback in the MIRA workbench

Scope: present a genuine semantic `review_uncertain` terminal snapshot as one clear,
nonfatal system notice while leaving technical errors on the existing error path.
Common baseline: `ebb578dde665c9c7269e4a64b508182680b2fa66`. Current authorized
deadline: 2026-10-04 12:58:44 UTC. UI-only behavior; no wire field, protocol, permission,
provider, audio, visual-effect, media, pose, receipt, or retry changes.

Owner: the existing `tests/web/*.test.mjs` glob is uniquely assigned to the `web` lane.
Node cases and run receipts are recorded in `traceability-web.json`. The current
`tools/check_specs.py` accepts only collected pytest node IDs, so it does not validate
this web sidecar; do not map these UI behaviors to unrelated Python tests or change the
global checker for this slice. Tests use the real TypeScript `SessionController`, fake
ports, and the existing fake-DOM main harness. They do not establish real browser paint,
audible output, or user visibility.
Consumers: `SessionController`, `SessionViewPort`, `app/main.ts`, and the static system
status region. The backend uses the existing snapshot pair `phase='error'` and
`last_error='review_uncertain'`; this feature does not broaden that classification.

### UNKNOWNUI-001 Exact, nonfatal uncertainty notice

Given the exact `review_uncertain` phase/error pair for the current activity and output
epoch, show the plain-text system notice labeled `系统提示` with the exact body
`这部分我还不确定，先跳过。你可以补充说明，或继续聊。` at most once for that
activity/epoch. Do not convert it to a generic error or call terminal failure handling;
settle only the local thinking indicator without replacing any displayed text. Do not
create receipts, media, poses, effects, voice, or retry activity. Repeated
poll snapshots cannot duplicate the notice. Explicit rejection and malformed/technical
errors retain their current error copy and handling.

### UNKNOWNUI-002 Immediate local clearing and useful continuity

Given a visible uncertainty notice, Stop, a newer submitted input, or Close clears it
synchronously before waiting for network cleanup. Old-activity snapshots cannot revive
it, and the user can send a following input. Preserve any already-rendered prefix and
never imply that the whole interaction was unexecuted. Older view ports without the new
optional notice callback receive only one fallback through their existing error surface,
which is cleared with the next local interruption.
