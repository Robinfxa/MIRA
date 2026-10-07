# IMG-STATUS-01: optional process image admission feedback

Base: frozen mira-image-integrated-20261005T2334Z, manifest SHA-256 07e4790721c1e15628526d8b86020d3560046fc9d8c86d3f7571f9ece1a62095. Owner lanes: providers via tests/contracts/test_*.py; web via tests/web/*.test.mjs. Consumers: process bootstrap, application media port, SessionActor, compiled frontend status. Shared Actor/bootstrap ownership is delegated by the image integration director. Resource budgets, refunds, retries, consent and DTOs are unchanged. Test resources are synthetic transports/pixels and local test clients; no provider, credentials, user database or browser. Ports conservatively expand the affected check to every offline lane; final release belongs to the director.

### IMGSTATUS01-001 Closed typed admission denial
Given an otherwise reviewed image job whose shared process attempt, reserved-byte or planning allowance is exhausted, including after failure and Close/new session, when the process gate rejects it, then a typed ValueError-compatible denial with closed reason budget crosses the application port. Actor publishes held/budget, preserves ordinary text, performs no extra image/review HTTP, releases session reservation bytes and never labels it a provider failure. Busy is held/ineligible, retains the in-flight owner and spends no extra allowance; a later explicit input may proceed after release. Arbitrary exception strings never authorize this classification.

### IMGSTATUS01-002 Cancellation fences remain final
Given a late typed denial after Stop, newer accepted input or same-epoch photo dismissal, when the old work settles, then current state is unchanged and no image, grant or reservation revives. Existing current-reservation, epoch, activity and visibility fences apply to the typed branch.

## Clear bounded frontend feedback (web sidecar)
Given held/budget, when the compiled controller installs the snapshot, then image feedback says its current-run call allowance is exhausted and chat can continue. It claims no provider billing cap, requests no pixels, retains ordinary subtitle receipts and permits subsequent chat. Other held reasons retain generic eligibility wording.
