import type { PublicConfig } from '../../shared/config.js';
import type { AudioProgressRequest, EffectView, ReceiptRequest, SessionView } from '../../shared/generated/contracts.js';
import { CancelSafePlayback, MicrophoneCapture } from '../audio/index.js';
import type { PlaybackOptions, CaptureOptions, AudioStopReason, CapturedAudio, PlaybackFact, PlaybackStream } from '../audio/index.js';
import type { EffectExecutor } from '../presentation/ports.js';
import { safeSessionError } from '../diagnostics/status.js';
import { PresentationGate } from '../presentation/permit-gate.js';
import { MiraHttpError } from './api-client.js';
import type { MicrophoneStream, SessionTransport, VoiceCapabilities } from './ports.js';

export interface SessionViewPort {
  connected(): void;
  update(view: SessionView): void;
  error(message: string): void;
  localStop(): void;
  capabilities?(value: VoiceCapabilities): void;
  rehearsalInput?(state: 'listening' | 'stopped'): void;
  microphone?(state: 'starting' | 'recording' | 'finishing' | 'stopped'): void;
  reviewAudition?(state: 'starting' | 'playing' | 'stopped' | 'completed' | 'failed'): void;
}
type PlaybackPort = Pick<CancelSafePlayback, 'unlock' | 'open' | 'stop' | 'reconcileAuthorization' | 'close'
  | 'audition' | 'stopAudition' | 'quiescent'>;
type CapturePort = Pick<MicrophoneCapture, 'start' | 'stop' | 'close'>;
export interface ControllerOptions {
  readonly createPlayback?: (options: PlaybackOptions) => PlaybackPort;
  readonly createCapture?: (options: CaptureOptions) => CapturePort;
  /** Short local fence for facts already issued when a new generation starts. */
  readonly factDrainTimeoutMs?: number;
}
export type SessionInputOutcome =
  | { readonly status: 'submitted' }
  | { readonly status: 'not-sent'; readonly text: string; readonly reason: 'history-failed' | 'history-timeout' | 'history-pending' }
  | { readonly status: 'superseded' }
  | { readonly status: 'closed' }
  | { readonly status: 'unknown' }
  | { readonly status: 'ignored' };
interface SpeechRun {
  readonly effect: EffectView;
  readonly generation: number;
  readonly abort: AbortController;
  handle: PlaybackStream | null;
  accepted: number;
  rendered: number;
  wake: (() => void) | null;
}
interface RehearsalInputRun {
  readonly generation: number;
  ready: Promise<void>;
  released: boolean;
}
interface MicrophoneRun {
  readonly generation: number;
  readonly streamId: string;
  readonly abort: AbortController;
  readonly queue: CapturedAudio[];
  queuedBytes: number;
  released: boolean;
  transport: MicrophoneStream | null;
  setup: Promise<void>;
  finishing: Promise<SessionInputOutcome | undefined> | null;
}
interface VisualPreparationRun {
  readonly effect: EffectView;
  readonly generation: number;
  readonly gate: PresentationGate;
  readonly abort: AbortController;
}
interface FactAcknowledgement {
  readonly sequence: number;
  readonly status: 'saved' | 'failed' | 'closed';
}
interface FactDelivery {
  readonly sequence: number;
  readonly presentationSequence: number;
  readonly generation: number;
  readonly acknowledgement: Promise<FactAcknowledgement>;
}
interface FactSnapshot {
  readonly throughSequence: number;
  readonly presentationCutoff: number;
  readonly pending: readonly FactDelivery[];
}
interface FailedFact {
  readonly sequence: number;
  readonly presentationSequence: number;
}
type FactDrainResult = 'saved' | 'failed' | 'timeout' | 'superseded' | 'closed';
const MEDIA_PREPARATION_LIMIT = 4;
const MEDIA_PREPARATION_ERROR = '旅行插画暂时无法显示，请稍后重试或继续聊天。';
const FACT_DRAIN_TIMEOUT_MS = 1500;
const FACT_HISTORY_FAILED = 'Earlier presentation history could not be confirmed, so this input was not sent. Start a fresh session before continuing.';
const FACT_HISTORY_TIMEOUT = 'Earlier presentation history is still waiting to be saved, so this input was not sent. Wait briefly, then retry.';

