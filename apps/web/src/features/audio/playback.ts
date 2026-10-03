import type { AudioOrigin, AudioRuntimeError, AudioStopReason, PlaybackFact, PlaybackStream } from './types.js';

export interface PlaybackOptions {
  /** Current authorization, independent of one-shot gate.consume / DOM receipts. */
  readonly isAuthorized: (origin: AudioOrigin) => boolean;
  readonly onFact?: (fact: PlaybackFact) => void;
  readonly onError?: (error: AudioRuntimeError) => void;
  /** Review-only audition lifecycle. Auditions never emit PlaybackFacts. */
  readonly onAuditionState?: (state: 'starting' | 'playing' | 'stopped' | 'completed' | 'failed') => void;
  readonly createContext?: () => AudioContext;
  readonly setInterval?: (callback: () => void, milliseconds: number) => number;
  readonly clearInterval?: (id: number) => void;
  readonly maxBufferedFrames?: number;
  readonly maxChunkFrames?: number;
  readonly maxQueuedChunks?: number;
}
interface StreamState {
  readonly generation: number;
  readonly origin: AudioOrigin;
  readonly queue: Int16Array[];
  sealed: boolean;
  pumping: boolean;
  bufferedFrames: number;
  submittedFrames: number;
  renderedFrames: number;
  source: AudioBufferSourceNode | null;
  activeFrames: number;
}
interface AuditionState {
  readonly generation: number;
  source: AudioBufferSourceNode | null;
}

