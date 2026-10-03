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
    return Object.freeze({ ...item });
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
export function parseSession(value) {
    const item = object(value);
    if (item.schema_version !== '0.1.0-foundation'
        || typeof item.session_id !== 'string' || typeof item.client_instance_id !== 'string'
        || !['revision', 'activity_seq', 'input_epoch', 'output_epoch', 'permit_revision'].every(k => integer(item[k]))
        || !['idle', 'thinking', 'ready', 'stopped', 'error'].includes(String(item.phase))
        || !(item.request_id === null || typeof item.request_id === 'string')
        || !(item.last_error === null || typeof item.last_error === 'string')
        || typeof item.sealed !== 'boolean'
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
        last_error_diagnostic_id: item.last_error !== null && Object.hasOwn(item, 'last_error_diagnostic_id')
            ? parseDiagnosticId(item.last_error_diagnostic_id) : null,
        active_grants: Object.freeze(grants),
        presented_effects: Object.freeze(item.presented_effects.map(effect)),
        audio_progress: Object.freeze(history.map(progress)),
    });
}
export function parseCreated(value) {
    const item = object(value);
    if (typeof item.session_token !== 'string' || item.session_token.length === 0)
        throw new Error('Missing session capability');
    return Object.freeze({ session: parseSession(item.session), session_token: item.session_token });
}
//# sourceMappingURL=protocol.js.map