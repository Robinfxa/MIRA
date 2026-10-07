# CHAT-02 Independent speech permission

Base: immutable mira-conversation-first-capture-20261005T0550Z. Owner: providers
(tests/contracts/test_*.py glob in tests/quality.toml). Consumers: conversation-first
SemanticReviewCoordinator, Actor and direct ASGI speech stream. Resources: existing
Python environment, synthetic in-process JEV and voice transports; no network,
credentials, installs, schema changes, extra state owner or provider admission.

### CHAT02-001 Speech and event independence
Given explicit voice capability and a current structurally valid bound input
observation with speech_restriction confidently NO, when unrelated capture/display
or controlled-object judgment is unknown, then ordinary speech and text remain
available. Optional controls remain held by the existing complete event contract.
Raw scores, wire policy and the selected NOUL thresholds are unchanged.

### CHAT02-002 Permission evidence remains closed
Given missing, malformed, stale, unavailable or unsupported-policy evidence, local
Stop, uncertain/YES speech restriction, or retained raw directives without typed
speech applicability, speech is not admitted. A current NO only says there is no
new restriction; it cannot erase any retained author/user constraint or obligation.
The existing voice capability, current grant, epoch and Stop checks still apply.

Offline synthetic tests establish software boundaries only. They do not establish
real provider quality, spoken naturalness, actual playback or device acceptance.
