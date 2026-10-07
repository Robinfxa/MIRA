"""Closed tool vocabulary and factual result projection; no provider or IO authority."""
import json
import re
from dataclasses import asdict, dataclass

from mira.application.authored_visual_events import event_available
from mira.application.contracts import CandidateRange, EffectProposal
from mira.application.ports.generation_tools import GenerationToolCall, GenerationToolResult, ToolDefinition, TOOL_FIELDS, NATIVE_CHARACTER_TOOLS
from mira.domain.errors import DomainError
from mira.domain.models import EffectKind
from mira.application.character_controls import CHARACTER_CAPABILITIES
from mira.domain.story import CapabilityState
from mira.application.image_readiness import image_tool_readiness
from mira.domain.story_images import parse_generated_photo


TOOL_DESCRIPTIONS = {
    'show_photo': 'Display the existing in-world lighthouse photo, only when that photo is the intended referent. Tool availability never determines what 看看 refers to. Only the application result establishes display.',
    'cancel_story_image': 'Cancel the existing pending fictional image only when requested. Use its exact request_id in story_images; no generation, retry or refund.',
    'generate_story_image': 'Request one authorized empty scenery/still-life image: no people or animals, including fictional ones. For an out-of-scope subject, explain the current limit and offer an empty-scene alternative; never silently substitute or spend usage on it. A request for another photo in a photo-sharing context needs no 生成 keyword; resolve current intent. Only enabled tools with consent/capacity may run; never duplicate pending work. Past, quoted, hypothetical or negated mentions alone are not requests. Closed brief validation and independent pixel qualification remain required. Report only returned generation/display facts.',
    'set_outfit': 'Change MIRA to one ready authored outfit. Resolve short replies against the latest user topic and actually presented reply; an outfit invitation followed by 看看 refers to the outfit, not a photo. Wait for exact display result.',
    'set_accessory': 'Display one authored character accessory; no physical action or user property is changed.',
    'set_emotion': 'Display a bounded fictional character expression. This is no inference or fact about the user. Only a display receipt establishes visible expression.',
    'perform_action': 'Raise the held camera to chest or return it to its resting endpoint. With return_camera the camera remains held; it cannot be placed on a table or free both hands. If already resting, it stays held there. Describe this limited movement truthfully when asked to put it down. Never captures a photograph, opens a camera, or grants camera permission.',
    'set_scene': 'Display a ready authored cafe/rain-window scene. Use advance_story for a current rain invitation choice; ordinary scene control never creates a chapter milestone.',
    'advance_story': 'Request one finite authored story operation. Luna interprets intent; never use keywords as a trigger. Role/choice evidence_text must equal current user input. Contextual 夏he can mean 夏禾. Quoted, hypothetical, negated, reported or unsure names are data; clarify naturally with x.ask_role/ask_role_confirmation only when needed. x.recognize/claim_role is a current fictional self-role claim; confirm_role needs the exact immediately preceding presented question reference_effect_id. No bare yes activates a role. This grants no real identity, authentication or real shared history. For recognition with a coherent photo invitation, include a fresh nonempty offer_id in x.recognize: one bounded compound operation first presents recognition, then only after its exact receipt lets the same continuation recall one supplied shared canon memory and offer the print. Only that genuine continuation subtitle receipt establishes the offer; recognition alone does not. Leave offer_id empty for recognition only, including previously declined/suspended chapters; a fresh offer there needs explicit reopen_gift. Authored memories and the promise are available after role activation without three x.story turns; x.story/x.promise are optional retellings, show_photo is optional preview, never handover or a required checkpoint. A standalone x.gift_offer remains available after recognition. Keep the current offer_id: one current accept_gift runs x.gift_accept and its exact handover scene receipt completes the gift. After refusal, if the current user clearly reconsiders AND accepts the same previously presented gift now, use x.gift_accept with reopen_accept_gift, the exact declined_gift_offer.offer_id, its effect_id as reference_effect_id and the full current evidence_text. This is one acceptance, not a new invitation. A bare mention, hypothetical, quotation, negation, uncertainty, or asking only to reopen is not current acceptance; interpret intent without keyword triggers. For reopen-only use x.gift_offer/reopen_gift with a fresh offer_id. Global Stop revokes pending work and suspends the chapter, but a retained declined_gift_offer is historical evidence: a NEW current reopen_accept_gift can explicitly reopen and accept it with a new handover receipt. Plain accept_gift cannot reopen it. Exit/checkpoint revoke the reference; a fresh offer then requires explicit reopen_gift, with no penalty. Never invent a missing reference. draft_cue is inert planning and never displayed/spoken. For x.ask_role, x.story, x.promise and t.offer, awaiting_dialogue means author one natural first-person subtitle, at most 500 characters, plus corresponding speech if enabled; only its actual receipt advances the spoken step. The compound recognition continuation has the same 500-character bound. Use sourced details naturally without source labels, interrogating the user, or asking them to request each step. t.offer targets rain_window or amber_raincoat; t.yes/t.window require current offer and accept_rain; t.no requires decline_rain. Empty optional strings mean absent. One operation plus one continuation; no loop, retry or call proves display.',
}


