# WP03 Google voice verification — 2026-10-03 09:30 UTC

## Result

Final scoped run: **49 Google speech contract tests + 7 architecture tests = 56 passed**.
The real installed Google 2.40.0 async client dispatch/protobuf seam ran against an explicit
no-network channel and AnonymousCredentials, with ADC and secure/insecure channel creation
patched to fail. The real HTTPX 0.28.1 streaming API ran using its MockTransport, including
bearer header injection, PCM output and early-close cleanup. These are offline transport-contract
checks, not actual Google service calls or account validation.

`tools/check_specs.py` passed; the repository currently has 44 linked requirements, including
this feature's six. Link collection is not additional executed behavioral tests.

Final immutable receipt:
`runs/006-final-green-20261003T0929Z/report.json`

Commands:

```text
.venv313/bin/python -m pytest tests/contracts/test_google_speech_stt.py tests/contracts/test_google_speech_tts.py tests/architecture/test_boundaries.py -q -o cache_dir=<temporary-evidence-path>
.venv313/bin/python tools/check_specs.py
```

The final receipt hashes the owned adapter/test/spec files before and after; no owned source
changed during these checks. It does not make a whole-repository immutable-snapshot claim while
other owners work. Integration/affected/full/release checks remain the director's responsibility.

## Actual RED/GREEN sequence

- `001-red-20261003T0913Z`: both new contract modules failed collection because adapters did not
  exist (exit 2). This is missing-implementation RED, not an assertion-level behavioral run.
- Initial implementation: 31 contract tests passed in the interactive command output.
- `002-red-hardening-20261003T0919Z`: four new failures (invalid first packet, source cleanup,
  injected token and invalid-token support) followed by an externally bounded 3-second deadline
  test timeout (recorded exit 124). The interrupted run is not a complete failure count.
- Hardening implemented: 36 tests passed; further negative coverage subsequently passed.
- `003-red-interim-tail.txt`: directed assertion failed because an unfinished STT hypothesis was
  treated as a normal end. Explicit incomplete_stream now passes the unchanged assertion.
- `004-green-20261003T0927Z`: 46 contracts + 7 architecture passed before further negative cases.
- `005-red-httpx-timeout.txt`: directed assertion failed because HTTPX ReadTimeout was mapped to
  unavailable. Typed timeout mapping now passes the unchanged assertion.
- `006-final-green-20261003T0929Z`: all 49 contracts + 7 architecture passed; final source hashes.

Additional coverage added after initial GREEN is regression coverage, not retroactively claimed
as test-first RED. Failed-run logs are retained rather than overwritten. No original acceptance
catalog cases were marked passed, no Git/push operation was performed, and shared config,
bootstrap, schemas, domain, actor, quality registry and dependency locks were not edited by this
worker. The director independently installed and pinned the SDK dependencies.

## Remaining production boundaries

- No Google login, ADC discovery, credential-file/cache read, API enablement, IAM mutation,
  persistent grant, model entitlement, billing/quota verification or paid/live request occurred.
- Bootstrap must supply authorized credentials to SpeechAsyncClient and an async refreshed-token
  provider to TTS; it owns secrets, token refresh and client shutdown. Auth fields alone do not
  make live_ready true. No hidden mock/legacy/model fallback exists.
- HTTPX should use trust_env=False and verified TLS. That disables automatic environment proxy
  and custom-CA pickup; if the runtime requires an approved managed proxy/CA, composition must
  inject it explicitly. Never disable certificate verification. gRPC needs supported HTTP/2 TLS
  reachability to the selected regional speech endpoint. Proxy/CA/network reachability has not
  been exercised here; no egress restriction was bypassed.
- STT callers must pace raw mono PCM16 approximately in real time. One stream is bounded below
  five minutes; no automatic rollover/retry is implemented. Google gRPC deadline handles the
  live call; caller controls waiting for the first microphone packet.
- TTS supports the 30 documented prebuilt voices only. Extended/custom/replicated voice creation
  and consent flows are deliberately outside this slice. Exact model/global are fixed.
- SSE idle/connect/write limits come from HTTPX; token acquisition and event reads also respect
  an absolute deadline. Total response/audio bounds apply. This is not a hard wall-clock process
  kill guarantee if an injected client/credential implementation ignores cancellation.
