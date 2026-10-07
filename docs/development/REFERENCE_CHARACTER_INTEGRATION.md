# Reference character integration — review candidate

This isolated visual change composes a corrected code-native head and long shoulder
waves through the existing renderer. The frozen torso02 revision is now included, with fitted garment contours and
unchanged camera/hand attachment interfaces. No likeness or art acceptance is
implied by software readiness. `visualAcceptance: pending` and
`likenessApproved: false` remain mandatory.

The selected renderer still uses the same prepare → permit gate → complete visible
copy → presentation receipt sequence. The hair modifier is typed and pure, runs
exactly once before the unchanged expression modifier, and shares the head's +4
native y registration. Its added shoulder waves sit under forearms, hands, and camera.
The catalog pins face, body, expression, and hair bytes; strict bootstrap validation
requires exactly those four source keys.

## Acceptance behavior

- Given any supported outfit, expression, accessory and phase, composition preserves
  unique semantic parts and paired head/rear-hair/neck registration.
- Given Stop, new input, hidden state, reduced motion, or Close, old pending drawing
  cannot receive a presentation receipt. Stop/hidden/reduced motion close the mouth.
- Given unchanged source geometry, applying hair does not mutate its input, and
  applying it twice fails rather than adding duplicate parts.
- Given a missing hair source in the catalog, software readiness fails closed.

The existing `tests/web/code-native-renderer.test.mjs` (web owner) and
`tests/contracts/test_renderer_readiness_bootstrap.py` (providers owner) own the
added checks. No new test file or ownership rule is introduced. Bootstrap's only
change is the four-key source validation. JEV, privacy, provider, OAuth, application
entry and HTML source are untouched by this slice.

## Verification at the head/hair checkpoint

The real RED run had 4 Node failures and 2 Python failures before implementation.
The first GREEN passed 29 focused Node tests and 19 Python tests. The bounded state
matrix was then expanded to all 192 supported state/running combinations.

The affected run selected architecture, env, config, actor, providers, http and web.
Six lanes passed. Providers reported four failures in the inherited, concurrent P0
review changes: one four-turn request-size guard and three old policy-revision
expectations. Those files are outside this visual slice. The affected source digest
was unchanged during the run. The old failed evidence is retained.

After rebasing every nonvisual path onto immutable 0515 manifest
`8b474d72a1725895eb0b15acea892bdce633b4646b82111e850388324c468203`,
all seven affected lanes passed with stable source digests: 2,234 Python tests
and 395 Node tests. Domain, tooling, specs, package, smoke and continuous lanes
were not selected; this is not a full or release claim.

The standalone review HTML is built directly from production TypeScript and vendored
sources. Its actual inline scripts execute in a VM with synthetic DOM/Canvas calls;
24 static variants and four phases are rasterized from that bundle's semantic scene
at native 288 × 408. These PNGs are review evidence, not application raster assets.
Actual browser pixel equivalence, device behavior, real providers and audio
synchronization are untested. A browser launch failed before a page/context existed;
no alternate browser route or retry was used.

Original source baseline: isolated copy of `mira-character-next-20261005T0325Z` at 05:07 UTC.
Current integration base: immutable `mira-conversation-capture-20261005T0515Z`.
Frozen 04:35 material and active source are unchanged. Torso02 was integrated from the owner's frozen 3cb62900900a740a0be4c34824f1c183a7f1511cbbfe5c346d2cf5d378ad3d3d source.
The final torso integration has a separate fresh verification run; the earlier
head/hair-only artifacts remain immutable.

## Final torso02 verification

The final torso02 source passed a fresh seven-lane affected run: 2,234 Python
tests and 395 Node tests. Source digest before and after was
`53d44582d9becfd63e33363f35a3ca4b1db49f36f7af3b64f43066384669b003`.
The final standalone HTML VM lifecycle check, 24 native variants, four phases,
and ASGI byte-for-byte serving of all 30 application bundles also passed.
The final comparison and complete 24-variant matrix were visually inspected
for integration artifacts. This does not approve resemblance, garment shape,
or device/browser rendering. These remain review candidates.
