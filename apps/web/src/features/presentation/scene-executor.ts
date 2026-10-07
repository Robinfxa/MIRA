import type { EffectView, SessionView } from '../../shared/generated/contracts.js';
import { generatedPhotoIdentity } from '../../shared/photo-value.js';
import { GENERATED_IMAGE_DESCRIPTION, GENERATED_IMAGE_LABEL, prepareGeneratedImage } from './generated-image-resource.js';
import type { GeneratedImagePrimitives, OwnedGeneratedImage } from './generated-image-resource.js';
import type { EffectExecutor } from './ports.js';
import type { CharacterRendererFactory, CharacterRendererMode, CharacterRendererPort } from './character-renderer-port.js';
import { initialSceneState, reduceSceneEffect } from './scene-state.js';
import type { SceneExpression, ScenePhase, SceneState } from './scene-state.js';
import {ChapterPresentation, isChapterEffect} from './chapter-presentation.js';
import type {ChapterPresentationOptions} from './chapter-presentation.js';

const PHASE_LABELS: Record<ScenePhase, string> = {
  idle: '陪你听雨', listening: '正在认真听', thinking: '想一想…', speaking: '正在说话',
};
const EXPRESSION_LABELS: Record<SceneExpression, string> = {
  calm: '平静', warm: '温暖微笑', curious: '好奇', reflective: '若有所思',
};
const ACTION_LABELS: Record<SceneState['action'], string> = {
  camera_raise: '把相机抬到胸前', camera_ready: '手中拿着相机', camera_lowered: '放低了相机', look_at_rain: '转头看向窗外的雨',
};
const SCENE_LABELS: Record<SceneState['environment'], string> = {
  cafe: '雨夜 · 窗边咖啡馆', rain_window: '雨窗 · 城市慢了下来', cafe_warm: '暖灯 · 留一会儿吧',
};
const EMOTION_LABELS: Record<SceneState['emotion'], string> = {
  emotion_normal:'平常', emotion_guarded:'戒备', emotion_happy:'开心', emotion_shy:'娇羞',
};
const OUTFIT_LABELS: Record<SceneState['outfit'], string> = {
  outfit_black_jacket:'黑夹克与奶油色内搭', outfit_cream_inner_only:'奶油色内搭', outfit_amber_raincoat:'琥珀雨衣与奶油色内搭',
};
const ACCESSORY_LABELS: Record<SceneState['accessory'], string> = {
  accessory_camera_clip:'相机头饰', accessory_star_clip:'银色星星发卡',
};
const DEFAULT_MEDIA_READINESS_TIMEOUT_MS = 5000;
const MAX_MEDIA_READINESS_TIMEOUT_MS = 30000;
const abortError = (): Error => Object.assign(new Error('Media preparation cancelled'), { name: 'AbortError' });

export interface SceneEffectExecutorOptions {
  readonly chapter?: ChapterPresentationOptions;
  /** Test seam for the bounded asset wait; production defaults to five seconds. */
  readonly mediaReadinessTimeoutMs?: number;
  /** Null disables Pixi; absent uses the local, lazy-loaded Pixi adapter. */
  readonly characterRendererFactory?: CharacterRendererFactory | null;
  /** Explicit opt-in for the unaccepted semantic code-native review renderer. */
  readonly characterRendererMode?: CharacterRendererMode;
  /** Authenticated exact-grant byte transport; absent means generated media is unavailable. */
  readonly generatedImage?: GeneratedImagePrimitives;
}

/**
 * Gated visual consumer. Optional camera and emotion transitions complete asynchronously;
 * the selected renderer owns their finite motion and this class never starts audio.
 * Real recording/playback owners call setPhase; subtitle delivery is not speech evidence.
 */
