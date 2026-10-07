import { MicrophoneCapture, LocalBargeInDetector } from '../audio/index.js';
import type { CaptureOptions, AudioRuntimeError, CapturedAudio, CaptureProcessingState,
  LocalBargeInMode, LocalBargeInResult } from '../audio/index.js';
import type { ContinuousListeningHoldResult, ContinuousListeningMode, ContinuousListeningReady, ContinuousListeningServerEvent, ContinuousListeningStream } from './ports.js';
import type { SessionInputOutcome, SessionContinuationTarget } from './controller.js';

export type ContinuousListeningState = 'idle' | 'starting' | 'listening' | 'stopping' | 'stopped' | 'limit' | 'error' | 'closed';
export type ContinuousConversationPhase = 'listening' | 'transcribing' | 'ready' | 'sending' | 'sent' | 'manual_review';
export interface ContinuousTranscriptView {
  readonly lease_id: string;
  readonly continuation_target?: SessionContinuationTarget;
  readonly revision: number;
  readonly text: string;
  readonly is_final: boolean;
  readonly endpoint_pending: boolean;
  readonly can_send: boolean;
  readonly truncated: boolean;
  readonly hint: string | null;
  readonly utterance_id?: string;
  readonly auto_ready?: boolean;
  readonly review_required?: boolean;
  readonly endpoint_basis?: 'offset_coverage' | 'vad_final_grace' | 'stream_finalized' | 'client_silence_finalized';
}
export type ContinuousCorrectionView = Pick<Extract<ContinuousListeningServerEvent, {type: 'utterance_revision'}>,
  'revision' | 'text' | 'submission_state'>;
export interface ContinuousSentTextView {
  readonly commit_id: string;
  readonly segment_seq: number;
  readonly revision: number;
  readonly text: string;
  readonly state: 'sending' | 'sent' | 'not_sent' | 'unknown';
  readonly notice: string | null;
  readonly utterance_id?: string;
  readonly correction?: ContinuousCorrectionView;
}
export interface ContinuousListeningView {
  readonly state: ContinuousListeningState;
  readonly lease_id: string | null;
  readonly ready: ContinuousListeningReady | null;
  readonly transcript: ContinuousTranscriptView | null;
  readonly previous_previews: readonly ContinuousTranscriptView[];
  readonly previous_preview_limit: number;
  readonly held_previews: readonly ContinuousTranscriptView[];
  readonly held_preview_limit: number;
  readonly sent_text: readonly ContinuousSentTextView[];
  readonly retired_sent_text: number;
  readonly service_budget_exhausted: boolean;
  readonly pending_text_capacity: boolean;
  readonly notice: string | null;
  readonly error: string | null;
  readonly conversation_phase: ContinuousConversationPhase;
  readonly natural_enabled: boolean;
  readonly recognition_status: Extract<ContinuousListeningServerEvent, {type: 'recognition_status'}> | null;
  readonly barge_in_mode: LocalBargeInMode;
  readonly barge_in_available: boolean;
  readonly barge_in_suspended: boolean;
  readonly capture_processing: CaptureProcessingState | null;
}
export interface RecoveredVoiceInput {
  readonly text: string;
  readonly continuationTarget: SessionContinuationTarget | null;
}
export interface ContinuousListeningControllerOptions {
  readonly mode?: ContinuousListeningMode;
  /** Captured quiet duration; an energy heuristic, never acoustic certainty. */
  readonly silenceMilliseconds?: number;
  /** Local interruption preference, sampled once per lease. Legacy headphones means enabled, not hardware proof. */
  readonly bargeInMode?: () => LocalBargeInMode;
  readonly setTimer?: (callback: () => void, milliseconds: number) => ReturnType<typeof setTimeout>;
  readonly clearTimer?: (timer: ReturnType<typeof setTimeout>) => void;
  readonly createCapture?: (options: CaptureOptions) => Pick<MicrophoneCapture, 'start' | 'stop' | 'close'>;
  readonly openStream: (leaseId: string, signal: AbortSignal,
    observers: {readonly onEvent: (event: ContinuousListeningServerEvent) => void;
      readonly onError: (error: Error) => void}, mode?: ContinuousListeningMode) => ContinuousListeningStream;
  readonly submitInput: (text: string, listeningUtteranceId?: string, continuationTarget?: SessionContinuationTarget) => Promise<SessionInputOutcome>;
  readonly canStart?: () => boolean;
  /** Local-only reply fence; must return before capture or commit starts. */
  readonly interruptReply?: () => boolean;
  /** User-send gesture only: fences reply and prepares its playback sink before commit awaits. */
  readonly prepareInputFromGesture?: () => boolean;
  /** Software sink ownership only; never evidence of acoustic echo or speaker identity. */
  readonly isPlaybackBusy?: () => boolean;
  /** Called with overlapping PCM, never inferred from a later reply or matching text. */
  readonly captureReplyContinuation?: () => SessionContinuationTarget | null;
  readonly isInterruptedReplyCurrent?: (target: SessionContinuationTarget) => boolean;
  /** Exact local request ownership before a quiet endpoint stops an overlapping reply. */
  readonly isReplyContinuationCurrent?: (target: SessionContinuationTarget) => boolean;
  readonly onUpdate: (view: ContinuousListeningView) => void;
  readonly onPhase?: (listening: boolean) => void;
  readonly createId?: () => string;
}
interface TranscriptState extends ContinuousTranscriptView {
  readonly textLength: number;
  readonly stable: boolean;
  readonly sourceEndSample?: number;
}
interface SentText extends ContinuousSentTextView {}
interface HeldCandidate { readonly utteranceId: string; readonly revision: number; readonly text: string; readonly sourceEnd?: number; }
interface BargeEvidence {
  readonly candidateStart: number;
  readonly end: number;
  readonly target: SessionContinuationTarget;
}
interface ListeningRun {
  readonly leaseId: string;
  readonly bargeInMode: LocalBargeInMode;
  readonly bargeDetector: LocalBargeInDetector;
  bargeInvalid: boolean;
  bargeSuspended: boolean;
  readonly bargeAttemptEnds: number[];
  readonly abort: AbortController;
  readonly queue: CapturedAudio[];
  queueBytes: number;
  stream: ContinuousListeningStream | null;
  ready: ContinuousListeningReady | null;
  captured: boolean;
  stopping: boolean;
  latestRevision: number;
  staleRevisionFence: number;
  commitCount: number;
  commitInFlight: boolean;
  onsetActiveSamples: number;
  onsetQuietSamples: number;
  onsetLatched: boolean;
  preserveAcceptedCommit: boolean;
  stopPromise: Promise<void> | null;
  readonly automaticAttempts: Map<string, {revision: number; commitId: string}>;
  readonly manualOnlyUtterances: Map<string, {revision: number; sourceEnd: number}>;
  readonly committedResetRevisions: Map<string, number>;
  readonly holdAttempts: Set<string>;
  pendingHold: HeldCandidate | null;
  heldCandidate: HeldCandidate | null;
  readonly corrections: Map<string, Extract<ContinuousListeningServerEvent, {type: 'utterance_revision'}>>;
  readonly playbackRanges: {start: number; end: number; target: SessionContinuationTarget | null}[];
  playbackUnknown: boolean;
  bargeEvidence: BargeEvidence | null;
  settledSourceEnd: number;
  localSamples: number;
  localActivityVersion: number;
  localQuietSamples: number;
  localActiveSamples: number;
  noiseFloor: number;
  noiseProbeEnergy: number;
  noiseProbeSamples: number;
  localMeaningful: boolean;
  localVoiceLatched: boolean;
  localHasText: boolean;
  localEndpoint: {id: string; sourceEnd: number; cancelled: boolean; state: string} | null;
  endpointTimer: ReturnType<typeof setTimeout> | null;
  readonly quietWaiters: Set<(quiet: boolean) => void>;
}
type CapturePort = Pick<MicrophoneCapture, 'start' | 'stop' | 'close'>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const hasWords = (text: string): boolean => /[\p{L}\p{N}]/u.test(text);
const MAX_PREVIOUS_PREVIEWS = 4;
const MAX_HELD_PREVIEWS = 12;
const MAX_SETTLED_RECORDS = 64;
const MAX_PENDING_RECORDS = 64;
// A narrow rapid-loop guard, not acoustic echo classification or a per-lease usage cap.
const BARGE_BURST_WINDOW_SAMPLES = 32000;
const BARGE_BURST_ATTEMPTS = 3;
// A bounded PCM energy heuristic, not speech recognition. We count about 40 ms of
// consecutive 16 kHz samples over this RMS floor and rearm after 200 ms of quiet.
const ONSET_RMS_FLOOR = 900;
const ONSET_MIN_ACTIVE_SAMPLES = 640;
const ONSET_QUIET_RESET_SAMPLES = 3200;
const MAX_ONSET_SAMPLES_PER_CHUNK = 1600;

