import { safeHttpError } from '../diagnostics/status.js';
import { parseCreated, parseSession } from '../../shared/protocol.js';
import { BrowserAudioTransport } from './audio-transport.js';
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
    constructor(config, primitives = {}) {
        this.config = config;
        this.fetcher = primitives.fetch ?? globalThis.fetch;
        this.audio = new BrowserAudioTransport(config, () => {
            if (this.closed || !this.sessionId || !this.token)
                throw new Error('Session not connected');
            return { sessionId: this.sessionId, token: this.token };
        }, primitives);
    }
    async request(path, method, body, parse, signal) {
        if (this.closed)
            throw new Error('Session closed');
        const abort = new AbortController();
        this.pending.add(abort);
        const timeout = setTimeout(() => abort.abort(), 5000);
        const combined = signal ? AbortSignal.any([signal, abort.signal]) : abort.signal;
        try {
            const response = await this.fetcher(this.config.apiBase + path, {
                method, headers: { 'Content-Type': 'application/json', ...(this.token ? { 'X-Mira-Session-Token': this.token } : {}) },
                body: body === undefined ? null : JSON.stringify(body), signal: combined, cache: 'no-store', redirect: 'error',
            });
            if (!response.ok)
                throw new Error(safeHttpError(response.status, response.headers.get('x-request-id')));
            let raw;
            try {
                raw = await response.json();
            }
            catch {
                throw new Error('Invalid session response. Local output stays blocked.');
            }
            return parse(raw);
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
            const created = await this.request('/sessions', 'POST', { client_instance_id: clientInstanceId }, parseCreated, signal);
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
    receipt(body) { return this.request(this.path('/receipts'), 'POST', body, parseSession); }
    audioProgress(body) { return this.request(this.path('/audio-progress'), 'POST', body, parseSession); }
    speech(effect, signal, onPcm) {
        return this.audio.speech(effect, signal, onPcm);
    }
    microphone(origin, signal) { return this.audio.microphone(origin, signal); }
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
//# sourceMappingURL=api-client.js.map