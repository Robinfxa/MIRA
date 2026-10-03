import type { PublicConfig } from '../../shared/config.js';
import { safeHttpError } from '../diagnostics/status.js';
import type { AudioProgressRequest, CreateSessionResponse, EffectView, InputRequest, ReceiptRequest, SessionView, StopRequest } from '../../shared/generated/contracts.js';
import { parseCreated, parseSession } from '../../shared/protocol.js';
import { BrowserAudioTransport } from './audio-transport.js';
import type { AudioTransportPrimitives } from './audio-transport.js';
import type { MicrophoneOrigin, MicrophoneStream, SessionTransport, VoiceCapabilities } from './ports.js';

/** All capabilities stay in memory. No token in URLs, persisted storage, or diagnostics. */
export class MiraApiClient implements SessionTransport {
  private sessionId: string | null = null;
  private token: string | null = null;
  private closed = false;
  private creating = false;
  private readonly pending = new Set<AbortController>();
  private readonly audio: BrowserAudioTransport;
  private readonly fetcher: typeof fetch;
  constructor(private readonly config: PublicConfig, primitives: AudioTransportPrimitives = {}) {
    this.fetcher = primitives.fetch ?? globalThis.fetch;
    this.audio = new BrowserAudioTransport(config, () => {
      if (this.closed || !this.sessionId || !this.token) throw new Error('Session not connected');
      return {sessionId: this.sessionId, token: this.token};
    }, primitives);
  }
  private async request<T>(path: string, method: string, body: unknown,
      parse: (raw: unknown) => T, signal?: AbortSignal): Promise<T> {
    if (this.closed) throw new Error('Session closed');
    const abort = new AbortController();
    this.pending.add(abort);
    const timeout = setTimeout(() => abort.abort(), 5000);
    const combined = signal ? AbortSignal.any([signal, abort.signal]) : abort.signal;
    try {
      const response = await this.fetcher(this.config.apiBase + path, {
        method, headers: {'Content-Type': 'application/json', ...(this.token ? {'X-Mira-Session-Token': this.token} : {})},
        body: body === undefined ? null : JSON.stringify(body), signal: combined, cache: 'no-store', redirect: 'error',
      });
      if (!response.ok) throw new Error(safeHttpError(response.status, response.headers.get('x-request-id')));
      let raw: unknown;
      try { raw = await response.json(); } catch { throw new Error('Invalid session response. Local output stays blocked.'); }
      return parse(raw);
    } finally { clearTimeout(timeout); this.pending.delete(abort); }
  }
  async create(clientInstanceId: string, signal?: AbortSignal): Promise<CreateSessionResponse> {
    if (this.creating || this.sessionId) throw new Error('Session already connected or connecting');
    this.creating = true;
    try {
      const created = await this.request('/sessions', 'POST', {client_instance_id: clientInstanceId}, parseCreated, signal);
      if (this.closed || signal?.aborted) {
        // Even an uncooperative late create cannot leak a connected browser session.
        void this.remove(created.session.session_id, created.session_token).catch(() => {});
        throw new Error('Session closed');
      }
      this.sessionId = created.session.session_id;
      this.token = created.session_token;
      return created;
    } finally { this.creating = false; }
  }
  private path(suffix = ''): string {
    if (this.closed || !this.sessionId) throw new Error('Session not connected');
    return `/sessions/${encodeURIComponent(this.sessionId)}${suffix}`;
  }
  capabilities(signal?: AbortSignal): Promise<VoiceCapabilities> {
    return this.request('/voice-capabilities', 'GET', undefined, raw => {
      if (!raw || typeof raw !== 'object') throw new Error('Invalid voice capability response');
      const value = raw as Record<string, unknown>;
      if (!['mock', 'replay', 'rehearsal', 'injected'].includes(String(value['generation_mode']))
        || typeof value['speech_enabled'] !== 'boolean' || typeof value['microphone_enabled'] !== 'boolean'
        || value['speech_sample_rate_hz'] !== 24000 || value['microphone_sample_rate_hz'] !== 16000
        || !['injected_unverified', 'unavailable', 'offline_fixture'].includes(String(value['qualification']))) throw new Error('Invalid voice capability response');
      return Object.freeze({...value}) as unknown as VoiceCapabilities;
    }, signal);
  }
  snapshot(signal?: AbortSignal): Promise<SessionView> { return this.request(this.path(), 'GET', undefined, parseSession, signal); }
  input(body: InputRequest, signal?: AbortSignal): Promise<SessionView> { return this.request(this.path('/inputs'), 'POST', body, parseSession, signal); }
  stop(body: StopRequest, signal?: AbortSignal): Promise<SessionView> { return this.request(this.path('/stop'), 'POST', body, parseSession, signal); }
  receipt(body: ReceiptRequest): Promise<SessionView> { return this.request(this.path('/receipts'), 'POST', body, parseSession); }
  audioProgress(body: AudioProgressRequest): Promise<SessionView> { return this.request(this.path('/audio-progress'), 'POST', body, parseSession); }
  speech(effect: EffectView, signal: AbortSignal, onPcm: (pcm: Int16Array) => void | Promise<void>): Promise<void> {
    return this.audio.speech(effect, signal, onPcm);
  }
  microphone(origin: MicrophoneOrigin, signal: AbortSignal): MicrophoneStream { return this.audio.microphone(origin, signal); }
  private async remove(sessionId: string, token: string): Promise<void> {
    const response = await this.fetcher(`${this.config.apiBase}/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE', headers: {'X-Mira-Session-Token': token}, keepalive: true,
      signal: AbortSignal.timeout(5000), redirect: 'error',
    });
    if (!response.ok && response.status !== 404) throw new Error('Server session cleanup could not be confirmed.');
  }
  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    for (const abort of this.pending) abort.abort();
    this.pending.clear();
    this.audio.close();
    const id = this.sessionId, token = this.token;
    this.sessionId = null;
    this.token = null;
    if (id && token) await this.remove(id, token);
  }
}
