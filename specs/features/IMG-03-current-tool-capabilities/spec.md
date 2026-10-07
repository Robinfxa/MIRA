# IMG-03: Current-request fictional image capability projection

Base: immutable mira-live-regression-final-20261006T0542Z. Owner: direct_tools.py and the new image capability contract tests. No bootstrap, schema, Actor, voice policy, generation budget or authorization changes. Test owner: providers, registered by the existing tests/contracts/test_*.py glob in tests/quality.toml. Consumers: direct Responses request body and its one continuation. Resources: existing Python runtime, self-authored fixtures and HTTPX MockTransport; no real config, credentials, network, image generation or dependency install.

### IMG03-001 Project the actual current request
Given the application-selected tool definitions, when a Responses request is serialized after the existing two-request budget gate, its capability facts must exactly match the tools present in that request. Fixed-photo availability and permission to request a new fictional image are separate booleans. Disabled story/runtime, missing custom-brief authorization, unavailable review, exhausted local image quota, and one remaining dialogue request must not advertise generation. User text cannot alter these application facts or grant an absent tool. Absence describes this request only and cannot justify a permanent inability or an invented quota/configuration cause.

### IMG03-002 Separate new fiction from existing inventory
Given the custom function-tool path, when context is serialized, remove the obsolete catalog-only story_image_scenes list and legacy image-proposal contract. Keep approved canon, fixed-photo provenance, prior generated-image observations and presentation evidence. A new fictional scenery/object image is distinct from selecting an existing photo and from taking a physical photograph. A supplied generate_story_image only permits a reviewed attempt; it is not proof of provider support, an existing image or successful display.

### IMG03-003 Continuation and unchanged boundaries
Given an admitted tool call and its bounded continuation, the latest request must project no callable tools, even if its initial request offered generation. Preserve the prior function call/output and newest facts. Keep the strict response schema, tool parser, two-model-request limit, one-tool limit, all image reviews/authorizations, Stop fences and no-fallback behavior unchanged. Unsupported tool calls still fail closed.

Verification: directed RED/GREEN on actual serialized synthetic HTTP requests, then explicit-file affected checks because the capture has no Git metadata. Live dialogue quality/account support and device acceptance remain untested.
