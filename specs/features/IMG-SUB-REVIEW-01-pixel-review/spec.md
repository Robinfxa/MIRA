# IMG-SUB-REVIEW-01 Independent subscription pixel review

Status: offline internal-client compatibility implementation only. Account entitlement,
live model image-input support and review quality remain unknown.
Base: immutable mira-combined-next-20261006T0018Z; exact 1292-file capture manifest.
Owner block: providers via existing tests/contracts/test_*.py unique ownership.
Consumers: explicit image runtime composition (integration owner), existing VisionReviewBackend.
Resources: one bounded injected credential lookup and one fixed-route streamed HTTP POST;
no authentication storage, provider discovery, retry, API fallback, raw logs or private corpus.
Unselected: live services/accounts, user devices, publication, full/release gates.

### IMGSUBREVIEW01-001 Exact independent pixel input
Given an already generated canonical PNG and compiled finite fictional scene request,
when reviewing, send exactly those bytes as a PNG data URI, the selected review model,
bound request/specification/content/policy identities and fixed check criteria. Send
tools=[], store=false, stream=true only to the fixed ChatGPT Codex Responses route.
Invalid/noncanonical/mislabeled bytes or a request carrying resource references fail
before credential access or HTTP. No history, local resource ID, session or admission
reference is transmitted. This interface does not accept original real-user images.

### IMGSUBREVIEW01-002 Complete and bound observation
Given a bounded SSE stream, require authoritative completed text messages
and a successful terminal event, with one strict JSON and exact required check set and
identity bindings. Preserve fail and unassessable without approval. The requested
model is exact, while returned model names may resolve aliases. Reuse the main
assembler's final-answer concatenation and commentary exclusion. Known first-party
inert metadata has no approval authority. Unknown events/items, tools, refusals,
multiple JSON documents, malformed/partial JSON, mismatched
deltas/snapshot, missing completion or output bounds never yield an observation.
The existing parser accepts a complete JSON event at SSE EOF, but missing terminal
events or partial JSON remain invalid. PNG request bytes have their own image-size
budget, independent of the text generator's 262 KiB request ceiling.

### IMGSUBREVIEW01-003 Cancellation and privacy
Given cancellation or timeout at credentials, response bytes or asynchronous cleanup,
no late result may escape even if an await suppresses cancellation. HTTP failures,
redirects, malformed headers, unsupported/oversized bodies and auth failures are safe
local errors. Exactly one attempt is allowed per call; no raw input/provider/credential
data is logged, and no API transport or alternate route exists.
At the fixed subscription route only, HTTP 200 without Content-Type retains the
previously verified text-transport compatibility boundary; present malformed MIME
still fails. Existing bounded gzip/deflate decoding is reused with independent raw
and decoded byte limits; unsupported encodings fail. No new decompression dependency.

## Grounded wire evidence

Pinned official OpenAI Codex revision: 4d15794336668d6098c0e36eb8e96cbbbfdb1d2d.
Source root: https://github.com/openai/codex/blob/4d15794336668d6098c0e36eb8e96cbbbfdb1d2d/codex-rs/

- protocol/src/models.rs:878–904,2673–2685,3898–3915: input_image inline image_url,
  PNG data URI, user content serialization.
- app-server/tests/suite/v2/turn_start.rs:200–355: actual /responses request carries
  inline PNG pixels even when hidden from the RPC projection.
- app-server/tests/suite/v2/imagegen_extension.rs:771–807,1013–1016: ChatGPT fake auth
  image-input fixture; 187–197: generated PNG becomes a later input_image.
- model-provider-info/src/lib.rs:80,427–445: fixed ChatGPT backend route.
- codex-api/src/endpoint/responses.rs:130–150: POST /responses, SSE acceptance.
- codex-api/src/sse/responses.rs:344–490: text delta/item done and terminal events.
  Lines 480–490 explicitly treat codex.response.metadata, response.metadata and
  responsesapi.websocket_timing as non-candidate metadata.

The prompt requests locally validated JSON without speculative token-limit fields or
an account capability assumption. Existing MIRA bounded SSE parser and text assembler
are reused unchanged; additional review-specific strictness is confined to this adapter.
This is not the public third-party plan-usage hosted-image contract.
