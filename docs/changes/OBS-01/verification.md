# OBS-01 focused verification

No live provider calls, credentials read, raw-mode activation, network telemetry, install or upload.
Tests use synthetic strings/PCM and private temporary directories only. Deadline remains
2026-10-04 08:53:50 UTC. This is not real-provider, real-microphone or independent human acceptance.

## Recorded development evidence

- `docs/verification/obs-01/runs/001-red-core`: 17 failed / 6 baseline passed, expected exit 1,
  zero source changes while running; missing recorder and exporter behavior.
- `docs/verification/obs-01/runs/002-green-core`: same 23 tests passed, zero source changes.
- `docs/verification/obs-01/runs/003-red-runtime`: 3 failures, expected exit 1; missing composition,
  correlation and media-cancellation hooks.
- `docs/verification/obs-01/runs/004-green-runtime`: same 3 tests passed, zero source changes.
- `docs/verification/obs-01/runs/005-red-hardening`: 2 failed / 1 passed; unbounded-bytes raw queue
  and arbitrary DomainError code reflection identified, while blocked-disk behavior already passed.
- `docs/verification/obs-01/runs/006-green-hardening`: same 3 tests passed, zero source changes.

An interim unrecorded focused regression command passed 137 tests, including actor, config, HTTP,
voice HTTP, audio progress, replay and architecture boundaries. It preceded later hardening and
is not the final snapshot's integration receipt. Final focused evidence is listed below; affected/full-suite integration belongs to the director.

## Current limits

- Core, read-only runtime status, persistent frontend banner, safe error correlation, and privacy-filtered
  dialogue/logical-model-content capture are integrated. Raw audio stays fail-closed without an exact
  reviewed-buffer caller; automatic microphone/TTS raw recording is intentionally absent.
- Logs are best-effort diagnostics, never durable transaction/session history. Full disk/slow disk
  may lose records; status counters report drops/IO failures while service work continues.
- Correlation IDs are stable local SHA-256 pseudonyms on disk; raw identifiers are not copied.
- Ordinary HTTP duration measures response-header completion. Media spans independently measure
  producer completion/cancellation and cannot prove acoustic rendering or what a person heard.
- Raw privacy review is distinct from semantic JEV approval. Exact buffers must qualify separately;
  filtering cannot guarantee discovery of every unknown secret, particularly spoken secrets.
- Original records are intentionally lost when review is uncertain, quota is full, a pending mode
  is revoked or retention expires. A started disk write may complete when disabling; pending writes
  are revoked. Raw content is absent from normal exports.

## Final focused receipts and independent review

All receipts are under `docs/verification/obs-01/runs/`, with command, UTC times, source hashes,
stdout/stderr hashes, exact exit code and zero source changes during each recorded run.

- `007-red-privacy-review` → `008-green-privacy-review`: quoted credentials and oldest-record
  retention, 2 behavioral failures → 2 passes.
- `009-red-export-cancel` → `010-green-export-cancel`: deep malformed JSON and review Stop/timeout
  classification, 2 failures → 2 passes.
- `011-red-prefixed-credentials` → `012-green-prefixed-credentials`: env-style and private-key
  assignments, 1 failure → 1 pass.
- `013-red-snapshot-error` → `014-green-snapshot-error`: untrusted provider DomainError code
  leaking through session.last_error, 1 failure → 1 pass at the application boundary.
- `015-red-runtime-recording` → `016-green-runtime-recording`: actual status, privacy-filtered
  runtime text capture and newly injected session-token filtering, 3 failures → 3 passes.
- `017-red-status-ui` → `018-green-status-ui`: visible actual-runtime banner, strict status parser,
  safe correlation, read-only polling and close/late-result behavior, 6 failures/1 baseline pass →
  7 Node passes with strict TypeScript compilation.
- `019-final-focused-python`: **151 Python passed** across diagnostics, Actor, configuration,
  HTTP/voice/audio/replay integration and architecture. This includes **40 OBS-specific Python
  tests**; the remainder is regression coverage, not new diagnostics tests.
- `020-final-web-contracts`: **115 Node tests passed**, including original 108 and 7 OBS tests;
  strict TypeScript build passed; canonical exported contracts consistent; 75 requirement/test
  links collectible. Link collection is not requirement execution.
- `021-cli-sanitized-smoke`: actual export CLI against one synthetic event produced the two-member
  private ZIP, excluded raw, and exited 0. No real runtime files or credentials were read.

A separate read-only privacy review independently reran the core at 35 tests before final UI/raw
text integration; it verified quoted/prefixed credential scrubbing, exact consent, queued mode
revocation, byte budgets, oldest-record retention, JSON/symlink/hardlink export boundaries,
nonblocking storage, Stop/timeout classification and public error scrubbing. The defects it found
were fixed with the recorded RED/GREEN pairs above. This is automated/Agent review, not human QA.

## Browser attempt and exact blocker

At 2026-10-03 10:58 UTC a synthetic no-recording fixture server exposed active-banner status only;
its sink inherited disabled capture/emit and no actual raw mode was enabled. The dedicated cloud
browser attempted one navigation to `http://127.0.0.1:8137` and returned exactly:

`Browser Use cannot open http://127.0.0.1:8137 in tab 8. Browser reported: net::ERR_BLOCKED_BY_CLIENT`

The fixture server was stopped. No native browser, alternate port, network route or other bypass
was attempted. Visual browser QA and screenshot evidence are therefore **blocked/not_run**.
DOM/Node markup checks do not replace visual desktop/mobile or real-device verification.

## Integration handoff

Shared code surfaces were released at 2026-10-03 11:02 UTC after the stable focused receipts.
The director owns subsequent Actor/bootstrap semantic integration and full/affected/release checks.
No commit/push, installation, provider call, real `.env` read or real raw recording activation was
performed by this slice. All runtime data stays under ignored `var/`; the export requires a new
local destination and is not authorization to upload/share.
