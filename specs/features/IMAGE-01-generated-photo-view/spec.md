# IMAGE-01: Bounded generated fictional photo presentation

Base: frozen mira-integration-20261005T2238Z. Owner: web lane, tests/web/controller-generated-images.test.mjs (existing unique tests/web/*.test.mjs ownership). Consumers: strict session protocol, API client, PresentationGate, SceneEffectExecutor and existing SessionController. Resources: at most one staging image and one visible image, 8 MiB PNG, fixed 1024 square decode, five-second readiness default, 30-second maximum. No image providers, credentials, network, browser painting or device acceptance are exercised here.

### IMAGE01-001 Exact resource authority
Given an application-issued canonical generated_story_photo:v1 UUID4 and lowercase SHA256 media grant, fetch only its authenticated same-origin endpoint with exact effect identity. Reject URLs, malformed tokens, redirects, incorrect MIME/cache policy, excessive bytes, digest mismatch and invalid decoded dimensions. A status projection or cached bytes cannot issue a presentation grant.

### IMAGE01-002 Optional independent preparation
Given text and an image waiting for fetch or decode, text and normal voice remain independent. Before visibility, recheck the current gate, generation and abort state. Only successful exact decoded-resource commit allocates the existing software receipt. A generated image changes no character appearance, camera pose or expression.

### IMAGE01-003 Immediate local fences and ownership
Given pending image preparation, Stop, newer input, Close, permit revocation or photo dismissal aborts staging and revokes owned URLs. Uncooperative late work cannot revive it. Dismissal also fences a same-turn post-seal grant that has not arrived. Already committed images remain after Stop, and release on dismissal, replacement or Close. Every listener and URL has one owner and bounded cleanup.

### IMAGE01-004 Honest status and regression
Pending, held, cancelled and failed image states have separate bounded feedback and never fail an ordinary reply. The surface says 剧情生成图 · 虚构画面 with generic safe textContent; no actual photo/newly shot/observed-detail claims. The authored trip_photo/placeholder surface remains fully functional and restores its own caption on replacement.

Executable Node scenarios and actual commands are recorded in verification.md. The existing spec-link checker supports only pytest node IDs; no fake Python wrapper or uncollectable Node ID is added to traceability.json. The integration owner maps backend requirements separately.