function capturedRms(chunk: CapturedAudio): number | null {
  const bytes = chunk.pcm16le;
  if (!(bytes instanceof Uint8Array) || bytes.length < 2 || bytes.length % 2 !== 0
    || bytes.length > MAX_ONSET_SAMPLES_PER_CHUNK * 2 || chunk.sampleRate !== 16000 || chunk.channels !== 1) return null;
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let energy = 0;
  for (let index = 0; index < bytes.length / 2; index++) { const sample = data.getInt16(index * 2, true); energy += sample * sample; }
  return Math.sqrt(energy / (bytes.length / 2));
}

/** The capture lease owns its lifetime separately from SessionController reply generations. */
export class ContinuousListeningController {
  private readonly capture: CapturePort;
  private readonly makeId: () => string;
  private run: ListeningRun | null = null;
  private state: ContinuousListeningState = 'idle';
  private ready: ContinuousListeningReady | null = null;
  private recognitionStatus: Extract<ContinuousListeningServerEvent, {type: 'recognition_status'}> | null = null;
  private processingState: CaptureProcessingState | null = null;
  private transcript: TranscriptState | null = null;
  private readonly previousPreviews: ContinuousTranscriptView[] = [];
  private readonly heldPreviews: ContinuousTranscriptView[] = [];
  private readonly sentText: SentText[] = [];
  private retiredSentText = 0;
  private serviceBudgetExhausted = false;
  private notice: string | null = null;
  private error: string | null = null;
  private closed = false;
  private releasing = false;
  private inputFence = 0;
  private readonly setTimer: (callback: () => void, milliseconds: number) => ReturnType<typeof setTimeout>;
  private readonly clearTimer: (timer: ReturnType<typeof setTimeout>) => void;

  constructor(private readonly options: ContinuousListeningControllerOptions) {
    if (options.silenceMilliseconds !== undefined && (!Number.isInteger(options.silenceMilliseconds)
      || options.silenceMilliseconds < 250 || options.silenceMilliseconds > 2000)) throw new RangeError('Quiet duration must be 250–2000 ms');
    // Native Window timers require their global receiver. Storing the native
    // function directly and calling this.setTimer throws only in the browser.
    this.setTimer = options.setTimer ?? ((callback, milliseconds) => globalThis.setTimeout(callback, milliseconds));
    this.clearTimer = options.clearTimer ?? (timer => globalThis.clearTimeout(timer));
    this.makeId = options.createId ?? (() => crypto.randomUUID());
    this.capture = (options.createCapture ?? (settings => new MicrophoneCapture(settings)))({
      onChunk: chunk => this.captureChunk(chunk),
      onState: state => {
        const run = this.run;
        if (!run || run.stopping) return;
        if (state === 'recording') {
          run.captured = true;
          if (run.ready) this.setState('listening');
        }
      },
      onError: problem => this.captureError(problem),
      onProcessing: state => {
        this.processingState = state === null ? null : Object.freeze({
          echoCancellationRequested: true,
          echoCancellationSupported: typeof state.echoCancellationSupported === 'boolean'
            ? state.echoCancellationSupported : null,
          echoCancellationReported: typeof state.echoCancellationReported === 'boolean'
            ? state.echoCancellationReported : null,
        });
        this.publish();
      },
      chunkMilliseconds: 40,
      maxPendingChunks: 8,
    });
    this.publish();
  }

  get active(): boolean { return this.run !== null && !this.run.stopping; }
  get microphoneActive(): boolean { return this.active; }
  /** Observable capture/ASR occupancy, not semantic or acoustic certainty. */
  get backgroundOutputBusy(): boolean {
    const run=this.run;
    return !!run && (run.ready===null || run.commitInFlight || !!run.pendingHold || !!run.localEndpoint
      || (this.transcript?.textLength??0)>0 || this.localEndpointEnabled(run)
        && (run.localMeaningful || run.localHasText || run.localQuietSamples<this.quietSamples(run)));
  }

  /** Returns a retained preview for an empty-composer UI action; never submits it. */
  restorePreviousPreview(leaseId: string): string | null {
    const index = this.previousPreviews.findIndex(preview => preview.lease_id === leaseId);
    if (index < 0) return null;
    const [preview] = this.previousPreviews.splice(index, 1);
    this.publish();
    return preview?.text ?? null;
  }

  restoreHeldPreview(leaseId: string, utteranceId: string): string | null {
    const index = this.heldPreviews.findIndex(preview => preview.lease_id === leaseId && preview.utterance_id === utteranceId);
    if (index < 0) return null;
    const [preview] = this.heldPreviews.splice(index, 1);
    this.publish();
    return preview?.text ?? null;
  }

  /** A user-reviewed recovery consumes exactly one retained revision; it grants no ASR commit. */
  restoreHeldInput(leaseId: string, utteranceId: string, revision: number): RecoveredVoiceInput | null {
    const index = this.heldPreviews.findIndex(preview => preview.lease_id === leaseId
      && preview.utterance_id === utteranceId && preview.revision === revision);
    if (index < 0) return null;
    const [preview] = this.heldPreviews.splice(index, 1);
    this.publish();
    return preview ? {text: preview.text, continuationTarget: preview.continuation_target ?? null} : null;
  }

  private pendingTextCount(): number {
    return this.sentText.filter(item => item.state !== 'sent' || item.correction !== undefined).length;
  }

  /** Explicit transfer to the empty composer; unreviewed/uncertain text is never evicted. */
  restoreSentText(commitId: string, correction = false): string | null {
    const index = this.sentText.findIndex(item => item.commit_id === commitId);
    const item = this.sentText[index];
    if (!item || item.state === 'sending') return null;
    if (correction && item.correction) {
      const text = item.correction.text;
      const {correction: _reviewed, ...remaining} = item;
      this.sentText[index] = remaining; this.compactHistory(this.run); this.publish(); return text;
    }
    if (!correction && (item.state === 'not_sent' || item.state === 'unknown')) {
      // Preserve a distinct correction until the user explicitly transfers it too.
      if (item.correction) this.sentText[index] = {...item, notice: '原文已复制到文字框供核对；更正仍保留。'};
      else this.sentText.splice(index, 1);
      this.compactHistory(this.run); this.publish(); return item.text;
    }
    return null;
  }

  private compactHistory(run: ListeningRun | null): void {
    let settled = this.sentText.filter(item => item.state === 'sent' && !item.correction).length;
    for (let index = 0; settled > MAX_SETTLED_RECORDS && index < this.sentText.length;) {
      const item = this.sentText[index]!;
      if (item.state === 'sent' && !item.correction) {
        this.sentText.splice(index, 1); settled--; this.retiredSentText++;
      } else index++;
    }
    if (!run) return;
    for (const [utterance, attempt] of run.automaticAttempts) {
      if (run.automaticAttempts.size <= MAX_SETTLED_RECORDS) break;
      const record = this.sentText.find(item => item.commit_id === attempt.commitId);
      if (record && (record.state !== 'sent' || record.correction) || this.transcript?.utterance_id === utterance) continue;
      // Absolute revision/source fences survive removal of exact settled identities.
      run.staleRevisionFence = Math.max(run.staleRevisionFence, attempt.revision);
      run.automaticAttempts.delete(utterance); run.corrections.delete(utterance);
      run.committedResetRevisions.delete(attempt.commitId); run.manualOnlyUtterances.delete(utterance);
    }
    for (const [utterance, source] of run.manualOnlyUtterances) {
      if (source.sourceEnd > run.settledSourceEnd || this.transcript?.utterance_id === utterance
        || this.heldPreviews.some(preview => preview.utterance_id === utterance)) continue;
      run.staleRevisionFence = Math.max(run.staleRevisionFence, source.revision);
      run.manualOnlyUtterances.delete(utterance);
    }
    while (run.holdAttempts.size > MAX_SETTLED_RECORDS) run.holdAttempts.delete(run.holdAttempts.values().next().value!);
    while (run.committedResetRevisions.size > MAX_SETTLED_RECORDS) run.committedResetRevisions.delete(run.committedResetRevisions.keys().next().value!);
    while (run.playbackRanges.length && run.playbackRanges[0]!.end <= run.settledSourceEnd) run.playbackRanges.shift();
  }

