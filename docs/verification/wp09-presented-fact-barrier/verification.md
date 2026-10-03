# WP09 presented-fact barrier verification

Date: 2026-10-03 UTC. Base remains the current integrated MIRA tree; no backend, schema, domain, or bootstrap changes were made.

## Behavior implemented

- The actual controller path is `apps/web/src/features/session/controller.ts` (under `features/session`, not the application directory name used in the task note).
- `input()` still blocks local output and stops audio synchronously. It captures the backend presentation cutoff and the highest already-issued local fact sequence, then waits for only that pending prefix, bounded to 1.5 seconds by default.
- Visual receipts and audio-progress facts remain serialized. A failed acknowledgement is sticky and blocks any new input whose cutoff contains it. Timeout reports that the input was not sent; Close and newer local activity promptly release the waiter. A response after timeout/supersession cannot revive the request.
- The controller returns explicit `submitted`, `not-sent`, `superseded`, `closed`, `unknown`, or `ignored` outcomes. `apps/web/src/app/main.ts` restores only exact text from a known pre-dispatch `not-sent` outcome, and only if the same UI revision is still current and the field is empty. It does not restore superseded or uncertain-after-dispatch input, overwrite newer typing, or claim the request was accepted.
- Microphone WebSocket handling only returns a transcript. Final ASR and fixed rehearsal input go through the same `input()` barrier before `/inputs` can commit. Stop still locally cancels capture before any acknowledgement wait. The dedicated test holds an earlier receipt through microphone completion and verifies that the final transcript is not sent until the receipt is acknowledged.

## RED / GREEN evidence

- `runs/002-red-real-http`: expected failure before the controller barrier. The test withheld the real rehearsal API `/receipts` request before server delivery, issued Stop, then submitted `照片里有什么`. The actual server sealed the turn with the absent-illustration subtitle while the valid receipt was still held: “我们还没有打开旅行插画。请先选择「看照片」.” This is the reproduced causal race, not a setup/collection failure.
- `runs/001-red-real-http` is preserved but excluded as RED evidence: its first version caught the subtitle receipt before the photo, so the visible-image assertion failed due to a harness assumption. `002` changed the interception to the actual media grant and reproduced the intended bug.
- `runs/004-green-regressions`: same real HTTP path passed after the fix with immediate Stop, receipt/audio-progress/input order, failed-ack, bounded timeout/retry, post-cutoff exclusion, rapid supersession, and Close controls.
- `runs/007-green-controller-ui`: 35 focused controller, voice, HTTP and UI tests passed, including main form text restoration and the paired stale post-cutoff fact failure control.
- `runs/012-green-web-final`: final `python3 tools/check.py --lane web --jobs 1` passed all 197 Node tests. `architecture`, `domain`, `env`, `config`, `actor`, `providers`, `http`, `tooling`, `specs`, `package`, and `smoke` were explicitly `not_run`; this is the focused web lane, not full/release or phone/browser acceptance.
- `runs/005-green-web-lane` preserves an earlier pre-execution selector error (`tests/unit/test_google_voice_smoke.py` had no owner then); the director fixed its registration. `runs/006-green-web-direct` preserves the next full web payload result, where one old assertion expected a pre-cutoff failed audio fact not to block a new request. It was replaced with explicit paired coverage: pre-cutoff failures block generation (`controller-fact-barrier.test.mjs`), while an old fact outside the captured prefix cannot stop newer playback (`controller-voice.test.mjs`). Final suite passed in `011`.

## Direct-client boundary and limitations

- The independent audit script and its saved JSON were not edited. Unchanged run `runs/009-independent-snapshot-repro` ran against its frozen snapshot. Run `runs/010-direct-http-current-api` ran that same script with current API source and frozen test configuration. Both show the direct HTTP client can still send `/inputs` before a valid receipt: the generation context has no photo, the late receipt is accepted with HTTP 200, history then includes the photo, and that already-captured turn remains on the absent branch.
- This is a canonical-frontend ordering fix. It does not add a backend receipt barrier, and a direct/malicious client can still assert an earlier cutoff. The HTTP server remains authoritative about receipt identity, sequence and stop fences, but a client-supplied cutoff is not proof of visual display.
- The renderer test establishes only that the local media executor applied the ready illustration before issuing a receipt. It does not prove browser paint or human perception. No real device, live provider, physical audio, or microphone QA was run.
- Timeout control tests use injected promises and a short test-only deadline. Real network timeout behavior is not being claimed.

## Files and hashes

- `apps/web/src/features/session/controller.ts` — `8e526d08be99595d4e6b8e2e2f5901ffbe54cc01d1fca50f9f36888f6c224866`
- `apps/web/src/app/main.ts` — `c4ea5e5818ce117733cbd416f7ebb2f47c6333ed2c6a77a18a45a17728385974`
- `tests/web/controller-fact-barrier.test.mjs` — `251864dc16c19be1231c434a393428b1e12bcd1809bfbab9b6c64498d4002009`
- `tests/web/controller-main.test.mjs` — `9226060c026fd03f72e83ece83ff5cd7765143418b9803f17541edae51288419`
- `tests/web/controller-voice.test.mjs` — `38fdcf6f0d06c7b884d9411f47185300b0cea54ab327ad86d4aaddf8af862721`
- `specs/features/WP09-presented-fact-barrier/spec.md` — `6dd82cd14541adb234351700adf13170674e266a299abe22e7ae13ac52b29aa8`

`runs/012-green-web-final/report.json` records unchanged source fingerprints during the successful lane. The older run records are preserved separately and must not be substituted for the final source snapshot.
