# WP04 verification

## Result

Implemented and ready for composition by the integration owner. Final focused isolated snapshot passes TypeScript and **38 Node tests: 18 scene tests + 20 inherited permit-gate tests**. No browser or audio acceptance pass is claimed. This slice does not edit main.ts or the controller, so the integrating owner still needs to select `SceneEffectExecutor` and connect real phase/mode/voice events.

Source base: `ebb578dde665c9c7269e4a64b508182680b2fa66`. Work was scoped to the assigned shared paths. Runs compile to unique temporary outputs, never shared `apps/web/dist`. Existing test ownership is the `web` lane's `tests/web/*.test.mjs` glob. No registry, protocol owner, generated contracts, playback controller, or provider files were edited by this slice.

## Actual checks

| Evidence | Actual result | Scope |
|---|---|---|
| `runs/001-red-state.txt` | 10 failed, exit 1, expected | Ten behavioral assertions against deliberate typed no-op scene skeletons. Tests collected normally; this was not a missing-module/collection failure. |
| `runs/002-red-markup.txt` | 6 failed, exit 1, expected | Scene markup/animation/assets assertions against original workbench HTML/CSS. |
| `runs/003-green-scene.txt` | 16 passed, exit 0 | Same original scene assertions after implementation; isolated TypeScript compile also succeeded. |
| `runs/004-static-render.txt` | blocked, exit 134 | Headless Chromium attempted a self-contained local static HTML file. It failed before loading: `socket() failed: Operation not permitted`. No port/alias/sandbox-flag bypass was attempted. |
| `runs/005-asset-render.txt` | exit 0 | Inkscape rasterized original character SVG. Warnings about unavailable writable user-profile/font caches did not prevent output. PNG was visually inspected. |
| `runs/006-environment-render.txt` | output files produced, final exit 0 | Original café and coastal illustration were rasterized and visually inspected. This is asset inspection, not a browser render. |
| `runs/007-isolated-scene-20261003t0935/report.json` | failed: 60 pass, 1 collection failure | An overly broad snapshot run included the concurrent audio tests but did not copy their public worklet asset. Its `ENOENT` is a snapshot scope error, not a discovered audio regression. This run is retained as failed. |
| `runs/008-focused-snapshot-20261003t0936/report.json` | TypeScript 0; 38 tests passed; source unchanged during copy | Correct focused snapshot: 18 scene + 20 inherited permit-gate tests. Full source hashes and commands recorded. |
| `runs/009-expression-render.txt` | exit 0 | Four original expression variants rendered as a labeled static contact sheet and visually inspected. |

Two added regressions (speech rejected by the visual executor, and stop copy does not invent unseen photos) were first run green and are recorded as regression coverage, not retroactively claimed RED/GREEN.

The execution container's wall clock is approximately four hours behind the task's UTC reminders. Snapshot report timestamps explicitly use the container clock; run-name times reflect task reminders. No timestamps were silently rewritten.

## Behavioral coverage

- Immutable structured pose/scene effects and all four expression variants.
- Rain environment plus looking out of the window.
- Media is absent until an admitted media effect; unrelated subtitle content cannot reveal it.
- Unknown pose/scene/media and misrouted speech fail closed.
- Four local presentation phases have distinct stage attributes and accessible descriptions.
- Subtitle strings are assigned as literal text; they do not start speech.
- Stop immediately ends speaking presentation, preserving displayed artifact, environment and action.
- New input clears old subtitles, enters thinking, and preserves presented visual facts.
- Unsupported effects leave an already displayed scene unchanged.
- Existing selectors, adult metadata, independently animated layers, explicit CSS phases/actions, narrow layouts, reduced motion, labeled controls, collapsed diagnostics and local-only assets.
- All 20 inherited local gate tests rerun, including stale grant, stop cutoff, late higher permit, identity-conflict and consumption-once negative controls.

The current repository traceability checker only collects Python test node IDs. This feature's Node names are documented here rather than introducing a fabricated Python mapping or modifying the shared checker.

## Visual evidence

`previews/mira-character.png`, `previews/cafe-night.png`, `previews/trip-memory.png`, and `previews/expressions-study.png` were actually generated and inspected. They establish that the original SVG assets render and that face variants differ. They do not establish HTML layout, animation playback, eye/blink timing, microphone input, audible output, browser cancellation or mobile compatibility.

Self-contained static HTML previews have application scripts removed and are labeled as offline visual previews. They are convenience source artifacts for review in an authorized browser, not an interactive demo or successful browser evidence.

## Stop-access source follow-up — 2026-10-03

The fixed Stop control now precedes the rehearsal guide in conversation-controls source order, and it remains the sole `data-stop` button bound through the existing `element('[data-stop]')` handler. The existing disabled fieldset at startup, rehearsal commands, synthetic-input control, ordinary presets, text composer, PTT hook, and voice-hint selectors are retained. The longer rehearsal explanation and ordered steps are in native closed-by-default `<details>/<summary>`; the summary keeps the native disclosure marker, existing summary focus-visible outline, and a 44px minimum interaction height. Fixed command/input controls remain outside that disclosure.

This is source/DOM-order improvement only. The static-layout review identified a source-order risk, not pixel-measured visibility. The compliant Chromium attempt remains blocked before render by the OS sandbox as recorded in `docs/verification/static-layout/20261003T1253Z-static-layout/report.md`; no viewport, keyboard, screen-reader, or device acceptance is claimed.

Focused evidence, recorded with unique IDs under `docs/verification/wp04/runs/`:

- `002-red-stop-and-disclosure`: 2 targeted cases failed as expected (Stop after the guide; long help lacked native disclosure). Exit 1; `changed_during_run` empty.
- `005-green-stop-access-final`: 8 scene-markup cases passed, including unique labeled Stop control, source order, collapsed disclosure, outside-disclosure fixed controls, existing handler selector, and disabled startup fieldset. Exit 0; `changed_during_run` empty.
- Exact source-scope SHA-256 files in each run cover `index.html`, `app.css`, `scene-markup.test.mjs`, and the read-only `main.ts` selector hook; each scope matched before/after its own test run. The final recorded test strengthened uniqueness to the whole HTML document after the RED run; the two targeted behavior cases are the same named cases.

Only `index.html`, `app.css`, the existing `tests/web/scene-markup.test.mjs`, this spec and verification record were edited for this slice. The existing `web` wildcard already includes the test, so no quality-owner registry was changed. The full web/affected quality lane was not run during parallel integration; the integration owner must run it against the frozen combined sources.

## Required integration/acceptance work still not run in this slice

- Actual 360px and desktop browser layout/animation inspection, including scrolling to controls and long subtitles.
- Actual local recording/listening and playback/speaking phase transitions, permission failure feedback and mic keyboard behavior.
- Gate-aware stale playback callback suppression by the real audio owner; the visual hook deliberately has no parallel identity/permission authority.
- Real audio stop, delayed audio/media callbacks and follow-on input.
- Backend structured effect support beyond the historical values, and truthful mode/voice labeling.
- Original photo fixture caption update through the owned review/digest path.
- Final all-front-end integration, affected quality gate, clean startup, 3–5 minute recording and true mobile/device validation.
