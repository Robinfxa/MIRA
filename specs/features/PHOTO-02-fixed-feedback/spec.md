# PHOTO-02: Observable fixed-photo attempts

Base: immutable mira-subscription-final-20261006T0114Z; 1,307 source files, capture manifest SHA256 61f0a635cce3e8096ab21d193d3e2d7c970c857390efabc2a44f5d2f3e745598.
Owner: fixed-photo feedback slice. Consumers: Actor, generation/JEV context, existing diagnostic export, authenticated session HTTP, controller and photo renderer. Shared schema/controller integration is owned by the director.
Resources: existing local Python/Node runtimes; synthetic model/review/DOM only. No network, new dependencies, providers, credentials, automatic retry, or user database.
Tests: providers owns tests/contracts/test_fixed_photo_feedback.py under its existing glob; web owns tests/web/fixed-photo-feedback.test.mjs under its existing glob. Downstream affected consumers include architecture, domain, actor, HTTP, diagnostics, provider contracts and web. Shared domain/contracts/DTO impact expands affected checks; final aggregate belongs to integration owner. Full/release/device/browser-paint/live semantic acceptance is outside this slice.

### PHOTO02-001: Actual proposal and closed outcomes
Given a schema-valid typed media=trip_photo proposal, when readiness filtering or optional review holds it, ordinary text remains available and a bounded latest-attempt state explains pending/held/granted status. Given only prose promising a picture, no attempt or grant is created; candidate-kind counts diagnose proposal absence. Dynamic generated-image state remains separate.

### PHOTO02-002: Failure feedback and facts
Given an issued active exact fixed-photo grant, when its frontend reports preparation or presentation failure, its latest status records that closed failure without fabricating a receipt or stopping ordinary chat. Only the existing successful receipt can establish presented=true. Missing acknowledgement remains receipt_pending. Generation and JEV receive the same bounded outcome and unchanged authoritative presented/visible fields.

### PHOTO02-003: Cancellation and stale events
Given Stop, new input, close, dismissal, duplicate receipts or an older grant callback, an old report cannot overwrite the latest attempt or revive a dismissed photo. A newly accepted late receipt can resolve the same latest attempt under the existing fence, while duplicate-after-dismiss cannot change its status. Historical receipts remain immutable and current visibility remains domain-owned.

### PHOTO02-004: Authenticated bounded diagnostic surface
Given metadata export or HTTP progress, only closed statuses/reasons, bounded numeric counts, and hashed existing correlation IDs are allowed. No caption, prompt, URL, path, header, raw error or payload field is accepted. HTTP progress is session-authenticated and exact-grant-bound; it cannot report success or create an action.

### Independent fixed-photo rendering (web lane)
Verified by tests/web/fixed-photo-feedback.test.mjs (Node test IDs are outside the pytest-only traceability index). Given a ready local fixed SVG and an unavailable/failing unrelated character renderer, the exact authorized photo can prepare and commit its own DOM surface without changing camera/expression/pose state. Its image load/decode failures remain nonfatal failures. Cancellation and current authority checks still fence presentation; pose effects retain their existing renderer requirement.
