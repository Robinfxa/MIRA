# MIRA foundation architecture audit

Audit date: 2026-10-03, source discovery 08:58–09:03 UTC. Mission deadline supplied by the integration owner: 2026-10-04 08:53:50 UTC. This report does not restart the source plan's T0.

Scope: read-only review of the supplied foundation and its reference documents, with this report as the only write. No bundled scripts, tests, installations, provider calls, authentication checks, secret files, publication, or production changes were performed by this audit. Recommendations below are implementation recommendations, not executed results. The repository can change during the mission; findings describe the foundation inspected at the times above.

## 1. Executive findings

1. The project is a compact, usable control-plane foundation. It is not a mostly finished voice product. Its actual loop is text input → fixed Mock/replay range → exact-fixture review → immutable effect grants → immediate DOM mutation → receipt. Preserve this loop's state authority and cancellation invariants.
2. There are no speech, microphone, character, image, or animation implementations in the inspected application. The frontend runtime has no package dependencies. There is no hidden React, audio framework, avatar model, or media asset to activate.
3. The latest mission direction makes subscription login/quota, real Google voice, and JEV/TypeSafe connectivity priority zero. Independent scene/character and cancel-safe fixture-audio work remains available as a parallel slice, without displacing those connectivity priorities. Fixed audio can demonstrate actual presentation without waiting for provider authentication, but remains truthfully labeled fixture capability until live service access is independently verified.
4. The most important serial integration is presentation semantics: one-shot DOM receipt is not audio completion, the current gate treats consumption as terminal, and the controller does not stop a running executor on every invalidation path. A live adapter alone cannot fill those gaps.
5. ENV-02 records OpenAI-family text/image/vision, Codex subscription carrier preferred; Google STT V2 and generic Google TTS; JEV/TypeSafe remains the separate Input/Output Decision route. The latest user direction, relayed by the integration owner at report completion, fixes STT to Speech-to-Text V2 and TTS to the exact requested `gemini-3.8-flash-tts`, superseding the older generic TTS choice. This audit has not verified that model's official existence, interface, availability, entitlement or streaming behavior. The mission's credential choice is Codex/ChatGPT subscription login on dot cloud; official support/capability validation belongs to the assigned authentication/voice workers. Google/JEV real access remains separately gated. No paid fallback or silent provider replacement is implied.
6. Source reports and the 164-entry architecture acceptance catalogue are historical evidence, not current test results. This audit ran no tests. In particular, the existing browser smoke is a DOM/TestClient harness and cannot establish microphone, real audio, mobile-device, Safari, or live-provider success.

## 2. Read these sources in this order

All paths are relative to the project root.

| Priority | Source | Why it matters |
|---|---|---|
| 1 | `AGENTS.md`, `CONTRIBUTING.md`, `docs/development/TESTING.md` | Mandatory layering, single owners, actual RED/GREEN, scoped test policy |
| 2 | `docs/plans/50-hour-delivery.md` | Product priorities, continuous original character experience, shared write surfaces, no reset of T0 |
| 3 | `docs/development/API_ENV.md`, `docs/development/PROVIDER_MATRIX.md` | ENV-02 provider decisions and explicit distinction between prepared configuration and usable live capability |
| 4 | `docs/reference/architecture-v0.6/docs/reference/snapshots/requirements.pdf` | Original product requirements, pages 1–6; original PDF was located, not rendered by this audit |
| 5 | `docs/reference/architecture-v0.6/docs/architecture/appendices/A2-requirements-and-tests.md` | RQ01–RQ13 product crosswalk and exact original acceptance scenarios |
| 6 | Same directory: `acceptance-catalog.json`, `A6-requirement-reuse-traceability.md` | Historical 164-case catalogue and WP/RI links; mappings are not passes |
| 7 | `docs/reference/architecture-v0.6/docs/architecture/modules/04-permits-interruption-and-recovery.md` | G02 complete grant set; G04 local stop, retention, causal restart |
| 8 | Same modules directory: `05-voice-runtime-v02.md` | One voice arbiter, audio/sample progress, TTS dependency admission, buffering and cancellation |
| 9 | Same modules directory: `06-character-memory-and-scene.md` | Original assets, capability catalogue, real exposure, action cancellation, D-M boundaries |
| 10 | Same modules directory: `08-evaluation-delivery-and-implementation.md`, `10-reuse-integration-and-work-packages.md` | Evidence levels, WP03/04 seam definitions, delivery requirements |
| 11 | `docs/implementation/ADR-F001-foundation.md` | Deliberate current subset, loopback deployment, plain TS, no audio over JSON polling |
| 12 | `docs/handoff/ENV-01.md`, `docs/development/TDD-SDD.md`, `specs/README.md` | Handoff, SDD/TDD method and legacy evidence boundaries |

