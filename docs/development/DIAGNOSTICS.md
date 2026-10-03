# OBS-01 local diagnostics

Operational diagnostics support the [project north star](../NORTH_STAR.md). They do not replace
SessionActor, the in-memory history or presentation receipts. No external telemetry is sent.

## Ordinary mode and export

Default: sanitized logging enabled, raw development recording disabled. `environment=development`
is not recording consent. The composition root constructs the sink; no import-time IO or new env
reader exists. Configuration enters only through the existing loader.

From repository root, with existing dependencies:

```bash
.venv313/bin/python tools/export_diagnostics.py --output var/diagnostics-export.zip
```

The destination must not already exist. The command does not load `.env`, walk credential files,
contact providers or upload/share anything. Its private ZIP has fixed `manifest.json` and
`events.jsonl` members. Records are revalidated; unknown fields, malformed/deep JSON and
symlinks/hardlinks are excluded or cause a safe local failure. Even when raw recording is on,
the default export never opens the raw directory.

Events contain only enums/numbers, timestamps and stable pseudonymous correlation IDs for
request/session/turn/effect. Incoming headers cannot choose the server request ID. Request IDs
returned in `X-Request-ID` can be matched to disk as `h_` plus the first 32 hexadecimal characters
of SHA-256 of their UTF-8 representation. The same rule applies to session/turn/effect IDs.
No URL, query, arbitrary provider name, raw exception, headers or content field is accepted.

Known errors are stable classes with Chinese recovery messages. HTTP 403 means the observed
operation was forbidden; it cannot establish whether IAM, entitlement, billing or another cause
was responsible. Unknown causes stay unknown. HTTP timings cover response headers; media timings
cover provider work, not acoustic playback or proof of human hearing.

## Explicit development recording

Both settings must be explicitly configured before raw capture is eligible:

- `MIRA_DIAGNOSTICS__DEVELOPMENT_RECORDING=true`
- `MIRA_DIAGNOSTICS__RECORDING_CONSENT=true`

These instructions describe the feature; no recording was enabled during implementation. An
operator must choose to enable it, understand that approved dialogue/model/audio can be private,
and ensure the persistent visible indicator is available in the running UI. The ordinary default
examples keep both values false. There is no remote UI endpoint that silently enables recording.

The read-only `/api/v1/diagnostics-status` endpoint drives a persistent frontend banner and is
polled every two seconds. Unknown/unreachable status shows a visible caution rather than pretending
recording is off. Close/pagehide cancels polling and ignores late responses. It cannot enable recording.

Raw capture is a distinct privacy gate. Semantic/JEV rejection does not prevent reproduction;
semantic/JEV allowance does not authorize recording. Bounded accepted dialogue and logical generation context/candidate outputs pass the built-in
known-secret and credential-envelope filter. They qualify as `approved` or `redacted` only after
that privacy check. The generation context/candidate is the application-level representation; this
is not a claim to capture the provider’s complete wire prompt, hidden input or original raw response.
Arbitrary raw/audio buffers require an explicit exact-content privacy review of `approved` or `redacted`. `uncertain`/`rejected` are dropped. The sink applies
trusted injected known-secret filtering and defensive credential-pattern filtering even after
approval; credential envelopes, Authorization headers and private-key structures are ineligible.
An arbitrary SDK object, request/response envelope or header map cannot be passed to this API.

Never claim generic spoken-secret redaction. Audio cannot be approved merely because its ASR
transcript looks safe. The exact audio requires a trusted privacy reviewer; without one it is
intentionally dropped. Runtime audio is not automatically recorded; the reviewed-buffer capture API
is available for a separately injected audio privacy-review integration. Regexes and known-secret matching cannot detect every novel secret format.
If review cannot reliably decide or redact, discard the buffer rather than save it.

Raw export is a separate deliberate local action:

```bash
.venv313/bin/python tools/export_diagnostics.py --output var/diagnostics-sensitive.zip \
  --include-reviewed-raw --confirm-sensitive-export
```

This can contain sensitive dialogue/audio and is not authorization to share the ZIP. Review the
contents before any separately authorized sharing. Normal exports exclude it. Neither export
may overwrite a prior file. All runtime logs/recordings/exports should remain under ignored `var/`.

## Bounds, retention and failure behavior

- Ordinary files: default 1 MiB × 4; configurable maximum 4 MiB × 16.
- Raw files: default and maximum 4 MiB × 4 (16 MiB total).
- Default/max file retention: 24 hours, optionally shorter.
- Queue: 256 items by default; independent 2 MiB pending/in-flight encoded-byte cap.
- Raw buffer: at most 128 KiB text or 512 KiB mono PCM16 audio per reviewed record.
- Private directory/file modes: 0700/0600; Linux/POSIX no-follow directory-fd path walk.
- Queue pressure drops records without waiting. The worker owns disk IO. IO exceptions are counted,
  not thrown into a request. `flush` is a bounded test/shutdown helper, never an event-loop hook.
- File age is anchored to its oldest record, not refreshed by subsequent writes. Whole-file expiry
  may discard newer records early; it cannot prolong older records by ongoing appends.
- Cleanup runs periodically while the process runs and before store writes. While the process is
  stopped, files cannot autonomously erase themselves; restart resumes cleanup. This is a local
  best-effort retention policy, not certified secure erasure or protection from operator backups.
- Disabling recording immediately blocks new acceptance and revokes queued raw buffers. A disk
  write already started may finish. Existing files remain private until normal expiry/cleanup.
- Counters are bounded and payload-free; missing logs/IO failures must be reported honestly.

Single process/worker matches the current application deployment. Multiple processes sharing the
same diagnostic directory, Windows permission semantics, live-provider causes and real audio
privacy review have not been validated. See [verification](../changes/OBS-01/verification.md).
