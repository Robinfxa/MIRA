# Independent media-readiness audit

**Result:** The suspected boundary is reproducible against immutable source snapshot `<project-root>`. `SessionController` can send a media receipt while the corresponding `<img>` is still incomplete or complete-but-broken. The existing code does not read image readiness. This proves a deterministic gap in the application-level history contract; it does not prove that a real browser currently exhibits a slow or broken asset, nor that any user saw pixels.

## Exact semantic claim at risk

`specs/features/DEMO-01-offline-rehearsal/spec.md:13-15` requires a photo question to reference media only when its effect is in “actual presented history.” In the rehearsal implementation, one receipt adds that effect to `SessionState.presented_effects` (`domain/models.py:93-98`, `domain/transitions.py:102-123`), and `rehearsal/backend.py:72-76` uses that fact to choose the `detail` response instead of `absent`. If a receipt is generated while the image resource is unavailable, the application overstates its own presentation history and the next `照片里有什么` can answer as though the scene was available.

This is an application/readiness claim only. Neither DOM visibility, `complete`/`naturalWidth`, nor `decode()` proves compositor paint or that a person looked at or understood the image.

## Source path

- `apps/web/src/features/presentation/scene-state.ts:47-50`: `trip_photo` immediately changes state to `photoVisible: true`.
- `apps/web/src/features/presentation/scene-executor.ts:34-38,60-68`: `apply()` is synchronous; render only toggles `[data-photo].hidden`. The executor never queries the child `<img>` or observes `load`, `error`, `complete`, `naturalWidth`, or `decode()`.
- `apps/web/src/features/session/controller.ts:136-144`: the controller calls `effects.apply(effect)`, immediately consumes the gate, and queues the receipt with no readiness check or await.
- `apps/web/index.html:104-106`: the revealed figure contains the local `/assets/scene/trip-memory.svg` image and its caption.
- `scene-executor.ts:40-47` preserves `photoVisible` on new input and Stop; the image's readiness is not involved in that retention decision.

## Deterministic reproduction

The independent runner under this directory compiles the snapshot's TypeScript into a temporary directory and runs the actual compiled `SessionController` and `SceneEffectExecutor` against synthetic DOM/image and transport stubs. No browser, local server, network/provider, credentials, or actual image decode is used.

From the canonical project root:

```sh
SNAP=<project-root>
OUT=$(mktemp -d <temporary-evidence-path>)
"$SNAP/node_modules/.bin/tsc" -p "$SNAP/apps/web/tsconfig.json" --outDir "$OUT"
MIRA_TEST_WEB_DIST="$OUT" node docs/verification/media-readiness-independent/repro.mjs
PYTHONPATH="$SNAP/apps/api/src" python3 docs/verification/media-readiness-independent/history_probe.py
```

Run `20261003T1305Z` is captured in `runs/20261003T1305Z-controller.json` and `runs/20261003T1305Z-history.json`.

Key observations from actual controller/executor code under the stubs:

- Slow image (`complete=false`, `naturalWidth=0`): figure is unhidden and exactly one media receipt is sent while still unready.
- Failed image (`complete=true`, `naturalWidth=0`): figure is unhidden and exactly one media receipt is sent despite the failed-resource sentinel.
- The simulated image has zero registered load/error listeners.
- Stop and newer input before simulated late load preserve `hidden=false`; the late load fills that already-exposed slot. This is retention of the preexisting DOM state, not a stale controller callback or second receipt.
- Already-ready image is also unhidden and receipted; Stop retains it, consistent with the intended retention of a genuinely presented image.
- The pure application probe starts with no receipt and obtains `absent`. Applying the same real `record_receipt` transition to the controller-shaped receipt adds `trip_photo` to `presented_effects`; the real rehearsal `fixture_for` then selects `detail` and the fixed caption “画面还留在这里。灯塔照亮幽暗的海岸，暖光朝海面延伸。”

The last step shows how the receipt is consumed by application history; it does not claim this synthetic test ran an end-to-end browser session. Existing `tests/integration/test_rehearsal_http.py` separately demonstrates the real rehearsal Actor's receipt/history/follow-up contract, but it explicitly supplies a receipt and therefore does not cover the frontend readiness boundary.

## Minimum cancel-safe fix proposal (not implemented)

Keep the existing `PresentationGate`, controller, and sole `SceneEffectExecutor`; add a media-only readiness acknowledgment rather than any second player/framework.

1. Keep a not-yet-ready photo hidden while checking the already-mounted image. Treat it ready only after a safe condition such as `complete && naturalWidth > 0`, preferably with `await img.decode()` and an explicit error path. A load/error wait is needed if it is still pending; error or timeout must not emit a media receipt.
2. Make only the media-application path await/return that acknowledgment. Before revealing the figure and before consuming/sending its receipt, revalidate the same local generation and `gate.allows(effect)`. Stop/new input must invalidate the pending acknowledgment synchronously; a late success must neither reveal an unpresented old effect nor issue a receipt.
3. Preserve the current behavior for a previously ready and receipted image: Stop/new input leave that existing image visible. A failed/unready first attempt remains absent, so a later photo question takes the existing `absent` route.

Suggested directed checks: ready image → one reveal and one receipt; already-failed image → no reveal/receipt and follow-up stays `absent`; pending image → Stop or new input → then resolve load → no old reveal/receipt; prior successfully presented image → Stop preserves it. Any resulting receipt continues to say only that the application reached its image-readiness/presentation step, never that pixels were painted or seen.