The current executable feature-spec directories are only `ENV-01-development-services`, `FND-02-fixture-replay`, and `FND-03-scoped-quality`. No WP03 or WP04 feature spec/traceability exists in the inspected baseline. Add new feature evidence separately; do not relabel the immutable source catalogue as passed. The architecture guard explicitly rejects a `passed` marker in that catalogue.

### Relevant source acceptance IDs

- Product: RQ01–RQ13, especially RQ02–RQ09 and RQ11–RQ13.
- Audio/character integration: RI-08–RI-12, RI-14–RI-17.
- Immediate control: P01–P08, P11, P14–P16, P18–P22.
- Honest completion/history: M08–M15; B01–B05, B10–B15; G3-P09–P13.
- Stop/retain/restart: G4-P01–P15, G4-P18–P24.
- Provider correctness and identity: CX-P01–P12; G56-D01–D10; image-dependent work G56-M/X groups.

These IDs select assertions to implement and test; they do not automatically establish full coverage when a similar foundation test exists.

## 3. What is actually implemented

### Backend modules

| Module | Current responsibility and interface |
|---|---|
| `domain/models.py` | Immutable dataclasses for `Effect`, `Receipt`, `Fence`, `SessionState`; `EffectKind` is only subtitle/pose/scene/media; `Phase` is idle/thinking/ready/stopped/error |
| `domain/transitions.py` | Pure begin-input, stop, accept-range, seal, fail and receipt transitions; preserves received history; output-epoch rejection and presentation cutoff fences |
| `application/contracts.py` | `EffectProposal(kind, value)`; `CandidateRange(effects, fixture_id)`; `GenerationContext(user_text, user_inputs, presented_effects, output_epoch, accepted_prefix)`; simple review verdict/reason |
| `application/compiler.py` | Assigns UUID and SHA-256 over kind/value after review, maximum eight effects per range; not a capability or semantic validator |
| `application/session_actor.py` | Single state writer using short `asyncio.Lock` sections; generation/review awaits outside lock; per-turn timeout; task cancellation plus epoch rejection; request idempotence and budgets |
| `application/sessions.py` | Process-local session registry and opaque session capability token; bounded session count; close/delete |
| `application/ports/generation.py` | Async iterator of complete `CandidateRange`s, with delayed cancellation explicitly anticipated |
| `application/ports/review.py` | Review returns observation, never state or permission authority |
| `application/ports/media.py` | Unregistered extension protocols for ASR, TTS, images and visual review; comments explicitly say not implemented capability |
| `adapters/generation/mock.py` | Authored command fixtures; generic text returns hello fixture; `/fail` is synthetic failure |
| `adapters/generation/replay/` | Bounded immutable packaged scenario; per-call cursor; validated fixture references; explicit complete/fail ending |
| `adapters/review/mock.py` | Exact equality to shared authored fixture catalogue; rejects arbitrary candidates |
| `adapters/journal/memory.py` | Bounded diagnostics only, not persistent replay or durable user history |
| `bootstrap/providers.py` | Registers only mock/replay generation plus fixture review; rejects live selection and external/paid-call flags |
| `bootstrap/container.py` | Creates per-app registry/journal/actors; provider injection is available for controlled composition/tests |
| `config/loader.py` | Sole runtime configuration/environment entrypoint; immutable typed settings are passed into composition |
| `entrypoints/http/` | Strict frozen DTOs, DTO mapping, session routes, errors and local-only application/static boundary |

