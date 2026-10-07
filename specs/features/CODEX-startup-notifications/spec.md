# Bounded official Codex startup notifications

Scope: metadata-only public setup on pinned Codex0.159.2. This slice never starts a native process in its tests and does not establish the cause of the user's Mac RPC failure. Existing binary/home/path checks, exact RPC sequence and effective-config isolation remain mandatory.

### CODEXSTARTUPNOTIFICATIONS-001: Supported startup only

After a validated initialize response and sending initialized, schema-valid configWarning and deprecationNotice notifications may be discarded while awaiting config/read. Before initialize completion, or for any other notification/server request, fail closed. No warning grants permission or substitutes for the effective-config check.
### CODEXSTARTUPNOTIFICATIONS-002: Safe diagnostics and strict schemas

Keep only fixed method/count facts. Never expose or persist warning text, paths, ranges, error payloads or credentials. Retain bounded RPC numeric error/phase diagnostics. Unknown/extra fields, invalid types, malformed JSON and unsolicited responses remain rejected.
### CODEXSTARTUPNOTIFICATIONS-003: Bounded reception and cleanup

At most16 startup notices,32KiB per notice,128KiB total notices,128KiB per line and1MiB total response wire. The original overall deadline is not reset by notices. Every success/failure/timeout closes the existing owned transport; there are no retries or additional outgoing RPC methods.

Quality owner: providers via tests/contracts/*.py; tooling owns the existing CLI helper. Consumers: MetadataOnlyTransport, prepare_runtime_admission.py. Shared schema owner unchanged; no HTTP protocol change or new dependency.

## Upstream basis

The exact tagged initialize processor emits config warnings after the initialize response. The pinned common protocol defines both notification names and an optional signed64-bit emittedAtMs envelope field. ConfigWarning has summary, optional details/path/range; range uses start/end line/column positions. DeprecationNotice has summary and optional details. Local additional bounds are explicit resource limits, not upstream guarantees.

- https://raw.githubusercontent.com/openai/codex/rust-v0.159.2/codex-rs/app-server/src/request_processors/initialize_processor.rs
- https://raw.githubusercontent.com/openai/codex/rust-v0.159.2/codex-rs/app-server-protocol/src/protocol/common.rs
- https://raw.githubusercontent.com/openai/codex/rust-v0.159.2/codex-rs/app-server-protocol/src/protocol/v2/config.rs
- https://raw.githubusercontent.com/openai/codex/rust-v0.159.2/codex-rs/app-server-protocol/src/protocol/v2/notification.rs
