# PHOTO-03: Deterministic admission for the shipped fixed photo tool

Base: immutable mira-response-contract-final-20261006T0522Z. Owner: fixed-photo application slice. Files: application/session_actor.py and application/generation_tool_execution.py. Domain transitions, bootstrap, schemas and frontend are unchanged. Tests belong uniquely to providers through the existing tests/contracts/test_*.py glob; compiled frontend checks use the web owner. Downstream consumers: Actor, Responses function result/continuation, photo progress, exact receipt, dismissal and Stop fences. Resources: existing Python/Node runtimes; synthetic HTTPX/SSE, Actor and DOM only. No real provider, new spend, credentials, environment, private database or dependency installs.

### PHOTO03-001 Fixed asset admission
Given an actual advertised show_photo call with exact {photo_id:trip_photo} arguments on the current active unsealed request, when the shipped asset is readiness/hash-attested and local dismissal/effect-capacity boundaries permit it, compile and grant that one fixed media effect directly. Do not request additional input/output semantic approval or manufacture a JEV ALLOW. A visible exact existing receipt may be reused. Private paths, URLs, unknown assets, capture and generated images are outside this authority. Legacy media proposals and every other action keep their existing review path.

### PHOTO03-002 Results and retries
Given a granted photo without an exact accepted receipt, report pending, failed or held truthfully. A failed display followed by a new actual tool call creates a new attempt/grant; stale progress cannot overwrite it. Only the exact matching receipt can establish shown. Keep two bounded Responses calls (tool selection and continuation), no automatic retry or third generation.

### PHOTO03-003 Lifecycle and scope
Stop, new input, dismissal, close, invalid arguments, unavailable readiness and effect capacity remain closed. A cancelled operation never revives. Generated image admission, review, pixel qualification, budgets and provenance are unchanged. Existing frontend prepare/load/decode/presentation and receipts remain required.

Verification: directional RED/GREEN followed by affected checks from an explicit file list (ZIP source has no Git base). Integration owns full/release/device acceptance. Diagnostic ZIP review established three fresh photo attempts held by semantic uncertainty; it did not establish an asset-load failure or a model-prompt bug. This feature intentionally changes the fixed-asset admission policy within the approved tool scope.