export class SceneEffectExecutor implements EffectExecutor {
  private state = initialSceneState();
  private readonly decodedImages = new WeakMap<HTMLImageElement, Promise<void>>();
  private readonly mediaReadinessTimeoutMs: number;
  private readonly rendererAbort = new AbortController();
  private characterRenderer: CharacterRendererPort | null = null;
  private characterRendererPromise: Promise<CharacterRendererPort | null> | null = null;
  private readonly characterRendererMode: CharacterRendererMode;
  private closed = false;
  private readonly generatedImage: GeneratedImagePrimitives | undefined;
  private generatedPreparation: AbortController | null = null;
  private preparedGenerated: OwnedGeneratedImage | null = null;
  private displayedGenerated: OwnedGeneratedImage | null = null;
  private scenePreparationEpoch = 0;
  private preparedScene: { id: string; digest: string; epoch: number; version: string; image: HTMLImageElement } | null = null;
  private chapter: ChapterPresentation | null = null;
  private readonly chapterOptions: ChapterPresentationOptions | undefined;
  private recognitionReaction = false;
  private recognitionOperation: object | null = null;

  private backgroundVersion(): string {
    return this.root.dataset['backgroundVersion'] === 'painterly-v3' ? 'painterly-v3' : 'classic';
  }

  private cancelScenePreparation(): void {
    this.scenePreparationEpoch++;
    this.preparedScene = null;
  }

  constructor(private readonly root: HTMLElement, options: SceneEffectExecutorOptions = {}) {
    const timeout = options.mediaReadinessTimeoutMs ?? DEFAULT_MEDIA_READINESS_TIMEOUT_MS;
    if (!Number.isSafeInteger(timeout) || timeout < 1 || timeout > MAX_MEDIA_READINESS_TIMEOUT_MS) {
      throw new RangeError('Media readiness timeout must be between 1 and 30000 milliseconds');
    }
    this.mediaReadinessTimeoutMs = timeout;
    this.generatedImage = options.generatedImage;
    this.characterRendererMode = options.characterRendererMode ?? 'static-pixi';
    this.chapterOptions = options.chapter;
    this.render();
    this.initializeCharacterRenderer(root.querySelector<HTMLElement>('.character-anchor'), options.characterRendererFactory);
  }

  private initializeCharacterRenderer(host: HTMLElement | null, factory: CharacterRendererFactory | null | undefined): void {
    if (!host || factory === null) return;
    const load: CharacterRendererFactory = factory ?? (async (target, signal) => {
      if (this.characterRendererMode === 'code-native-review') {
        const module = await import('./code-native-character-renderer.js');
        return module.createCodeNativeCharacterRenderer(target, {signal});
      }
      const module = await import('./pixi-character-renderer.js');
      return module.createPixiCharacterRenderer(target, {signal});
    });
    this.characterRendererPromise = Promise.resolve().then(() => load(host, this.rendererAbort.signal)).then(renderer => {
      if (this.closed || this.rendererAbort.signal.aborted) {
        try { renderer?.destroy(); } catch { /* the static SVG remains the fallback */ }
        return null;
      }
      this.characterRenderer = renderer;
      if (renderer) this.render();
      return renderer;
    }).catch(() => null);
  }
  private chapterPresenter(): ChapterPresentation {
    if (!this.chapterOptions) throw new Error('Chapter presentation unavailable');
    this.chapter ??= new ChapterPresentation(this.root, this.chapterOptions);
    return this.chapter;
  }

  private async prepareCharacterState(state: SceneState, signal: AbortSignal): Promise<void> {
    if (signal.aborted) throw abortError();
    if (!this.characterRendererPromise) {
      if (this.characterRendererMode === 'code-native-review') throw new Error('Code-native review renderer unavailable');
      return;
    }
    const renderer = await this.awaitWithAbort(this.characterRendererPromise, signal);
    if (signal.aborted) throw abortError();
    if (!renderer || this.characterRenderer !== renderer) {
      if (this.characterRendererMode === 'code-native-review') throw new Error('Code-native review renderer unavailable');
      return;
    }
    let prepared = false;
    try { prepared = await renderer.prepareState(state, signal); }
    catch {
      if (signal.aborted) throw abortError();
      if (this.characterRendererMode === 'code-native-review') {
        this.root.dataset['rendererError'] = 'preparation-failed';
        throw new Error('Code-native review preparation failed');
      }
      this.disableCharacterRenderer(renderer);
      return;
    }
    if (signal.aborted) throw abortError();
    if (!prepared) {
      if (this.characterRendererMode === 'code-native-review') throw new Error('Code-native review asset unavailable');
      this.disableCharacterRenderer(renderer);
    }
  }

