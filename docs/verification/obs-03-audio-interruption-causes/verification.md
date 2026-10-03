# OBS-03 audio interruption cause verification

Date: 2026-10-03 UTC. Offline local software evidence only.
Git ancestor: `ebb578dde665c9c7269e4a64b508182680b2fa66`; this ancestor is not the current dirty
working snapshot. Every run records actual source hashes before/after and its command.

## Finding and correction

The Actor mapped an accepted current `AudioStatus.INTERRUPTED` report to `USER_STOP` both in
its playback diagnostic and when cancelling generation, review, TTS and STT. The report supplies
an observed interruption status, with no field establishing which local action caused it.

Only `SessionActor.audio_progress` cause selection changed:
- Playback cancellation reason is `UNKNOWN`; its safe receipt diagnostic locator is unchanged.
- Downstream work is cancelled with `PERMIT_REVOKED`, the domain transition's observed consequence.
- Explicit Stop/new-input paths retain `USER_STOP`/`SUPERSEDED`.

There is no new enum, wire field, domain transition, configuration, provider call or cancellation
coordinator. Current interrupted reports still revoke authority, preserve cumulative software
render facts, retain reliable inputs, and set the existing `audio_interrupted` error. Later Stop
still establishes a fence and clears error metadata. Existing microphone teardown stays intact.

## Actual checks

All below use `.venv313/bin/python`; each unique run directory contains command, exit code,
stdout/stderr hashes and source fingerprints. All recorded `changed_during_run` lists are empty.

| Run | Result | Scope |
| --- | --- | --- |
| `001-red-20261003t1231z` | 6 failed, 3 passed; expected exit 1 | Real pre-change failures show false USER_STOP for playback/generation/review/TTS/STT and report-before-Stop |
| `002-green-20261003t1232z` | Same 9 tests passed | Only Actor cause correction applied |
| `003-consumers-20261003t1233z` | 145 passed | First focused consumer regression |
| `004-specs-20261003t1233z` | 99 requirement links collectable | Link validation, not test execution |
| `005-inflight-stop-baseline-20261003t1234z` | 1 passed | Additional baseline regression: late interruption during pending Stop teardown |
| `006-final-consumers-20261003t1234z` | 153 passed | Final 10-test file plus related consumers and architecture |
| `007-final-specs-20261003t1234z` | 99 requirement links collectable | Final traceability validation |

These counts overlap and must not be added. The extra in-flight teardown case is baseline
coverage, not an invented RED/GREEN claim. The exact original nine-test file is retained in
`red-green-source/`; its SHA-256 equals the test hash in both original RED/GREEN receipts.
The original Actor is in `baseline-source/`, final Actor/test files in `verified-source/`.

The final focused command explicitly selected:
- `tests/contracts/test_audio_interruption_diagnostics.py`
- `tests/contracts/test_diagnostics_runtime.py`
- `tests/contracts/test_async_error_locators.py`
- `tests/contracts/test_microphone_teardown.py`
- `tests/contracts/test_audio_context_projection.py`
- `tests/contracts/test_cue_compilation.py`
- `tests/unit/test_audio_transitions.py`
- `tests/unit/test_actor.py`
- `tests/integration/test_audio_progress.py`
- `tests/integration/test_voice_http.py`
- `tests/integration/test_replay_actor.py`
- `tests/architecture/test_boundaries.py` (includes generated-contract drift check)

## Race and history evidence

Deterministic barriers put a second candidate in output review while speech and microphone
operations remain pending. Interruption synchronously clears microphone input and revokes all
work; completed speech is never inferred from 240 rendered samples. Duplicate facts leave state
and terminal diagnostics unchanged. Report-before-Stop preserves the initial unknown cause;
Stop-before-report preserves USER_STOP, including before child cleanup runs. New-input-before-
report preserves SUPERSEDED and does not cancel the new pending generation branch. Failed
playback remains FAILED with UNKNOWN code and no cancellation reason. Correlation remains the
real report request's sanitized locator.

## Limits and handoff

`tests/contracts/test_*.py` is already exclusively owned by the providers lane; shared
`tests/quality.toml` was not changed. Director-owned affected/full/release checks on a frozen
integrated snapshot remain separate. Web suite, package/release, real browser, provider accounts,
physical microphone/speakers, remote CI and original product acceptance were not run here.
No credentials were read, no network/provider requests or publication occurred.
