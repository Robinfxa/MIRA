"""Finite native character-tool plans, independent of JEV observations.

Luna interprets intent. This application code binds exact current input, finite
story prerequisites, authored readiness and eventual presentation receipts.
"""
from dataclasses import replace
import hashlib

from mira.application.actor_story import PreparedCharacterUpdate, RAINCOAT_CONTROL
from mira.application.actor_chapter import prepare_chapter_state
from mira.application.compiler import compile_range
from mira.application.contracts import CandidateRange, EffectProposal
from mira.application.generation_tool_execution import control_effect, control_ready, control_capability, NativeDialogueIntent
from mira.domain.errors import DomainError
from mira.domain.models import EffectKind
from mira.domain.story import (NativeStoryEvidence, StoryTurn, StoryProposal, PROPOSAL_SIGNAL_BY_TRANSITION,
    ReceiptRequirement, ReceiptComponent, ResultCode, bind_compiled_effect, reduce_story)
from mira.domain.xiahe_chapter import NativeChapterAct, CHAPTER_SCENES, CHAPTER_CAPABILITIES, stage_chapter, bind_chapter_effect


def _effects(proposals,context,activity):
    return compile_range(CandidateRange(tuple(proposals),'application-native-character-tool'),
        epoch=context.output_epoch,activity=activity) if proposals else ()


def prepare_native_character(runtime,context,call,arguments,input_id,activity, *, dialogue_effect=None):
    runtime.ensure_definition(context)
    if call.name!='advance_story':
        proposal=control_effect(call.name,arguments)
        if proposal is None or not control_ready(proposal,runtime.readiness):
            raise DomainError('tool_held','readiness')
        effects=_effects((proposal,),context,activity)
        grants=tuple((e,runtime.readiness.get(control_capability(e)).asset_revision) for e in effects
            if e.kind is EffectKind.SCENE or e.value.startswith(('outfit_','accessory_','emotion_')))
        return PreparedCharacterUpdate(runtime.runtime.story,runtime.runtime.affect,effects,grants),None
    return _prepare_native_story(runtime,context,arguments,input_id,activity,dialogue_effect=dialogue_effect)


def _prepare_native_story(runtime,context,arguments,input_id,activity, *, dialogue_effect=None):
    transition=arguments['transition_id']
    act=arguments['input_act']
    exact=bool(arguments['evidence_text'] and arguments['evidence_text']==context.user_text)
    if transition=='x.ask_role':
        if not exact or act!='ask_role_confirmation':
            raise DomainError('tool_held','current_role_question_required')
        if dialogue_effect is None:return _dialogue_intent(arguments),None
        return PreparedCharacterUpdate(runtime.runtime.story,runtime.runtime.affect,(dialogue_effect,),()),'needs_confirmation'
    if transition.startswith('t.'):
        return _prepare_rain(runtime,context,arguments,input_id,activity,exact,dialogue_effect=dialogue_effect),None
    expected={'x.recognize':'claim_role','x.exit':'exit_role','x.gift_accept':'accept_gift',
              'x.gift_decline':'decline_gift'}.get(transition)
    if transition == 'x.gift_accept' and act == 'reopen_accept_gift':
        expected = 'reopen_accept_gift'
    native_act=None
    if expected is not None:
        if transition=='x.recognize' and act=='confirm_role':
            question=runtime._native_role_question
            reference=arguments['reference_effect_id']
            if (question is None or reference!=question[0]
                    or not runtime.native_role_question_current(context.output_epoch,context.presented_effects,input_id)):
                raise DomainError('tool_held','needs_confirmation')
            act='claim_role'
        if not exact or act!=expected:
            raise DomainError('tool_held','current_input_act_required')
        native_act=NativeChapterAct(expected,context.user_text,input_id,context.output_epoch,
            arguments['reference_effect_id'] or None if expected=='reopen_accept_gift' else None)
    elif act=='reopen_gift':
        if not exact:raise DomainError('tool_held','current_input_act_required')
        native_act=NativeChapterAct(act,context.user_text,input_id,context.output_epoch)
    elif act!='none':
        raise DomainError('tool_held','unexpected_input_act')
    scene=CHAPTER_SCENES.get(transition)
    proposals=[]
    if scene:proposals.append(EffectProposal(EffectKind.SCENE,scene))
    if transition in {'x.story','x.promise'} and dialogue_effect is None:
        current=runtime.runtime.story
        # Validate the finite step without compiling, issuing or committing a cue.
        scope=hashlib.sha256(('mira.story.scope.v1:'+current.scope_id).encode()).hexdigest()
        checked=stage_chapter(current.chapter,transition=transition,input_id=input_id,
            epoch=context.output_epoch,user_text=context.user_text,
            draft_cue='awaiting dialogue',ready=True,scope_binding=scope)
        if checked==current.chapter:raise DomainError('tool_held','chapter_precondition')
        return _dialogue_intent(arguments),None
    effects=((dialogue_effect,) if transition in {'x.story','x.promise'} else
        _effects(proposals,context,activity))
    proposal=StoryProposal(transition,PROPOSAL_SIGNAL_BY_TRANSITION[transition],input_id,context.output_epoch,
        arguments['offer_id'] or None,(CHAPTER_CAPABILITIES[scene],) if scene else (),
        dialogue_effect.value if dialogue_effect is not None else None)
    current=runtime.runtime.story
    story,admitted=prepare_chapter_state(current,proposal,effects,user_text=context.user_text,
        input_id=input_id,epoch=context.output_epoch,readiness=runtime.readiness,
        reviewed=False,relevant=False,willingness='UNKNOWN',refusal=False,native_act=native_act)
    if story.chapter==current.chapter:
        raise DomainError('tool_held','chapter_precondition')
    return PreparedCharacterUpdate(story,runtime.runtime.affect,admitted,()),None


