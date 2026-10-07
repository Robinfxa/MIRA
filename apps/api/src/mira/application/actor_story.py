"""Small single-Actor bridge: reviewed suggestions, compiled grants, real receipts.

No filesystem, provider, HTTP, automatic recording or presentation authority.
The Actor holds its transition lock when mutating this pure coordinator.
"""
from __future__ import annotations

from dataclasses import dataclass,replace
import hashlib
import json
from collections.abc import Awaitable, Callable

from mira.application.contracts import (CandidateRange,EffectProposal,GenerationContext,
    CharacterSemanticEvidence,CharacterSemanticValue as V,ReviewObservation,ReviewVerdict)
from mira.application.decision_contracts import evidence_digest
from mira.application.character_controls import CHARACTER_CAPABILITIES
from mira.application.story import StoryRuntime, RuntimeSnapshot
from mira.application.actor_chapter import (chapter_ready, local_role_proposal, prepare_chapter_state, acknowledge_chapter_effect)
from mira.domain.xiahe_chapter import (CHAPTER_SCENES, CHAPTER_CAPABILITIES, CHAPTER_REVISION, CHAPTER_TRANSITIONS, ChapterPreviewReference, reuse_visible_preview, validate_input_act)
from mira.domain.models import Effect,EffectKind,Receipt
from mira.domain.errors import DomainError
from mira.domain.story import (awaited_friend_claim_available,AffectState,AffectSignal,CapabilityState,EvidenceLabel,EpisodeCandidate,
    JevEvidence,PresentationReceipt,ReadinessCatalog,ReceiptComponent,ReceiptKind,
    ReceiptRequirement,ResultCode,Relevance,StoryState,StoryTurn,Stop,Will,
    begin_story_input,fence_story_reply,bind_compiled_effect,parse_story_proposal,parse_affect_proposal,
    affect_turn_from_jev,reduce_affect,reduce_story)

RAINCOAT_CONTROL='outfit_amber_raincoat'


@dataclass(frozen=True,slots=True)
class PreparedCharacterUpdate:
    story: StoryState
    affect: AffectState
    admitted_effects: tuple[Effect, ...]
    control_grants: tuple[tuple[Effect, str], ...]