/** One gate, one playback sink and one microphone. Every continuation carries local causality. */
export class SessionController {
  private reportedError: string | null = null;
  private gate: PresentationGate | null = null;
  private snapshot: SessionView | null = null;
  private capabilities: VoiceCapabilities | null = null;
  private running = false;
  private connecting = false;
  private closed = false;
  private generation = 0;
  private generationAbort = new AbortController();
  private readonly lifetime = new AbortController();
  private activityRequest: AbortController | null = null;
  private pollRequest: AbortController | null = null;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly playback: PlaybackPort;
  private readonly capture: CapturePort;
  private readonly visualPreparations = new Map<string, VisualPreparationRun>();
  private speech: SpeechRun | null = null;
  private microphone: MicrophoneRun | null = null;
  private rehearsalInput: RehearsalInputRun | null = null;
  private unlocked = false;
  private facts: Promise<void> = Promise.resolve();
  private pendingFacts = 0;
  private factSequence = 0;
  private failedFact: FailedFact | null = null;
  private readonly factDeliveries = new Map<number, FactDelivery>();
  private readonly factDrainTimeoutMs: number;
  private closePromise: Promise<void> | null = null;

  constructor(private readonly api: SessionTransport, private readonly effects: EffectExecutor,
    private readonly view: SessionViewPort, private readonly config: PublicConfig, options: ControllerOptions = {}) {
    this.factDrainTimeoutMs = options.factDrainTimeoutMs ?? FACT_DRAIN_TIMEOUT_MS;
    if (!Number.isSafeInteger(this.factDrainTimeoutMs) || this.factDrainTimeoutMs < 1 || this.factDrainTimeoutMs > 30000) {
      throw new RangeError('Fact drain timeout must be between 1 and 30000 milliseconds');
    }
    this.playback = (options.createPlayback ?? (settings => new CancelSafePlayback(settings)))({
      isAuthorized: origin => !this.closed && this.gate?.isAuthorized(origin) === true,
      onFact: fact => this.playbackFact(fact),
      onError: error => { if (!this.closed) this.view.error(error.message); },
      onAuditionState: state => { if (!this.closed) this.view.reviewAudition?.(state); },
    });
    this.capture = (options.createCapture ?? (settings => new MicrophoneCapture(settings)))({
      onChunk: chunk => this.captureChunk(chunk),
      onState: state => {
        const current = this.microphone;
        if (!current || !this.current(current.generation) || current.released) return;
        if (state === 'recording') { this.effects.setPhase?.('listening'); this.view.microphone?.('recording'); }
        else if (state === 'starting') this.view.microphone?.('starting');
      },
      onError: error => { if (this.microphone && !this.closed) this.fail(new Error(error.message)); },
    });
  }
  private current(generation: number): boolean { return !this.closed && this.running && generation === this.generation; }

  async connect(): Promise<void> {
    if (this.closed || this.running || this.connecting) return;
    this.connecting = true;
    const clientId = crypto.randomUUID();
    try {
      const created = await this.api.create(clientId, this.lifetime.signal);
      if (this.closed) { await this.api.close(); return; }
      this.gate = new PresentationGate(created.session.session_id, clientId);
      this.running = true;
      this.view.connected();
      this.install(created.session);
      void this.api.capabilities(this.lifetime.signal).then(value => {
        if (this.closed) return;
        this.capabilities = value;
        this.view.capabilities?.(value);
        this.startSpeech();
      }).catch(error => { if (!this.closed) this.report(error); });
      void this.poll();
    } catch (error) { if (!this.closed) { this.fail(error); throw error; } }
    finally { this.connecting = false; }
  }

