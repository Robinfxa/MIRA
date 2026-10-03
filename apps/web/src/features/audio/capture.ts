import { StreamingPcm16Resampler } from './pcm.js';
import type { AudioRuntimeError, CapturedAudio } from './types.js';

export type CaptureState = 'starting' | 'recording' | 'stopped' | 'closed';
export interface CaptureOptions {
  /** Must settle only when the transport has accepted the bytes into its own bounded buffer. */
  readonly onChunk: (chunk: CapturedAudio) => void | Promise<void>;
  readonly onError?: (error: AudioRuntimeError) => void;
  readonly onState?: (state: CaptureState) => void;
  readonly getUserMedia?: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
  readonly createContext?: () => AudioContext;
  readonly createWorkletNode?: (context: AudioContext, name: string, options: AudioWorkletNodeOptions) => AudioWorkletNode;
  readonly workletUrl?: string;
  readonly chunkMilliseconds?: number;
  readonly maxPendingChunks?: number;
}
interface CaptureSession {
  readonly generation: number;
  context: AudioContext | null;
  stream: MediaStream | null;
  source: MediaStreamAudioSourceNode | null;
  node: AudioWorkletNode | null;
  resampler: StreamingPcm16Resampler | null;
  pending: number;
  recording: boolean;
  sequence: number;
  outputFrames: number;
  nextCaptureFrame: number | null;
  sourceSampleRate: number | null;
  trackEnded: (() => void) | null;
}
class SetupError extends Error {
  constructor(readonly code: AudioRuntimeError['code']) { super(code); }
}

