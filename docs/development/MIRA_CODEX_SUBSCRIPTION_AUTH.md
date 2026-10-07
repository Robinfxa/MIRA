# MIRA Codex subscription login (experimental, default off)

MIRA keeps subscription OAuth in its own private store. This direct subscription
route is separate from the public OpenAI API-key route. It never falls back to an
API key, the Codex CLI, Hermes, or another provider. Importing MIRA's auth module,
starting the usual offline demo, and reading local status do not start a login or
provider request.

The current direct route targets a private subscription backend and is not an
official public OpenAI API v1 contract. This implementation does not establish
applicable terms, quota, account eligibility, model availability, or live
compatibility. Do not represent any of those as verified. There is no live OAuth,
subscription, or model request in the synthetic test suite.

## User-operated controls

Run from the project root:

```sh
python tools/provider_login.py --help
python tools/provider_login.py login
python tools/provider_login.py --auth-store /path/to/mira-session.json login
python tools/provider_login.py status
python tools/provider_login.py logout
python tools/provider_login.py restore-backup
python tools/provider_login.py forget
```

`login` prints the warning first and requires the user to type `LOGIN`. It then
requests a device code from fixed OAuth endpoints, shows the one-time code and
official verification URL in that terminal only, and waits for the user's approval.
The optional `--auth-store` (alias `--store`) selects a MIRA-owned session path for
the user-operated CLI and can match the direct provider's configured auth-store path.
The CLI never opens a browser automatically. Pressing Ctrl+C cancels the local poll;
it does not revoke an already approved grant. Tokens are saved only after the token
response validates. HTTP errors and logs contain fixed safe error codes, not response
bodies, headers, device codes, or tokens.

`status` reads only the active MIRA-owned store and does not refresh or discover
credentials. `logout` locally marks only MIRA's active state signed out, after a
typed confirmation; a private recoverable backup remains. The backup is never used
automatically. `restore-backup` requires a separate typed confirmation. `forget`
requires typing `DELETE` and removes only MIRA's active store and backup. None of
these commands calls a provider revoke endpoint or claims to revoke provider-side
tokens.

## Storage and refresh

The CLI and `CodexOAuthCredentialSource` share a MIRA-owned app-private path outside
the checkout:

- macOS: `~/Library/Application Support/MIRA/auth/openai-codex-session.json`
- Windows: `~/AppData/Local/MIRA/auth/openai-codex-session.json`
- Linux/other POSIX: `~/.local/share/mira/auth/openai-codex-session.json`

POSIX app-auth directories and files are created owner-private (`0700` / `0600`);
an existing permissive directory/file is rejected rather than chmod'ed. Windows
inherits the current user's profile ACL and has not been independently validated.
The store uses a cross-process lock and same-directory atomic replacements. A backup
of the current validated pair is retained for explicit recovery, including when a
refresh rotates the refresh token. A signed-out primary record is authoritative;
the backup cannot silently restore an authenticated status.

Refreshing is lazy and occurs only when the direct subscription route explicitly
calls `get_credentials()`. It is serialized under the MIRA-owned file lock, uses a
120-second expiry margin, persists any returned rotated refresh token before
returning the access token, and does not start a fresh grant after refresh failure.
The returned access token is a redacted `SecretStr`; the response adapter receives
the provider interface, never a path or raw headers.

The auth adapter extracts only the optional `chatgpt_account_id` and data/compute
residency request metadata from the access-token JWT namespace
`https://api.openai.com/auth`. This is decoded without signature verification and
does not validate a user, account, token, plan, or permission; the backend remains
the token validator. Missing/malformed optional claims are omitted.

## Public source evidence

The pinned Hermes review snapshot is `439334127f012e1ee0685acd5dba288e459af0ec`.
It was used as interface evidence only; MIRA implements its own user flow, storage,
error boundaries and tests. Relevant source references:

- [Pinned Hermes OAuth constants](https://github.com/NousResearch/hermes-agent/blob/439334127f012e1ee0685acd5dba288e459af0ec/hermes_cli/auth_constants.py#L71-L93)
- [Pinned Hermes Codex OAuth lifecycle](https://github.com/NousResearch/hermes-agent/blob/439334127f012e1ee0685acd5dba288e459af0ec/hermes_cli/auth_codex.py)
- [Pinned Hermes provider login selection](https://github.com/NousResearch/hermes-agent/blob/439334127f012e1ee0685acd5dba288e459af0ec/hermes_cli/auth_codex.py#L943-L980)
- [Pinned Hermes refresh and rotated-token persistence](https://github.com/NousResearch/hermes-agent/blob/439334127f012e1ee0685acd5dba288e459af0ec/hermes_cli/auth_codex.py#L480-L515)
- [Pinned Hermes account/residency header contract](https://github.com/NousResearch/hermes-agent/blob/439334127f012e1ee0685acd5dba288e459af0ec/agent/codex_headers.py#L34-L80)

The implementation uses the reviewed public client ID and fixed `auth.openai.com`
device-code, token, and verification endpoints. MIRA does not adopt Hermes' identity,
store, session, default user agent, CLI credential import path, or app-server flow.
