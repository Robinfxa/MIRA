import type { EffectView } from '../../shared/generated/contracts.js';
import type { EffectExecutor } from './ports.js';
import { initialSceneState, reduceSceneEffect } from './scene-state.js';
import type { SceneExpression, ScenePhase, SceneState } from './scene-state.js';

const PHASE_LABELS: Record<ScenePhase, string> = {
  idle: '陪你听雨', listening: '正在认真听', thinking: '想一想…', speaking: '正在说话',
};
const EXPRESSION_LABELS: Record<SceneExpression, string> = {
  calm: '平静', warm: '温暖微笑', curious: '好奇', reflective: '若有所思',
};
const ACTION_LABELS: Record<SceneState['action'], string> = {
  camera_ready: '手中拿着相机', camera_lowered: '放低了相机', look_at_rain: '转头看向窗外的雨',
};
const SCENE_LABELS: Record<SceneState['environment'], string> = {
  cafe: '雨夜 · 窗边咖啡馆', rain_window: '雨窗 · 城市慢了下来', cafe_warm: '暖灯 · 留一会儿吧',
};
const DEFAULT_MEDIA_READINESS_TIMEOUT_MS = 5000;
const MAX_MEDIA_READINESS_TIMEOUT_MS = 30000;
const abortError = (): Error => Object.assign(new Error('Media preparation cancelled'), { name: 'AbortError' });

export interface SceneEffectExecutorOptions {
  /** Test seam for the bounded asset wait; production defaults to five seconds. */
  readonly mediaReadinessTimeoutMs?: number;
}

/**
 * Synchronous visual consumer beneath the existing presentation gate.
 * CSS supplies animation; this class schedules nothing and never starts audio.
 * Real recording/playback owners call setPhase; subtitle delivery is not speech evidence.
 */
export class SceneEffectExecutor implements EffectExecutor {
  private state = initialSceneState();
  private readonly decodedImages = new WeakMap<HTMLImageElement, Promise<void>>();
  private readonly mediaReadinessTimeoutMs: number;

  constructor(private readonly root: HTMLElement, options: SceneEffectExecutorOptions = {}) {
    const timeout = options.mediaReadinessTimeoutMs ?? DEFAULT_MEDIA_READINESS_TIMEOUT_MS;
    if (!Number.isSafeInteger(timeout) || timeout < 1 || timeout > MAX_MEDIA_READINESS_TIMEOUT_MS) {
      throw new RangeError('Media readiness timeout must be between 1 and 30000 milliseconds');
    }
    this.mediaReadinessTimeoutMs = timeout;
    this.render();
  }

  private element(name: string): HTMLElement {
    const target = this.root.querySelector<HTMLElement>(`[data-${name}]`);
    if (!target) throw new Error(`Missing scene slot: ${name}`);
    return target;
  }

  apply(effect: EffectView): void {
    const next = reduceSceneEffect(this.state, effect);
    this.state = next;
    this.render();
  }

  /**
   * Wait for the already-mounted local illustration without changing visible DOM state.
   * This establishes decoded-resource readiness only; it cannot establish browser paint or
   * that a person looked at the image. The controller revalidates its gate before apply().
   */
  async prepare(effect: EffectView, signal: AbortSignal): Promise<void> {
    if (effect.kind !== 'media' || (effect.value !== 'trip_photo' && effect.value !== 'trip_photo_placeholder')) return;
    if (signal.aborted) throw abortError();
    const image = this.root.querySelector<HTMLImageElement>('[data-photo] img');
    if (!image) throw new Error('Image resource unavailable');

    const deadline = new AbortController();
    let timedOut = false;
    const abortDeadline = (): void => deadline.abort();
    const timer = globalThis.setTimeout(() => { timedOut = true; deadline.abort(); }, this.mediaReadinessTimeoutMs);
    signal.addEventListener('abort', abortDeadline, { once: true });
    try {
      await this.waitForImageLoad(image, deadline.signal);
      await this.decodeImage(image, deadline.signal);
      if (signal.aborted) throw abortError();
      if (!this.imageIsReady(image)) throw new Error('Image resource unavailable');
    } catch (error) {
      if (signal.aborted) throw abortError();
      if (timedOut) throw new Error('Image readiness timed out');
      throw error instanceof Error && error.name === 'AbortError' ? error : new Error('Image resource unavailable');
    } finally {
      globalThis.clearTimeout(timer);
      signal.removeEventListener('abort', abortDeadline);
    }
  }