/** Explicit push-to-talk capture. It neither sends network traffic nor chooses ASR policy. */
export class MicrophoneCapture {
  private current: CaptureSession | null = null;
  private generation = 0;
  private closed = false;
  private readonly closing = new Set<Promise<void>>();
  private readonly chunkMilliseconds: number;
  private readonly maxPendingChunks: number;
  constructor(private readonly options: CaptureOptions) {
    this.chunkMilliseconds = options.chunkMilliseconds ?? 20;
    this.maxPendingChunks = options.maxPendingChunks ?? 8;
    if (!Number.isInteger(this.chunkMilliseconds) || this.chunkMilliseconds < 10 || this.chunkMilliseconds > 100
      || !Number.isInteger(this.maxPendingChunks) || this.maxPendingChunks < 1 || this.maxPendingChunks > 32) {
      throw new RangeError('Invalid microphone buffer bounds');
    }
  }
  private alive(session: CaptureSession): boolean {
    return !this.closed && this.current === session && session.generation === this.generation;
  }
  /** Invoke directly from an explicit user action; construction does not touch any browser resource. */
  async start(): Promise<boolean> {
    if (this.closed || this.current) return false;
    const session: CaptureSession = {generation: ++this.generation, context: null, stream: null, source: null,
      node: null, resampler: null, pending: 0, recording: false, sequence: 0, outputFrames: 0,
      nextCaptureFrame: null, sourceSampleRate: null, trackEnded: null};
    this.current = session;
    this.state('starting');
    if (!this.alive(session)) return false;
    try {
      const media = this.options.getUserMedia ?? (typeof navigator !== 'undefined'
        ? navigator.mediaDevices?.getUserMedia?.bind(navigator.mediaDevices) : undefined);
      const createNode = this.options.createWorkletNode ?? (typeof globalThis.AudioWorkletNode === 'function'
        ? (context: AudioContext, name: string, options: AudioWorkletNodeOptions) => new AudioWorkletNode(context, name, options) : undefined);
      const createContext = this.options.createContext ?? (typeof globalThis.AudioContext === 'function'
        ? () => new AudioContext({latencyHint: 'interactive'}) : undefined);
      if (!media || !createNode || !createContext) throw new SetupError('unsupported');
      const context = createContext();
      session.context = context;
      if (!context.audioWorklet?.addModule) throw new SetupError('unsupported');
      session.resampler = new StreamingPcm16Resampler(context.sampleRate);
      // Begin resume in the original user gesture. Permission can remain pending indefinitely.
      // A late getUserMedia result always has an attached cleanup path after stop/close/failure.
      const streamPromise = media({audio: {channelCount: {ideal: 1}, echoCancellation: true,
        noiseSuppression: true, autoGainControl: true}, video: false}).then(stream => {
        if (!this.alive(session)) this.stopTracks(stream);
        else session.stream = stream;
        return stream;
      });
      const [stream] = await Promise.all([streamPromise, context.resume(),
        context.audioWorklet.addModule(this.options.workletUrl ?? '/assets/audio/capture-worklet.js')]);
      if (!this.alive(session)) return false;
      const tracks = stream.getAudioTracks();
      if (tracks.length === 0) throw new SetupError('capture-failed');
      const reportedRate = tracks[0]?.getSettings().sampleRate;
      session.sourceSampleRate = Number.isFinite(reportedRate) && (reportedRate ?? 0) > 0 ? reportedRate! : null;
      const node = createNode(context, 'mira-pcm-capture', {numberOfInputs: 1, numberOfOutputs: 1,
        outputChannelCount: [1], channelCount: 1, channelCountMode: 'explicit',
        processorOptions: {chunkFrames: Math.floor(context.sampleRate * this.chunkMilliseconds / 1000),
          maxPendingChunks: this.maxPendingChunks}});
      session.node = node;
      node.port.onmessage = event => this.message(session, event.data as unknown);
      node.onprocessorerror = () => this.fail(session, 'capture-failed');
      session.source = context.createMediaStreamSource(stream);
      session.trackEnded = () => this.fail(session, 'device-ended');
      for (const track of tracks) track.addEventListener('ended', session.trackEnded);
      session.recording = true;
      session.source.connect(node);
      // The processor writes silence; microphone sound is never routed to speakers.
      node.connect(context.destination);
      this.state('recording');
      return this.alive(session);
    } catch (error) {
      if (this.alive(session)) {
        const code = error instanceof SetupError ? error.code
          : error instanceof Error && (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError')
            ? 'permission-denied' : 'capture-failed';
        this.fail(session, code);
      }
      return false;
    }
  }
  private message(session: CaptureSession, value: unknown): void {
    if (!this.alive(session) || !session.recording) return;
    if (!value || typeof value !== 'object') { this.fail(session, 'capture-failed'); return; }
    const packet = value as Record<string, unknown>;
    if (packet['type'] === 'overflow') { this.fail(session, 'capture-overflow'); return; }
    const samples = packet['samples'];
    const frame = packet['startFrame'];
    if (packet['type'] !== 'samples' || !(samples instanceof Float32Array) || samples.length === 0
      || samples.length > Math.ceil(session.context!.sampleRate * this.chunkMilliseconds / 1000)
      || packet['sampleRate'] !== session.context!.sampleRate || packet['sequence'] !== session.sequence
      || typeof frame !== 'number' || !Number.isSafeInteger(frame) || frame < 0
      || (session.nextCaptureFrame !== null && frame !== session.nextCaptureFrame)) {
      this.fail(session, 'capture-failed'); return;
    }
    if (session.pending >= this.maxPendingChunks) { this.fail(session, 'capture-overflow'); return; }
    let pcm16le: Uint8Array;
    try { pcm16le = session.resampler!.push(samples); }
    catch { this.fail(session, 'capture-failed'); return; }
    const sequence = session.sequence++;
    session.nextCaptureFrame = frame + samples.length;
    const chunk: CapturedAudio = Object.freeze({pcm16le, sampleRate: 16000, channels: 1,
      captureSampleRate: session.context!.sampleRate, sourceSampleRate: session.sourceSampleRate,
      sequence, startSample: session.outputFrames, endSample: session.outputFrames + pcm16le.length / 2, captureStartFrame: frame});
    session.outputFrames = chunk.endSample;
    session.pending++;
    try {
      const result = this.options.onChunk(chunk);
      void Promise.resolve(result).then(() => {
        if (!this.alive(session)) return;
        session.pending--;
        session.node!.port.postMessage({type: 'ack', sequence});
      }).catch(() => this.fail(session, 'consumer-failed'));
    } catch { this.fail(session, 'consumer-failed'); }
  }
  stop(): void {
    const session = this.current;
    this.current = null;
    this.generation++;
    if (!session) return;
    this.release(session);
    this.state('stopped');
  }
  private stopTracks(stream: MediaStream): void {
    for (const track of stream.getTracks()) { try { track.stop(); } catch { /* Release the remaining tracks. */ } }
  }
  private release(session: CaptureSession): void {
    session.recording = false;
    if (session.stream) {
      if (session.trackEnded) for (const track of session.stream.getAudioTracks()) track.removeEventListener('ended', session.trackEnded);
      this.stopTracks(session.stream);
      session.stream = null;
    }
    if (session.source) { try { session.source.disconnect(); } catch { /* Already disconnected. */ } session.source = null; }
    if (session.node) {
      session.node.port.onmessage = null;
      session.node.onprocessorerror = null;
      try { session.node.port.postMessage({type: 'stop'}); } catch { /* Port may already be closed. */ }
      try { session.node.port.close(); } catch { /* Port may already be closed. */ }
      try { session.node.disconnect(); } catch { /* Node may already be disconnected. */ }
      session.node = null;
    }
    if (session.context) {
      const context = session.context;
      session.context = null;
      const releaseGeneration = this.generation;
      const promise = context.close().catch(() => {
        // A past cleanup failure is not a failure of a newer capture.
        if (this.generation === releaseGeneration) this.error('capture-failed');
      });
      this.closing.add(promise);
      void promise.then(() => this.closing.delete(promise));
    }
    session.resampler = null;
  }
  private fail(session: CaptureSession, code: AudioRuntimeError['code']): void {
    if (!this.alive(session)) return;
    this.stop();
    this.error(code);
  }
  private state(state: CaptureState): void {
    try { this.options.onState?.(state); }
    catch { if (this.current) this.fail(this.current, 'consumer-failed'); }
  }
  private error(code: AudioRuntimeError['code']): void {
    const messages: Partial<Record<AudioRuntimeError['code'], string>> = {
      unsupported: 'Microphone capture is unavailable in this browser. Text input is still available.',
      'permission-denied': 'Microphone permission was denied. Text input is still available.',
      'capture-overflow': 'Microphone delivery fell behind and was stopped. Retry or use text input.',
      'consumer-failed': 'Microphone delivery failed. Retry or use text input.',
      'device-ended': 'The microphone disconnected. Retry or use text input.',
    };
    try { this.options.onError?.(Object.freeze({code, message: messages[code] ?? 'Microphone capture failed. Text input is still available.'})); }
    catch { /* Error observers cannot start or retain microphone resources. */ }
  }
  async close(): Promise<void> {
    if (!this.closed) {
      this.closed = true;
      this.stop();
      this.state('closed');
    }
    // Do not wait indefinitely for the browser's pending permission dialog.
    await Promise.all([...this.closing]);
  }
}
