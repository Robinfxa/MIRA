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
