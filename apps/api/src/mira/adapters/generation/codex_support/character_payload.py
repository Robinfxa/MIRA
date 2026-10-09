"""Bounded untrusted character suggestions, separate from effects and authority."""
from __future__ import annotations

import hashlib

from mira.application.contracts import GenerationContext
from mira.domain.story import Affect, AffectSignal, parse_story_proposal, PROPOSAL_SIGNAL_BY_TRANSITION, awaited_friend_claim_available
from mira.domain.xiahe_chapter import CHAPTER_SCENES, validate_input_act
from mira.domain.models import EffectKind
from mira.application.character_controls import CHARACTER_POSES
from .payload import canonical, parse_effects, strict_json, POSES
from .types import CodexGenerationError


def offered_id(context: GenerationContext) -> str:
    if context.character_story is None:
        raise CodexGenerationError('codex_character_context_missing')
    raw=context.character_story.projection_id+':'+str(context.output_epoch)
    return 'offer.'+hashlib.sha256(raw.encode()).hexdigest()[:24]


def character_proposal_contract(context: GenerationContext) -> dict:
    return {
        'schema':'mira.character-proposals.v1',
        'next_offer_id':offered_id(context),
        'active_offer_id':context.character_story.active_offer_id,
        'story_proposal':{
            'fields':['transition_id','signal','offer_id','target_capabilities','draft_cue','input_act','reopen_offer'],
            'transitions':{key:value.value for key,value in PROPOSAL_SIGNAL_BY_TRANSITION.items()},
            'chapter':{
                'source':'facts.character_story.chapter',
                'awaited_friend_claim_available':awaited_friend_claim_available(
                    context.character_story.chapter,context.character_story.known_canon),
                'absent_state':'stranger_cafe; no recognition or chapter presentation has occurred',
                'scene_beats':CHAPTER_SCENES,
                'input_act':{'fields':['kind','evidence_text','role_name'],
                    'kinds':['claim_role','exit_role','reopen_gift','reopen_rain','accept_gift','decline_gift'],
                    'role_name':'夏禾','evidence_text':'exact full current user_text, maximum 500 characters'},
                'rule':'Before role_active the user is an unrecognized visitor. Never assume their real identity or an earlier relationship. Propose x.recognize for an explicit unquoted unconditional first-person current role statement such as 我是夏禾 (I am Xiahe; this legacy validator requires the Chinese declaration), with input_act kind claim_role. When awaited_friend_claim_available is true, a current explicit first-person claim to be the old friend you are seeking or waiting for may name the same unique authored role Xiahe (wire role_name 夏禾) without repeating its name. This application fact cannot be supplied by user text or model output. Negation, quotations, questions, third-person or conditional mentions and an isolated affirmation remain ordinary chat, not recognition. No other role alias exists. Only receipt activates the role. x.exit with current explicit exit_role cancels future role acts. After recognition, supplied shared canon may be recalled naturally as authored past; it does not require three retelling turns. x.story and x.promise with exact draft_cue are optional receipted retellings. Use first person naturally, without source labels; these are fictional role relationships, never real remembered user history. Existing show_photo is optional preview, not a gift or a prerequisite for offering it. x.gift_offer uses next_offer_id and scene/xiahe_gift_offer. Only a receipted gift offer followed by current clear acceptance can propose x.gift_accept with chapter.active_gift_offer_id, input_act kind accept_gift naming the exact current user_text, and scene/xiahe_photo_handover. A decline uses x.gift_decline with input_act kind decline_gift and the exact current user_text, without penalty. After decline, a new gift offer needs input_act kind reopen_gift naming the exact current explicit request. Completed handover is a finite ending; free chat continues. Never introduce a third NPC or say another Xiahe is arriving. Legacy canon.waiting is the authored setup, not evidence of a separate arriving person. All author-provenance remains fiction. Use only chapter.allowed_next; never stage two chapter beats in one reply.',
            },
            'reopen_rule':'After a declined, suspended or unavailable rain invitation, propose a new t.offer only on the current explicit user request to reopen. Set reopen_offer true and input_act kind reopen_rain with exact current user_text. Quoted, negated or hypothetical requests cannot reopen. New invitations can start after either completed rain branch; raincoat and window are independent optional paths.',
            'window_capability':'cafe.scene.rain_window',
            'window_rule':'For an optional window-view invitation use t.offer with target_capabilities [cafe.scene.rain_window] and exact draft_cue. It offers a camera/view cut while keeping current outfit and pose, not walking. Only after the exact offer is presented and the current user clearly accepts it, use t.window with the same active_offer_id and target_capabilities [cafe.scene.rain_window], plus scene/rain_window. One YES is sufficient; no extra turn is needed. Do not substitute t.yes, change clothes, or claim arrival before a successful scene receipt. Declines and unrelated chat stay here. Old wardrobe invitations never authorize this window route.',
            'raincoat_capability':'mira.outfit.amber_raincoat',
            'rule':'Use next_offer_id for a new offer and active_offer_id for accepting an existing offer. t.yes only accepts the exact presented rain invitation. Direct user wardrobe/accessory requests may propose the matching authored pose without a story transition. Every control still needs full independent output review and an exact ready entry in facts.character_assets. Unknown or unavailable means stay naturally in the current scene. These suggestions do not grant actions. last_acknowledged_appearance is historical software presentation, not proof the current browser restored it; never claim automatic restoration.',
        },
        'affect_proposal':{
            'fields':['candidate','signal','canon_reason_id'],
            'candidates':[item.value for item in Affect],
            'signals':[item.value for item in AffectSignal],
            'rule':'Propose only; do not supply confidence or source IDs. Independent semantic evidence and recent-turn smoothing decide internal affect, independently of story progress and idle/listening/thinking/speaking phase. A visible emotion needs its own optional authored emotion pose in effects, full review, a ready asset, and agreement with the resulting internal affect. Mismatching optional emotion effects may be dropped; no unproposed emotion is added. Only a successful exact presentation receipt establishes visual history.',
        },
    }


