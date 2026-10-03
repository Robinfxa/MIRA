# WP04 Original character scene

Scope: mobile-first visual presentation and original code-native art. This feature does not provide microphone capture, audio playback, provider access, or a second presentation/permission authority. Common baseline: `ebb578dde665c9c7269e4a64b508182680b2fa66`. The current authorized project deadline remains 2026-10-04 08:53:50 UTC.

## Consumers, resources, and verification ownership

- Consumer: the existing `SessionController` and its `EffectExecutor` port, composed only by the integration owner in `app/main.ts`.
- Owns: scene markup/CSS, local original SVG assets, `scene-state.ts`, `scene-executor.ts`, and `tests/web/scene*.test.mjs`.
- Test owner: existing `web` lane (`tests/web/*.test.mjs` already covers these files); no registry write is required. Integration owner must run affected checks after hookup.
- Resources: local filesystem and installed TypeScript/Node only. No accounts, network assets, new dependencies, paid APIs, browser TTS, or network publication.
- Checks in this slice: targeted Node behavior tests and isolated TypeScript output. Actual browser layout, audible output, real microphone input, and the final 3–5 minute recording remain separate evidence.

### WP04-001 Original adult, scene-first composition
Given a new session, when the page loads, an original 26-year-old travel photographer and a café/rain-window environment occupy the primary stage, with accessible subtitles, text input, stop, and explicit microphone hook. Diagnostics are subordinate and initially collapsed. At 360px and desktop widths, CSS must keep controls in normal flow and let the page scroll rather than clip essential content.

### WP04-002 Four actual presentation phases
Given an explicit local phase hook, when `setPhase` receives idle/listening/thinking/speaking, the stage exposes that phase and an accessible description. Character-level SVG transforms, eyes/brows, mouth and breath animate or change to make the phases visually distinct. Speaking is set by the actual audio owner; displaying subtitles alone does not claim audible speech.

### WP04-003 Three distinct expressions and two actions
Given permitted structured pose effects, warm/curious/reflective expressions change facial geometry or layer visibility, and camera-lowered/look-at-rain visibly change camera/head pose. Unknown pose names fail rather than receiving a false presentation receipt.

### WP04-004 Conversation-triggered environment and artifact
Given an admitted rain-window or trip-photo effect, the environment/camera and original travel illustration change immediately. No fixed page timeline reveals the artifact. Unknown media or scene values fail closed; user-supplied effect text is never an asset URL or HTML.

### WP04-005 Stop preserves already presented facts
Given a revealed photo and changed scene, when stop or a new input begins, photo, scene and persistent action remain. Stop immediately exits the speaking phase; no renderer callback, audio queue, network request or timer can revive an old effect. The existing gate remains responsible for admitting current effects.

### WP04-006 Safe rendering and accessibility
Given untrusted subtitle text, render using `textContent`. Decorative art is hidden from assistive technology while the character/action description and phase label remain available. Controls have labels and keyboard focus states. Reduced-motion CSS disables ambient/character loops and makes phase/action changes immediate. No remote fonts or image dependencies.

### WP04-007 Stop control before progressively disclosed rehearsal help
Given the conversation controls have been enabled, when the rehearsal guide is used, the single existing Stop control appears before the long instructions in source order. The instructions use native `<details>/<summary>` disclosure, closed by default and keyboard operable, while the fixed command buttons and synthetic-input control remain outside the disclosure. The conversation fieldset remains disabled during startup, and the existing stop and conversation selectors stay intact. Source/DOM behavior test: `tests/web/scene-markup.test.mjs` (`node --test`); actual viewport position and visibility still require pixel/device review.

## Structured values and integration

`pose`: camera_lowered, camera_ready, look_at_rain, face_calm, face_warm, face_curious, face_reflective.
`scene`: cafe, rain_window, cafe_warm.
`media`: trip_photo_placeholder (legacy fixture identity) or trip_photo (same explicitly original illustrated local artwork). These do not represent generated photography.
`subtitle`: any admitted string, rendered as plain text.

Only add these values to live generation/review after the integrator's ordinary policy path permits them. This renderer never expands a backend grant. Phase hooks are local presentation events, not new backend enum values.