  /** Starts capture synchronously in the click gesture; silence is sent as ordinary PCM frames. */
  start(): boolean {
    if (this.closed || this.releasing || this.run) return false;
    if (this.serviceBudgetExhausted || this.pendingTextCount() >= MAX_PENDING_RECORDS) {
      this.notice = this.serviceBudgetExhausted
        ? '共享语音服务次数已用尽，不能通过重开聆听重置；已有文字可核对后发送。'
        : '待处理文字已达保留容量。请先把未发送文字放入空文字框核对，再继续聆听。';
      this.publish(); return false;
    }
    if (this.heldPreviews.length >= MAX_HELD_PREVIEWS) {
      this.notice = '已保留 12 段待核对语音。请先把一段放入空文字框并核对，再继续聆听。';
      this.publish(); return false;
    }
    if (!this.archiveCurrentTranscript() || this.previousPreviews.length >= MAX_PREVIOUS_PREVIEWS) {
      this.notice = '上次聆听的预览已满 4 段。请先把其中一段放入空文字框并核对（不会自动发送），再开始新的监听。';
      this.publish(); return false;
    }
    if (this.options.canStart && !this.options.canStart()) {
      this.notice = '请先结束当前的按住说话输入或关闭原始开发录制，再开始连续聆听。';
      this.publish(); return false;
    }
    const leaseId = this.makeId();
    if (!UUID.test(leaseId)) { this.setError('无法开始连续聆听：会话标识无效。'); return false; }
    let bargeInMode: LocalBargeInMode;
    try {
      bargeInMode = this.options.mode === 'natural' ? this.options.bargeInMode?.() ?? 'headphones' : 'guarded';
      if (bargeInMode !== 'guarded' && bargeInMode !== 'headphones') throw new Error('Invalid mode');
    } catch { this.setError('请先选择语音插话开启或关闭，再开始聆听。'); return false; }
    const prepareStart = this.options.mode === 'natural'
      ? this.options.prepareInputFromGesture ?? this.options.interruptReply : this.options.interruptReply;
    if (prepareStart) {
      try {
        if (!prepareStart()) {
          this.setError('当前回复未能安全停止，连续聆听没有启动。请使用“停止回应”后重试。');
          return false;
        }
      } catch {
        this.setError('当前回复未能安全停止，连续聆听没有启动。请使用“停止回应”后重试。');
        return false;
      }
    }
    const run: ListeningRun = {leaseId, bargeInMode, bargeDetector: new LocalBargeInDetector(bargeInMode), bargeInvalid: false,
      bargeSuspended: false, bargeAttemptEnds: [],
      abort: new AbortController(), queue: [], queueBytes: 0,
      stream: null, ready: null, captured: false, stopping: false, latestRevision: 0,
      staleRevisionFence: 0, commitCount: 0, commitInFlight: false,
      onsetActiveSamples: 0, onsetQuietSamples: 0, onsetLatched: false,
      preserveAcceptedCommit: false, stopPromise: null, automaticAttempts: new Map(), manualOnlyUtterances: new Map(),
      committedResetRevisions: new Map(), corrections: new Map(),
      holdAttempts: new Set(), pendingHold: null, heldCandidate: null,
      playbackRanges: [], playbackUnknown: false, bargeEvidence: null, settledSourceEnd: 0, localSamples: 0, localActivityVersion: 0, localQuietSamples: 0, localActiveSamples: 0, noiseFloor: 40, noiseProbeEnergy: 0, noiseProbeSamples: 0,
      localMeaningful: false, localVoiceLatched: false, localHasText: false, localEndpoint: null, endpointTimer: null, quietWaiters: new Set()};
    this.run = run; this.ready = null; this.recognitionStatus = null; this.notice = null; this.error = null;
    this.state = 'starting'; this.publish();
    let capturePromise: Promise<boolean>;
    try {
      // Calling start before any await preserves the browser's user-gesture permission boundary.
      capturePromise = this.capture.start();
      if (!this.current(run)) {
        void Promise.resolve(capturePromise).catch(() => {});
        return false;
      }
      run.stream = this.options.openStream(leaseId, run.abort.signal, {
        onEvent: event => this.transportEvent(run, event),
        onError: problem => this.transportError(run, problem),
      }, this.options.mode ?? 'manual');
    } catch (problem) {
      this.failRun(run, problem instanceof Error ? problem : new Error('Continuous listening could not start.'));
      return false;
    }
    void Promise.resolve(capturePromise).then(started => {
      if (!this.current(run)) return;
      if (!started) this.failRun(run, new Error('麦克风没有启动，请检查权限后重试。'), true);
    }).catch(problem => this.failRun(run, problem instanceof Error ? problem : new Error('麦克风启动失败。'), true));
    void run.stream.ready.then(ready => {
      if (!this.current(run)) return;
      run.ready = ready; this.ready = ready;
      this.drainQueue(run);
      if (!this.current(run)) return;
      if (run.captured) this.setState('listening');
      else this.publish();
    }).catch(problem => {
      if (this.current(run)) this.failRun(run, problem instanceof Error ? problem : new Error('连续聆听连接失败。'));
    });
    void run.stream.closed.then(() => {
      if (this.current(run) && !run.stopping) this.failRun(run, new Error('连续聆听连接意外结束。'));
    });
    return true;
  }

  private current(run: ListeningRun): boolean { return !this.closed && this.run === run && !run.stopping; }

  private archiveCurrentTranscript(): boolean {
    const current = this.transcript;
    if (!current) return true;
    if (!hasWords(current.text)) { this.transcript = null; return true; }
    if (this.previousPreviews.some(preview => preview.lease_id === current.lease_id)) {
      this.transcript = null; return true;
    }
    if (this.previousPreviews.length >= MAX_PREVIOUS_PREVIEWS) return false;
    this.previousPreviews.push(Object.freeze({...current, can_send: false,
      hint: '上次聆听的未发送/临时预览；其中可能包含下方另列的已确认文字。请核对后再放入空文字框；不会自动发送。'}));
    this.transcript = null;
    return true;
  }

  private captureChunk(chunk: CapturedAudio): void {
    const run = this.run;
    if (!run || !this.current(run)) throw new Error('连续聆听已停止。');
    const playbackBusy = this.playbackBusy();
    const barge = run.bargeDetector.observe(chunk, {playbackBusy, noiseFloor: run.noiseFloor});
    if (barge.kind === 'invalid' && !run.bargeInvalid) {
      run.bargeInvalid = true; run.bargeSuspended = false;
      if (run.bargeInMode === 'headphones') {
        this.notice = '本次采集不能用于自动插话，请使用打断按钮；已收到的文字会保留。';
        this.publish();
      }
    }
    if (this.options.mode === 'natural' && playbackBusy) {
      // A recognition segment also contains quiet PCM between turns. Mark only
      // potentially audible overlap; quiet during headphone playback must not
      // taint the next clean phrase. This is energy evidence, not echo identity.
      const rms = capturedRms(chunk);
      if (rms === null) run.playbackUnknown = true;
      else if (rms >= Math.max(90, Math.min(180, run.noiseFloor * 1.5))) {
        let target: SessionContinuationTarget | null = null;
        try { target = this.options.captureReplyContinuation?.() ?? null; } catch { /* Unknown provenance stays unlinked. */ }
        const previous = run.playbackRanges.at(-1);
        if (previous && previous.target === target && previous.end >= chunk.startSample) previous.end = Math.max(previous.end, chunk.endSample);
        else if (run.playbackRanges.length < 64) run.playbackRanges.push({start: chunk.startSample, end: chunk.endSample, target});
        else run.playbackUnknown = true;
      }
      run.onsetActiveSamples = 0; run.onsetQuietSamples = 0; run.onsetLatched = false;
      if (run.bargeInMode === 'guarded') {
        run.localMeaningful = false; run.localActiveSamples = 0; run.localQuietSamples = 0; run.localVoiceLatched = false;
      } else {
        // End-of-speech and early energy interruption are independent. A soft
        // phrase still reaches the normal quiet/final endpoint if barge-in misses.
        this.detectLocalQuiet(run, chunk, false);
      }
      if (barge.kind === 'qualified') this.tryHeadphoneInterruption(run, barge);
    } else if (this.localEndpointEnabled(run) || (this.options.mode === 'natural' && run.ready === null)) this.detectLocalQuiet(run, chunk);
    else this.detectCapturedOnset(run, chunk);
    if (!this.current(run)) throw new Error('连续聆听已停止。');
    if (run.stream && run.ready) { run.stream.send(chunk); this.maybeEndpoint(run); return; }
    if (run.queue.length >= 100 || run.queueBytes + chunk.pcm16le.byteLength > 65536) {
      this.failRun(run, new Error('连接尚未就绪，音频队列已达上限。'));
      throw new Error('连续聆听音频队列已达上限。');
    }
    run.queue.push({...chunk, pcm16le: chunk.pcm16le.slice()});
    run.queueBytes += chunk.pcm16le.byteLength;
  }

