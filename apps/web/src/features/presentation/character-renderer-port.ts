import type { SceneState } from './scene-state.js';

/** Read-only preparation, ordinary rendering and optional bounded camera completion. */
export interface CharacterRendererPort {
  prepareState(state: SceneState, signal: AbortSignal): Promise<boolean>;
  render(state: SceneState): void;
  /** Explicit finite camera or emotion transition; ordinary render calls never restart it.
   * True means the terminal frame was copied. Abort preserves coherent partial pose. */
  transitionState?(state: SceneState, signal: AbortSignal, kind?: 'camera' | 'emotion'): Promise<boolean>;
  getEmotionMotionState?(): {readonly target: SceneState['emotion']; readonly progress: number;
    readonly status: 'idle' | 'running' | 'cancelled' | 'completed'};
  /** Local visible motion only, never an application receipt or hardware camera fact. */
  getMotionState?(): {readonly progress: number; readonly target: 'camera_ready' | 'camera_raise';
    readonly status: 'idle' | 'running' | 'cancelled' | 'completed'};
  /** Synchronously cancel motion and restore neutral face channels on Stop. */
  stop?(): void;
  /** Optional local pause hook for page hiding/backgrounding. */
  setPaused?(paused: boolean): void;
  /** Review-only status used to expose unaccepted assets without claiming success. */
  getStatus?(): {readonly mode: 'static-pixi' | 'code-native-review'; readonly visualAcceptance: 'pending' | 'accepted'; readonly warnings: readonly string[]};
  destroy(): void;
}
export type CharacterRendererFactory = (host: HTMLElement, signal: AbortSignal) => Promise<CharacterRendererPort | null>;
export type CharacterRendererMode = 'static-pixi' | 'code-native-review';
