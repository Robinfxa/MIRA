# WP09 bounded presented-fact barrier

Base: inherited integrated mission tree, original T0 unchanged. Owner: frontend causal-history repair. The controller is the sole frontend owner of generation/fact sequencing. Do not change shared schemas, domain transitions, bootstrap, or provider code in this slice.

Goal: a new generation must not overtake valid presentation facts already issued at its immutable local cutoff. Stop remains immediate and local. A new request waits only for the captured pre-cutoff fact prefix, with a bounded deadline and explicit failed-ack behavior.

Non-goals: making browser DOM/image decode a claim of physical display or user perception; proving client-asserted cutoffs to the server; changing backend history semantics; adding a generic queue/coordinator; waiting for live work after the captured prefix.

### WP09-001 Bounded cutoff snapshot
Given Stop or input interrupts a running generation, the controller first performs local cancellation synchronously, then freezes the local fact sequence through the exact `presentation_cutoff`. When a subsequent input begins, it captures all already-issued visual-receipt and audio-progress acknowledgements through that cutoff before any generation HTTP request is sent.

When each captured acknowledgement succeeds, the new request may proceed. Facts issued after the snapshot are outside its barrier. Stop itself is never blocked on network fact delivery.

### WP09-002 Failure, timeout, closure, and supersession
Given a captured fact acknowledgement fails, the controller does not submit the new generation and shows a safe actionable history error. Given an acknowledgement does not settle before the bounded deadline, the controller does not submit the generation and shows a retryable timeout error. Close or a newer local activity cancels the waiter promptly; neither may revive the old request. Failed history remains fail-closed for any cutoff that contains the failed fact.

### WP09-003 Real HTTP causal ordering
Given the rehearsal server has sealed the `看照片` turn and the decoded local illustration has been applied, hold the actual `/receipts` HTTP request before the server receives it. When Stop returns and the user submits `照片里有什么`, the controller keeps the new `/inputs` request behind the receipt acknowledgement. After release, receipt and terminal audio-progress facts are acknowledged in presentation order, then the real HTTP generation uses presented-photo history and returns the detail response.

### WP09-004 Not-sent input retention and voice entry
Given a history failure or timeout prevents the controller from dispatching the `/inputs` request, the controller returns a typed `not-sent` outcome with the exact input text. The UI restores that text only if that same submission remains current and the message field is still empty. Newer typing or a later submission is never overwritten; superseded, closed, accepted and uncertain-after-dispatch outcomes are not restored as a blocked request. Final microphone transcription and the fixed rehearsal command route through the same bounded `input()` barrier before the HTTP generation can commit.

## Contracts and boundaries
- Port: existing `SessionTransport`; no public wire change.
- Owner: `apps/web/src/features/session/controller.ts`.
- Consumers: browser SessionController and its existing MiraApiClient/PresentationGate/audio history ports.
- UI acceptance/retention consumer: `apps/web/src/app/main.ts` reoffers only text the controller proves was not sent; it does not retry or accept the request itself.
- No environment settings, provider calls, credentials, or package changes. Use local synthetic rehearsal HTTP only.
- Test owner/lane: `tests/web/controller-fact-barrier.test.mjs`, existing `web` lane.
- Resources: existing TypeScript compiler, Node test runner, ready Python 3.11–3.13 and local FastAPI dependencies for the loopback rehearsal integration.
- RED/GREEN: record the unchanged actual HTTP regression test before and after implementation. Also exercise failure, timeout, close, supersession, and rapid-input paths with deterministic in-memory barriers.
- UI checks: `tests/web/controller-main.test.mjs` verifies exact-text restoration after known pre-dispatch blocking, and no overwrite of newer text; `tests/web/controller-voice.test.mjs` verifies voice final routing and stale post-cutoff failure ownership.
- No full/release run or publication from this worker. The integration director owns affected/full collection.

## Trust boundary
The barrier coordinates this browser controller's own issued facts. Direct or malicious clients can still send arbitrary presentation cutoffs; the HTTP server remains authoritative about accepted effect identity, cutoff fences, and presentation history. A client-supplied cutoff alone is not proof that an effect was shown.
