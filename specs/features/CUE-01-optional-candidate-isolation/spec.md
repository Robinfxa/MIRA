# CUE-01: Valid dialogue survives invalid optional suggestions

Base: immutable 0721 source. Owner: generation character parser, direct-tool adapter, closed local candidate diagnostics and narrow Actor emission. Providers owns tests/contracts/test_optional_candidate_isolation.py via the existing unique tests/contracts/test_*.py glob in tests/quality.toml. Consumers: actual direct HTTPX wire, Actor text/speech grants, independent review, diagnostic export. Resources: existing Python environment, synthetic fixtures and MockTransport only. No provider call, retry, account, authentication, user transcript or voice-policy edit.

### CUE01-001 Preserve only strictly valid dialogue
Given one complete valid JSON object with recognized top-level fields and strict nonempty subtitle/speech, when a recognized optional story, affect or authored pose/scene suggestion is invalid, preserve the exact dialogue and hold all optional controls/proposals for that candidate. Never infer an action, approval, image, role, gift or receipt. Valid candidates keep existing behavior. The legacy strict parser remains strict unless the direct ordinary-conversation path explicitly selects this policy.

### CUE01-002 Keep structural and tool boundaries
Given invalid JSON, unknown top-level/effect fields, invalid or empty dialogue, unsupported effect kinds, media effects or image_proposal, reject under the existing boundary. No JSON rescue, implicit tool call, discarded function_call_output, retry or permissive exception swallowing. Inactive image_proposal:null remains rejected as its own regression case. Tool-adjacent commentary and final continuation retain their existing strict protocol.

### CUE01-003 Record closed local holds
Given a held optional suggestion, emit only a closed reason tuple and bounded counts through the existing local diagnostic sink/exporter. Keep these diagnostics out of candidate_data/provider/JEV payloads. Invalid diagnostic metadata cannot grant effects. Preserve precise known validation error reasons, including character proposal failure, instead of generic validation. Raw candidate text, identifiers, paths and credentials are excluded.

### CUE01-004 Recover on the next real Actor turn
Given a failed optional role/control proposal with valid dialogue, the Actor may grant and acknowledge only text/speech, with no optional effect receipt or role state activation. The next independent valid turn still completes. An actually valid explicit role statement retains the existing independent approval/receipt gates. Synthetic speech yields PCM; this does not establish device playback. Stop still fences late results.

Actual user exports show four generic candidate validation failures; their specific bad fields remain unknown. Offline repair evidence must not be described as reproduction of those undisclosed bytes.
