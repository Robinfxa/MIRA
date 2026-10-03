"""Application-owned semantic composition; no providers, IO or permit authority."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from mira.application.contracts import (
    CandidateRange, GenerationContext, ReviewObservation, ReviewVerdict, audio_context_progress,
)
from mira.application.decision_contracts import (
    AuthorPolicy, ControlledReferent, DecisionSnapshot, DirectiveFact, InputDecisionObservation,
    InputDecisionStatus, PresentationFact, ReliableUserInput, ResponseContractProducer,
    evidence_digest, valid_snapshot,
)
from mira.application.ports.decisions import InputDecisionBackend
from mira.application.ports.semantic_review import ResponseContractReviewBackend
from mira.domain.models import EffectKind, SessionState


def _context(state: SessionState) -> GenerationContext:
    return GenerationContext(state.user_inputs[-1], state.user_inputs, state.presented_effects,
                             state.output_epoch, state.active_grants, audio_context_progress(state.audio_progress))


@dataclass(frozen=True, slots=True)
class DecisionSnapshotOwner:
    """Explicit owner facts, not inferred rules. Call snapshot while holding Actor lock.

    Missing reliable events or issued effects fail closed. This builder does not repair
    imported state, invent event IDs, guess referents, or call a model. Only acknowledged
    presentation and audio progress create presentation facts; accepted-only effects
    remain solely in the accepted prefix. Retained directives stay in original language.
    """
    author_policy: AuthorPolicy
    effective_constraints: tuple[DirectiveFact, ...] = ()
    response_obligations: tuple[DirectiveFact, ...] = ()
    referents: tuple[ControlledReferent, ...] = ()

    def snapshot(self, state: SessionState,
                 reliable_inputs: tuple[ReliableUserInput, ...]) -> DecisionSnapshot | None:
        if type(state) is not SessionState or not state.request_id or not state.user_inputs:
            return None
        latest = {progress.effect_id: progress for progress in state.audio_progress}
        issued = {effect.id: effect for effect in state.issued_effects}
        if (len(issued) != len(state.issued_effects) or not set(latest) <= issued.keys()
                or any(issued.get(effect.id) != effect for effect in state.active_grants)):
            return None
        for receipt in state.receipts:
            effect = issued.get(receipt.effect_id)
            if (effect is None or effect.kind == EffectKind.SPEECH
                    or (receipt.digest, receipt.output_epoch, receipt.activity_seq)
                    != (effect.digest, effect.output_epoch, effect.activity_seq)):
                return None
        presented_ids = {effect.id for effect in state.presented_effects}
        facts = []
        for effect in state.issued_effects:
            if effect.id in presented_ids:
                facts.append(PresentationFact(effect, "presented"))
            elif effect.id in latest:
                progress = latest[effect.id]
                status = "partial" if progress.rendered_samples > 0 else "unknown"
                facts.append(PresentationFact(effect, status))
        result = DecisionSnapshot(
            "snapshot-pending", state.revision, state.activity_seq, state.input_epoch,
            len(reliable_inputs), state.request_id, _context(state), reliable_inputs,
            self.author_policy, tuple(facts), self.referents, self.effective_constraints,
            self.response_obligations,
        )
        if not valid_snapshot(result):
            return None
        return replace(result, snapshot_id="snapshot-" + evidence_digest(result))


def snapshot_same_branch(state: SessionState, snapshot: DecisionSnapshot) -> bool:
    """Stop, supersede, failure or close must exit instead of restarting an old branch."""
    return (type(snapshot) is DecisionSnapshot and not snapshot.local_stop
            and state.request_id is not None
            and (state.request_id, state.activity_seq, state.input_epoch, state.output_epoch,
                 len(state.user_inputs), state.user_inputs)
            == (snapshot.generation_id, snapshot.activity_seq, snapshot.input_epoch,
                snapshot.context.output_epoch, snapshot.input_revision,
                snapshot.context.user_inputs))


def snapshot_matches_state(state: SessionState, snapshot: DecisionSnapshot) -> bool:
    """Ignore bookkeeping-only revision changes, but re-observe changed real evidence.

    A receipt, audio-progress fact or newly accepted range changes the exact context.
    The Actor rebuilds the pending candidate's snapshot under its existing timeout;
    observations never migrate across these snapshots. No lock is acquired here.
    """
    return snapshot_same_branch(state, snapshot) and _context(state) == snapshot.context


class SemanticReviewCoordinator:
    """Two explicit await boundaries let the single state writer check both results."""
    def __init__(self, input_decision: InputDecisionBackend,
                 output_review: ResponseContractReviewBackend) -> None:
        self._input_decision = input_decision
        self._output_review = output_review
        self._producer = ResponseContractProducer()

    async def observe(self, snapshot: DecisionSnapshot) -> InputDecisionObservation:
        if not valid_snapshot(snapshot):
            return InputDecisionObservation("invalid", "", InputDecisionStatus.INVALID,
                                            "semantic_snapshot_invalid")
        if snapshot.local_stop:
            return InputDecisionObservation(snapshot.snapshot_id, evidence_digest(snapshot),
                InputDecisionStatus.UNAVAILABLE, "semantic_local_stop")
        return await self._input_decision.observe(snapshot)

    async def review(self, snapshot: DecisionSnapshot, candidate: CandidateRange,
                     observation: InputDecisionObservation | None, *,
                     scope: Literal["stage", "seal"] = "stage") -> ReviewObservation:
        if type(snapshot) is not DecisionSnapshot:
            return ReviewObservation(ReviewVerdict.UNKNOWN, "semantic_snapshot_invalid")
        contract = self._producer.produce(snapshot.context, candidate, snapshot=snapshot,
                                          observation=observation, scope=scope)
        if contract is None:
            return ReviewObservation(ReviewVerdict.UNKNOWN, "semantic_contract_unavailable")
        return await self._output_review.review_contract(snapshot.context, candidate, contract)
