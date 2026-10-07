# PIXI-BASE-01 verification

Date: 2026-10-04 UTC. Source was verified in an isolated copy using the pinned
`package-lock.json`; the source checkout's pre-existing dependency symlink was not
replaced. Tests used synthetic session effects, a mocked Pixi application runtime,
local PNG files and a loopback rehearsal server. No live provider, microphone, browser
UI, deployment or user device was used.

## Dependencies and bundle

- PixiJS `8.19.0` (MIT), esbuild `0.28.2` (MIT), TypeScript `5.8.3`.
- `npm ci --ignore-scripts --no-audit --no-fund` installed the 15 locked packages in
  the isolated validation copy.
- `npm run build` passed, checking each manifest-pinned SHA-256 and PNG IHDR size,
  then compiling TypeScript and bundling a local ESM entry with relative local chunks.
  No CDN or runtime network asset route is used.
- The offline wheel check passed. It built and installed the Python wheel, verified
  78 installed resource hashes, served 72 exact web resources including the Pixi
  chunks, linked licenses, manifest and PNGs, and passed config, fixture, health and
  session lifecycle smoke checks.

## RED / GREEN and automated tests

- `docs/verification/pixi-base-01/runs/001-red-prepare-before-render/` records the
  pre-implementation failure: the selected-frame preparation test failed because
  `prepare()` returned before staging the next visual state. Its expected process exit
  was 1.
- `docs/verification/pixi-base-01/runs/002-green-prepare-before-render/` records the
  same test passing after prepare-before-apply was added; expected exit was 0.
- Targeted Pixi suite: 10/10 Node tests passed, including strict manifest and image
  hashes/dimensions, exact action×expression selection, same-anchor no-crop geometry,
  current-frame readiness, stale initialization/close, and WebGL context-loss fallback.
- Full isolated browser suite: 260/260 Node tests passed via `npm test`.
- The `web` quality lane passed via `tools/check_web.py`, again with 260/260 Node tests.

The web suite covers application-level receipts and cancellation only where the
existing controller tests do so; Pixi itself reports no receipt. The controller awaits
visual preparation, revalidates the existing gate, synchronously applies the prepared
texture, then issues the existing receipt. A no-longer-approved or failed renderer
state uses the existing SVG path. Trip-photo readiness remains independent.

## Limits

There is no screenshot from a real browser/GPU and no 390×844 phone or 1440×900 manual
acceptance. CSS face-size estimates are geometry only (roughly 103 px mobile and 136 px
desktop after full-height placement). User visibility, photo-over-hand clearance and
physical-device performance remain unverified. Static frame changes do not provide
speaking-mouth motion or phoneme/audio synchronization.

Official PixiJS references checked for this implementation:

- https://pixijs.com/8.x/guides/components/application
- https://pixijs.com/8.x/guides/components/assets
- https://pixijs.com/blog/june-2026