  private install(snapshot: SessionView): void {
    const gate = this.gate;
    if (this.closed || !gate) return;
    if (this.snapshot && (snapshot.session_id !== this.snapshot.session_id
      || snapshot.client_instance_id !== this.snapshot.client_instance_id)) {
      this.fail(new Error('Session response identity mismatch. Local output was stopped.')); return;
    }
    try { if (!gate.install(snapshot)) return; }
    catch (error) { this.fail(error); return; }
    // Revocation is reconciled synchronously even when this snapshot belongs to an old activity.
    this.playback.reconcileAuthorization();
    this.cancelRevokedVisualPreparations();
    if (snapshot.activity_seq !== gate.currentActivity()) return;
    this.snapshot = snapshot;
    this.view.update(snapshot);
    if (snapshot.phase === 'error') { this.fail(new Error(safeSessionError(snapshot.last_error ?? 'generation_failed', snapshot.last_error_diagnostic_id))); return; }
    this.presentVisuals();
    this.startSpeech();
    if (!this.speech && !this.microphone && !this.rehearsalInput && snapshot.sealed && snapshot.phase === 'idle') this.effects.setPhase?.('idle');
  }

  private presentVisuals(): void {
    const gate = this.gate;
    if (!gate || !this.snapshot || this.closed) return;
    for (const effect of this.snapshot.active_grants) {
      if (effect.kind === 'speech' || !gate.allows(effect)) continue;
      if (effect.kind === 'media') this.prepareMediaEffect(effect, this.generation, gate);
      else this.applyVisualEffect(effect, this.generation, gate);
    }
  }

  private applyVisualEffect(effect: EffectView, generation: number, gate: PresentationGate): void {
    if (!this.current(generation) || this.gate !== gate || !gate.allows(effect)) return;
    try { this.effects.apply(effect); }
    catch (error) { this.fail(error); return; }
    // apply() is synchronous, but may re-enter application code. Revalidate before history.
    if (!this.current(generation) || this.gate !== gate || !gate.allows(effect)) return;
    const receipt = gate.consume(effect);
    if (receipt) this.enqueueFact(receipt, false, generation);
  }

  private prepareMediaEffect(effect: EffectView, generation: number, gate: PresentationGate): void {
    if (!this.current(generation) || this.gate !== gate || !gate.allows(effect)) return;
    if (this.visualPreparations.has(effect.id)) return;
    if (!this.effects.prepare || this.visualPreparations.size >= MEDIA_PREPARATION_LIMIT) {
      this.view.error(MEDIA_PREPARATION_ERROR);
      return;
    }
    const run: VisualPreparationRun = {effect, generation, gate, abort: new AbortController()};
    this.visualPreparations.set(effect.id, run);
    void this.finishMediaPreparation(run);
  }

  private async finishMediaPreparation(run: VisualPreparationRun): Promise<void> {
    const stillAuthorized = (): boolean => this.visualPreparations.get(run.effect.id) === run
      && !run.abort.signal.aborted && this.current(run.generation)
      && this.gate === run.gate && run.gate.allows(run.effect);
    try {
      await this.effects.prepare!(run.effect, run.abort.signal);
    } catch {
      if (stillAuthorized()) this.view.error(MEDIA_PREPARATION_ERROR);
      this.releaseVisualPreparation(run);
      return;
    }
    // Resource callbacks can be slow or ignore AbortSignal. Never let them revive old authority.
    if (!stillAuthorized()) { this.releaseVisualPreparation(run); return; }
    try {
      if (!stillAuthorized()) return;
      this.effects.apply(run.effect);
      if (!stillAuthorized()) return;
      const receipt = run.gate.consume(run.effect);
      if (receipt) this.enqueueFact(receipt, false, run.generation);
    } catch (error) {
      if (stillAuthorized()) this.fail(error);
    } finally { this.releaseVisualPreparation(run); }
  }

  private releaseVisualPreparation(run: VisualPreparationRun): void {
    if (this.visualPreparations.get(run.effect.id) === run) this.visualPreparations.delete(run.effect.id);
  }

  private cancelRevokedVisualPreparations(): void {
    for (const run of this.visualPreparations.values()) {
      if (run.generation !== this.generation || this.gate !== run.gate || !run.gate.allows(run.effect)) run.abort.abort();
    }
  }

  private cancelVisualPreparations(): void {
    // Keep uncooperative callbacks counted against the small cap until they actually settle.
    for (const run of this.visualPreparations.values()) run.abort.abort();
  }

