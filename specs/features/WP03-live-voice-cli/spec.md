# WP03 — Explicit live voice development CLI

Status: bounded CLI assembly; no real provider, microphone, or account has been
validated by its tests. This adds a separate voice-only entry point and leaves the
existing public text CLI's guard and default text mode untouched.

Consumer: `tools/live_voice.py` using the existing text admission reader,
`create_development_voice_factory`, and `create_development_app` voice seam.
Owner lane: providers (existing `tests/contracts/test_*.py` contract lane).
Baseline: current recovery source; synthetic admission, ADC path, credentials,
HTTP client, provider bundle, and ASGI lifecycle only.
Resources: existing Codex/JEV admission, Google Speech-to-Text V2 adapter,
Gemini Enterprise TTS adapter, and development-app lifespan.

### WP03LIVEVOICECLI-001 Explicit data and spend admission

Given no separate voice authorization, when the voice CLI is asked to serve, then
it stops before loading Google credentials or creating provider resources. The
voice acknowledgement names microphone audio sent to Google Speech-to-Text V2,
approved text sent to Google Gemini TTS, and applicable provider charges; it is
separate from the pre-existing Codex/JEV admission. Prior application dialogue
continues to flow to Codex/JEV under that admission. No provider or capability is
silently enabled by configuration, a declared project, or a successful `check`.

The CLI is a separate opt-in command. `live_dev.py` remains text-only by default,
and its public route guard is not relaxed. Microphone capture remains a browser
user-gesture action; server startup does not start capture or recording.

### WP03LIVEVOICECLI-002 Private explicit Google ADC file

Given an absolute, existing, owner-only ADC file outside the repository, when
`serve` passes all admission/configuration/voice-consent checks, then Google auth
is loaded only through the official `google.auth.load_credentials_from_file`
SDK entry point for that exact path. A `check`, `--help`, no-argument run, or
rejected serve never reads ADC contents, imports provider SDKs for authentication,
refreshes a token, or makes network/provider calls. Credentials are not printed,
manually parsed, extracted from JSON, or auto-discovered. Runtime TTS refresh uses
the injected Google SDK credentials and existing token-provider seam.

Caller-selected proxy and CA settings are kept from the already-approved runtime
environment and are not replaced by weaker TLS or process-global mutation. If the
current proxy/CA environment differs from the pinned admission, voice serving
stops before credential loading or provider construction.
Given an approved custom CA file, when voice serving constructs gRPC credentials,
then it validates that bounded PEM bundle and passes those exact roots through
standard verifying `grpc.ssl_channel_credentials`. Invalid roots fail closed;
custom directory-only roots require an explicit CA file instead of silently
using unrelated defaults. Ordinary installations without custom roots retain the
vendor platform defaults. No global environment or system trust store is changed.

### WP03LIVEVOICECLI-003 Fixed Google selection and bounded instance budget

Given settings that do not select Google Speech-to-Text V2 `chirp_3`, Gemini
Enterprise `gemini-3.8-flash-tts`, voice `Kore`, and TTS location `global`, when
the CLI checks or serves, then it refuses before loading Google credentials.
Given caller-selected integer TTS and STT request ceilings from 1 to 8 and finite
positive duration ceilings no greater than 30 seconds, when the app lifespan
creates its one voice bundle, then those exact limits are passed into the existing
single-use factory. Invalid and omitted limits are rejected before auth or provider
work. Browser audio is not opened or recorded by this command.

### WP03LIVEVOICECLI-004 Honest status and lifecycle

Given a `check` with valid declared settings, explicit voice acknowledgement,
private ADC path metadata, and valid existing text admission, when status is
printed, then it says voice is declared/configured only, auth and inference were
not run, no provider/network activity occurred, and no quota, entitlement, or
durable dollar cap was verified. The output distinguishes per-invocation request
and duration ceilings from costs; it discloses audio to Google STT, approved text
to Google TTS, and prior app dialogue to Codex/JEV.

Given an admitted server lifespan that initializes a synthetic voice bundle, when
the ASGI app shuts down, then the underlying voice resources and CLI-owned TTS
HTTP client are closed once. Startup failures close owned resources and display
only a safe diagnostic. These tests use fake auth/credentials/transports/providers
and never contact a real provider or open browser microphone capture.
Given an embedding caller owns an existing stopped event loop, when startup
failure triggers synchronous HTTP cleanup, then cleanup creates and closes only
its own temporary loop and leaves the caller's loop and policy association intact.
