# Limited head yaw and shoulder attention review candidate

Base: immutable 0221 capture manifest SHA256 22a4f2e26a113fdc5ed88419596a2444a83261e2747cf25d632cdb87145fb686. Owner: web lane (existing tests/web/*.test.mjs owner), consumers: production code-native renderer, camera lifecycle, expression/hair composition. Resources: existing Node/TS and software SVG rasterizer; no provider, installation, or browser restriction bypass.

- Given stopped, hidden, or reduced motion, dynamic yaw/shoulder channels are zero; adopted neutral/rest paths, registration and neck root stay exact.
- Given normal running, bounded relative yaw in both directions changes projected face/eyes/nose/lips, ear exposure and hair overlap. The existing roll remains a separate channel. This is limited 2D articulation, never a 360 degree or full 3D rig claim.
- Given shoulder attention, a continuous upper-body deformation joins neck root, clavicle, trapezius, clothes and upper arms. Its influence fades before the fixed camera/hands and pelvis.
- Given speaking, blink, four expressions and three outfits, existing overlays compose before yaw; camera/hand grip stays one assembly through lift and return.
- Given Stop or suspension while a cue is pending, established lifecycle cancellation and exact completion receipts remain authoritative.

Acceptance evidence: actual source-bound continuous before/after software render, relative left/neutral/right sheet, playable self-contained preview, matrix at motion extrema. Software state checks and rendered pixels are not browser/device/user visual approval.