def _prepare_rain(runtime,context,args,input_id,activity,exact, *, dialogue_effect=None):
    transition=args['transition_id'];act=args['input_act'];current=runtime.runtime.story
    if transition in {'t.yes','t.window','t.no'}:
        if not exact or act!=('decline_rain' if transition=='t.no' else 'accept_rain'):
            raise DomainError('tool_held','current_offer_choice_required')
        if not args['offer_id'] or args['offer_id']!=current.active_offer_id:
            raise DomainError('tool_held','current_offer_required')
        intent='decline' if transition=='t.no' else 'accept'
    else:
        if act not in {'none','reopen_rain'} or act=='reopen_rain' and not exact:
            raise DomainError('tool_held','current_reopen_required')
        intent='reopen' if act=='reopen_rain' else 'offer'
    cap=('cafe.scene.rain_window' if args['target']=='rain_window' else 'mira.outfit.amber_raincoat')
    if transition=='t.offer':
        if args['target']=='none':raise DomainError('tool_held','offer_cue_required')
        proposals=()
        target=(cap,) if args['target']=='rain_window' else ()
    elif transition=='t.window':
        proposals=(EffectProposal(EffectKind.SCENE,'rain_window'),);target=('cafe.scene.rain_window',)
    elif transition=='t.yes':
        proposals=(EffectProposal(EffectKind.POSE,RAINCOAT_CONTROL),);target=('mira.outfit.amber_raincoat',)
    else:proposals=();target=()
    proposal=(StoryProposal(transition,PROPOSAL_SIGNAL_BY_TRANSITION[transition],input_id,context.output_epoch,
        args['offer_id'] or None,target,
        (dialogue_effect.value if dialogue_effect is not None else 'awaiting dialogue')
            if transition=='t.offer' else None) if transition!='t.no' else None)
    evidence=NativeStoryEvidence(input_id,context.output_epoch,args['offer_id'] or None,intent)
    reduction=reduce_story(current,StoryTurn(input_id,context.output_epoch,proposal,None,
        runtime.readiness,True,reopen_offer=intent=='reopen',native_evidence=evidence),runtime.runtime.definition)
    if reduction.effect_plan is None:
        if transition=='t.no' and reduction.code is ResultCode.CHOICE_NO:
            return PreparedCharacterUpdate(reduction.state,runtime.runtime.affect,(),())
        raise DomainError('tool_held','story_precondition')
    if transition=='t.offer' and dialogue_effect is None:return _dialogue_intent(args)
    effects=((dialogue_effect,) if transition=='t.offer' else _effects(proposals,context,activity))
    effect=effects[0];plan=reduction.effect_plan
    component=(ReceiptComponent.SUBTITLE if transition=='t.offer' else
        ReceiptComponent.SCENE if transition=='t.window' else ReceiptComponent.WARDROBE)
    cue=hashlib.sha256(effect.value.encode()).hexdigest() if transition=='t.offer' else None
    requirement=ReceiptRequirement(component,effect.id,cue or effect.digest,cue)
    story,_=bind_compiled_effect(reduction.state,plan,compiled_effect_id=effect.id,
        compiled_effect_digest=effect.digest,requirement=requirement,actual_cue_digest=cue)
    grants=((effect,plan.capability_revision),) if transition in {'t.yes','t.window'} else ()
    return PreparedCharacterUpdate(story,runtime.runtime.affect,effects,grants)


