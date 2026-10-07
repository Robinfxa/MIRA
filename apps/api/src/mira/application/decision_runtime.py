"""Application-owned semantic composition; no providers, IO or permit authority."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from mira.application.contracts import (
    CandidateRange, GenerationContext, ReviewObservation, ReviewVerdict, audio_context_progress,
)
from mira.application.diagnostic_errors import (
    classify_reason, is_jev_transport_reason, is_semantic_uncertainty_reason,
    jev_resource_failure_code,
)
from mira.application.decision_contracts import (
    AuthorPolicy, ControlledReferent, DecisionSnapshot, DirectiveFact, InputDecisionObservation,
    InputDecisionStatus, PresentationFact, ReliableUserInput, ResponseContractProducer,
    evidence_digest, valid_snapshot, character_author_policy, speech_permission_allowed,
)
from mira.application.diagnostic_events import DiagnosticCode
from mira.application.ports.decisions import InputDecisionBackend
from mira.application.ports.semantic_review import ResponseContractReviewBackend
from mira.domain.models import EffectKind, SessionState
from mira.domain.story import CapabilityState, valid_story_projection


def _context(state: SessionState, *, memory_packet=None, character_story=None, character_assets=None,
             request_context=None, visual_action_uncertain=False, memory_recall_status=None,
             conversation_recall=None, conversation_recall_status=None) -> GenerationContext:
    return GenerationContext(state.user_inputs[-1], state.user_inputs, state.presented_effects,
                             state.output_epoch, state.active_grants,
                             audio_context_progress(state.audio_progress), memory_packet,
                             character_story, character_assets, request_context=request_context,
                             visual_action_uncertain=visual_action_uncertain, response_mode=state.response_mode,
                             photo_visible=state.photo_visible, photo_visibility_revision=state.photo_visibility_revision,
                             memory_recall_status=memory_recall_status,
                             conversation_recall=conversation_recall,
                             conversation_recall_status=conversation_recall_status,
                             story_images=state.story_image_facts, fixed_photo=state.fixed_photo,
                             retired_user_inputs=state.retired_user_inputs)


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
    include_authored_referents: bool = False

    def snapshot(self, state: SessionState,
                 reliable_inputs: tuple[ReliableUserInput, ...], *,
                 memory_packet=None, character_story=None, character_assets=None,
                 request_context=None, visual_action_uncertain=False, memory_recall_status=None,
             conversation_recall=None, conversation_recall_status=None) -> DecisionSnapshot | None:
        if type(state) is not SessionState or not state.request_id or not state.user_inputs:
            return None
        if character_story is not None and not valid_story_projection(character_story):
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
        presented = iter(state.presented_effects)
        for effect in state.issued_effects:
            if effect.id in presented_ids:
                # Share the exact domain projection; snapshot validation stays strict.
                facts.append(PresentationFact(next(presented), "presented"))
            elif effect.id in latest:
                progress = latest[effect.id]
                status = "partial" if progress.rendered_samples > 0 else "unknown"
                facts.append(PresentationFact(effect, status))
        referents = self.referents
        if (self.include_authored_referents is True
                and character_assets is not None and len(referents) < 16
                and character_assets.state_for('mira.media.trip_photo') is CapabilityState.READY
                and not any(item.referent_id == 'authored.trip_photo' for item in referents)):
            referents += (ControlledReferent('authored.trip_photo',
                'MIRA的内置原创海岸灯塔插画。它可供展示；可用不代表用户已看见，且它不是新拍照片或用户照片。',
                None, 'mira.media.trip_photo'),)
        result = DecisionSnapshot(
            "snapshot-pending", state.revision, state.activity_seq, state.input_epoch,
            len(reliable_inputs), state.request_id,
            _context(state, memory_packet=memory_packet, character_story=character_story,
                     character_assets=character_assets, request_context=request_context,
                     visual_action_uncertain=visual_action_uncertain,
                     memory_recall_status=memory_recall_status,
                             conversation_recall=conversation_recall,
                             conversation_recall_status=conversation_recall_status), reliable_inputs,
            character_author_policy(character_story, self.author_policy, readiness=character_assets), tuple(facts), referents, self.effective_constraints,
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
    return (snapshot_same_branch(state, snapshot)
            and _context(state, memory_packet=snapshot.context.memory_packet,
                         character_story=snapshot.context.character_story,
                         character_assets=snapshot.context.character_assets,
                         request_context=snapshot.context.request_context,
                         visual_action_uncertain=snapshot.context.visual_action_uncertain,
                         memory_recall_status=snapshot.context.memory_recall_status,
                         conversation_recall=snapshot.context.conversation_recall,
                         conversation_recall_status=snapshot.context.conversation_recall_status) == snapshot.context)


class SemanticReviewCoordinator:
    """Two explicit await boundaries let the single state writer check both results."""
    def __init__(self, input_decision: InputDecisionBackend,
                 output_review: ResponseContractReviewBackend, *,
                 conversation_first: bool = False) -> None:
        if type(conversation_first) is not bool:
            raise ValueError('conversation_policy_invalid')
        self.conversation_first = conversation_first
        self._input_decision = input_decision
        self._output_review = output_review
        self._producer = ResponseContractProducer()

    def speech_allowed(self, snapshot, candidate, observation) -> bool:
        """Independent permission evidence; this never approves optional controls."""
        return speech_permission_allowed(snapshot, candidate, observation)

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
        if (type(observation) is InputDecisionObservation
                and observation.status != InputDecisionStatus.OBSERVED
                and is_semantic_uncertainty_reason(observation.reason_code)):
            # Preserve the exact fixed semantic cause. Technical/unavailable input
            # observations still take their dedicated non-soft failure paths below.
            return ReviewObservation(ReviewVerdict.UNKNOWN, observation.reason_code)
        if (type(observation) is InputDecisionObservation
                and observation.status != InputDecisionStatus.OBSERVED
                and classify_reason(observation.reason_code).code == DiagnosticCode.INVALID_RESPONSE):
            return ReviewObservation(ReviewVerdict.UNKNOWN, "semantic_input_invalid_response")
        if (type(observation) is InputDecisionObservation
                and observation.status != InputDecisionStatus.OBSERVED
                and (is_jev_transport_reason(observation.reason_code)
                     or jev_resource_failure_code(observation.reason_code) is not None)):
            return ReviewObservation(ReviewVerdict.UNKNOWN, observation.reason_code)
        contract = self._producer.produce(snapshot.context, candidate, snapshot=snapshot,
                                          observation=observation, scope=scope,
                                          optional_image_only=self.conversation_first)
        if contract is None:
            return ReviewObservation(ReviewVerdict.UNKNOWN, "semantic_contract_unavailable")
        return await self._output_review.review_contract(snapshot.context, candidate, contract)
