# Direct requested Fast tier

Baseline: immutable mira-integration-20261005T2238Z source copy (no Git metadata).
Owner: providers; consumers: CLI, diagnostics exporter, Actor/HTTP unchanged.
Resources: existing Python runtime, synthetic HTTP only, no auth reads/network/provider calls.
No threshold, voice, appearance, reasoning, route, retry or request-ceiling changes.

### FAST-001 Scoped requested default
Given chatgpt_subscription and gpt-6-luna, when omitted, request Fast using service_tier=priority. Other model/route defaults omit it. Explicit standard on subscription omits service_tier as first-party Codex does; API standard uses default. Explicit fast remains available. Invalid choices fail before credentials/network.
### FAST-002 Requested versus returned facts
Given a completed response, when final tier is supplied, report only closed known tier classes separately from the selection. Absent/null/unknown metadata never confirms Fast. Optional metadata cannot reject otherwise valid content; different tiers are visibly reported. Created/in-progress metadata is not final confirmation. Report callbacks are best-effort and cannot fail content.
### FAST-003 Failures and cancellation
Given rejected Fast input, quota, authentication, timeout or cancellation, expose a safe terminal diagnostic and preserve the original failure. Recognized service_tier rejection is recoverable by an explicit standard restart. No retry, automatic fallback, extra credential fetch or extra inference. A later explicit call remains bounded by the original budget.
### FAST-004 Offline declaration and bounded local acceptance
Given check, report requested tier, wire tier, 2.5x subscription Fast usage disclosure and provider confirmation not_run, without loading auth or making requests. CLI wiring is tested with synthetic transport. Real user local testing is separate, one generated text turn per selection, no audio or memory.
