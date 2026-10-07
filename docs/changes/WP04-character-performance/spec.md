# WP04 coordinated code-native performance

Baseline: isolated copy of mira-integration-20261005T2238Z including the 2242 lifecycle repair. Owner: web lane, existing unique tests/web/*.test.mjs glob. Consumers: code-native composition and renderer only. Resources: current Canvas2D RAF, vendored geometry, no new dependencies, assets, networking, audio ownership or provider calls.

Given running idle, local head roll, breathing, blinks, gaze changes and delayed rooted hair must be perceptible and bounded; the entire composition remains fixed. Given listening or thinking, attention and lookaway use distinct posture and eye channels. Speaking adds nod and a small coordinated arm/camera gesture while preserving its rigid two-hand grip; mouth remains a labeled stage oscillator, not PCM or phoneme driven.

Given phase changes, numeric pose channels transition continuously on the same visual clock. Stop, explicit Pause, hidden document and reduced motion suppress all live channels immediately and preserve the adopted static geometry. Visibility/reduced-motion restoration may resume the current phase, never release Stop/Pause or revive canceled camera completion. Stale callbacks cannot commit after cancellation or destruction.

Normal retains the adopted face. Guarded, happy and shy add readable brow, eyelid, gaze and head-posture differences. Rest neck-root geometry and outfit fit are preserved. Head/neck motion pivots at the anatomical neck base; torso, pelvis and canvas are never moved as a single poster. Long hair has deterministic secondary lag.

Verification: behavioral RED/GREEN in tests/web/code-native-performance.test.mjs and renderer lifecycle tests, strict TS and affected checks; software-rasterized same-angle moving comparisons, extrema, grip/neck seams and all outfits. Tests are not visual or user acceptance. Device/browser and actual audio synchronization are outside this slice.

Explicit camera actions take ownership of the currently drawn physical hand/camera lift, including any ambient gesture. No ambient offset may disappear at cancellation or reappear after suspension. Cancelled partial poses remain action-owned; head, eye, breath and hair performance may still resume. Only a successfully copied camera_ready endpoint restores ambient hand gestures, with a 450 ms smooth fade-in. Geometry-level tests compare the actual drawn camera matrix across Stop, Hide, reduced-motion, Pause and signal abort.


## V2: user feedback at 23:26 on 2026-10-05

The user accepted the preview direction and asked for smoother chest, shoulder and arm breathing and more mouth participation in emotions. This isolated V2 continues from the frozen 2327 camera fix. No provider, voice, story, frontend layout or source imagery changes are included.

The upper thorax expands coherently about the waist. Shoulder anchors share that motion; elbows and the rigid two-hand grip follow with a small phase lag. Neck skin has two attachment weights: the jaw follows the head, and the base follows the breathing chest. All original stopped contours stay unchanged, including the approved root. Camera ownership covers ambient breathing lift as well as speaking gestures.

Guarded lips have more tension and downward corners, happy lips broaden and lift, and shy lips purse into a restrained smile. Happy and shy have brief bounded idle parting followed by complete closure. Existing speaking mouth geometry composes with these shapes; it is still a procedural stage oscillator, not PCM or phoneme synchronization. Lip parameters and emotional head bias settle on the existing renderer clock; Stop, hidden, reduced motion and Pause close live mouth channels immediately.

The moving head receives bounded local clearance from the two authored crown crests. The torso/canvas never translates for crop correction; the neck-root attachment is compensated by neck skinning. Stopped rest geometry remains the adopted baseline. The comparison is rendered from actual renderer drawing calls at 30 computed frames per second, without frame interpolation; this does not claim measured browser FPS.


## V3: broader acting requested at 23:52 on 2026-10-05

This V3 is isolated from the frozen V2. The user explicitly requested a more exaggerated, theatrical overall expression. Normal remains unchanged; happy opens into a wider smile with lifted eyes/brows and a clipped tooth plane, guarded furrows and presses the lips, and shy averts gaze with an inhibited compact smile. All channels remain authored local 2D geometry. No new images, providers, backend, audio owner or world/scene content is introduced.

All facial emotion channels now share a bounded 550 ms transition. SceneEffectExecutor.present invokes the existing transitionState/AbortSignal seam with kind=emotion; the DOM emotion fact and controller receipt wait until the target's fully weighted frame was successfully copied. Subtitle and speech-phase updates continue independently and cannot replace the pending emotion target. A retarget begins at the currently drawn weights. Stop, hidden/reduced-motion changes, Pause, abort, destruction, draw failure, deadline and stale callbacks cannot report a cancelled target as complete. Reduced-motion startup may complete immediately only after a full static target copy.

The narrow interface/consumer changes are in character-renderer-port.ts and SceneEffectExecutor.present. Controller/gate/backend implementations stay unchanged. Existing caption independence and speech playback ownership are reused. Verification includes actual controller endpoint receipts, retarget exclusion, subtitle/phase continuity, cancellation and failure, 30 fps actual executor/renderer transition capture, all outfits/extrema, tooth clipping and closed mouth on interruption. Software tests and preview direction are not device or PCM acceptance.
