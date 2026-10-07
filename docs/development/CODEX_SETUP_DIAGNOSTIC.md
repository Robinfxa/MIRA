# Offline Codex setup diagnostic

This standalone tool diagnoses selected filesystem metadata for a Codex CLI
installation. It is read-only and offline. It never launches Codex or JavaScript,
calls npm, reads Codex settings/authentication files, changes permissions, copies
files, or installs anything. It does not consult `PATH`, `HOME`, or other
environment variables. With no explicit arguments it reports that it did no
inspection.

Run it from this checkout with explicit paths. Point `runtime_cwd` to an
existing empty private directory that you selected for Codex. The checkout or
`$PWD` is usually nonempty and is not a suitable runtime cwd:

```sh
runtime_cwd='/absolute/path/to/empty-private-runtime-dir'
python3 tools/codex_setup_diagnose.py \
  --executable '/usr/local/lib/node_modules/@openai/codex/bin/codex.js' \
  --codex-home "$HOME/.codex" \
  --runtime-cwd "$runtime_cwd"
```

You can select the native file directly instead of the JavaScript wrapper. For
an Intel Mac using the nested npm optional dependency, that path has this shape:

```text
/usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-darwin-x64/vendor/x86_64-apple-darwin/bin/codex
```

The wrapper recognizer only matches the known `@openai/codex/bin/codex.js`
layout and checks two exact optional-dependency locations (nested or hoisted).
It does not inspect wrapper contents, follow package scripts, or search the
filesystem. The native executable is hashed in streaming mode against the
offline Codex CLI 0.159.2 pins recorded in
`docs/development/CODEX_PLATFORM_PIN_PROVENANCE.md`. “Native/version
established” means the exact host-specific digest matched. It does not mean the
file was run or that login, model access, or application integration works.
For the approved Codex-subscription route and auth boundaries, see
[`API_ENV.md` §4.1 and §7](API_ENV.md). This utility does not run `login status`.

This is only file identity and selected-path readiness. It cannot diagnose or
claim to fix the Mac's current App Server RPC/protocol error. A verified native
binary and clean permission metadata do not establish that RPC startup, login,
model inference, or MIRA integration works; those remain separate live checks.

The JSON output contains only fixed role and reason categories, whether a
native/version was established, and whether a process or network was used. It
does not print selected paths, hashes, environment contents, config values, or
authentication data. `--codex-home` and `--runtime-cwd` are stat-only directory
checks; the tool does not enumerate their contents. In particular,
`runtime_cwd.emptiness_checked` is always `false`; the real preflight separately
requires an empty runtime directory.

Permission reporting follows the public default `process._validate_runtime`
path, not its separate managed-readonly-installation exception. A
current-user-owned or root-owned `0755` executable is allowed by that guard;
owner-write access on such a binary or current-user-owned parent is only
informational. Group/world-writable executable or ancestors, foreign ownership,
symlinks, and executable setuid/setgid bits are blockers. Root-owned sticky
`/tmp` or `/var/tmp` parents are the public guard's specific group/world-write
exception. A default Codex home must have no group/other mode bits and be owned
by the current user. An approved development context may instead accept the
exact previously observed home mode if it has no group/world write bits. This
diagnostic cannot inspect that context and never assumes its approval. A
non-private home is therefore reported as a public-path blocker; a separate
informational category says that managed development context was not inspected.

Interpretation:

- `javascript_wrapper_detected` means the chosen executable is the known npm
  JavaScript shim. If a native candidate is reported, review the known package
  layout and permission categories before deciding what to do.
- `official_native_verified` plus `version_established: true` confirms only the
  pinned native bytes for this host and version.
- `blocking_categories` are public path-guard blockers. `launch_blocking_categories`
  identify execute/access bits that can prevent a process launch even though
  the public guard does not check those bits itself. Missing owner-write alone
  is an operational warning, not proof that a read/search-only runtime directory
  cannot launch. `conditional_categories` is reserved; no managed exception is
  inferred from directory metadata.
- If the selected path is the npm JavaScript wrapper, a verified native
  candidate can make `native_established` true while
  `selected_path_is_native` remains false. Select the native file directly for
  a route that requires it; the diagnostic never runs the wrapper.
- `executable_missing`, `npm_native_candidate_missing`, and
  `npm_native_candidate_unverified` describe a missing or unverified file.
  `executable_not_regular`, `executable_not_executable`,
  `executable_too_large_to_hash`, and `executable_hash_unavailable` describe
  file type, execute-bit, or hash limits.
- `symlink_in_executable_path`, `selected_executable_symlink`, and
  `symlink_in_path` identify symlinks in the selected native executable or
  directory path; a native file reached through a symlink is not hashed.
  `selected_executable_symlink` separately reports when the chosen path itself
  is a symlink, including when it names the JS wrapper.
- `official_hash_not_recognized`, `platform_pin_mismatch`,
  `npm_native_layout_platform_mismatch`, and
  `supported_platform_pin_unavailable` mean platform-specific native identity
  or version is not established.
- `executable_owner_writable`, `install_ancestor_owner_writable`, and
  `directory_ancestor_owner_writable` are
  informational when the file/parent is current-user-owned. They never trigger
  a repair or copy recommendation. Group/world-write, foreign-owner, symlink,
  and setuid/setgid blockers remain separate.
- `directory_not_private`,
  `directory_group_or_world_writable`, `directory_not_user_searchable`,
  `path_not_directory`, and `directory_missing` describe the selected home or
  runtime directory. `directory_owner_write_unavailable` is informational: later
  runtime writes may fail, but this check does not prove that they are required.
  `path_not_canonical_absolute` matches the public guard's canonical absolute
  path requirement.
  Permission categories use Unix mode/ownership metadata; ACLs, mount policy,
  code signatures, and runtime behavior are outside this check. These are
  prompts for human review, not a repair or guard override.
- Only when a verified native has a blocking group/world-write or foreign-owner
  issue may the tool suggest considering a separately reviewed private copy of
  that native executable. Owner-write alone never triggers that suggestion;
  setuid/setgid blockers never trigger a copy recommendation.
  Check both source and destination first. Do not copy the Codex home or any
  settings/authentication data. A copy does not bypass any existing guard, and
  this tool will not copy it or alter permissions for you.
- `official_hash_not_recognized`, `platform_pin_mismatch`, or
  `supported_platform_pin_unavailable` means this tool cannot establish the
  native/version. It does not infer a version from a package wrapper or metadata.

Targeted offline tests:

```sh
python3 -m unittest -v tests.unit.test_codex_setup_diagnose
```

## Metadata config/read diagnostics

An observed `remoteControl/status/changed` status notice is schema-validated and ignored passively at startup and during a turn; it never enables or invokes remote control. Config verification remains mandatory. A metadata failure now includes `check_code` for response shape/type, known unsafe fields, or the actual configuration predicate. Only allowlisted field names, value kind/emptiness and counts are returned; never share private configuration or raw logs to diagnose these codes. The user's actual Mac failure was `developer_instructions:null`. This source corrects that false rejection: null and exactly empty strings/arrays/objects represent inactive optional values. Nonempty strings (including whitespace), nested nonempty content and malformed bool/number values still fail with a safe field/type label. The actual metadata retry after this correction must still be observed separately.

Pinned source context: OpenAI Codex rust-v0.159.2 defines `ConfigToml.developer_instructions` as `#[serde(default)] Option<String>` in [config_toml.rs](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/config/src/config_toml.rs#L2585-L2588). This confirms an unset field is valid; the actual Mac diagnostic independently observed JSON null. It does not prove every possible config/read field or future build is compatible.
