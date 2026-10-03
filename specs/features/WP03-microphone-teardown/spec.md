# WP03-MIC microphone cancellation teardown

Scope: HTTP microphone teardown and the existing media operation lifecycle; no
Actor transition, semantic review, provider selection, persistence, or wire changes.
Common baseline: ebb578dde665c9c7269e4a64b508182680b2fa66 (no Git execution).
Owner: providers, via the existing tests/contracts/test_*.py unique-owner glob.
Consumers: HTTP voice, Actor/session close, architecture/import boundaries.
Resources: installed .venv313, in-process synthetic providers and WebSocket stub;
no network listener, live providers, credentials, browser, or device claims.
The integration owner runs affected/full/release; directed checks retain unique receipts.

### WP03MIC-001 Immediate invalidation
Given queued raw microphone audio and a reader/sender whose cancellation cleanup
is suspended at an Event barrier, When disconnect, cancel, request cancellation,
or Actor Stop occurs, Then the operation is invalidated and queued raw audio is
cleared before any cancellable teardown await. Finish alone still drains.

### WP03MIC-002 Cancellation-safe ownership
Given teardown awaits or an uncooperative iterator, When outer request cancellation
repeats, Then bounded teardown cannot strand unowned tasks, cancellation causes
remain intact, and late output cannot be published. Media capacity remains charged
until producer and owned socket consumers terminate, then is released.

### WP03MIC-003 Session shutdown
Given pending microphone work, When the session closes, Then the same synchronous
invalidation applies, raw audio is cleared, and bounded cleanup retains/reaps any
uncooperative work without creating another authority or generic task manager.

Historical failure retained: docs/verification/http-01-portable-openapi/003-consumers-20261003t1139z/http/stdout.txt.
