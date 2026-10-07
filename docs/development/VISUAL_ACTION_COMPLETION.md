# Bounded camera action completion

Base: immutable 20261005T1444Z natural-conversation capture. Owner: web lane (tests/web/*.test.mjs); related consumers: presentation gate, local renderer, fact receipt barrier. Resources: existing Node/TypeScript runtime only; no provider, assets, device, network or new dependency. Integration owner runs affected with explicit files because this captured tree has no Git metadata.

Given an authorized camera_raise or camera_ready action, prepare validates resources without visible mutation; the controller rechecks authority before starting a finite animation. A completed receipt is allocated only after the renderer reports its terminal Canvas commit and the controller rechecks current generation, grant, signal and session. Stop, new input, Close or revoked authority synchronously abort pending motion. Cancellation never produces a completed receipt; camera restoration/partial state is explicit locally and never represented as a completed target.

Optional pose/scene/media effects serialize in grant order. Authorized captions and speech remain independent of optional readiness/motion; captions preserve existing cue and chunk dwell constraints. Repeated polling cannot restart the same in-flight identity; repeated current target does not run a new motion episode. Existing synchronous executor ports remain supported. Local trip_photo uses the existing load/decode gate and never hardware capture. Receipt denotes rendered software state only.

Targeted RED/GREEN: tests/web/controller-visual-completion.test.mjs plus real compiled renderer integration, failed Canvas copy, late callback, stop/new-input/revoke/close, local photo readiness and text prefix. Evidence is append-only outside the checkout. No browser/device visual acceptance claim.
