# CODE-SCENE-01 semantic character renderer

Owner: web lane, existing tests/web/*.test.mjs ownership in tests/quality.toml.
Baseline: public source mira-character-integration-next-20261005T0146Z.
Consumers: SceneEffectExecutor, SessionController's existing prepare/gate/apply/receipt boundary.
Resources: local editable semantic face/body code, Canvas2D at 288×408, one animation frame loop. No renderer provider, auth, database, network, or new dependency.

## CODE-SCENE-001 explicit review mode
Given new public launcher startup, the current adopted code-native renderer is selected; explicit static-pixi remains available. The low-level application factory compatibility default is unchanged. Given body data-character-renderer=code-native-review, draw semantic vectors on a 288×408 canvas with nearest-neighbor CSS scaling and an honest review-status notice. Source pins and readiness describe only actual capabilities; adopting the 1752 baseline does not declare perfect likeness.

## CODE-SCENE-002 atomic visible state
Given a permitted effect, prepare an invisible complete candidate, revalidate the existing gate, and synchronously commit the character before DOM facts or receipt. Unsupported camera/face/emotion/accessory states fail visibly; they do not become label-only success. All three drawn outfits are independent of phase and emotion.

## CODE-SCENE-003 lifecycle cancellation
Stop closes the mouth, resets phase/time, invalidates stale frame/preparation callbacks, and preserves displayed wardrobe/media/history. Close destroys resources. Hidden, Pause and reduced-motion changes cancel scheduled frames and invalidate pending work. New phase after Stop can restart only current motion; no whole-canvas CSS animation.

## CODE-SCENE-009 temporary suspension and current phase resumption
Baseline: manifest-verified 20261005-2030 source, renderer SHA-256 `fbab34df662a184fdfb6d7fa39519a21e9ee55053c5e653852a957688e7e9ea6`. Owner: existing web lane wildcard in tests/quality.toml; consumers: the existing SceneEffectExecutor and SessionController; resources: one local RAF and Canvas2D, no new dependency or provider.

Given an eligible idle/listening/thinking/speaking phase, when visibility becomes hidden or reduced motion is enabled, cancel frames, close the mouth and invalidate pending preparation. When all temporary restrictions end, resume that same current phase with exactly one fresh frame clock, excluding the suspended elapsed time. Overlapping restrictions and an explicit pause remain independent. A current non-idle phase received while hidden can resume when visible.

Given explicit Stop or Close before or during suspension, returning visible or disabling reduced motion must not revive the old phase, clock, preparation, or callback. New input continues through the existing current-phase and permit gates; this renderer does not infer audio permission. Given an in-flight camera action, suspension rejects that action and preserves its last successfully copied geometry. Ambient movement may resume, but the cancelled action cannot finish or produce a completion receipt.

Executable coverage: tests/web/code-native-renderer.test.mjs, the four-phase/two-suspension matrix, overlapping startup restrictions, explicit Stop timing, hidden new phase, camera cancellation and destroyed/late preparation cases. Existing controller receipt and stale-preparation cases remain in the same file. Run evidence stays outside checkout. Native Node TS transformation is executable synthetic evidence only, not strict TypeScript compilation, browser painting, audio audibility, or device acceptance.

## CODE-SCENE-004 honest capabilities
Readiness distinguishes review_only geometry from unavailable capabilities and unapproved likeness. Four phase channels remain independent of the four implemented emotional geometry states. Camera and silver-star clips are independently selectable. Camera lowering/turning and legacy non-neutral face poses remain unavailable. Browser pixels, visual likeness and real audio lip sync remain unverified.


## CODE-SCENE-005 editable connection drafts
Given startup or a failed connection, the text field stays editable, Send and voice actions stay disabled, and explicit status plus Retry explain what can happen. Retry is single-flight, never silently deletes another session, and preserves the draft. Close keeps the draft editable and fences a pending successful callback. Only the API client's fixed safe error text and validated request ID are shown.

## Executable coverage
The existing traceability CLI accepts Python tests only. These Node test mappings are explicit here, not fabricated pytest nodes:
- 001/004: tests/web/code-native-renderer.test.mjs source-pin/catalog/composition checks; tests/web/controller-main.test.mjs composition check.
- 002: code-native-renderer.test.mjs prepare-vs-copy, unsupported state, failed-copy DOM, actual-controller receipt tests.
- 003: code-native-renderer.test.mjs Stop/hidden/reduced-motion/Close and actual uncooperative preparation gate tests.
- 005: controller-main.test.mjs connection failure/retry/Close tests; error-locators.test.mjs real controller/API integration.

All tests remain owned by the existing web wildcard in tests/quality.toml. Backend/config/bootstrap consumers are handled in the integration parent's separate work. Evidence is held outside the source checkout.

## CODE-SCENE-006 explicit software capability composition
Given the review renderer is explicitly selected, the shipped catalogue maps implemented geometry to software readiness with source revision, while unimplemented slots stay unavailable. Static mode does not inherit these new slots. The HTTP marker selects the same renderer as the launcher, and the wheel preserves the nested catalogue and emitted vendor code. `tests/contracts/test_renderer_readiness_bootstrap.py::test_selected_review_renderer_binds_software_readiness_without_art_approval` and `tests/contracts/test_renderer_readiness_bootstrap.py::test_selected_renderer_is_explicit_in_real_http_entry_and_static_catalog` are executable Python coverage under the existing providers wildcard.

## CODE-SCENE-007 fixed offline review controls
Given explicit code-native rendering plus mock generation, nine labelled authored command buttons pass through the existing Actor, exact fixture review, preparation and receipt path. They do not change the injected live reviewer or classify arbitrary user text. `tests/contracts/test_code_character_mock_entry.py::test_explicit_code_mock_command_reaches_actor_grant_and_exact_receipt` exercises all nine commands. Three outfits, four emotions and two accessories remain independent.

The proportional static layout is 288x408 with one invariant translate(18 0) root; full-target emotion is drawn before receipt. Blink closure no longer switches to a spatially displaced lower lid. Neither static SVG checks nor fake Canvas calls prove browser/user aesthetic acceptance.

## CODE-SCENE-008 adopted launcher default and explicit fallback
Given the new direct or offline launcher, omitting a renderer selects code-native-review. Explicit static-pixi is forwarded unchanged to the child/composition; neither path starts live services during check. With and without story, the selected renderer controls the actual readiness catalogue and generation context. Coverage: `tests/contracts/test_live_provider_launcher.py::test_new_live_entry_adopts_code_character_and_keeps_explicit_static_fallback`, `tests/unit/test_dev_startup.py::test_offline_launcher_forwards_adopted_renderer_or_explicit_fallback`, `tests/unit/test_dev_startup.py::test_offline_child_uses_same_renderer_without_loading_live_resources`, and existing `test_real_application_exposes_selected_visual_readiness_without_story`.
