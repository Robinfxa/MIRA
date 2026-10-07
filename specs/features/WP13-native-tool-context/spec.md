# WP13 native tool chapter context and closed observations

Base: immutable frozen1515 source `mira-luna-tool-integration-20261006T1431Z`.
Owner: providers, uniquely registered by `tests/contracts/test_*.py` in tests/quality.toml.
Consumers: subscription/API serialized Responses, SessionActor, diagnostics privacy/export.
Resources: synthetic HTTP/SSE and compiled software receipt fixtures only. No provider,
credential, private dialogue, Mac, new asset, retry, paid fallback, JEV or domain change.
Affected validation at integration: architecture/config/providers/actor/http/specs/tooling;
this slice runs focused tests, with final affected gate owned by integration.

### WP13NATIVE-001 One actionable chapter snapshot

Given a story-enabled native request, including dormant state and held continuation,
serialize current chapter at facts.character_story.chapter. Keep exactly one current
canon projection per context; native_tool_contract.chapter_source only references it.
Keep domain and legacy wire unchanged, existing prompt byte limits enforced, and
subscription/API routes equivalent. Use allowed_next, typed current role/offer claims,
and author canon. Clarifying x.ask_role is allowed outside chapter milestone list.

### WP13NATIVE-002 Closed hold result and ordinary body

Given an application DomainError(tool_held), preserve only its allowlisted finite reason
in actual function_call_output. Unknown error strings/codes remain precondition.
A held prerequisite is not permanent inability and must not erase dialogue. Keep genuine
function-call/output correlation and one operation plus one continuation with no more tools.

### WP13NATIVE-003 Role, gift, canon and cancellation boundaries

Mixed-script direct role claims and current typed confirmations still require matching
recognition receipt. Ordinary dialogue, stale references, denial, off-topic text and
post-Stop receipts cannot activate a role. Preview is not offer or handover; full chapter
and current acceptance stay required. Lighthouse canon remains Mira's solo trip.

### WP13NATIVE-004 Closed native observation and compatible export

Record only eight fixed tool names, finite transition/status/reason, original operation
epoch/activity, known chapter before/after and role flags, and actual receipt kind.
Requested is not executed; pending is not shown. Cancellation has original operation
identity and no new-epoch after-state. Diagnostic failure cannot affect dialogue.
Use existing event/export chain; old records still export and arbitrary/raw fields,
unknown values, body hashes, input, arguments and exception text are excluded.

### WP13NATIVE-005 Concrete outfit intent and factual failure explanation

Given a contextual request to see the inner top or remove the raincoat/outer layer,
native guidance selects set_outfit cream_inner_only while keeping the inner top on;
putting on the jacket selects black_jacket. Execution still requires a model function
call and exact display receipt. Quoted/negated/hypothetical words cannot force code.
Given failed/held/unavailable result, describe only actual status/known reason; an
unknown reason stays unknown. Never invent a provenance or moral refusal, provider
error, quota or permission reason, and do not speak internal field/source labels.

### WP13NATIVE-006 Current pending job versus capacity for a new one

Given an already-started image job whose tool result is pending/generating, a
continuation with no tools and zero remaining capacity for another job does not
change that current result to failed or not started. Describe only observed progress.
The process gate remains busy until settlement; readiness counters are diagnostics,
not model facts. Later terminal state does not rewrite the earlier tool result or
cause an extra model call or automatic retry.