  private tryHeadphoneInterruption(run: ListeningRun, result: LocalBargeInResult): void {
    const start = result.startSample, end = result.endSample;
    if (run.bargeInMode !== 'headphones' || result.kind !== 'qualified'
      || start === null || end === null || !this.current(run) || run.bargeSuspended) return;
    while (run.bargeAttemptEnds.length && end - run.bargeAttemptEnds[0]! > BARGE_BURST_WINDOW_SAMPLES) {
      run.bargeAttemptEnds.shift();
    }
    run.bargeAttemptEnds.push(end);
    run.bargeSuspended = run.bargeAttemptEnds.length >= BARGE_BURST_ATTEMPTS;
    const pausedNotice = run.bargeSuspended
      ? '短时间内连续触发，自动插话已暂停；麦克风仍在聆听。可点击恢复语音插话，或停止聆听后关闭语音插话。' : '';
    let target: SessionContinuationTarget | null = null;
    try { target = this.options.captureReplyContinuation?.() ?? null; } catch { /* Unknown source stays held. */ }
    let stopped = false;
    try { stopped = this.options.interruptReply?.() === true && !this.playbackBusy(); }
    catch { /* An uncertain stop cannot approve overlap. */ }
    if (!this.current(run)) return;
    if (!stopped) {
      this.notice = '这次声音活动未能提前打断回应；转写会继续，说完后会再次尝试发送。' + pausedNotice;
      this.publish(); return;
    }
    // Keep overlap and its request provenance until a final can be correlated.
    // The detector qualifies this Stop, while the finalized utterance determines
    // which earlier samples (including soft speech and pauses) belong with it.
    const range = run.playbackRanges.find(value => value.start <= start && value.end >= end);
    run.bargeEvidence = target && range?.target === target
      ? {candidateStart: start, end, target} : null;
    run.localSamples = end; run.localMeaningful = true;
    run.localActiveSamples = 1920; run.localQuietSamples = 0;
    run.localVoiceLatched = true; run.localActivityVersion++;
    if (run.localEndpoint && !run.localEndpoint.cancelled) {
      run.localEndpoint.cancelled = true;
      try { run.stream?.cancelEndpoint?.(run.localEndpoint.id); }
      catch { this.failRun(run, new Error('语音分句取消未确认，文字已保留；请核对后继续。')); return; }
    }
    this.notice = '检测到持续声音活动，已打断回应，继续聆听。' + pausedNotice;
    this.publish();
  }

  /** An explicit UI gesture may clear a burst pause, never capture validity or old overlap. */
  resumeAutomaticInterruption(): boolean {
    const run = this.run;
    if (!run || !this.current(run) || run.bargeInMode !== 'headphones' || run.bargeInvalid || !run.bargeSuspended) return false;
    run.bargeAttemptEnds.length = 0; run.bargeSuspended = false;
    this.notice = '语音插话已恢复，建议使用耳机；说完后仍按正常停顿发送。';
    this.publish(); return true;
  }

  private localEndpointEnabled(run: ListeningRun): boolean {
    return this.naturalEnabled(run) && run.ready?.client_endpoint_supported === true;
  }

  private quietSamples(run: ListeningRun): number {
    return (this.options.silenceMilliseconds ?? run.ready?.client_silence_ms ?? 700) * 16;
  }

  /** One bounded sample clock. ASR revisions can arm soft speech, never restart quiet. */
  private detectLocalQuiet(run: ListeningRun, chunk: CapturedAudio, interruptOnOnset = true): void {
    const bytes = chunk.pcm16le;
    if (!(bytes instanceof Uint8Array) || bytes.length < 2 || bytes.length % 2 !== 0
      || bytes.length > 3200 || chunk.sampleRate !== 16000 || chunk.channels !== 1) return;
    const count = bytes.length / 2, view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let energy = 0;
    for (let i = 0; i < count; i++) { const value = view.getInt16(i * 2, true); energy += value * value; }
    const rms = Math.sqrt(energy / count);
    run.localSamples = chunk.endSample;
    // Learn only bounded low ambient energy, never a loud speaking level. A
    // measured drop below the release floor can become quiet immediately;
    // neither ASR revisions nor a fixed 90-RMS background keep restarting it.
    const onsetFloor = Math.max(400, run.noiseFloor * 3);
    const releaseFloor = Math.max(180, run.noiseFloor * 2);
    const softFloor = Math.max(90, run.noiseFloor * 2.5);
    const active = run.localVoiceLatched ? rms >= releaseFloor
      : rms >= onsetFloor || (run.localHasText && rms >= softFloor);
    const quiet = run.localVoiceLatched ? !active : rms < softFloor;
    const ambientProbe = rms < 400 && (!run.localMeaningful && !run.localHasText
      || run.localVoiceLatched && !active);
    if (ambientProbe) {
      run.noiseProbeEnergy += energy; run.noiseProbeSamples += count;
      const required = run.localVoiceLatched ? 3200 : 8000;
      if (run.noiseProbeSamples >= required) {
        run.noiseFloor = Math.min(300, Math.sqrt(run.noiseProbeEnergy / run.noiseProbeSamples));
        run.noiseProbeEnergy = 0; run.noiseProbeSamples = 0;
      }
    } else { run.noiseProbeEnergy = 0; run.noiseProbeSamples = 0; }
    if (!quiet) run.localQuietSamples = 0;
    else run.localQuietSamples = Math.min(32000, run.localQuietSamples + count);
    if (active) {
      run.localActiveSamples = Math.min(1920, run.localActiveSamples + count);
      if (run.localActiveSamples >= 1920) run.localMeaningful = true;
      if (!run.localVoiceLatched && run.localActiveSamples >= 640) {
        run.localVoiceLatched = true; run.localActivityVersion++;
        if (run.localEndpoint && !run.localEndpoint.cancelled) {
          run.localEndpoint.cancelled = true;
          try { run.stream?.cancelEndpoint?.(run.localEndpoint.id); }
          catch { this.failRun(run, new Error('语音分句取消未确认，文字已保留；请核对后继续。')); return; }
        }
        try { if (interruptOnOnset) this.options.interruptReply?.(); }
        catch { this.failRun(run, new Error('本地回复中断未能确认，文字已保留。')); return; }
      }
    } else {
      run.localActiveSamples = 0;
      if (run.localQuietSamples >= 3200) run.localVoiceLatched = false;
    }
    if (run.localQuietSamples >= this.quietSamples(run)) {
      for (const resolve of [...run.quietWaiters]) resolve(true);
    }
  }

  private maybeEndpoint(run: ListeningRun): void {
    if (!this.current(run) || !this.localEndpointEnabled(run) || !run.stream?.endpoint
      || run.localEndpoint || run.commitInFlight || run.pendingHold || !run.localMeaningful
      || run.localQuietSamples < this.quietSamples(run)
      || (run.bargeInMode === 'guarded' && this.playbackBusy())) return;
    const id = this.makeId();
    if (!UUID.test(id)) { this.failRun(run, new Error('语音分句标识无效，文字已保留。')); return; }
    run.localEndpoint = {id, sourceEnd: run.localSamples, cancelled: false, state: 'awaiting_delivery'};
    try { run.stream.endpoint(id, run.localSamples); }
    catch { this.failRun(run, new Error('语音分句未能发送，文字已保留，可使用文字输入。')); return; }
    this.armEndpointTimer(run, id);
    this.notice = '正在整理这段话……'; this.publish();
  }

  private armEndpointTimer(run: ListeningRun, id: string): void {
    this.clearEndpointTimer(run);
    run.endpointTimer = this.setTimer(() => {
      if (this.current(run) && run.localEndpoint?.id === id) this.failRun(run,
        new Error('等待语音最终转写超时，已停止聆听；已有文字保留，可核对后用文字发送。'));
    }, (run.ready?.drain_timeout_ms ?? 2000) + 1000);
  }

  private clearEndpointTimer(run: ListeningRun): void {
    if (run.endpointTimer !== null) this.clearTimer(run.endpointTimer);
    run.endpointTimer = null;
  }

  /** Gates only a reply's first dispatch; every later PCM packet uses the existing queue. */
  waitForReplyQuiet(signal: AbortSignal): Promise<boolean> {
    const run = this.run;
    if (signal.aborted || this.closed) return Promise.resolve(false);
    if (!run || !this.localEndpointEnabled(run)) return Promise.resolve(true);
    if (run.localQuietSamples >= this.quietSamples(run)) return Promise.resolve(true);
    return new Promise(resolve => {
      const finish = (quiet: boolean): void => {
        this.clearTimer(timer); run.quietWaiters.delete(finish); signal.removeEventListener('abort', abort); resolve(quiet);
      };
      const abort = (): void => finish(false);
      const timer = this.setTimer(() => finish(false), 10000);
      run.quietWaiters.add(finish); signal.addEventListener('abort', abort, {once: true});
    });
  }

