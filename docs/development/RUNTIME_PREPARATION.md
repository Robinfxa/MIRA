# Prepare a local public Codex runtime

MIRA's regular text-development entry reads a private admission file generated from your own official Codex installation and current local policy environment. The helper does not ask you to handwrite config hashes, copy cloud paths, copy login files, or supply a JEV key. It never reads `.env` or the JEV key; MIRA's normal local configuration loader handles Google and JEV settings when the app runs.

The no-argument command is inert:

```bash
python tools/prepare_runtime_admission.py
```

It reports `unarmed` and does not start Codex. `--help` only shows options. The explicit `--prepare` path starts the pinned native app-server and may cause ordinary account/catalog metadata traffic. It sends only initialize and config-read protocol messages; it performs no account lookup, model turn, tool call, or inference. This is a metadata setup action, not an offline configuration check.

Before any metadata request, the command requires both `--confirm-policy-environment` and `--authorize-codex-and-jev-content`, plus caller-selected finite request ceilings. The policy confirmation records that the applicable local proxy/certificate policy is understood. The separate content authorization acknowledges that later MIRA text entry sends entered dialogue and relevant prior application context to native Codex/OpenAI and TypeSafe/JEV, and sends the generated candidate to TypeSafe/JEV. JEV requests may be billable. The displayed request and turn ceilings are request counts, not dollar caps; they are enforced per app invocation in memory, so restarting the app with the same admission begins a fresh allowance. They are not a durable cross-restart ledger. MIRA does not send workspace files or authentication files through this workflow.

The default `probe` usage profile keeps the historical request and session-turn
maximums at 8. An application that needs longer sessions may explicitly prepare an
`application` admission with `--usage-profile application`; this permits caller-set
finite request ceilings from 1 to 100 and session turns from 1 to 100. Each exact
ceiling is still required, the Codex request ceiling cannot exceed session turns,
and the metadata-probe timeout and protocol limits do not change. No value means
unlimited. Newly written admissions state their profile; a legacy admission without
that field is read as `probe` and cannot silently inherit application limits.

Example one-time preparation:

```bash
runtime_cwd="$(mktemp -d "$HOME/mira-codex-runtime.XXXXXX")"
python tools/prepare_runtime_admission.py \
  --prepare \
  --usage-profile probe \
  --runtime-cwd "$runtime_cwd" \
  --codex-requests 2 \
  --session-turns 2 \
  --input-jev-requests 3 \
  --output-jev-requests 3 \
  --input-jev-timeout-seconds 10 \
  --output-jev-timeout-seconds 10 \
  --probe-timeout-seconds 10 \
  --confirm-policy-environment \
  --authorize-codex-and-jev-content \
  --write-admission "$HOME/mira-runtime-admission.json"
```

For a longer app invocation, explicitly choose `--usage-profile application` and
choose finite counts no greater than 100. This profile affects the later app's
in-memory request/turn ceilings only; it does not alter cloud probe ledgers, add a
provider request during preparation, or establish a billing cap.

The helper finds `codex` on `PATH`, uses `CODEX_HOME` or `~/.codex`, and accepts explicit `--codex` and `--codex-home` paths if needed. It supports only these exact official native Codex CLI 0.159.2 builds: Linux x86_64, macOS arm64, and macOS x86_64. It selects the pin from current runtime OS/machine facts and checks the executable bytes; caller flags and environment values cannot choose another digest. When the selected command is the recognized official `@openai/codex/bin/codex.js` npm wrapper, the helper inspects only the exact host-specific nested and hoisted optional-package locations and selects a unique matching native binary. A bounded ordinary symlink to that wrapper is allowed. The wrapper and package scripts are never run, and no other package layout is guessed. Missing, ambiguous, changed, wrong-platform, or unsafe native candidates fail closed with a fixed reason. A matching native blocked by existing filesystem permissions is reported separately so the user can distinguish it from a missing install. The helper does not copy binaries, change permissions, search the filesystem, update or re-pin versions, or read Codex home contents. Windows and Linux arm64 are not supported by the pinned release.

The 2026-10-04 macOS pins were derived from the exact OpenAI 0.159.2 release assets and published archive SHA-256 values. See [Codex platform pin provenance](CODEX_PLATFORM_PIN_PROVENANCE.md) for artifact IDs and local verification steps. The frozen 09:52 delivery remains Linux-only; use a matching later source/package for this extension, and do not copy only the new helper into the frozen package. The published asset/archive identity and software guards are verified; Mac native launch, metadata handshake, login, and model inference have not been run.

The runtime working directory must already exist, be private, and be empty. The output path must be absolute, new, outside the repository, and under existing safe directories. The helper creates only the new JSON file with mode 0600; it does not change directory modes, login state, settings, or grants. API-key and provider-route override environment variables fail by name-presence check, and their values are never inspected or printed. Proxy entries containing user information, query strings, or fragments are rejected.

The resulting public admission uses `route_kind=public` and `development_context=null`, and stores the exact config digest and selected non-secret runtime environment. Fingerprints and pinned-version checks describe observed metadata only. A successful declaration does not establish account entitlement, available quota, inference readiness, or dollar spend limits.

## Pinned startup warnings

The metadata-only reader accepts only the pinned `configWarning` and
`deprecationNotice` schemas while waiting for `config/read`, after initialization
has completed. Their text and paths are discarded; output contains only method
counts. The effective configuration still has to pass every isolation check.
Sixteen notices, 32KiB per notice and 128KiB total notice data are hard limits;
the existing overall timeout is unchanged. Unknown notifications, server requests,
RPC errors and schema drift still block preparation. See
[the versioned startup contract](../../specs/features/CODEX-startup-notifications/spec.md).

This fixes a reproducible mismatch with a supported official startup sequence.
It does not prove that such a warning caused the user's earlier Mac failure;
the actual sanitized envelope diagnosis and unified Mac acceptance remain open.

The npm auto-discovery support list currently covers the two macOS layouts. The official0.159.2 wrapper also defines Linux optional packages, but this helper has not admitted those package artifacts for automatic discovery. Linux callers can still explicitly select the existing pinned native binary. See the [official wrapper source](https://github.com/openai/codex/blob/rust-v0.159.2/codex-cli/bin/codex.js). This corrects an inaccurate Linux-package comment preserved in the immutable1845 capture; no executable pin or permission policy changes here.
