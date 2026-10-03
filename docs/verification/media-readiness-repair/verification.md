# Media readiness and presentation-history repair

## Scope

The photo effect now passes through one abortable preparation boundary in the existing scene executor. Preparation reads the already-mounted local illustration, waits for load and decode readiness, and does not mutate the DOM. The controller applies and consumes the effect only after readiness and a fresh generation/permit check. Pending work is capped at four unique effects and aborted on Stop, new input, revocation, and close. Resource failure leaves the photo hidden, emits no media receipt, and produces fixed actionable copy.

This is an application-level readiness contract. `complete`, positive `naturalWidth`, and a successful `decode()` are not evidence of compositor paint, user attention, or understanding. The existing cue sequencing and single audio owner are unchanged.

## Directed RED/GREEN evidence

Final behavior tests are `tests/web/controller-media-readiness.test.mjs`. The RED compiles the immutable T12:56Z source snapshot, then runs that exact current test file against the snapshot controller/executor. The GREEN builds and runs the same test file against the repaired working source.

- `runs/007-red-frozen`: build succeeded; 16 cases failed as expected against the frozen source. The first case observed no decode call, and unready/broken media was already visible and receipted. `changed_during_run` was empty.
- `runs/008-green`: `npm run build && node --test tests/web/controller-media-readiness.test.mjs`; 16 passed, 0 failed. `changed_during_run` was empty.
- `runs/009-web-suite`: `npm test`; TypeScript build and all 184 web tests passed, 0 failed. `changed_during_run` was empty.
- Affected selector run with the installed `.venv313` Python selected `architecture` and `web`; both passed. Other lanes remained `not_run`. The runtime Python initially used by `tools/check.py` lacked `pytest`, so the check was rerun with the ready project interpreter. Report: `var/quality/0a2b2fad89a142bdbda9b37f23554d9e/summary.json`.

Coverage includes decoded-ready success with one receipt, retention of a successfully presented photo after Stop, load/error/decode/timeout failures, late load after timeout, Stop/new-input/revocation/close cancellation, an uncooperative late callback, bounded unique pending work, single-flight reuse of an unabortable browser decode promise, repeated snapshots, duplicate load events, and no frontend receipt for a failed photo when the next photo question starts.

The next-turn check verifies the frontend emits no false receipt. The separate immutable application probe in `docs/verification/media-readiness-independent/` demonstrates that no presented-photo receipt selects the rehearsal `absent` fixture, while recording the photo effect selects `detail`. Together these establish the app-history boundary without claiming a browser end-to-end run or changing backend history behavior.

## Boundaries

All readiness tests use synthetic DOM/image/transport stubs. No browser, compositor, provider, account, credential, microphone, or device output was used. No backend authority, schema, Actor, cue compiler, or audio semantics were changed. Python traceability mappings remain limited to their existing Python contracts; the new frontend cases run in the existing `web` lane.
