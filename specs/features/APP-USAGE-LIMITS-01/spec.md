# APP-USAGE-LIMITS Explicit bounded application usage profiles

Block: providers/tooling. Consumers: admitted development app, voice app, and
continuous-listening lease owner. Historical `probe` ledgers and limits are
unchanged. This is an in-memory technical ceiling, not billing, account quota, or a
durable cross-restart ledger. Verification uses synthetic local transports only;
no credentials, metadata probe, provider call, or UI route is exercised here.

### APPUSAGELIMITS-001 Frozen profiles and closed validation

Given the default `probe` profile, When request, turn or voice duration limits are
validated, Then requests and turns remain 1–8 and TTS/STT stream durations remain at
most 30 seconds. Given the explicit `application` profile, Then requests and turns
may be caller-selected only within 1–100, TTS audio remains at most 30 seconds per
stream, and STT remains at most 290 seconds per stream. Boolean counts, unknown
profiles, nonfinite values, zero, negatives and over-cap inputs fail closed. No
profile represents unlimited use or raises the lower-level adapter caps.

### APPUSAGELIMITS-002 Admission selection is explicit and legacy safe

Given the runtime-preparation CLI, When a caller chooses `--usage-profile
application`, Then each finite request/turn limit is validated before runtime
path, environment, or Codex metadata I/O and the exact profile is saved in the new
private admission. Given the field is absent from a legacy admission, Then the
reader treats it as `probe`; a probe admission can never be silently upgraded by a
new process. The `live_voice.py` CLI must explicitly select the same profile as
text admission, and its required count/duration flags stay at the caller's values.

### APPUSAGELIMITS-003 Per-invocation limits remain distinct from dollars

Given app setup, When the declaration is shown to an operator or continuous
frontend, Then it identifies the profile, exact caller-selected counts/timeouts and
voice stream limits. Request counts are in-memory per invocation and reset on app
restart; stream-duration ceilings are per stream. This is not a dollar cap, durable
ledger, or provider entitlement check. Unknown current-use fields remain unknown
instead of being rendered as zero.

### APPUSAGELIMITS-004 Irreversible request reservations

Given a request/voice attempt is reserved before provider dispatch, When the
operation is canceled or has an unknown outcome, Then its reservation is not
refunded. Empty, malformed or oversized local voice input may still be rejected
before reservation. Continuous mode uses one STT reservation per lease; lease
duration may be narrower than the profile cap.

Preparation validates request ceilings both at the CLI boundary and before metadata. Revalidation is idempotent for exact bounded integers; booleans and values beyond the selected profile remain rejected before any process is started.
