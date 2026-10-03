# MIRA static layout review

Date: 2026-10-03 13:02 UTC  
Result: **pixel review blocked before page render**. This is a source/layout-risk review only, not visual acceptance.

## Pinned source

Copied allowlisted local source into `inputs/` before the render attempt. The source digests matched the UI builder's pin and were unchanged after the attempts.

| Source | SHA-256 |
|---|---|
| `apps/web/index.html` | `2580073ff597e6cf9abae1d46ef1286e1777e37926aadcf2fd1796cd9e8a1a24` |
| `apps/web/public/app.css` | `addcb33c8aa32b9cd07846a1ba343deceeefdff85bb40a85483ffdb1f46882e6` |
| `apps/web/public/scene/cafe-night.svg` | `3c3dcfb31b9126ab3ee511dd1e241fd2d714babcfd100651346fd162913cbf96` |
| `apps/web/public/scene/trip-memory.svg` | `e6571c45bb27bcc010854ffed0077837a225959d8224437b2b6234a5b0d8745e` |

## Pixel-render blocker

Only installed renderer found was Chromium 154.0.8037.57. I prepared script-free HTML with CSS and local SVGs embedded, `default-src 'none'`, scripts disabled, external HTTP/HTTPS/WS requests blocked, host resolution denied, fresh temporary profile, and the Chromium sandbox retained. No localhost navigation, fetch, credentials, or external assets were used.

Both a direct headless attempt and an approved run of the isolated Playwright renderer failed before page rendering with `process_singleton_posix.cc:297: socket() failed: Operation not permitted`; Playwright also reported ptrace blocked. I did not add `--no-sandbox`, install a renderer, or weaken browser/security settings. No PNG/pixel image was produced; `images/` is empty.

## Actionable source-level observations

- **Stop is far below the fixed rehearsal guide on mobile.** In `index.html`, the always-open, five-step `.rehearsal-guide` and its command row come first (lines 121–140); the only `停止回应` button is after the regular presets and composer (line 147). On a phone this likely requires scrolling away from the just-used story command to stop playback. Consider placing a stop control beside the rehearsal commands or collapsing the long instructions while keeping the fixed commands and synthetic-input control visible. Geometry still needs pixel verification.
- **Long bilingual captions use an inner scroll area.** `.subtitle` is capped at `180px` with `overflow-y: auto` (`app.css:115`). The fixed `story` cue combines Chinese and English to about 330 characters, so a mobile view may show only a portion at once, with an internal scroll nested inside the page. Verify this at 320px and 390px; consider a clearer scroll affordance or a taller/reflowing subtitle area.
- **The OFF state is not an affirmative visible badge.** The raw HTML starts with `unknown` and a visible warning (`index.html:24`). `recordingNotice()` hides the notice after healthy diagnostics confirms recording is off (`status.ts:24`). The rehearsal copy does say there is no microphone capture and the synthetic-input button says “不录音,” but a static, no-network render cannot establish runtime recording status. If users need an explicit OFF indicator, the current healthy-off branch has no visible notice.
- **Smallest-phone artwork overlap remains unverified.** At widths `<=480px`, the character art is 370px wide with `right:-73px`, while scene copy is 180px wide (`app.css:237–240`). Check the face/title relationship at 320px when a compliant renderer is available.

## Static harness

The `static-rehearsal.html` and `static-photo-speaking.html` files are transformed, local-only mock layouts; the latter exposes the long caption and visible illustration. They contain no script and are not interactive sessions. The `data-recording-state="off"` notice in these fixtures is a visual-only mock marker, not a service response. Rendering and any claims about actual behavior remain unverified.
