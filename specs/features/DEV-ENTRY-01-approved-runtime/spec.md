# DEV-ENTRY-01: explicit local development application

Owner: bounded local entry. Consumers: `create_development_app`, the existing MIRA ASGI router and presentation renderer, plus `tools/live_dev.py`. Runtime input is an explicit pinned Codex admission, typed settings, an immutable supported decision policy, caller-budgeted JEV transports, finite turn/request ceilings, and an optional already-authorized voice factory.

### DEVENTRY01-001 The live development factory requires explicit bounded admission

Given the ordinary `create_app()` factory and provider factory keep their current fail-closed behavior, when an application caller constructs the separate development entry, then it must provide an explicitly authorized typed runtime and exact public-or-managed route binding, supported policy, finite Codex/JEV request limits, and finite timeouts. Public runtime has no managed context or `CODEX_HOME` override. A managed runtime is accepted only with its explicit pinned context. Invalid route, unarmed authorization, non-finite or huge timeout, unsupported policy, and an invalid turn/request ceiling fail before provider requests.

### DEVENTRY01-002 Text-only generation yields standalone visible text

Given no admitted voice bundle is supplied, when Codex generation is configured for the development app, then its author instruction, structured output schema, and parser explicitly exclude speech. A new sentence is returned as a standalone subtitle effect that can share a range with an authored pose or scene. The legacy backend default retains its speech-capable behavior. If voice-required mode is requested without an admitted in-process voice factory, construction fails.

### DEVENTRY01-003 The existing ASGI and presentation gates handle the candidate

Given a caller-injected Codex transport and synthetic JEV transports, when one HTTP session submits a new-sentence-and-pose request, then the real app lifecycle and existing session path can admit the subtitle and pose with `cue_speech_id=null`, no audio facts, and no voice capability. Unknown input or output rejection produces no active grants. Stop cancels a pending generation and app shutdown closes the session. One app instance admits only one session and the declared per-session input-turn limit.

### DEVENTRY01-004 The command line is inert by default and prepares the UI before serving

Given no command-line arguments, when `tools/live_dev.py` is run without `PYTHONPATH`, then it reports unarmed help without opening config/admission files or calling a provider. Given explicit private config and admission paths, `check` reports declarations without provider calls. Given `serve`, then contract exports are checked and a clean checkout's TypeScript is rebuilt before the loopback app starts, so `/` references and serves the newly built `/dist/app/main.js`.

### DEVENTRY01-005 The real development entry retains sanitized diagnostics

Given diagnostics are enabled in the caller's typed settings, when the development entry processes a synthetic provider contract error, semantic rejection or uncertain result, then the ordinary bounded recorder persists correlated request/turn and fixed cause facts. The provider contract error remains `invalid_response`; semantic rejection and uncertainty retain distinct public codes. Unknown raw provider strings, private dialogue and known secrets do not enter default logs. An explicitly disabled recorder remains disabled. Config-level development recording is reset to off; a fresh visible user consent transition is still required to start raw capture. Diagnostics failure remains governed by the existing fail-open recorder behavior.

### DEVENTRY01-006 Managed admission accepts Codex's canonical HOME/.codex default

Given an explicitly approved managed runtime has a canonical absolute `HOME` and its fixed `runtime.codex_home` is exactly `HOME/.codex`, when the caller constructs the development app without a `CODEX_HOME` entry, then factory admission succeeds without adding that override, reading the filesystem or credentials, or starting a transport. Empty explicit `CODEX_HOME`, a missing/relative/noncanonical default `HOME`, and a home that does not match the runtime remain rejected. Filesystem canonicality, ownership, and installation/config fingerprint checks stay with production runtime validation before process spawn.

## Scope and evidence

- No HTTP route/schema, frontend source, arbitrary module loading, OAuth, generic budget service, or provider authentication discovery is added.
- Serve uses the exact normal local Codex CLI/runtime in its admission, TypeSafe configuration from an explicitly selected private env file, the fixed `gpt-6-luna` Codex model and fixed `jev-1.13.0` JEV model. Local Google configuration can be loaded by the existing loader, but this CLI does not create a voice bundle; text mode remains explicit until an in-process voice factory is admitted.
- Text/candidate transmissions are authorized by the separate `--authorize-codex-and-jev-content` consent recorded in Admission, distinct from local policy-environment confirmation. JEV requests may be billable. Limits are in-process request/turn ceilings per app invocation, not durable across restarts and not dollar caps.
- Test resources: local Python 3.13 dependencies, pinned TypeScript from existing `node_modules`, FastAPI `TestClient`, and synthetic Codex/JEV transports only. No provider, device, credential-cache, login, or account calls are involved in these tests.
- Test ownership and lanes: contract tests in `tests/contracts/test_*.py` are collected by the existing `providers` lane; the focused Node test is collected by the existing `web` lane.
- The managed-home factory boundary is covered by `tests/contracts/test_managed_home_factory.py`, collected by the existing `providers` lane.
