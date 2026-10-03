import type { AudioProgressRequest, CreateSessionResponse, EffectView, InputRequest, MicrophoneComplete, MicrophoneStart, ReceiptRequest, ReviewedAudioStatusResponse, SessionView, StopRequest } from '../../shared/generated/contracts.js';
import type { CapturedAudio } from '../audio/types.js';

export type { VoiceCapabilities } from '../../shared/generated/contracts.js';
import type { VoiceCapabilities } from '../../shared/generated/contracts.js';
export type MicrophoneOrigin = Pick<MicrophoneStart, 'stream_id' | 'activity_seq' | 'input_epoch'>;
export type FinalTranscript = Pick<MicrophoneComplete, 'text' | 'had_final'>;
export interface MicrophoneStream {
  readonly ready: Promise<void>;
  readonly completion: Promise<FinalTranscript>;
  send(chunk: CapturedAudio): void;
  finish(): Promise<FinalTranscript>;
  cancel(): void;
}
/** Session use cases depend on ports, not fetch or a provider SDK. */
export interface SessionTransport {
  create(clientInstanceId: string, signal?: AbortSignal): Promise<CreateSessionResponse>;
  capabilities(signal?: AbortSignal): Promise<VoiceCapabilities>;
  snapshot(signal?: AbortSignal): Promise<SessionView>;
  input(request: InputRequest, signal?: AbortSignal): Promise<SessionView>;
  stop(request: StopRequest, signal?: AbortSignal): Promise<SessionView>;
  receipt(request: ReceiptRequest): Promise<SessionView>;
  audioProgress(request: AudioProgressRequest): Promise<SessionView>;
  reviewedAudioStatus?(signal?: AbortSignal): Promise<ReviewedAudioStatusResponse>;
  speech(effect: EffectView, signal: AbortSignal, onPcm: (pcm: Int16Array) => void | Promise<void>): Promise<void>;
  microphone(origin: MicrophoneOrigin, signal: AbortSignal): MicrophoneStream;
  close(): Promise<void>;
}