/** One character-voice sink; no policy, wire receipts, provider selection or speech synthesis. */
export class CancelSafePlayback {
  private context: AudioContext | null = null;
  private current: StreamState | null = null;
  private auditioning: AuditionState | null = null;
  private auditionGeneration = 0;
  private generation = 0;
  private timer: number | null = null;
  private closed = false;
  private closePromise: Promise<void> | null = null;
  private readonly maxBufferedFrames: number;
  private readonly maxChunkFrames: number;
  private readonly maxQueuedChunks: number;
  constructor(private readonly options: PlaybackOptions) {
    this.maxBufferedFrames = this.bound(options.maxBufferedFrames ?? 120_000, 1, 480_000);
    this.maxChunkFrames = this.bound(options.maxChunkFrames ?? 24_000, 1, 48_000);
    this.maxQueuedChunks = this.bound(options.maxQueuedChunks ?? 50, 1, 500);
  }
  private bound(value: number, minimum: number, maximum: number): number {
    if (!Number.isSafeInteger(value) || value < minimum || value > maximum) throw new RangeError('Invalid audio buffer bound');
    return value;
  }
  /** True only when no ordinary speech or review audition owns the shared sink. */
  get quiescent(): boolean { return !this.closed && this.current === null && this.auditioning === null; }
  private authorized(origin: AudioOrigin): boolean {
    try { return this.options.isAuthorized(origin) === true; } catch { return false; }
  }
  private alive(state: StreamState): boolean {
    return !this.closed && this.current === state && state.generation === this.generation;
  }
  private permitted(state: StreamState): boolean {
    if (!this.alive(state)) return false;
    if (this.authorized(state.origin)) return true;
    this.stop('revoked');
    return false;
  }
  /** Call from a user gesture to satisfy browser autoplay policies; never requests microphone access. */
  async unlock(): Promise<boolean> {
    if (this.closed) return false;
    try { await this.getContext().resume(); return !this.closed; }
    catch { if (!this.closed) this.error('playback-failed', 'Audio could not start. Use text or retry audio from a user gesture.'); return false; }
  }
  open(origin: AudioOrigin): PlaybackStream | null {
    if (this.closed || !this.authorized(origin)) return null;
    // Reopening the same active effect must not restart already submitted sound.
    if (this.current && JSON.stringify(this.current.origin) === JSON.stringify(this.copyOrigin(origin))) return null;
    this.stopAudition();
    this.stop('new-input');
    const state: StreamState = { generation: ++this.generation, origin: this.copyOrigin(origin),
      queue: [], sealed: false, pumping: false, bufferedFrames: 0, submittedFrames: 0,
      renderedFrames: 0, source: null, activeFrames: 0 };
    this.current = state;
    this.timer = (this.options.setInterval ?? globalThis.setInterval)(() => this.reconcileAuthorization(), 20);
    return Object.freeze({
      push: (pcm16: Int16Array) => this.push(state, pcm16),
      finish: () => {
        if (!this.permitted(state) || state.sealed) return false;
        if (state.submittedFrames === 0 && state.bufferedFrames === 0) {
          this.fail(state, 'invalid-pcm', 'No audio was received for this response.');
          return false;
        }
        state.sealed = true;
        this.completeIfDrained(state);
        return true;
      },
    });
  }
  private copyOrigin(origin: AudioOrigin): AudioOrigin {
    return Object.freeze({id: origin.id, digest: origin.digest, activity_seq: origin.activity_seq, output_epoch: origin.output_epoch});
  }
  private push(state: StreamState, pcm16: Int16Array): boolean {
    if (!this.permitted(state) || state.sealed) return false;
    if (!(pcm16 instanceof Int16Array) || pcm16.length === 0) {
      this.fail(state, 'invalid-pcm', 'Audio requires nonempty signed PCM16 mono at 24 kHz.'); return false;
    }
    if (pcm16.length > this.maxChunkFrames || state.bufferedFrames + pcm16.length > this.maxBufferedFrames
      || state.queue.length + (state.source ? 1 : 0) >= this.maxQueuedChunks) {
      this.fail(state, 'queue-overflow', 'Audio buffer limit exceeded; this response was stopped.'); return false;
    }
    state.queue.push(pcm16.slice());
    state.bufferedFrames += pcm16.length;
    void this.pump(state);
    return true;
  }
  private getContext(): AudioContext {
    if (!this.context) {
      if (this.options.createContext) this.context = this.options.createContext();
      else if (typeof globalThis.AudioContext === 'function') this.context = new AudioContext({latencyHint: 'interactive'});
      else throw new Error('Web Audio unavailable');
    }
    return this.context;
  }
  /** Explicit user-gesture-only playback of a reviewed raw buffer through this shared sink. */
  async audition(pcm16: Int16Array, sampleRateHz: number): Promise<boolean> {
    if (this.closed || this.current || this.auditioning || !(pcm16 instanceof Int16Array)
      || pcm16.length < 1 || pcm16.length > 262_144
      || ![16_000, 24_000, 48_000].includes(sampleRateHz)) return false;
    const state: AuditionState = {generation: ++this.auditionGeneration, source: null};
    this.auditioning = state;
    this.notifyAudition('starting');
    try {
      const context = this.getContext();
      await context.resume();
      if (!this.activeAudition(state)) return false;
      const buffer = context.createBuffer(1, pcm16.length, sampleRateHz);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < pcm16.length; i++) channel[i] = pcm16[i]! / 32_768;
      const source = context.createBufferSource();
      state.source = source;
      source.buffer = buffer;
      source.onended = () => this.finishAudition(state);
      source.connect(context.destination);
      if (!this.activeAudition(state)) return false;
      source.start();
      this.notifyAudition('playing');
      return true;
    } catch {
      if (this.activeAudition(state)) this.terminateAudition(state, 'failed');
      this.error('playback-failed', 'Reviewed audio could not be auditioned. The clip was not saved.');
      return false;
    }
  }
  private activeAudition(state: AuditionState): boolean {
    return !this.closed && this.auditioning === state && state.generation === this.auditionGeneration;
  }
  private finishAudition(state: AuditionState): void {
    if (!this.activeAudition(state)) return;
    this.detachAudition(state);
    this.notifyAudition('completed');
  }
  /** Synchronously disconnects and drops a review audition without emitting any character fact. */
  stopAudition(): void {
    const state = this.auditioning;
    if (!state) return;
    this.terminateAudition(state, 'stopped');
  }
  private terminateAudition(state: AuditionState, outcome: 'stopped' | 'failed'): void {
    if (this.auditioning !== state || state.generation !== this.auditionGeneration) return;
    this.detachAudition(state);
    this.notifyAudition(outcome);
  }
  private detachAudition(state: AuditionState): void {
    this.auditioning = null;
    this.auditionGeneration++;
    const source = state.source;
    state.source = null;
    if (!source) return;
    source.onended = null;
    try { source.disconnect(); } catch { /* Already disconnected by the browser. */ }
    try { source.stop(); } catch { /* An already ended source can reject stop. */ }
    source.buffer = null;
  }
  private notifyAudition(state: 'starting' | 'playing' | 'stopped' | 'completed' | 'failed'): void {
    try { this.options.onAuditionState?.(state); } catch { /* An observer cannot retain or revive audio. */ }
  }
  private async pump(state: StreamState): Promise<void> {
    if (!this.permitted(state) || state.pumping || state.source || state.queue.length === 0) return;
    state.pumping = true;
    try {
      const context = this.getContext();
      await context.resume();
      // A pending autoplay/resume promise is never authority to start an old generation.
      if (!this.permitted(state)) return;
      const pcm16 = state.queue.shift();
      if (!pcm16) return;
      const buffer = context.createBuffer(1, pcm16.length, 24_000);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < pcm16.length; i++) channel[i] = pcm16[i]! / 32768;
      const source = context.createBufferSource();
      state.source = source;
      state.activeFrames = pcm16.length;
      source.buffer = buffer;
      source.onended = () => this.ended(state, source);
      source.connect(context.destination);
      if (!this.permitted(state)) return;
      source.start();
      state.submittedFrames += pcm16.length;
      this.fact(state, 'submitted');
    } catch {
      if (this.alive(state)) this.fail(state, 'playback-failed', 'Audio playback failed. Text input is still available.');
    } finally { state.pumping = false; }
  }
  private ended(state: StreamState, source: AudioBufferSourceNode): void {
    if (!this.permitted(state) || state.source !== source) return;
    source.onended = null;
    try { source.disconnect(); } catch { /* Already disconnected by the browser. */ }
    state.source = null;
    state.renderedFrames += state.activeFrames;
    state.bufferedFrames -= state.activeFrames;
    state.activeFrames = 0;
    this.fact(state, 'rendered');
    if (!this.alive(state)) return;
    this.completeIfDrained(state);
    void this.pump(state);
  }
  private completeIfDrained(state: StreamState): void {
    if (!this.permitted(state) || !state.sealed || state.source || state.queue.length !== 0 || state.bufferedFrames !== 0) return;
    this.current = null;
    this.clearTimer();
    this.fact(state, 'completed');
  }
  /** Integrator calls synchronously after every installed permit update. */
  reconcileAuthorization(): void {
    if (this.current && !this.authorized(this.current.origin)) this.stop('revoked');
  }
  stop(reason: AudioStopReason = 'stop'): void {
    this.stopAudition();
    this.terminate(reason, 'stopped');
  }
  private terminate(reason: AudioStopReason, stage: 'stopped' | 'failed'): void {
    const state = this.current;
    this.current = null;
    this.generation++;
    this.clearTimer();
    if (!state) return;
    state.queue.length = 0;
    state.bufferedFrames = 0;
    const source = state.source;
    state.source = null;
    if (source) {
      source.onended = null;
      // Disconnect synchronously even if stop() throws or onended is already queued.
      try { source.disconnect(); } catch { /* Best effort resource release. */ }
      try { source.stop(); } catch { /* An already ended source can reject stop. */ }
    }
    this.fact(state, stage, reason);
  }
  private clearTimer(): void {
    if (this.timer !== null) (this.options.clearInterval ?? globalThis.clearInterval)(this.timer);
    this.timer = null;
  }
  private fail(state: StreamState, code: AudioRuntimeError['code'], message: string): void {
    if (!this.alive(state)) return;
    this.terminate('error', 'failed');
    this.error(code, message);
  }
  private error(code: AudioRuntimeError['code'], message: string): void {
    try { this.options.onError?.(Object.freeze({code, message})); } catch { /* Error observers cannot revive the sink. */ }
  }
  private fact(state: StreamState, stage: PlaybackFact['stage'], reason?: AudioStopReason): void {
    const fact: PlaybackFact = Object.freeze({origin: state.origin, stage, submittedFrames: state.submittedFrames,
      renderedFrames: state.renderedFrames, sampleRate: 24000,
      inFlightFramesUncertain: state.submittedFrames - state.renderedFrames,
      ...(reason === undefined ? {} : {reason})});
    try { this.options.onFact?.(fact); }
    catch { if (this.alive(state)) this.fail(state, 'consumer-failed', 'Audio progress handling failed; playback stopped.'); }
  }
  close(): Promise<void> {
    if (this.closePromise) return this.closePromise;
    this.closed = true;
    this.stop('close');
    const context = this.context;
    this.context = null;
    this.closePromise = context ? context.close().catch(() => {
      this.error('playback-failed', 'The audio device did not close cleanly.');
    }) : Promise.resolve();
    return this.closePromise;
  }
}
