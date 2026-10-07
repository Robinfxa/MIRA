# WP01 Codex subscription generation adapter

Status: offline implementation slice; default-OFF. It neither admits a live provider nor
proves subscription model availability, semantic review or user-visible presentation.
Common baseline: ebb578dde665c9c7269e4a64b508182680b2fa66. Mission deadline stays
2026-10-04 08:53:50 UTC. Owner: providers; consumers: GenerationBackend, SessionActor,
bootstrap. Director owns shared tests/quality.toml registration and affected integration.
Resources: injected transport and disposable synthetic subprocesses only. No auth file,
private runtime process, actual inference, paid API, external data or new dependency.

### WP01CX-001 Explicit admission and fixed model
Given default constructor or exhausted request budget, fail before process creation.
Given trusted admitted runtime inputs, spend one request reservation before awaiting.
Use only gpt-6-luna; never silently fallback, retry, discover auth or read environment.

### WP01CX-002 Pinned category isolation
Given pinned v0.159.2, verify executable SHA, initialize protocol, subscription account,
effective disabled feature categories and zero MCP servers before starting a turn.
Use ephemeral fresh thread, empty environments/tools/capability roots, fixed instructions,
no loaded instruction paths, standard tier and low reasoning. Reject version/config/model
drift. This is category isolation, not a claim that all model-advertised tools are absent.

### WP01CX-003 Rebuilt bounded prompt
Given application context, reconstruct only its reliable inputs, accepted prefix,
presentation facts and software audio progress with fixed author instructions. Never
confuse accepted with presented or rendered audio with physical hearing. No transcript
of a coding agent, environment, process output, filesystem or credential enters prompts.

### WP01CX-004 Complete structured candidates only
Given all AgentMessage output including async delivery, treat it as untrusted effects
JSON. Parse duplicate-free bounded exact schema; only separate subtitle/speech and known
authored pose/scene/media controls are supported. IDs and unregistered action values
are unsupported. Per CHAT01-004/005 (2026-10-05), paths, URLs, markup and code quoted
inside subtitle/speech are literal text only; the earlier lexical text ban is superseded.
No delta, partial item, malformed/truncated output or failed/cancelled turn
is a candidate. Yield one complete CandidateRange only after clean terminal completion.
The adapter assigns opaque origin identity; fixture_id does not confer fixture approval.

### WP01CX-005 Fail-closed event protocol
Given any server request, approval, question, unknown event/item/tool, reroute, context
compaction or provider error, interrupt and terminate. No modal, external action or
user-message route is available. Known reasoning is ignored immediately and not logged
or stored. Plan/clock utility events may be ignored, but are never candidate output.

### WP01CX-006 Bounded transport and cancellation
Given adjacent buffered lines, receive all through a dedicated asynchronous reader and
bounded queue. Bound startup, total turn, line, wire, events, output, and shutdown.
Cancellation attempts turn/interrupt for the identified turn, then terminates/reaps the
process within bounded cleanup. Cancelled or late output never yields a candidate.
Stderr is drained/discarded; only fixed error codes leave the adapter.
Given a queue failure followed by OS pipe backpressure, close must finish the pipe
lifecycle as well as reap the child. A known exit code alone is insufficient.
Given cancellation during this cleanup, kill and reap the child and await pipe shutdown
before propagating cancellation; discarded bytes must not re-enter the candidate queue.

2026-10-05 cleanup regression baseline: frozen paired source quality digest
`0d0f19f8d935684f2f7e7dc078e78f0a799eec1e46ab4a23717d3a212e5a8146`.
Owner remains the existing providers contract-file glob; consumers and resources above
are unchanged. Local synthetic Python processes only; no provider or device acceptance.

### WP01CX-007 Integration boundaries
No alternate Actor, history, review, permit, HTTP, configuration, bootstrap or auth system.
CandidateRange still requires the existing independent review and current output epoch.
Shared composition and actual approved model smoke/admission remain separate work.
