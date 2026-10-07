# Explicit development voice CLI

`tools/live_voice.py` is a separate, opt-in loopback app for the existing bounded
Google voice seam. The ordinary `tools/live_dev.py` command stays text-only and
its `serve --voice-required` request still fails closed. Config fields and a
successful setup check do not enable voice, verify an account, or prove a live
provider call works.

## Data and billing scope

Before either `check` or `serve`, the caller must give a separate
`--authorize-google-voice-data-and-spend` acknowledgement. It is in addition to
the existing private Codex/JEV text admission. The voice path is:

- After the browser asks for permission and a person explicitly presses the
  microphone control, captured audio goes to Google Speech-to-Text V2.
- Approved response text goes to Google Gemini Enterprise TTS.
- Prior application dialogue continues to go to Codex and JEV under the existing
  text admission.
- Server startup never opens a browser microphone or starts recording. The web
  client captures ordinary push-to-talk or the separate finite continuous-listening mode only from an explicit user gesture. Continuous mode displays provisional text and requires another explicit click to submit server-confirmed stable text; it does not auto-submit on silence or a VAD event.

Google STT/TTS and Codex/JEV can incur provider charges. The default `probe`
profile keeps TTS/STT request ceilings at 1–8 and both per-stream duration limits
at 30 seconds. The explicitly selected `application` profile permits caller-set
finite TTS/STT request ceilings from 1 to 100, TTS output streams up to 30 seconds,
and STT input streams up to 290 seconds. These are technical bounds, not a durable
request ledger, estimated spend, provider guarantee, or dollar cap. Request
reservations are irreversible inside an instance; restarting the app starts a
fresh in-memory request allowance. Stream-duration limits apply independently to
each audio stream. No automatic provider fallback or automatic limit expansion is
used.

The text admission and voice CLI profiles must match. Legacy text admissions with
no `usage_profile` field are interpreted as `probe`; the voice CLI defaults to
`probe` and must be passed `--usage-profile application` explicitly to use an
application admission. Count and duration flags remain required so selecting the
profile never auto-expands actual request allowances.

## Explicit local inputs

Use paths to files the user already has. This command does not create accounts,
install gcloud, download credentials, run login, find default credentials, or
extract tokens. The ADC path must be absolute, owner-only, regular, and outside
the checkout. `check` verifies path metadata only and does not read its contents.

The explicit MIRA env file must declare a JEV model/key and the fixed voice
selection below. The ADC file is loaded only for an admitted `serve`, through
Google's official `google.auth.load_credentials_from_file` API. TTS access-token
refresh, when needed, uses the SDK credential object through Google's auth
transport. Credentials and token values are never printed or manually parsed.

The currently fixed selection is:

- Google Speech-to-Text V2 `chirp_3`; STT region and language are read from the
  explicit MIRA env file
- Gemini Enterprise `gemini-3.8-flash-tts`, voice `Kore`, location `global`
- Project ID from the explicit MIRA env file

The server retains the proxy and CA variables bound into the approved runtime
admission. It stops before credential loading if the current proxy/CA environment
differs or contains an unsupported proxy route. It does not weaken TLS or change
system-wide network settings.

For STT's gRPC transport, an approved `SSL_CERT_FILE` (or
`REQUESTS_CA_BUNDLE` when absent) is validated and explicitly passed as verifying
root certificates. This prevents the HTTP and gRPC clients from accidentally
using different trust roots. A custom `SSL_CERT_DIR` alone is rejected with an
actionable request for a CA file; it is not silently ignored. With no custom CA
configuration, the vendor's platform defaults remain in use. No certificate,
credential, or authentication header is written to diagnostics.

## Check without loading credentials

```bash
.venv/bin/python tools/live_voice.py check \
  --env-file /absolute/private/mira.env \
  --admission /absolute/private/admission.json \
  --adc-file /absolute/private/application-default-credentials.json \
  --usage-profile probe \
  --authorize-google-voice-data-and-spend \
  --tts-requests 1 --stt-requests 1 \
  --tts-max-seconds 30 --stt-max-seconds 30
```

This reads the explicitly chosen MIRA env and text admission, verifies ADC file
metadata, and prints declarations plus selected bounds. The status always says
`armed=false`, `declaration_checked=true`, `live_ready=false`, and
`admission_authorized` reflects only the explicit text-admission field accepted
by the parser. Declared speech, key, project, or ADC-path metadata does not verify
provider credentials, account entitlement, quota, or live readiness. It does not read ADC
contents, import authentication credentials, refresh a token, prepare provider
clients, call a provider, or contact the network. Output marks inference as not
run, live readiness as false, entitlement/quota as unverified, and dollar cap as
none. It does not echo paths, env values, or credential contents.

## Serve after review

Use the same required inputs and bounds with `serve` instead of `check`:

```bash
.venv/bin/python tools/live_voice.py serve \
  --env-file /absolute/private/mira.env \
  --admission /absolute/private/admission.json \
  --adc-file /absolute/private/application-default-credentials.json \
  --authorize-google-voice-data-and-spend \
  --tts-requests 1 --stt-requests 1 \
  --tts-max-seconds 30 --stt-max-seconds 30
```

`serve` validates the existing Codex/JEV admission, explicit config, fixed Google
selection, private ADC path, request limits, and current approved network
environment before asking the official Google auth SDK to load the selected ADC
file. It then uses the existing single-use in-process voice factory and app
lifespan. A voice factory that cannot start fails closed; the app and its
voice-owned HTTP/STT resources close at shutdown. Starting the server is not a
readiness or entitlement check. Real STT/TTS behavior remains unverified until a
separately authorized real invocation is performed.

For an application admission, use `--usage-profile application` with both `check`
and `serve`, then explicitly choose the finite TTS/STT counts and stream-duration
limits. The application STT stream declaration can be at most290 seconds. The current continuous-listening lease is separately capped at min(120 seconds, the declared STT duration), rounded down to whole seconds. A declaration below1 second disables continuous mode while preserving supported PTT. Each lease permits at most12 manual sends, and each session at most4 lease starts; there is no automatic rollover. One STT RPC per lease consumes one of the app's STT
request reservations; cancellation or an unknown remote result does not refund it.

Do not share the private env, admission, or ADC files. Never use the root
`.env` or an unselected default credential path as an implicit substitute.

For the exact click-start/manual-send controls, usage semantics and a five-minute device checklist, see [Continuous listening](CONTINUOUS_LISTENING.md).
