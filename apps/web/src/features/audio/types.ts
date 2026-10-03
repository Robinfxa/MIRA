/** Immutable grant identity. Deliberately independent of wire schema and DOM receipts. */
export interface AudioOrigin {
  readonly id: string;
  readonly digest: string;
  readonly activity_seq: number;
  readonly output_epoch: number;
}
export type AudioStopReason = 'stop' | 'new-input' | 'revoked' | 'error' | 'close';
export type AudioErrorCode = 'unsupported' | 'playback-failed' | 'queue-overflow'
  | 'invalid-pcm' | 'permission-denied' | 'capture-failed' | 'capture-overflow'
  | 'consumer-failed' | 'device-ended';
export interface AudioRuntimeError { readonly code: AudioErrorCode; readonly message: string; }
export interface PlaybackFact {
  readonly origin: AudioOrigin;
  readonly stage: 'submitted' | 'rendered' | 'completed' | 'stopped' | 'failed';
  readonly submittedFrames: number;
  readonly renderedFrames: number;
  readonly sampleRate: 24000;
  readonly inFlightFramesUncertain: number;
  readonly reason?: AudioStopReason;
}
export interface PlaybackStream {
  /** False means this generation is invalid/finished, or the stream failed closed. */
  push(pcm16: Int16Array): boolean;
  finish(): boolean;
}
export interface CapturedAudio {
  readonly pcm16le: Uint8Array;
  readonly sampleRate: 16000;
  readonly channels: 1;
  /** Rate of Float32 input delivered by the actual AudioContext. */
  readonly captureSampleRate: number;
  /** Device-reported rate, if present; the browser may resample into AudioContext. */
  readonly sourceSampleRate: number | null;
  readonly sequence: number;
  readonly startSample: number;
  readonly endSample: number;
  readonly captureStartFrame: number;
}
