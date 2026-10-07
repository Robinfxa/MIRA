# M06 local operator pairing gate for memory mode

Scope: a memory-only browser page marked by the backend must wait for an ephemeral local operator pairing before constructing the session controller, diagnostics watcher, or private API client. Pairing uses a manually entered one-time code in a password-style input and an HttpOnly same-origin application cookie. No code or browser-owned cookie is placed in URLs, browser storage, clipboard access, or UI diagnostics. Non-memory page behavior remains unchanged.

Owner: `tests/quality.toml` already assigns `tests/web/*.test.mjs` uniquely to the `web` lane. The Node-specific behavior map is in `traceability-web.json`; `tools/check_specs.py` accepts collected pytest node IDs only and does not validate this sidecar. Tests use fake DOM/fetch only; no real browser, localhost service, provider, or real credential is used.

### M06OP-001 Pair before private session work

Given a memory-mode page whose body has the exact `data-operator-pairing="required"` marker, perform only the same-origin public operator status GET until the backend confirms the browser's included operator app cookie is paired to this process. Without a valid cookie the backend reports `paired: false`; an old cookie from another process cannot unlock the UI. Do not construct or connect the private session API/controller or diagnostics watcher before successful pairing. Pair using POST `/api/v1/operator/pair` with JSON `{code}`, same-origin credentials, and require HTTP 204 before continuing. The public status response is accepted only when it contains exactly `required`, `paired`, and `revoked`, all booleans. Pages without the marker retain the existing session-start path.

### M06OP-002 Keep the pairing code ephemeral and quiet

Given the pairing form, show clear instructions to personally read the private local pairing file on every launch. Use a password-style input with autocomplete off; clear its value synchronously before sending, on failures, and after success. Never echo the code or inspect a pair/revoke response body. Use fixed same-origin routes with credentials included, cache disabled, and bounded aborts. Do not inspect location, URL fragments, local/session storage, or clipboard. HTTP failures must not show a fake paired state, echo response contents, or trigger an automatic retry. A revoked code requires a fresh local launch and pairing file.

### M06OP-003 Fence close and revocation against late pairing

Given an in-flight or paired memory-mode page, closing/cancelling must fence all later pairing results so they cannot unlock the UI. When paired, request local controller stop and close before POSTing `/api/v1/operator/revoke` with the same-origin app cookie. During an in-flight pair, revoke is attempted after the pending result settles, without invoking the private app startup callback. The pairing cookie is browser-managed and never copied into JavaScript storage or session tokens.