  /** Uses only fresh, bounded captured PCM; transcript revisions never participate. */
  private detectCapturedOnset(run: ListeningRun, chunk: CapturedAudio): void {
    const bytes = chunk.pcm16le;
    if (!(bytes instanceof Uint8Array) || bytes.byteLength < 2 || bytes.byteLength % 2 !== 0
      || bytes.byteLength > MAX_ONSET_SAMPLES_PER_CHUNK * 2 || chunk.sampleRate !== 16000 || chunk.channels !== 1) return;
    const count = bytes.byteLength / 2, view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let sumSquares = 0;
    for (let index = 0; index < count; index++) {
      const sample = view.getInt16(index * 2, true);
      sumSquares += sample * sample;
    }
    const aboveFloor = Math.sqrt(sumSquares / count) >= ONSET_RMS_FLOOR;
    if (aboveFloor) {
      run.onsetActiveSamples = Math.min(ONSET_MIN_ACTIVE_SAMPLES, run.onsetActiveSamples + count);
      run.onsetQuietSamples = 0;
    } else {
      run.onsetActiveSamples = 0;
      run.onsetQuietSamples = Math.min(ONSET_QUIET_RESET_SAMPLES, run.onsetQuietSamples + count);
      if (run.onsetQuietSamples >= ONSET_QUIET_RESET_SAMPLES) run.onsetLatched = false;
    }
    if (run.onsetLatched || run.onsetActiveSamples < ONSET_MIN_ACTIVE_SAMPLES) return;
    run.onsetLatched = true;
    try {
      if (this.options.interruptReply && !this.options.interruptReply()) {
        // A non-reply can be present while a lease is active; in that case the
        // one-shot detector stays latched, avoiding repeated work on the same sound.
        return;
      }
    } catch {
      this.failRun(run, new Error('本地回复中断未能确认，连续聆听已停止以免漏掉新输入。'));
      return;
    }
    this.notice = '检测到新的本地声音活动，已尝试中断当前回复；能量阈值可能受噪声或扬声器回声影响。';
    this.publish();
  }

  private drainQueue(run: ListeningRun): void {
    if (!this.current(run) || !run.stream || !run.ready) return;
    try {
      for (const chunk of run.queue) {
        if (!this.current(run)) return;
        run.stream.send(chunk);
      }
      run.queue.length = 0; run.queueBytes = 0;
      this.maybeEndpoint(run);
    } catch (problem) {
      this.failRun(run, problem instanceof Error ? problem : new Error('音频发送失败。'));
    }
  }

  private transportEvent(run: ListeningRun, event: ContinuousListeningServerEvent): void {
    if (!this.current(run)) return;
    if (event.type === 'ready') {
      // The ready promise is authoritative; this frame remains observable but does not reset state.
      return;
    }
    if (event.lease_id !== run.leaseId) return;
    if (event.type === 'transcript') {
      if (event.revision <= run.latestRevision) return;
      run.latestRevision = event.revision;
      const committed = event.committed_utterance_id ? run.automaticAttempts.get(event.committed_utterance_id) : undefined;
      const correlatedReset = committed !== undefined && event.committed_commit_id === committed.commitId
        && event.revision === committed.revision + 1;
      if (correlatedReset) run.committedResetRevisions.set(committed.commitId, event.revision);
      const text = event.text.slice(0, 2000);
      const truncated = event.text.length > 2000;
      const isFinal = event.is_final;
      this.transcript = Object.freeze({lease_id: run.leaseId, revision: event.revision, text,
        textLength: text.length, is_final: isFinal, endpoint_pending: false,
        stable: isFinal, review_required: correlatedReset && hasWords(text),
        can_send: (isFinal || this.transcript?.endpoint_pending === true)
          && hasWords(text) && !truncated && event.revision > run.staleRevisionFence && !run.commitInFlight && !run.pendingHold,
        truncated, hint: this.naturalEnabled(run) ? '正在识别并等待这段话结束；也可手动发送当前稳定文字。'
          : isFinal ? '识别器标记了一个稳定片段；它不保证完整句尾。点击发送后只提交服务端确认的文字。'
          : '临时转写仍可能变化，不会自动发送。'});
      if (correlatedReset && !text) this.transcript = null;
      if (this.localEndpointEnabled(run) && !correlatedReset && !run.commitInFlight && hasWords(text) && (run.bargeInMode !== 'guarded' || !this.playbackBusy())) {
        run.localHasText = true; run.localMeaningful = true; this.maybeEndpoint(run);
      }
      this.notice = null; this.publish();
    } else if (event.type === 'endpoint_pending') {
      if (event.revision < run.latestRevision) return;
      if (event.revision > run.latestRevision) run.latestRevision = event.revision;
      // An endpoint hint describes the stable prefix, not a replacement recognition
      // result. Keep a richer preview already observed at this same revision.
      const prior = this.transcript?.lease_id === run.leaseId
        && this.transcript.revision === event.revision ? this.transcript : null;
      const text = prior?.text ?? event.text.slice(0, 2000);
      const truncated = prior?.truncated ?? event.text.length > 2000;
      this.transcript = Object.freeze({lease_id: run.leaseId, revision: event.revision, text,
        textLength: text.length, is_final: prior?.is_final ?? false, endpoint_pending: true,
        stable: prior?.stable ?? false,
        can_send: event.can_submit_manually === true && hasWords(text) && !truncated
          && event.revision > run.staleRevisionFence && !run.commitInFlight && !run.pendingHold,
        truncated, hint: this.naturalEnabled(run)
          ? '正在识别；说完后会自动发送，也可使用手动发送备用按钮。'
          : event.can_submit_manually === true
          ? '句末对齐尚未确认。发送前请核对；麦克风会继续聆听。'
          : '句末对齐尚未确认，当前服务器不允许手动提交；麦克风仍在聆听。'});
      this.notice = null; this.publish();
    } else if (event.type === 'endpoint_status') {
      const pending = run.localEndpoint;
      if (!pending || event.endpoint_id !== pending.id || event.source_end_sample !== pending.sourceEnd) return;
      // Frontend PCM delivery and provider final drain are separately bounded.
      // A repeated status cannot repeatedly reset the drain deadline.
      if (pending.state === 'awaiting_delivery' && (event.state === 'queued' || event.state === 'draining')) {
        this.armEndpointTimer(run, pending.id);
      }
      pending.state = event.state;
      if (event.state === 'cancelled') {
        this.clearEndpointTimer(run); run.localEndpoint = null; this.maybeEndpoint(run);
      }
      this.publish();
    } else if (event.type === 'utterance_ready') {
      this.utteranceReady(run, event);
    } else if (event.type === 'utterance_revision') {
      this.utteranceRevision(run, event);
    } else if (event.type === 'recognition_status') {
      if (event.stream_index < (this.recognitionStatus?.stream_index ?? 0)) return;
      this.recognitionStatus = Object.freeze({...event}); this.publish();
    } else if (event.type === 'utterance_held' || event.type === 'hold_rejected') {
      // Settle on frame receipt too, so a valid next-activity frame in the same
      // host task is not misclassified while the promise continuation is queued.
      this.finishHold(run, event);
    } else if (event.type === 'commit_ready' || event.type === 'commit_rejected') {
      // commit() resolves this exact frame to the user action that initiated it.
    } else if (event.type === 'stopped') {
      if (event.reason === 'service_budget_exhausted') this.serviceBudgetExhausted = true;
      const limit = ['max_duration', 'max_samples', 'utterance_limit', 'revision_limit', 'input_limit'].includes(event.reason);
      this.endRun(run, limit ? 'limit' : 'stopped', this.serviceBudgetExhausted
          ? '共享语音服务次数已用尽，麦克风已关闭；已识别文字仍保留，可核对后用文字发送。不会自动重开或重置额度。'
        : limit
          ? '本条连续聆听已到达主动配置的时长、发送或识别次数上限。不会自动续开；如需继续，请再次点击开始。'
        : event.reason === 'quota_exhausted'
          ? 'Google 语音识别报告配额或服务使用限制，麦克风已停止。已识别文字仍保留，可核对后用文字发送；请检查服务配额后再手动开启。'
        : ['incomplete_stream', 'timeout', 'invalid_response'].includes(event.reason)
          ? '语音识别未能获得完整最终文字或已达服务上限，已停止聆听；已有预览保留，可核对后用文字发送。'
        : event.reason === 'user_stop' || event.reason === 'permission_lost'
          ? '连续聆听已停止。已收到的文字仍保留在这里，可继续核对。'
          : '连续聆听已结束。麦克风已释放，已收到的文字仍保留在这里。', false, 'user_stop', limit || event.reason === 'service_budget_exhausted');
    }
  }

