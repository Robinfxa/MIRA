# PIXI-BASE-01: Pixi portrait rendering with the SVG safety fallback

Scope: mount same-origin, transparent, high-resolution full-frame portraits through
PixiJS while leaving the existing animated SVG scene as the renderer/assets recovery
path. The approved set contains all twelve action×expression frames (four expressions
across three actions), each a single full-frame RGBA image. Frames are mutually
exclusive, never layered. Four interaction phases remain in existing application
state and controls; static art does not yet have phase-specific poses or mouth sync.

Owner: web presentation adapter with the existing serialized controller preparation
path. The uniquely owned Node cases are in `tests/web/pixi-character.test.mjs`, covered
by the existing `web` lane. No HTTP schema, domain transition, permit identity, audio
owner, or provider is added. Consumers: `SceneEffectExecutor`, serialized visual
preparation/revalidation before sync apply and receipt, the stage's existing inline SVG
fallback, and the local static asset mount. Resources: twelve committed local generated
PNGs, a strict local manifest, and PixiJS loaded from the package lock. No CDN, remote
art, microphone, real provider, or deployment action.

## Given / When / Then

### PIXIBASE-001 — Preserve the actual portrait pixels and proportions

Given the logical canvas is 560×720 and the approved assets measure 1101/1102×1428/1429
RGBA, when the renderer chooses its frame rectangle, then it bottom-centres each frame
at the same logical root anchor and scales it uniformly to logical height 720. It
validates the manifest's recorded source dimensions and does not crop or stretch an
asset to force the earlier 1120×1440 planning size.

### PIXIBASE-002 — Only use local, declared, exact-state art

Given a valid same-origin manifest, when the exact current action×expression pair is
selected, then exactly that one local full-frame image is rendered. The manifest maps
camera-ready calm to the neutral master, camera-ready warm/curious/reflective to their
reviewed portraits, and every action to four separate matching expression frames. It
does not infer an action-only frame for another expression or combine PNGs. Unknown
states, remote URLs, path traversal, mismatched source dimensions, duplicate filenames,
or malformed manifests fail closed to the animated SVG; no placeholder or unreviewed
image is inferred into a usable variant.

### PIXIBASE-003 — Keep scene state and the single playback/receipt owner

Given Pixi initialization or image loading is pending while the controller receives
ordered visual grants, when the selected local frame is prepared, then the existing
controller revalidates activity/authority and synchronously applies that exact frame
before issuing the existing receipt. Stop, Close, or newer input aborts preparation and
cannot revive a stale texture. Phase changes remain owned by the existing audio/session
path. The Pixi adapter creates no effects, permits, receipts, audio, or retries; existing
Stop, gate, history, and media-readiness behavior remains authoritative.

### PIXIBASE-004 — Fail back cleanly and stay mobile-friendly

Given WebGL, local assets, texture upload, or initialization is unavailable, when the
adapter fails, then it removes any partial canvas and leaves the pre-existing SVG
available, including after WebGL context loss. It loads only the current frame and one
staged replacement, keeps no more than two textures resident, uses a capped device-pixel
ratio (maximum 2), and renders only on commits with no always-running animation ticker.
Reduced-motion users receive static frames without animated transitions.

## Verification boundary

Automated checks exercise manifest/hash/source dimensions, exact frame resolution,
anchored layout, serialized prepare-before-receipt behavior, two-texture residency,
async Stop/Close/context-loss fallback, and local Pixi bundle construction. They do not
prove a browser/GPU rendered the image, that a user saw it, or that on-device performance
is acceptable. The current route serves twelve full-frame PNGs totaling 28.54 MiB
compressed instead of the originally planned two atlases; only the current frame and a
staged replacement are loaded on demand. This is an explicit interim download tradeoff.
The trip-photo illustration stays under its independent media gate.
