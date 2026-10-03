# WP03-MIC cancellation teardown verification

## Result

The original intermittent HTTP failure exposed a real ordering bug. The old
microphone `finally` cancelled reader/sender and awaited their `gather` before
invalidating STT, clearing raw PCM, or registering provider reaping. Cancelling
the request at that await could skip all three. This is reproduced with explicit
Event barriers, without increasing the existing one-second test waits.

Final source-stable affected receipt:
[009-consumers-20261003t1156z/summary.json](009-consumers-20261003t1156z/summary.json).
It records **878 passed Python tests**, no skips/failures/errors, with:

- architecture: 7
- actor: 15
- providers: 643 (includes 13 new microphone teardown cases)
- HTTP: 71 (existing voice HTTP cases unchanged)
- tooling: 142
- specs: passed link/collection check, not another behavioral test count

Selected source files have identical before/after hashes. Domain, env, config,
web, package, and smoke were not selected. This is an explicit-file affected
check, not Git-diff selection, a full/release check, or original 164-case product
acceptance. No Git, live provider, browser, network listener, credentials, `.env`,
paid operation, remote CI, actual microphone, or audio device was used.

## Change

1. `MediaOperation.cancel` synchronously clears its buffered output and invokes
   the microphone's bound `buffer.clear`, before any await. It preserves the
   first cancellation cause and does not repeatedly cancel a producer while
   that producer is closing its iterator.
2. The existing media operation owns its two HTTP microphone child tasks. This
   is scoped lifecycle plumbing, not a task manager or another state authority.
3. `SessionActor.close_media` performs revocation and attaches reaping callbacks
   synchronously, then returns the existing bounded close coroutine. Callers
   still await it. Media registry capacity remains occupied until the producer
   and both owned children actually finish, including uncooperative cleanup.
4. HTTP teardown establishes the above before a cancellable await. Explicit
   outer cancellation is classified as disconnect; existing Stop/session-close
   causes survive later cleanup. The error branch revokes before error sending.
   Child cancellation remains in route teardown so Stop/session deletion can
   still emit the existing `media_cancelled` wire response.
5. Session close registers media cleanup before waiting for generation tasks;
   its bounded media wait is reached through `finally` even if that preceding
   wait is cancelled. No Actor semantic, projection, domain, or wire changes.

`asyncio.wait(..., timeout=.25)` bounds teardown waits and does not propagate
outer cancellation into iterator/child cleanup. The 75-second request timeout,
90-second producer timeout, and the existing HTTP test's one-second assertion
remain unchanged.

## Retained evidence and development sequence

All evidence files are retained, including failed intermediate runs. Directed
stdout captures below are real local pytest outputs; their filenames carry
run labels, not an independently verified exact start timestamp. They do not
have the full structured runner metadata that the affected receipts provide.

- `001-red-20261003t1148z.txt`: **4 failed**, before implementation. Held child
  cleanup exposes disconnect/outer-cancel provider revocation omissions,
  cancel's raw-PCM omission, and cancellation of teardown itself skipping STT
  cleanup. `001-red-source.sha256` records that code/test boundary; baseline
  production copies are in `baseline-source/`.
- `002-green-20261003t1150z.txt`: despite the initial intended run label,
  **2 failed, 42 passed**. Cancelling socket children directly on Actor Stop
  suppressed the existing error response. The implementation was corrected;
  existing assertions were not weakened.
- `003-green-20261003t1151z.txt`: **44 passed**, same original four adversarial
  cases plus 40 unchanged voice HTTP cases.
- `004-adversarial-20261003t1153z.txt`: **1 failed, 11 passed**. New test cleanup
  directly awaited an intentionally cancelled child, raising CancelledError.
  That new harness await was changed to gather(return_exceptions=True). This
  is a test-harness correction, not a claimed product RED.
- `005-baseline-adversarial-20261003t1153z.txt`: **8 failed, 4 passed**. Expanded
  twelve-case regression suite run against preserved pre-fix production files
  in an isolated `/tmp` package copy with pytest's explicit pythonpath override.
  Active production files were not reverted. This is a post-implementation
  baseline regression demonstration, not twelve cases all written first.
- `006-green-20261003t1153z.txt`: **52 passed**, expanded twelve cases plus the
  unchanged 40 voice HTTP cases.
- `007-consumers-20261003t1154z/`: behavioral lanes passed; spec link lane failed
  because the new requirement prefix did not match `WP03-MIC`. The headings and
  mappings were corrected. This receipt is not an overall pass.
- `008-shutdown-20261003t1156z.txt`: **13 passed** after adding cancellation of
  session shutdown during a held generation cleanup wait. This additional case
  is a GREEN-first coverage addition, not claimed historical RED.
- `009-consumers-20261003t1156z/`: final source-stable affected pass above.

Commands for directed fixed-source checks were
`.venv313/bin/python -m pytest tests/contracts/test_microphone_teardown.py -q`
and, where noted, the same with `tests/integration/test_voice_http.py` added.
The exact final affected command and lane commands are in receipt 009.
The only test file edited/created in this task is
`tests/contracts/test_microphone_teardown.py`; providers owns it through the
existing `tests/contracts/test_*.py` catalog glob. The catalog was not changed.

The original failure remains untouched at
`../http-01-portable-openapi/003-consumers-20261003t1139z/http/stdout.txt`.
Its reproduced source media route hash is
`13d7f89281a30619da88e3599ce55f5ff3f6f7177667f9cbc65cbaf6bcc57ee3`.
`verified-source/` contains the final three touched production files and the
final test file, copied only after their hashes matched receipt 009.

## Coverage and limits

The 13 cases cover disconnect, explicit cancel, outer cancellation, cancellation
while child cleanup is held, repeated outer cancellation, retained ownership,
four-slot exhaustion by uncooperative iterators, held aclose, first-cause
retention, suppression of late output, capacity release, Stop, session close,
repeated cancellation of session shutdown, and normal/aborted final drain.
Normal finish still produces final transcript/complete without creating a user
turn. The existing final-drain disconnect test also passed concurrently with
other consumer lanes.

Python cannot forcibly terminate an arbitrary cancellation-resistant coroutine.
Such work remains tracked and charged against the existing four-operation
session capacity until it truly exits. The fix guarantees synchronous local
revocation and queue clearing plus bounded waiting; it does not claim that a
broken provider releases remote resources within .25 seconds. Shared files
were subsequently released to the separate async error-correlation task, so
later integrated changes require their own verification.
