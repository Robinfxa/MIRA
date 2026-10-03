# OBS-01 handoff

## Implemented

- Strict payload-free event/port contracts and safe error catalogue in application.
- Nonblocking local JSONL sink with item+byte queue limits, bounded rotation, oldest-record
  retention, 0700/0600 files, no-follow FD IO, safe failure counters and explicit raw mode.
- Trusted known-secret and dynamically created session-token injection; credential envelope
  rejection and quoted/prefixed credential pattern filtering in every recording path.
- Original accepted dialogue and logical model context/candidates are captured only after
  privacy filtering when explicitly enabled. Candidate capture precedes semantic review.
- Audio capture API accepts only exact privacy-reviewed bounded PCM. Automatic runtime audio
  capture is intentionally absent; ASR text is not proof the original audio contains no secrets.
- HTTP request/session/turn/effect correlation, generation/review/media timings and distinct
  cancellation causes; safe errors in direct HTTP, stream errors and session.last_error.
- `GET /api/v1/diagnostics-status` returns actual sink state/counters without paths or secrets.
- Persistent active/unknown/degraded banner outside collapsed diagnostics, two-second read-only
  polling, close/pagehide abort with stale-result guard, validated HTTP diagnostic ID in error copy.
- `tools/export_diagnostics.py --output var/diagnostics-export.zip` produces sanitized local ZIP;
  raw requires BOTH `--include-reviewed-raw --confirm-sensitive-export` and never overwrites.
- North star and user-addendum documented separately from source PDF claims.

## Ownership released

All implementation surfaces are released to the director: application/session_actor.py,
application/media_runtime.py, bootstrap/container.py, config/settings.py, config/loader.py,
new diagnostic settings, HTTP app/routes/media_routes/schemas, canonical generated files,
frontend main/index/app.css/api-client and new diagnostics UI module. No domain transition meaning
was changed and no second playback/session authority was created.

## Verify

- `docs/verification/obs-01/runs/019-final-focused-python/report.json`: 151 Python, zero source changes.
- `docs/verification/obs-01/runs/020-final-web-contracts/report.json`: 115 Node + strict TS,
  canonical export check + 75 collectible spec links, zero source changes.
- `docs/verification/obs-01/runs/021-cli-sanitized-smoke/report.json`: actual one-command CLI smoke.
- OBS-specific Python subset: 40. New Node subset: 7. Neither number is full product acceptance.
- Existing quality catalog registration was performed by director, not diagnostics worker.

## Limits to preserve

Default raw=false, separate recording consent, no actual activation by this task. Known-secret and
pattern filtering cannot prove all novel secrets absent. Reject/drop uncertain audio; do not claim
universal audio redaction. A started disk write can finish on disable; queued raw records cannot.
Retention runs while service runs; no autonomous deletion while process is stopped. Logical model
content is not the complete hidden/provider wire payload. No automatic raw exception-body capture.
Browser visual check was blocked once by ERR_BLOCKED_BY_CLIENT; no retry/bypass. See verification.
Full/affected/release and new semantic integration remain director-owned.
