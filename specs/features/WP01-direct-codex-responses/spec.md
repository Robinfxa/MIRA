# WP01 Direct Codex Responses generation adapter

Status: offline implementation slice; default-OFF. The ChatGPT Codex Responses route is
private/undocumented for third-party compatibility; offline mocks establish request shape,
not service availability, permitted use, quota, model access, semantic review, or presentation.
No real request, auth grant, login, or credentials were used. `httpx==0.28.1` is already pinned.
The existing GenerationBackend, SessionActor, independent JEV review, compiler, and output
epoch remain the authority. This adapter only proposes untrusted candidate effects.

### WP01DR-001 Explicit fixed route and model
Given no explicit admission and positive request budget, generation fails before credential
access or network. Given an explicit `chatgpt_subscription` or `openai_api` route and one
validated model identifier, send only to that route's fixed endpoint. Never retry, change
model, change route, or switch billing. Subscription defaults are the factory's responsibility.

### WP01DR-002 Opaque route-specific credentials
Given an injected `get_credentials()` source, read only a SecretStr access token. Send it as
Bearer auth only to the fixed route endpoint. Subscription may additionally send the supplied
`ChatGPT-Account-ID` and `x-openai-internal-codex-residency`; the public API route must omit
both. Never inspect auth storage, log raw body/headers/token, or derive metadata in this adapter.

### WP01DR-003 Bounded Responses request
Given valid generation context, reuse fixed local prompt/instructions and send Responses
`instructions` plus a single user `input` message, `stream: true`, and `store: false`. Expose
no tools, tool choices, or side-effect execution. Subscription route does not assume support
for `text.format`; both routes still use strict local candidate parsing.

### WP01DR-004 Complete SSE assembly only
Given fragmented/multiline SSE, enforce finite line, event, wire, output, prompt, request,
startup, and turn bounds. Completed `response.output_item.done` assistant message items are
authoritative; output-text deltas are fallback only when no completed item exists for that
message. `response.completed` may have a null output snapshot. Only a clean terminal success,
EOF, one complete text item, and successful local parse produce one CandidateRange.
Errors, incomplete/failed/cancelled terminal states, EOF before success, malformed content,
tool-call items, late cancellation, or unsupported content never yield.

### WP01DR-005 Safe actionable failures and cleanup
Given 401, 403, 429, timeout, transport, contract, incomplete stream, cancellation, or bound
failure, close the stream/client and expose only fixed safe codes plus local stage and known HTTP
status where applicable. Never expose provider error bodies, credentials, raw response headers,
or event payloads. A cancellation never yields a CandidateRange; remote completion/billing
termination is not guaranteed by local cancellation.

## Contract and tests
Port: `GenerationBackend`; route and model selected by the composition/factory owner; no
bootstrap, config, CLI, process, preflight, auth-store, Actor, review, or shared-payload edits
in this slice. Credentials: injected structural protocol agreed with the auth owner. MockHTTP
transport only; no live endpoint or account. The adapter does not claim the private endpoint
is an official public API contract or that either route has quota/model access.

Test lane: providers, owned by the integration director in `tests/quality.toml`.
Required consumer: existing independent generation/review and cancellation contracts.
RED/GREEN target: `python -m pytest tests/contracts/test_direct_codex_responses.py -q`.
Common base and affected plan are owned by the integration director. Synthetic `httpx.MockTransport`
only; no external account, network request, persistent artifact, or actual provider call.


## 2026-10-05 compressed SSE and content-free failure diagnosis

### WP01DR-006 Decode bounded HTTP content before SSE
Given identity, gzip or deflate (zlib-wrapped or raw) HTTP content, decode exactly once
before strict UTF-8/SSE parsing. Independently enforce the configured byte cap on wire
and decoded content; bound decompression itself. Invalid/truncated/trailing compressed
content fails closed. Cancellation and timeout close streams and never yield candidates.
Do not weaken terminal success, one-message, effects, or independent review contracts.

### WP01DR-007 Export only fixed generation failure facts
Given direct generation failure, preserve HTTP status and local phase/reason through
Actor and ordinary diagnostics export. Include only bounded counts, known event types,
fixed encoding/terminal state/error-code classes. Unknown provider strings become other.
Never include text, IDs, raw headers, bodies, tokens, URLs or prompts. Existing records
remain readable. Frontend generic invalid_response must not falsely attribute generation
failure to review or claim previously presented output never appeared.

Hotfix base: immutable 2219 source capture; auth-v2 and fetch-receiver changes touch
separate files. Test owner: providers by existing tests/contracts/test_*.py glob; UI owner:
web. Consumers: actor, HTTP, diagnostic encoder/export, no public DTO changes. New safe
contract lives in application; adapter imports it, not vice versa. Synthetic tests only,
no credentials, auth stores, provider calls, model changes or billing changes. The real
user failure cause remains unknown until safe failure facts from a new run are observed.

### WP01DR-008 Content-free strict JSON rejection classes
Given a candidate rejected by the existing strict JSON parser, preserve the external
invalid_response and codex_json_invalid reason while exporting only a closed failure
kind (syntax, duplicate_key, nonfinite, encoding, depth, type, unknown) and lexical
wrapper shape (bare_object, array, markdown_fence, plain_or_other). Shapes describe the
first non-JSON-whitespace prefix, not validated syntax. Non-JSON failures have null
classification fields. Existing exports lacking these optional fields remain readable.
Do not record candidate text, keys, hashes, parser messages, or exception text. Do not
strip wrappers, repair content, retry requests, or change valid JSON acceptance.

Base: /tmp/mira-firstperson-integration-20261005T0613Z snapshot, 2026-10-05 06:48 UTC.
Owner: providers via the existing tests/contracts/test_*.py glob. Consumers: shared
strict parser, direct adapter, safe diagnostic encoder/export. No Actor, prompt, auth,
model, network, or shared candidate fields change. MockTransport and synthetic markers
only. The real 147-byte candidate's cause is unknown; classification is prospective.

### WP01DR-009 Local candidate value failures and independent next-turn recovery
Given completed HTTP/SSE followed by candidate validation that raises ValueError
(including UnicodeError) or TypeError, reject as invalid_response in the validation
phase with the fixed candidate_value_invalid reason. Never misreport a local malformed
value as transport unavailability or SSE decoding failure. Strict JSON classifications
remain separate; malformed values are not repaired and consume exactly one request.
Actual network, SSE JSON and SSE UTF-8 failures retain their existing phases/reasons.

Given a completed but invalid candidate in the direct ASGI application, a subsequent
explicit user input can independently generate text and separately permitted speech.
Failed generated content enters neither grants nor presented history; reliable user
input remains. Uncertain speech permission keeps the independent text available.
Synthetic streamed HTTP, real JEV parser, authenticated microphone WebSocket/manual
transcript submission, ASGI receipts/audio transport and safe export
exercise this contract; they do not establish physical playback or live provider success.

Base: restored 0703 release at 2026-10-05 12:34 UTC. Owner: providers via existing
contracts glob; consumers: direct adapter, Actor/HTTP, diagnostics/export. No Actor,
shared contracts, prompts, route, model or auth changes. One focused pytest process;
affected tests before integration. Actual 147-byte candidate remains unavailable and
its original cause is unknown. Three new local-value examples are independent synthetic
reproductions, not reconstructions of that private response.
