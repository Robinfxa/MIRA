# CAMERA-01: bounded articulated camera lift

Base: immutable `mira-natural-conversation-capture-20261005T1444Z`, with 1413 artwork.
Geometry and renderer owner: camera-motion worker. Shared SceneState, CharacterRendererPort,
SceneEffectExecutor and controller owner: visual-action-completion worker. Backend action
admission, capability catalog and bootstrap owner: integration owner.

The prototype adds a code-native upper-chest camera lift and return. Camera and gripping
hands keep rigid relative geometry. Two projected shoulder/elbow/wrist chains deform the
editable upper arm, cuff and forearm paths; strap endpoints take up slack. This is bounded
2.5D foreshortening at the existing camera angle, not eye-height contact or a 3D skeleton.
Travel is 81 native pixels upward and 9 rightward, with a 1-second full-travel smoothstep.
No face/hair/neck geometry, renderer resolution, paid assets, dependencies, real camera,
shutter, provider or media creation is added.

## Observable behaviors

1. Given ready, camera_raise draws intermediate articulated geometry and resolves only
   after a successful terminal Canvas copy. camera_ready reverses from the actual pose.
2. Given an in-flight motion, Stop, abort, hide, pause, destroy or a new target cancels it.
   Stop/abort preserve the most recently copied coherent pose. No cancelled action is a
   completion receipt. Destroy is the explicit close/removal path.
3. Repeating the same target while active shares completion without resetting progress.
   Ordinary phase/subtitle/wardrobe renders preserve physical pose. The latest state is
   retained when the target is finally copied.
4. Reduced-motion requests copy their terminal pose without animation. A missing frame
   loop has a five-second deadline and cancels without falsely completing.
5. If staging or copying fails during motion, retain the last good canvas and progress,
   reject completion, invalidate callbacks, and refuse new effects until replacement.
6. The same motion paths are used across all three outfits. Lower torso, head, face and
   hair remain registered; no full-character transform, raster embedding or crossfade.

## Verification and limits

Tests belong to the existing unique web lane (`tests/web/*.test.mjs` in quality.toml).
Run the directed renderer tests, then affected web + architecture using explicit changed
files because this captured source has no Git metadata. Existing dependencies come from
`mira-resumed-runtime-20261005T1236Z`; evidence is outside the source tree. Shared consumer
edits borrowed for compilation are listed separately in the handoff and are not owned here.

Initial geometry and first lifecycle behaviors have actual RED/GREEN logs. Later failure,
deadline and latest-phase regressions were added after implementation review; they are
regression evidence, not retroactive test-first evidence. Native SVG raster frames inspect
pixels from the compiled production composition; they are not browser/device screenshots.
The optional prototype uses the actual Canvas renderer and exposes Raise/Return/Stop and
joint overlay. User visual approval and real device/browser acceptance remain pending.
