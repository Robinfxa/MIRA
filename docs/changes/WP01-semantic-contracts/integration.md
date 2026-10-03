# Exact integration seam

This slice exposes application facts and a separate semantic input port. It is not
an Actor integration, a live factory activation or a calibration admission.

## Application API

`InputDecisionBackend.observe(snapshot: DecisionSnapshot) -> InputDecisionObservation`
is async. `JevInputDecisionBackend` implements it using the existing `JevTransport` /
`HttpxJevTransport`. Constructor keywords: transport, model, calibration_ref=None,
request_limit=0, timeout_seconds=10, snapshot_is_current=None. Fixed model IDs only.
The optional current-snapshot callback is checked before and after the request; the
Actor must still recheck its live identity under its lock before applying observations.

`ResponseContractProducer().produce(context, candidate, *, snapshot, observation,
scope="stage") -> ResponseContract | None` is synchronous and does not mutate any
state. None means no trusted review contract; it is not silent success.

`DecisionSnapshot` fields:

- snapshot_id, event_watermark, activity_seq, input_epoch, input_revision, generation_id
- context: exact GenerationContext (including accepted prefix and audio_progress)
- reliable_inputs: tuple[ReliableUserInput(event_id, text, source="text"|"asr_final")]
- author_policy: AuthorPolicy(policy_revision, character_revision, capability_revision,
  character_facts, allowed_controls=(), constraints=())
- presentation_facts: tuple[PresentationFact(effect, status, observed_text=None)]
- referents: tuple[ControlledReferent(referent_id, description, presentation_effect_id)]
- effective_constraints / response_obligations: tuples of DirectiveFact(directive_id,
  raw_text, source_ref, scope="turn"|"session", interpretation="authoritative"|"observed"|"unknown")
- local_stop=False

Collections must be tuples, bounded and exact. Raw reliable input texts must equal
context.user_inputs, and its last text must equal context.user_text. Fully presented
facts must equal context.presented_effects in order. Referents bind existing fact IDs;
none/ambiguous are reserved provider choices. Unknown facts are retained, never promoted.

Audio facts use the integrator-owned `GenerationContext.audio_progress` and domain
`AudioProgress`. Speech fact identity must match effect_id/digest/output_epoch/activity.
Latest completed progress corresponds to a presented fact; nonzero noncompleted samples
to partial; zero samples to unknown. observed_text must be None: this runtime has no
word alignment. Even completed samples are software rendering, not proof of hearing or
understanding. Do not fabricate the partial fact's Effect from an unreviewed text delta.

`mira26_author_policy()` is explicit local fiction: MIRA, 26-year-old adult original
photographer, fictional rainy cafe. It declares only the exact pose and scene identifiers
implemented by the current scene reducer. It does not reveal external/personal data or
approve any user request. Application capability checks and presentation gates still apply.

## Response facts and adapter mapping

ResponseContract carries contract_id, contract_digest, basis_snapshot_digest,
context_digest, candidate_digest, policy_revision (author policy), raw
 effective_constraints / response_obligations, character_facts, allowed_controls,
scope, snapshot and input_observation; unresolved_items is empty for a usable result.
Digests use UTF-8 JSON, sorted keys, compact separators, no nonfinite values, SHA-256.
For the exact GenerationContext/CandidateRange they match the existing exported output
adapter digest helpers. All snapshot and observation facts also participate in contract ID.

At composition time:

1. Obtain current owner-built snapshot and a matching input observation.
2. Produce the application contract. Return None to JEV if missing/unknown/stale/stopped.
3. Map scalar/raw arrays to JevReviewContract; set the adapter policy_revision to its
   QUESTION_SET_VERSION, preserving author policy revision inside snapshot.
4. Carry snapshot and input_observation as separate typed evidence in an explicitly
   extended output-review contract/state. Never discard them or put them into raw rules.
   The original output adapter does not yet have these fields; until the integration
   owner extends and tests them, a mapping which would lose evidence must return None.
5. Resolve again after review and enforce Actor epoch/activity/Stop checks before permits.

The producer preserves all old raw restrictions and unfulfilled obligations supplied by
their owner. A negative current predicate never removes old restrictions. Every current
raw input remains an obligation; simultaneous no-speech and show-photo stay together.
The three predicates do not claim to normalize every possible request. Unsupported
requirements stay in their original language for full O1–O6 output judgment. Unknown
interpretation prevents a trusted contract. No keyword whitelist approves arbitrary text.

## Admission still needed

- Real account/key, approved synthetic transmission and bounded spend; no live call here.
- Independent Chinese input calibration for fixed model, mira-input-v1, thresholds and
  actual workload. A calibration_ref is a trusted admission reference, not a verifier.
- Independent output review calibration and complete trusted context producer wiring.
- Existing reviewed fixed-asset identity or real-pixel D-M for MEDIA; this producer
  deliberately returns None for every MEDIA candidate. No new image admission exists.
- Runtime one-in-flight/latest-pending scheduling and exact post-await revalidation.

Explicit Stop runs deterministically in the local/browser/Actor control path before any
semantic call. local_stop guards accidental invocation, not a new Stop implementation.
Do not feed stop requests through this provider or wait for it to agree. ASR final is
reliable transcription, not whole-turn handover. Privacy, turn-taking, costs and permits
remain application decisions. Tests here prove mechanics only, not semantic quality.

## Follow-on composition implemented · 2026-10-03 11:14 UTC

The previously missing typed output mapping and Actor wiring above are now implemented
by the separate WP01 semantic-composition slice. See
[the exact construction and currentness seam](../WP01-semantic-composition/integration.md)
and [its scoped evidence](../WP01-semantic-composition/verification.md).
The earlier text describes this original DTO-only handoff; it is not a remaining claim
that the output adapter lacks typed fields. Input/output calibration and live factory
admission remain separate and default-off. HTTP ASR provenance remains unverified.
