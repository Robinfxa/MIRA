import { validateCueFields, validateCueGrants } from './cue-contract.js';
function object(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value))
        throw new Error('Invalid protocol object');
    return value;
}
function integer(value) {
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
function digest(value) { return typeof value === 'string' && /^[a-f0-9]{64}$/.test(value); }
function effect(value) {
    const item = object(value);
    if (typeof item.id !== 'string' || typeof item.value !== 'string' || !digest(item.digest)
        || !['subtitle', 'speech', 'pose', 'scene', 'media'].includes(String(item.kind))
        || !integer(item.output_epoch) || !integer(item.activity_seq))
        throw new Error('Invalid effect');
    validateCueFields(item);
    return Object.freeze({ ...item, ...(item.caption_chunk == null ? {} : {
            caption_chunk: Object.freeze({ ...item.caption_chunk })
        }) });
}
function progress(value) {
    const item = object(value);
    if (typeof item.effect_id !== 'string' || !digest(item.digest)
        || !['output_epoch', 'activity_seq', 'presentation_seq'].every(key => integer(item[key]) && item[key] > 0)
        || !integer(item.sample_rate_hz) || item.sample_rate_hz < 8000 || item.sample_rate_hz > 48000
        || !integer(item.rendered_samples) || item.rendered_samples > item.sample_rate_hz * 300
        || !['rendered', 'completed', 'interrupted', 'failed'].includes(String(item.status))
        || ((item.status === 'rendered' || item.status === 'completed') && item.rendered_samples === 0))
        throw new Error('Invalid audio progress');
    return Object.freeze({ ...item });
}
export function parseDiagnosticId(value) {
    return typeof value === 'string' && value.length === 34 && /^h_[0-9a-f]{32}$/.test(value) ? value : null;
}
function storyImage(value) {
    const item = object(value);
    const keys = ['capability', 'state', 'request_id', 'scene_id', 'resource_id', 'content_digest', 'failure_code', 'completion_state', 'completion_effect_id', 'completion_speech_effect_id', 'completion_available'];
    if (Object.keys(item).some(key => !keys.includes(key))
        || (item.capability !== undefined && !['unavailable', 'bounded_fiction'].includes(String(item.capability)))
        || (item.state !== undefined && !['unavailable', 'idle', 'held', 'pending', 'generating', 'reviewing', 'qualified', 'presented', 'failed', 'cancelled'].includes(String(item.state)))
        || ['request_id', 'resource_id'].some(key => item[key] != null && (typeof item[key] !== 'string'
            || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(item[key])))
        || (item.scene_id != null && (typeof item.scene_id !== 'string' || !/^[a-z0-9_-]{1,80}$/.test(item.scene_id)))
        || (item.completion_state !== undefined && !['unavailable', 'pending', 'context_consumed', 'requested', 'granted', 'presented', 'failed', 'cancelled'].includes(String(item.completion_state)))
        || (item.completion_available !== undefined && typeof item.completion_available !== 'boolean')
        || ['completion_effect_id', 'completion_speech_effect_id'].some(key => item[key] != null && (typeof item[key] !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(item[key])))
        || (item.content_digest != null && !digest(item.content_digest))
        || (item.failure_code != null && !['unavailable', 'ineligible', 'budget', 'generation', 'review', 'timeout', 'cancelled'].includes(String(item.failure_code)))) {
        throw new Error('Invalid generated illustration status');
    }
    return Object.freeze({ ...item });
}
function fixedPhoto(value) {
    const item = object(value);
    const keys = ['state', 'reason', 'attempt_seq', 'output_epoch', 'activity_seq', 'effect_id'];
    if (Object.keys(item).some(key => !keys.includes(key))
        || !['idle', 'pending', 'held', 'granted', 'preparing', 'receipt_pending', 'presented', 'failed', 'cancelled', 'dismissed'].includes(String(item.state))
        || !['attempt_seq', 'output_epoch', 'activity_seq'].every(key => integer(item[key]))
        || (item.reason != null && !['unavailable', 'already_visible', 'dismissed', 'review_unknown', 'review_rejected', 'review_failed', 'optional_ineligible', 'preparation_failed', 'presentation_failed', 'receipt_unconfirmed', 'cancelled'].includes(String(item.reason)))
        || (item.effect_id != null && (typeof item.effect_id !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(item.effect_id)))) {
        throw new Error('Invalid fixed illustration status');
    }
    return Object.freeze({ ...item });
}
export function parseSession(value) {
    const item = object(value);
    if (item.schema_version !== '0.1.0-foundation'
        || typeof item.session_id !== 'string' || typeof item.client_instance_id !== 'string'
        || !['revision', 'activity_seq', 'input_epoch', 'output_epoch', 'permit_revision'].every(k => integer(item[k]))
        || !['idle', 'thinking', 'ready', 'stopped', 'error'].includes(String(item.phase))
        || !(item.request_id === null || typeof item.request_id === 'string')
        || !(item.last_error === null || typeof item.last_error === 'string')
        || (item.photo_visible !== undefined && typeof item.photo_visible !== 'boolean')
        || (item.photo_visibility_revision !== undefined && !integer(item.photo_visibility_revision))
        || typeof item.sealed !== 'boolean'
        || (item.response_muted !== undefined && typeof item.response_muted !== 'boolean')
        || (item.response_mode !== undefined && (typeof item.response_mode !== 'string'
            || !['voice', 'text_only'].includes(item.response_mode)))
        || (item.response_preference_revision !== undefined && !integer(item.response_preference_revision))
        || !Array.isArray(item.active_grants) || !Array.isArray(item.presented_effects)
        || item.active_grants.length > 4096 || item.presented_effects.length > 4096
        || (item.audio_progress !== undefined && (!Array.isArray(item.audio_progress) || item.audio_progress.length > 4096))) {
        throw new Error('Incompatible session contract');
    }
    // Empty legacy foundation snapshots carry no audio claims; present claims are always validated.
    const history = (item.audio_progress ?? []);
    const grants = item.active_grants.map(effect);
    validateCueGrants(grants);
    return Object.freeze({ ...item,
        ...(item.chapter_projection === undefined ? {} : { chapter_projection: item.chapter_projection === null
                ? null : chapterProjection(item.chapter_projection) }),
        ...(item.fixed_photo === undefined ? {} : { fixed_photo: fixedPhoto(item.fixed_photo) }),
        ...(item.story_image === undefined ? {} : { story_image: storyImage(item.story_image) }),
        last_error_diagnostic_id: item.last_error !== null && Object.hasOwn(item, 'last_error_diagnostic_id')
            ? parseDiagnosticId(item.last_error_diagnostic_id) : null,
        active_grants: Object.freeze(grants),
        presented_effects: Object.freeze(item.presented_effects.map(effect)),
        audio_progress: Object.freeze(history.map(progress)),
    });
}
function chapterProjection(value) {
    const item = object(value);
    const keys = ['schema', 'source_hash', 'stage', 'role_active', 'role_name', 'active_gift_offer_id',
        'gift_offer_effect_id', 'gift_offer_effect_digest', 'pending_transition', 'completed', 'revision', 'suspended'];
    const stages = ['stranger_cafe', 'recognized', 'old_friend_story', 'photo_promise', 'photo_previewed', 'gift_offered', 'gift_declined', 'completed'];
    const transitions = ['x.recognize', 'x.story', 'x.promise', 'x.preview', 'x.gift_offer', 'x.gift_accept', 'x.gift_decline', 'x.exit'];
    if (Object.keys(item).length !== keys.length || Object.keys(item).some(key => !keys.includes(key))
        || item.schema !== 'mira.xiahe-chapter.v1' || !digest(item.source_hash)
        || !stages.includes(String(item.stage)) || typeof item.role_active !== 'boolean'
        || (item.role_name !== null && item.role_name !== '夏禾')
        || (item.role_active ? item.role_name !== '夏禾' : item.role_name !== null)
        || (item.active_gift_offer_id !== null && (typeof item.active_gift_offer_id !== 'string'
            || item.active_gift_offer_id.length < 1 || item.active_gift_offer_id.length > 128))
        || (item.gift_offer_effect_id !== null && (typeof item.gift_offer_effect_id !== 'string'
            || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(item.gift_offer_effect_id)))
        || (item.gift_offer_effect_digest !== null && !digest(item.gift_offer_effect_digest))
        || (item.pending_transition !== null && !transitions.includes(String(item.pending_transition)))
        || typeof item.completed !== 'boolean' || !integer(item.revision) || typeof item.suspended !== 'boolean') {
        throw new Error('Invalid chapter projection');
    }
    return Object.freeze({ ...item });
}
export function parseCreated(value) {
    const item = object(value);
    if (typeof item.session_token !== 'string' || item.session_token.length === 0)
        throw new Error('Missing session capability');
    return Object.freeze({ session: parseSession(item.session), session_token: item.session_token });
}