class SessionCharacterRuntime:
    def __init__(self,runtime:StoryRuntime,readiness:ReadinessCatalog,
                 checkpoint: Callable[[RuntimeSnapshot], Awaitable[None]] | None = None):
        if type(runtime) is not StoryRuntime or type(readiness) is not ReadinessCatalog:
            raise ValueError('character_runtime_invalid')
        self.runtime=runtime
        self.readiness=readiness
        self._checkpoint=checkpoint
        self._definition_digest=evidence_digest(runtime.definition)
        # Receipt reconciliation metadata, never presentation authority. Kept
        # only for this Actor's bounded issued-effect budget, not checkpointed.
        self._control_grants: dict[str, tuple[Effect, str]] = {}
        self._last_presentation_seq: dict[str, int] = {}
        self._chapter_grants = {}
        self._native_role_question = None
        self._native_role_question_reply_frontier = None
        self._native_role_confirmation_input = None

    def retain_effect_metadata(self, effect_ids: set[str]) -> None:
        """Expired grants have no remaining receipt authority in the Actor ledger."""
        self._control_grants = {key: value for key, value in self._control_grants.items() if key in effect_ids}
        self._chapter_grants = {key: value for key, value in self._chapter_grants.items() if key in effect_ids}

    def begin_input(self,input_id:str,epoch:int):
        updated=begin_story_input(self.runtime.story,input_id,epoch,self.runtime.definition)
        question=self._native_role_question
        bound=self._native_role_confirmation_input
        if question is not None:
            if bound is not None and bound[0]==question[0]:
                current=(input_id,epoch)==bound[1:]
            else:
                current=epoch==self._role_question_frontier()+1
            if current:
                self._native_role_confirmation_input=(question[0],input_id,epoch)
            else:
                self._native_role_question=None
                self._native_role_question_reply_frontier=None
                self._native_role_confirmation_input=None
        else:
            self._native_role_question_reply_frontier=None
            self._native_role_confirmation_input=None
        self.runtime.story=updated
        return self.runtime.project().projection

    def _role_question_frontier(self):
        question=self._native_role_question
        if question is None: return None
        control=self._native_role_question_reply_frontier
        return control[1] if control is not None and control[0]==question[0] else question[1]

    def _role_question_presented(self,presented_effects):
        question=self._native_role_question
        latest=next((e for e in reversed(presented_effects) if e.kind is EffectKind.SUBTITLE),None)
        return bool(question is not None and latest is not None
            and (latest.id,latest.output_epoch)==question[:2])

    def native_role_question_current(self,epoch,presented_effects,input_id):
        """Only the next actual input across an exact chain of reply controls.

        The question's source identity/epoch is never rewritten. An intervening
        user input consumes this opportunity even if its generation is stopped.
        """
        frontier=self._role_question_frontier()
        question=self._native_role_question
        return bool(frontier is not None and epoch==frontier+1
            and self._native_role_confirmation_input==(question[0],input_id,epoch)
            and self.runtime.story.epoch==epoch and self._role_question_presented(presented_effects))

    def reply_fence(self,epoch:int,presented_effects):
        current=self.runtime.story
        updated=fence_story_reply(current,epoch,self.runtime.definition)
        if updated is current: return
        question=self._native_role_question
        bound=self._native_role_confirmation_input
        if (question is not None and (bound is None or bound[0]!=question[0])
                and current.epoch==self._role_question_frontier()
                and self._role_question_presented(presented_effects)):
            self._native_role_question_reply_frontier=(question[0],epoch)
        else:
            self._native_role_question=None
            self._native_role_question_reply_frontier=None
            self._native_role_confirmation_input=None
        self.runtime.story=updated

    def ensure_definition(self,context:GenerationContext):
        projection=context.character_story
        current=self.runtime.project().projection
        if (projection is None or evidence_digest(self.runtime.definition)!=self._definition_digest
                or projection.scope_binding_hash!=current.scope_binding_hash
                or projection.graph_hash!=current.graph_hash
                or projection.canon_revision!=current.canon_revision
                or context.character_assets!=self.readiness
                or context.output_epoch!=self.runtime.story.epoch):
            raise DomainError('review_uncertain','Character context changed; keep this story step pending.')
        # The captured turn-start projection stays identical for generation/review.
        # Causally acknowledged local receipts may advance current state in this turn;
        # they remain separate actual presentation facts, not rewritten old context.

    def _proposal(self,candidate:CandidateRange,input_id:str,epoch:int):
        if candidate.story_proposal_json is None:return None
        try:return parse_story_proposal(json.loads(candidate.story_proposal_json),input_id=input_id,epoch=epoch)
        except (ValueError,TypeError,KeyError):
            raise DomainError('invalid_response','Invalid character suggestion.') from None

    def prepare_candidate(self,context:GenerationContext,candidate:CandidateRange,input_id:str):
        self.ensure_definition(context)
        proposal=self._proposal(candidate,input_id,context.output_epoch)
        if proposal is not None and proposal.transition_id in CHAPTER_SCENES:
            value = CHAPTER_SCENES[proposal.transition_id]
            if not chapter_ready(self.readiness, value):
                fallback = ('这张照片暂时没能递出来，你可以稍后再试，我们也可以继续聊。'
                    if proposal.transition_id == 'x.gift_accept' else
                    '这一段暂时没能呈现，我们可以先继续聊。')
                candidate = replace(candidate, effects=tuple(
                    replace(effect,value=fallback) if effect.kind in {EffectKind.SUBTITLE,EffectKind.SPEECH}
                    else effect for effect in candidate.effects))
            if chapter_ready(self.readiness, value) and not any(
                    effect.kind is EffectKind.SCENE and effect.value == value for effect in candidate.effects):
                candidate = replace(candidate, effects=candidate.effects + (EffectProposal(EffectKind.SCENE, value),))
        if proposal is not None and proposal.transition_id in {'x.story', 'x.promise'}:
            if not any(effect.kind is EffectKind.SUBTITLE and effect.value == proposal.draft_cue for effect in candidate.effects):
                raise DomainError('invalid_response','Story beat does not bind to an exact subtitle cue.')
        # A bare chapter scene never acquires authority from its spelling.
        candidate = replace(candidate, effects=tuple(effect for effect in candidate.effects
            if not (effect.kind is EffectKind.SCENE and effect.value in CHAPTER_CAPABILITIES)
            or (proposal is not None and CHAPTER_SCENES.get(proposal.transition_id) == effect.value)))
        wardrobe=tuple(effect for effect in candidate.effects if effect.kind is EffectKind.POSE
                       and effect.value.startswith('outfit_'))
        if proposal is not None and proposal.transition_id=='t.yes':
            record=self.readiness.get('mira.outfit.amber_raincoat')
            if record is None or record.state is not CapabilityState.READY:
                # Still review the text/proposal and let the reducer close an
                # explicitly unavailable invitation. Never compile its outfit.
                candidate=replace(candidate,effects=tuple(effect for effect in candidate.effects
                    if not (effect.kind is EffectKind.POSE and effect.value==RAINCOAT_CONTROL)))
            elif not any(effect.value==RAINCOAT_CONTROL for effect in wardrobe):
                candidate=replace(candidate,effects=candidate.effects+(EffectProposal(EffectKind.POSE,RAINCOAT_CONTROL),))
        if proposal is not None and proposal.transition_id=='t.offer':
            if not proposal.draft_cue or not any(effect.kind is EffectKind.SUBTITLE
                    and effect.value==proposal.draft_cue for effect in candidate.effects):
                raise DomainError('invalid_response','Invitation text does not bind to a subtitle.')
        # A newly named pose is not evidence that either the active renderer or
        # its registered local assets can show it. Remove unsupported optional
        # controls before independent content review; never emit a false receipt.
        candidate=replace(candidate,effects=tuple(effect for effect in candidate.effects
            if self._available_for_current_renderer(effect)))
        if not candidate.effects:
            raise DomainError('review_uncertain','No available character effect remains.')
        return candidate

    def _available_for_current_renderer(self, effect) -> bool:
        if effect.kind is EffectKind.SCENE and effect.value in CHAPTER_CAPABILITIES:
            return chapter_ready(self.readiness, effect.value)
        if self._is_character_control(effect):
            return self.readiness.state_for(CHARACTER_CAPABILITIES.get(effect.value,'')) is CapabilityState.READY
        # A selected renderer may explicitly decline an older optional pose too.
        # Preserve text for full review rather than issuing a grant it cannot draw.
        # Older renderers with no catalogue retain their existing pose contract.
        if effect.kind is EffectKind.SCENE and effect.value == "rain_window":
            return self.readiness.state_for("cafe.scene.rain_window") is CapabilityState.READY
        if effect.kind is EffectKind.POSE:
            capability = ('mira.face.' + effect.value.removeprefix('face_')
                          if effect.value.startswith('face_') else 'mira.pose.' + effect.value)
            record = self.readiness.get(capability)
            if record is not None:
                return record.state is CapabilityState.READY
        return True

    def prepare_accept(self,context:GenerationContext,candidate:CandidateRange,observation:ReviewObservation,
                       effects:tuple[Effect,...],input_id:str, *,
                       hold_optional_failures: bool = False)->PreparedCharacterUpdate:
        self.ensure_definition(context)
        if observation.verdict is not ReviewVerdict.ALLOW:
            raise DomainError('review_uncertain', 'Complete output review is required.')
        if (len(effects) != len(candidate.effects)
                or any((effect.kind, effect.value, effect.output_epoch) !=
                       (proposed.kind, proposed.value, context.output_epoch)
                       for effect, proposed in zip(effects, candidate.effects))):
            raise DomainError('invalid_response', 'Compiled effects differ from reviewed effects.')
        evidence=observation.character_evidence
        if (type(evidence) is not CharacterSemanticEvidence
                or evidence.context_digest!=evidence_digest(context)
                or evidence.candidate_digest!=evidence_digest(candidate)):
            evidence=None
        proposal=self._proposal(candidate,input_id,context.output_epoch)
        if proposal is not None and proposal.transition_id.startswith('x.'):
            return self._prepare_chapter_accept(context,candidate,effects,input_id,proposal,
                reviewed=True,evidence=evidence)
        if proposal is not None and proposal.transition_id!='t.chat' and evidence is None:
            if hold_optional_failures:
                return PreparedCharacterUpdate(self.runtime.story,self.runtime.affect,
                    tuple(effect for effect in effects if effect.kind is EffectKind.SUBTITLE),())
            raise DomainError('review_uncertain','The story suggestion is uncertain; keep the current scene.')
        will=Will.UNKNOWN
        if evidence is not None:
            if evidence.refusal is V.YES:will=Will.NO
            elif evidence.willingness is V.YES and evidence.refusal is V.NO:will=Will.YES
        relevance=(Relevance.RELEVANT if evidence and evidence.relevance is V.YES else
                   Relevance.IRRELEVANT if evidence and evidence.relevance is V.NO else Relevance.UNKNOWN)
        jev=JevEvidence(input_id,context.output_epoch,self.runtime.story.active_offer_id,will,relevance,
                        refusal=bool(evidence and evidence.refusal is V.YES))
        reduction=reduce_story(self.runtime.story,StoryTurn(input_id,context.output_epoch,proposal,jev,
            self.readiness,True,reopen_offer=bool(proposal and proposal.reopen_offer
                and validate_input_act(proposal.input_act,context.user_text,'reopen_rain'))),self.runtime.definition)
        if proposal is not None and proposal.transition_id!='t.chat' and reduction.effect_plan is None:
            if hold_optional_failures:
                return PreparedCharacterUpdate(reduction.state,self.runtime.affect,
                    tuple(effect for effect in effects if effect.kind is EffectKind.SUBTITLE),())
            self.runtime.story=reduction.state
            raise DomainError('review_uncertain','The story suggestion is uncertain; keep the current scene.')
        story=reduction.state
        plan=reduction.effect_plan
        if plan is not None:
            if plan.transition_id=='t.offer':
                effect=next((effect for effect in effects if effect.kind is EffectKind.SUBTITLE
                             and effect.value==proposal.draft_cue),None)
                if effect is None:raise DomainError('invalid_response','No compiled invitation cue.')
                cue=hashlib.sha256(effect.value.encode()).hexdigest()
                requirement=ReceiptRequirement(ReceiptComponent.SUBTITLE,effect.id,cue,cue)
            elif plan.transition_id=='t.window':
                effect=next((effect for effect in effects if effect.kind is EffectKind.SCENE
                             and effect.value=='rain_window'),None)
                if effect is None:raise DomainError('invalid_response','No compiled scene effect.')
                cue=None
                requirement=ReceiptRequirement(ReceiptComponent.SCENE,effect.id,effect.digest)
            else:
                effect=next((effect for effect in effects if effect.kind is EffectKind.POSE
                             and effect.value==RAINCOAT_CONTROL),None)
                if effect is None:raise DomainError('invalid_response','No compiled wardrobe effect.')
                cue=None
                requirement=ReceiptRequirement(ReceiptComponent.WARDROBE,effect.id,effect.digest)
            story,_=bind_compiled_effect(story,plan,compiled_effect_id=effect.id,
                compiled_effect_digest=effect.digest,requirement=requirement,actual_cue_digest=cue)
        affect=self.runtime.affect
        if input_id not in affect.seen_input_ids:
            affect_proposal=None;signal=AffectSignal.UNCERTAIN
            if candidate.affect_proposal_json is not None:
                try:
                    ids=tuple(turn.input_id for turn in affect.recent_turns if turn.reliable)[-3:]+(input_id,)
                    affect_proposal=parse_affect_proposal(json.loads(candidate.affect_proposal_json),
                        trusted_evidence_ids=ids,approved_canon_ids=context.character_story.canon_entry_ids)
                    signal=affect_proposal.signal
                except (ValueError,TypeError,KeyError):
                    raise DomainError('invalid_response','Invalid affect suggestion.') from None
            turn=affect_turn_from_jev(input_id,signal,
                sufficient_evidence=bool(evidence and evidence.affect_supported is V.YES),
                specific_notice=bool(evidence and evidence.specific_notice is V.YES))
            affect=reduce_affect(affect,turn,affect_proposal,self.runtime.definition)
        # Only remove optional POSEs from the exact reviewed/compiled range.
        # Speech/subtitle IDs, digests and cue linkage remain untouched.
        effects = tuple(effect for effect in effects if not (effect.kind is EffectKind.SCENE
            and effect.value == 'rain_window' and (plan is None or plan.transition_id != 't.window')))
        admitted = tuple(effect for effect in effects
            if not self._is_character_control(effect)
            or (self.readiness.state_for(CHARACTER_CAPABILITIES.get(effect.value, '')) is CapabilityState.READY
                and (not effect.value.startswith('emotion_')
                     or effect.value == 'emotion_' + affect.emotion.value)))
        if not admitted:
            if hold_optional_failures:
                return PreparedCharacterUpdate(story,affect,(),())
            # The allowed evidence still counts once toward hysteresis, but no
            # grant (including an invented normal-emotion grant) is produced.
            self.runtime.story, self.runtime.affect = story, affect
            raise DomainError('review_uncertain', 'No admitted character effect remains.')
        grants = tuple((effect, self.readiness.get(CHARACTER_CAPABILITIES[effect.value]).asset_revision)
                       for effect in admitted if effect.kind is EffectKind.POSE
                       and effect.value in CHARACTER_CAPABILITIES)
        if plan is not None and plan.transition_id == 't.window':
            grants += tuple((effect, plan.capability_revision) for effect in admitted
                            if effect.kind is EffectKind.SCENE and effect.value == 'rain_window')
        return PreparedCharacterUpdate(story, affect, admitted, grants)

    def reconcile_visible_preview(self,effect,receipt,input_id,epoch,*,visible):
        """Caller supplies the current visible_fixed_receipt under the Actor lock.

        Preserve its old epoch/sequence. No new rendering/receipt/episode exists.
        """
        story=self.runtime.story
        if (visible is not True or effect.kind is not EffectKind.MEDIA or effect.value!='trip_photo'
                or type(input_id) is not str or not input_id or len(input_id)>128
                or story.input_fence_id!=input_id or story.epoch!=epoch
                or (receipt.effect_id,receipt.digest,receipt.output_epoch,receipt.activity_seq)!=
                    (effect.id,effect.digest,effect.output_epoch,effect.activity_seq)):
            return False
        reference=ChapterPreviewReference('reused_visible',
            'visual.'+effect.id+'.'+str(receipt.presentation_seq),effect.id,effect.digest,
            receipt.output_epoch,receipt.activity_seq,receipt.presentation_seq)
        chapter=reuse_visible_preview(story.chapter,reference,input_id=input_id,epoch=epoch)
        if chapter==story.chapter:return False
        self.runtime.story=replace(story,chapter=chapter,revision=story.revision+1)
        return True

    def choice_candidate(self,choice,offer_id,offer_effect_id,offer_effect_digest,*,input_id,epoch):
        """Resolve an explicit UI choice locally before a new Actor input begins.

        Caller holds the Actor lock and binds the returned reliable text/candidate
        to one new input/epoch. No provider interpretation or grant occurs here.
        """
        chapter=self.runtime.story.chapter
        if (type(input_id) is not str or not input_id or len(input_id)>128
                or input_id in self.runtime.story.last_input_ids
                or type(epoch) is not int or epoch<=self.runtime.story.epoch
                or choice not in {'accept','decline'} or not chapter.role_active or chapter.suspended
                or chapter.stage.value!='gift_offered'
                or (offer_id,offer_effect_id,offer_effect_digest)!=(chapter.active_gift_offer_id,
                    chapter.gift_offer_effect_id,chapter.gift_offer_effect_digest)):
            raise DomainError('stale_chapter_choice','This gift invitation is no longer current.')
        user_text='我收下这张照片' if choice=='accept' else '暂时不收照片'
        cue='我现在把这张灯塔照片递给你。' if choice=='accept' else '好，那我先留着。我们接着聊。'
        transition='x.gift_accept' if choice=='accept' else 'x.gift_decline'
        signal='accept_photo_gift' if choice=='accept' else 'decline_photo_gift'
        proposal={'transition_id':transition,'signal':signal,'offer_id':offer_id,
            'target_capabilities':['chapter.xiahe.photo_handover'] if choice=='accept' else [],
            'input_act':{'kind':'accept_gift' if choice=='accept' else 'decline_gift',
                'evidence_text':user_text,'role_name':'夏禾'}}
        candidate=CandidateRange((EffectProposal(EffectKind.SUBTITLE,cue),),
            'local-current-chapter-choice',story_proposal_json=json.dumps(proposal,ensure_ascii=False))
        return candidate

    def local_role_candidate(self,context,candidate,input_id):
        """Director may use this after existing content checks, without a JEV role vote."""
        self.ensure_definition(context)
        return local_role_proposal(self._proposal(candidate,input_id,context.output_epoch),context.user_text,
            awaited_friend=awaited_friend_claim_available(self.runtime.story.chapter,self.runtime.definition.canon.entries))

    def local_chapter_candidate(self,context,candidate,input_id):
        self.ensure_definition(context)
        proposal=self._proposal(candidate,input_id,context.output_epoch)
        return bool(proposal and proposal.transition_id in CHAPTER_TRANSITIONS)

    def prepare_local_chapter_accept(self,context,candidate,effects,input_id):
        """Validated role control only; does not authorize unrelated optional effects."""
        self.ensure_definition(context)
        proposal=self._proposal(candidate,input_id,context.output_epoch)
        if proposal is None or proposal.transition_id not in CHAPTER_TRANSITIONS:
            raise DomainError('review_uncertain','A finite current chapter proposal is required.')
        if (len(effects)!=len(candidate.effects) or any(
                (e.kind,e.value,e.output_epoch)!=(p.kind,p.value,context.output_epoch)
                for e,p in zip(effects,candidate.effects))):
            raise DomainError('invalid_response','Compiled chapter effects differ from the candidate.')
        return self._prepare_chapter_accept(context,candidate,effects,input_id,proposal,
            reviewed=False,evidence=None)

    prepare_local_role_accept = prepare_local_chapter_accept

    def _prepare_chapter_accept(self,context,candidate,effects,input_id,proposal,*,reviewed,evidence):
        story,admitted=prepare_chapter_state(self.runtime.story,proposal,effects,
            user_text=context.user_text,input_id=input_id,epoch=context.output_epoch,
            readiness=self.readiness,reviewed=reviewed,
            relevant=bool(evidence and evidence.relevance is V.YES),
            willingness='YES' if evidence and evidence.willingness is V.YES else 'UNKNOWN',
            refusal=bool(evidence and evidence.refusal is V.YES),
            awaited_friend=awaited_friend_claim_available(self.runtime.story.chapter,self.runtime.definition.canon.entries))
        return PreparedCharacterUpdate(story,self.runtime.affect,admitted,())

    @staticmethod
    def _is_character_control(effect):
        return effect.kind is EffectKind.POSE and effect.value.startswith(('outfit_', 'accessory_', 'emotion_'))

    def commit(self,update:PreparedCharacterUpdate):
        self.runtime.story,self.runtime.affect=update.story,update.affect
        pending=update.story.chapter.pending
        if pending is not None and pending.effect_id is not None:
            self._chapter_grants[pending.effect_id]=pending
        self._control_grants.update((effect.id, (effect, revision))
                                    for effect, revision in update.control_grants)

    def stop(self,epoch:int):
        self._native_role_question=None
        self._native_role_question_reply_frontier=None
        self._native_role_confirmation_input=None
        self.runtime.apply_story(Stop(epoch))

    def checkpoint_snapshot(self):
        return self.runtime.snapshot() if self._checkpoint is not None else None

    async def persist(self,snapshot:RuntimeSnapshot | None):
        if snapshot is not None and self._checkpoint is not None:
            try:
                await self._checkpoint(snapshot)
            except Exception:
                # An already-started write may have succeeded. The same receipt
                # can reconcile, but no new provider turn is automatically tried.
                raise DomainError('story_checkpoint_pending',
                    'Character history save is pending or unavailable; retry the same receipt.') from None

    def acknowledge(self,receipt:Receipt,effect:Effect):
        """Called only after the Actor validates issued identity and Stop cutoff.

        Late pre-fence facts can reconcile history; they cannot advance a graph
        or recreate a grant. A new browser has no old compiled-control ledger.
        """
        if ((receipt.effect_id, receipt.digest, receipt.output_epoch, receipt.activity_seq) !=
                (effect.id, effect.digest, effect.output_epoch, effect.activity_seq)):
            return
        chapter,handled=acknowledge_chapter_effect(self.runtime.story,receipt,effect,
            issued_chapter=self._chapter_grants.get(effect.id))
        if handled:
            self.runtime.story=chapter
            self._chapter_grants.pop(effect.id,None)
            return
        # Chapter scene beats never become environment or appearance facts.
        if effect.kind is EffectKind.SCENE and effect.value in CHAPTER_CAPABILITIES:
            return
        pending=self.runtime.story.pending
        if pending is not None and pending.compiled_effect_id==effect.id:
            requirement=pending.receipt_requirement
            if requirement is None:return
            current=self.runtime.story
            value=PresentationReceipt('visual.'+effect.id+'.'+str(receipt.presentation_seq),current.scope_id,
                current.story_id,current.graph_revision,current.canon_revision,receipt.output_epoch,
                pending.grant_id,pending.transition_id,pending.receipt_kind,EvidenceLabel.CLIENT_REPORT,'complete',
                offer_id=pending.offer_id,before_outfit=current.current_outfit,
                after_outfit='amber_raincoat' if pending.receipt_kind is ReceiptKind.WARDROBE_COMPLETED else None,
                capability_revision=pending.capability_revision,
                compiled_effect_id=effect.id,compiled_effect_digest=effect.digest,
                component=requirement.component,component_id=requirement.component_id,
                component_digest=requirement.component_digest,cue_digest=requirement.cue_digest)
            result=self.runtime.apply_story(value)
            if result.code is ResultCode.RECEIPT_ACCEPTED:
                if effect.kind is EffectKind.SCENE:
                    self._last_presentation_seq['scene'] = receipt.presentation_seq
                if effect.value == RAINCOAT_CONTROL:
                    self._last_presentation_seq['outfit'] = receipt.presentation_seq
                self._control_grants.pop(effect.id, None)
                return
        grant=self._control_grants.get(effect.id)
        if grant is None or grant[0] != effect:
            return
        current=self.runtime.story
        if effect.kind is EffectKind.SCENE:
            # The Actor already validated that this receipt describes an actual
            # pre-fence presentation. Keep that history, but never revive a
            # cancelled graph grant or treat late acknowledgement as new consent.
            receipt_id='visual.'+effect.id+'.'+str(receipt.presentation_seq)
            if receipt_id not in current.receipt_ids:
                episode=EpisodeCandidate(
                    candidate_id='episode.rain_window:'+receipt_id,
                    event_code='cafe_'+effect.value+'_presented', receipt_id=receipt_id,
                    compiled_effect_id=effect.id, compiled_effect_digest=effect.digest,
                    component_id=effect.id, component_digest=effect.digest,
                    evidence=EvidenceLabel.CLIENT_REPORT, story_id=current.story_id,
                    graph_revision=current.graph_revision, canon_revision=current.canon_revision,
                    character_state=(('scene_after',effect.value),('asset_revision',grant[1]),
                                     ('history_scope','fictional_software_presentation'),
                                     ('reconciliation','current_exact_receipt' if effect.output_epoch==current.epoch else 'late_pre_fence_no_graph_advance')))
                self.runtime.story=replace(current,
                    receipt_ids=(current.receipt_ids+(receipt_id,))[-64:],
                    episodes=(current.episodes+(episode,))[-32:],revision=current.revision+1)
            self._control_grants.pop(effect.id,None)
            return
        slot, target=effect.value.split('_',1)
        receipt_id='visual.'+effect.id+'.'+str(receipt.presentation_seq)
        if receipt_id in current.receipt_ids:
            self._control_grants.pop(effect.id,None)
            return
        # Presentation sequence is the validated within-browser ordering, not
        # network arrival order. A late older receipt never overwrites newer
        # acknowledged appearance. All valid facts remain qualified episodes.
        latest=receipt.presentation_seq > self._last_presentation_seq.get(slot,0)
        episode=EpisodeCandidate(
            candidate_id='episode.character_control:'+receipt_id,
            event_code='mira_'+effect.value+'_presented', receipt_id=receipt_id,
            compiled_effect_id=effect.id, compiled_effect_digest=effect.digest,
            component_id=effect.id, component_digest=effect.digest,
            evidence=EvidenceLabel.CLIENT_REPORT, story_id=current.story_id,
            graph_revision=current.graph_revision, canon_revision=current.canon_revision,
            character_state=((slot+'_after',target),
                             ('asset_revision',grant[1]),('history_scope','fictional_software_presentation'),
                             ('presentation_order','latest' if latest else 'earlier_than_acknowledged')))
        changes={}
        if latest:
            changes['last_acknowledged_'+slot]=target
            if slot=='outfit':changes['current_outfit']=target
            if slot=='emotion':
                from mira.domain.story import Affect
                self.runtime.affect=replace(self.runtime.affect,emotion=Affect(target),revision=self.runtime.affect.revision+1)
            self._last_presentation_seq[slot]=receipt.presentation_seq
        self.runtime.story=replace(current, **changes,
            receipt_ids=(current.receipt_ids+(receipt_id,))[-64:],
            episodes=(current.episodes+(episode,))[-32:],revision=current.revision+1)
        self._control_grants.pop(effect.id,None)
