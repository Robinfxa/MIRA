# Pixi integration lifecycle and frame-layout controls

Scope: optional visual-resource owner closure and full-frame CSS, beneath the existing presentation policy. No model, audio, wire-schema or grant authority is added. The renderer implementation and serial asset preparation are separate slices.

- PIXI-INT-001: Given an optional renderer close hook, when the user closes the session, invoke it exactly once along with capture/playback/API cleanup; ordinary Stop must leave the renderer available for the next interaction.
- PIXI-INT-002: Given a renderer stop/destruction failure, still attempt all remaining resource cleanup, fence the local session, and show bounded actionable failure copy without the thrown payload.
- PIXI-INT-003: Given committed high-detail Pixi full-frame artwork, fit its logical560×720 frame inside the full stage-height bounds without inheriting cropped SVG offsets. Preserve the SVG fallback's existing CSS while Pixi is unready or unavailable. Only while the ready marker exists, remove its hidden SVG animation subtree from layout; removing the marker restores fallback rules.

The source CSS and geometric constraints can be tested offline. Actual browser layout, paint, WebGL resource release and human visual/audio experience remain separate acceptance items. The web sidecar below is executed by the web lane; the Python-only spec checker does not collect it.