### Public protocol and transport

- Wire version is exactly `0.1.0-foundation`; it is explicitly not voice-v0.2.
- `/api/v1`: health; session create/get/delete; text inputs; stop; receipts; diagnostics events.
- Input carries request UUID, activity sequence, presentation cutoff, and nonblank text up to 2,000 characters.
- `SessionView` includes complete active grant set and already receipted effects, branch/control counters, phase, request ID and sealed status.
- Current receipt is one terminal fact per effect: identity/digest/epoch/activity and integer presentation sequence. It has no started/progress/interrupted/failed state, samples, partial exposure, uncertainty, duration or channel-specific coverage.
- Current health is hardcoded Mock and all live flags false. A future live profile must not continue reporting this as if it were accurate capability introspection.
- HTTP control body is capped at 32 KiB; transfer-encoded bodies are rejected. There is no audio upload/data channel, WebSocket or SSE implementation.
- Loopback host and allowed origins are enforced; runtime is one process/worker with in-memory sessions. It is not public production authentication.
- Client polls snapshots every 200 ms; ordinary fetch timeout is 5 seconds. Polling is only a control-workbench mechanism, not an audio transport.

### Frontend modules

| Module | Current responsibility |
|---|---|
| `features/presentation/permit-gate.ts` | Local input/stop latch, identity and revision validation, complete-set check, one-shot de-duplication and receipt sequence |
| `features/presentation/ports.ts` | `EffectExecutor.apply(effect): void`, `prepareInput(): void`, `stop(): void` |
| `features/presentation/dom-executor.ts` | Immediate text/dataset/hidden-state changes, expressly a diagnostic adapter |
| `features/session/controller.ts` | Connect/poll/input/stop/close coordinator; installs snapshots and immediately acknowledges DOM application |
| `features/session/api-client.ts` | Same-origin HTTP and in-memory session token; never stores token in URL or localStorage |
| `features/session/ports.ts` | Injectable session transport interface |
| `shared/protocol.ts` | Narrow runtime parser hardcoded to the foundation version, effect kinds and phases |
| `shared/generated/contracts.ts` | Generated public DTO types; read-only output |
| `app/main.ts` | DOM wiring and current browser composition root |

### Stack and assets