  /** Block and physically disconnect before any network cancellation or new request. */
  private interrupt(reason: AudioStopReason): number {
    const generation = ++this.generation;
    // A barrier belongs to exactly one local turn. Stop, close, failure or a newer input
    // releases that waiter immediately, even if a transport ignores cancellation.
    this.generationAbort.abort();
    this.generationAbort = new AbortController();
    this.cancelVisualPreparations();
    this.rehearsalInput = null; this.view.rehearsalInput?.('stopped');
    this.gate?.block();
    const speech = this.speech;
    this.playback.stop(reason); // terminal fact is allocated before beginInput/stop captures cutoff
    speech?.abort.abort(); speech?.wake?.();
    this.speech = null;
    const microphone = this.microphone;
    this.microphone = null;
    this.capture.stop();
    microphone?.abort.abort(); microphone?.transport?.cancel();
    if (microphone) { microphone.queue.length = 0; microphone.queuedBytes = 0; }
    this.activityRequest?.abort(); this.activityRequest = null;
    this.view.microphone?.('stopped');
    return generation;
  }
  private unlock(generation: number): void {
    this.unlocked = false;
    void this.playback.unlock().then(ok => {
      if (!this.current(generation)) return;
      this.unlocked = ok;
      if (ok) this.startSpeech();
      else this.view.error('Audio could not start. Text input is still available; try again from a user gesture.');
    }).catch(error => { if (this.current(generation)) this.report(error); });
  }
  async input(text: string, sourceAudioStreamId?: string): Promise<SessionInputOutcome> {
    if (!text.trim()) return { status: 'ignored' };
    if (this.closed || !this.gate) return { status: 'closed' };
    const generation = this.interrupt('new-input');
    const generationSignal = this.generationAbort.signal;
    this.reportedError = null; this.view.error('');
    const id = crypto.randomUUID(), basis = this.gate.beginInput(id);
    const factSnapshot = this.captureFactSnapshot(basis.presentation_cutoff);
    this.effects.prepareInput();
    if (this.capabilities?.speech_enabled !== false) this.unlock(generation); // invoked in the gesture, never after a fetch/permission await
    const drain = await this.drainFactSnapshot(factSnapshot, generation, generationSignal);
    if (drain === 'closed' || this.closed) return { status: 'closed' };
    if (drain === 'superseded' || !this.current(generation)) return { status: 'superseded' };
    if (drain !== 'saved') {
      this.fail(new Error(drain === 'timeout' ? FACT_HISTORY_TIMEOUT : FACT_HISTORY_FAILED));
      return { status: 'not-sent', text, reason: drain === 'timeout' ? 'history-timeout' : 'history-failed' };
    }
    const abort = new AbortController(); this.activityRequest = abort;
    try {
      const snapshot = await this.api.input({...basis, request_id: id, text,
        ...(sourceAudioStreamId && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sourceAudioStreamId)
          ? {source_audio_stream_id: sourceAudioStreamId} : {})}, abort.signal);
      if (this.current(generation)) { this.install(snapshot); return { status: 'submitted' }; }
      return this.closed ? { status: 'closed' } : { status: 'superseded' };
    } catch (error) {
      if (this.current(generation) && error instanceof MiraHttpError
        && error.status === 409 && error.code === 'history_pending') {
        this.fail(new Error('上一轮可见内容尚未确认保存；本次输入未送出。请等待状态更新后重试。'));
        return {status: 'not-sent', text, reason: 'history-pending'};
      }
      if (this.current(generation)) { this.fail(error); return { status: 'unknown' }; }
      return this.closed ? { status: 'closed' } : { status: 'superseded' };
    } finally { if (this.activityRequest === abort) this.activityRequest = null; }
  }
  async stop(): Promise<void> {
    if (!this.gate || this.closed) return;
    const generation = this.interrupt('stop');
    this.reportedError = null; this.view.error('');
    const basis = this.gate.stop();
    this.effects.stop(); this.view.localStop();
    const abort = new AbortController(); this.activityRequest = abort;
    try {
      const snapshot = await this.api.stop(basis, abort.signal);
      if (this.current(generation)) this.install(snapshot);
    } catch (error) { if (this.current(generation)) this.fail(error); }
    finally { if (this.activityRequest === abort) this.activityRequest = null; }
  }

  private startSpeech(): void {
    const gate = this.gate;
    if (this.closed || !this.running || !this.unlocked || !this.capabilities?.speech_enabled
      || !gate || this.speech || this.microphone || this.rehearsalInput || !this.snapshot) return;
    const effect = this.snapshot.active_grants.find(value => value.kind === 'speech' && gate.allows(value));
    if (!effect || !gate.claimSpeech(effect)) return;
    const run: SpeechRun = {effect, generation: this.generation, abort: new AbortController(), handle: null, accepted: 0, rendered: 0, wake: null};
    this.speech = run;
    run.handle = this.playback.open(effect);
    if (!run.handle) { this.fail(new Error('Audio grant could not start. Use text input.')); return; }
    void this.api.speech(effect, run.abort.signal, async pcm => {
      // Read one packet at a time and pace it against naturally ended software samples.
      while (run.accepted - run.rendered + pcm.length > 96000) {
        if (!this.activeSpeech(run)) throw new Error('Speech cancelled');
        await new Promise<void>(resolve => { run.wake = resolve; });
      }
      if (!this.activeSpeech(run) || !run.handle!.push(pcm)) throw new Error('Speech playback stopped');
      run.accepted += pcm.length;
    }).then(() => {
      if (this.activeSpeech(run) && !run.handle!.finish()) this.fail(new Error('Speech did not complete. Use text input.'));
    }).catch(error => { if (this.activeSpeech(run)) this.fail(error); });
  }
  private activeSpeech(run: SpeechRun): boolean {
    return this.speech === run && this.current(run.generation) && !run.abort.signal.aborted && this.gate?.isAuthorized(run.effect) === true;
  }
  private playbackFact(fact: PlaybackFact): void {
    const run = this.speech;
    const progress = this.gate?.audioProgress(fact);
    if (progress && !this.closed) this.enqueueFact(progress, true, run?.generation ?? this.generation);
    if (!run || run.effect.id !== fact.origin.id || run.effect.digest !== fact.origin.digest) return;
    if (fact.stage === 'rendered') { run.rendered = fact.renderedFrames; run.wake?.(); run.wake = null; }
    if (fact.stage === 'submitted' && this.activeSpeech(run)) {
      if (this.gate?.submitSpeech(fact)) this.presentVisuals();
      this.effects.setPhase?.('speaking');
    }
    if (fact.stage === 'completed' || fact.stage === 'stopped' || fact.stage === 'failed') {
      this.speech = null; run.abort.abort(); run.wake?.(); run.wake = null;
      if (!this.current(run.generation)) return;
      this.effects.setPhase?.(this.microphone ? 'listening' : 'idle');
      if (fact.stage === 'failed' || fact.reason === 'error') this.fail(new Error('Audio failed. Text input is still available.'));
      else if (fact.stage === 'completed') queueMicrotask(() => { if (this.current(run.generation)) this.startSpeech(); });
    }
  }
  private captureFactSnapshot(presentationCutoff: number): FactSnapshot {
    const throughSequence = this.factSequence;
    return {
      throughSequence,
      presentationCutoff,
      pending: [...this.factDeliveries.values()].filter(delivery =>
        delivery.sequence <= throughSequence && delivery.presentationSequence <= presentationCutoff),
    };
  }

  private noteFailedFact(sequence: number, presentationSequence: number): void {
    if (this.failedFact === null || sequence < this.failedFact.sequence) {
      this.failedFact = { sequence, presentationSequence };
    }
  }

  private async drainFactSnapshot(snapshot: FactSnapshot, generation: number,
      signal: AbortSignal): Promise<FactDrainResult> {
    if (this.closed) return 'closed';
    if (!this.current(generation) || signal.aborted) return 'superseded';
    if (this.failedFact !== null && this.failedFact.sequence <= snapshot.throughSequence
      && this.failedFact.presentationSequence <= snapshot.presentationCutoff) return 'failed';
    if (snapshot.pending.length === 0) return 'saved';

    return new Promise<FactDrainResult>(resolve => {
      let settled = false;
      let remaining = snapshot.pending.length;
      const timer = setTimeout(() => finish('timeout'), this.factDrainTimeoutMs);
      const onAbort = (): void => finish(this.closed ? 'closed' : 'superseded');
      const finish = (result: FactDrainResult): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        signal.removeEventListener('abort', onAbort);
        resolve(result);
      };
      signal.addEventListener('abort', onAbort, { once: true });
      if (signal.aborted) { onAbort(); return; }
      for (const delivery of snapshot.pending) {
        void delivery.acknowledgement.then(ack => {
          if (settled) return;
          if (ack.status === 'failed') { finish('failed'); return; }
          if (ack.status === 'closed') { finish(this.closed ? 'closed' : 'failed'); return; }
          if (--remaining === 0) {
            finish(this.failedFact !== null && this.failedFact.sequence <= snapshot.throughSequence
              && this.failedFact.presentationSequence <= snapshot.presentationCutoff
              ? 'failed' : 'saved');
          }
        });
      }
    });
  }

  private enqueueFact(fact: ReceiptRequest | AudioProgressRequest, audio: boolean, generation = this.generation): void {
    const sequence = ++this.factSequence;
    if (++this.pendingFacts > 4096) {
      this.pendingFacts--;
      this.noteFailedFact(sequence, fact.presentation_seq);
      this.fail(new Error('Presentation history delivery is full. Close and create a new session.'));
      return;
    }
    // Keep terminal audio behind earlier rendered counters. Each acknowledgement retains its
    // immutable issue sequence, presentation sequence and owning local generation.
    const acknowledgement = this.facts.then(async (): Promise<FactAcknowledgement> => {
      try {
        if (this.closed) return { sequence, status: 'closed' };
        if (audio) await this.api.audioProgress(fact as AudioProgressRequest);
        else await this.api.receipt(fact);
        return { sequence, status: 'saved' };
      } catch (error) {
        this.noteFailedFact(sequence, fact.presentation_seq);
        if (this.current(generation)) this.fail(error);
        // Preserve the new activity's actionable failure/locator, if it has one.
        else if (!this.closed && this.reportedError === null) this.view.error('An earlier presentation fact could not be saved. History may be incomplete.');
        return { sequence, status: 'failed' };
      } finally { this.pendingFacts--; }
    });
    this.facts = acknowledgement.then(() => undefined);
    const delivery: FactDelivery = {
      sequence,
      presentationSequence: fact.presentation_seq,
      generation,
      acknowledgement,
    };
    this.factDeliveries.set(sequence, delivery);
    void acknowledgement.then(() => {
      if (this.factDeliveries.get(sequence) === delivery) this.factDeliveries.delete(sequence);
    });
  }

  /** User-controlled fixed input rehearsal. No capture, STT, PCM input or speech-recognition claim. */
  async startRehearsalInput(): Promise<void> {
    if (!this.gate || this.closed || this.rehearsalInput
      || this.capabilities?.generation_mode !== 'rehearsal'
      || this.capabilities.qualification !== 'offline_fixture') return;
    const generation = this.interrupt('new-input');
    this.reportedError = null; this.view.error('');
    const basis = this.gate.stop();
    this.effects.stop(); this.effects.setPhase?.('listening');
    this.unlock(generation);
    const run: RehearsalInputRun = {generation, ready: Promise.resolve(), released: false};
    this.rehearsalInput = run; this.view.rehearsalInput?.('listening');
    const abort = new AbortController(); this.activityRequest = abort;
    run.ready = this.api.stop(basis, abort.signal).then(snapshot => {
      if (!this.current(generation) || this.rehearsalInput !== run) return;
      if (snapshot.activity_seq !== basis.activity_seq) throw new Error('Rehearsal input was superseded');
      this.install(snapshot);
    }).catch(error => { if (this.current(generation) && this.rehearsalInput === run) this.fail(error); })
      .finally(() => { if (this.activityRequest === abort) this.activityRequest = null; });
    await run.ready;
  }
  async finishRehearsalInput(): Promise<SessionInputOutcome | undefined> {
    const run = this.rehearsalInput;
    if (!run || run.released || !this.current(run.generation)) return;
    run.released = true;
    this.effects.setPhase?.('thinking');
    await run.ready;
    if (this.rehearsalInput !== run || !this.current(run.generation)) return;
    this.rehearsalInput = null; this.view.rehearsalInput?.('stopped');
    return this.input('照片里有什么');
  }

  async startMicrophone(): Promise<void> {
    if (!this.gate || this.closed || this.microphone) return;
    if (!this.capabilities?.microphone_enabled) { this.view.error('Microphone recognition is not configured. Use text input.'); return; }
    const generation = this.interrupt('new-input');
    this.reportedError = null; this.view.error('');
    const basis = this.gate.stop();
    this.effects.prepareInput();
    this.unlock(generation);
    const streamId = crypto.randomUUID();
    const run: MicrophoneRun = {generation, streamId, abort: new AbortController(), queue: [], queuedBytes: 0,
      released: false, transport: null, setup: Promise.resolve(), finishing: null};
    this.microphone = run;
    this.activityRequest = run.abort;
    // Start capture synchronously under the user's gesture, before awaiting the stop acknowledgement.
    const starting = this.capture.start();
    run.setup = this.api.stop(basis, run.abort.signal).then(snapshot => {
      if (!this.activeMicrophone(run)) return;
      if (snapshot.activity_seq !== basis.activity_seq) throw new Error('Microphone stop acknowledgement was superseded');
      this.install(snapshot);
      if (!this.activeMicrophone(run)) return;
      const transport = this.api.microphone({stream_id: streamId, activity_seq: snapshot.activity_seq, input_epoch: snapshot.input_epoch}, run.abort.signal);
      run.transport = transport;
      void transport.completion.catch(error => { if (this.activeMicrophone(run)) this.fail(error); });
      for (const chunk of run.queue) transport.send(chunk);
      run.queue.length = 0; run.queuedBytes = 0;
      return transport.ready;
    }).catch(error => { if (this.activeMicrophone(run)) this.fail(error); });
    const started = await starting;
    if (!started && this.activeMicrophone(run) && !run.released) this.fail(new Error('Microphone did not start. Use text input.'));
  }
  private activeMicrophone(run: MicrophoneRun): boolean {
    return this.microphone === run && this.current(run.generation) && !run.abort.signal.aborted;
  }
  private captureChunk(chunk: CapturedAudio): void {
    const run = this.microphone;
    if (!run || !this.activeMicrophone(run) || run.released) throw new Error('Microphone cancelled');
    if (run.transport) { run.transport.send(chunk); return; }
    if (run.queue.length >= 100 || run.queuedBytes + chunk.pcm16le.length > 65536) throw new Error('Microphone startup queue exceeded its bound');
    run.queue.push({...chunk, pcm16le: chunk.pcm16le.slice()}); run.queuedBytes += chunk.pcm16le.length;
  }
  async finishMicrophone(): Promise<SessionInputOutcome | undefined> {
    const run = this.microphone;
    if (!run || !this.activeMicrophone(run)) return;
    if (run.finishing) return run.finishing;
    run.released = true;
    this.capture.stop(); this.view.microphone?.('finishing'); this.effects.setPhase?.('thinking');
    run.finishing = (async (): Promise<SessionInputOutcome | undefined> => {
      await run.setup;
      if (!this.activeMicrophone(run) || !run.transport) return;
      const result = await run.transport.finish();
      if (!this.activeMicrophone(run)) return;
      this.microphone = null; run.abort.abort(); this.view.microphone?.('stopped');
      const text = result.text.trim();
      const noise = /^\[(?:noise|silence|inaudible|music|静音|噪音)\]$/i.test(text);
      if (!result.had_final || !text || noise || !/[\p{L}\p{N}]/u.test(text)) {
        if (this.activityRequest === run.abort) this.activityRequest = null;
        this.effects.setPhase?.('idle');
        this.view.error('No reliable speech was recognized. Try again or use text input.');
        return;
      }
      if (this.activityRequest === run.abort) this.activityRequest = null;
      const sourceStreamId = await this.reviewedAudioSourceForInput(run.streamId, result.had_final);
      if (!this.current(run.generation)) return this.closed ? {status: 'closed'} : {status: 'superseded'};
      return this.input(text, sourceStreamId);
    })().catch(error => { if (this.activeMicrophone(run)) this.fail(error); return undefined; });
    return run.finishing;
  }

  private async reviewedAudioSourceForInput(streamId: string, hadFinal: boolean): Promise<string | undefined> {
    if (!hadFinal || !this.api.reviewedAudioStatus) return undefined;
    const generation = this.generation;
    const localAbort = new AbortController();
    const signal = AbortSignal.any([this.generationAbort.signal, localAbort.signal]);
    this.activityRequest = localAbort;
    try {
      const status = await this.api.reviewedAudioStatus(signal);
      if (!this.current(generation) || signal.aborted || !status.recording_active || status.input_completion_ready !== true
        || status.pending_kind !== 'audio_input' || status.pending_stream_id !== streamId) return undefined;
      return streamId;
    } catch {
      // A raw-audio staging failure must never block a valid final transcript.
      return undefined;
    } finally { if (this.activityRequest === localAbort) this.activityRequest = null; }
  }

  /** May audition only when ordinary generation, capture, presentation, and playback are idle. */
  canAuditionReviewedAudio(): boolean {
    const snapshot = this.snapshot;
    return !this.closed && this.running && snapshot !== null && snapshot.sealed
      && snapshot.active_grants.length === 0 && snapshot.phase !== 'thinking'
      && !this.speech && !this.microphone && !this.rehearsalInput
      && this.visualPreparations.size === 0 && this.activityRequest === null && this.playback.quiescent;
  }

  async auditionReviewedAudio(pcm16le: Uint8Array, sampleRateHz: number): Promise<boolean> {
    if (!this.canAuditionReviewedAudio()) {
      this.view.error('Wait until MIRA’s response, microphone capture, and scene preparation have finished before auditioning reviewed audio.');
      return false;
    }
    if (!(pcm16le instanceof Uint8Array) || pcm16le.byteLength < 2 || pcm16le.byteLength > 512 * 1024
      || pcm16le.byteLength % 2 !== 0 || ![16000, 24000, 48000].includes(sampleRateHz)) {
      this.view.error('The reviewed audio does not match the supported bounded PCM format.');
      return false;
    }
    const samples = new Int16Array(pcm16le.byteLength / 2);
    const view = new DataView(pcm16le.buffer, pcm16le.byteOffset, pcm16le.byteLength);
    for (let i = 0; i < samples.length; i++) samples[i] = view.getInt16(i * 2, true);
    return this.playback.audition(samples, sampleRateHz);
  }

  stopReviewedAudioAudition(): void { this.playback.stopAudition(); }

  private async poll(): Promise<void> {
    if (!this.running || this.closed) return;
    const generation = this.generation, abort = new AbortController();
    this.pollRequest = abort;
    try {
      const snapshot = await this.api.snapshot(abort.signal);
      if (this.current(generation)) this.install(snapshot);
    } catch (error) { if (this.current(generation)) this.fail(error); }
    finally {
      if (this.pollRequest === abort) this.pollRequest = null;
      if (this.running && !this.closed) this.pollTimer = setTimeout(() => { this.pollTimer = null; void this.poll(); }, this.config.pollIntervalMs);
    }
  }
  private report(error: unknown): void {
    this.reportedError = error instanceof Error ? error.message : 'Transport unavailable. Use text input.';
    this.view.error(this.reportedError);
  }
  private fail(error: unknown): void {
    if (this.closed) return;
    this.interrupt('error'); this.effects.stop(); this.report(error);
  }
  close(): Promise<void> {
    if (this.closePromise) return this.closePromise;
    this.closed = true; this.running = false;
    this.interrupt('close'); this.effects.stop(); this.lifetime.abort();
    this.pollRequest?.abort(); this.pollRequest = null;
    if (this.pollTimer !== null) { clearTimeout(this.pollTimer); this.pollTimer = null; }
    this.closePromise = Promise.allSettled([this.capture.close(), this.playback.close(), this.api.close()]).then(results => {
      if (results.some(result => result.status === 'rejected')) this.view.error('Local resources closed; server cleanup could not be confirmed.');
    });
    return this.closePromise;
  }
}
