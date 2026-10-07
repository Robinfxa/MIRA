import type { EffectView, SessionView } from '../../shared/generated/contracts.js';

/** Replace the diagnostic DOM adapter without giving a renderer policy authority. */
export interface EffectExecutor {
  apply(effect: EffectView): void;
  /** Optional resource gate for effects whose backing asset must be ready before apply. */
  prepare?(effect: EffectView, signal: AbortSignal): Promise<void>;
  /** Optional bounded visible commit. Resolves only after terminal rendered state;
   * abort must stop motion. Subtitles remain independently presentable during motion. */
  present?(effect: EffectView, signal: AbortSignal, canCommit?: () => boolean): Promise<void>;
  /** Revoke exact generated resources within their original turn, preserving Stop/new-input history. */
  reconcilePhoto?(snapshot: SessionView): void;
  /** Application projection revokes chapter controls; it never fabricates a receipt. */
  reconcileChapter?(snapshot: SessionView): void;
  /** Synchronous local invalidation, including voice interruption before new input. */
  invalidateChapter?(): void;
  discardPrepared?(effect: EffectView): void;
  /** Explicit local app control: hides the photo and aborts staging, without canceling the turn. */
  dismissPhoto?(target?: 'display'|'fixed_photo'|'all_photos'): void;
  prepareInput(): void;
  stop(): void;
  /** Release local renderer resources when the whole session is closed (never on Stop). */
  close?(): void;
  setPhase?(phase: 'idle' | 'listening' | 'thinking' | 'speaking'): void;
}
