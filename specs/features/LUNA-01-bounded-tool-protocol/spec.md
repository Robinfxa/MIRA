# LUNA-01 Bounded Responses tool protocol

## Scope

Adapter-owned, ephemeral two-request tool turn. The application owns definitions, execution,
truthful results and current context. No callbacks execute tools inside the transport.
Base: frozen 0221 source capture manifest SHA256
22a4f2e26a113fdc5ed88419596a2444a83261e2747cf25d632cdb87145fb686.

## Requirements

### LUNA01-001

Given explicit tools, when a complete Responses function_call terminates successfully, return the exact call ID and strictly bounded validated arguments. Deltas, incomplete, conflicting, duplicate or unknown calls never execute.
### LUNA01-002

Given the application result, continue once with the original reasoning items and function call, a call-ID-matched function_call_output, and fresh context. Require text-only subtitle/speech candidates, disable all tools, and never retry, fall back routes or make a third request.
### LUNA01-003

Given finite request allowance and turn deadline, reserve continuation capacity before returning a call. Count each real request with the existing counter. Cancellation, close, errors and ordinary text release unused capacity and clear ephemeral protocol data.
### LUNA01-004

Given existing subscription/API authentication and response guards, preserve them. Existing generate remains available. Tool arguments <=8192 bytes, result <=2048 bytes, definitions <=16384 bytes; full retained wire and requests remain bounded by existing limits. No raw provider text, IDs, arguments or reasoning in safe diagnostics.

The native first response requests dialogue only. Every action, outfit, accessory,
expression, scene and chapter plan requires a real function call. Received strict legal
dialogue plus recognized old pose/scene/story/affect fields retains that dialogue while
holding every legacy side effect with closed diagnostics. Unknown envelopes, malformed
JSON and media/image bypasses still fail. Explicit native_character_tools=False restores
the legacy schema/parser only for the selected legacy review mode. Call commentary and
continuations are always inert dialogue; mixed tool calls/proposals cannot execute.

### LUNA01-005

Given a completed text message rejected by candidate validation in the first ordinary
response, final continuation, or complete call commentary, preserve the same closed
reason and JSON failure/wrapper classes as the existing non-tool generation route.
Preserve strict rejection, consumed request counts, cleanup and one-continuation bounds.
No provider text, parser exception text, body hashes or new raw-recording fields enter
diagnostics. Transport and terminal failures retain their original stages. This narrows
future diagnosis; it does not reconstruct redacted content from prior exports.

### LUNA01-006

Given any default direct tool-turn request, request Responses text.format with type
json_schema, strict=true and an object-root schema matching the current candidate
vocabulary. Native first responses and final continuations declare only subtitle and
admitted speech. Every object disallows extra properties and requires declared properties.
Known legacy optional fields received beside valid ordinary dialogue are held, never
executed or renamed into a tool. Accompanying function-call commentary remains strict
text-only, and is available to the Actor before optional execution and continuation.
The explicitly selected legacy adapter retains its nullable proposal schema and parser.

Given a server rejecting text.format or returning non-JSON despite it, keep the distinct
HTTP/validation failure and make no retry, raw-text fallback or API route switch. Ordinary
chat remains one request; a tool turn remains at most two. No real subscription-account
compatibility or model-quality result is inferred from synthetic tests.

## Given / When / Then

Tests cover actual synthetic SSE and outgoing HTTP bodies for both fixed endpoints,
ordinary text, application-owned dynamic fictional brief, matching output IDs, preserved
reasoning, duplicate calls, delta conflicts, missing done/terminal, changed snapshots,
continuation tools/proposals, capacity, timeout, cancellation and cleanup.

## Ownership, consumers and resources

Owned writes: direct_codex_responses.py, direct_tools.py, contract tests and this spec.
Consumer: application per-turn tool port and Actor operation/result bridge.
Unique test owner: providers via tests/contracts/test_*.py in tests/quality.toml.
Affected lanes: providers/config/actor/http/continuous plus architecture/specs/tooling.
Shared port is supplied by integration owner. No network/account/device calls, credentials,
new dependency, persistent agent framework or broader image budgets.

## Evidence and limits

RED/GREEN and affected evidence are external to source. Synthetic protocol acceptance is
not proof of account access, subscription endpoint compatibility or real model behavior.
Official reference: https://developers.openai.com/api/docs/guides/function-calling
Pinned first-party Codex source: 4d15794336668d6098c0e36eb8e96cbbbfdb1d2d,
protocol/src/models.rs FunctionCall/FunctionCallOutput and SSE output_item.done handling.

For LUNA01-006, the Responses structured-output guide documents object roots, nested
anyOf, required nullable properties and additionalProperties=false:
https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses
First-party source read on2026-10-06 shows text and tools in the same ResponsesApiRequest,
and create_text_param_for_request converts an output schema into strict json_schema:
https://github.com/openai/codex/blob/main/codex-rs/codex-api/src/common.rs
https://github.com/openai/codex/blob/main/codex-rs/core/src/client.rs
This establishes a first-party wire convention, not access or behavior of a particular
subscription account. Source retrieval and focused RED/GREEN evidence are recorded in
the handoff; existing prompt-only legacy generate is outside this narrow tool-route patch.
