# IMG-REVIEW-03: bounded subscription review stream partitions

Base: frozen commit `355609fe43149a902eb1e5ace53a1e3879826a1d`, 2026-10-06.
Owner: providers via the existing unique `tests/contracts/test_*.py` owner in
`tests/quality.toml`. Consumers: independent pixel review, direct text/tool SSE
transport and component-check detail report. Related lanes: architecture,
providers, config, actor, http and specs. Shared schema/bootstrap/Actor unchanged.

### IMGREVIEW03-001 Delta partition invariance
Given the same small, strictly bound pixel-review JSON and canonical PNG, when
the valid response text is divided into 126, 127, 128 or 256 SSE deltas, then the
production reviewer accepts the same observation within all retained byte limits.
The local event budget is 1024, matching the existing direct Responses default.
This does not establish the actual cause of the 2012 live review failure.

### IMGREVIEW03-002 Closed resource failures
Given a bounded SSE stream, when event count exceeds 1024, then the reviewer
fails with `subscription_review_event_limit`. Wire, decoded, line and output
byte overflows retain separate fixed local failure codes. The existing 65,536
wire/decoded bytes, 16,384 line bytes, 8192 output bytes, timeouts, single request,
no retry and no route fallback remain unchanged. No provider text is logged.

### IMGREVIEW03-003 Preserve independent strict review
Given more than 128 valid stream events, when request identity, PNG digest,
schema, checks or metadata is invalid, then no observation is accepted. Exact
PNG transmission, canonicalization, content/schema/policy binding, terminal
checks and pixel review are retained. No arbitrary JSON recovery is introduced.

Protocol basis checked 2026-10-06: [OpenAI Responses streaming events](https://developers.openai.com/api/reference/resources/responses/streaming-events)
defines output text deltas as text strings, without a fixed partition size.
These public shape references do not establish private subscription entitlement.