  private naturalEnabled(run: ListeningRun | null = this.run): boolean {
    const ready = run?.ready ?? this.ready;
    return this.options.mode === 'natural' && ready?.endpoint_mode === 'google_vad_offsets_natural'
      && ready.manual_commit_required === false;
  }

  private interruptionCurrent(target: SessionContinuationTarget): boolean {
    try { return this.options.isInterruptedReplyCurrent?.(target) === true; } catch { return false; }
  }

  private replySourceCurrent(target: SessionContinuationTarget): boolean {
    try { return this.options.isReplyContinuationCurrent?.(target) ?? this.interruptionCurrent(target); }
    catch { return false; }
  }

  private playbackBusy(): boolean {
    try { return this.options.isPlaybackBusy?.() !== false; } catch { return true; }
  }

  private utteranceReady(run: ListeningRun,
      event: Extract<ContinuousListeningServerEvent, {type: 'utterance_ready'}>): void {
    if (!this.naturalEnabled(run) || event.revision < run.latestRevision) return;
    // Transport validates the wire; retain the fence here for injected/test ports too.
    const basis = event.endpoint_basis ?? 'offset_coverage', final = event.final_offset_samples;
    if (!UUID.test(event.utterance_id) || event.begin_offset_samples < 0
      || event.begin_offset_samples > event.end_offset_samples || event.end_offset_samples > event.source_end_sample
      || !run.ready || (run.ready.max_samples !== null && event.source_end_sample > run.ready.max_samples)
      || (final === null ? !['stream_finalized', 'client_silence_finalized'].includes(basis) : final < event.begin_offset_samples || final > event.source_end_sample)
      || (basis === 'offset_coverage' && (final === null || event.end_offset_samples > final))
      || (basis === 'vad_final_grace' && !(run.ready?.natural_grace_ms && run.ready.natural_grace_ms > 0))) return;
    const local = basis === 'client_silence_finalized' ? run.localEndpoint : null;
    if (basis === 'client_silence_finalized' && (!local || event.client_endpoint_id !== local.id || event.source_end_sample !== local.sourceEnd)) return;
    if (this.localEndpointEnabled(run) && basis !== 'client_silence_finalized') return;
    const resumed = local?.cancelled === true;
    if (local) {
      this.clearEndpointTimer(run); run.localEndpoint = null;
      if (!resumed) { run.localMeaningful = false; run.localHasText = false; }
    }
    const priorAttempt = run.automaticAttempts.get(event.utterance_id);
    if (priorAttempt && event.revision <= priorAttempt.revision) return;
    run.latestRevision = event.revision;
    const sourceRanges = run.playbackRanges.filter(range => range.start < event.end_offset_samples
      && range.end > event.begin_offset_samples);
    const sourceTarget = sourceRanges[0]?.target;
    const continuationTarget = !run.playbackUnknown && sourceTarget
      && sourceRanges.every(range => range.target === sourceTarget) ? sourceTarget : null;
    const staleSource = event.begin_offset_samples < run.settledSourceEnd;
    const evidence = run.bargeEvidence;
    const correlated = evidence !== null && event.begin_offset_samples <= evidence.candidateStart
      && event.end_offset_samples >= evidence.end && event.source_end_sample >= evidence.end;
    // Once a final reaches this Stop, its capability cannot approve a second utterance.
    if (correlated) run.bargeEvidence = null;
    const promoted = correlated && !staleSource && !run.bargeInvalid && !run.playbackUnknown
      && continuationTarget === evidence.target && this.interruptionCurrent(evidence.target);
    const overlap = run.playbackUnknown || this.playbackBusy()
      || run.playbackRanges.some(range => range.start < event.source_end_sample && range.end > event.begin_offset_samples
        && !(promoted && range.target === evidence.target
          && range.end <= evidence.end));
    const guardedOverlap = run.bargeInMode === 'guarded' && overlap;
    if (guardedOverlap) {
      if (run.manualOnlyUtterances.size < 256) run.manualOnlyUtterances.set(event.utterance_id, {revision: event.revision, sourceEnd: event.end_offset_samples});
      else run.playbackUnknown = true;
    }
    const staleContinuation = continuationTarget !== null && !this.replySourceCurrent(continuationTarget);
    const review = resumed || staleSource || staleContinuation || guardedOverlap || priorAttempt !== undefined || run.manualOnlyUtterances.has(event.utterance_id) || run.corrections.has(event.utterance_id)
      || run.commitInFlight || run.pendingHold !== null
      || (run.ready.max_utterances !== null && run.commitCount >= run.ready.max_utterances);
    const text = event.text.slice(0, 2000), truncated = event.text.length > 2000;
    this.transcript = Object.freeze({lease_id: run.leaseId, revision: event.revision, text,
      textLength: text.length, is_final: true, endpoint_pending: false, stable: true,
      ...(continuationTarget ? {continuation_target: continuationTarget} : {}),
      sourceEndSample: event.end_offset_samples,
      utterance_id: event.utterance_id, auto_ready: !review, review_required: review, endpoint_basis: basis, truncated,
      can_send: hasWords(text) && !truncated && !run.commitInFlight && !run.pendingHold && event.revision > run.staleRevisionFence,
      hint: guardedOverlap ? '已选择保守模式：这段采集与回复播放重叠，请核对后手动发送。'
        : review ? '这段文字需要核对，不会自动重发；可使用手动发送。'
          : basis === 'client_silence_finalized' ? '本地停顿后的识别已结束，正在发送；音量判断可能受噪声影响。'
          : basis === 'vad_final_grace' ? '已根据停顿和稳定转写自动分句，正在发送；如有后续更正会保留供核对。'
            : basis === 'stream_finalized' ? '本段识别已结束，正在自动发送。'
              : '语音活动已结束，稳定文字已覆盖句末，正在自动提交。'});
    this.notice = null; this.publish();
    if (review) {
      const index = this.heldPreviews.findIndex(preview => preview.lease_id === run.leaseId && preview.utterance_id === event.utterance_id);
      if (index >= 0) this.heldPreviews[index] = this.transcript;
      else if (this.heldPreviews.length < MAX_HELD_PREVIEWS) this.heldPreviews.push(this.transcript);
      else {
        this.endRun(run, 'limit', '待核对语音已满 12 段，本段也已保留。请先恢复一段到空文字框，再继续聆听。', true);
        return;
      }
      this.publish();
      if (basis === 'stream_finalized' || basis === 'client_silence_finalized') {
        run.heldCandidate = {utteranceId: event.utterance_id, revision: event.revision, text, sourceEnd: event.end_offset_samples};
        this.flushHeldCandidate(run);
      }
    }
    if (!review && this.transcript.can_send) void this.sendTranscript(run, this.transcript, event.utterance_id);
  }

  /** Non-Input settlement has its own queue; model-input attempts never consume it. */
  private flushHeldCandidate(run: ListeningRun): void {
    if (!this.current(run) || !run.heldCandidate || run.commitInFlight || run.pendingHold
      || !run.ready || (run.ready.max_utterances !== null && run.commitCount >= run.ready.max_utterances)) return;
    const candidate = run.heldCandidate;
    run.heldCandidate = null;
    if (run.holdAttempts.has(`${candidate.utteranceId}:${candidate.revision}`)) return;
    if (candidate.revision !== run.latestRevision) {
      this.failRun(run, new Error('暂缓语音已被新的识别状态取代，已停止聆听；文字仍保留，可核对后手动发送。'));
      return;
    }
    void this.holdCurrent(run, candidate.utteranceId, candidate.revision, candidate.text, candidate.sourceEnd);
  }

  private async holdCurrent(run: ListeningRun, utteranceId: string, revision: number, text: string, sourceEnd?: number): Promise<void> {
    const key = `${utteranceId}:${revision}`;
    if (!this.current(run) || run.holdAttempts.has(key) || run.pendingHold || run.commitInFlight) return;
    run.holdAttempts.add(key);
    run.pendingHold = {utteranceId, revision, text, ...(sourceEnd === undefined ? {} : {sourceEnd})};
    this.refreshCanSend(run); this.publish();
    if (!this.current(run)) return;
    try {
      if (!run.stream?.hold) throw new Error('Hold acknowledgement unavailable');
      const result = await run.stream.hold(utteranceId, revision);
      if (run.pendingHold?.utteranceId === utteranceId && run.pendingHold.revision === revision) {
        this.finishHold(run, result);
      }
    } catch {
      if (this.current(run)) this.failRun(run, new Error('暂缓语音的确认没有完成，已停止聆听；文字仍保留，可核对后手动发送。'));
    }
  }

