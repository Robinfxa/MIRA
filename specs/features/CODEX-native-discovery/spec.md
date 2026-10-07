# Safe native Codex discovery behind the official npm wrapper

Scope: explicit metadata-preparation only. Discovery may start from an explicit executable path or the normal `codex` PATH lookup. It recognizes only the exact official `@openai/codex/bin/codex.js` layout and its known host-specific optional native package locations. It never executes JavaScript, invokes npm/package scripts, searches outside those package-relative locations, copies binaries, reads Codex home contents, or changes permissions, account state, network policy, or version pins.

### CODEXNATIVEDISCOVERY-001: Resolve the known wrapper only

Given an exact official npm wrapper (including a bounded ordinary symlink to that wrapper), resolve only the current host's reviewed native optional package in its exact nested or hoisted location. Require one unique candidate. Unknown wrapper layout, symlink cycles/escapes, missing/ambiguous candidates, and wrong-platform-only candidates fail with fixed reason codes and no raw path disclosure.

### CODEXNATIVEDISCOVERY-002: Preserve native trust checks

Before metadata preparation, verify the canonical native path, current platform pin, exact native digest, executable bit, regular-file type, allowed ownership, non-writable-by-group/world source and ancestors, no symlink components, and no setuid/setgid bits. Any failure is closed with a fixed reason. A matching native blocked by filesystem permissions is reported distinctly from a missing native. No fallback copy, chmod, home change, auth/config access, or alternate version is allowed.

### CODEXNATIVEDISCOVERY-003: Keep preparation bounded and inert by default

No-argument and help behavior remain inert. The selected native executable is passed into the existing metadata-only preparation flow; its initialize/config-read RPC sequence, startup notice counts, auth isolation, and no-model status remain unchanged. Synthetic tests never execute a Codex binary, JavaScript, model, or network request.

Quality owner: providers via `tests/contracts/test_codex_native_discovery.py`; tooling also covers the existing runtime-preparation contract. Consumers: `prepare_runtime_admission.py` and the existing native process preflight. No app route, admission schema, network policy, or Codex home behavior changes.
