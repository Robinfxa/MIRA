import type { PublicConfig } from '../../shared/config.js';
import { safeHttpError } from '../diagnostics/status.js';
import type { AudioProgressRequest, CreateSessionResponse, EffectView, InputRequest, ReceiptRequest,
  ReviewedAudioActionResponse, ReviewedAudioConfirmRequest, ReviewedAudioRecordingRequest,
  ReviewedAudioReviewResponse, ReviewedAudioStatusResponse, SessionView, StopRequest } from '../../shared/generated/contracts.js';
import { parseCreated, parseSession } from '../../shared/protocol.js';
import { parseReviewedAudioStatus, type ReviewedAudioPreview } from '../diagnostics/reviewed-audio.js';
import { BrowserAudioTransport } from './audio-transport.js';
import type { AudioTransportPrimitives } from './audio-transport.js';
import type { MicrophoneOrigin, MicrophoneStream, SessionTransport, VoiceCapabilities } from './ports.js';

/** Safe HTTP error metadata. The response body message is never reflected to the UI. */
export class MiraHttpError extends Error {
  constructor(readonly status: number, readonly code: string | null, safeMessage: string) { super(safeMessage); }
}

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
      if (!response.ok) {
        let code: string | null = null;
        if (response.status === 409) {
          try {
            const raw: unknown = await response.json();
            if (raw && typeof raw === 'object' && !Array.isArray(raw)
              && (raw as Record<string, unknown>)['code'] === 'history_pending') code = 'history_pending';
          } catch { /* Non-JSON and arbitrary conflicts keep their generic safe message. */ }
        }
        throw new MiraHttpError(response.status, code, safeHttpError(response.status, response.headers.get('x-request-id')));
      }
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
  reviewedAudioStatus(signal?: AbortSignal): Promise<ReviewedAudioStatusResponse> {
    return this.request(this.path('/reviewed-audio'), 'GET', undefined, parseReviewedAudioStatus, signal);
  }
  setReviewedAudioRecording(enabled: boolean, consent: boolean, signal?: AbortSignal): Promise<ReviewedAudioActionResponse> {
    const body: ReviewedAudioRecordingRequest = {enabled, consent};
    return this.request(this.path('/reviewed-audio/recording'), 'POST', body, parseReviewedAudioAction, signal);
  }
  requestReviewedAudioReview(streamId: string, signal?: AbortSignal): Promise<ReviewedAudioReviewResponse> {
    if (!isUuid(streamId)) throw new Error('Reviewed audio stream is invalid');
    return this.request(this.path(`/reviewed-audio/streams/${encodeURIComponent(streamId)}/review`),
      'POST', {}, parseReviewedAudioReview, signal);
  }
  async reviewedAudioPreview(review: ReviewedAudioReviewResponse, signal?: AbortSignal): Promise<ReviewedAudioPreview> {
    if (!isReviewId(review.review_id) || !isDigest(review.digest)) throw new Error('Reviewed audio ticket is invalid');
    const requestPath = this.path(`/reviewed-audio/reviews/${encodeURIComponent(review.review_id)}/preview`);
    const apiPrefix = new URL(this.config.apiBase, 'http://mira.invalid').pathname.replace(/\/$/, '');
    const expectedPath = apiPrefix + requestPath;
    if (review.preview_path !== expectedPath) throw new Error('Reviewed audio preview path is invalid');
    if (this.closed) throw new Error('Session closed');
    const abort = new AbortController();
    this.pending.add(abort);
    const timeout = setTimeout(() => abort.abort(), 5000);
    const combined = signal ? AbortSignal.any([signal, abort.signal]) : abort.signal;
    try {
      const response = await this.fetcher(this.config.apiBase + requestPath, {
        method: 'GET', headers: this.token ? {'X-Mira-Session-Token': this.token} : {},
        signal: combined, cache: 'no-store', redirect: 'error',
      });
      if (!response.ok) throw new Error(safeHttpError(response.status, response.headers.get('x-request-id')));
      const sampleRateHz = Number(response.headers.get('x-mira-sample-rate-hz'));
      const kind = response.headers.get('x-mira-recording-kind');
      const digest = response.headers.get('x-mira-audio-digest');
      if (response.headers.get('content-type')?.split(';', 1)[0]?.trim().toLowerCase() !== 'application/octet-stream'
        || response.headers.get('x-mira-audio-format') !== 'pcm16le-mono'
        || sampleRateHz !== review.sample_rate_hz || kind !== review.kind || digest !== review.digest
        || !response.headers.get('cache-control')?.toLowerCase().split(',').some(value => value.trim() === 'no-store')) {
        void response.body?.cancel().catch(() => {});
        throw new Error('Reviewed audio preview metadata mismatch');
      }
      const length = response.headers.get('content-length');
      if (length !== null && (!/^\d+$/.test(length) || Number(length) > 512 * 1024)) {
        void response.body?.cancel().catch(() => {});
        throw new Error('Reviewed audio preview exceeded its bound');
      }
      const reader = response.body?.getReader();
      if (!reader) throw new Error('Reviewed audio preview body unavailable');
      const chunks: Uint8Array[] = [];
      let total = 0;
      try {
        while (true) {
          const item = await reader.read();
          if (item.done) break;
          if (!item.value || total + item.value.byteLength > 512 * 1024) {
            await reader.cancel(); throw new Error('Reviewed audio preview exceeded its bound');
          }
          chunks.push(item.value); total += item.value.byteLength;
        }
      } catch (error) {
        for (const chunk of chunks) chunk.fill(0);
        throw error;
      }
      if (total !== review.byte_count || total < 2 || total % 2 !== 0) {
        for (const chunk of chunks) chunk.fill(0);
        throw new Error('Reviewed audio preview length mismatch');
      }
      const bytes = new Uint8Array(total);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; chunk.fill(0); }
      let digestBytes: ArrayBuffer;
      try { digestBytes = await globalThis.crypto.subtle.digest('SHA-256', bytes); }
      catch { bytes.fill(0); throw new Error('Reviewed audio digest verification is unavailable'); }
      const actualDigest = Array.from(new Uint8Array(digestBytes), value => value.toString(16).padStart(2, '0')).join('');
      if (actualDigest !== review.digest) { bytes.fill(0); throw new Error('Reviewed audio preview digest mismatch'); }
      return Object.freeze({pcm16le: bytes, sampleRateHz: review.sample_rate_hz, kind: review.kind, digest: review.digest});
    } finally { clearTimeout(timeout); this.pending.delete(abort); }
  }
  confirmReviewedAudio(review: ReviewedAudioReviewResponse, body: ReviewedAudioConfirmRequest,
      signal?: AbortSignal): Promise<ReviewedAudioActionResponse> {
    if (!isReviewId(review.review_id) || !isDigest(review.digest) || body.reviewed_digest !== review.digest) {
      throw new Error('Reviewed audio confirmation does not match its ticket');
    }
    return this.request(this.path(`/reviewed-audio/reviews/${encodeURIComponent(review.review_id)}/confirm`),
      'POST', body, parseReviewedAudioAction, signal);
  }
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

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}
function isReviewId(value: string): boolean { return /^[0-9a-f]{32}$/.test(value); }
function isDigest(value: string): boolean { return /^[0-9a-f]{64}$/.test(value); }
function parseReviewedAudioAction(raw: unknown): ReviewedAudioActionResponse {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Reviewed audio action unavailable');
  const value = raw as Record<string, unknown>;
  const keys = ['scope', 'scope_notice', 'ok', 'code', 'message', 'recording_active', 'accepted_for_queue'];
  if (Object.keys(value).some(key => !keys.includes(key)) || (value['scope'] !== undefined && value['scope'] !== 'application')
    || typeof value['scope_notice'] !== 'string' || value['scope_notice'].length > 500
    || typeof value['ok'] !== 'boolean' || typeof value['code'] !== 'string' || value['code'].length > 100
    || typeof value['message'] !== 'string' || value['message'].length > 500
    || typeof value['recording_active'] !== 'boolean'
    || (value['accepted_for_queue'] !== undefined && typeof value['accepted_for_queue'] !== 'boolean')) {
    throw new Error('Reviewed audio action unavailable');
  }
  return Object.freeze({...value}) as unknown as ReviewedAudioActionResponse;
}
function parseReviewedAudioReview(raw: unknown): ReviewedAudioReviewResponse {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Reviewed audio ticket unavailable');
  const value = raw as Record<string, unknown>;
  const keys = ['scope', 'scope_notice', 'review_id', 'digest', 'kind', 'sample_rate_hz', 'byte_count',
    'expires_in_seconds', 'preview_path', 'notice'];
  if (Object.keys(value).some(key => !keys.includes(key)) || (value['scope'] !== undefined && value['scope'] !== 'application')
    || typeof value['scope_notice'] !== 'string' || value['scope_notice'].length > 500
    || typeof value['review_id'] !== 'string' || !isReviewId(value['review_id'])
    || typeof value['digest'] !== 'string' || !isDigest(value['digest'])
    || value['kind'] !== 'audio_input' && value['kind'] !== 'audio_output'
    || value['sample_rate_hz'] !== 16000 && value['sample_rate_hz'] !== 24000 && value['sample_rate_hz'] !== 48000
    || !Number.isSafeInteger(value['byte_count']) || (value['byte_count'] as number) < 2 || (value['byte_count'] as number) > 512 * 1024
    || typeof value['expires_in_seconds'] !== 'number' || !Number.isFinite(value['expires_in_seconds'])
    || value['expires_in_seconds'] <= 0 || value['expires_in_seconds'] > 60
    || typeof value['preview_path'] !== 'string' || value['preview_path'].length > 500
    || typeof value['notice'] !== 'string' || value['notice'].length > 500) {
    throw new Error('Reviewed audio ticket unavailable');
  }
  return Object.freeze({...value}) as unknown as ReviewedAudioReviewResponse;
}
