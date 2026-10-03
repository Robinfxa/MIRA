# Integration handoff

## Render hook

Import `SceneEffectExecutor` from `features/presentation/scene-executor.js`, construct it with the existing `[data-stage]` element, and use it where the existing diagnostic `DomEffectExecutor` was composed. Do not instantiate a second `SessionController` or `PresentationGate`.

The existing `apply(effect)`, `prepareInput()`, and `stop()` contract is supported. `apply()` is synchronous visual consumption only and must remain downstream of the gate. It rejects unsupported kinds (including `speech`) and unknown pose/scene/media values without asset lookup, remote URL use, or a false successful receipt.

The audio coordinator should route approved `speech` to its own real audio path and call scene phase hooks from current, non-stale playback/capture events. Subtitle arrival alone deliberately does not set `speaking`.

## Local presentation hooks

- `setPhase('idle' | 'listening' | 'thinking' | 'speaking')`
- `setExpression('calm' | 'warm' | 'curious' | 'reflective')`

These hooks present already-established local facts. They do not add backend phases, check identities, create grants, start or stop audio, or schedule callbacks. The integrating audio/capture owner must suppress stale callbacks before calling them, including late `playing`/`ended` events after stop. Avoid setting `idle` merely because a backend snapshot is ready while authorized audio is still playing.

`prepareInput()` clears the old subtitle, changes phase to thinking, and keeps persistent photo/environment/actions. On real mic start the audio/capture owner may immediately set listening. `stop()` returns to idle and changes the caption; it keeps photo/environment/actions and schedules nothing. A new speech turn can then transition normally.

## Admitted values

- Pose: `camera_lowered`, `camera_ready`, `look_at_rain`, `face_calm`, `face_warm`, `face_curious`, `face_reflective`
- Scene: `cafe`, `rain_window`, `cafe_warm`
- Media: `trip_photo_placeholder` (legacy fixture identity) or `trip_photo`
- Subtitle: any approved string, always assigned using textContent

The photo is the original local coastal illustration in `/assets/scene/trip-memory.svg`. It is not a generated photo. The legacy backend photo caption still describes placeholder media; the integrating fixture owner should update that caption consistently through its review/digest path if desired. Do not bypass the grant or audit rules to change the content.

## New UI selectors

- `[data-ptt]`: accessible button, disabled until real microphone support is configured; keyboard/pointer capture belongs to the audio owner.
- `[data-voice-hint]` / `#voice-hint`: honest capability and recording/error guidance.
- `[data-mode-label]`: concise actual mode (for example Mock / fixture playback / live). It initially says connecting.
- `[data-mode-description]`: additional explanation inside collapsed details.
- `[data-phase-label]`: owned by the scene executor; current local performance description.
- `[data-character-description]`: accessible current appearance/action description, owned by the executor.

All original selectors used by main.ts remain. Form/input, data-command buttons, stop, close, status, diagnostic, error and fieldset remain unique where appropriate. Mode labeling must be filled by real service metadata and never inferred from an animation.

## Visual design and constraints

The stage is the primary surface, with an original 26-year-old travel photographer and café environment. Diagnostics are collapsed. Art is local and original. Character motion uses native SVG transforms and CSS keyframes; reduced motion disables loops but retains distinct poses/mouth/phase cues. Text/input/controls stay in document flow; short viewports scroll instead of hiding controls behind a fixed panel.

The renderer has no timers, fetches, browser TTS, audio elements, permission flow, or external asset dependencies. No new package dependency.
