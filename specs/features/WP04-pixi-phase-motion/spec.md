# WP04 Pixi character phase motion

Scope: add subtle, phase-driven CSS compositor motion to the ready Pixi canvas without changing its selected action/expression texture, render loop, bottom-centre frame anchor, or presentation gate. The existing SVG remains the render-failure fallback.

Consumer: existing `SceneEffectExecutor`, which publishes its current phase on `.stage[data-phase]`; `PixiCharacterSurface`, which sets `.character-anchor[data-renderer="pixi"]` only after drawing a frame and removes that marker on close or WebGL context loss.

Resources: local stylesheet and existing browser APIs only. No ticker, timer, JavaScript animation, extra frame swaps, mouth sync, new asset, or dependency.

### WP04MOTION-001 Current phase drives gentle primary-character motion

Given a ready Pixi character, when the executor changes between idle, listening, and speaking, then the current phase selects subtle CSS compositor motion on the Pixi canvas (breath, listen lean, speaking nod). Thinking remains motion-free; the exact action/expression frame stays selected by the existing renderer contract.

### WP04MOTION-002 Stop, fallback, close, and reduced motion remain safe

Given speaking motion is active, when Stop changes the current phase to idle, then only idle breathing applies and no callback can revive speaking motion. Motion is scoped to the ready Pixi renderer marker, so renderer failure, close, or context loss restores the SVG path without an animation loop. `prefers-reduced-motion: reduce` disables Pixi transforms/loops. CSS motion changes no crop, canvas size, or frame anchor.

Verification owner: existing `web` lane, which covers `tests/web/*.test.mjs`. `tests/web/pixi-character-motion.test.mjs` verifies selector mapping plus actual `SceneEffectExecutor` phase hooks in a fake DOM. Browser paint, hidden-tab animation scheduling, and physical-device motion remain unverified.
