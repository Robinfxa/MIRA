# LUNA-02 Media tool composition

Base: frozen0221 capture22a4f2e26a113fdc5ed88419596a2444a83261e2747cf25d632cdb87145fb686.
Owner: director composition; unique tests owner is the existing providers glob.
Consumers: direct bootstrap/CLI, Actor, optional caption planner and image admission.

### LUNA02-001

Given an explicitly injected tool backend, composition preserves the original total
request budget while allowing at most two requests per user turn. A normal turn
uses one. Legacy factories remain one-request mode. Configuration performs no IO.

### LUNA02-002

Given explicit existing image data/use consent, custom fictional briefs require
their own new scope flag. The flag alone never enables image generation; legacy
media proposal mode cannot advertise the new tool-only custom-brief capability.
No new key, account grant, automatic retry, API fallback or budget increase occurs.

### LUNA02-003

Given the existing optional caption planner, a complete ordinary/tool-result cue
uses that same planner once. Voice and action-bearing cues retain existing whole-cue
semantics. This is not token streaming, per-bubble TTS or a new text admission gate.

### LUNA02-004

Given fixed and generated photos on the same surface, deduplicate only the exact
currently visible fixed target; a different generated image can be replaced by an
authorized fixed-photo request. Unknown visibility and dismissal fences remain
conservative. Natural in-world names and explicit truthful source answers coexist
with unchanged provenance metadata; a promise is never a display receipt.

## Given / When / Then and verification

The dedicated composition tests exercise real adapter request bodies and pure
fact projections with synthetic data. Actual cross-layer function_call to receipt
and continuation is independently exercised before release. Whole release follows
final source capture. Public fixtures are self-authored; the supplied user dialogue
was reconstructed only in separate local evidence and is not a delivery input.

Changed shared roots: Providers, direct app/container composition, finite usage
declaration, image options and live_provider.py. Existing guards and explicit user
consent retain authority. Runtime-independent port supplies the per-turn exchange;
no generic orchestrator, callback-based executor or extra service is introduced.

Real account tool/image eligibility, latency and model dialogue behavior are not
established by mocks. Image prompt shape filters are not universal privacy or
semantic classification; no complete private transcript or memory packet is
automatically attached to image requests. Next-stage visual yaw, persona memory
and topic expansion are isolated and not part of this slice.
