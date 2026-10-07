"""Closed authored camera/photo vocabulary; presentation facts never imply capture.

No IO and no new permission authority. Bootstrap attests local availability; the
Actor holds unavailable or duplicate proposals before optional semantic review.
"""
from __future__ import annotations

from dataclasses import asdict, replace

from mira.domain.models import EffectKind
from mira.domain.story_images import parse_generated_photo
from mira.domain.story import CapabilityState, ReadinessCatalog

CAMERA_ENDPOINTS = ('camera_ready', 'camera_raise')
_CAMERA_POSES = CAMERA_ENDPOINTS + ('camera_lowered', 'look_at_rain')
MEDIA = ('trip_photo',)
CAMERA_MEANING = 'raise_held_camera_to_chest_only'
PHOTO_PROVENANCE = 'authored_illustration'


def event_available(effect, readiness: ReadinessCatalog | None) -> bool:
    if effect.kind is EffectKind.MEDIA:
        return (effect.value in MEDIA and readiness is not None
                and readiness.state_for('mira.media.' + effect.value) is CapabilityState.READY)
    if effect.kind is EffectKind.POSE:
        if effect.value == 'camera_raise':
            return (readiness is not None
                    and readiness.state_for('mira.pose.camera_raise') is CapabilityState.READY)
        if readiness is not None:
            identifier = ('mira.face.' + effect.value.removeprefix('face_')
                          if effect.value.startswith('face_') else 'mira.pose.' + effect.value)
            record = readiness.get(identifier)
            if record is not None:
                return record.state is CapabilityState.READY
    return True


def camera_uncertain(state) -> bool:
    """Unreceipted issued motion may have stopped halfway; old endpoint is stale."""
    latest = next((effect for effect in reversed(state.issued_effects)
                   if effect.kind is EffectKind.POSE and effect.value in _CAMERA_POSES), None)
    return latest is not None and not any(receipt.effect_id == latest.id for receipt in state.receipts)


def visual_facts(context) -> dict:
    camera = None
    code_native = (context.character_assets is not None
                   and context.character_assets.revision.startswith('code-native-review:'))
    for effect in reversed(context.presented_effects):
        if effect.kind is EffectKind.POSE and effect.value in _CAMERA_POSES:
            camera = effect.value
            break
        if not code_native and effect.kind is EffectKind.SCENE and effect.value == 'cafe':
            camera = 'camera_ready'
            break
    photo = next((effect for effect in reversed(context.presented_effects)
                  if effect.kind is EffectKind.MEDIA and effect.value in MEDIA), None)
    latest_photo=next((e for e in reversed(context.presented_effects) if e.kind is EffectKind.MEDIA
                      and (e.value in MEDIA or parse_generated_photo(e.value) is not None)),None)
    attempt = asdict(context.fixed_photo) if context.fixed_photo.state != 'idle' else None
    if attempt is not None: attempt.pop('effect_id')
    return {
        'camera': {'meaning': CAMERA_MEANING,
                   'last_acknowledged_endpoint': camera,
                   'status': ('uncertain' if context.visual_action_uncertain else
                              'acknowledged' if camera else 'unacknowledged')},
        'trip_photo': {'provenance': PHOTO_PROVENANCE, 'presented': photo is not None,
                       'visible': context.photo_visible and latest_photo is not None and latest_photo.value in MEDIA,
                       'visibility_revision': context.photo_visibility_revision,
                       'content': 'original coastal lighthouse illustration',
                       **({'latest_attempt': attempt} if attempt is not None else {})},
        'captures_photos': False,
    }


def visual_context_projection(context) -> dict | None:
    """Keep unrelated legacy story contexts byte-stable; include actual facts.

    Readiness alone is not presentation. Historical/uncertain camera state stays
    meaningful even if a renderer capability is now absent or unavailable.
    """
    facts = visual_facts(context)
    readiness = context.character_assets
    result = {}
    if (context.visual_action_uncertain or facts['camera']['last_acknowledged_endpoint'] is not None
            or readiness is not None
            and readiness.state_for('mira.pose.camera_raise') is CapabilityState.READY):
        result['camera'] = facts['camera']
    if (facts['trip_photo']['presented'] or context.fixed_photo.state != 'idle' or readiness is not None
            and readiness.state_for('mira.media.trip_photo') is CapabilityState.READY):
        result['trip_photo'] = facts['trip_photo']
    if result:
        result['captures_photos'] = False
    return result or None


def filter_visual_events(context, candidate, state):
    """Keep text independent; repeated confirmed targets do not become episodes.

    Do not deduplicate against a pre-Stop endpoint after a later motion grant.
    Rendering may be partial even though no new completion receipt exists.
    """
    facts = visual_facts(context)
    uncertain = context.visual_action_uncertain or camera_uncertain(state)
    target = None if uncertain else facts['camera']['last_acknowledged_endpoint']
    latest_photo = next((effect for effect in reversed(state.presented_effects)
        if effect.kind is EffectKind.MEDIA
        and (effect.value in MEDIA or parse_generated_photo(effect.value) is not None)), None)
    # Deduplicate the same visible target, not every image sharing this surface.
    # An acknowledged generated picture may be replaced by the requested fixed one.
    # Unknown visibility and an explicit dismissal fence remain conservative.
    photo_visible = (state.activity_seq <= state.photo_dismissed_through_activity
        or state.photo_visible and (latest_photo is None or latest_photo.value in MEDIA))
    code_native = (context.character_assets is not None
                   and context.character_assets.revision.startswith('code-native-review:'))
    effects = []
    for effect in candidate.effects:
        if not event_available(effect, context.character_assets):
            continue
        camera = effect.kind is EffectKind.POSE and effect.value in CAMERA_ENDPOINTS
        photo = effect.kind is EffectKind.MEDIA and effect.value in MEDIA
        if camera and target == effect.value:
            continue
        if photo and photo_visible:
            continue
        effects.append(effect)
        # This is only the endpoint of the retained proposal sequence, never a
        # presentation fact. The frontend executes these controls in order; a
        # later return must not be compared against the turn-start endpoint.
        if effect.kind is EffectKind.POSE and effect.value in _CAMERA_POSES:
            target = effect.value
        elif not code_native and effect.kind is EffectKind.SCENE:
            if effect.value == 'cafe':
                target = 'camera_ready'
        if photo:
            photo_visible = True
    return replace(candidate, effects=tuple(effects))
