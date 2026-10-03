# WP07 bounded speech-cue causality

Base: inherited integrated mission tree, original T0 unchanged. Owner: cue-causality repair worker under director. Shared surface authorization: domain Effect, application compiler, canonical HTTP schema/export, Codex candidate parser, frontend gate/protocol/controller. Actor stage/seal, diagnostics adapters and audio-history projection remain with their owners.

Tests: `providers` owns tests/contracts/test_cue_compilation.py through its existing wildcard; `web` owns tests/web/controller-cues.test.mjs. Consumers: compiler, mock/replay, Codex author, HTTP mapper, cue gate, single audio sink, scene executor. Resources: Python 3.13, TypeScript, Node, injected synthetic Web Audio. No live credentials/providers, browser/device or hearing qualification. Director owns coherent combined affected/full run.

## WP07-001 Compiler-owned bounded association
Given a reviewed CandidateRange, compiler assigns a fresh cue_id and the sole speech effect's ID as cue_speech_id (null for independent text/visual ranges). A speech cue contains at most one speech and one subtitle; ambiguous candidates fail closed. Text need not equal speech. Provider output cannot assign effect/cue IDs. Application digest binds these fields; identity and same-cue membership cannot drift. Mock/replay visual-only ranges retain immediate presentation.

## WP07-002 Actual software-source boundary
Given two cumulative speech cues, receiving grants, opening speech transport or accepting queued PCM does not show/receipt their captions or authored controls. Only the exact cue's first actual source submission permits those non-speech effects. Repeated submissions, polling and backpressure cannot present future cues or duplicate receipts. Completion starts the next speech transport, whose cue still waits for its own source submission. Independent visual-only or text-only ranges remain immediate.

## WP07-003 Cancellation and truthful history
Given Stop, new input, error or revocation before a future cue's first source submission, its caption/control receives no presentation receipt and stale callbacks cannot revive it. Already displayed scene/photo remain through the existing scene executor. Software-source submission is neither physical hearing nor word alignment and does not create an audio rendered/completed claim.

## WP07-004 Strict metadata and safe errors
Given missing, malformed, duplicate, mismatched or mutable speech cue metadata, parser/gate fail closed. Legacy visual-only snapshots and isolated legacy speech remain compatible, while mixed legacy speech/visual sets are ambiguous and rejected. Partial presented history validates field shape without demanding its unpresented speech peer. Session errors use safeSessionError even after view.update; unknown server strings never overwrite safe copy. Existing HTTP request IDs remain in safe transport errors.

Exact permanent Node titles and Python tests are the behavioral mapping; recorded runs are software evidence only. No generic timeline framework, word synchronizer, second playback controller or inferred text-equality pairing is introduced.

## WP07-005 Fixed original-character grounding
Given a generation prompt, `author_policy` is serialized from the existing typed `mira26_author_policy()` source, preserving its original fictional adult photographer, fictional rainy-cafe setting and controlled-action limits. User input remains separate, never silently promoted into character policy or private user facts. The prompt's bounded cue rule does not fabricate subtitles from audio or trigger speech from subtitles. Observable Python test: `test_codex_prompt_uses_authoritative_original_character_policy`.

## Adversarial evidence references
- Compiler and candidate identity/ambiguity: `tests/contracts/test_cue_compilation.py`, first eight cases (actual 7 fail / 1 pass RED, then 8 pass GREEN).
- Source gating: `captions wait for their own actual source submission, never grant or queued PCM`.
- Independent controls: `independent visual and standalone text cues remain immediate while authored speech controls wait`.
- Stop: `Stop before cue two source prevents its subtitle receipt and stale submissions` and `Stop during pending source resume prevents even first caption and receipt`.
- Long speech: `backpressure and repeated snapshots never advance captions before cue completion`.
- Revocation: `revocation before source submission blocks all future cue captions`.
- Actual scene preservation: `controller Stop preserves actual rendered scene and photo but never future cue text`.
- Superseding input: `new input while future cue PCM waits cannot present the old cue`.
- Metadata: the nine `cue metadata fails closed` cases, `cue metadata is immutable across revisions and caller substitutions`, and `malformed cue replacement synchronously disconnects current source before callbacks`.
- Safe errors: generation_timeout, an unknown private string, and prototype-like unknown constructor/toString/__proto__ codes; `HTTP safe error request ID survives controller error handling`.

Exact run evidence and immutable RED test-prefix snapshots are in `docs/verification/wp07-cue-causality/verification.md`. Node requirements are recorded by executable titles because the inherited machine traceability checker collects pytest only; no false pytest mappings are supplied.
