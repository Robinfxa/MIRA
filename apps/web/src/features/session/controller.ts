import { createClientId } from '../../shared/client-id.js';
import type { PublicConfig } from '../../shared/config.js';
import type { AudioProgressRequest, EffectView, ReceiptRequest, PhotoDismissRequest, SessionView, FixedPhotoProgressRequest, FixedPhotoView } from '../../shared/generated/contracts.js';
import { CancelSafePlayback, MicrophoneCapture } from '../audio/index.js';
import type { PlaybackOptions, CaptureOptions, AudioStopReason, CapturedAudio, PlaybackFact, PlaybackStream } from '../audio/index.js';
import type { EffectExecutor } from '../presentation/ports.js';
import { safeSessionError } from '../diagnostics/status.js';
import { PresentationGate } from '../presentation/permit-gate.js';
import { generatedPhotoIdentity } from '../../shared/photo-value.js';
import {isChapterEffect} from '../presentation/chapter-presentation.js';
import { MiraHttpError } from './api-client.js';
import { classifyUnexpectedAbort } from './transport-errors.js';
import type { MicrophoneStream, MicrophoneTimingSnapshot, MicrophoneTranscriptRevision,
  SessionTransport, SessionInputRequest, VoiceCapabilities } from './ports.js';

export interface SessionViewPort {
  connected(): void;
  update(view: SessionView, local?: { readonly expectedReplyInterruption: boolean }): void;
  error(message: string): void;
  /** Page-only chat facts: never drafts, unconfirmed inputs or unconsumed grants. */
  inputAccepted?(text: string, requestId: string): void;
  visualPresented?(effect: EffectView): void;
  /** Nonfatal, turn-scoped status that is separate from the actionable error surface. */
  systemNotice?(notice: { readonly label: string; readonly body: string } | null): void;
  /** Optional image progress/failure does not replace ordinary reply status. */
  fixedPhotoStatus?(message: string | null, dismissible: boolean): void;
  storyImageStatus?(message: string | null, dismissible: boolean): void;
  localStop(): void;
  capabilities?(value: VoiceCapabilities): void;
  outputPreference?(muted: boolean, mode: 'voice' | 'text_only', pending: boolean): void;
  rehearsalInput?(state: 'listening' | 'stopped'): void;
  microphone?(state: 'starting' | 'recording' | 'finishing' | 'stopped'): void;
  /** User input in progress; always separate from assistant subtitle and composer. */
  microphonePreview?(revision: MicrophoneTranscriptRevision | null): void;
  /** Ephemeral numeric-only browser clock observations for this stream. */
  microphoneTiming?(timing: MicrophoneTimingSnapshot | null): void;
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
  /** Reading dwell for explicitly chunked captions; never speech alignment. */
  readonly captionDwellMs?: number;
  /** A separate continuous capture is not tied to reply generation, but Stop/error/Close release it. */
  readonly onGlobalStop?: (reason: AudioStopReason) => void;
  /** Independent capture owners use this to block PTT and raw-audio audition overlap. */
  readonly externalMicrophoneActive?: () => boolean;
  /** Bounded local quiet gate for first reply dispatch only; no extra playback owner. */
  readonly waitForReplyQuiet?: (signal: AbortSignal) => Promise<boolean>;
  readonly userInputPending?: () => boolean;
}
/** Local object identity binds reviewed recovery to one session/turn, never ASR authority. */
export interface SessionContinuationTarget {
  readonly sessionId: string;
  readonly requestId: string;
  readonly outputEpoch: number;
  readonly activitySeq: number;
}
export type SessionInputOutcome =
  | { readonly status: 'submitted' }
  | { readonly status: 'not-sent'; readonly text: string; readonly reason: 'history-failed' | 'history-timeout' | 'history-pending' | 'continuation-stale' | 'cancelled-before-dispatch' }
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
  submitted: boolean;
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
  readonly timingOriginMs: number;
  readonly abort: AbortController;
  readonly queue: CapturedAudio[];
  queuedBytes: number;
  released: boolean;
  transport: MicrophoneStream | null;
  setup: Promise<void>;
  finishing: Promise<SessionInputOutcome | undefined> | null;
  lastPreviewRevision: number;
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
const VISUAL_PREPARATION_LIMIT = 4;
const MEDIA_PREPARATION_ERROR = '旅行插画暂时无法显示，请稍后重试或继续聊天。';
const VISUAL_PREPARATION_ERROR = '场景暂时无法更新，请稍后重试或继续聊天。';
const FACT_DRAIN_TIMEOUT_MS = 1500;
const FACT_HISTORY_FAILED = 'Earlier presentation history could not be confirmed, so this input was not sent. Start a fresh session before continuing.';
const FACT_HISTORY_TIMEOUT = 'Earlier presentation history is still waiting to be saved, so this input was not sent. Wait briefly, then retry.';
const REVIEW_UNCERTAIN_NOTICE = '这部分我还不确定，先跳过。你可以补充说明，或继续聊。';
// Mirrors the server's conservative explicit-enable aliases. Quoted, negated,
// conditional, model-authored and unrecognized text cannot release a local latch.
const VOICE_ENABLE_COMMANDS = new Set(['取消静音', '可以开声音', '开启声音', '打开声音',
  '恢复语音', '可以说话了', '现在可以说话了', 'unmute', 'enable voice', 'turn on voice']);
function explicitVoiceEnable(text: string): boolean {
  const command = text.trim().toLowerCase().replace(/[。.!！ ]+$/u, '').replace(/^请/u, '');
  return VOICE_ENABLE_COMMANDS.has(command);
}

/** One gate, one playback sink and one microphone. Every continuation carries local causality. */
export class SessionController {
  private reportedError: string | null = null;
  private reviewUncertainNoticeKey: string | null = null;
  private legacySystemNoticeActive = false;
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
  /** Attempts are scoped to the current locally interrupted turn and suppress poll retries. */
  private readonly attemptedVisualPreparations = new Set<string>();
  private readonly capacityDeferredVisuals = new Set<string>();
  private speech: SpeechRun | null = null;
  private localOutputMuted = false;
  private unconfirmedLocalMute = false;
  private localMuteBaseRevision = 0;
  private responseIntentSequence = 0;
  private speechBlockedThroughIntent = 0;
  private speechMutedThroughEpoch = 0;
  private responseInputIntent: {requestId: string; sequence: number; enableVoice: boolean} | null = null;
  private preferenceRevision = 0;
  private preferenceWrite: Promise<void> | null = null;
  get outputMuted(): boolean { return this.localOutputMuted; }
  private interruptedReply: SessionContinuationTarget | null = null;
  private handledTerminalError: string | null = null;
  private continuationTarget: SessionContinuationTarget | null = null;
  private continuationBlockedThroughActivity = -1;
  private microphone: MicrophoneRun | null = null;
  private rehearsalInput: RehearsalInputRun | null = null;
  private unlocked = false;
  private facts: Promise<void> = Promise.resolve();
  private pendingFacts = 0;
  private photoVisibilityRevision = 0;
  private chapterChoiceActivity: number | null = null;
  private photoDismissedThroughActivity = -1;
  private photoDismissal: Promise<void> | null = null;
  private localFixedPhoto: {effect: EffectView; state: NonNullable<FixedPhotoView['state']>} | null = null;
  private fixedPhotoReport: Promise<void> = Promise.resolve();
  private fixedPhotoReportsPending = 0;
  private imageFailureActivity = -1;
  private imagePresentedActivity = -1;
  private imageDismissedThroughActivity = -1;
  private displayedPhoto: EffectView | null = null;
  private photoDismissalKey: string | null = null;
  private readonly hiddenImageJobs = new Set<string>();
  private imageCompletionWait: AbortController | null = null;
  private readonly imageCompletionAttempts = new Set<string>();
  private factSequence = 0;
  private failedFact: FailedFact | null = null;
  private readonly factDeliveries = new Map<number, FactDelivery>();
  private readonly factDrainTimeoutMs: number;
  private readonly captionDwellMs: number;
  private captionTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly captionQueue = new Map<string, {nextIndex: number; end: number; readyAt: number}>();
  private readonly onGlobalStop: ((reason: AudioStopReason) => void) | undefined;
  private readonly externalMicrophoneActive: () => boolean;
  private closePromise: Promise<void> | null = null;
  get microphoneBusy(): boolean { return this.microphone !== null || this.rehearsalInput !== null; }
  /** Software ownership only, not acoustic silence; unknown/closed owners remain busy. */
  get replyPlaybackBusy(): boolean {
    return this.closed || !this.running || this.speech !== null || this.playback.quiescent !== true;
  }

