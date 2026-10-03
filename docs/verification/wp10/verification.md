# WP10 server history-prefix verification

Date: 2026-10-03 UTC. Local synthetic verification only. The shared workspace was already broadly modified at task entry; recorded reports include source hashes so results stay scoped to the exact files and run.

## Directed RED/GREEN

- `runs/001-red-server-prefix/report.json` is the actual pre-fix RED on the directed unit and loopback HTTP tests: 4 failed, 1 passed, exit 1 as expected. The prefix-gap, huge-cutoff, active-Actor, and direct-HTTP raced-photo cases failed because the server accepted an incomplete prefix. The Stop/late-history control passed.
- `runs/002-green-server-prefix/report.json` reruns the same five selected test node IDs after the fix: 5 passed, exit 0, no source changes during the run.
- `runs/003-green-gap-controls/report.json` adds the interior audio-sequence gap and above-cutoff controls: 2 passed, exit 0, no source changes during the run.
- `runs/005-spec-links/report.json` runs `tools/check_specs.py`: 130 requirement-to-test links resolve. This is collection/link evidence, not test execution evidence; `009-spec-links` repeats it after the final spec edit.
- `runs/006-final-owner-tests/report.json` is a recorded intermediate failed assertion: the test referred to `ReliableUserInput.request_id`, while the existing field is `event_id`. The assertion was corrected without changing implementation behavior.
- `runs/007-final-owner-tests/report.json` is the focused run after that correction: all 7 tests passed. A subsequent assertion also checked that Stop preserved reliable user input.
- `runs/008-final-directed/report.json` is the authoritative current focused run: all 7 tests in `test_history_pending.py` and `test_history_pending_http.py` pass in 0.46s, exit 0, with no source changes during the run.
- `runs/009-spec-links/report.json` reruns `tools/check_specs.py`: 130 requirement-to-test links resolve, exit 0; this is not execution evidence.
- `runs/004-final-directed/report.json` also passed 7 tests, but records an unrelated concurrent edit to `tests/web/controller-reviewed-audio.test.mjs`; `008` supersedes it with an unchanged snapshot.

## Covered behavior

- Cutoff zero passes; missing first or interior sequence slots raise retryable `history_pending`; an audio-progress fact and visual receipts complete one shared sequence prefix.
- A fact whose sequence is above the cutoff does not count toward that prefix. A client cutoff of `10**1000` fails promptly without range iteration.
- While a branch is active, a pending input cancels its owned task and revokes its authority under the Actor lock without consuming the proposed activity sequence, input epoch, request fingerprint, reliable input or user text. Its bounded cutoff fence accepts the valid delayed fact as history only; the exact same request then retries and its context includes that fact. A cancellation-resistant provider cannot apply a late result.
- Through loopback HTTP, Stop returns immediately with no receipt present. The raced input returns 409 `history_pending`; the delayed valid receipt returns 200 and remains history-only; the same input ID/body is accepted afterward and returns the authored detail response. A repeated accepted request stays idempotent.

No DTO, route, generated contract, bootstrap or frontend file was changed for this feature. No provider, credential, public-network or physical-device call was made. The cutoff is client-asserted and this is not proof of authenticity, display or perception. A permanently lost fact leaves the prefix incomplete; current client recovery may require a fresh session.

The director owns the shared quality registry and full integration freeze. This slice did not run affected/full/release aggregate lanes; the new files are registered in the `actor` and `http` lanes, and the director's separate freeze run remains the integration gate.

## Combined-integration compatibility correction (18:42 UTC)

The first immutable1834 release run failed two older audio tests: both assumed a new input could begin before a terminal audio fact included in its cutoff had been acknowledged. That assumption is deliberately rejected by this feature. The failed release receipt remains at `var/quality/coherent-release-20261003T1834Z/summary.json`; package/smoke were not run.

Only the two test scenarios were updated. They now require `history_pending`, retain the old cancellation cause and unconsumed request, acknowledge the exact immutable terminal fact, retry the same request, and prove duplicate late delivery cannot cancel or rewrite the new branch. Production guard logic was not relaxed. `runs/010-integration-audio-prefix-regressions` passed29 related domain/Actor/diagnostic/HTTP cases with unchanged source during the run. This is a test-contract migration following the observed integration failure, not fabricated pre-implementation TDD evidence.