- Backend declaration: Python 3.11–3.13, FastAPI, Pydantic, Uvicorn, python-dotenv; exact recorded dependency snapshots in `requirements/*.lock`. The locks are not hash-locked wheels and their comments do not establish a fresh install here.
- Frontend: TypeScript 5.8.3, native ES2022 modules, DOM; strict checks include `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, unused code and switch fallthrough. No frontend runtime package is declared.
- Node package declares Node >=22.12.0. README's previously tested runtime versions are historical claims only.
- `apps/web/public` is served at `/assets`; `apps/web/dist` at `/dist`; `index.html` at `/`. Repo root is never a static mount.
- The sole current public asset is `app.css`. No WAV/MP3/OGG/WebM/MP4/PNG/JPG/SVG files were found under inspected `apps/` or `tests/`.
- Scene has existing `data-stage`, `data-scene-label`, `data-pose`, `data-photo`, `data-subtitle` slots. There is no microphone button or audio element.
- Files placed under `apps/web/public` can be served without an API/schema change. This is an asset-serving seam, not approval to play them or evidence of correct receipts.
- Python wheel verification copies only `apps/api/src` and verifies three replay JSON resources. It does not validate packaging or availability of web/media assets.

## 4. Highest-risk compatibility gaps

### 4.1 Presentation lifecycle must change before honest continuous audio

The controller currently calls `effects.apply(effect)` and then immediately `gate.consume(effect)`. That is suitable only for the stated instant DOM scope. Turning apply into audio enqueue while leaving receipt timing unchanged would incorrectly claim an entire response was presented before playback.

`PresentationGate.consume` adds the effect ID to a permanently consumed set. `allows(effect)` thereafter returns false, even when the grant remains valid. Therefore it cannot also be used unmodified to authorize later packets of an already-started stream. Started/consumed identity and currently valid permission require distinct semantics.

Current lifecycle omissions become material once effects are asynchronous:

- New input calls `prepareInput`, whose implementation only clears subtitle text.
- Close blocks the gate and deletes the server session but never calls executor stop.
- Poll failure blocks new admission but does not stop already running output.
- Receipt-send failure reports an error without blocking the gate or stopping output.
- Grant revocation/error snapshot replaces the gate snapshot but does not notify a running executor to revoke its future submissions.
- A callback after `apply` has no generation token or final-sink guard in the current executor contract.

These are static findings about a synchronous workbench, not failures of a claimed existing audio implementation. Add focused tests at these exact seams when introducing asynchronous output.

### 4.2 Current contracts are intentionally fixture-sized

- No speech effect, resource manifest, dependencies, composite effect lifecycle, audio stream identity, sample range, caption alignment or partial receipt exists.
- Four visible product states cannot simply map from the backend enum: listening and speaking are absent, while ready means granted work rather than physically speaking.
- `CandidateRange.fixture_id` is mandatory and review is exact fixture equality. Do not make arbitrary live text look like a fixture or weaken this reviewer.
- `ReviewObservation` has no checked content digest, coverage or question identity. A live review binding must be explicit rather than inferred from an unrelated `allow`.
- `GenerationContext` contains reliable user text and fully receipted effects, but no implemented structured ResponseContract, input-decision snapshot, capabilities, affect, current visible-object identity or unresolved/partial exposure model.
- `compile_range` hashes arbitrary strings after review; it is not sufficient to reject unknown action names, URLs, or unattested media.
- Generation natural iterator EOF currently means seal after one or more candidates. Live adapters must distinguish valid provider completion from truncated streams and abnormal termination.
- Scene retention is currently literal DOM retention after stop; there is no independently represented retained-object permission/visibility state. Historical exposure does not prove an object remains currently visible.

### 4.3 Schema export is narrow

`tools/export_contracts.py` supports `$ref`, const/enum, `anyOf`, primitive types, arrays and constrained property objects. New schema vocabulary outside this subset fails intentionally. Freeze the smallest required public vocabulary first and verify generated types; do not hand-edit OpenAPI or generated TS to get around export failures.

## 5. Product gap assessment from source inspection

| Requirement | Foundation status | Missing evidence/work |
|---|---|---|
| Mobile-first scene | Basic responsive workbench exists | Original character scene and actual device interaction |
| Text/multi-turn | Text API and stored input history exist | Natural dialogue, reliable boundary understanding, longer coherent scene |
| Microphone/ASR | Unregistered protocol only | Capture, permission/error flow, sample metadata, Google adapter and actual recognition |
| Voice/subtitles | Subtitle DOM only | TTS, stream transport, single voice sink, honest timing/progress/history |
| Four states | Diagnostic server-phase label | Idle/listening/thinking/speaking visual behavior tied to actual activity |
| Three expressions/two actions | None | Original assets, capability manifest, execution/cancellation outcomes |
| Environment/content event | Fixed placeholder scene/photo commands | Real visible controlled assets, current-content causal trigger, failure path |
| Local stop/no resurrection | Relevant core logic exists | Asynchronous renderer/audio final-sink proof and actual device tail measurement |
| Actual presented history | Whole-effect DOM receipts only | Partial/unknown speech, media visibility and interruption outcomes |
| Live LLM/review | Slots fail closed | Carrier validation, generation adapter, live JEV review and controlled context |
| Images/D-M | Unregistered protocols only | Optional separately admitted slow path; no substitute for core scene quality |
| No-key experience | Fixed Mock/replay path exists | Same new renderer/audio/controller contract, clear fixture label |
| Release | Source/docs/historical evidence | Fresh final checks, artifact/asset validation, actual 3–5 minute recording and truthful scope report |

Do not make online image generation, Hindsight, automatic VAD/backchannels, semantic resume, account pools, or a second runtime the new critical path. The source explicitly keeps these optional/deferred or out of scope.

## 6. Parallel slice ownership recommendation

The following are proposed ownership boundaries, not changes performed by this audit. An integration owner must assign filenames before workers edit. Repository instructions prefer separate worktrees, a shared base commit, bounded aggregate jobs and coherent source snapshots. Latest priority-zero subscription, voice and JEV investigations take precedence over alphabetical slice order below.

### A. Scene and original character, WP04

Own a new isolated character/scene renderer module and its asset subdirectory under `apps/web/public`, plus renderer-specific tests. Deliver visible four-state treatment, three actual expressions, two actual non-speech actions, scene change and photo/display capability. Each declared capability must correspond to real assets and interruption behavior.

Can begin without API changes: asset creation/inspection, responsive scene rendering and renderer unit tests using injected approved effect inputs. Existing static mount is sufficient. Reserve `index.html`/`app.css` for this worker only if no other worker needs to alter them; final `app/main.ts` wiring belongs to integrator. Do not make renderer choose conversation policy or start a second audio source. Do not treat a static fallback as normal-path expression/action coverage.

### B. Browser audio and local control, WP03

Own a new local audio-sink/arbiter module and focused tests, working first with fixed licensed/authored fixture audio and injectable clocks/sinks. Prove cancellation of prepared, queued and in-progress output, no late callback revival, one character voice path, bounded queue, and actual lifecycle callbacks. Keep synthetic callback tests separate from real browser audio observations.

Can begin independently: sink abstraction, deterministic cancellation tests and fixture-asset loading. Must consume integrator-frozen effect and progress interfaces before connecting into controller/gate. Do not independently rewrite `permit-gate.ts`, `controller.ts` or generated contracts. Do not introduce browser speech synthesis as an unannounced replacement for the chosen Google TTS route.

### C. Google speech connectivity/adapters, WP03 — latest mission priority zero

First verify the explicitly requested Speech-to-Text V2 and `gemini-3.8-flash-tts` service routes and capability gaps. The exact requested TTS model must not be silently replaced with the older generic Cloud TTS configuration. After the integration owner freezes required narrow port additions, own only adapter modules and synthetic transport tests. Preserve STT and TTS as separate capability adapters. Importing the module must not initialize credentials, SDK clients or a service. Do not independently edit loader/bootstrap/locks.

The present `AudioPacket`/`TranscriptRevision` protocols are useful input vocabulary but lack a fully specified lifecycle, channel metadata and capability/cancellation receipts. Surface needed changes to the integration owner. Real project/ADC/voice access is a separate gate; successful fixture tests do not prove it.

### D. Subscription and JEV connectivity/adapters, WP01 — latest mission priority zero

Own adapter-specific modules/tests only after the official Codex subscription capability investigation identifies the supported route. The current mission choice does not authorize reading auth files or building token handling. Use reconstructed reliable history and filter tools/logs out of candidate content. Treat provider error/end/cancellation as different outcomes.

JEV remains the separate chosen review route; no silent OpenAI judge replacement. Synthetic protocol tests can proceed once their contract is frozen, while real access is separately gated. The fixture reviewer remains exact and private to Mock/replay.

### E. Adversarial tests and delivery evidence, WP07/08

Own new tests and mission evidence files against frozen interfaces. Prioritize interrupted/repeated/failed flows, mobile layout and fresh-start behavior. Test worker supplies desired `tests/quality.toml` registrations to its single owner. Do not overwrite historical `docs/verification` receipts or run unbounded full suites while other workers edit shared files.

This worker can independently specify/test controllable fake sinks, duplicate/reordered grants, late completions and close/reconnect behavior, while the integrator owns the behavior under test and final suite execution.

## 7. Changes to integrate serially

### Explicit shared owners in current instructions

- `apps/api/src/mira/entrypoints/http/schemas.py`
- `apps/api/src/mira/domain/transitions.py`
- `apps/api/src/mira/bootstrap/providers.py` and `bootstrap/container.py`
- `apps/api/src/mira/config/loader.py`
- `tests/quality.toml` test ownership and conservative impact rules

### Closely coupled files that need one named integration owner

- `domain/models.py`; `application/contracts.py`; `application/ports/media.py`
- `application/compiler.py`, `application/session_actor.py`
- `entrypoints/http/mappers.py`, `routes.py`, and any media/data endpoint boundary in `app.py`
- `features/presentation/ports.ts`, `permit-gate.ts`
- `features/session/controller.ts`, `ports.ts`, `api-client.ts`
- `shared/protocol.ts` and final `app/main.ts` composition
- `adapters/fixture_catalog.py` if fixture meaning/content changes
- `config/settings.py`, `config/service_settings.py`, public profiles, dependency manifests/locks
- Generated OpenAPI/TS, updated only through the exporter

### Recommended serial integration sequence

1. Preserve the foundation base and set explicit ownership. Resolve only the minimum effect lifecycle, audio progress, valid-now authorization and retained-media semantics needed for the first vertical slice.
2. Freeze typed internal/public contracts and associated negative tests, including wire-version handling. Add rather than reinterpret legacy instant receipts. Separate actual presentation phase from plan readiness where needed.
3. Integrate executor lifecycle and local revocation paths with the same gate/controller; prove new input, explicit stop, server revoke, failure, close and late callbacks all suppress future output.
4. Connect fixture scene/audio through the same actor/permit/executor/receipt route. Establish partial/failed outcomes and actual history before live provider complexity.
5. Register independently tested real adapters only after their access/capability gates are cleared. Keep external/paid settings explicit, fail closed on required review unavailability, and keep no-key fixtures separate but on the same control contract.
6. Run affected integration checks on one coherent snapshot; reserve full/release and fresh UI recording for the integration owner.

## 8. Safety and operational boundaries to preserve

- Domain stays standard-library-only; application never imports HTTP, config, bootstrap or concrete adapters. No environment reads outside loader, no import-time resources, no global service locator.
- One actor, one control sequence, one role-voice arbiter. A media framework may execute, but may not independently decide to answer or authorize playback.
- Stop acts locally before network. A higher grant revision alone never clears stop; only a causal new reliable request can establish a new branch. Empty/noisy input does not reopen the old response.
- Old callbacks may close resources or add verified earlier facts; they may not play, reveal, mark a canceled action completed, or advance story.
- Reliable user inputs and real already-presented history survive cancellation. Unknown/partial output stays unknown/partial. Clearing subtitles cannot undo previously disclosed text.
- Fixed reviewer only approves fixed catalogue entries. Missing live review cannot default to allow. Media intent approval is not approval of unknown generated bytes.
- Image display must bind actual asset identity, actual visual review and current permission. No arbitrary URLs, code, dynamic instructions or unreviewed partial images.
- Character actions with sound cannot bypass the voice arbiter; mute embedded motion sound unless separately approved and controlled. Audio end stops lip motion, not automatically every persistent affect.
- No credential extraction, private auth-file reads, automatic login reuse across unknown environments, implicit paid fallback, public production exposure or account changes under this audit.
- The loopback host/security boundary is a real deployment constraint. A publicly reachable build needs deliberate authorized deployment work rather than removing checks to make a preview open.

## 9. Test inventory and active commands

### Present source coverage

- Architecture: dependency layering, sole environment-reader convention, no app import-time connections, contract drift and untouched source acceptance statuses.
- Domain: epoch/activity invalidation, monotonic cutoff, complete-set append, duplicate identities, seal versus receipt completion, late valid and after-stop receipts.
- Actor: uncooperative generator cancellation, stop without waiting, reject/unknown review, empty/time-limited generation failure, idempotency, budgets and history projection.
- Providers/contracts: fixed/replay generator conformance, script schema/size/duplicate keys, deterministic cancellation barriers, explicit failure.
- HTTP: session isolation/capability, input/grant/receipt/stop/delete, origin/body limits, sanitized errors, fail-closed live selection; replay integration.
- Frontend: one test file with 20 declared Node tests, limited to gate/parser behavior. No controller/executor/audio/microphone tests are present in this baseline.
- Browser: `tests/browser/smoke.py` injects a TestClient-backed fetch into Chromium and checks Mock DOM and desktop/mobile viewport behavior. It writes fixed historical report/screenshot paths. It is not in the default lane catalogue and does not exercise actual browser networking or audio.

### Commands defined by current files, not executed here

```bash
# Focused behavior: choose an actual node and keep RED/GREEN scope identical.
python -m pytest tests/unit/test_actor.py::test_uncooperative_provider_result_cannot_revive_stop -q

