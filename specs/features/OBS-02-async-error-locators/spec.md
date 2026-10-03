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
