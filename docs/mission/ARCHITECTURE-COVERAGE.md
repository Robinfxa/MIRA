# Architecture coverage: published1659 and local-only management

Status reviewed2026-10-04 18:37 UTC. This source/spec comparison is not a claim that the architecture book is complete. Published1515 includes opt-in read-only Actor recall with operator pairing;1659 adds manual paired memory editing and a read-only setup doctor. This candidate adds a provider-free local console using the same scoped store and separate write consent. Its new full-release evidence belongs to its matching START-HERE.

| Module | Existing implemented slice | Important remaining scope |
| --- | --- | --- |
| M01 state/authority | In-process Actor, revisions, epochs, grants, receipts and bounded diagnostic journal | Durable Actor source-event/outbox/state recovery and restart-safe causal history |
| M02 decisions/contract | Typed decision snapshots, JEV input/output gates, fixed author policy, versioned uncertainty handling | Complete memory/disclosure provenance in the shared generation/review context |
| M03 plan/completion | Compiled candidate ranges/effects and accepted-prefix control | Rich authored storylet/OpenIntent lifecycle and memory-backed planning |
| M04 permits/interruption | Local-first Stop, stale-output fences, permit validation, receipt-prefix barriers | Durable recovery across process loss and full authored scene/intent continuation |
| M05 voice | Real STT/TTS adapters, software capture/playback/cancellation, component provider evidence | Human microphone/speaker/browser acceptance and a continuous natural voice session |
| M06 character/memory/scene | Fixed typed AuthorPolicy,12 Pixi frames, scene/receipt lifecycle;1212 manual scoped SQLite/CLI;1515 opt-in shared Actor recall; 1659 explicit paired manual management; candidate provider-free local console | Automatic memory extraction, full Canon/LearnedStance, storylet memory, controlled dynamic-media review and real memory-dialogue quality |
| M07 failure/routines | Bounded timeouts, structured errors, UNKNOWN system notice, capacity and recovery paths | Authored recurring-scene/routine subsystem; no generic scheduler is claimed |
| M08 evaluation/delivery | Layered tests, exact manifests, source/public releases, install/restore checks | Real3–5 minute recording, phone/browser interaction and natural-language quality evaluation |
| M09 provider/auth/usage | Explicit native Codex, Google and JEV adapters; scoped real-call receipts and budgets | Portable user-environment acceptance, integrated generated-image plus direct-image-review path |
| M10 reuse/integration | Layered ports/adapters/bootstrap, locked dependencies and notices | Remaining memory/outbox/story/media integrations described by the book |

## What “memory” means in0952

`adapters/journal/memory.py` contains a bounded, transient diagnostic deque. Its port explicitly says it is not a durable transaction log. `SessionState.user_inputs`, receipts and audio progress support continuity inside the current process/session; they do not survive a new process as an application memory database. Separately, `mira26_author_policy()` supplies typed fixed character facts and allowed controls. These are useful existing pieces, but neither is a full long-term persona or memory system.

## Published1212 manual-memory slice

Published1212 implements a local, explicit-consent evidence store and local operator workflow: source/version/scope labels, persistence across restart, correction/supersession, reversible soft forgetting, provenance-aware bounded recall and a structured context packet. It uses local SQLite rather than creating an external memory account. Defaults do not record actual conversations. Recalled text is untrusted data and does not grant actions, override current permissions or prove that a proposed action happened. The CLI cannot fabricate presentation receipts.

This target does **not** claim automatic ingestion from the Actor, automatic cross-session model recall, personality learning, Hindsight integration or completed shared story state. Those require their own reliable source-event production, matching generation/review projection, explicit privacy configuration and tests. The test results and exact implemented subset will be recorded in the next matching delivery, without rewriting0952 evidence.

Primary architecture references: [M01](../reference/architecture-v0.6/docs/architecture/modules/01-state-and-authority.md), [M06](../reference/architecture-v0.6/docs/architecture/modules/06-character-memory-and-scene.md), [M10](../reference/architecture-v0.6/docs/architecture/modules/10-reuse-integration-and-work-packages.md). Device and PDF acceptance remain in [CURRENT-ACCEPTANCE](CURRENT-ACCEPTANCE.md).

Focused implementation evidence:43 combined architecture/store/CLI/subprocess tests passed on stable source, plus12 independent synthetic safety controls. The actual CLI opens a real SQLite store across separate processes; it is not a mocked persistence demonstration. Full candidate release and publication remain separately recorded in the corresponding delivery. Mac platform pin compatibility is also included in that next candidate, with no actual Mac live inference claim. The user later observed offline rendering and is diagnosing their metadata setup.

## Published1515 application recall, software evidence only

Published1515 composes a private read-only SQLite worker into the existing
Actor. The scope is operator-selected at startup; browser/model input cannot
choose it. An explicit per-launch private-file pairing code gates private
API/session creation and database opening; this boundary passed independent synthetic privacy/lifecycle acceptance on1515. A separate transmission opt-in names Codex generation and TypeSafe
JEV output review. Input permission classification omits memory text. The same
immutable, source-labelled packet is generation/review-bound, with revision
checks before issuing new grants; Stop/new input/Close discard late results.
Raw model-input/output capture is suppressed on memory-enabled turns. Default
rehearsal and text startup without memory options do not read the database.

Two synthetic HTTP integration paths have passed, including the actual
development factory and production adapters with fake transports. They prove
wiring and no database mutation, not live model interpretation or full M06.
Only manually saved USER_STATEMENT evidence is admitted; authored secrets,
interpretations, generated visualizations and unverified presentation sources
remain excluded. Voice+memory is rejected until its additional Google recipient
consent is implemented. See [Actor memory](../development/ACTOR_MEMORY.md).

User device feedback at12:07–12:20 confirms a visible detailed portrait and
whole-frame motion, with stiffness, weak breathing and background-style mismatch.
It does not establish full browser/audio/video acceptance. Layered local motion
is a separate design task; no new rig is claimed in this memory code slice.

## Next-stage explicit management

The paired text app can separately opt into manually confirmed save/correction/soft-forget/restore operations. A fixed local scope, strict revision CAS, operation-ID replay rules, bounded pages and close/revoke fences protect this path. Actual synthetic HTTP edits invalidate stale Actor candidates; newly submitted input can use the new revision. These are manual user statements, not automatic learning or durable Actor history. Local editing and provider transmission retain separate consent. No actual user memory or provider calls are included in this candidate acceptance.
