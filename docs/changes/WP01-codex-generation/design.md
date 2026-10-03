# WP01 Codex generation design and integration contract

This slice is deliberately default-OFF and has not run a real Codex model request.
It implements the existing GenerationBackend port and returns only CandidateRange.
No Actor, review, permit, runtime configuration loader or HTTP endpoint is introduced.

## Trusted construction

```python
CodexRuntime(
    executable=Path('/approved/absolute/codex'),
    codex_home=Path('/approved/private/codex-home'),
    runtime_cwd=Path('/approved/private/empty-runtime'),
    environment=approved_process_environment,
    executable_sha256=PINNED_EXECUTABLE_SHA256,
    expected_config_sha256=approved_effective_config_digest,
    policy_environment_confirmed=False,  # caller must verify managed policy preservation
)
CodexAppServerGenerationBackend(
    runtime=runtime,
    admitted=False,                 # explicit later admission required
    request_limit=0,               # default: no attempts
    limits=CodexLimits(),
    transport_factory=None,        # None selects concrete stdio subprocess
)
```

Only the composition root may supply these values. They are not generated content or
an HTTP/user-supplied command/config surface. No executable lookup, environment lookup,
credential lookup, auth-file read, authentication reconstruction or API fallback exists.
The fixed production executable digest is Linux installation-specific; another version
or binary requires explicit review and code/profile repinning, not an automatic update.

The real subprocess factory requires a caller-supplied SHA256 of the approved complete
`config/read` result.config, serialized as JSON with sort_keys=True, separators=(',', ':'),
ensure_ascii=False and UTF-8. An inspection-home hash is not the authenticated-runtime
hash. The adapter never learns or approves that hash automatically. The caller must use
its approved native control-plane preflight. No credential/token contents are required.
The digest is compared before starting any turn; selected category checks remain mandatory
in addition to the digest. Injected offline test factories may omit a config fingerprint.

The runtime directories must be absolute canonical non-symlink paths, distinct, owned by
the current Unix user and mode 0700; the runtime cwd must be empty. The adapter examines
only executable bytes and directory metadata/emptiness, never home contents. The native
Codex process itself owns its approved subscription authentication and may maintain its
own runtime files. Empty cwd and category restrictions are not an OS filesystem sandbox.

Process environment is an explicit immutable allowlist: HOME/PATH/LANG/LC_ALL/TMPDIR,
HTTP(S)/ALL/NO proxy uppercase/lowercase values and existing CA-bundle settings. Values
are not copied from ambient environment, changed, logged or added to prompts. CODEX_HOME
is set only from the trusted runtime input. API-key, external token, provider routing,
LD_PRELOAD and other arbitrary environment overrides are rejected. Explicitly supplied
CODEX_PERMISSION_PROFILE, CODEX_NETWORK_PROXY_ACTIVE and CODEX_SANDBOX_NETWORK_DISABLED
are preserved unchanged. Real creation also requires policy_environment_confirmed=True
after the parent verifies all applicable managed policy controls are preserved. This
default-false gate is not inferred from an empty environment, category restriction or
config digest. If the deployment requires additional unsupported policy environment
keys, runtime activation remains blocked pending an explicit reviewed contract. Never
remove a platform permission check to make the adapter start.

## Exact profile and upstream evidence

Installed CLI version: 0.159.2. Official rust-v0.159.2 source commit:
ff6aec96948b70d94983af2641a6b67c94faeff5.

- Executable SHA256: 1748767b230ebfc3d4ab7e4e254920d0c0ad9691fd8c11f190e7d44511a4a92e
- Generated ThreadStartParams SHA256: 80a40a7fac15b4bf70efb7f893fb353acc0a0d30c68f54aee4f01923deca85de
- Generated TurnStartParams SHA256: 07771223642e1b61bd9aac0069fc0f98143a1c047724ca02c7ceb13653442738
- Pinned core tools/spec_plan.rs SHA256: 849ef21d4e5c83febdc31eacd7609911d43e3f69a35168fe02ae899273b5ef3e

The auth verifier supplied these existing source artifacts; this worker did not start
the actual logged-in runtime or inspect any authentication file. Generated schemas were
read directly. The profile consists of `features.respect_system_proxy=true`, app-server
stdio, web_search="disabled", and disabled apps/plugins/browser_use/computer_use/
multi_agent/shell_tool/image_generation/tool_suggest/sleep_tool/token_budget.
The effective config must have each flag explicitly false, respect_system_proxy true,
web search disabled and a present empty MCP-server map. Null default model/provider is
allowed in config, followed by exact selected model/provider checks on thread creation.
Custom hooks, notify commands, model providers/routes and instruction files are rejected.
The native default chatgpt_base_url https://chatgpt.com/backend-api/ is allowed exactly,
as source-verified in pinned config/mod.rs lines 4401–4403; arbitrary alternatives fail.
This is a native process config check, not a direct backend HTTP client.

