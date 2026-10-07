import type { AudioProgressRequest, ContinuousListeningCommitReady, ContinuousListeningCommitRejected,
  ContinuousListeningHeld, ContinuousListeningHoldRejected, ContinuousListeningEndpointStatus,
  ContinuousListeningEndpointPending, ContinuousListeningReady as ContractContinuousListeningReady,
  ContinuousListeningStopped, ContinuousListeningTranscript, ContinuousListeningRecognitionStatus, ContinuousListeningUtteranceReady,
  ContinuousListeningUtteranceRevision, CreateSessionResponse, EffectView,
  InputRequest, PhotoDismissRequest, FixedPhotoProgressRequest, MicrophoneComplete, MicrophoneStart, ReceiptRequest, ReviewedAudioStatusResponse,
  SessionView, StopRequest, ResponsePreferenceRequest, StoryImageCompletionRequest } from '../../shared/generated/contracts.js';
import type { CapturedAudio } from '../audio/types.js';

export type { VoiceCapabilities } from '../../shared/generated/contracts.js';
import type { VoiceCapabilities } from '../../shared/generated/contracts.js';
export type MicrophoneOrigin = Pick<MicrophoneStart, 'stream_id' | 'activity_seq' | 'input_epoch'>;
export type FinalTranscript = Pick<MicrophoneComplete, 'text' | 'had_final'>;
export interface MicrophoneTranscriptRevision {
  readonly stream_id: string;
  readonly revision: number;
  readonly text: string;
  readonly is_final: boolean;
}
/** Per-client monotonic elapsed timings from press-to-talk start; never persisted. */
export interface MicrophoneTimingSnapshot {
  readonly stream_id: string;
  readonly dispatch_ms: number;
  readonly first_revision_ms?: number;
  readonly first_final_revision_ms?: number;
  readonly client_finish_ms?: number;
  readonly stream_close_ms?: number;
  readonly revision_count: number;
  readonly final_revision_count: number;
}
export interface MicrophoneObservers {
  readonly timingOriginMs?: number;
  readonly onRevision?: (revision: MicrophoneTranscriptRevision | null) => void;
  readonly onTiming?: (timing: MicrophoneTimingSnapshot) => void;
}
export interface MicrophoneStream {
  readonly ready: Promise<void>;
  readonly completion: Promise<FinalTranscript>;
  send(chunk: CapturedAudio): void;
  finish(clientFinishAtMs?: number): Promise<FinalTranscript>;
  cancel(): void;
}
export type ContinuousListeningReady = ContractContinuousListeningReady;
export type ContinuousListeningMode = 'manual' | 'natural';
type Frame<T extends {readonly type?: string}, Kind extends string> = Omit<T, 'type'> & {readonly type: Kind};
export type ContinuousListeningServerEvent =
  | { readonly type: 'ready'; readonly ready: ContinuousListeningReady }
  | Frame<ContinuousListeningTranscript, 'transcript'>
  | Frame<ContinuousListeningEndpointPending, 'endpoint_pending'>
  | Frame<ContinuousListeningEndpointStatus, 'endpoint_status'>
  | Frame<ContinuousListeningUtteranceReady, 'utterance_ready'>
  | Frame<ContinuousListeningUtteranceRevision, 'utterance_revision'>
  | Frame<ContinuousListeningRecognitionStatus, 'recognition_status'>
  | Frame<ContinuousListeningHeld, 'utterance_held'>
  | Frame<ContinuousListeningHoldRejected, 'hold_rejected'>
  | Frame<ContinuousListeningCommitReady, 'commit_ready'>
  | Frame<ContinuousListeningCommitRejected, 'commit_rejected'>
  | Frame<ContinuousListeningStopped, 'stopped'>;
export type ContinuousListeningCommitResult =
  | Extract<ContinuousListeningServerEvent, {type: 'commit_ready'}>
  | Extract<ContinuousListeningServerEvent, {type: 'commit_rejected'}>;
export type ContinuousListeningHoldResult =
  | Extract<ContinuousListeningServerEvent, {type: 'utterance_held'}>
  | Extract<ContinuousListeningServerEvent, {type: 'hold_rejected'}>;
export interface ContinuousListeningObservers {
  readonly onEvent: (event: ContinuousListeningServerEvent) => void;
  readonly onError: (error: Error) => void;
}
export interface ContinuousListeningStream {
  readonly ready: Promise<ContinuousListeningReady>;
  readonly closed: Promise<void>;
  send(chunk: CapturedAudio): void;
  endpoint?(endpointId: string, sourceEndSample: number): void;
  cancelEndpoint?(endpointId: string): void;
  commit(commitId: string, revision: number, utteranceId?: string): Promise<ContinuousListeningCommitResult>;
  hold(utteranceId: string, revision: number): Promise<ContinuousListeningHoldResult>;
  stop(reason?: 'user_stop' | 'permission_lost'): Promise<void>;
  cancel(): void;
}
export type SessionInputRequest = InputRequest;
/** Session use cases depend on ports, not fetch or a provider SDK. */
export interface SessionTransport {
  create(clientInstanceId: string, signal?: AbortSignal): Promise<CreateSessionResponse>;
  capabilities(signal?: AbortSignal): Promise<VoiceCapabilities>;
  snapshot(signal?: AbortSignal): Promise<SessionView>;
  input(request: SessionInputRequest, signal?: AbortSignal): Promise<SessionView>;
  stop(request: StopRequest, signal?: AbortSignal): Promise<SessionView>;
  completeStoryImage?(request: StoryImageCompletionRequest,signal?: AbortSignal): Promise<SessionView>;
  responsePreference?(request: ResponsePreferenceRequest, signal?: AbortSignal): Promise<SessionView>;
  fixedPhotoProgress?(body: FixedPhotoProgressRequest): Promise<SessionView>;
  dismissPhoto?(request: PhotoDismissRequest): Promise<SessionView>;
  receipt(request: ReceiptRequest): Promise<SessionView>;
  audioProgress(request: AudioProgressRequest): Promise<SessionView>;
  reviewedAudioStatus?(signal?: AbortSignal): Promise<ReviewedAudioStatusResponse>;
  speech(effect: EffectView, signal: AbortSignal, onPcm: (pcm: Int16Array) => void | Promise<void>): Promise<void>;
  microphone(origin: MicrophoneOrigin, signal: AbortSignal, observers?: MicrophoneObservers): MicrophoneStream;
  continuousListening?(leaseId: string, signal: AbortSignal, observers: ContinuousListeningObservers,
    mode?: ContinuousListeningMode): ContinuousListeningStream;
  /** Optional for older test/client transports; when available it shares the microphone timer. */
  monotonicNow?(): number;
  close(): Promise<void>;
}
