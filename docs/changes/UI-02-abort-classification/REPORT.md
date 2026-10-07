# UI-02: abort classification and late-response fencing

The reported text “signal is aborted without reason” can be reproduced from this application's own 5-second JSON request deadline. It calls AbortController.abort() without a cause, and controller.report previously copied the resulting native exception message. The same defect exists in the immutable 0550 build and the frozen responsive UI build. This demonstrates a concrete mechanism, not proof of the user's specific request timing or root cause. Server generation duration does not establish HTTP request duration.

## Minimal correction

- New transport-errors.ts owns three safe categories: request_timeout, request_cancelled, request_aborted. Deadline aborts carry a typed cause. AbortSignal.any's first cause wins.
- API JSON fetch/body-read and reviewed-audio preview classify owned timeout versus caller cancellation versus unexpected abort. Malformed JSON, ordinary network errors and HTTP failures are not swallowed or reclassified as success.
- Late responses from an uncooperative fetch cannot return a timed-out/canceled snapshot. Late successful session creation receives the existing bounded DELETE cleanup rather than installing credentials.
- Speech's existing 330-second transport deadline gets the same classification. The 5-second JSON and 330-second speech bounds are unchanged.
- The controller's report boundary maps unexpected native AbortError/TimeoutError to safe fixed text; it does not suppress them. Existing ownership/generation guards continue to suppress Stop/new-input/Close and stale microphone/poll callbacks.
- No auto-retry occurs. Timeout/interruption copy explicitly says the operation result is unconfirmed, avoiding a false claim that the server did not receive an input.

Production files: api-client.ts, audio-transport.ts, controller.ts and new transport-errors.ts under apps/web/src/features/session. Controller change is one import and two report lines; no input, poll, generation, receipt or FIFO logic changed. The semantic-chunk owner has the exact seam for its combined controller. Do not overwrite that owner's controller with this 0550-based file.

## Genuine tests and results

The first 12 directed tests against both frozen 0550 and frozen responsive compiled artifacts produced 6 failures / 6 passes. Missing classifications and late-response acceptance failed; owned cancellation guards already passed. After transport changes, 12/12 passed. A new report-boundary expectation then failed (15/16 passing); the minimal report correction made all 16 pass.

Final affected run: 411/411 web tests and 7/7 architecture checks passed, with unchanged source digest during execution. Report: docs/verification/ui-02-abort/affected/summary.json. A separate responsive source copy with only this fix overlaid also compiled and passed 425/425 web tests (011-responsive-integration.log). Original source captures and frozen responsive proposal were not modified.

Cases include actual AbortController/default DOMException at fetch/body, explicit controlled deadlines, unexpected native abort, Stop/new-input/Close, stale poll, microphone setup/final cancellation, first-cause races, late input and late session creation cleanup, and preserving ordinary/malformed-response failures. These are deterministic synthetic browser-module/controller tests, not a browser network observation.

No provider calls, credential access, browser workaround, device capture, external network diagnosis or full release run occurred. The user-specific triggering request remains unverified; this patch does not make genuinely slow HTTP requests succeed or establish that every reported abort was a normal cancellation.

Source: /tmp/mira-frontend-abort-fix-20261005
Compiled source: /tmp/mira-frontend-abort-fix-dist
Separate responsive integration: /tmp/mira-abort-responsive-integration-20261005
Combined compiled source: /tmp/mira-abort-responsive-integration-dist

The frozen UI's prepared-subtitle observer omission is a separate issue identified and owned by the semantic chunk worker; it is not silently counted as fixed by this abort patch.