def control_effect(name, arguments):
    if name in ('set_outfit', 'set_accessory', 'set_emotion'):
        slot=name.removeprefix('set_')
        return EffectProposal(EffectKind.POSE, slot+'_'+arguments[slot])
    if name == 'perform_action':
        return EffectProposal(EffectKind.POSE, {'raise_camera':'camera_raise','return_camera':'camera_ready'}[arguments['action']])
    if name == 'set_scene':
        return EffectProposal(EffectKind.SCENE, arguments['scene'])
    return None


def control_capability(effect):
    if effect.kind is EffectKind.SCENE:
        # The baseline cafe and rain-window compositions share the same attested scene sources.
        return 'cafe.scene.rain_window' if effect.value=='cafe' else 'cafe.scene.'+effect.value
    return CHARACTER_CAPABILITIES.get(effect.value, 'mira.pose.'+effect.value)


def control_ready(effect, readiness):
    return readiness is not None and readiness.state_for(control_capability(effect)) is CapabilityState.READY


def tool_definitions(context, state, runtime, *, review_available, image_task_count, max_effects,
                     native_authority=False, role_confirmation_reference=None):
    if len(state.issued_effects) >= max_effects:
        return ()
    names=[]
    if native_authority and runtime is not None and state.story_image.request_id is not None and state.story_image.state in ('pending','generating','reviewing','qualified'):
        names.append('cancel_story_image')
    if state.activity_seq > state.photo_dismissed_through_activity:
        if event_available(EffectProposal(EffectKind.MEDIA,'trip_photo'),context.character_assets):
            names.append('show_photo')
    readiness = image_tool_readiness(context,state,runtime,review_available=review_available,
        image_task_count=image_task_count,max_effects=max_effects)
    if readiness.state=='enabled':names.append('generate_story_image')
    if native_authority:
        for name in ('set_outfit','set_accessory','set_emotion','perform_action','set_scene'):
            field=next(iter(TOOL_FIELDS[name]))
            if any(control_ready(control_effect(name,{field:v}),context.character_assets)
                    for v in TOOL_FIELDS[name][field]['enum']): names.append(name)
        if context.character_story is not None: names.append('advance_story')
    descriptions=dict(TOOL_DESCRIPTIONS)
    if role_confirmation_reference is not None:
        reference,epoch=role_confirmation_reference
        descriptions['advance_story']+=' Current application confirmation reference: '+reference+'; source output_epoch='+str(epoch)+'. Only this exact prior presented question can confirm the fictional role now.'
    return tuple(ToolDefinition(name,descriptions[name],json.dumps({'type':'object',
        'properties':TOOL_FIELDS[name],'required':list(TOOL_FIELDS[name]),'additionalProperties':False})) for name in names)


def parse_tool_arguments(call):
    if (type(call) is not GenerationToolCall or type(call.call_id) is not str
            or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',call.call_id)
            or type(call.arguments_json) is not str or len(call.arguments_json.encode('utf-8'))>8192):
        raise ValueError('tool_call_invalid')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError('tool_argument_duplicate')
            result[key]=value
        return result
    def invalid(_value): raise ValueError('tool_argument_nonfinite')
    value=json.loads(call.arguments_json,object_pairs_hook=unique,parse_constant=invalid)
    fields=TOOL_FIELDS.get(call.name)
    if fields is None: raise ValueError('tool_unavailable')
    if type(value) is not dict or set(value)!=set(fields): raise ValueError('tool_arguments_invalid')
    for key,field in fields.items():
        item=value[key]
        if (type(item) is not str or not field.get('minLength',1)<=len(item)<=field.get('maxLength',600)
                or any(ord(c)<32 or ord(c)==127 or 0xD800<=ord(c)<=0xDFFF for c in item)
                or ('enum' in field and item not in field['enum'])
                or field.get('minLength',1)>0 and not item.strip()):
            raise ValueError('tool_arguments_invalid')
    return value


@dataclass(frozen=True, slots=True)
class NativeDialogueIntent:
    """Application-owned finite intent; deliberately contains no control prose."""
    transition_id: str
    input_act: str
    offer_id: str
    target: str
    recognition_effect_id: str | None = None


@dataclass(frozen=True, slots=True)
class NativeToolIdentity:
    effect_id: str | None
    request_id: str
    output_epoch: int
    activity_seq: int
    status: str = 'pending'
    reason: str | None = None
    dialogue_intent: NativeDialogueIntent | None = None


def accepted_effect_receipt(state,effect_id):
    effect=next((e for e in state.presented_effects if e.id==effect_id),None)
    if effect is None:return None
    return next((r for r in state.receipts if (r.effect_id,r.digest,r.output_epoch,r.activity_seq)==
        (effect.id,effect.digest,effect.output_epoch,effect.activity_seq)),None)


def current_control_receipt(state,effect):
    def slot(e):
        if e.kind is EffectKind.SCENE:return ('scene',)
        if e.kind is EffectKind.POSE:
            return ('pose',e.value.split('_',1)[0])
        return (e.kind,)
    latest=next((e for e in reversed(state.issued_effects) if slot(e)==slot(effect)),None)
    return accepted_effect_receipt(state,latest.id) if latest is not None and latest.value==effect.value else None


