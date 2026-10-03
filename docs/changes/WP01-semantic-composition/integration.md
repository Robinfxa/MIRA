# Exact composition seam

Implemented offline 2026-10-03. `SessionActor` and narrow bootstrap injection were
released to this slice by the integration owner; implementation paths returned at
11:12 UTC after 361 scoped tests passed with no recorded source changes.

## Construction

All constructors below are inert. The composition owner supplies authorized transport,
fixed model, separately admitted input/output calibration references and explicit
per-process request budgets. This example performs no network request, discovers no
credentials and does not enable the existing default-off live factory.

```python
from mira.adapters.review.jev import JevReviewBackend
from mira.adapters.review.jev_input import JevInputDecisionBackend
from mira.application.decision_contracts import mira26_author_policy
from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
from mira.bootstrap.providers import Providers

input_decision = JevInputDecisionBackend(
    transport=approved_transport,
    model=fixed_model,
    calibration_ref=input_admission_or_none,
    request_limit=input_request_budget,
)
output_review = JevReviewBackend(
    transport=approved_transport,
    model=fixed_model,
    calibration_ref=output_admission_or_none,
    request_limit=output_request_budget,
)
providers = Providers(
    generation_backend,
    output_review,
    semantic_review=SemanticReviewCoordinator(input_decision, output_review),
    decision_owner=DecisionSnapshotOwner(
        mira26_author_policy(),
        effective_constraints=owned_constraints,
        response_obligations=owned_obligations,
        referents=owned_referents,
    ),
)
# build_container(settings, providers=providers) supplies this pair to each Actor.
```

`input_admission_or_none` / `output_admission_or_none` must remain None until their
separate real admission evidence exists. A reference is an owner admission record,
not a verifier. Synthetic test reference strings must never enter a live factory.
The two budgets are distinct, bounded counters: total maximum attempts is their sum.
Shared adapter instances preserve these per-process counters across sessions; each
Actor has its own semantic await lock. No retry/fallback adds an undeclared budget.
`create_providers(settings)` retains its existing rejection of live backends.

`Providers.semantic_review` and `.decision_owner` are both supplied or both absent.
Default mock/replay injection remains absent. Missing one fails construction.

## Snapshot and execution ownership

- Actor records exact `ReliableUserInput(request_id, text, source)` once on accepted
  submit. Retransmission cannot change source; reliable input survives Stop/failure.
- `DecisionSnapshotOwner.snapshot(state, reliable_inputs)` runs under Actor lock and
  binds request ID, activity, input/output epochs, input count and watermark. It does
  not reconstruct missing event identities or truncate history to pass resource limits.
- Accepted effects remain separate from presentation. Receipt-bound visual effects,
  completed software speech, partial rendered samples and zero-sample unknown facts
  come only from issued effect identities. No observed words or physical hearing are
  inferred. Invalid receipt, audio or accepted identity yields no snapshot.
- The owner accepts explicit raw typed constraints, outstanding obligations and
  controlled referents. It does not guess session persistence/scope from the three
  current-input predicates. All reliable raw history still reaches full output review.
- `SemanticReviewCoordinator.observe(snapshot)` and `.review(snapshot, candidate,
  observation, scope="stage"|"seal")` are separate awaits. It emits judgments, not permits.
- Actor rechecks branch and exact accepted/presented/audio context under its lock
  after each await. Stop/supersede/failure exits. A changed presentation fact rebuilds
  the same pending candidate and re-observes it, within the existing overall timeout.
  Pure bookkeeping revision increments do not invalidate unchanged semantic facts.
- One semantic wait per Actor; cancelled pending turns never invoke a later provider.
  The existing four-task bound and overall timeout remain. A provider that ignores
  every cancellation forever cannot be forcibly terminated by Python; local Stop
  still invalidates authority immediately and no stale result gains a permit.
- Stage ALLOW is applied under the final lock check. A separate `seal` review judges
  final obligation coverage with the last complete candidate and current accepted
  prefix; it issues no duplicate effect. A rejected/unknown seal does not mark complete.

## Output mapping and compatibility

`ResponseContractReviewBackend.review_contract(context, candidate, contract)` is the
application port. `JevReviewBackend.review_contract` rebuilds the exact application
contract, checks all fields/digests and uses a per-call resolver without mutating shared
backend state. Direct `review_detailed` resolvers retain pre/post-await equality checks.

`JevReviewContract` adds typed `snapshot`, `input_observation`,
`basis_snapshot_digest`, `response_contract_digest`, and `synthetic=False`.
`map_response_contract` preserves all facts; output policy revision is the output
question-set revision while author policy revision remains inside the typed snapshot.
No typed facts are packed into effective-constraint strings. Request digest/nonce
binding covers all new fields. Oversized evidence stays UNKNOWN; no lossy truncation.

Legacy raw-only contracts require explicit `synthetic=True`; they must contain no
production typed evidence. Only known synthetic tests/probes may set this. Explicit
synthetic construction does not remove output calibration gates or grant arbitrary
fixture/live content approval. Confidence parser logic and thresholds are unchanged.

## Diagnostics and provenance limits

Input/output review phases retain safe diagnostic spans. Suppressed cancellation
cannot be logged as a successful late input judgment; fixed `jev_input_*` aliases map
observed 401/403/429/timeout/invalid-response/transport failure without reflecting raw
messages. A 403 says permission denied; its underlying cause remains unestablished.

`SessionActor.submit(source="asr_final")` is an internal-only trusted seam. The current
public HTTP endpoint still submits text. Returned ASR text posted by the browser is
reliable user text with ASR attribution unverified: no server-side transcript/stream
identity binding was added, and no frontend assertion is trusted as such proof.
ASR final still does not establish whole-turn handover.

No real key, credential read, live call, calibration, factory activation, D-M admission,
actual physical hearing or device validation was performed by this slice.
