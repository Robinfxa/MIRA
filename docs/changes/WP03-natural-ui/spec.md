# Natural conversation browser slice

Base: immutable integration copy `mira-integration-next-20261005T1244Z`, copied 2026-10-05 13:00 UTC. No Git metadata is available; affected checks use explicit changed paths. Web owner: natural voice UI. Backend schema and generated contracts remain backend-owned. Playback ownership remains SessionController-owned.

## Observable requirements

- Given a user clicks start, the UI explicitly requests natural mode, prepares the existing playback sink in that gesture, and displays finite lease/count limits. Opening the page never opens the microphone.
- Given server readiness declares natural offsets and no manual-commit requirement, only an `utterance_ready` with validated source offsets can request automatic commit. Final text, punctuation, elapsed silence and `endpoint_pending` cannot prove an utterance is complete.
- Given one utterance/version, repeated readiness produces at most one automatic commit. Exact lease, token, revision and text are retained through commit acknowledgement. A stale rejection, changed revision, Stop, Close or failure fences its result; no hidden model retry occurs.
- Given recognition changes an already committed utterance, preserve its original submitted text and associate the new full text with that same utterance as a visible correction requiring review. Never make the correction a fresh automatic turn.
- Given software playback owns the sink during captured samples or when submission would start, keep the text for manual review. This is overlap prevention, not acoustic echo detection. Do not interrupt owned playback from the microphone energy heuristic.
- Given unknown endpoint capability, show listening/transcribing and explicit manual fallback. Given transport/input failure or finite terminal, retain pending/accepted text with truthful delivery status. Preserve prior lease previews without silent eviction.

Consumer surface: main.ts, continuous-listening.ts, TypeScript session ports/API/browser transport. Test owner is existing `web` glob in tests/quality.toml. Synthetic browser tests cover normal automatic flow, repeats, missing proof, late corrections, stale replies, Stop/Close, playback overlap and failure. No provider, account, hardware microphone, browser or physical playback validation is claimed. No dependencies or budget changes.
