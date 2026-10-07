# IMG-SIZE-01: bounded provider-returned image dimensions

Baseline: frozen /tmp/mira-post1515-integration-20261006T1623Z (1645 source). Work is isolated; no account calls, request-size, quality, model, attempts, bytes or cost changes. The reported original IHDR is 1536x1024; its CRC and full pixels were not validated. Synthetic complete PNGs establish the regression only.

Owner: providers contracts and web lane. Consumers: decoder, immutable request/admission, runtime, subscription review, protected resource, renderer and receipt/tool result. Shared bootstrap and ports edits are coordinated with integration owner. Resource: one generation and at most one review per job, existing byte and timeout bounds; finite accepted raster envelope 1536x1024 maximum. Portrait 1024x1536 is admitted alongside square and landscape, supported by the first-party image size contract and native Codex client tests. API stays square.

### IMGSIZE01-001
Given a complete opaque 1536x1024 PNG returned from the subscription transport for the unchanged 1024x1024 request, when the explicit bounded output policy validates and independently reviews its canonical bytes, then the same actual pixels/dimensions reach the protected resource, and shown occurs only after the matching software renderer receipt. Existing 1024x1024 works too.

### IMGSIZE01-002
Given unsupported dimensions, invalid CRC, incomplete or extra raster data, transparency, animation, wrong review/digest/receipt or cancellation, then no visible image/tool success is granted and attempts are not refunded. API remains strictly square; other shapes are rejected.

First-party contract (read 2026-10-06): https://developers.openai.com/api/reference/resources/images/methods/generate and https://github.com/openai/codex/blob/main/codex-rs/codex-api/src/endpoint/images.rs . Shapes do not prove account entitlement.

### IMGSIZE01-003
Given an already failed or cancelled image fact, when later input/Stop/cleanup releases it again, then the original terminal outcome remains stable, reservations are released at most once, and attempts/cost are never refunded. Still-pending work changes to cancelled normally. This terminal-state repair does not change source-intent selection or add tools.