def dialogue_only(candidate):
    if (type(candidate) is not CandidateRange or type(candidate.effects) is not tuple
            or not candidate.effects
            or any(type(effect) is not EffectProposal or effect.kind not in (EffectKind.SUBTITLE,EffectKind.SPEECH)
                   for effect in candidate.effects)
            or any(value is not None for value in (candidate.story_proposal_json,candidate.affect_proposal_json,
                                                   candidate.image_proposal_json,candidate.image_intent))):
        raise DomainError('invalid_response','Tool continuation must contain only dialogue.')
    return candidate


def accepted_photo_receipt(state, effect_id):
    effect=next((e for e in state.presented_effects if e.id==effect_id and e.kind is EffectKind.MEDIA),None)
    if effect is None: return None
    return next((r for r in state.receipts if (r.effect_id,r.digest,r.output_epoch,r.activity_seq)
        == (effect.id,effect.digest,effect.output_epoch,effect.activity_seq)),None)


def current_photo_receipt(state):
    photos={e.id for e in state.presented_effects if e.kind is EffectKind.MEDIA
            and (e.value=='trip_photo' or parse_generated_photo(e.value) is not None)}
    return max((r for r in state.receipts if r.effect_id in photos),key=lambda r:r.presentation_seq,default=None)


def visible_fixed_receipt(state):
    receipt=current_photo_receipt(state)
    if not state.photo_visible or receipt is None: return None
    return receipt if any(e.id==receipt.effect_id and e.value=='trip_photo'
        and e.activity_seq>state.photo_dismissed_through_activity for e in state.presented_effects) else None


def tool_result(call, status, *, state=None, receipt=None, reason=None, phase=None):
    value={'schema':'mira.generation-tool-result.v1','tool':call.name,'status':status,
        'shown':receipt is not None,'visible':bool(receipt is not None and state is not None
            and state.photo_visible and current_photo_receipt(state)==receipt),
        'provenance':('authored_illustration' if call.name=='show_photo' else
            'generated_visualization' if call.name=='generate_story_image' else 'authored_character_control')}
    if call.name in NATIVE_CHARACTER_TOOLS:
        value['visible']=receipt is not None
    if state is not None: value['state_revision']=state.revision
    if receipt is not None: value['receipt']=asdict(receipt)
    if call.name == 'perform_action' and receipt is not None and state is not None:
        effect = next((e for e in state.presented_effects if e.id == receipt.effect_id
            and e.kind is EffectKind.POSE and e.value in {'camera_ready','camera_raise'}), None)
        if effect is not None:
            value['action_outcome'] = {'pose':effect.value,'camera_held':True,'placed_on_table':False}
    if reason is not None: value['reason']=reason
    if phase is not None: value['phase']=phase
    return GenerationToolResult(call.call_id,json.dumps(value,ensure_ascii=False,separators=(',',':')))


def project_tool_result(call,state,identity):
    """Project only this operation, never a previous image's successful receipt."""
    if type(identity) is NativeToolIdentity:
        receipt=accepted_effect_receipt(state,identity.effect_id)
        if receipt is not None:return tool_result(call,'shown',state=state,receipt=receipt,reason=identity.reason)
        if (state.request_id,state.output_epoch,state.activity_seq)!=(identity.request_id,identity.output_epoch,identity.activity_seq):
            return tool_result(call,'cancelled',state=state,reason='superseded')
        if identity.effect_id is not None and not any(e.id==identity.effect_id for e in state.active_grants):
            return tool_result(call,'cancelled',state=state,reason='grant_revoked')
        return tool_result(call,identity.status,state=state,reason=identity.reason,
            phase='awaiting_dialogue' if identity.dialogue_intent is not None and identity.effect_id is None else None)
    if call.name=='show_photo':
        status=state.fixed_photo
        if status.attempt_seq!=identity: return tool_result(call,'held',state=state,reason='superseded')
        receipt=accepted_photo_receipt(state,status.effect_id)
        if receipt is not None: return tool_result(call,'shown',state=state,receipt=receipt)
        outcome=('failed' if status.state=='failed' else 'cancelled' if status.state in ('cancelled','dismissed') else 'held' if status.state=='held'
                 else 'pending')
        return tool_result(call,outcome,state=state,reason=status.reason,phase=status.state)
    status=state.story_image
    if status.request_id!=identity: return tool_result(call,'held',state=state,reason='superseded')
    fact=next((f for f in state.story_image_facts if f.request_id==identity),None)
    receipt=accepted_photo_receipt(state,fact.presented_effect_id) if fact is not None else None
    if receipt is not None: return tool_result(call,'shown',state=state,receipt=receipt)
    outcome=('unavailable' if status.state=='unavailable' else 'failed' if status.state=='failed'
             else 'cancelled' if status.state=='cancelled' else 'held' if status.state=='held' else 'pending')
    return tool_result(call,outcome,state=state,reason=status.failure_code,phase=status.state)
