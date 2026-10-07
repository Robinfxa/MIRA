import { safeHttpError } from '../diagnostics/status.js';
import { parseCreated, parseSession } from '../../shared/protocol.js';
import { generatedPhotoIdentity } from '../../shared/photo-value.js';
import { awaitImageOperation, readGeneratedImageResponse } from '../presentation/generated-image-resource.js';
import { parseReviewedAudioStatus } from '../diagnostics/reviewed-audio.js';
import { BrowserAudioTransport } from './audio-transport.js';
import { MiraTransportError, classifyTransportFailure, isAbortFailure } from './transport-errors.js';
/** Safe HTTP error metadata. The response body message is never reflected to the UI. */
export class MiraHttpError extends Error {
    status;
    code;
    constructor(status, code, safeMessage) {
        super(safeMessage);
        this.status = status;
        this.code = code;
    }
}
/** All capabilities stay in memory. No token in URLs, persisted storage, or diagnostics. */
export class MiraApiClient {
    config;
    sessionId = null;
    token = null;
    closed = false;
    creating = false;
    pending = new Set();
    audio;
    fetcher;
    clock;
    constructor(config, primitives = {}) {
        this.config = config;
        // Native browser fetch requires its global receiver, not this client instance.
        // Keep explicitly injected transports unchanged for tests and embedding callers.
        this.fetcher = primitives.fetch ?? ((...args) => globalThis.fetch(...args));
        this.clock = primitives.now ?? (() => performance.now());
        this.audio = new BrowserAudioTransport(config, () => {
            if (this.closed || !this.sessionId || !this.token)
                throw new Error('Session not connected');
            return { sessionId: this.sessionId, token: this.token };
        }, primitives);
    }
    async request(path, method, body, parse, signal, onAbortedParsed) {
        if (this.closed)
            throw new Error('Session closed');
        const abort = new AbortController();
        this.pending.add(abort);
        const timeoutError = new MiraTransportError('request_timeout', 5000);
        const timeout = setTimeout(() => abort.abort(timeoutError), 5000);
        const combined = signal ? AbortSignal.any([signal, abort.signal]) : abort.signal;
        try {
            const response = await this.fetcher(this.config.apiBase + path, {
                method, headers: { 'Content-Type': 'application/json', ...(this.token ? { 'X-Mira-Session-Token': this.token } : {}) },
                body: body === undefined ? null : JSON.stringify(body), signal: combined, cache: 'no-store', redirect: 'error',
            });
            if (combined.aborted && !onAbortedParsed)
                throw combined.reason;
            if (!response.ok) {
                let code = null;
                if (response.status === 409) {
                    try {
                        const raw = await response.json();
                        if (raw && typeof raw === 'object' && !Array.isArray(raw)
                            && raw['code'] === 'history_pending')
                            code = 'history_pending';
                    }
                    catch { /* Non-JSON and arbitrary conflicts keep their generic safe message. */ }
                }
                else if (response.status === 429) {
                    const raw = await readBoundedJson(response, 4096);
                    if (raw && typeof raw === 'object' && !Array.isArray(raw)
                        && raw['code'] === 'session_capacity')
                        code = 'session_capacity';
                }
                throw new MiraHttpError(response.status, code, safeHttpError(response.status, response.headers.get('x-request-id'), code));
            }
            let raw;
            try {
                raw = await response.json();
            }
            catch (error) {
                if (combined.aborted || isAbortFailure(error))
                    throw error;
                throw new Error('Invalid session response. Local output stays blocked.');
            }
            const parsed = parse(raw);
            if (combined.aborted) {
                // A fetch implementation may ignore abort. Clean up a late create, but never install it.
                onAbortedParsed?.(parsed);
                throw combined.reason;
            }
            return parsed;
        }
        catch (error) {
            throw classifyTransportFailure(error, combined, timeoutError, this.closed);
        }
        finally {
            clearTimeout(timeout);
            this.pending.delete(abort);
        }
    }
    async create(clientInstanceId, signal) {
        if (this.creating || this.sessionId)
            throw new Error('Session already connected or connecting');
        this.creating = true;
        try {
            const created = await this.request('/sessions', 'POST', { client_instance_id: clientInstanceId }, parseCreated, signal, value => { void this.remove(value.session.session_id, value.session_token).catch(() => { }); });
            if (this.closed || signal?.aborted) {
                // Even an uncooperative late create cannot leak a connected browser session.
                void this.remove(created.session.session_id, created.session_token).catch(() => { });
                throw new Error('Session closed');
            }
            this.sessionId = created.session.session_id;
            this.token = created.session_token;
            return created;
        }
        finally {
            this.creating = false;
        }
    }
    path(suffix = '') {
        if (this.closed || !this.sessionId)
            throw new Error('Session not connected');
        return `/sessions/${encodeURIComponent(this.sessionId)}${suffix}`;
    }
    capabilities(signal) {
        return this.request('/voice-capabilities', 'GET', undefined, raw => {
            if (!raw || typeof raw !== 'object')
                throw new Error('Invalid voice capability response');
            const value = raw;
            if (!['mock', 'replay', 'rehearsal', 'injected'].includes(String(value['generation_mode']))
                || typeof value['speech_enabled'] !== 'boolean' || typeof value['microphone_enabled'] !== 'boolean'
                || value['speech_sample_rate_hz'] !== 24000 || value['microphone_sample_rate_hz'] !== 16000
                || !['injected_unverified', 'unavailable', 'offline_fixture'].includes(String(value['qualification'])))
                throw new Error('Invalid voice capability response');
            return Object.freeze({ ...value });
        }, signal);
    }
    snapshot(signal) { return this.request(this.path(), 'GET', undefined, parseSession, signal); }
    input(body, signal) { return this.request(this.path('/inputs'), 'POST', body, parseSession, signal); }
    stop(body, signal) { return this.request(this.path('/stop'), 'POST', body, parseSession, signal); }
    completeStoryImage(body, signal) {
        return this.request(this.path('/story-image-completions'), 'POST', body, parseSession, signal);
    }
    responsePreference(body, signal) {
        return this.request(this.path('/response-preference'), 'POST', body, parseSession, signal);
    }
    dismissPhoto(body) {
        return this.request(this.path('/photo-dismissals'), 'POST', body, parseSession);
    }
    fixedPhotoProgress(body) {
        return this.request(this.path('/fixed-photo-progress'), 'POST', body, parseSession);
    }
    async generatedImage(effect, signal) {
        const identity = effect.kind === 'media' ? generatedPhotoIdentity(effect.value) : null;
        // URL parsing strips TAB/LF/CR; reject controls before attaching the session capability.
        if (!identity || !/^\/(?!\/)[^\\?#\u0000-\u001f\u007f]*$/.test(this.config.apiBase) || !/^[a-f0-9]{64}$/.test(effect.digest)
            || !Number.isSafeInteger(effect.output_epoch) || effect.output_epoch < 1
            || !Number.isSafeInteger(effect.activity_seq) || effect.activity_seq < 1)
            throw new Error('Generated illustration unavailable');
        const path = this.path(`/story-images/${identity.resourceId}`);
        const abort = new AbortController();
        this.pending.add(abort);
        const timer = setTimeout(() => abort.abort(), 5000);
        const combined = AbortSignal.any([signal, abort.signal]);
        try {
            if (combined.aborted)
                throw new Error('Generated illustration cancelled');
            const body = { effect_id: effect.id, digest: effect.digest, output_epoch: effect.output_epoch,
                activity_seq: effect.activity_seq, content_digest: identity.contentDigest };
            const response = await awaitImageOperation(this.fetcher(this.config.apiBase + path, {
                method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Mira-Session-Token': this.token },
                body: JSON.stringify(body),
                signal: combined, cache: 'no-store', redirect: 'error', credentials: 'same-origin',
            }), combined, late => { void late.body?.cancel().catch(() => { }); });
            return await readGeneratedImageResponse(response, combined);
        }
        finally {
            clearTimeout(timer);
            this.pending.delete(abort);
        }
    }
    receipt(body) { return this.request(this.path('/receipts'), 'POST', body, parseSession); }
    audioProgress(body) { return this.request(this.path('/audio-progress'), 'POST', body, parseSession); }
    reviewedAudioStatus(signal) {
        return this.request(this.path('/reviewed-audio'), 'GET', undefined, parseReviewedAudioStatus, signal);
    }
    setReviewedAudioRecording(enabled, consent, signal) {
        const body = { enabled, consent };
        return this.request(this.path('/reviewed-audio/recording'), 'POST', body, parseReviewedAudioAction, signal);
    }
    requestReviewedAudioReview(streamId, signal) {
        if (!isUuid(streamId))
            throw new Error('Reviewed audio stream is invalid');
        return this.request(this.path(`/reviewed-audio/streams/${encodeURIComponent(streamId)}/review`), 'POST', {}, parseReviewedAudioReview, signal);
    }
    async reviewedAudioPreview(review, signal) {
        if (!isReviewId(review.review_id) || !isDigest(review.digest))
            throw new Error('Reviewed audio ticket is invalid');
        const requestPath = this.path(`/reviewed-audio/reviews/${encodeURIComponent(review.review_id)}/preview`);
        const apiPrefix = new URL(this.config.apiBase, 'http://mira.invalid').pathname.replace(/\/$/, '');
        const expectedPath = apiPrefix + requestPath;
        if (review.preview_path !== expectedPath)
            throw new Error('Reviewed audio preview path is invalid');
        if (this.closed)
            throw new Error('Session closed');
        const abort = new AbortController();
        this.pending.add(abort);
        const timeoutError = new MiraTransportError('request_timeout', 5000);
        const timeout = setTimeout(() => abort.abort(timeoutError), 5000);
        const combined = signal ? AbortSignal.any([signal, abort.signal]) : abort.signal;
        try {
            const response = await this.fetcher(this.config.apiBase + requestPath, {
                method: 'GET', headers: this.token ? { 'X-Mira-Session-Token': this.token } : {},
                signal: combined, cache: 'no-store', redirect: 'error',
            });
            if (combined.aborted) {
                void response.body?.cancel().catch(() => { });
                throw combined.reason;
            }
            if (!response.ok)
                throw new Error(safeHttpError(response.status, response.headers.get('x-request-id')));
            const sampleRateHz = Number(response.headers.get('x-mira-sample-rate-hz'));
            const kind = response.headers.get('x-mira-recording-kind');
            const digest = response.headers.get('x-mira-audio-digest');
            if (response.headers.get('content-type')?.split(';', 1)[0]?.trim().toLowerCase() !== 'application/octet-stream'
                || response.headers.get('x-mira-audio-format') !== 'pcm16le-mono'
                || sampleRateHz !== review.sample_rate_hz || kind !== review.kind || digest !== review.digest
                || !response.headers.get('cache-control')?.toLowerCase().split(',').some(value => value.trim() === 'no-store')) {
                void response.body?.cancel().catch(() => { });
                throw new Error('Reviewed audio preview metadata mismatch');
            }
            const length = response.headers.get('content-length');
            if (length !== null && (!/^\d+$/.test(length) || Number(length) > 512 * 1024)) {
                void response.body?.cancel().catch(() => { });
                throw new Error('Reviewed audio preview exceeded its bound');
            }
            const reader = response.body?.getReader();
            if (!reader)
                throw new Error('Reviewed audio preview body unavailable');
            const chunks = [];
            let total = 0;
            try {
                while (true) {
                    const item = await reader.read();
                    if (combined.aborted) {
                        await reader.cancel();
                        throw combined.reason;
                    }
                    if (item.done)
                        break;
                    if (!item.value || total + item.value.byteLength > 512 * 1024) {
                        await reader.cancel();
                        throw new Error('Reviewed audio preview exceeded its bound');
                    }
                    chunks.push(item.value);
                    total += item.value.byteLength;
                }
            }
            catch (error) {
                for (const chunk of chunks)
                    chunk.fill(0);
                throw error;
            }
            if (total !== review.byte_count || total < 2 || total % 2 !== 0) {
                for (const chunk of chunks)
                    chunk.fill(0);
                throw new Error('Reviewed audio preview length mismatch');
            }
            const bytes = new Uint8Array(total);
            let offset = 0;
            for (const chunk of chunks) {
                bytes.set(chunk, offset);
                offset += chunk.byteLength;
                chunk.fill(0);
            }
            let digestBytes;
            try {
                digestBytes = await globalThis.crypto.subtle.digest('SHA-256', bytes);
            }
            catch {
                bytes.fill(0);
                throw new Error('Reviewed audio digest verification is unavailable');
            }
            if (combined.aborted) {
                bytes.fill(0);
                throw combined.reason;
            }
            const actualDigest = Array.from(new Uint8Array(digestBytes), value => value.toString(16).padStart(2, '0')).join('');
            if (actualDigest !== review.digest) {
                bytes.fill(0);
                throw new Error('Reviewed audio preview digest mismatch');
            }
            return Object.freeze({ pcm16le: bytes, sampleRateHz: review.sample_rate_hz, kind: review.kind, digest: review.digest });
        }
        catch (error) {
            throw classifyTransportFailure(error, combined, timeoutError, this.closed);
        }
        finally {
            clearTimeout(timeout);
            this.pending.delete(abort);
        }
    }
    confirmReviewedAudio(review, body, signal) {
        if (!isReviewId(review.review_id) || !isDigest(review.digest) || body.reviewed_digest !== review.digest) {
            throw new Error('Reviewed audio confirmation does not match its ticket');
        }
        return this.request(this.path(`/reviewed-audio/reviews/${encodeURIComponent(review.review_id)}/confirm`), 'POST', body, parseReviewedAudioAction, signal);
    }
    speech(effect, signal, onPcm) {
        return this.audio.speech(effect, signal, onPcm);
    }
    microphone(origin, signal, observers) {
        return this.audio.microphone(origin, signal, observers);
    }
    continuousListening(leaseId, signal, observers, mode = 'manual') {
        return this.audio.continuousListening(leaseId, signal, observers, mode);
    }
    monotonicNow() { return this.clock(); }
    async remove(sessionId, token) {
        const response = await this.fetcher(`${this.config.apiBase}/sessions/${encodeURIComponent(sessionId)}`, {
            method: 'DELETE', headers: { 'X-Mira-Session-Token': token }, keepalive: true,
            signal: AbortSignal.timeout(5000), redirect: 'error',
        });
        if (!response.ok && response.status !== 404)
            throw new Error('Server session cleanup could not be confirmed.');
    }
    async close() {
        if (this.closed)
            return;
        this.closed = true;
        for (const abort of this.pending)
            abort.abort();
        this.pending.clear();
        this.audio.close();
        const id = this.sessionId, token = this.token;
        this.sessionId = null;
        this.token = null;
        if (id && token)
            await this.remove(id, token);
    }
}
/** Parse only small error envelopes. Error bodies are untrusted and never shown to users. */
async function readBoundedJson(response, maxBytes) {
    const contentType = response.headers.get('content-type')?.split(';', 1)[0]?.trim().toLowerCase();
    if (contentType !== 'application/json') {
        void response.body?.cancel().catch(() => { });
        return null;
    }
    const contentLength = response.headers.get('content-length');
    if (contentLength !== null && (!/^\d+$/.test(contentLength) || Number(contentLength) > maxBytes)) {
        void response.body?.cancel().catch(() => { });
        return null;
    }
    const reader = response.body?.getReader();
    if (!reader)
        return null;
    const chunks = [];
    let total = 0;
    try {
        while (true) {
            const item = await reader.read();
            if (item.done)
                break;
            if (!item.value || total + item.value.byteLength > maxBytes) {
                await reader.cancel();
                return null;
            }
            chunks.push(item.value);
            total += item.value.byteLength;
        }
    }
    catch (error) {
        if (isAbortFailure(error))
            throw error;
        return null;
    }
    finally {
        reader.releaseLock();
    }
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
    }
    try {
        return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    }
    catch {
        return null;
    }
}
function isUuid(value) {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}
function isReviewId(value) { return /^[0-9a-f]{32}$/.test(value); }
function isDigest(value) { return /^[0-9a-f]{64}$/.test(value); }
function parseReviewedAudioAction(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw))
        throw new Error('Reviewed audio action unavailable');
    const value = raw;
    const keys = ['scope', 'scope_notice', 'ok', 'code', 'message', 'recording_active', 'accepted_for_queue'];
    if (Object.keys(value).some(key => !keys.includes(key)) || (value['scope'] !== undefined && value['scope'] !== 'application')
        || typeof value['scope_notice'] !== 'string' || value['scope_notice'].length > 500
        || typeof value['ok'] !== 'boolean' || typeof value['code'] !== 'string' || value['code'].length > 100
        || typeof value['message'] !== 'string' || value['message'].length > 500
        || typeof value['recording_active'] !== 'boolean'
        || (value['accepted_for_queue'] !== undefined && typeof value['accepted_for_queue'] !== 'boolean')) {
        throw new Error('Reviewed audio action unavailable');
    }
    return Object.freeze({ ...value });
}
function parseReviewedAudioReview(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw))
        throw new Error('Reviewed audio ticket unavailable');
    const value = raw;
    const keys = ['scope', 'scope_notice', 'review_id', 'digest', 'kind', 'sample_rate_hz', 'byte_count',
        'expires_in_seconds', 'preview_path', 'notice'];
    if (Object.keys(value).some(key => !keys.includes(key)) || (value['scope'] !== undefined && value['scope'] !== 'application')
        || typeof value['scope_notice'] !== 'string' || value['scope_notice'].length > 500
        || typeof value['review_id'] !== 'string' || !isReviewId(value['review_id'])
        || typeof value['digest'] !== 'string' || !isDigest(value['digest'])
        || value['kind'] !== 'audio_input' && value['kind'] !== 'audio_output'
        || value['sample_rate_hz'] !== 16000 && value['sample_rate_hz'] !== 24000 && value['sample_rate_hz'] !== 48000
        || !Number.isSafeInteger(value['byte_count']) || value['byte_count'] < 2 || value['byte_count'] > 512 * 1024
        || typeof value['expires_in_seconds'] !== 'number' || !Number.isFinite(value['expires_in_seconds'])
        || value['expires_in_seconds'] <= 0 || value['expires_in_seconds'] > 60
        || typeof value['preview_path'] !== 'string' || value['preview_path'].length > 500
        || typeof value['notice'] !== 'string' || value['notice'].length > 500) {
        throw new Error('Reviewed audio ticket unavailable');
    }
    return Object.freeze({ ...value });
}