  private imageIsReady(image: HTMLImageElement): boolean {
    return image.complete && image.naturalWidth > 0;
  }

  private waitForImageLoad(image: HTMLImageElement, signal: AbortSignal): Promise<void> {
    if (signal.aborted) return Promise.reject(abortError());
    if (image.complete) return this.imageIsReady(image) ? Promise.resolve() : Promise.reject(new Error('Image resource unavailable'));
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error?: Error): void => {
        if (settled) return;
        settled = true;
        image.removeEventListener('load', onLoad);
        image.removeEventListener('error', onError);
        signal.removeEventListener('abort', onAbort);
        if (error) reject(error); else resolve();
      };
      const onLoad = (): void => finish(this.imageIsReady(image) ? undefined : new Error('Image resource unavailable'));
      const onError = (): void => finish(new Error('Image resource unavailable'));
      const onAbort = (): void => finish(abortError());
      image.addEventListener('load', onLoad, { once: true });
      image.addEventListener('error', onError, { once: true });
      signal.addEventListener('abort', onAbort, { once: true });
      // Close the small race between the initial complete check and listener registration.
      if (image.complete) onLoad();
      if (signal.aborted) onAbort();
    });
  }

  private decodeImage(image: HTMLImageElement, signal: AbortSignal): Promise<void> {
    if (signal.aborted) return Promise.reject(abortError());
    if (!this.imageIsReady(image)) return Promise.reject(new Error('Image resource unavailable'));
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error?: Error): void => {
        if (settled) return;
        settled = true;
        signal.removeEventListener('abort', onAbort);
        if (error) reject(error); else resolve();
      };
      const onAbort = (): void => finish(abortError());
      signal.addEventListener('abort', onAbort, { once: true });
      this.decodeResource(image).then(() => {
          finish(this.imageIsReady(image) ? undefined : new Error('Image resource unavailable'));
        }, () => finish(new Error('Image resource unavailable')));
      if (signal.aborted) onAbort();
    });
  }

  private decodeResource(image: HTMLImageElement): Promise<void> {
    const existing = this.decodedImages.get(image);
    if (existing) return existing;
    let decoding: Promise<void>;
    try { decoding = image.decode(); }
    catch { decoding = Promise.reject(new Error('Image resource unavailable')); }
    this.decodedImages.set(image, decoding);
    // Keep an in-flight decode single-flight even if one waiter is canceled. A settled
    // rejection is retryable, but an older rejection must never evict a newer cached attempt.
    void decoding.catch(() => {
      if (this.decodedImages.get(image) === decoding) this.decodedImages.delete(image);
    });
    return decoding;
  }

  prepareInput(): void {
    this.state = { ...this.state, phase: 'thinking', subtitle: '' };
    this.render();
  }

  stop(): void {
    this.state = { ...this.state, phase: 'idle', subtitle: this.state.photoVisible ? '已停下。那张旅行插画还留在这里。' : '已停下。我们可以慢慢说。' };
    this.render();
  }

  setPhase(phase: ScenePhase): void {
    this.state = { ...this.state, phase };
    this.render();
  }

  setExpression(expression: SceneExpression): void {
    this.state = { ...this.state, expression };
    this.render();
  }

  private render(): void {
    const state = this.state;
    this.root.dataset.phase = state.phase;
    this.root.dataset.expression = state.expression;
    this.root.dataset.action = state.action;
    this.root.dataset.scene = state.environment;
    this.element('subtitle').textContent = state.subtitle;
    this.element('photo').hidden = !state.photoVisible;
    this.element('pose').textContent = ACTION_LABELS[state.action];
    this.element('scene-label').textContent = SCENE_LABELS[state.environment];
    this.element('phase-label').textContent = PHASE_LABELS[state.phase];
    this.element('character-description').textContent =
      `MIRA，26 岁的旅行摄影师。神情${EXPRESSION_LABELS[state.expression]}，${ACTION_LABELS[state.action]}。${PHASE_LABELS[state.phase]}。`;
  }
}