def parse_character_candidate(texts, limits, context, *, speech_enabled=True):
    if context.character_story is None:
        return parse_effects(texts,limits,speech_enabled=speech_enabled),None,None
    if len(texts)!=1 or len(texts[0].encode('utf-8'))>limits.max_output_bytes:
        raise CodexGenerationError('codex_output_limit')
    obj=strict_json(texts[0])
    if (type(obj) is not dict or 'effects' not in obj
            or set(obj)-{'effects','story_proposal','affect_proposal'}):
        raise CodexGenerationError('codex_effects_invalid')
    effects=parse_effects([canonical({'effects':obj['effects']}).decode()],limits,
                         speech_enabled=speech_enabled,allowed_poses=POSES+CHARACTER_POSES)
    encoded=[]
    for name in ('story_proposal','affect_proposal'):
        value=obj.get(name)
        if value is None:
            encoded.append(None);continue
        if type(value) is not dict or len(canonical(value))>4096:
            raise CodexGenerationError('codex_character_proposal_invalid')
        try:
            if name=='story_proposal':
                parsed=parse_story_proposal(value,input_id='untrusted-candidate',epoch=context.output_epoch)
                if parsed.transition_id in {'t.offer','x.gift_offer'} and parsed.offer_id!=offered_id(context):
                    raise ValueError('offer_binding')
                if parsed.transition_id in {'t.offer','x.story','x.promise'} and (not parsed.draft_cue
                        or not any(effect.kind is EffectKind.SUBTITLE and effect.value==parsed.draft_cue
                                   for effect in effects)):
                    raise ValueError('offer_cue_binding')
                if parsed.transition_id in {'t.yes','t.window'} and (not context.character_story.active_offer_id
                        or parsed.offer_id!=context.character_story.active_offer_id):
                    raise ValueError('offer_binding')
                if parsed.transition_id in {'x.gift_accept','x.gift_decline'} and (
                        parsed.offer_id != context.character_story.chapter.active_gift_offer_id):
                    raise ValueError('chapter_offer_binding')
                if parsed.input_act is not None and parsed.input_act.evidence_text != context.user_text:
                    raise ValueError('chapter_input_binding')
                if parsed.transition_id in {'x.recognize','x.exit'} and not validate_input_act(
                        parsed.input_act,context.user_text,
                        'claim_role' if parsed.transition_id=='x.recognize' else 'exit_role',
                        awaited_friend=awaited_friend_claim_available(
                            context.character_story.chapter,context.character_story.known_canon)):
                    raise ValueError('chapter_current_role_statement')
                if parsed.reopen_offer and not validate_input_act(parsed.input_act,context.user_text,'reopen_rain'):
                    raise ValueError('chapter_reopen_binding')
            else:
                if (set(value)-{'candidate','signal','canon_reason_id'}
                        or not {'candidate','signal'}<=set(value)):
                    raise ValueError('affect_fields')
                Affect(value['candidate']);AffectSignal(value['signal'])
                reason=value.get('canon_reason_id')
                if reason is not None and (type(reason) is not str
                        or reason not in context.character_story.canon_entry_ids):
                    raise ValueError('affect_canon')
        except (ValueError,TypeError,KeyError):
            raise CodexGenerationError('codex_character_proposal_invalid') from None
        encoded.append(canonical(value).decode())
    return effects,*encoded