  private awaitWithAbort<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
    if (signal.aborted) return Promise.reject(abortError());
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error?: Error, value?: T): void => {
        if (settled) return;
        settled = true;
        signal.removeEventListener('abort', onAbort);
        if (error) reject(error); else resolve(value as T);
      };
      const onAbort = (): void => finish(abortError());
      signal.addEventListener('abort', onAbort, {once: true});
      promise.then(value => finish(undefined, value), () => finish(new Error('Character renderer unavailable')));
      if (signal.aborted) onAbort();
    });
  }

  private disableCharacterRenderer(expected?: CharacterRendererPort): void {
    const renderer = this.characterRenderer;
    if (!renderer || (expected && renderer !== expected)) return;
    this.characterRenderer = null;
    try { renderer.destroy(); } catch { /* the inline SVG remains the fallback */ }
  }

  private element(name: string): HTMLElement {
    const target = this.root.querySelector<HTMLElement>(`[data-${name}]`);
    if (!target) throw new Error(`Missing scene slot: ${name}`);
    return target;
  }

  dismissPhoto(target: 'display'|'fixed_photo'|'all_photos'='all_photos'): void {
    if (this.closed || target==='fixed_photo' && this.state.photoKind==='generated') return;
    if (target==='all_photos') this.cancelPreparedGenerated();
    this.state = {...this.state, photoVisible: false};
    this.render(this.state, false);
    this.releaseDisplayedGenerated();
  }

  reconcilePhoto(snapshot: SessionView): void {
    const displayed = this.displayedGenerated?.effect;
    if (!displayed || snapshot.phase === 'stopped' || displayed.activity_seq !== snapshot.activity_seq
      || displayed.output_epoch !== snapshot.output_epoch) return;
    if (!snapshot.active_grants.some(effect => effect.id === displayed.id && effect.kind === 'media'
      && effect.value === displayed.value && effect.digest === displayed.digest
      && effect.activity_seq === displayed.activity_seq && effect.output_epoch === displayed.output_epoch)) this.dismissPhoto();
  }

  private cancelPreparedGenerated(): void {
    this.generatedPreparation?.abort(); this.generatedPreparation = null;
    this.preparedGenerated?.dispose(); this.preparedGenerated = null;
  }

  discardPrepared(effect: EffectView): void {
    if (this.preparedGenerated?.effect.id === effect.id) this.cancelPreparedGenerated();
  }

  private releaseDisplayedGenerated(): void {
    this.displayedGenerated?.dispose(); this.displayedGenerated = null;
    this.root.querySelector<HTMLElement>('[data-generated-photo]')?.replaceChildren();
  }

  private commitFixedPhoto(effect: EffectView, signal?: AbortSignal, canCommit?: () => boolean): void {
    if (effect.kind !== 'media' || effect.value !== 'trip_photo') throw new Error('Invalid fixed illustration');
    const photo = this.element('photo');
    const image = this.root.querySelector<HTMLImageElement>('[data-photo] img');
    // present() is the readiness-checked path; apply() remains the synchronous legacy seam.
    if (signal && (!image || !this.imageIsReady(image))) throw new Error('Image resource unavailable');
    const next = {...this.state, photoVisible: true, photoKind: 'authored' as const};
    const host = this.root.querySelector<HTMLElement>('[data-generated-photo]');
    const authored = this.root.querySelector<HTMLElement>('[data-authored-photo]');
    const label = this.root.querySelector<HTMLElement>('[data-photo-label]');
    const description = this.root.querySelector<HTMLElement>('[data-photo-description]');
    const close = this.root.querySelector<HTMLElement>('[data-photo-close]');
    if (this.closed || signal?.aborted || canCommit?.() === false) throw abortError();
    // Only the photo surface changes. No avatar redraw, implicit pose, or pose receipt.
    if (host) host.hidden = true;
    if (authored) authored.hidden = false;
    if (label) label.textContent = 'TRAVEL NOTE 07 · 原创插画';
    if (description) description.textContent = '有些光，值得等。';
    close?.setAttribute('aria-label', '关闭旅行插画');
    photo.hidden = false;
    this.state = next;
    this.releaseDisplayedGenerated();
  }

  apply(effect: EffectView): void {
    if (effect.kind === 'media' && effect.value === 'trip_photo') {
      this.commitFixedPhoto(effect); return;
    }
    if (effect.kind === 'media' && generatedPhotoIdentity(effect.value)) {
      this.commitGeneratedPhoto(effect);
      return;
    }
    const next = this.reduceForRenderer(effect);
    this.render(next, effect.kind !== 'subtitle');
    this.state = next;
    if (effect.kind === 'media') this.releaseDisplayedGenerated();
  }

  private commitGeneratedPhoto(effect: EffectView, signal?: AbortSignal, canCommit?: () => boolean): void {
    const prepared = this.preparedGenerated;
    if (!prepared || prepared.effect.id !== effect.id || prepared.effect.value !== effect.value
      || prepared.effect.digest !== effect.digest || prepared.effect.output_epoch !== effect.output_epoch
      || prepared.effect.activity_seq !== effect.activity_seq) throw new Error('Generated illustration is not prepared');
    const host = this.element('generated-photo');
    const authored = this.element('authored-photo');
    const label = this.element('photo-label');
    const description = this.element('photo-description');
    const photo = this.element('photo');
    const next = reduceSceneEffect(this.state, effect);
    // Nothing asynchronous or renderer-owned happens between final authority and visible commit.
    if (this.closed || signal?.aborted || canCommit?.() === false) throw abortError();
    prepared.commit();
    const previous = this.displayedGenerated;
    try {
      host.replaceChildren(prepared.image);
      authored.hidden = true;
      label.textContent = GENERATED_IMAGE_LABEL;
      description.textContent = GENERATED_IMAGE_DESCRIPTION;
      this.root.querySelector<HTMLElement>('[data-photo-close]')?.setAttribute('aria-label', '关闭剧情生成图');
      host.hidden = false;
      photo.hidden = false;
      this.state = next;
      this.displayedGenerated = prepared;
      this.preparedGenerated = null;
      previous?.dispose();
    } catch (error) {
      prepared.dispose(); this.preparedGenerated = null;
      photo.hidden = true;
      throw error;
    }
  }

  /** Called only after the controller's current gate check. A terminal Canvas copy
   * is necessary but never sufficient authority for the controller's final receipt. */
  async present(effect: EffectView, signal: AbortSignal, canCommit?: () => boolean): Promise<void> {
    if (this.closed || signal.aborted) throw abortError();
    if (isChapterEffect(effect)) {
      if (!this.chapter) throw new Error('Chapter presentation unavailable');
      if (effect.value === 'xiahe_recognition') {
        const renderer = this.characterRenderer;
        if (this.characterRendererMode !== 'code-native-review' || !renderer?.transitionState) throw new Error('Chapter recognition reaction unavailable');
        const operation = {}; this.recognitionOperation = operation;
        this.recognitionReaction = true;
        try {
          const smiled = await this.awaitWithAbort(renderer.transitionState({...this.state, emotion: 'emotion_happy'}, signal, 'emotion'), signal);
          if (!smiled || signal.aborted || this.closed || canCommit?.() === false) throw abortError();
          await this.chapter.present(effect, signal, canCommit ?? (() => true));
          if (this.recognitionOperation !== operation || signal.aborted || canCommit?.() === false) throw abortError();
          this.recognitionReaction = false;
          const restored = await this.awaitWithAbort(renderer.transitionState(this.state, signal, 'emotion'), signal);
          if (!restored || signal.aborted || this.closed || canCommit?.() === false) throw abortError();
        } catch (error) {
          this.chapter.cancelRecognition(effect); throw error;
        } finally {
          if (this.recognitionOperation === operation) {
            this.recognitionOperation = null; this.recognitionReaction = false;
            if (!this.closed && renderer === this.characterRenderer) this.render();
          }
        }
        return;
      }
      await this.chapter.present(effect, signal, canCommit ?? (() => true)); return;
    }
    if (effect.kind === 'media' && effect.value === 'trip_photo') {
      this.commitFixedPhoto(effect, signal, canCommit); return;
    }
    if (effect.kind === 'media' && generatedPhotoIdentity(effect.value)) {
      this.commitGeneratedPhoto(effect, signal, canCommit);
      return;
    }
    if (effect.kind === 'scene') {
      const prepared = this.preparedScene;
      if (!prepared || prepared.id !== effect.id || prepared.digest !== effect.digest
          || prepared.epoch !== this.scenePreparationEpoch || prepared.version !== this.backgroundVersion()
          || !this.imageIsReady(prepared.image)) throw new Error('Scene preparation is stale or unavailable');
      this.apply(effect);
      this.preparedScene = null;
      return;
    }
    const cameraAction = effect.kind === 'pose' && ['camera_raise', 'camera_ready'].includes(String(effect.value));
    const emotionAction = effect.kind === 'pose' && /^emotion_(normal|guarded|happy|shy)$/.test(String(effect.value));
    if ((!cameraAction && !emotionAction) || this.characterRendererMode !== 'code-native-review') {
      this.apply(effect);
      return;
    }
    const renderer = this.characterRenderer;
    if (!renderer?.transitionState) throw new Error('Animated character renderer unavailable');
    const target = this.reduceForRenderer(effect);
    try {
      const transition = renderer.transitionState(target, signal, emotionAction ? 'emotion' : 'camera');
      // render() preserves camera interpolation while describing its current state.
      this.render();
      const completed = await this.awaitWithAbort(transition, signal);
      if (!completed || signal.aborted || this.closed || renderer !== this.characterRenderer) throw abortError();
      // Captions/phase may have changed during motion; commit only this effect into
      // the latest state so completion cannot roll them back to its start snapshot.
      this.apply(effect);
    } catch (error) {
      if (!this.closed && renderer === this.characterRenderer) this.render();
      throw error;
    }
  }

  private reduceForRenderer(effect: EffectView): SceneState {
    const value = String(effect.value);
    const appearance = /^(outfit_|emotion_|accessory_)/.test(value);
    if (this.characterRendererMode !== 'code-native-review' && effect.kind === 'pose' && value === 'camera_raise') {
      throw new Error('Animated camera action requires code-native rendering');
    }
    if (this.characterRendererMode !== 'code-native-review' && effect.kind === 'pose' && appearance) {
      if (!['outfit_black_jacket', 'emotion_normal', 'accessory_camera_clip'].includes(value)) {
        throw new Error('Appearance state requires explicit code-native review rendering');
      }
    }
    const next = reduceSceneEffect(this.state, effect);
    if (this.characterRendererMode !== 'code-native-review') return next;
    // Environment/media change their own visible facts, never an unsupported implicit face/camera pose.
    if (effect.kind === 'scene' || effect.kind === 'media') {
      return {...next, action: this.state.action, expression: this.state.expression};
    }
    return next;
  }

  /**
   * Wait for the already-mounted local illustration without changing visible DOM state.
   * This establishes decoded-resource readiness only; it cannot establish browser paint or
   * that a person looked at the image. The controller revalidates its gate before apply().
   */
  async prepare(effect: EffectView, signal: AbortSignal): Promise<void> {
    if (signal.aborted || this.closed) throw abortError();
    if (isChapterEffect(effect)) {
      const chapter = this.chapterPresenter();
      if (effect.value === 'xiahe_recognition') {
        if (this.characterRendererMode !== 'code-native-review') throw new Error('Chapter recognition reaction unavailable');
        await this.prepareCharacterState({...this.state, emotion: 'emotion_happy'}, signal);
      }
      await chapter.prepare(effect, signal); return;
    }
    const sceneEpoch = this.scenePreparationEpoch;
    // Authorized text does not depend on optional character readiness.
    if (effect.kind === 'subtitle') return;
    if (effect.kind === 'media' && effect.value === 'trip_photo') {
      const image = this.root.querySelector<HTMLImageElement>('[data-photo] img');
      if (!image) throw new Error('Image resource unavailable');
      await this.prepareImage(image, signal);
      return;
    }
    if (effect.kind === 'media' && generatedPhotoIdentity(effect.value)) {
      if (!this.generatedImage) throw new Error('Generated illustration unavailable');
      this.cancelPreparedGenerated();
      const preparation = new AbortController(); this.generatedPreparation = preparation;
      const combined = AbortSignal.any([signal, preparation.signal]);
      const prepared = await prepareGeneratedImage(effect, combined,
        {...this.generatedImage, timeoutMs: this.mediaReadinessTimeoutMs});
      if (this.closed || combined.aborted || this.generatedPreparation !== preparation) {
        prepared.dispose(); throw abortError();
      }
      this.preparedGenerated = prepared;
      return;
    }
    const nextState = this.reduceForRenderer(effect);
    await this.prepareCharacterState(nextState, signal);
    if (signal.aborted) throw abortError();
    if (effect.kind === 'scene') {
      const epoch = sceneEpoch;
      const version = this.backgroundVersion();
      const image = this.root.querySelector<HTMLImageElement>(`[data-scene-source="${version}"]`);
      const source = version === 'painterly-v3' ? '/assets/scene/cafe-painterly-lighting-v3-table-free.png' : '/assets/scene/cafe-night.svg';
      if (!image || image.getAttribute('src') !== source) throw new Error('Scene resource unavailable');
      await this.prepareImage(image, signal);
      if (signal.aborted || this.closed || epoch !== this.scenePreparationEpoch) throw abortError();
      if (version !== this.backgroundVersion()) throw new Error('Scene selection changed during preparation');
      this.preparedScene = {id: effect.id, digest: effect.digest, epoch, version, image};
      return;
    }
    if (effect.kind !== 'media' || (effect.value !== 'trip_photo' && effect.value !== 'trip_photo_placeholder')) return;
    const image = this.root.querySelector<HTMLImageElement>('[data-photo] img');
    if (!image) throw new Error('Image resource unavailable');
    await this.prepareImage(image, signal);
  }

  private async prepareImage(image: HTMLImageElement, signal: AbortSignal): Promise<void> {
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
    this.recognitionOperation = null;
    this.recognitionReaction = false;
    this.chapter?.prepareInput();
    this.cancelPreparedGenerated();
    this.cancelScenePreparation();
    this.state = { ...this.state, phase: 'thinking', subtitle: '' };
    this.render();
  }

  stop(): void {
    this.recognitionOperation = null;
    this.recognitionReaction = false;
    this.chapter?.stop();
    this.cancelPreparedGenerated();
    this.state = { ...this.state, phase: 'idle', subtitle: this.state.photoVisible
      ? (this.state.photoKind === 'generated' ? '已停下。剧情生成图还留在这里。' : '已停下。那张旅行插画还留在这里。')
      : '已停下。我们可以慢慢说。' };
    this.cancelScenePreparation();
    try { this.characterRenderer?.stop?.(); } catch { this.disableCharacterRenderer(); }
    try { this.render(); } catch { this.disableCharacterRenderer(); this.render(); }
  }

  /** Allow the owning page lifecycle to pause the local visual loop without closing it. */
  setPaused(paused: boolean): void {
    try { this.characterRenderer?.setPaused?.(paused); }
    catch { this.disableCharacterRenderer(); }
  }

  setPhase(phase: ScenePhase): void {
    const next = { ...this.state, phase };
    this.render(next);
    this.state = next;
  }

  setExpression(expression: SceneExpression): void {
    const next = { ...this.state, expression };
    this.render(next, true);
    this.state = next;
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.chapter?.close();
    this.cancelPreparedGenerated();
    this.releaseDisplayedGenerated();
    this.element('photo').hidden = true;
    this.cancelScenePreparation();
    this.rendererAbort.abort();
    this.disableCharacterRenderer();
  }

  reconcileChapter(snapshot: SessionView): void {
    this.chapter?.reconcile(snapshot.chapter_projection ?? null, snapshot.activity_seq);
  }
  invalidateChapter(): void { this.recognitionOperation = null; this.recognitionReaction = false; this.chapter?.stop(); }

  private render(state: SceneState = this.state, requireReviewCommit = false): void {
    // Resolve every DOM destination before asking the renderer to commit. A failed
    // explicit review commit must leave both the scene and its text description unchanged.
    const subtitle = this.element('subtitle');
    const photo = this.element('photo');
    const pose = this.element('pose');
    const sceneLabel = this.element('scene-label');
    const phaseLabel = this.element('phase-label');
    const characterDescription = this.element('character-description');
    const rendererStatus = this.characterRenderer?.getStatus?.();
    const reviewWarning = this.characterRendererMode === 'code-native-review'
      ? ' · 代码角色审阅中 · 外观未经认可' : '';
    const warningText = rendererStatus?.mode === 'code-native-review' ? ` ${rendererStatus.warnings.join(' ')}` : '';
    if (requireReviewCommit && this.characterRendererMode === 'code-native-review' && !this.characterRenderer) {
      throw new Error('Code-native review renderer unavailable');
    }
    try { this.characterRenderer?.render(this.recognitionReaction ? {...state, emotion: 'emotion_happy'} : state); }
    catch {
      if (this.characterRendererMode === 'code-native-review') {
        this.root.dataset['rendererError'] = 'commit-failed';
        if (requireReviewCommit) throw new Error('Code-native review render did not commit');
      } else this.disableCharacterRenderer();
    }
    this.root.dataset.phase = state.phase;
    this.root.dataset.expression = state.expression;
    const motion = this.characterRenderer?.getMotionState?.();
    const partial = motion !== undefined && motion.progress > 0 && motion.progress < 1;
    const moving = motion?.status === 'running';
    const visibleAction = motion ? (motion.progress === 1 ? 'camera_raise' : 'camera_ready') : state.action;
    const actionLabel = moving ? '正在移动相机，动作尚未完成'
      : partial ? '相机动作已中断，停在中途' : ACTION_LABELS[visibleAction];
    this.root.dataset.action = moving || partial ? 'camera_partial' : visibleAction;
    if (motion) {
      this.root.dataset['cameraMotionStatus'] = motion.status;
      this.root.dataset['cameraProgress'] = String(motion.progress);
    }
    this.root.dataset.scene = state.environment;
    this.root.dataset['outfit'] = state.outfit;
    this.root.dataset['emotion'] = state.emotion;
    this.root.dataset['accessory'] = state.accessory;
    this.root.dataset['characterRendererMode'] = this.characterRendererMode;
    if (rendererStatus?.mode === 'code-native-review' && this.characterRenderer) this.root.dataset['visualAcceptance'] = 'pending';
    else delete this.root.dataset['visualAcceptance'];
    subtitle.textContent = state.subtitle;
    photo.hidden = !state.photoVisible;
    const generated = state.photoKind === 'generated';
    const generatedHost = this.root.querySelector<HTMLElement>('[data-generated-photo]');
    const authored = this.root.querySelector<HTMLElement>('[data-authored-photo]');
    const photoLabel = this.root.querySelector<HTMLElement>('[data-photo-label]');
    const photoDescription = this.root.querySelector<HTMLElement>('[data-photo-description]');
    if (generatedHost) generatedHost.hidden = !generated;
    if (authored) authored.hidden = generated;
    if (photoLabel) photoLabel.textContent = generated ? GENERATED_IMAGE_LABEL : 'TRAVEL NOTE 07 · 原创插画';
    if (photoDescription) photoDescription.textContent = generated ? GENERATED_IMAGE_DESCRIPTION : '有些光，值得等。';
    this.root.querySelector<HTMLElement>('[data-photo-close]')?.setAttribute('aria-label', generated ? '关闭剧情生成图' : '关闭旅行插画');
    pose.textContent = actionLabel;
    sceneLabel.textContent = SCENE_LABELS[state.environment];
    phaseLabel.textContent = `${PHASE_LABELS[state.phase]}${reviewWarning}`;
    const appearance = this.characterRendererMode === 'code-native-review'
      ? `神情${EMOTION_LABELS[state.emotion]}，穿着${OUTFIT_LABELS[state.outfit]}，佩戴${ACCESSORY_LABELS[state.accessory]}`
      : `神情${EXPRESSION_LABELS[state.expression]}`;
    characterDescription.textContent =
      `MIRA，26 岁的旅行摄影师。${appearance}，${actionLabel}。${PHASE_LABELS[state.phase]}。${reviewWarning}${warningText}`;
  }
}