  private finishHold(run: ListeningRun, result: ContinuousListeningHoldResult): void {
    const pending = run.pendingHold;
    if (!this.current(run) || !pending) return;
    if (result.lease_id !== run.leaseId || result.utterance_id !== pending.utteranceId || result.revision !== pending.revision
      || (result.type === 'utterance_held' && result.text !== pending.text)) {
      this.failRun(run, new Error('暂缓语音的确认与保留文字不一致，已停止聆听；请核对保留文字。')); return;
    }
    run.pendingHold = null;
    if (result.type === 'hold_rejected') {
      if (result.reason === 'request_limit') this.endRun(run, 'limit', '本条聆听已达上限，暂缓文字仍保留；请核对后再继续。', true);
      else this.failRun(run, new Error('暂缓语音的确认已失效，已停止聆听；文字仍保留，不会自动重试。'));
      return;
    }
    if (pending.sourceEnd !== undefined) run.settledSourceEnd = Math.max(run.settledSourceEnd, pending.sourceEnd);
    this.refreshCanSend(run);
    if (!this.current(run)) return;
    this.maybeEndpoint(run);
    this.notice = '这段文字已保留供核对，麦克风继续聆听下一段；没有提交到对话。';
    this.publish();
  }

  private utteranceRevision(run: ListeningRun,
      event: Extract<ContinuousListeningServerEvent, {type: 'utterance_revision'}>): void {
    const attempt = run.automaticAttempts.get(event.utterance_id);
    if (!attempt || attempt.commitId !== event.commit_id || event.revision <= attempt.revision
      || event.revision <= (run.corrections.get(event.utterance_id)?.revision ?? 0)) return;
    run.corrections.set(event.utterance_id, event);
    const index = this.sentText.findIndex(item => item.commit_id === event.commit_id && item.utterance_id === event.utterance_id);
    if (index >= 0) this.sentText[index] = {...this.sentText[index]!, correction: {
      revision: event.revision, text: event.text, submission_state: event.submission_state}};
    // A correction belongs to the old utterance. It must not overwrite a newer activity preview.
    if (this.transcript?.utterance_id === event.utterance_id) {
      this.transcript = Object.freeze({...this.transcript, auto_ready: false, review_required: true, can_send: false,
        hint: '识别器更正了同一段话。原文和更正在发送记录中关联保留，请核对；不会自动作为新一轮发送。'});
    }
    this.notice = '识别器更正了先前同一段话，请核对发送记录中的更正；不会自动重发。';
    this.publish();
  }

  /** User action only: asks the server to snapshot the exact visible revision before sending it. */
  async sendCurrent(): Promise<void> {
    const run = this.run, transcript = this.transcript, stream = run?.stream;
    if (!run || !this.current(run) || !stream || !transcript || transcript.lease_id !== run.leaseId
      || !transcript.can_send || run.commitInFlight || run.pendingHold) return;
    await this.sendTranscript(run, transcript);
  }

  private async sendTranscript(run: ListeningRun, transcript: TranscriptState, utteranceId?: string): Promise<void> {
    const stream = run.stream;
    if (!stream || !this.current(run) || run.commitInFlight || run.pendingHold) return;
    if (this.pendingTextCount() >= MAX_PENDING_RECORDS) {
      this.endRun(run, 'limit', '待处理文字已达保留容量，本段文字也已保留。请先恢复到空文字框核对，再继续聆听。', true);
      return;
    }
    const automatic = utteranceId !== undefined;
    if (automatic && (!this.naturalEnabled(run) || (run.bargeInMode === 'guarded' && this.playbackBusy())
      || run.automaticAttempts.has(utteranceId))) return;
    const continuation = automatic ? transcript.continuation_target : undefined;
    if (continuation && !this.replySourceCurrent(continuation)) {
      this.notice = '这段插话的原回复已被新一轮取代，文字仍保留供核对。';
      this.transcript = Object.freeze({...transcript, auto_ready: false, review_required: true});
      this.publish(); return;
    }
    const inputFence = this.inputFence;
    const activityAtCommit = run.localActivityVersion;
    const commitId = this.makeId();
    if (!UUID.test(commitId)) { this.setError('无法发送：本次请求标识无效。'); return; }
    const revision = transcript.revision;
    const prepareInput = automatic ? this.options.interruptReply
      : this.options.prepareInputFromGesture ?? this.options.interruptReply;
    if (prepareInput) {
      try {
        if (!prepareInput()) {
          this.notice = '当前回复未能安全停止，已确定文字没有发送；请点“停止回应”后重试。';
          this.refreshCanSend(run); this.publish(); return;
        }
      } catch {
        this.notice = '当前回复未能安全停止，已确定文字没有发送；请点“停止回应”后重试。';
        this.refreshCanSend(run); this.publish(); return;
      }
    }
    if (automatic) {
      run.automaticAttempts.set(utteranceId, {revision, commitId});
      this.sentText.push({commit_id: commitId, segment_seq: 0, revision, text: transcript.text,
        utterance_id: utteranceId, state: 'sending', notice: '正在确认这段语音文字，尚未提交到 MIRA。'});
    }
    run.commitInFlight = true;
    this.transcript = Object.freeze({...transcript, can_send: false});
    this.notice = null; this.publish();
    let result;
    try { result = await stream.commit(commitId, revision, utteranceId); }
    catch (problem) {
      if (this.current(run)) {
        run.commitInFlight = false;
        this.notice = '发送确认没有完成。文字仍保留；请核对当前转写后再操作。';
        this.retireUnconfirmed(run, this.notice);
        this.refreshCanSend(run); this.publish();
      }
      return;
    }
    if (this.closed || inputFence !== this.inputFence
      || (!this.current(run) && !run.preserveAcceptedCommit)) return;
    run.commitInFlight = false;
    if (result.type === 'commit_rejected') {
      this.retireUnconfirmed(run, '这段自动确认未通过，未提交到 MIRA；文字已保留，不会自动重试。');
      // A stale response names the server's current revision. Keep the requested
      // stale snapshot fenced while permitting a later explicit click on that exact one.
      run.staleRevisionFence = Math.max(run.staleRevisionFence, result.current_revision - 1);
      if (result.reason === 'request_limit') {
        this.endRun(run, 'limit', '本条连续聆听的发送次数已到上限。不会自动续开；如需继续，请再次点击开始。', true);
        return;
      }
      if (result.reason === 'lease_revoked') {
        this.endRun(run, 'error', '连续聆听许可已撤销，麦克风已释放。', true);
        return;
      }
      if (result.reason === 'identity_conflict') {
        this.endRun(run, 'error', '本次提交标识与服务端记录冲突；为避免重复，已停止聆听。', true);
        return;
      }
      this.notice = result.reason === 'pending_capacity'
        ? '服务端待处理输入已满，当前文字和聆听仍保留；请等待已有输入完成后，稍后手动发送。'
        : result.reason === 'stale_revision'
        ? '转写刚更新，请核对后再发送。'
        : '还没有服务端确认可发送的稳定文字；可以继续说或停止聆听。';
      this.refreshCanSend(run); this.publish(); return;
    }
    const correction = utteranceId === undefined ? undefined : run.corrections.get(utteranceId);
    const fenced = automatic && (result.lease_id !== run.leaseId || result.commit_id !== commitId
      || result.utterance_id !== utteranceId || result.revision !== revision || result.text !== transcript.text
      || (run.latestRevision !== revision && run.latestRevision !== run.committedResetRevisions.get(commitId))
      || correction !== undefined || this.playbackBusy()
      || (continuation !== undefined && !this.interruptionCurrent(continuation))
      || (this.localEndpointEnabled(run) && run.localActivityVersion !== activityAtCommit));
    const item: SentText = {commit_id: result.commit_id, segment_seq: result.segment_seq,
      revision: result.revision, text: result.text, state: fenced ? 'not_sent' : 'sending',
      notice: fenced ? '确认期间转写或播放状态已变化，这段文字没有自动送出；请核对后手动发送。' : null,
      ...(utteranceId === undefined ? {} : {utterance_id: utteranceId}),
      ...(correction === undefined ? {} : {correction: {revision: correction.revision,
        text: correction.text, submission_state: correction.submission_state}})};
    const pendingIndex = this.sentText.findIndex(value => value.commit_id === item.commit_id);
    if (pendingIndex < 0) this.sentText.push(item);
    else this.sentText[pendingIndex] = item;
    if (transcript.sourceEndSample !== undefined && result.lease_id === run.leaseId
      && result.commit_id === commitId && result.revision === revision && result.text === transcript.text
      && (utteranceId === undefined || result.utterance_id === utteranceId)) {
      run.settledSourceEnd = Math.max(run.settledSourceEnd, transcript.sourceEndSample);
    }
    run.commitCount++;
    run.staleRevisionFence = Math.max(run.staleRevisionFence, result.revision);
    this.refreshCanSend(run);
    this.notice = null; // Delivery is described by the record's pending/accepted result, not the commit acknowledgement.
    if (automatic && !fenced && this.transcript?.revision === revision) this.transcript = null;
    if (fenced) this.notice = item.notice;
    this.publish();
    const reachedLimit = run.ready !== null && run.ready.max_utterances !== null && run.commitCount >= run.ready.max_utterances;
    const submission = fenced ? null : this.options.submitInput(result.text, result.commit_id, continuation);
    if (reachedLimit && this.current(run)) {
      this.endRun(run, 'limit', '本条连续聆听已达到声明的发送上限。不会自动续开；如需继续，请再次点击开始。', false,
        'user_stop', true);
    }
    if (!submission) return;
    let outcome: SessionInputOutcome;
    try { outcome = await submission; }
    catch { outcome = {status: 'unknown'}; }
    this.updateSentText(item.commit_id, outcome);
  }

