# Codex CLI 0.159.2 platform pin provenance

Checked 2026-10-04 UTC. This note supports the next MIRA source/package only; it does not modify or supersede the frozen 09:52 Linux-only delivery.

## Official source and version binding

The source is OpenAI's `openai/codex` GitHub repository. Its stable `rust-v0.159.2` release page identifies the exact version and release; the expanded official asset listing provides each platform archive's SHA-256 and size:

- [OpenAI Codex CLI 0.159.2 release](https://github.com/openai/codex/releases/tag/rust-v0.159.2)
- [Official 0.159.2 release assets and published SHA-256 values](https://github.com/openai/codex/releases/expanded_assets/rust-v0.159.2)

The native Codex executable archives used here are:

| Host | Exact official archive URL | Published archive SHA-256 | Published size | Derived native executable SHA-256 |
|---|---|---|---:|---|
| macOS arm64 | `https://github.com/openai/codex/releases/download/rust-v0.159.2/codex-aarch64-apple-darwin.tar.gz` | `025deffd84cbc99d88ef952e585dc67c7c94e4273f89ba3d45f7e5799743c13c` | 91 MB (95,449,637 bytes) | `16593cc2f422d5f398a8e40f550ebbaf1245392528957be342c295920a300704` |
| macOS x86_64 | `https://github.com/openai/codex/releases/download/rust-v0.159.2/codex-x86_64-apple-darwin.tar.gz` | `3f4e1f71aa05b1dd3d02dd66e780f7857cf19c693498a171f038f74ef3ef3be9` | 99.4 MB (104,209,603 bytes) | `5acdb61ada4233af340719ddb243d5e71ea24f04afeed922644d8f1d486d4c79` |

The downloaded archive checksums matched the values published beside those exact URLs in the official release asset listing. Before reading file contents, each gzip/tar archive was inspected: it contains exactly one regular member with the expected target-triple filename and no directory traversal, symlinks, hard links, or other member types. The member bytes were copied to a separate private verification directory without running them. `file` identifies the resulting files as Mach-O 64-bit arm64 and Mach-O 64-bit x86_64 executables, respectively. The last column is a local SHA-256 derived from those checksum-verified archive members; it is not represented as a separate vendor-published executable checksum.

The existing Linux x86_64 digest stays unchanged: `1748767b230ebfc3d4ab7e4e254920d0c0ad9691fd8c11f190e7d44511a4a92e`. The code keeps `PINNED_EXECUTABLE_SHA256` as this legacy Linux alias. No pin is provided for Windows or Linux arm64.

## Selection and guard behavior

`CodexRuntime` derives an immutable expected pin from the current Python runtime's `sys.platform` and `platform.machine()` values. There is no model or environment-variable override and no constructor argument can supply a different platform's digest. The process boundary rechecks those host facts before touching or starting the executable. The metadata preflight requires the selected platform's exact upstream `platformFamily` and `platformOs`; missing, unknown, or mismatched values fail closed. The CLI helper accepts only the three reviewed host combinations listed above and verifies the actual executable bytes, so a JavaScript `codex` wrapper does not satisfy the native binary pin.

## Verification boundary

Official release asset identity, archive SHA-256 matching, archive-member safety, and offline software guards were checked. No foreign binary was executed. This Linux work environment did not run the native macOS executable: actual Mac process startup, metadata handshake, login, model inference, and user-Mac acceptance are all **not run**. The previously frozen 09:52 package remains Linux-only; this extension must ship in a complete matching later source/package rather than by transplanting only this helper or its platform-pin code into the frozen bundle.