def _dialogue_intent(arguments):
    return NativeDialogueIntent(*(arguments[key] for key in
        ('transition_id','input_act','offer_id','target')))


def bind_native_dialogue(runtime,context,intent,effects,input_id,activity):
    """Bind only a separately authored complete dialogue cue, never tool prose."""
    if type(intent) is not NativeDialogueIntent or len(effects)!=1:
        return None
    effect=effects[0]
    if (effect.kind is not EffectKind.SUBTITLE or effect.caption_chunk is not None
            or (effect.output_epoch,effect.activity_seq)!=(context.output_epoch,activity)
            or not 0<len(effect.value)<=500):return None
    if intent.transition_id == 'x.recognize':
        return _bind_recognition_offer(runtime,context,intent,effect,input_id,activity)
    # These are structural values previously validated for this exact turn.
    # The control brief is deliberately absent, and cannot be promoted to an effect.
    arguments={'transition_id':intent.transition_id,'input_act':intent.input_act,
        'offer_id':intent.offer_id,'target':intent.target,'evidence_text':context.user_text,
        'reference_effect_id':''}
    runtime.ensure_definition(context)
    update,_reason=_prepare_native_story(runtime,context,arguments,input_id,activity,dialogue_effect=effect)
    return update


def recognition_offer_intent(update, arguments):
    """Retain only the issued recognition identity, never a tool/control cue."""
    if (update is None or arguments.get('transition_id') != 'x.recognize'
            or not arguments.get('offer_id')):
        return None
    pending = update.story.chapter.pending
    if (pending is None or pending.transition != 'x.recognize'
            or update.story.chapter.suspended): return None
    return NativeDialogueIntent('x.recognize', arguments['input_act'],
        arguments['offer_id'], 'none', pending.effect_id)


def _bind_recognition_offer(runtime, context, intent, effect, input_id, activity):
    runtime.ensure_definition(context)
    recognition = next((e for e in context.presented_effects
        if e.id == intent.recognition_effect_id and e.kind is EffectKind.SCENE
        and e.value == CHAPTER_SCENES['x.recognize']
        and (e.output_epoch,e.activity_seq) == (context.output_epoch,activity)), None)
    if recognition is None: return None
    current = runtime.runtime.story
    scope = hashlib.sha256(('mira.story.scope.v1:'+current.scope_id).encode()).hexdigest()
    chapter = stage_chapter(current.chapter,transition='x.gift_offer',input_id=input_id,
        epoch=context.output_epoch,user_text=context.user_text,offer_id=intent.offer_id,
        draft_cue=effect.value,ready=True,scope_binding=scope,
        recognition_effect_id=recognition.id)
    if chapter == current.chapter: return None
    chapter = bind_chapter_effect(chapter,effect_id=effect.id,digest=effect.digest,
        epoch=context.output_epoch)
    return PreparedCharacterUpdate(replace(current,chapter=chapter,revision=current.revision+1),
        runtime.runtime.affect,(effect,),())
