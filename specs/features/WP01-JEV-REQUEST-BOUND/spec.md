# WP01 JEV output-review request bound

Status: bounded local serialization/transport contract. This is not a provider token
or cost ceiling and does not represent a live provider call.

### WP01JEVREQUESTBOUND-001 Output-review requests remain complete and byte-bounded

Given an output review request containing its exact current context, candidate, immutable
review contract, full question set and digests, the backend serializes canonical UTF-8
without projecting away context or evidence. Exactly 32,768 serialized bytes may be
sent. A request at 32,769 bytes returns UNKNOWN with the fixed `jev_request_too_large`
reason before transport invocation. The HTTP transport independently accepts exactly
32,768 bytes and rejects a larger body before creating an HTTP request. Limits are
measured in bytes, including multibyte UTF-8 characters.

Only the local output-review request envelope changes to 32 KiB. Input-review stays at
16 KiB; the existing 64 KiB response ceiling, question set, decision thresholds,
request-budget reservation, retries, provider token/cost limits and evidence binding
remain unchanged. An actual four-turn synthetic ASGI run retains complete input history,
presented effects, accepted prefix, snapshots, input observations and digest binding
with eight input-review requests, eight output-review requests and four fake generation
requests. This software-only result does not establish real UI presentation, human
understanding, provider account access, spend, network behavior or audio.

### WP01JEVREQUESTBOUND-002 Configured review bounds reach the concrete HTTP transport

Given the development review factory has resolved separate input/output request-byte
limits, when it receives the production HttpxJevTransport, each backend receives a
separate transport with exactly that backend's resolved limit. A shared original
transport remains unchanged. Custom callables and custom HTTP subclasses retain their
identity and behavior. No request, client, credential discovery, or provider call is
created by assembly.

The transport's standalone/probe default remains 32,768 bytes. Explicit limits must
be exact integers from 1,024 through the existing absolute ceiling of 131,072 bytes;
booleans, floats, non-finite values and out-of-range values fail before HTTP. At the
chosen limit the original UTF-8 bytes are dispatched once; one byte above is rejected
before HTTP. No context normalization, response ceiling, request count, probability,
confidence, semantic policy, consent, retry or application default changes.

Given the built-in story and actual renderer readiness after five synthetic ordinary
chat turns, a trip_photo candidate generates a 13,449-byte input review and a
33,692-byte output review. With existing application/story defaults (32/64 KiB),
both reviews traverse the production HTTP transport with HTTPX MockTransport and the
real JEV parser. The Actor grants the photo only for a valid allow response; reject,
unknown, malformed, oversized-response and local oversize controls hold the photo
while retaining the ordinary subtitle. A presentation fact requires a software
receipt. This synthetic reproduction does not identify the cause of every device
error or establish real provider, photo visibility, TTS or user acceptance.

Owner/consumers: providers owns tests/contracts/test_jev_transport_request_limits.py
through the existing tests/quality.toml contract glob; bootstrap consumers are
development, voice and direct-provider composition. Related affected lanes are
architecture, config, env, actor, providers, http and specs/tooling. Resource budget:
offline HTTPX mocks only, no provider/network calls, no new dependencies or credentials.
Baseline: immutable source-2030 restored at 2026-10-05T22:17Z; new isolated stage
mira-jev-limit-next-20261005T2232Z. External append-only evidence records actual RED/GREEN.
