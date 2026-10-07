# Original MIRA visual assets

Created for this project on 2026-10-03 as hand-authored SVG path geometry and CSS animation. No stock image, downloaded character, external font, template rig, or third-party artwork is embedded.

- `cafe-night.svg`: original café/window/city/cup/notebook vector environment.
- `trip-memory.svg`: original coastal travel illustration shown by an admitted media effect. This is an illustrated story artifact, not a real photograph or runtime image-generation result.
- The original adult character is inline SVG in `apps/web/index.html` so CSS can independently animate her body, eyes, head, mouth, camera, and hands. MIRA is explicitly 26 years old. Her design uses adult proportions, an amber raincoat, a dark bob haircut, and a silver star hair clip.
- CSS animation is the implemented multimodal branch: breath, blink, listening/thinking/speaking, and admitted camera/window actions. Speaking motion is a stylized talking loop, not phoneme or audio-amplitude lip sync.

Authorship: AI-assisted original code-native design and implementation for the MIRA project. This note records provenance, not an independent human originality assessment. No external asset license obligations were introduced.

## Pixi portrait artwork (2026-10-04)

The reviewed set has twelve mutually exclusive full-frame RGBA images: a neutral camera-ready base; warm, curious and reflective face variants for camera-ready; calm, warm, curious and reflective composites for `camera_lowered`; and the same four composites for `look_at_rain`. Images are 1101/1102×1428/1429, have transparent backgrounds and share a bottom-centre anchor. The 560×720 logical renderer fits each source uniformly to 720 logical px high, without stretching or cropping.

`mira_manifest.json` records every local filename, actual pixel size, source anchor and SHA-256 hash. The package contains about 28.54 MiB of compressed PNGs. The renderer loads the initial frame and then only a requested state frame; a maximum of one current texture and one prepared replacement may be resident. Full-frame images are single sprites; no core/variant layering is used. Four interaction phases still update in application state, but the static art does not include a speaking-mouth sequence or phase-specific animation. Pixi initialization, local asset failure, unsupported rendering or WebGL context loss restore the original SVG path. The trip-photo illustration remains a separate media-gated asset.

These are AI-assisted original character illustrations created for MIRA, then reviewed as individual state frames for identity, expression/action match, and transparent edges. That review is an AI-assisted development check, not independent human approval or a browser/device visual acceptance.

## Optional café background preview (2026-10-04)

`cafe-painterly-lighting-v3-table-free.png` is a separate AI-assisted rainy-window background plate. It contains no character; the Pixi portrait files and their hashes remain unchanged. The image is 1586×992 RGB PNG (SHA-256 `4bd221f284181946d9427fd7fab042fba7e56ff8014046c577f0d60fea389fb3`). The original hand-authored `cafe-night.svg` remains the default and CSS fallback. V3 is selectable as a reversible visual preview; its desktop/mobile crop geometry is source-derived, but no browser-rendered composite or independent user acceptance is claimed here. The earlier tabletop version is retained only in review materials and is not a served asset.
