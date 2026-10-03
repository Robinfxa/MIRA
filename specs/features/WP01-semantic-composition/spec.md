# WP01 semantic input/output composition

Baseline: ebb578dde665c9c7269e4a64b508182680b2fa66. Offline only; no live admission.
Owner: `tests/contracts/test_semantic*composition.py`, uniquely in providers glob.
Consumers: SessionActor, JEV, bootstrap; new port expands integration to all affected
lanes. Resources: synthetic in-process transports/Event barriers only. Director owns
frozen-source affected/full checks. Actor and narrow bootstrap injection were explicitly
released to this slice at 11:05 UTC. HTTP/schema/config/frontend remain untouched.

### WP01COMP-001 Owner-built facts
Given SessionState, exact reliable input events and explicitly owned policy/directives,
build an immutable snapshot retaining accepted vs presented effects, full original raw
inputs and real software sample evidence. Partial audio has no inferred heard words.
Missing event history or unavailable issued identity cannot be invented or truncated.

### WP01COMP-002 Separate awaits and exact currentness
Input observation and output review are separate await boundaries for the Actor to
recheck under its lock. Stop bypasses semantic backends. Branch identity changes exit;
changed accepted/presented/audio facts require rebuild and re-observation of the latest
candidate under the existing turn timeout. Irrelevant state revision changes do not
invalidate identical facts. The coordinator itself creates no permits or state updates. Actor serializes semantic
waits per session, discards superseded pending turns, and reviews explicit seal scope
before declaring completion. Final-ASR provenance is an internal explicit submit
argument only; the current public HTTP input remains text, without a false ASR claim.

### WP01COMP-003 Typed output evidence
A production JEV review contract carries the complete snapshot and input observation
as typed evidence, including policy revisions, directive identity/scope/interpretation,
referent probabilities and partial presentation. Recompute the application contract and
validate all canonical bindings before transport. No evidence goes into raw constraint
strings and no evidence is discarded. Unknown input never calls output review.

### WP01COMP-004 Explicit synthetic compatibility
Existing direct contracts are accepted only with an explicit synthetic flag. They have
no typed production evidence and cannot be mixed with it. Missing input/output Chinese
calibration remains UNKNOWN. No fixture ID or keyword approves arbitrary live content.
Every model answer remains bound to exact request keys/content; confidence logic unchanged.
