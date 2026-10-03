# WP06 backend verification

Final bounded backend handoff: `docs/verification/wp06-audio/runs/020-backend-handoff-green/report.json`.

- Interpreter: pinned `.venv313/bin/python`.
- Result: 174 selected tests passed in 3.38 seconds; exit 0; no source changes during the recorded run.
- Included: domain/transitions and audio facts, actor/foundation/replay HTTP, new voice HTTP/WS, architecture guards, Google STT/TTS adapter contracts.
- `tools/export_contracts.py --check`: consistent.
- `tools/check_specs.py`: 59 repository requirements reference collected tests at this snapshot; this is link checking, not execution evidence.
- Excluded: other workers' unfinished source, full/affected/release integration, live providers/accounts, actual browser/device/microphone, original acceptance catalogue. The director owns coherent shared-snapshot affected/full/release validation; shared schema/domain changes conservatively expand that selection.

## Immutable development evidence

All directories below are under `docs/verification/wp06-audio/runs/`; earlier output was never overwritten. A positive baseline is not retroactively called RED/GREEN.

| Runs | What was actually observed |
| --- | --- |
| 001-http-red → 002-http-green | Original ten real HTTP receipt behaviors fail then pass with the same tests: speech rejected by legacy receipt, typed partial/completed progress, duplicates, exact identity, monotonicity, terminal immutability and Stop fences. |
| 003-domain-context-baseline | 55 passing audio/domain/context/foundation actor tests after adding deeper coverage; new cases have no claimed historical RED. |
| 004-media-http-red → 005-media-http-green-attempt | Thirteen tests fail at missing app media-injection seam, then all thirteen pass through actual synthetic HTTP/WS paths. The separate contract-export command initially exposed implicit FastAPI ValidationError schema vocabulary; explicit route error schemas fixed the export. |
| 006-media-negative-baseline | 26 tests pass, adding synthetic malformed PCM, late cancellation-resistant TTS, final-drain cancel/disconnect, empty/interim transcripts and session deletion coverage. |
| 007-concrete-wiring-red → 008-concrete-wiring-green | Two missing concrete composition tests fail then pass; SDK constructors/HTTP clients are doubles, no token retrieval or network call. |
| 009-late-failure-red → 010-late-failure-green | A real race test shows old generation failure cancelling a newer microphone; actor now cancels media only when the old failure actually changes current state. |
| 011-admission-ingress-red → 012-admission-ingress-green | Optional quota/caller-owned HTTP routing and bounded CLI WebSocket ingress fail then pass. |
| 013-transport-bounds-teardown | 34 passing voice tests, including actual ASGI disconnect cleanup and microphone queue/pacing/duration bounds. |
| 014-backend-scoped-green | Honest unsuccessful attempt: 167 pass, one legacy replay-health compatibility assertion fails. `/voice-capabilities.generation_mode` retains exact mode while legacy health keeps its fixture-family label. |
| 015-terminal-audio-cancel-red → 016-terminal-audio-cancel-green | All three terminal audio statuses initially fail independent upstream-cancellation behavior, then pass. Current failure/interruption also revokes grants; old facts remain history only. |
| 017-backend-scoped-green | 171 selected tests pass after health compatibility and terminal cancellation fixes. |
| 018-lifespan-factory-red → 019-lifespan-factory-green | Three loop/lifecycle tests fail then pass. The RED also honestly records local SDK construction's unclosed event-loop/socket warnings; the fix rejects construction outside app lifespan before SDK resources. No provider inference or credentials were used. |
| 020-backend-handoff-green | Final selected set: 174 passed; immutable source-before/source-after fingerprints match. |

## Handoff status

Backend owned files and generated contracts are stable for director integration. Test registration is director-owned: `test_audio_transitions.py` belongs to domain; `test_audio_progress.py` and `test_voice_http.py` belong to HTTP. Nine WP06 requirement IDs have collected node mappings in the feature traceability manifest. Protocol, lifecycle, resource ownership and remaining qualification limits are documented in `integration.md`.

No provider credentials were obtained, no live calls were performed, no security/DNS/proxy/IAM settings changed, and no git/index/push operation was performed by this backend worker. The existing provider adapter source and separate frontend gate/sink/controller source were left untouched.
