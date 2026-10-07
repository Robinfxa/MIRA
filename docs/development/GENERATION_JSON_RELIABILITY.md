# Generation JSON reliability review — 2026-10-05

## Observed failure and current evidence boundary

The reported user failure had HTTP 200, 44 SSE events, a completed terminal, one final
message, one delta message, an empty terminal snapshot, and a 147-byte candidate that
failed with `codex_json_invalid`. The candidate itself is unavailable. These facts do
not determine whether it contained a fence, malformed quoting, duplicate keys, a
nonfinite constant, or another rejected JSON form. No post-0703 diagnostic export has
been examined in this review. The original cause remains unknown.

The 0703 parser already carries closed `json_failure_kind` and `wrapper_shape` facts.
The latter describes a lexical prefix, not validated JSON or a repair instruction.
A future export from a build containing that classifier can narrow the failure without
retaining candidate text. Raw bodies, exception messages, key names and content hashes
are unnecessary for the next diagnostic step.

## Confirmed, separate local validation defect

Three synthetic, story-enabled candidates exposed a different defect after successful
JSON decoding:

- A numeric overflow (`1e999`) in an effect value was reported as transport unavailable.
- The same overflow in a proposal was reported as transport unavailable.
- An escaped unpaired Unicode surrogate in text was reported as an SSE failure.

These inputs were already rejected. Their errors occurred while validating decoded
candidate values, after HTTP/SSE completion. A catch around only candidate parsing now
maps ValueError (including UnicodeError) and TypeError to `invalid_response`, phase
`validation`, reason `candidate_value_invalid`. The JSON-failure fields remain null
because these examples are not failures in the strict JSON decoder. No text is repaired,
no malformed candidate is accepted, and no retry or second request is added.

The original strict-JSON classifications remain unchanged. Synthetic connection failures,
malformed SSE JSON, and invalid SSE UTF-8 retain their original stages and reasons.
This correction is not a claim to have identified or fixed the unseen 147-byte candidate.

## Reproducible application recovery

`test_direct_generation_validation_recovery.py` uses the real direct HTTP adapter,
production ASGI app and Actor, actual JEV response parser, authenticated presentation
receipts, synthetic audio transport, and ordinary diagnostic export. Its synthetic wire
contains 44 events, one final message and one matching delta, followed by an empty
subscription terminal snapshot. Only the metadata shape resembles the observed failure;
the test content is explicitly invented and does not reconstruct that private response.

The matrix covers syntax, duplicate keys, nonfinite constants, Markdown fences and the
three local-value examples. Each failed turn has no grants and no TTS or JEV call. A
second, independently submitted input succeeds without restarting the session. Voice
cases open the authenticated microphone WebSocket, receive a synthetic STT transcript,
and verify that recognition alone makes no generation request before explicit submission. Reliable
user input survives; failed generated content never enters presented history. Text can
receive its own presentation receipt. Permitted speech returns synthetic PCM; uncertain
speech permission retains the separate text grant and makes no TTS call. This establishes
software recovery, not real model quality, browser playback, microphone or physical hearing.

## Prompt and capability review

The request carries one fixed JSON-object instruction. First-person character guidance
constrains the speech/subtitle values; it does not ask for free text outside the object.
Text-only mode explicitly forbids speech. Voice mode allows at most one speech cue and
requires a separately authored corresponding subtitle. Story suggestions are separate
optional object fields, and the parser admits them only with story context. These rules
are consistent; this review found no concrete contradiction warranting a prompt rewrite.
The existing finite effects, value, output and event limits remain authoritative.

## Official API option, kept separate from subscription

Official Responses supports `text.format` with `type: json_schema`, a schema name and
`strict: true`. Its schema subset requires every property to be required; optional values
can be represented with null. Refusal and incomplete responses still require handling.
JSON mode (`json_object`) constrains JSON syntax but does not enforce the application
schema. See the [official Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
The [official GPT-6 Luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna)
currently lists Structured Outputs as supported. This does not establish any account's
access, quota, or entitlement.

A separate implementation proposal for an explicitly selected public API route is:

1. Add an explicit API-only Structured Outputs option; keep the existing subscription
   request body unchanged. Do not silently switch routes, billing, model or formats.
2. Build the schema from the same capability/context inputs as candidate validation.
   The existing legacy `output_schema()` cannot be copied unchanged: it omits story and
   affect proposals and the additional character poses admitted in story mode. Proposed
   nullable story/affect properties fit the parser's existing top-level null handling.
   Keep every schema object closed with `additionalProperties: false`.
3. Test schema/request shape separately for text, voice and story combinations; retain
   all local cue-count, byte-size, ID-binding, capability and permission checks. Provider
   schema conformance is not application approval or semantic review.
4. Verify refusal, incomplete, malformed and unsupported-schema responses fail closed
   with one request. Never retry with a weaker format or silently drop the schema.
5. Keep any live validation, API credential use and spend separately authorized. An
   offline mock cannot prove the selected account/provider honors the format.

The cited public API documentation does not establish support for those fields at the
private subscription endpoint used in the reported failure. This slice adds no request
fields on either route and performs no live call. A small prompt-format experiment may
be considered after new diagnostic evidence identifies a formatting failure, but it is
not a substitute for that evidence and is not included here.

## Exact evidence still needed for the reported failure

When the operator next chooses to run an admitted turn, preserve the ordinary sanitized
export and its build identity. The relevant generation-failed record should include:

- `phase`, `reason`, `json_failure_kind`, `wrapper_shape`, and HTTP/terminal status
- Event count/classes, completed and delta counts, candidate byte count, snapshot shape,
  and any existing terminal-compatibility class
- Existing hashed session/request/turn correlations, so a subsequent independent turn
  can be checked for success without confusing it with an automatic retry

Missing or null classification in an older export cannot retrospectively establish the
syntax failure. No raw candidate, private utterance, authentication file or token is
requested by this review. Until newer evidence exists, the appropriate product statement
is that diagnostics and recovery are verified synthetically and the original live cause
is unresolved.
