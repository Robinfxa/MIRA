# WP01 explicit development semantic-review composition

Status: narrow, injected development composition. It is not the default live factory,
not a calibration record, and not a claim of live integration or Chinese quality.

The caller separately owns account, credential, paid-call and total-cost admission.
This factory performs no discovery, authentication, network call or resource allocation.
It receives the main generation port and independent typed JEV input/output transports.
The only selectable policy is the exact immutable `user-development-0.6-v1` value.

## Given / When / Then

### DEVCOMP-001 Explicit admission and preserved default guard

Given an explicit `authorized is True`, a callable injected generation port and two
typed transports, plus exactly `USER_DEVELOPMENT_0_6_V1`, when the development factory
is constructed, then it may compose the development stack. Missing/false authorization,
an unsupported or modified policy, or invalid injection is rejected before any transport
call. The existing `create_providers` path remains closed for service-backed modes and
ordinary defaults remain fixture-free of semantic composition.

### DEVCOMP-002 Real adapters and inert construction

Given valid injected ports and explicit selected policy, when the factory constructs
providers, then `Providers.review` and the semantic coordinator use a real
`JevReviewBackend`, while input observation uses a real `JevInputDecisionBackend`;
the stack also contains the application `DecisionSnapshotOwner(mira26_author_policy())`.
Both JEV adapters use exactly `jev-1.13.0`, retain the selected policy, and have no
calibration reference. Construction alone invokes no transport or generation operation.

### DEVCOMP-003 Actor consumes selected policy fail-closed

Given a caller-provided generation backend, when `SessionActor` is composed using the
returned `Providers`, then a structurally valid candidate may be granted only after
both typed reviews explicitly allow under the selected policy. Input UNKNOWN, output
UNKNOWN or REJECT cannot grant effects or seal a turn, and there is no fixture-review
fallback. Synthetic injected transports prove mechanics only.

### DEVCOMP-004 Stop and explicit prohibition retain authority

Given the development stack is active, when the user explicitly stops during delayed
review, then a cancellation-suppressing late ALLOW cannot resurrect the old branch or
issue a grant. An explicit capture prohibition remains in the typed input observation;
a media candidate cannot receive a grant or bypass the existing media boundary.

### DEVCOMP-005 Independent bounded requests

Given separately selected input and output request limits and timeouts, when the
factory constructs the adapters, then each value remains independent and within the
factory's documented finite bounds. An exhausted input budget does not consume the
output budget; both adapters keep their fixed request/response byte caps.

## Verification boundary

Contract and Actor tests use synthetic in-process transports and a synthetic generator.
They make no live call, read no credentials, establish no calibration, and do not
enable the general application factory. They do not establish live integration or
provider quality.
