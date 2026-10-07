# Explicit voice CLI integration record

This slice supplies an opt-in command around the existing bounded voice factory.
It has not loaded real ADC credentials, called a provider, opened a microphone, or
established account entitlement. The text entry and default offline launcher are
unchanged.

## Actual failures and repairs

The first broad affected run completed 972 provider assertions but exited with
an event-loop/two-socket cleanup failure. It is a failed run, not a passing lane.
Ordered independent reproduction identified a synchronous test's `asyncio.run`
and the command's fallback cleanup as clobbering a stopped policy-owned loop.
The test now uses its assigned async loop. Cleanup uses an explicit owned Runner
loop and preserves an embedding caller's stopped loop.

An independent source comparison also identified missing custom-CA propagation
from the approved runtime to STT's gRPC transport. The command now validates a
bounded explicit PEM CA file and injects standard verifying gRPC credentials;
there is no global trust change or fallback on invalid configured roots.

Four new focused tests were run before the repair and failed (four RED). After
implementation, all 18 launcher cases passed. The four cover external-loop
preservation, exact CA propagation, malformed-CA refusal, and explicit handling
of platform roots versus unsupported custom-directory-only roots.

Focused software checks establish contract behavior only. Full affected/release
and independent post-fix acceptance must bind the final source hashes. Older
00:35 release evidence excludes this CLI slice.