  private refreshCanSend(run: ListeningRun): void {
    const current = this.transcript;
    if (current?.lease_id === run.leaseId) {
      const eligible = current.stable || current.endpoint_pending;
      this.transcript = Object.freeze({...current,
        ...(current.utterance_id && run.automaticAttempts.has(current.utterance_id) ? {auto_ready: false, review_required: true} : {}),
        can_send: eligible && hasWords(current.text)
        && !current.truncated && current.revision > run.staleRevisionFence && !run.commitInFlight && !run.pendingHold});
    }
    this.flushHeldCandidate(run);
  }

  private updateSentText(commitId: string, outcome: SessionInputOutcome): void {
    const index = this.sentText.findIndex(item => item.commit_id === commitId);
    if (index < 0) return;
    const item = this.sentText[index]!;
    const state: ContinuousSentTextView['state'] = outcome.status === 'submitted' ? 'sent'
      : outcome.status === 'not-sent' ? 'not_sent' : 'unknown';
    const notice = state === 'sent' ? '已提交到 MIRA；监听是否仍开启由上方状态显示。'
      : state === 'not_sent' ? '这段文字未送出，已保留在下方。可放入文字框核对后，再由你手动发送。'
      : state === 'unknown' ? '发送结果不确定。文字已保留；为避免重复，请先检查会话状态，本页不会自动重发。'
      : outcome.status === 'superseded' ? '该发送被较新的会话操作取代。文字仍保留。'
        : outcome.status === 'closed' ? '会话已关闭，文字仍保留。' : '输入未被接受，文字仍保留。';
    this.sentText[index] = {...item, state, notice}; this.publish();
  }

  private retireUnconfirmed(run: ListeningRun, notice: string): void {
    for (const {commitId} of run.automaticAttempts.values()) {
      const index = this.sentText.findIndex(item => item.commit_id === commitId && item.segment_seq === 0 && item.state === 'sending');
      if (index >= 0) this.sentText[index] = {...this.sentText[index]!, state: 'not_sent', notice};
    }
  }

  private captureError(problem: AudioRuntimeError): void {
    const run = this.run;
    if (!run) return;
    this.failRun(run, new Error(problem.message), problem.code === 'permission-denied');
  }

  private transportError(run: ListeningRun, problem: Error): void {
    if (!this.current(run)) return;
    this.failRun(run, problem);
  }

  private failRun(run: ListeningRun, problem: Error, permissionLost = false): void {
    if (!this.current(run)) return;
    this.inputFence++;
    this.error = problem.message; this.notice = null;
    this.endRun(run, 'error', problem.message, true, permissionLost ? 'permission_lost' : 'user_stop');
  }

  private endRun(run: ListeningRun, state: ContinuousListeningState, notice: string,
      sendStop: boolean, stopReason: 'user_stop' | 'permission_lost' = 'user_stop',
      preserveAcceptedCommit = false): void {
    if (this.run !== run || run.stopping) return;
    run.preserveAcceptedCommit = preserveAcceptedCommit;
    if (!preserveAcceptedCommit) this.retireUnconfirmed(run, '确认已停止，这段文字未提交到 MIRA；原文及更正已保留。');
    const archived = this.archiveCurrentTranscript();
    this.clearEndpointTimer(run); for (const resolve of [...run.quietWaiters]) resolve(false);
    run.bargeDetector.reset(); this.processingState = null;
    run.stopping = true; this.run = null; this.releasing = true;
    run.queue.length = 0; run.queueBytes = 0;
    try { this.capture.stop(); } catch { /* Track release is still attempted by close. */ }
    this.state = state; this.notice = archived ? notice + (state === 'error' && this.previousPreviews.length
      ? ' 已识别文字保留在下方“上次聆听预览”；可放入文字框核对后发送。' : '')
      : '这段预览仍保留在上方；历史已满。请先恢复一段到空文字框，再继续开始新监听。';
    this.options.onPhase?.(false); this.publish();
    const stop = sendStop && run.stream ? run.stream.stop(stopReason) : Promise.resolve();
    run.stopPromise = Promise.resolve(stop).catch(() => {}).then(() => {
      run.abort.abort(); this.releasing = false;
      if (this.closed) this.state = 'closed';
      this.publish();
    });
  }

  async stop(reason: 'user_stop' | 'permission_lost' = 'user_stop'): Promise<void> {
    this.inputFence++;
    const run = this.run;
    if (!run) return;
    this.endRun(run, 'stopping', reason === 'permission_lost'
      ? '麦克风权限已失效，已停止并释放设备。' : '已停止连续聆听；已收到的文字仍保留在这里。', true, reason);
    await run.stopPromise;
    if (!this.closed && this.state === 'stopping') this.state = 'stopped';
    this.publish();
  }

  private setState(state: ContinuousListeningState): void {
    this.state = state;
    this.options.onPhase?.(state === 'listening');
    this.publish();
  }

  private setError(message: string): void { this.error = message; this.state = 'error'; this.publish(); }

  private publish(): void {
    this.compactHistory(this.run);
    const view: ContinuousListeningView = Object.freeze({state: this.state, lease_id: this.run?.leaseId ?? null,
      ready: this.ready, transcript: this.transcript,
      previous_previews: Object.freeze([...this.previousPreviews]), previous_preview_limit: MAX_PREVIOUS_PREVIEWS,
      held_previews: Object.freeze([...this.heldPreviews]), held_preview_limit: MAX_HELD_PREVIEWS,
      sent_text: Object.freeze([...this.sentText]), retired_sent_text: this.retiredSentText,
      service_budget_exhausted: this.serviceBudgetExhausted,
      pending_text_capacity: this.pendingTextCount() >= MAX_PENDING_RECORDS,
      notice: this.notice, error: this.error, natural_enabled: this.naturalEnabled(),
      recognition_status: this.recognitionStatus,
      barge_in_mode: this.run?.bargeInMode ?? (this.options.mode === 'natural' ? 'headphones' : 'guarded'),
      barge_in_available: this.run?.bargeInMode === 'headphones' && !this.run.bargeInvalid && !this.run.bargeSuspended,
      barge_in_suspended: this.run?.bargeSuspended ?? false,
      capture_processing: this.processingState,
      conversation_phase: this.run?.commitInFlight ? 'sending'
        : this.run?.pendingHold ? 'transcribing'
        : this.transcript?.auto_ready ? 'ready'
        : this.transcript?.review_required || (this.transcript?.can_send && !this.naturalEnabled()) ? 'manual_review'
        : this.transcript ? 'transcribing'
        : this.recognitionStatus && ['draining', 'opening'].includes(this.recognitionStatus.state) ? 'transcribing'
        : this.sentText.at(-1)?.state === 'sending' ? 'sending'
        : this.sentText.at(-1)?.state === 'sent' ? 'sent' : 'listening'});
    try { this.options.onUpdate(view); } catch { /* Render failures cannot affect capture ownership. */ }
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.inputFence++;
    this.closed = true;
    const run = this.run;
    if (run) {
      this.retireUnconfirmed(run, '会话已关闭，这段文字未提交到 MIRA；原文及更正已保留。');
      this.archiveCurrentTranscript();
      this.clearEndpointTimer(run); for (const resolve of [...run.quietWaiters]) resolve(false);
      run.bargeDetector.reset(); this.processingState = null;
      run.stopping = true; this.run = null; run.queue.length = 0; run.queueBytes = 0;
      try { this.capture.stop(); } catch { /* Close continues. */ }
      const stop = run.stream?.stop('user_stop');
      await Promise.resolve(stop).catch(() => {});
      run.abort.abort();
    } else this.archiveCurrentTranscript();
    this.state = 'closed'; this.notice = '会话已关闭，未发送文字仍保留在当前页面。';
    this.options.onPhase?.(false);
    try { await this.capture.close(); } catch { /* The browser permission prompt may remain pending. */ }
    this.publish();
  }
}
