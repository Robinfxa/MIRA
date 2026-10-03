import type { EffectView } from '../../shared/generated/contracts.js';

/** Replace the diagnostic DOM adapter without giving a renderer policy authority. */
export interface EffectExecutor {
  apply(effect: EffectView): void;
  /** Optional resource gate for effects whose backing asset must be ready before apply. */
  prepare?(effect: EffectView, signal: AbortSignal): Promise<void>;
  prepareInput(): void;
  stop(): void;
  setPhase?(phase: 'idle' | 'listening' | 'thinking' | 'speaking'): void;
}
