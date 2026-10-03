# Independent post-fix rerun: decode retry

This is a separate evidence folder; the pre-fix audit and first correction recheck were left untouched. Current source and focused tests were copied before testing. `SHA256SUMS.corrected` records the captured files; the post-run hash check for those files passed at 14:19Z. Baseline hashes and the post-run baseline check are recorded separately. In particular, the new executor hash is `7251b4ad61c936037a7674126734940e7d3669337acfbad33d276887da99c953`.

## Outcomes

- The saved decode-retry probe was copied and adapted only in this folder to expect first `prepare()` failure then success, with two decode calls. Against an isolated build assembled from the captured corrected sources it produced `{"outcomes":["Image resource unavailable","ready"],"decodeCalls":2}` (`20261003T1418Z-decode-retry-adapted.json`). The original pre-fix probe remains untouched in the earlier folder.
- The prior async observer passed on the captured corrected build and still reproduces old baseline behavior on the 12:56 source. Stop, new input, permit revocation, and close all suppress late decode; ready media reveals once and remains after Stop. See the two `20261003T1418Z-*-observer.json` files.
- The focused readiness and cue suites passed **44/44**, including the new controller-level retry case, no receipt on the first failed decode, and only the fresh effect’s receipt after retry. Cue submission remains speech-start-bound (`20261003T1419Z-focused-web.tap`).
- A real application history probe shows no receipt ⇒ `absent`, and an application-recorded ready receipt ⇒ `trip_photo` in `presented_effects` and `detail` on follow-up (`20261003T1419Z-history.json`). The API history implementation hashes still match the frozen baseline.
- A separate uncooperative-decode probe reached the configured 10 ms timeout on two attempts while calling the underlying `decode()` only once; resolving it late did not make either timed-out preparation succeed (`20261003T1421Z-uncooperative-decode.json`). This confirms timeout-bounded waiters and pending-decode single-flight.

## Repro commands

The isolated TypeScript build used the 12:56 source tree plus only captured corrected `ports.ts`, `scene-executor.ts`, and `controller.ts`, and copied readiness/cue tests. Outputs were compiled under `<temporary-evidence-path>`.

```sh
SNAP=<project-root>
CAP=<project-root>/docs/verification/media-readiness-independent/postdecode-retry-rerun-20261003T1416Z
CORR=<temporary-evidence-path>
MIRA_TEST_WEB_DIST="$CORR/apps/web/dist" node "$CAP/decode-retry-probe-adapted.mjs"
MIRA_TEST_WEB_DIST="$CORR/apps/web/dist" node "$CAP/cross-version-observer.mjs"
(cd "$CORR" && MIRA_TEST_WEB_DIST="$CORR/apps/web/dist" node --test --test-reporter=tap tests/web/controller-media-readiness.test.mjs tests/web/controller-cues.test.mjs)
PYTHONPATH="$SNAP/apps/api/src" python3 "$CAP/history_state_probe.py"
MIRA_TEST_WEB_DIST="$CORR/apps/web/dist" node "$CAP/uncooperative-decode-probe.mjs"
```

No browser, provider, credentials, network, Git writes, or production-file edits were used.
