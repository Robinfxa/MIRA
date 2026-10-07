# Local operator boundary for explicitly enabled memory

### M06PAIR-001: No private reads before operator authorization
Memory mode requires an explicit app-bound pairing capability. Without a valid
one-use code from the private per-launch file, private API/session/diagnostics/
recording/media/WS access is blocked and the memory factory is not called.
Ordinary non-memory behavior remains unchanged.

### M06PAIR-002: Browser-origin and session binding
Pairing requires exact allowed Origin and Host and a bounded strong code. It
issues an opaque HttpOnly SameSite=Strict cookie for one app and one browser
origin. Private mutations require Origin; safe browser GET without Origin must
have same-origin Fetch-Metadata or a matching Referer. The public status only
reports this requester's valid pairing. A separate session bearer remains
required. Wrong code/Origin/Host, replay, expiry, exhaustion and another app or
browser fail closed. Invalid request bodies and logs never echo the code.

### M06PAIR-003: Revocation and bounded lifecycle
Explicit revoke and app shutdown invalidate pairing and close sessions/readers.
Stop cancels current work without changing operator authorization. Startup
failure revokes the consumed code. A late cancellation-resistant factory result
is disposed rather than attached to the app. No automatic re-pairing, provider
retry, memory recording, grant inheritance, or OS-permission change occurs.

## Threat model and evidence scope
This is a localhost capability, not proof of OS identity or multi-user login.
Same-user malicious code, a compromised browser, or anyone reading the private
code file can act as the operator. Tests use synthetic codes and data only;
no real credentials or stored user data have been created or transmitted.
