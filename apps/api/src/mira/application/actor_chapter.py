"""Narrow application bridge for the finite 夏禾 fiction chapter.

Scene values here are presentation beats. They must never enter environmental
scene or appearance reducers. No method creates an issued Actor grant itself.
"""
from dataclasses import replace
import hashlib

from mira.domain.models import EffectKind
from mira.domain.story import CapabilityState, EpisodeCandidate, EvidenceLabel
from mira.domain.xiahe_chapter import (CHAPTER_SCENES, CHAPTER_CAPABILITIES, CHAPTER_ASSETS,
    CHAPTER_REVISION, ChapterStage, ChapterPreviewReference, stage_chapter, bind_chapter_effect, acknowledge_chapter,
    validate_input_act)


def chapter_ready(readiness, value):
    cap = CHAPTER_CAPABILITIES.get(value)
    record = readiness.get(cap) if cap else None
    return bool(record is not None and record.state is CapabilityState.READY
        and record.asset_revision == CHAPTER_REVISION
        and CHAPTER_ASSETS[value] in record.verified_assets)


def local_role_proposal(proposal, user_text, *, awaited_friend=False):
    return bool(proposal and proposal.transition_id in {'x.recognize', 'x.exit'}
        and validate_input_act(proposal.input_act, user_text,
            'claim_role' if proposal.transition_id == 'x.recognize' else 'exit_role',
            awaited_friend=awaited_friend))


def prepare_chapter_state(story, proposal, effects, *, user_text, input_id, epoch,
                          readiness, reviewed, relevant, willingness, refusal, awaited_friend=False, native_act=None):
    if proposal.input_id != input_id or proposal.epoch != epoch or epoch != story.epoch:
        return story, ()
    scene = CHAPTER_SCENES.get(proposal.transition_id)
    effect = next((e for e in effects if (e.kind is EffectKind.SCENE and e.value == scene)), None) if scene else None
    if proposal.transition_id in {'x.story', 'x.promise'}:
        effect = next((e for e in effects if e.kind is EffectKind.SUBTITLE and e.value == proposal.draft_cue), None)
    ready = chapter_ready(readiness, scene) if scene else effect is not None
    scope = hashlib.sha256(('mira.story.scope.v1:' + story.scope_id).encode()).hexdigest()
    chapter = stage_chapter(story.chapter, transition=proposal.transition_id,
        input_id=input_id, epoch=epoch, user_text=user_text, input_act=proposal.input_act,
        offer_id=proposal.offer_id, draft_cue=proposal.draft_cue,
        reviewed=reviewed, relevant=relevant, willingness=willingness,
        refusal=refusal, ready=ready and effect is not None, scope_binding=scope,
        awaited_friend=awaited_friend,native_act=native_act)
    if chapter.pending is not None and chapter.pending != story.chapter.pending:
        chapter = bind_chapter_effect(chapter,effect_id=effect.id,digest=effect.digest,epoch=epoch)
    allowed = tuple(e for e in effects if e.kind in {EffectKind.SUBTITLE, EffectKind.SPEECH}
        or chapter.pending is not None and e.id == chapter.pending.effect_id)
    # Exit is immediate control cancellation; the user's reliable correction is
    # retained independently. No role correction is rewritten as user identity.
    return replace(story, chapter=chapter, input_fence_id=None,
        last_input_ids=story.last_input_ids if input_id in story.last_input_ids else (*story.last_input_ids,input_id)[-16:],
        revision=story.revision + 1), allowed


def acknowledge_chapter_effect(story, receipt, effect, *, issued_chapter=None):
    scope = hashlib.sha256(('mira.story.scope.v1:' + story.scope_id).encode()).hexdigest()
    pending = story.chapter.pending
    receipt_id = 'visual.' + effect.id + '.' + str(receipt.presentation_seq)
    if receipt_id in story.receipt_ids:
        return story, False
    chapter = story.chapter
    if pending is not None and pending.effect_id == effect.id:
        chapter = acknowledge_chapter(chapter,receipt_id=receipt_id,effect_id=effect.id,
            digest=effect.digest,epoch=receipt.output_epoch,scope_binding=scope)
        if chapter == story.chapter:
            return story, False
        milestone = pending.milestone
        reconciliation = 'current_exact_receipt'
    elif issued_chapter is not None and issued_chapter.effect_id == effect.id:
        # The Actor already verified actual pre-fence presentation. History can
        # reconcile, but a cancelled scene must not reactivate the current role.
        milestone = issued_chapter.milestone
        reconciliation = 'late_pre_fence_no_chapter_advance'
    elif (effect.kind is EffectKind.MEDIA and effect.value == 'trip_photo'
            and receipt.output_epoch == story.epoch and chapter.role_active
            and 'recognition' in dict(chapter.milestones)
            and 'photo_preview' not in dict(chapter.milestones) and chapter.pending is None):
        # Existing deterministic show_photo issues this effect. Its independently
        # verified actual receipt is preview evidence, never a gift receipt.
        chapter = stage_chapter(chapter, transition='x.preview', input_id='receipt.'+effect.id,
            epoch=receipt.output_epoch,user_text='',reviewed=True,relevant=True,ready=True,
            scope_binding=scope)
        chapter = bind_chapter_effect(chapter,effect_id=effect.id,digest=effect.digest,epoch=receipt.output_epoch)
        chapter = acknowledge_chapter(chapter,receipt_id=receipt_id,effect_id=effect.id,digest=effect.digest,
            epoch=receipt.output_epoch,scope_binding=scope)
        chapter=replace(chapter,preview_reference=ChapterPreviewReference('new_presentation',
            receipt_id,effect.id,effect.digest,receipt.output_epoch,receipt.activity_seq,receipt.presentation_seq))
        milestone, reconciliation = 'photo_preview', 'current_exact_receipt'
    else:
        return story, False
    episode = EpisodeCandidate(candidate_id='episode.xiahe:'+receipt_id,
        event_code='xiahe_'+milestone+'_presented',receipt_id=receipt_id,
        compiled_effect_id=effect.id,compiled_effect_digest=effect.digest,
        component_id=effect.id,component_digest=effect.digest,
        evidence=EvidenceLabel.CLIENT_REPORT,story_id=story.story_id,
        graph_revision=story.graph_revision,canon_revision=story.canon_revision,
        character_state=(('chapter_revision',CHAPTER_REVISION),('milestone',milestone),
            ('role_name','夏禾'),('history_scope','fictional_software_presentation'),
            ('source','authored_backstory'),('reconciliation',reconciliation)))
    releases = story.released_story_events
    release = {'old_friend':'story.photo_detail','photo_promise':'story.waiting_reason'}.get(milestone)
    if reconciliation == 'current_exact_receipt' and release and release not in releases:
        releases = (*releases,release)
    return replace(story,chapter=chapter,revision=story.revision+1,
        receipt_ids=(*story.receipt_ids,receipt_id)[-64:],episodes=(*story.episodes,episode)[-32:],
        released_story_events=releases),True