  /** Submitted playback only; fetched/queued PCM awaiting source.start has made no sound. */
  get replyPcmBusy(): boolean {
    if (this.closed || !this.running) return true;
    return this.speech ? this.speech.submitted : this.playback.quiescent !== true;
  }

  constructor(private readonly api: SessionTransport, private readonly effects: EffectExecutor,
    private readonly view: SessionViewPort, private readonly config: PublicConfig, private readonly options: ControllerOptions = {}) {
    this.factDrainTimeoutMs = options.factDrainTimeoutMs ?? FACT_DRAIN_TIMEOUT_MS;
    this.captionDwellMs = options.captionDwellMs ?? 800;
    if (!Number.isSafeInteger(this.captionDwellMs) || this.captionDwellMs < 1 || this.captionDwellMs > 3000) {
      throw new RangeError('Caption dwell must be between 1 and 3000 milliseconds');
    }
    this.onGlobalStop = options.onGlobalStop;
    this.externalMicrophoneActive = options.externalMicrophoneActive ?? (() => false);
    if (!Number.isSafeInteger(this.factDrainTimeoutMs) || this.factDrainTimeoutMs < 1 || this.factDrainTimeoutMs > 30000) {
      throw new RangeError('Fact drain timeout must be between 1 and 30000 milliseconds');
    }
    this.playback = (options.createPlayback ?? (settings => new CancelSafePlayback(settings)))({
      isAuthorized: origin => !this.closed && !this.localOutputMuted && this.snapshot?.response_mode !== 'text_only'
        && origin.output_epoch > this.speechMutedThroughEpoch
        && this.gate?.isAuthorized(origin) === true,
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
    try {
      const clientId = createClientId();
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

  private install(snapshot: SessionView, acceptedInput?: {readonly text: string; readonly requestId: string}): void {
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
    this.effects.reconcilePhoto?.(snapshot);
    this.snapshot = snapshot;
    this.effects.reconcileChapter?.(snapshot);
    // Ordinary snapshots/capabilities cannot release a locally latched mute. A
    // newer preference revision records an explicit user change on the server.
    this.reconcileOutputPreference();
    const inputIntent = this.responseInputIntent;
    if (this.localOutputMuted || snapshot.response_mode === 'text_only'
      || (inputIntent?.requestId === snapshot.request_id && inputIntent.sequence <= this.speechBlockedThroughIntent)) {
      this.speechMutedThroughEpoch = Math.max(this.speechMutedThroughEpoch, snapshot.output_epoch);
    }
    this.view.outputPreference?.(this.localOutputMuted, snapshot.response_mode ?? 'voice', this.preferenceWrite !== null);
    this.playback.reconcileAuthorization();
    this.photoVisibilityRevision = Math.max(this.photoVisibilityRevision, snapshot.photo_visibility_revision ?? 0);
    if (acceptedInput && snapshot.request_id === acceptedInput.requestId) {
      try { this.view.inputAccepted?.(acceptedInput.text, acceptedInput.requestId); }
      catch { /* A page-only projection must not change accepted input or presentation authority. */ }
    }
    // The server keeps terminal audio interruption in its factual state. Qualify
    // only our own explicit local cancellation; never hide an unexpected failure.
    const expectedReplyInterruption = snapshot.last_error === 'audio_interrupted'
      && this.interruptedReply !== null
      && snapshot.output_epoch === this.interruptedReply.outputEpoch
      && snapshot.activity_seq === this.interruptedReply.activitySeq
      && (snapshot.request_id === null || snapshot.request_id === this.interruptedReply.requestId);
    this.view.update(snapshot, {expectedReplyInterruption});
    this.updateStoryImageStatus(snapshot);
    this.updateFixedPhotoStatus(snapshot);
    if (expectedReplyInterruption) {this.presentVisuals();return;}
    if (snapshot.phase === 'error') {
      if (snapshot.last_error === 'review_uncertain') {
        this.handledTerminalError = null; this.showReviewUncertainNotice(snapshot);
      }
      else {
        const code = snapshot.last_error ?? 'generation_failed';
        const identity = JSON.stringify([snapshot.session_id, snapshot.activity_seq, snapshot.output_epoch,
          code, snapshot.last_error_diagnostic_id ?? null]);
        const error = new Error(safeSessionError(code, snapshot.last_error_diagnostic_id));
        // A terminal poll keeps its explanation visible, but must not stop a microphone
        // that the user explicitly restarted after this same failure was handled.
        if (identity === this.handledTerminalError) this.report(error);
        else { this.handledTerminalError = identity; this.fail(error); }
      }
      return;
    }
    this.handledTerminalError = null;
    if (snapshot.last_error) this.report(new Error(safeSessionError(snapshot.last_error, snapshot.last_error_diagnostic_id)));
    this.presentVisuals();
    this.startSpeech();
    this.maybeCompleteImage();
    if (!this.speech && !this.microphone && !this.rehearsalInput && !this.externalMicrophoneActive()
      && snapshot.sealed && snapshot.phase === 'idle') this.effects.setPhase?.('idle');
  }

  private captionReady(effect: EffectView, generation: number, gate: PresentationGate): boolean {
    if (effect.id===this.snapshot?.story_image?.completion_effect_id && this.imagePresentationBusy()) return false;
    const chunk = effect.caption_chunk;
    if (!chunk) return true;
    const previous = this.captionQueue.get(chunk.group_id);
    if (chunk.index === 0) return previous === undefined;
    if (!previous || previous.nextIndex !== chunk.index || previous.end !== chunk.start) return false;
    const remaining = previous.readyAt - performance.now();
    if (remaining <= 0) return true;
    if (this.captionTimer === null) {
      this.captionTimer = setTimeout(() => {
        this.captionTimer = null;
        if (this.current(generation) && this.gate === gate) this.drainVisuals(generation, gate);
      }, remaining);
    }
    return false;
  }

  private noteCaptionPresented(effect: EffectView): void {
    const chunk = effect.caption_chunk;
    if (chunk) this.captionQueue.set(chunk.group_id, {nextIndex: chunk.index + 1,
      end: chunk.end, readyAt: performance.now() + this.captionDwellMs});
  }

  private presentVisuals(): void {
    const gate = this.gate;
    if (!gate || !this.snapshot || this.closed) return;
    this.drainVisuals(this.generation, gate);
  }

  /**
   * Optional visual actions serialize through resource readiness, rendered completion
   * and receipt allocation. Completion-aware executors let authorized captions progress
   * independently while preserving their own cue, order and reading dwell.
   */
  private drainVisuals(generation: number, gate: PresentationGate): void {
    const snapshot = this.snapshot;
    if (!snapshot || !this.current(generation) || this.gate !== gate) return;
    // Completion-aware executors can update captions without changing pending camera
    // geometry. Keep cue/chunk ordering, but never put speech text behind an optional action.
    const independentCaptions = this.effects.present !== undefined;
    if (independentCaptions && ![...this.visualPreparations.values()].some(run =>
      run.effect.kind === 'subtitle' && run.generation === generation && !run.abort.signal.aborted)) {
      for (const effect of snapshot.active_grants) {
        if (effect.kind !== 'subtitle' || !gate.allows(effect)) continue;
        if (!this.captionReady(effect, generation, gate)) break;
        if (this.visualPreparations.has(effect.id)) break;
        if (this.attemptedVisualPreparations.has(effect.id)) continue;
        // Reserve one bounded text slot even if old optional callbacks ignore abort.
        if (this.visualPreparations.size >= VISUAL_PREPARATION_LIMIT + 1) break;
        this.attemptedVisualPreparations.add(effect.id);
        const run: VisualPreparationRun = {effect, generation, gate, abort: new AbortController()};
        this.visualPreparations.set(effect.id, run);
        void this.finishVisualPreparation(run);
        break;
      }
    }
    // Do not let a later grant pass a preparation already in flight. A formerly
    // ineligible cue caption can become authorized by actual audio submission while a
    // later scene is preparing; cancel that later staging so the earlier grant goes first.
    for (const run of this.visualPreparations.values()) {
      if (run.generation !== generation || run.gate !== gate || run.abort.signal.aborted
        || !gate.allows(run.effect) || (independentCaptions && run.effect.kind === 'subtitle')) continue;
      const runIndex = snapshot.active_grants.findIndex(effect => effect.id === run.effect.id);
      const earlierEligible = runIndex > 0 && snapshot.active_grants.slice(0, runIndex).some(effect =>
        effect.kind !== 'speech' && (!independentCaptions || effect.kind !== 'subtitle')
          && gate.allows(effect) && !this.attemptedVisualPreparations.has(effect.id));
      if (!earlierEligible) return;
      run.abort.abort();
      this.attemptedVisualPreparations.delete(run.effect.id);
    }

    for (const effect of snapshot.active_grants) {
      // Cue-dependent captions stay out of the ordered queue until real source submission.
      if (effect.kind === 'speech' || (independentCaptions && effect.kind === 'subtitle') || !gate.allows(effect)) continue;
      if (!this.captionReady(effect, generation, gate)) return;
      if (generatedPhotoIdentity(effect.value) && this.imagePresentationBusy()) continue;
      const existing = this.visualPreparations.get(effect.id);
      if (existing) {
        // An aborted old-turn callback with a reused id still owns that attempt until it
        // settles. Its finally block will resume this drain without overlapping resources.
        return;
      }
      if (effect.kind === 'media' && !this.effects.prepare) {
        if (!this.attemptedVisualPreparations.has(effect.id)) {
          this.attemptedVisualPreparations.add(effect.id);
          this.reportVisualPreparationFailure(effect, 'preparation_failed');
        }
        continue;
      }
      if (this.effects.prepare || this.effects.present) {
        if (this.attemptedVisualPreparations.has(effect.id)) continue;
        if (this.capacityDeferredVisuals.has(effect.id)) return;
        if (this.visualPreparations.size >= VISUAL_PREPARATION_LIMIT) {
          this.capacityDeferredVisuals.add(effect.id);
          this.view.error(effect.kind === 'media' ? MEDIA_PREPARATION_ERROR : VISUAL_PREPARATION_ERROR);
          return;
        }
        this.capacityDeferredVisuals.delete(effect.id);
        this.attemptedVisualPreparations.add(effect.id);
        const run: VisualPreparationRun = {effect, generation, gate, abort: new AbortController()};
        this.visualPreparations.set(effect.id, run);
        void this.finishVisualPreparation(run);
        return;
      }
      this.applyVisualEffect(effect, generation, gate);
      if (!this.current(generation) || this.gate !== gate) return;
    }
  }

  private applyVisualEffect(effect: EffectView, generation: number, gate: PresentationGate): void {
    if (!this.current(generation) || this.gate !== gate || !gate.allows(effect)) return;
    try { this.effects.apply(effect); }
    catch (error) {
      if (effect.kind === 'media' && effect.value === 'trip_photo') this.reportVisualPreparationFailure(effect, 'presentation_failed');
      else this.fail(error);
      return;
    }
    this.completeVisualEffect(effect, generation, gate);
  }

  private completeVisualEffect(effect: EffectView, generation: number, gate: PresentationGate): void {
    // A visual commit can re-enter application code; completion never grants authority.
    if (!this.current(generation) || this.gate !== gate || !gate.allows(effect)) return;
    const receipt = gate.consume(effect);
    if (receipt) {
      if (effect.kind==='media' && (effect.value==='trip_photo' || generatedPhotoIdentity(effect.value))) this.displayedPhoto=effect;
      if (effect.kind === 'media' && effect.value === 'trip_photo') this.reportFixedPhoto(effect, 'receipt_pending');
      if (effect.kind === 'media' && generatedPhotoIdentity(effect.value)) {
        this.imagePresentedActivity = effect.activity_seq;
        this.view.storyImageStatus?.('剧情生成图已展示 · 虚构画面', true);
      }
      this.noteCaptionPresented(effect);
      this.enqueueFact(receipt, false, generation);
      try { this.view.visualPresented?.(effect); }
      catch { /* The actual presentation receipt remains authoritative if a display fails. */ }
    }
  }

  private imagePresentationBusy(): boolean {
    return this.microphoneBusy || this.speech!==null || this.playback.quiescent===false || this.options.userInputPending?.()===true;
  }

  private async finishVisualPreparation(run: VisualPreparationRun): Promise<void> {
    const stillAuthorized = (): boolean => this.visualPreparations.get(run.effect.id) === run
      && !run.abort.signal.aborted && this.current(run.generation)
      && this.gate === run.gate && run.gate.allows(run.effect)
      && (!generatedPhotoIdentity(run.effect.value) || !this.imagePresentationBusy())
      && (!isChapterEffect(run.effect) || (this.snapshot?.chapter_projection?.schema === 'mira.xiahe-chapter.v1'
        && this.snapshot.chapter_projection.suspended === false));
    if (run.effect.kind === 'media' && run.effect.value === 'trip_photo') this.reportFixedPhoto(run.effect, 'preparing');
    const generated=generatedPhotoIdentity(run.effect.value)!==null;
    try {
      if (generated && this.options.waitForReplyQuiet && !await this.options.waitForReplyQuiet(run.abort.signal)) {
        this.releaseVisualPreparation(run);this.attemptedVisualPreparations.delete(run.effect.id);return;
      }
      if (generated && !stillAuthorized()) {
        this.releaseVisualPreparation(run);this.attemptedVisualPreparations.delete(run.effect.id);
        if (!this.current(run.generation)) this.resumeVisualDrain(run.gate);
        return;
      }
      if (this.effects.prepare) await this.effects.prepare(run.effect, run.abort.signal);
    } catch {
      const authorized = stillAuthorized();
      this.releaseVisualPreparation(run);
      if (authorized) this.reportVisualPreparationFailure(run.effect, 'preparation_failed');
      this.resumeVisualDrain(run.gate);
      return;
    }
    // Resource callbacks can be slow or ignore AbortSignal. Never let them revive old authority.
    if (!stillAuthorized()) {
      if (generated && this.imagePresentationBusy()) this.attemptedVisualPreparations.delete(run.effect.id);
      this.releaseVisualPreparation(run);
      this.resumeVisualDrain(run.gate);
      return;
    }
    try {
      if (!stillAuthorized()) return;
      if (this.effects.present) {
        await this.effects.present(run.effect, run.abort.signal, stillAuthorized);
        if (stillAuthorized()) this.completeVisualEffect(run.effect, run.generation, run.gate);
      } else this.applyVisualEffect(run.effect, run.generation, run.gate);
    } catch {
      if (stillAuthorized()) this.reportVisualPreparationFailure(run.effect, 'presentation_failed');
    } finally {
      this.releaseVisualPreparation(run);
      this.resumeVisualDrain(run.gate);
    }
  }

  private releaseVisualPreparation(run: VisualPreparationRun): void {
    this.effects.discardPrepared?.(run.effect);
    if (this.visualPreparations.get(run.effect.id) === run) this.visualPreparations.delete(run.effect.id);
    if (this.visualPreparations.size < VISUAL_PREPARATION_LIMIT) this.capacityDeferredVisuals.clear();
  }

  private reportVisualPreparationFailure(effect: EffectView,
      outcome: 'preparation_failed' | 'presentation_failed' = 'preparation_failed'): void {
    if (effect.kind === 'media' && effect.value === 'trip_photo') {
      this.reportFixedPhoto(effect, outcome);
      if (!this.view.fixedPhotoStatus) this.view.error(MEDIA_PREPARATION_ERROR);
      return;
    }
    if (effect.kind === 'media' && generatedPhotoIdentity(effect.value)) {
      this.imageFailureActivity = effect.activity_seq;
      const message = '剧情生成图未能展示，可以继续聊天。';
      if (this.view.storyImageStatus) this.view.storyImageStatus(message, false);
      else this.view.error(message);
    } else this.view.error(effect.kind === 'media' ? MEDIA_PREPARATION_ERROR : VISUAL_PREPARATION_ERROR);
  }

  private updateFixedPhotoStatus(snapshot: SessionView): void {
    const status = snapshot.fixed_photo;
    if (snapshot.activity_seq <= this.photoDismissedThroughActivity || !status
      || status.activity_seq !== snapshot.activity_seq) {
      this.view.fixedPhotoStatus?.(null, false); return;
    }
    const local = this.localFixedPhoto;
    const state = local && local.effect.id === status.effect_id
      && local.effect.output_epoch === status.output_epoch && local.effect.activity_seq === status.activity_seq
      && status.state !== 'presented' && status.state !== 'dismissed' && status.state !== 'cancelled'
      ? local.state : status.state ?? 'idle';
    const messages = {
      idle: null, pending: '旅行插画正在准备，可以继续聊天。',
      held: status.reason === 'already_visible' ? null : '这张旅行插画暂未显示，可以继续聊天。',
      granted: '旅行插画正在准备，可以继续聊天。', preparing: '旅行插画正在准备，可以继续聊天。',
      receipt_pending: '图片展示状态正在确认，可以继续聊天。',
      presented: '旅行插画已展示 · 原创画面', failed: '这张旅行插画未能显示，可以继续聊天。',
      cancelled: null, dismissed: null,
    } as const;
    this.view.fixedPhotoStatus?.(messages[state], ['pending','granted','preparing','receipt_pending','presented'].includes(state));
  }

  private reportFixedPhoto(effect: EffectView, outcome: FixedPhotoProgressRequest['outcome']): void {
    if (effect.kind !== 'media' || effect.value !== 'trip_photo' || this.closed) return;
    this.localFixedPhoto = {effect, state: outcome.endsWith('_failed') ? 'failed'
      : outcome === 'receipt_pending' ? 'receipt_pending' : 'preparing'};
    if (this.snapshot) this.updateFixedPhotoStatus(this.snapshot);
    if (!this.api.fixedPhotoProgress || this.fixedPhotoReportsPending >= VISUAL_PREPARATION_LIMIT) return;
    const request: FixedPhotoProgressRequest = {effect_id: effect.id, digest: effect.digest,
      output_epoch: effect.output_epoch, activity_seq: effect.activity_seq, outcome};
    ++this.fixedPhotoReportsPending;
    // Ordered, bounded, best-effort metadata. It can never create a grant or a receipt.
    this.fixedPhotoReport = this.fixedPhotoReport.then(async () => {
      if (!this.closed) await this.api.fixedPhotoProgress!(request);
    }).catch(() => { /* Unconfirmed reporting does not stop ordinary chat or invent a failure. */ })
      .finally(() => { --this.fixedPhotoReportsPending; });
  }

  private async flushFixedPhotoReport(signal: AbortSignal): Promise<void> {
    if (!this.fixedPhotoReportsPending || signal.aborted) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let release: (() => void) | undefined;
    try {
      await Promise.race([this.fixedPhotoReport, new Promise<void>(resolve => {
        release = () => resolve(); signal.addEventListener('abort', release, {once: true});
        timer = setTimeout(resolve, this.factDrainTimeoutMs);
      })]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      if (release) signal.removeEventListener('abort', release);
    }
  }

  /** One browser-observed quiet opportunity per job; no model retry loop. */
  private maybeCompleteImage(): void {
    const snapshot=this.snapshot,job=snapshot?.story_image,gate=this.gate;
    if (!snapshot || !job?.request_id || !snapshot.request_id || !gate || this.closed
      || !this.api.completeStoryImage || !job.completion_available || job.completion_state!=='pending'
      || this.imageCompletionWait || this.imageCompletionAttempts.has(job.request_id)
      || !snapshot.sealed || snapshot.phase!=='idle' || this.pendingFacts>0 || this.failedFact
      || this.imagePresentationBusy() || snapshot.active_grants.some(e=>gate.allows(e))
      || !snapshot.active_grants.some(e=>gate.isAuthorized(e)) || snapshot.chapter_projection?.pending_transition
      || this.hiddenImageJobs.has(job.request_id)) return;
    const generation=this.generation,requestId=job.request_id,abort=new AbortController();
    this.imageCompletionWait=abort;
    const current=():boolean=>this.current(generation) && !abort.signal.aborted
      && this.snapshot?.request_id===snapshot.request_id && this.snapshot?.output_epoch===snapshot.output_epoch
      && this.snapshot?.story_image?.request_id===requestId && this.snapshot?.story_image?.completion_state==='pending'
      && !this.imagePresentationBusy() && this.pendingFacts===0 && !this.failedFact && this.snapshot.phase==='idle'
      && !this.hiddenImageJobs.has(requestId);
    void (async()=>{
      try {
        if (this.options.waitForReplyQuiet && !await this.options.waitForReplyQuiet(abort.signal)) return;
        if (!current()) return;
        const picture=snapshot.presented_effects.find(e=>generatedPhotoIdentity(e.value)?.resourceId===job.resource_id
          && generatedPhotoIdentity(e.value)?.contentDigest===job.content_digest);
        if (job.state!=='failed' && (job.state!=='presented' || !picture)) return;
        this.imageCompletionAttempts.add(requestId);
        const saved=await this.api.completeStoryImage!({request_id:requestId,parent_request_id:snapshot.request_id!,
          output_epoch:snapshot.output_epoch,activity_seq:snapshot.activity_seq,presented_effect_id:picture?.id??null},abort.signal);
        if(this.current(generation) && !abort.signal.aborted)this.install(saved);
      } catch { /* Unknown/failed completion is not retried; normal chat and image stay intact. */ }
      finally {if(this.imageCompletionWait===abort)this.imageCompletionWait=null;}
    })();
  }

  private updateStoryImageStatus(snapshot: SessionView): void {
    if (snapshot.activity_seq<=this.imageDismissedThroughActivity || snapshot.story_image?.request_id && this.hiddenImageJobs.has(snapshot.story_image.request_id)) {
      this.view.storyImageStatus?.(null, false); return;
    }
    if (this.imageFailureActivity === snapshot.activity_seq) {
      this.view.storyImageStatus?.('剧情生成图未能展示，可以继续聊天。', false); return;
    }
    const state = snapshot.story_image?.state ?? 'unavailable';
    const messages = {
      unavailable: null, idle: null, held: '剧情生成图暂未获准，可以继续聊天。',
      pending: '剧情生成图等待处理，可以继续聊天。', generating: '正在生成剧情虚构画面，可以继续聊天。',
      reviewing: '正在检查剧情生成图，可以继续聊天。', qualified: '正在准备展示剧情生成图。',
      presented: '剧情生成图已展示 · 虚构画面', failed: '剧情生成图未能完成，可以继续聊天。',
      cancelled: '剧情生成图请求已取消。',
    } as const;
    const presented = this.imagePresentedActivity === snapshot.activity_seq && state === 'qualified';
    const message = state === 'held' && snapshot.story_image?.failure_code === 'budget'
      ? '本次运行的剧情生成图调用额度已用尽，可以继续聊天。' : messages[state];
    this.view.storyImageStatus?.(presented ? messages.presented : message,
      ['pending', 'generating', 'reviewing', 'qualified', 'presented'].includes(state));
  }

  private resumeVisualDrain(gate: PresentationGate): void {
    // A stale callback can only resume the current queue after release; its own effect
    // remains fenced by generation/gate checks before apply and receipt.
    if (this.running && !this.closed && this.gate === gate) this.drainVisuals(this.generation, gate);
  }

  private cancelRevokedVisualPreparations(): void {
    for (const run of this.visualPreparations.values()) {
      if (run.generation !== this.generation || this.gate !== run.gate || !run.gate.allows(run.effect)) {
        run.abort.abort();
        this.attemptedVisualPreparations.delete(run.effect.id);
      }
    }
  }

  private cancelVisualPreparations(): void {
    if (this.captionTimer !== null) { clearTimeout(this.captionTimer); this.captionTimer = null; }
    this.captionQueue.clear();
    // Keep uncooperative callbacks counted against the small cap until they actually settle.
    for (const run of this.visualPreparations.values()) run.abort.abort();
  }

  private showReviewUncertainNotice(snapshot: SessionView): void {
    const key = `${snapshot.activity_seq}:${snapshot.output_epoch}`;
    if (this.reviewUncertainNoticeKey === key) return;
    this.reviewUncertainNoticeKey = key;
    // Settle the local thinking indicator without rewriting a prefix already on screen.
    this.effects.setPhase?.(this.externalMicrophoneActive() ? 'listening' : 'idle');
    if (this.view.systemNotice) this.view.systemNotice({label: '系统提示', body: REVIEW_UNCERTAIN_NOTICE});
    else {
      // Older view ports keep the notice visible once through their existing status surface.
      this.legacySystemNoticeActive = true;
      this.view.error(REVIEW_UNCERTAIN_NOTICE);
    }
  }

  private clearSystemNotice(): void {
    this.view.systemNotice?.(null);
    if (this.legacySystemNoticeActive) {
      this.legacySystemNoticeActive = false;
      this.view.error('');
    }
  }

  /** Block and physically disconnect before any network cancellation or new request. */
  private interrupt(reason: AudioStopReason, preserveReviewedParent = false): number {
    this.chapterChoiceActivity = null;
    this.effects.invalidateChapter?.();
    if (reason !== 'new-input') {
      this.continuationBlockedThroughActivity = Math.max(this.continuationBlockedThroughActivity, this.gate?.currentActivity() ?? 0);
      // Source lineage survives Stop and known pre-dispatch history failure;
      // generation/abort fences still revoke all old execution below.
      if (reason !== 'stop' && !preserveReviewedParent) this.continuationTarget = null;
      this.interruptedReply = null;
      try { this.onGlobalStop?.(reason); } catch { /* External capture release cannot block local Stop. */ }
    }
    const interruptedMicrophone = this.microphone !== null;
    this.view.microphonePreview?.(null);
    if (reason !== 'new-input' || interruptedMicrophone) this.view.microphoneTiming?.(null);
    this.clearSystemNotice();
    if (reason==='stop' || reason==='close') this.view.storyImageStatus?.(null,false);
    else if (this.snapshot) this.updateStoryImageStatus(this.snapshot);
    this.view.fixedPhotoStatus?.(null, false);
    this.localFixedPhoto = null;
    const generation = ++this.generation;
    // A barrier belongs to exactly one local turn. Stop, close, failure or a newer input
    // releases that waiter immediately, even if a transport ignores cancellation.
    this.generationAbort.abort();
    this.generationAbort = new AbortController();
    this.imageCompletionWait?.abort();this.imageCompletionWait=null;
    this.cancelVisualPreparations();
    this.attemptedVisualPreparations.clear();
    this.capacityDeferredVisuals.clear();
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
  /** Prepare the existing sink before a send awaits teardown/commit; never captures or submits PCM. */
  prepareInputFromGesture(): boolean {
    // Block old grants and stop any suspended/queued source before resuming the shared context.
    if (!this.interruptReply()) return false;
    if (this.capabilities?.speech_enabled !== false) this.unlock(this.generation);
    return true;
  }
  /** Exact current offer, saved presentation and live application role all agree. */
  isChapterOfferCurrent(effect: EffectView): boolean {
    const snapshot = this.snapshot, chapter = snapshot?.chapter_projection;
    return !this.closed && effect.kind === 'scene' && effect.value === 'xiahe_gift_offer'
      && chapter?.schema === 'mira.xiahe-chapter.v1' && chapter.role_active && !chapter.suspended
      && chapter.stage === 'gift_offered' && chapter.active_gift_offer_id !== null && chapter.pending_transition === null
      && chapter.gift_offer_effect_id === effect.id && chapter.gift_offer_effect_digest === effect.digest
      && snapshot!.activity_seq === this.chapterChoiceActivity && snapshot!.activity_seq === this.gate?.currentActivity()
      && (snapshot!.phase === 'ready' || snapshot!.phase === 'idle')
      && snapshot!.presented_effects.some(saved => saved.id === effect.id && saved.digest === effect.digest
        && saved.kind === effect.kind && saved.value === effect.value
        && saved.output_epoch === effect.output_epoch && saved.activity_seq === effect.activity_seq);
  }
  chooseChapterGift(effect: EffectView, choice: 'accept' | 'decline'): Promise<SessionInputOutcome> {
    if (!this.isChapterOfferCurrent(effect) || (choice !== 'accept' && choice !== 'decline')) return Promise.resolve({status: 'ignored'});
    const chapter = this.snapshot!.chapter_projection!;
    const chapterChoice: NonNullable<SessionInputRequest['chapter_choice']> = {
      choice, offer_id: chapter.active_gift_offer_id!, offer_effect_id: effect.id, offer_effect_digest: effect.digest,
    };
    return this.input(choice === 'accept' ? '我收下这张照片' : '暂时不收照片', undefined, undefined, undefined, chapterChoice);
  }
  async input(text: string, sourceAudioStreamId?: string, listeningUtteranceId?: string,
      reviewedContinuation?: SessionContinuationTarget,
      chapterChoice?: NonNullable<SessionInputRequest['chapter_choice']>): Promise<SessionInputOutcome> {
    if (!text.trim()) return { status: 'ignored' };
    if (this.closed || !this.gate) return { status: 'closed' };
    if (reviewedContinuation && (reviewedContinuation !== this.continuationTarget
      || reviewedContinuation.sessionId !== this.snapshot?.session_id)) {
      this.view.error('恢复语音的原请求已失效或被新一轮取代，未发送。文字已保留；请核对后选择“改为新话题”。');
      return {status: 'not-sent', text, reason: 'continuation-stale'};
    }
    const continuation = reviewedContinuation ?? (listeningUtteranceId ? this.interruptedReply : null);
    if (!listeningUtteranceId && !reviewedContinuation) this.interruptedReply = null;
    const generation = this.interrupt('new-input');
    const generationSignal = this.generationAbort.signal;
    this.reportedError = null; this.view.error('');
    const id = createClientId(), basis = this.gate.beginInput(id);
    this.chapterChoiceActivity = basis.activity_seq;
    this.responseInputIntent = {requestId: id, sequence: ++this.responseIntentSequence,
      enableVoice: explicitVoiceEnable(text)};
    const factSnapshot = this.captureFactSnapshot(basis.presentation_cutoff);
    this.effects.prepareInput();
    // Direct sends run here in the gesture. Callers that await teardown/commit first
    // prepare the same sink with prepareInputFromGesture() before that await.
    if (this.capabilities?.speech_enabled !== false) this.unlock(generation);
    const drain = await this.drainFactSnapshot(factSnapshot, generation, generationSignal);
    if (drain === 'closed' || this.closed) return { status: 'closed' };
    if (drain === 'superseded' || !this.current(generation)) return reviewedContinuation
      ? {status: 'not-sent', text, reason: 'cancelled-before-dispatch'} : {status: 'superseded'};
    if (drain !== 'saved') {
      this.fail(new Error(drain === 'timeout' ? FACT_HISTORY_TIMEOUT : FACT_HISTORY_FAILED), true);
      return { status: 'not-sent', text, reason: drain === 'timeout' ? 'history-timeout' : 'history-failed' };
    }
    const abort = new AbortController(); this.activityRequest = abort;
    try {
      await this.preferenceWrite;
      await this.flushFixedPhotoReport(generationSignal);
      if (!this.current(generation)) return this.closed ? {status: 'closed'} : reviewedContinuation
        ? {status: 'not-sent', text, reason: 'cancelled-before-dispatch'} : {status: 'superseded'};
      const request: SessionInputRequest = {...basis, request_id: id, text,
        ...(chapterChoice ? {chapter_choice: chapterChoice} : {}),
        ...(continuation ? {relation: 'continuation' as const, continuation_of_request_id: continuation.requestId,
          continuation_of_output_epoch: continuation.outputEpoch} : {}),
        ...(sourceAudioStreamId && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sourceAudioStreamId)
          ? {source_audio_stream_id: sourceAudioStreamId} : {}),
        ...(listeningUtteranceId && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(listeningUtteranceId)
          ? {listening_utterance_id: listeningUtteranceId} : {})};
      // Dispatch may be accepted even if its response is lost. Retire the old
      // parent here, never at function entry or while waiting for known facts.
      this.continuationTarget = null;
      const snapshot = await this.api.input(request, abort.signal);
      if (this.current(generation)) { this.interruptedReply = null; this.install(snapshot, {text, requestId: id}); return { status: 'submitted' }; }
      return this.closed ? { status: 'closed' } : { status: 'superseded' };
    } catch (error) {
      if (this.current(generation) && error instanceof MiraHttpError
        && error.status === 409 && error.code === 'history_pending') {
        // This exact server response guarantees the input/request identity was
        // not consumed. A new explicit click may retry its reviewed source;
        // unknown transport outcomes still retire it and never retry here.
        if (reviewedContinuation) this.continuationTarget = reviewedContinuation;
        this.fail(new Error('上一轮可见内容尚未确认保存；本次输入未送出。请等待状态更新后重试。'),
          reviewedContinuation !== undefined);
        return {status: 'not-sent', text, reason: 'history-pending'};
      }
      if (this.current(generation)) { this.fail(error); return { status: 'unknown' }; }
      return this.closed ? { status: 'closed' } : { status: 'superseded' };
    } finally { if (this.activityRequest === abort) this.activityRequest = null; }
  }
  /** Hide and fence locally before any network wait. This never interrupts speech or capture. */
  dismissPhoto(target: 'display'|'fixed_photo'|'image_job'='display'): Promise<void> {
    const gate=this.gate;
    if (!gate || this.closed || !this.running) return Promise.resolve();
    const shown=this.displayedPhoto, job=this.snapshot?.story_image;
    const key=target==='image_job' ? `job:${job?.request_id}` : target==='display' ? `display:${shown?.id}` : `fixed:${gate.currentActivity()}`;
    if (key===this.photoDismissalKey) return this.photoDismissal ?? Promise.resolve();
    this.photoDismissalKey=key;
    const generated=shown ? generatedPhotoIdentity(shown.value) : null;
    const closesFixed=target==='fixed_photo' || target==='display' && !generated;
    if (closesFixed) this.photoDismissedThroughActivity=gate.currentActivity();
    if (target==='image_job') this.imageDismissedThroughActivity=gate.currentActivity();
    if (job?.request_id && (target==='image_job' || target==='display' && generated?.resourceId===job.resource_id)) this.hiddenImageJobs.add(job.request_id);
    const basis=gate.dismissPhoto(closesFixed ? 'fixed_photo' : target,shown?.id);
    this.cancelRevokedVisualPreparations();
    if (target==='display' || closesFixed && !generated || target==='image_job' && generated?.resourceId===job?.resource_id) {
      this.effects.dismissPhoto?.(closesFixed ? 'fixed_photo' : 'display');
    }
    if (closesFixed) {this.view.fixedPhotoStatus?.(null,false);this.localFixedPhoto=null;}
    if (target==='image_job' || target==='display' && generated?.resourceId===job?.resource_id) this.view.storyImageStatus?.(null,false);
    const request: PhotoDismissRequest={...basis,request_id:createClientId(),target,
      expected_revision:this.photoVisibilityRevision++,
      expected_photo_effect_id:target==='display' || target==='fixed_photo' && !generated ? shown?.id??null : null,
      expected_image_request_id:target==='image_job' ? job?.request_id??null : null};
    this.photoDismissal=this.enqueueFact(request,'photo');
    this.resumeVisualDrain(gate);return this.photoDismissal;
  }

  dismissStoryImage(): Promise<void> {
    const shown=this.displayedPhoto, job=this.snapshot?.story_image;
    return this.dismissPhoto(job?.state==='presented' && shown && generatedPhotoIdentity(shown.value)?.resourceId===job.resource_id ? 'display' : 'image_job');
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

  private reconcileOutputPreference(): void {
    // Only this.snapshot has passed the session/branch gate. Mute may tighten
    // during an in-flight write; release waits until that write has settled.
    const snapshot = this.snapshot;
    if (!snapshot) return;
    const revision = snapshot.response_preference_revision ?? 0;
    if (revision < this.preferenceRevision) return;
    const inputIntent = this.responseInputIntent;
    if (inputIntent?.requestId === snapshot.request_id && inputIntent.enableVoice
      && inputIntent.sequence > this.speechBlockedThroughIntent
      && snapshot.response_muted === false && snapshot.response_mode === 'voice') {
      // This exact user input was initiated after the local mute, and the server
      // has accepted its new turn. A poll may prove acceptance before its POST
      // response arrives; an older input cannot borrow this newer intent.
      this.unconfirmedLocalMute = false;
      this.localOutputMuted = false;
      this.preferenceRevision = revision;
    }
    if (snapshot.response_muted === true) {
      this.localOutputMuted = true;
      this.preferenceRevision = revision;
      if (revision > this.localMuteBaseRevision) this.unconfirmedLocalMute = false;
    } else if (!this.preferenceWrite && revision > this.preferenceRevision) {
      if (!this.unconfirmedLocalMute) this.localOutputMuted = false;
      this.preferenceRevision = revision;
    }
  }

  async setOutputMuted(muted: boolean): Promise<void> {
    if (this.closed || !this.snapshot || this.preferenceWrite) return;
    this.speechBlockedThroughIntent = ++this.responseIntentSequence;
    this.speechMutedThroughEpoch = Math.max(this.speechMutedThroughEpoch, this.snapshot.output_epoch);
    let release!: () => void;
    const barrier = new Promise<void>(resolve => { release = resolve; });
    this.preferenceWrite = barrier;
    if (muted) {
      this.localOutputMuted = true; this.unconfirmedLocalMute = true;
      this.localMuteBaseRevision = this.snapshot.response_preference_revision ?? 0;
    }
    this.view.outputPreference?.(this.localOutputMuted, muted ? 'text_only' : this.snapshot.response_mode ?? 'voice', true);
    if (muted) {
      const run = this.speech;
      // Reuse the only sink. This allocates an honest terminal fact immediately;
      // its transport waits for the server revocation, not local audio teardown.
      this.playback.stop('stop');
      run?.abort.abort(); run?.wake?.(); this.speech = null;
      this.effects.setPhase?.(this.microphone || this.externalMicrophoneActive() ? 'listening' : 'idle');
    }
    try {
      if (!this.api.responsePreference) throw new Error('回应静音已在本地生效；当前连接不支持保存偏好。');
      const snapshot = await this.api.responsePreference({muted,
        expected_revision: this.snapshot.response_preference_revision ?? 0}, this.lifetime.signal);
      if (this.closed) return;
      this.install(snapshot);
      // A failed local mute remains held even if an older input response arrives
      // later with a newer server preference. Only accepted confirmation can
      // reconcile it; a rejected stale success has no authority over this latch.
      if (!muted && this.snapshot === snapshot && snapshot.response_muted === false
        && (snapshot.response_preference_revision ?? 0) >= this.preferenceRevision) {
        this.unconfirmedLocalMute = false;
      }
    } catch (error) {
      if (!this.closed) this.report(error);
    } finally {
      this.preferenceWrite = null; release();
      if (!this.closed) this.reconcileOutputPreference();
      if (!this.closed) this.view.outputPreference?.(this.localOutputMuted,
        this.snapshot?.response_mode ?? 'text_only', false);
    }
  }

  private startSpeech(): void {
    const gate = this.gate;
    if (this.closed || !this.running || this.localOutputMuted || this.snapshot?.response_mode === 'text_only'
      || !this.unlocked || !this.capabilities?.speech_enabled
      || !gate || this.speech || this.microphone || this.rehearsalInput || !this.snapshot) return;
    const effect = this.snapshot.active_grants.find(value => value.kind === 'speech'
      && (value.id!==this.snapshot?.story_image?.completion_speech_effect_id || !this.options.userInputPending?.())
      && value.output_epoch > this.speechMutedThroughEpoch && gate.allows(value));
    if (!effect || !gate.claimSpeech(effect)) return;
    const run: SpeechRun = {effect, generation: this.generation, abort: new AbortController(), handle: null, accepted: 0, submitted: false, rendered: 0, wake: null};
    this.speech = run;
    void this.beginSpeech(run);
  }
  private async beginSpeech(run: SpeechRun): Promise<void> {
    try {
      if (this.options.waitForReplyQuiet && !await this.options.waitForReplyQuiet(run.abort.signal)) {
        if (this.activeSpeech(run)) this.failSpeech(run, new Error('回应语音尚未开始：仍在等待安静。文字保留，可继续说话或重新发送。'));
        return;
      }
    } catch (error) { if (this.activeSpeech(run)) this.failSpeech(run, error); return; }
    if (!this.activeSpeech(run)) return;
    if (run.effect.id===this.snapshot?.story_image?.completion_speech_effect_id && (this.microphoneBusy || this.options.userInputPending?.())) {
      this.speech=null;run.abort.abort();return;
    }
    const effect = run.effect;
    run.handle = this.playback.open(effect);
    if (!run.handle) { this.failSpeech(run, new Error('Audio grant could not start. Use text input.')); return; }
    void this.api.speech(effect, run.abort.signal, async pcm => {
      // Pace against both rendered frames and this sink's actual packet/frame
      // capacity. Many small packets can fill its queue before the frame budget.
      while (run.accepted - run.rendered + pcm.length > 96000
        || run.handle?.canAccept?.(pcm.length) === false) {
        if (!this.activeSpeech(run)) throw new Error('Speech cancelled');
        await new Promise<void>(resolve => { run.wake = resolve; });
      }
      if (!this.activeSpeech(run) || !run.handle!.push(pcm)) throw new Error('Speech playback stopped');
      run.accepted += pcm.length;
    }).then(() => {
      if (this.activeSpeech(run) && !run.handle!.finish()) this.failSpeech(run, new Error('Speech did not complete. Use text input.'));
    }).catch(error => { if (this.activeSpeech(run)) this.failSpeech(run, error); });
  }
  private failSpeech(run: SpeechRun, error: unknown): void {
    if (!this.current(run.generation)) return;
    const gate = this.gate;
    if (!gate?.preserveTextAfterSpeechFailure(run.effect)) { this.fail(error); return; }
    // Keep the text preparation's generation and permit. Local audio/dependent
    // authority is removed before disconnecting, including reentrant sink facts.
    this.speech = null;
    run.abort.abort(); run.wake?.(); run.wake = null;
    this.playback.stop('error');
    this.cancelRevokedVisualPreparations();
    this.effects.setPhase?.(this.microphone || this.externalMicrophoneActive() ? 'listening' : 'idle');
    this.report(error);
    this.presentVisuals();
  }
  private activeSpeech(run: SpeechRun): boolean {
    return this.speech === run && this.current(run.generation) && !this.localOutputMuted
      && run.effect.output_epoch > this.speechMutedThroughEpoch
      && this.snapshot?.response_mode !== 'text_only' && !run.abort.signal.aborted && this.gate?.isAuthorized(run.effect) === true;
  }
  private playbackFact(fact: PlaybackFact): void {
    const run = this.speech;
    const progress = this.gate?.audioProgress(fact);
    if (progress && !this.closed) this.enqueueFact(progress, true, run?.generation ?? this.generation);
    if (!run || run.effect.id !== fact.origin.id || run.effect.digest !== fact.origin.digest) return;
    if (fact.stage === 'rendered') { run.rendered = fact.renderedFrames; run.wake?.(); run.wake = null; }
    if (fact.stage === 'submitted' && this.activeSpeech(run)) {
      run.submitted = true;
      if (this.gate?.submitSpeech(fact)) {
        this.presentVisuals();
        this.effects.setPhase?.('speaking');
      }
    }
    if (fact.stage === 'completed' || fact.stage === 'stopped' || fact.stage === 'failed') {
      this.speech = null; run.abort.abort(); run.wake?.(); run.wake = null;
      if (!this.current(run.generation)) return;
      this.effects.setPhase?.(this.microphone || this.externalMicrophoneActive() ? 'listening' : 'idle');
      if (fact.stage === 'failed' || fact.reason === 'error') this.failSpeech(run, new Error('Audio failed. Text input is still available.'));
      else if (fact.stage==='completed') queueMicrotask(()=>{if(this.current(run.generation)){this.startSpeech();this.presentVisuals();this.maybeCompleteImage();}});
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

  private enqueueFact(fact: ReceiptRequest | AudioProgressRequest | PhotoDismissRequest,
      audio: boolean | 'photo', generation = this.generation): Promise<void> {
    const presentationSequence = 'presentation_cutoff' in fact ? fact.presentation_cutoff : fact.presentation_seq;
    const sequence = ++this.factSequence;
    if (++this.pendingFacts > 4096) {
      this.pendingFacts--;
      this.noteFailedFact(sequence, presentationSequence);
      if (audio === 'photo') this.view.error('照片已在本页收起，但状态同步队列已满。请结束会话后重开。');
      else this.fail(new Error('Presentation history delivery is full. Close and create a new session.'));
      return Promise.resolve();
    }
    // Keep terminal audio behind earlier rendered counters. Each acknowledgement retains its
    // immutable issue sequence, presentation sequence and owning local generation.
    const preferenceWrite = this.preferenceWrite;
    const acknowledgement = this.facts.then(async (): Promise<FactAcknowledgement> => {
      try {
        await preferenceWrite;
        if (this.closed) return { sequence, status: 'closed' };
        if (audio === 'photo') {
          if (!this.api.dismissPhoto) throw new Error('照片已在本页收起，但服务不支持同步。请结束会话后重开。');
          const saved = await this.api.dismissPhoto(fact as PhotoDismissRequest);
          if (!this.snapshot || saved.session_id !== this.snapshot.session_id
            || saved.client_instance_id !== this.snapshot.client_instance_id
            || saved.photo_visibility_revision !== (fact as PhotoDismissRequest).expected_revision + 1
            ) throw new Error('照片已在本页收起，但状态同步未确认。请结束会话后重开。');
          // The close response cannot replay grants or interrupt independent media owners.
          this.photoVisibilityRevision = Math.max(this.photoVisibilityRevision, saved.photo_visibility_revision);
        } else if (audio) await this.api.audioProgress(fact as AudioProgressRequest);
        else {
          const chapterReceipt = this.snapshot?.active_grants.some(effect => effect.id === (fact as ReceiptRequest).effect_id
            && isChapterEffect(effect));
          const saved = await this.api.receipt(fact as ReceiptRequest);
          if ((chapterReceipt || saved.story_image?.completion_state==='pending' || saved.story_image?.completion_state==='presented') && this.current(generation)) this.install(saved);
          const local = this.localFixedPhoto;
          if (this.current(generation) && local && local.effect.id === (fact as ReceiptRequest).effect_id
            && saved.fixed_photo?.state === 'presented' && saved.fixed_photo.effect_id === local.effect.id
            && saved.presented_effects.some(effect => effect.id === local.effect.id && effect.digest === local.effect.digest
              && effect.output_epoch === local.effect.output_epoch && effect.activity_seq === local.effect.activity_seq)) {
            this.localFixedPhoto = {...local, state: 'presented'};
            if (this.snapshot) this.updateFixedPhotoStatus(this.snapshot);
          }
        }
        return { sequence, status: 'saved' };
      } catch (error) {
        this.noteFailedFact(sequence, presentationSequence);
        if (audio === 'photo' && !this.closed) this.view.error('照片已在本页收起，但状态同步未确认。请结束会话后重开。');
        else if (this.current(generation)) this.fail(error);
        // Preserve the new activity's actionable failure/locator, if it has one.
        else if (!this.closed && this.reportedError === null) this.view.error('An earlier presentation fact could not be saved. History may be incomplete.');
        return { sequence, status: 'failed' };
      } finally {this.pendingFacts--;queueMicrotask(()=>this.maybeCompleteImage());}
    });
    this.facts = acknowledgement.then(() => undefined);
    const delivery: FactDelivery = {
      sequence,
      presentationSequence: presentationSequence,
      generation,
      acknowledgement,
    };
    this.factDeliveries.set(sequence, delivery);
    void acknowledgement.then(() => {
      if (this.factDeliveries.get(sequence) === delivery) this.factDeliveries.delete(sequence);
    });
    return acknowledgement.then(() => undefined);
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
    run.ready = this.api.stop({...basis,scope:'reply'},abort.signal).then(snapshot => {
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
    if (this.externalMicrophoneActive()) { this.view.error('先停止连续聆听，再使用按住说话。'); return; }
    this.view.microphonePreview?.(null); this.view.microphoneTiming?.(null);
    if (!this.capabilities?.microphone_enabled) { this.view.error('Microphone recognition is not configured. Use text input.'); return; }
    const generation = this.interrupt('new-input');
    this.reportedError = null; this.view.error('');
    const basis = this.gate.stop();
    this.effects.prepareInput();
    this.unlock(generation);
    const streamId = createClientId();
    const timingOriginMs = this.api.monotonicNow?.() ?? performance.now();
    const run: MicrophoneRun = {generation, streamId, timingOriginMs, abort: new AbortController(), queue: [], queuedBytes: 0,
      released: false, transport: null, setup: Promise.resolve(), finishing: null, lastPreviewRevision: 0};
    this.microphone = run;
    this.activityRequest = run.abort;
    // Start capture synchronously under the user's gesture, before awaiting the stop acknowledgement.
    const starting = this.capture.start();
    run.setup = this.api.stop({...basis,scope:'reply'},run.abort.signal).then(snapshot => {
      if (!this.activeMicrophone(run)) return;
      if (snapshot.activity_seq !== basis.activity_seq) throw new Error('Microphone stop acknowledgement was superseded');
      this.install(snapshot);
      if (!this.activeMicrophone(run)) return;
      const transport = this.api.microphone(
        {stream_id: streamId, activity_seq: snapshot.activity_seq, input_epoch: snapshot.input_epoch},
        run.abort.signal,
        {
          timingOriginMs: run.timingOriginMs,
          onRevision: revision => {
            if (!this.activeMicrophone(run) || revision?.stream_id !== undefined && revision.stream_id !== run.streamId) return;
            if (revision === null) { this.view.microphonePreview?.(null); return; }
            if (run.released || revision.revision <= run.lastPreviewRevision || revision.revision > 10000
              || typeof revision.text !== 'string') return;
            run.lastPreviewRevision = revision.revision;
            this.view.microphonePreview?.({...revision, text: revision.text.slice(0, 2000)});
          },
          onTiming: timing => {
            if (this.activeMicrophone(run) && timing.stream_id === run.streamId) this.view.microphoneTiming?.(timing);
          },
        },
      );
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
    this.view.microphonePreview?.(null);
    if (!run || !this.activeMicrophone(run)) return;
    if (run.finishing) return run.finishing;
    run.released = true;
    const clientFinishAtMs = this.api.monotonicNow?.() ?? performance.now();
    this.capture.stop(); this.view.microphone?.('finishing'); this.effects.setPhase?.('thinking');
    run.finishing = (async (): Promise<SessionInputOutcome | undefined> => {
      await run.setup;
      if (!this.activeMicrophone(run) || !run.transport) return;
      const result = await run.transport.finish(clientFinishAtMs);
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
    if (snapshot === null) return false;
    // `sealed` closes an input's generation branch. The actual fresh-session contract is
    // idle/unsealed with no request and zero activity; Stop is stopped/unsealed. A completed
    // response is idle/sealed with a request identity and every current grant represented in
    // presented history. The server records speech there only after COMPLETED audio progress.
    const freshSession = snapshot.phase === 'idle' && !snapshot.sealed && snapshot.request_id === null
      && snapshot.revision === 0 && snapshot.permit_revision === 0
      && snapshot.activity_seq === 0 && snapshot.input_epoch === 0 && snapshot.output_epoch === 0
      && snapshot.active_grants.length === 0 && snapshot.presented_effects.length === 0;
    const stoppedSession = snapshot.phase === 'stopped' && !snapshot.sealed && snapshot.request_id === null
      && snapshot.active_grants.length === 0;
    const allGrantsPresented = snapshot.active_grants.every(grant => snapshot.presented_effects.some(presented =>
      presented.id === grant.id && presented.kind === grant.kind && presented.value === grant.value
        && presented.digest === grant.digest && presented.output_epoch === grant.output_epoch
        && presented.activity_seq === grant.activity_seq && (presented.cue_id ?? null) === (grant.cue_id ?? null)
        && (presented.cue_speech_id ?? null) === (grant.cue_speech_id ?? null)));
    const completedSession = snapshot.phase === 'idle' && snapshot.sealed && snapshot.request_id !== null
      && allGrantsPresented;
    const sessionQuiescent = freshSession || stoppedSession || completedSession;
    return !this.closed && this.running && sessionQuiescent
      && !this.externalMicrophoneActive()
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

  /** Snapshot before overlap/finalization; only this exact locally issued object can be restored. */
  captureReplyContinuation(): SessionContinuationTarget | null {
    const snapshot = this.snapshot;
    if (this.closed || !this.gate || !snapshot?.request_id || (this.speech === null && snapshot.sealed)
      || this.gate.currentActivity() !== snapshot.activity_seq
      || snapshot.activity_seq <= this.continuationBlockedThroughActivity) return null;
    const current = this.continuationTarget;
    if (current?.sessionId === snapshot.session_id && current.requestId === snapshot.request_id
      && current.outputEpoch === snapshot.output_epoch && current.activitySeq === snapshot.activity_seq) return current;
    return this.continuationTarget = Object.freeze({sessionId: snapshot.session_id, requestId: snapshot.request_id,
      outputEpoch: snapshot.output_epoch, activitySeq: snapshot.activity_seq});
  }

  /** Exact local capability, including the gap while a newer input waits on receipts. */
  isInterruptedReplyCurrent(target: SessionContinuationTarget): boolean {
    return !this.closed && this.interruptedReply === target && this.continuationTarget === target
      && target.sessionId === this.snapshot?.session_id && this.gate?.currentActivity() === target.activitySeq;
  }

  /** Exact source ownership even when finalized speech arrives after playback ends. */
  isReplyContinuationCurrent(target: SessionContinuationTarget): boolean {
    return this.isInterruptedReplyCurrent(target) || (!this.closed && this.continuationTarget === target
      && target.sessionId === this.snapshot?.session_id && target.requestId === this.snapshot?.request_id
      && target.outputEpoch === this.snapshot?.output_epoch && this.gate?.currentActivity() === target.activitySeq
      && target.activitySeq > this.continuationBlockedThroughActivity);
  }

  /** Locally fences the current reply without changing an independent continuous mic lease. */
  interruptReply(): boolean {
    if (!this.gate || this.closed) return false;
    const target = this.captureReplyContinuation()
      ?? (this.continuationTarget && this.isReplyContinuationCurrent(this.continuationTarget) ? this.continuationTarget : null);
    if (target) this.interruptedReply = target;
    try {
      this.interrupt('new-input');
      this.gate?.resumeBackgroundImages();this.presentVisuals();
      this.effects.setPhase?.(this.externalMicrophoneActive() ? 'listening' : 'idle');
      return true;
    } catch {
      this.view.error('本地回复未能确认停止。请使用“停止回应”并检查音频状态。');
      return false;
    }
  }

  /** Keeps the scene's listening phase accurate while an independent lease survives new input turns. */
  setContinuousListeningPhase(active: boolean): void {
    if (!this.closed && !this.speech && !this.microphone && !this.rehearsalInput) {
      this.effects.setPhase?.(active ? 'listening' : 'idle');
    }
  }

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
    const failure = classifyUnexpectedAbort(error);
    this.reportedError = failure instanceof Error ? failure.message : 'Transport unavailable. Use text input.';
    this.view.error(this.reportedError);
  }
  private fail(error: unknown, preserveReviewedParent = false): void {
    if (this.closed) return;
    this.interrupt('error', preserveReviewedParent); this.effects.stop(); this.report(error);
  }
  close(): Promise<void> {
    if (this.closePromise) return this.closePromise;
    this.closed = true; this.running = false; this.interruptedReply = null;
    let localCleanupFailed = false;
    try { this.interrupt('close'); } catch { localCleanupFailed = true; }
    try { this.effects.stop(); } catch { localCleanupFailed = true; }
    this.generationAbort.abort(); this.lifetime.abort();
    this.activityRequest?.abort(); this.activityRequest = null;
    this.pollRequest?.abort(); this.pollRequest = null;
    if (this.pollTimer !== null) { clearTimeout(this.pollTimer); this.pollTimer = null; }
    // Invoke each owner independently: a synchronous renderer failure must not
    // prevent microphone, playback or remote-session cleanup from starting.
    const cleanup = [() => this.effects.close?.(), () => this.capture.close(),
      () => this.playback.close(), () => this.api.close()];
    this.closePromise = Promise.allSettled(cleanup.map(close => Promise.resolve().then(close))).then(results => {
      if (localCleanupFailed || results.some(result => result.status === 'rejected')) {
        this.view.error('已请求关闭，部分资源释放未能确认。请关闭页面并查看诊断。');
      }
    });
    return this.closePromise;
  }
}
