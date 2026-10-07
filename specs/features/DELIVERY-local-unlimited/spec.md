# Delivery: unlimited local interaction, finite services

Base: immutable mira-xiahe-chapter-final-20261006T0721Z; manifest ce4a89d0be9f3e1fe3ea313be554a4adf0c0c2048083fe4fd7562c8a84b75807.
Owner: continuous lane for the new local-policy tests; Actor/domain and listening service are this isolated worker's write surfaces. Bootstrap/config/CLI/schema/web merge remains with integration owner. No network, providers, credentials, persistent user database, installation, deployment or full/release checks.

### DELIVERYLOCAL-001
Given explicit None local limits, more than the old 20 turns, 12 commits, four leases and 120 seconds remain usable. Existing finite profiles continue enforcing exactly their selected finite limits. None means absent local quota, never a large numeric sentinel. Request/response sizes, concurrency, pacing, queues, cleanup and provider request budgets remain finite.

### DELIVERYLOCAL-002
Given an unlimited listening lease, each recognition RPC still ends within its finite provider duration. Normal bounded renewal consumes the shared irreversible request budget; failure does not retry, cancellation does not refund, and restart does not reset it. Exhaustion visibly terminates voice and preserves recognized draft. Two sessions share the ledger while their text remains isolated.

### DELIVERYLOCAL-003
Given indefinite logical counts, raw text, exact idempotency records and presentation evidence use bounded recent retention. Original source identities, provenance and current branch authority are unchanged within the window. Expired original input retries fail stale_activity without new service usage; expired presentation sequences can never become new facts. Omitted-history metadata is explicit and never asserts full recall. No summary model requests or automatic persistence are introduced.


## Subscription text default, 2026-10-06

Baseline: immutable mira-luna-tool-integration-20261006T1431Z (1515 delivery). The new subscription default follows the user request to test hundreds of turns. Owner: providers for tests/contracts/test_subscription_unlimited_budget.py through the existing unique contract glob; web for tests/web/main-generation-budget.test.mjs. Consumers: direct adapter, tool continuation, CLI/check declaration, usage composition and the existing error surface. Validation is synthetic HTTP and compiled frontend only; no model, credential, Google or device calls.

### DELIVERYLOCAL-004
Given chatgpt_subscription with no explicit generation/turn count, the production defaults are None for both model requests and text turns. Three hundred Actor turns including one hundred tool calls consume four hundred synthetic requests without a count limit; existing recent-history bounds remain. Official API defaults stay 20/20, probe composition stays finite, and explicit finite integers still apply. Each turn remains limited to one operation and one continuation; cancellation closes the stream and releases its reservation without retries or stale continuation.

### DELIVERYLOCAL-005
This earlier finite-voice default is superseded by VOICE-DEFAULT-UNLIMITED. Given subscription text has no count limit, continuous-listening and shared STT counts now default to None; explicit finite compatibility composition and per-RPC duration remain supported. Image attempt caps do not change. Startup/check renders JSON null and explicit text/generation count policies; image readiness accepts an unlimited dialogue count without treating it as exhausted. When an explicitly finite local generation cap is exhausted, generation_budget_exhausted is a safe public code with limit_reached diagnostics and an actionable message. Provider 429 remains quota_exhausted; response-size limits remain response_limit. Repeated snapshots retain the unsent draft and already displayed conversation history.


Recovery check (web owner: tests/web/controller-terminal-recovery.test.mjs): a terminal session/activity/output/error identity stops playback and external capture once. Repeated identical/error-equivalent polls continue displaying the error without stopping explicitly restarted continuous capture. A new error identity or new turn stops once again; explicit Stop/Close still stop immediately, and a late old snapshot cannot replace a newer turn. No automatic provider retry is introduced.