- Async generators must be closed on early consumer exit. Adapters close per-call resources;
  composition closes shared clients. Cancellation-resistant injected streams are tested: late
  transcript/audio cannot be emitted after task cancellation.
- Microphone capture, user authorization of submitted audio, Chinese intelligibility, genuine
  service latency, local browser playback, epoch/permit composition, audio stop tail and
  end-to-end 3–5-minute experience remain untested. Local Stop must precede network cancellation.

Next owner can use `integration.md` for exact constructor wiring and bounded live-smoke admission.

## Live synthetic connectivity addendum — 2026-10-03 17:15 UTC

This addendum supersedes the earlier statement that no paid request occurred. Seven provider
attempts are now represented in the private ignored ledger; unknown reservations were not
released or reconciled without usage evidence. No microphone or private user audio was used.

| Attempt | Result | Reserved max (USD, pre-tax) |
| --- | --- | ---: |
| Initial TTS | Tool review was canceled; no HTTP result, retained as unknown | 0.026624 |
| Cancel-slot TTS | HTTP 400, `invalid_input`; no packet or cancel | 0.026624 |
| Minimal TTS | HTTP 200, `unsupported_audio`; response media facts were not captured then | 0.303104 |
| Initial STT | gRPC `unavailable` during TLS/proxy setup; no transcript | 0.008000 |
| Recovery TTS | HTTP 200, part type `text`, finish `STOP`, no `inlineData`; `non_audio_part` | 0.303104 |
| Fixture STT | Completed once with a synthetic Flite English fixture; see below | 0.008000 |
| Text-diagnostic TTS | HTTP 200 followed by client timeout at the 30-second bound; no validated audio or response-part diagnostics | 0.303104 |

The ledger's conservative maximum reservation is **$0.978560 before tax**. The final TTS
report recorded a timeout; its full $0.303104 reservation remains unknown and consumed. No
further request was dispatched. Google Cloud documents that SKU prices exclude taxes and that
taxes may depend on billing location; the billing read remained unavailable, so an all-in
under-$1 amount cannot be established. [Google Cloud tax guidance](https://docs.cloud.google.com/billing/docs/resources/vat-overview)

The one successful STT attempt used the project-owned offline synthetic `greeting` fixture,
`en-US`, `chirp_3`, `us`, 24 kHz mono PCM, 147,240 samples (6.135 seconds), fixture PCM SHA-256
`67179120b348ae05195453fab63199b3e458474311a57791afae51a833c8c924`. The STT stream produced
one partial and one final revision; the final matched the fixture caption. The raw transcript was
not persisted. This verifies a bounded synthetic English STT stream only, not Chinese quality,
microphone capture, acoustic performance or device playback.

The 17:12 TTS diagnostic kept the approved exact model, global endpoint, Kore voice and minimal
official body (`responseModalities: ["AUDIO"]`, no optional `responseFormat` or token cap). The
earlier HTTP200 first observed text part was not a MIME/PCM decoder failure. The client closed the stream at that part, so later events are unknown. Its
provider text, `modelVersion` and usage metadata had already been discarded, so they remain
unknown. The bounded text/model/usage diagnostic path was implemented and exercised offline;
the later live call timed out before a response part exposed those facts. No cause is inferred.

For gRPC, bootstrap now accepts explicitly supplied `ssl_channel_credentials`; the approved
one-shot path builds those from the existing managed CA bundle while retaining normal chain and
hostname verification. It does not edit system/environment trust or disable TLS. Synthetic
valid/invalid CA and SDK transport-injection tests passed; the successful fixture stream also
demonstrated one live STT path through that explicit trust injection.

Focused checks after these changes: `py_compile` plus the selected Google speech contract,
smoke and voice-factory integration tests reported **82 passed, 36 deselected**. This is not a
whole-repository release result; the director owns wider quality checks. Sanitized private
receipts are under ignored `var/mission/google-setup/`:

- `recovery-tts-stt-20261003T1646Z.json`
- `recovery-stt-20261003T1654Z.json`
- `text-diagnostic-tts-only-20261003T1711Z.json`
- `live-smoke-ledger.json`
