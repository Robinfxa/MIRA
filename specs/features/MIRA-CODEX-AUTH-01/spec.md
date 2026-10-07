# MIRA-CODEX-AUTH-01: MIRA-owned Codex subscription login

## Scope and constraints

This slice adds a user-operated OAuth device-code login and a separate MIRA-owned
local session store for the private Codex subscription backend. It is distinct from
the public OpenAI API-key route. It is default-off and must never fall back to an
API key or another provider. No login, grant, refresh, token discovery, model
request, or credential read may happen at import time or during status/check-only
operations.

The subscription endpoint is private and is not an official public OpenAI API v1
contract. Applicable terms, quota, account eligibility, and live compatibility are
not established by this offline implementation. A user must explicitly start and
approve sign-in in the standalone CLI. There is no automated browser opening or
automatic new grant retry.

## Given / When / Then

- Given no MIRA session, when the auth module is imported or local status is read,
  then there is no network request, auth-file discovery, filesystem read at import,
  or false authenticated state.
- Given explicit `login` and typed local consent, when the user completes the
  fixed device-code flow, then the one-time code is displayed only to that CLI and
  a validated token pair is written only to MIRA's private app directory.
- Given device flow pending, `slow_down`, user denial, expiry, malformed response,
  HTTP error, or cancellation, when login stops, then no new session is persisted
  and no hidden retry starts another grant.
- Given an expired MIRA session, when the explicitly selected subscription route
  requests credentials, then one serialized refresh uses the fixed token endpoint;
  any rotated refresh token and expiry are atomically persisted before credentials
  are returned.
- Given two concurrent callers with one expiring session, when both request
  credentials, then cross-process locking causes only one refresh and both receive
  the newly persisted access token.
- Given a missing, malformed, overly permissive, or unsupported MIRA store, when
  credentials are requested, then the adapter fails closed without exposing token
  contents or silently discovering another store.
- Given explicit local logout, when the user confirms, then the MIRA active state
  is invalidated while a private recoverable backup remains. Provider revocation is
  never claimed. A separate explicit forget action removes only MIRA's files.
- Given a redirect from an OAuth endpoint, when the client receives it, then the
  response is rejected and the authorization code or refresh token is never sent
  to another host.

### MIRACODEXAUTH01-001

Import and local status remain offline and do not produce a false authenticated state.

### MIRACODEXAUTH01-002

An explicitly approved device-code login persists only a validated MIRA-owned session.

### MIRACODEXAUTH01-003

Pending, slow-down, denied, expired, timed-out, malformed, failed, and cancelled login
states fail closed without an implicit new grant.

### MIRACODEXAUTH01-004

Expired session refresh serializes, supports rotation, and persists before return.

### MIRACODEXAUTH01-005

Concurrent credential requests share a single cross-process refresh.

### MIRACODEXAUTH01-006

Invalid or insufficiently private session state does not expose secrets or fall back.

### MIRACODEXAUTH01-007

Local sign-out invalidates only MIRA's active state and preserves explicit recovery.

### MIRACODEXAUTH01-008

OAuth redirects are rejected before an authorization code or refresh token can reach
another host.

## Ports and consumer

- Auth adapter: `CodexCredentialSource.get_credentials() -> CodexOAuthCredentials`
- Bundle fields: redacted `SecretStr access_token`, optional account/residency
  metadata. The generation backend receives only this source and never reads auth
  files.
- Consumer: explicit direct subscription generation selection (separate from API
  key selection); runtime composition remains owned by the integration owner.

## Test owner and resources

- Unique test owner: `tests/contracts/test_codex_subscription_auth.py`
- Quality lane: `providers`
- External resources: none. HTTPX MockTransport and synthetic tokens only.
- Scope excludes provider account calls, real OAuth grants, live model requests,
  desktop/UI login, provider revocation, and terms/legal approval.