# Frontend isolated build + Node tests, suitable for parallel work.
python tools/check.py --lane web --jobs 1

# Relevant narrow group; final selection follows changed files.
python tools/check.py --lane domain actor providers http --jobs 3

# ZIP/non-Git selector and explicit impact preview.
python tools/check.py --files apps/web/src/features/presentation/permit-gate.ts --plan

# Once an actual shared Git baseline exists, include committed changes.
python tools/check.py --affected --base <shared-base> --jobs 3

# Integrator only, against a coherent final source snapshot.
python tools/check.py --full --jobs 3
python tools/check.py --release --jobs 3

# Schema owner only: generate, then verify drift.
python tools/export_contracts.py
python tools/export_contracts.py --check

# Unique evidence IDs; only synthetic/offline inputs in this recorder.
python tools/record_check.py --feature wp03 --id <unique-red-id> --expect-exit 1 -- python -m pytest <node> -q
```

`npm test` is valid but builds into shared `apps/web/dist`; the `web` quality lane instead writes a unique run-owned output directory and sets `MIRA_TEST_WEB_DIST`. Prefer the latter for parallel work. Full currently means the default offline lanes, not browser/audio/live account/device validation. Release adds serial wheel and loopback fixture checks, not production deployment or remote CI.

Do not run `scripts/dev` as a harmless inspection: its documented startup can install missing dependencies. Do not casually rerun the historical browser smoke into existing evidence paths. New tests require one catalogue owner and real collected node IDs. Shared domain/ports/schema/locks/tests-policy changes conservatively expand impact; unknown paths must not be silently omitted.

## 10. Fixed upstream references versus installed code

The source records useful fixed upstream pointers, but none of these libraries is installed/used by this foundation's declared application dependencies:

- Pipecat C12/C13: `cae1f51a4060b6acf679991e75374520069ef016`, output transport and interruption frames.
- LiveKit C14: `8de48c229655d10ca3df3274ba77c20eef50c6c1`, speech lifecycle reference.
- Charivo C15/C16: `62f3a4369643d4e132cfc25104a15422e1155c05`, render manager and package-specific Live2D licenses.
- AIRI C17: `731123861093abfd7fc34c0654ba9f99206ab944`, ordered synthesis/playback and cancellation.
- Open-LLM-VTuber C18: `992309c0aa19845960228f880013d4685fde93b5`, interruption and heard-response history.

Exact source URLs, blob identities and prior read ranges are in `docs/reference/architecture-v0.6/docs/architecture/appendices/A5-open-source-evidence-and-licenses.md`. This audit read those records, not current upstream source or APIs. Their compatibility, availability, licenses and ability to meet this mission still require appropriate verification before adoption. They are references, not a reason to add a large framework or second session authority.

## 11. Audit completion and open evidence

Completed: architecture/source inventory, exact ownership seams, source acceptance location, provider decisions, current frontend/test stack, implementation risks and bounded parallel recommendations.

Not performed: any current test run, dependency installation, fresh build, browser/device execution, actual sound/microphone measurement, current upstream API check, provider authentication/entitlement check, live inference, generated-media approval, publication or production deployment.

Only this report was written. Preserve these distinctions in the mission's final delivery report.