Initialize uses experimentalApi=true followed by initialized. account/read with
refreshToken=false must report a native chatgpt account; account metadata is discarded.
Each request starts a fresh ephemeral thread with environments=[], dynamicTools=[],
selectedCapabilityRoots=[], runtimeWorkspaceRoots=[], exact model gpt-6-luna,
allowProviderModelFallback=false, never approvals, user approval reviewer, read-only
sandbox and fixed MIRA author instructions. Loaded instructionSources must be empty.
The selected thread must report the pinned CLI version, no environments or history,
exact gpt-6-luna/openai, and the expected cwd. Turn start repeats empty environments,
uses low effort and standard tier, and supplies the fixed effects output schema.

The generated schema says environments=[] disables environment access. At this pinned
source revision spec_plan.rs gates shell/exec/write_stdin at line 1083, apply_patch at
1269 and view_image at 1283 on environment presence. This is category isolation.
It is expressly not blanket tools=[]: plan and clock utilities can remain. User-input
and async-message tools may also be advertised by a model; their events are handled
fail-closed or as untrusted candidate data, never routed to a user or external agent.

## Event allowlist

Handled notifications:

- thread/started, thread/status/changed, turn/started, turn/completed: validated identities
  and pinned thread/state checks. Only completed without error can terminate successfully.
- item/started, item/completed: only userMessage, agentMessage, reasoning, plan and the
  precise functionCallOutput names (plain update_plan or clock.curr_time) are accepted.
- item/agentMessage/delta: bounded in-memory partial output, never yielded.
- item/reasoning/textDelta, item/reasoning/summaryTextDelta,
  item/reasoning/summaryPartAdded, item/plan/delta, turn/plan/updated,
  thread/tokenUsage/updated: identity checked, body discarded without retention/logging.
- account/updated: only chatgpt; remoteControl/status/changed: only disabled.
- warning: bounded known notification shape, discarded without forwarding text.

Every server request, even a seemingly benign request, is forbidden. Approvals,
request_user_input, async AgentMessage.questions, unknown event/item/tool, model/rerouted,
provider error, custom hooks and unrecognized protocol extensions cancel/fail the request.
Unknown legitimate events may therefore reject a live turn until separately reviewed;
no event widening is performed in response to model output.

All AgentMessage bodies, including delivery="async", commentary and final_answer, enter
the same strict effects parser. Async messages never call user_message or another agent.
Nonempty questions fail immediately. Message text must be duplicate-free exact JSON with
1–8 effects total and only kind/value fields. Speech and subtitles remain distinct.
Known pose/scene enums come from the existing authored frontend controls. MEDIA is absent.
Obvious URL/path/markup/code-delimiter payloads are rejected; all accepted text is literal
data and never interpreted as a command, resource location, code or effect identifier.
Semantic content still requires the existing independent reviewer. No fixture is approved
because it resembles authored content: the adapter mints a fresh codex-origin UUID.

## Bounds and cancellation

Default limits: startup 10 seconds, complete turn 60 seconds, each shutdown stage 1 second,
128 KiB/line, 1 MiB total incoming wire, 16 KiB candidate output, 64 KiB rebuilt prompt,
1024 messages and a 128-line queue. Constructor validates finite positive bounded limits.
No automatic model retries occur. One request reservation is spent before the first await,
including failures, timeout and cancellation. This local attempt count is not an account
quota, token-spend ledger or provider-wide budget; the composition root owns those scopes.

A dedicated asyncio StreamReader task reads lines into a bounded queue, including adjacent
lines already buffered in one OS read. No select/TextIO combination is used. Stderr is
drained and discarded in bounded chunks, never captured for diagnostics. The process is
started directly without a shell or arbitrary command interpolation. Spawn cancellation
retains creation ownership long enough to reap an already-created synthetic/native child.

When thread/turn IDs are known, failure or cancellation attempts turn/interrupt and waits
briefly for that turn's terminal state, discarding all late candidate output. If cancellation
happens before turn identity is returned, interrupt cannot be addressed and process cleanup
is the fallback. Then stdin closes, the process group receives TERM, then KILL if needed,
and wait/reap is bounded. Reader tasks and candidate buffers are cleared. No candidate is
yielded until terminal output validation and successful process cleanup have completed.
Pathological OS process-creation/reaping failures remain operational errors, never success.

## Still unverified and out of scope

Actual gpt-6-luna completion/quota, approved authenticated-runtime config digest, factory
admission, provider interoperability, Chinese quality, live semantic review, persistence,
real audio, browser/mobile behavior and cross-platform process cleanup are unverified.
The existing Actor owns output epochs and cancellation fencing; review owns semantics;
compiler/permits own effect identity and presentation authorization. This adapter does
not replace or weaken any of those boundaries.