def parse_image_character_candidate(texts, limits, context, *, speech_enabled=True):
    """A recognized image suggestion can be held independently of valid conversation."""
    image=None
    if len(texts)==1 and len(texts[0].encode('utf-8'))<=limits.max_output_bytes:
        obj=strict_json(texts[0])
        if type(obj) is dict and 'image_proposal' in obj:
            raw=obj.pop('image_proposal')
            image=canonical(raw).decode()
            texts=[canonical(obj).decode()]
    effects,story,affect=parse_character_candidate(texts,limits,context,speech_enabled=speech_enabled)
    return effects,story,affect,image


def parse_conversation_character_candidate(texts, limits, context, *, speech_enabled=True):
    """Hold known optional failures only after strict, complete dialogue validation.

    This is selected only by the ordinary direct-tool response path. It never
    recovers JSON, permits media, or converts a suggestion into an action.
    A bad optional group holds all controls/proposals rather than executing a
    partially understood combination. Legacy and tool-continuation parsers stay strict.
    """
    from mira.application.optional_candidate_diagnostics import SafeOptionalCandidateDiagnostic
    if len(texts) != 1 or len(texts[0].encode('utf-8')) > limits.max_output_bytes:
        raise CodexGenerationError('codex_output_limit')
    obj = strict_json(texts[0])
    fields = {'effects', 'story_proposal', 'affect_proposal'} if context.character_story else {'effects'}
    if (type(obj) is not dict or 'effects' not in obj
            or set(obj) - fields
            or type(obj['effects']) is not list or not 1 <= len(obj['effects']) <= 8):
        raise CodexGenerationError('codex_effects_invalid')
    dialogue, controls = [], []
    for effect in obj['effects']:
        if type(effect) is not dict or set(effect) != {'kind', 'value'}:
            raise CodexGenerationError('codex_effects_invalid')
        kind = effect['kind']
        if type(kind) is not str or kind not in ('subtitle', 'speech', 'pose', 'scene'):
            raise CodexGenerationError('codex_effects_unsupported')
        (dialogue if kind in ('subtitle', 'speech') else controls).append(effect)
    if not dialogue:
        # A pure action is not recoverable dialogue. Preserve the old strict route.
        return (*parse_character_candidate(texts, limits, context, speech_enabled=speech_enabled), None)
    def encoded(value):
        return [canonical(value).decode('utf-8')]
    safe_effects = parse_effects(encoded({'effects': dialogue}), limits,
                                speech_enabled=speech_enabled)
    reasons = []
    try:
        parse_effects(encoded({'effects': obj['effects']}), limits,
                      speech_enabled=speech_enabled,
                      allowed_poses=POSES + (CHARACTER_POSES if context.character_story else ()))
    except CodexGenerationError as error:
        if error.args not in (('codex_effects_invalid',), ('codex_effects_unsupported',)):
            raise
        reasons.append('visual_controls_invalid')
    for name in ('story_proposal', 'affect_proposal'):
        if obj.get(name) is None:
            continue
        try:
            parse_character_candidate(encoded({'effects': dialogue, name: obj[name]}),
                                      limits, context, speech_enabled=speech_enabled)
        except CodexGenerationError as error:
            if error.args != ('codex_character_proposal_invalid',):
                raise
            reasons.append(name + '_invalid')
    if not reasons:
        return (*parse_character_candidate(texts, limits, context, speech_enabled=speech_enabled), None)
    hold = SafeOptionalCandidateDiagnostic(tuple(reasons),
        sum(e.kind is EffectKind.SUBTITLE for e in safe_effects),
        sum(e.kind is EffectKind.SPEECH for e in safe_effects), len(controls))
    return safe_effects, None, None, hold

