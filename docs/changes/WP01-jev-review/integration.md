# WP01 JEV integration seam

## Delivered

- `mira.adapters.review.jev.JevReviewBackend` implements the unchanged async
  `ReviewBackend.review(context, candidate) -> ReviewObservation` port.
- `review_detailed` returns `JevReviewResult` with sanitized usage and opaque content /
  contract digests. It does not retain raw requests, answers, headers or exception text.
- `mira.adapters.review.jev_support.http.HttpxJevTransport` performs one actual fixed
  HTTPS POST using an injected SecretStr. It supports an injected httpx transport for
  offline tests, and creates no HTTP client or network resource on construction.

Backend keyword arguments are transport, model, contract_resolver,
calibration_ref=None, request_limit=0, timeout_seconds=10. Request budget is bounded
0–100 and shared by concurrent reviews on that instance; the owner must not continually
recreate instances to evade a run budget. The transport has no independent retry loop.
The parent remains responsible for account-wide authorization, privacy and spend.

## Exact trusted contract

Frozen JevReviewContract fields:

- contract_id, policy_revision (`mira-output-v1`)
- context_digest, candidate_digest, using the exported canonical digest helpers
- effective_constraints: tuple of original applicable restrictions
- response_obligations: nonempty tuple of original applicable obligations
- character_facts: nonempty tuple of authorized character/scene facts
- allowed_controls: exact tuple of EffectProposal POSE/SCENE values, default empty
- scope: stage or seal, default stage

The trusted resolver receives the exact GenerationContext and CandidateRange. It must
return None when it cannot establish complete current facts. It is consulted again after
the response, so a revoked or changed contract cannot approve. The Actor must still check
current state/output epoch and cancellation before issuing permits; an immutable snapshot
cannot itself know about unrelated state changes.

Application code must not import an adapter DTO. A transport-independent application
producer may expose its own facts; the composition root translates them into the adapter
contract. No shared application/config/actor/bootstrap files were edited by this worker.
The initial foundation lacks a full ResponseContract producer, partial/unknown presented
history and input interpretation. Do not invent those facts or call this complete G05.

Each request includes the entire candidate and full supplied context, including accepted
but unpresented prefix. All O1–O6 dimensions and each effect receive an answer keyed by
request nonce + content digest. A previous response cannot approve a subsequent request,
even if the content is identical. No fixture catalogue is imported.

SUBTITLE and SPEECH are distinct exact content. A caption approval cannot approve speech.
POSE/SCENE require exact control coverage and semantic review. MEDIA always yields UNKNOWN;
textual descriptions never establish a real-pixel D-M approval. Other new effect kinds are
unsupported until explicitly admitted. Long requests fail rather than silently truncate.

## Calibration is still blocked

The provisional policy uses Choice allow/reject/unknown. A substantive reject requires
at least 0.99 selected probability and 0.985 confidence. Low confidence stays unknown.
Every required choice must meet the allow thresholds. Returned confidence must agree
with the documented three-way Choice statistic (small numerical tolerance only).

`calibration_ref` is a trusted caller admission reference; it is not a validator or proof.
It must refer to completed Chinese evaluation of this exact fixed model, versioned
questions, thresholds, controls and intended workload. No such production admission was
created here. Tests use a clearly named synthetic admission only. Missing admission may
perform an explicitly authorized smoke, but even unanimous valid allow answers return
UNKNOWN / jev_policy_not_calibrated. Passing unit tests cannot fill this field.

Error/unknown result codes preserve authentication, request validation, rate limiting,
overload, timeout, transport failure, malformed response, stale contract and semantic
uncertainty distinctions. Invalid response usage is not billed-as-zero. No soft rejection
is retried against another model or fixture.

## Next slice: explicit Input Decision, not silently omitted

Reuse the one-request TypeSafe transport, but give input interpretation its own typed
request/observation and versioned question set. Proposed request facts: immutable
snapshot_id, input_epoch, input_revision, original user_text, relevant original constraints,
current scene/entity IDs, and actually presented plus accepted-prefix facts. Bind request
identity and exact answer coverage with the same nonce/digest discipline.

Minimal independent observations:

- Noul: explicit speech restriction, explicit camera/capture restriction, explicit request
  to display an object. These are simultaneous labels, not mutually exclusive choices.
- Choice: referenced controlled object ID, with explicit `none` and `ambiguous` alternatives.
- Preserve original user text and unresolved obligations. Do not ask JEV to generate state
  patches or fabricate normalized permissions from absent closed-set predicates.

The observation must keep per-primitive values, validity/unknown and input identity.
Actor-owned policy combines them with explicit controls. Noul has no returned confidence;
Choice confidence is not interchangeable with Noul probability. Chinese thresholds and
contradiction rules require their own evaluation. This proposal is not an implemented
input-decision adapter and is not silently replaced by output review.

## Runtime dependency

httpx 0.28.1 already exists in requirements/dev.lock and the shared .venv313. No dependency
was installed or lock file edited. The director should ensure the eventual live runtime's
installation route includes httpx; the initial pyproject runtime list did not include it.
