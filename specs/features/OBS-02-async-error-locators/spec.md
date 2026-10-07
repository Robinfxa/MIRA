# OBS-02 — Async error diagnostic locators

Owner: assigned async error worker; narrow shared transition/schema edits released by director.
Baseline: director-frozen 20261003T1158Z source; no Git operation needed in this slice.
Test blocks: providers (`tests/contracts/test_async_error_locators.py`), web (`tests/web/error-locators.test.mjs`).
Consumers: domain, Actor, diagnostic sanitizer, HTTP/media DTO exports and actual browser controller/main.
Resources: existing Python 3.13, TypeScript and Node; synthetic ASGI/socket/DOM only. No live services,
credentials, browser, installation or publication. Director owns coherent release on a frozen copy.

### OBS02-001 — Exact async origin
Given generation or review fails after input HTTP success, when the error snapshot is polled,
then active request authority is null and an immutable diagnostic locator matches the originating
request's sanitized log context, never the input command UUID or later poll request.
Absent/malformed diagnostic origin yields null; no artificial linkage is created.

### OBS02-002 — Media correlation
Given TTS, STT or a reported playback failure with an existing request diagnostic context,
when the typed stream/error snapshot is emitted, then its safe locator matches a real diagnostic
event's context. Provider text, headers, keys and dialogue are never reflected.

### OBS02-003 — Stale and safe presentation
Given Stop or new input, prior error metadata clears; late generation/media/errors cannot replace
new-turn state. The actual main/controller/API and stream paths retain actionable Chinese copy
and validated locator; malformed, inherited/prototype and unknown ID values cannot be reflected.

### OBS02-004 — JEV output-format failure diagnostics
Given the local ASGI path has received a valid input observation and a bounded output-review
response returns HTTP 200 with an invalid probability contract, when the existing parser rejects
that response, then the response remains UNKNOWN and fail-closed, no candidate is presented or
retried, the session exposes `invalid_response`, and its diagnostic ID locates the failed
`output_review` event. That existing local event/export may contain only fixed parser categories,
bounded sizes/counts/numeric ranges and an optional response digest. It never contains provider
body text, field names, headers, credentials, or arbitrary strings. Per-question facts use only
the fixed JEV suffix (`o1`–`o6`, `effect_0`–`effect_7`) and retain bounded observed values such as
the selected probability and an out-of-tolerance sum without rounding or normalizing them.
Summary/recording failures do not affect rejection of the candidate. The parser and decision
thresholds remain unchanged.

### OBS02-005 — Semantic uncertainty stays distinct
Given an otherwise valid output review returns semantic REJECT or a fixed semantic UNKNOWN,
when the Actor records the result, REJECT exposes `review_not_allowed` and only the explicit
semantic UNKNOWN reasons (`jev_semantic_unknown`, the selected development-policy UNKNOWN, or
propagated `jev_input_semantic_unknown`) expose `review_uncertain`. The uncertainty copy says
the response could not be confirmed, not that the user content was definitively rejected.
Neither result grants a permit. Contract, snapshot, calibration/configuration, invalid-response,
transport, resource-limit, or unrecognized UNKNOWN reasons remain on their ordinary fail-closed
error paths; they are not presented as normal ambiguity or retried.

The matching browser-copy assertion is separate from Python traceability:
`tests/web/error-locators.test.mjs` test “invalid provider response and uncertain review have separate safe copy”.
