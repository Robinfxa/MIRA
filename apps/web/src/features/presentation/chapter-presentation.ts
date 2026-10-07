import type {EffectView, ChapterProjectionView} from '../../shared/generated/contracts.js';

export const CHAPTER_SCENES = ['xiahe_recognition', 'xiahe_gift_offer', 'xiahe_photo_handover'] as const;
export const CHAPTER_PHOTO_SOURCE = '/assets/scene/trip-memory.svg';
export interface ChapterChoice {readonly effect: EffectView; readonly choice: 'accept' | 'decline'; readonly text: string;}
export interface ChapterPresentationOptions {
  readonly onChoice: (choice: ChapterChoice) => void;
  readonly isOfferCurrent: (effect: EffectView) => boolean;
  readonly timeoutMs?: number;
}
/** Bounded application projection. Reconciliation can revoke UI; it cannot create
 * recognition or gift presentation from a summary alone. */
export type ChapterProjection = ChapterProjectionView;
export function isChapterEffect(effect: EffectView): boolean {
  return effect.kind === 'scene' && CHAPTER_SCENES.includes(effect.value as typeof CHAPTER_SCENES[number]);
}
const aborted = (): Error => Object.assign(new Error('Chapter presentation cancelled'), {name: 'AbortError'});
const identity = (effect: EffectView): string => JSON.stringify([effect.id, effect.digest, effect.value, effect.output_epoch, effect.activity_seq]);
type Prepared = {effect: EffectView; key: string; generation: number; image: HTMLImageElement | null};

/** Finite DOM presentation only. The existing grant gate and application own all
 * story state and receipts. Neither a choice nor resource preparation is a gift. */
export class ChapterPresentation {
  private readonly document: Document;
  private readonly window: Window;
  private readonly relationship: HTMLElement;
  private readonly gift: HTMLElement;
  private readonly print: HTMLElement;
  private readonly photo: HTMLElement;
  private readonly status: HTMLElement;
  private readonly detail: HTMLElement;
  private readonly actions: HTMLElement;
  private readonly accept: HTMLButtonElement;
  private readonly decline: HTMLButtonElement;
  private readonly timeoutMs: number;
  private epoch = new AbortController();
  private generation = 0;
  private prepared: Prepared | null = null;
  private offer: {effect: EffectView; generation: number; chosen: boolean} | null = null;
  private savedOffer: EffectView | null = null;
  private presenting = false;
  private recognized = false;
  private recognitionActivity = -1;
  private pendingRecognition: {activity: number; generation: number; signal: AbortSignal} | null = null;
  private received = false;
  private closed = false;
  private readonly completed = new Set<string>();
  private readonly animations = new Set<Animation>();

  constructor(private readonly root: HTMLElement, private readonly options: ChapterPresentationOptions) {
    this.document = root.ownerDocument;
    const window = this.document.defaultView;
    if (!window) throw new Error('Chapter browser surface unavailable');
    this.window = window;
    this.timeoutMs = options.timeoutMs ?? 5000;
    if (!Number.isSafeInteger(this.timeoutMs) || this.timeoutMs < 1 || this.timeoutMs > 30000) throw new RangeError('Invalid chapter presentation timeout');
    const host = root.querySelector<HTMLElement>('.stage-visual');
    if (!host) throw new Error('Chapter stage unavailable');
    const element = <T extends keyof HTMLElementTagNameMap>(tag: T, name: string, className: string): HTMLElementTagNameMap[T] => {
      const node = this.document.createElement(tag); node.dataset[name] = ''; node.className = className; return node;
    };
    this.relationship = element('div', 'chapterRelationship', 'chapter-relationship');
    this.relationship.hidden = true;
    this.relationship.setAttribute('role', 'status');
    const relationshipTitle = element('strong', 'chapterRelationshipTitle', '');
    relationshipTitle.textContent = '夏禾 · 老朋友';
    const relationshipDetail = element('span', 'chapterRelationshipDetail', '');
    relationshipDetail.textContent = 'MIRA 认出了你';
    this.relationship.append(relationshipTitle, relationshipDetail);
    this.gift = element('section', 'chapterGift', 'chapter-gift');
    this.gift.hidden = true;
    this.gift.setAttribute('aria-label', 'MIRA 的照片赠予');
    this.print = element('figure', 'chapterPrint', 'chapter-print');
    this.photo = element('div', 'chapterPhoto', 'chapter-print-image');
    const caption = element('figcaption', 'chapterPrintCaption', '');
    caption.textContent = '有些光，值得等。';
    this.print.append(this.photo, caption);
    this.status = element('strong', 'chapterStatus', 'chapter-gift-status');
    this.status.setAttribute('role', 'status'); this.status.setAttribute('aria-live', 'polite');
    this.detail = element('span', 'chapterDetail', 'chapter-gift-detail');
    this.actions = element('div', 'chapterActions', 'chapter-gift-actions');
    this.accept = element('button', 'chapterAccept', 'chapter-gift-accept');
    this.accept.type = 'button'; this.accept.textContent = '收下照片';
    this.decline = element('button', 'chapterDecline', 'chapter-gift-decline');
    this.decline.type = 'button'; this.decline.textContent = '暂时不收';
    this.accept.addEventListener('click', () => this.choose('accept'));
    this.decline.addEventListener('click', () => this.choose('decline'));
    this.actions.append(this.accept, this.decline);
    this.gift.append(this.print, this.status, this.detail, this.actions);
    // A strip beside the dialogue keeps the print and 44px choices clear of the
    // unchanged face/hand drawing, including 320px viewports.
    root.insertBefore(this.relationship, host.nextSibling);
    root.insertBefore(this.gift, this.relationship.nextSibling);
    this.disableChoices();
  }

  private disableChoices(): void { this.accept.disabled = true; this.decline.disabled = true; }
  private choose(choice: ChapterChoice['choice']): void {
    const offer = this.offer;
    if (!offer || offer.chosen || this.closed || this.presenting || this.gift.hidden || this.accept.disabled
      || offer.generation !== this.generation || !this.options.isOfferCurrent(offer.effect)) return;
    // Lock synchronously before invoking application code, which may re-enter Stop/input.
    offer.chosen = true; this.disableChoices();
    this.status.textContent = choice === 'accept' ? '正在回应 MIRA…' : '你选择了暂时不收';
    this.options.onChoice({effect: offer.effect, choice, text: choice === 'accept' ? '我收下这张照片' : '暂时不收照片'});
  }

  private assertCurrent(signal: AbortSignal, generation: number, canCommit: () => boolean = () => true): void {
    if (this.closed || signal.aborted || generation !== this.generation || !canCommit()) throw aborted();
  }
  private assertVisible(node: HTMLElement): void {
    if (this.document.visibilityState === 'hidden' || !this.root.isConnected || !node.isConnected
      || node.hidden || node.getClientRects().length === 0) throw new Error('Chapter surface is not visible');
    const bounds = node.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) throw new Error('Chapter surface has no visible size');
  }
  private wait<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
    if (signal.aborted) return Promise.reject(aborted());
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error?: unknown, value?: T): void => {
        if (settled) return; settled = true; globalThis.clearTimeout(timer); signal.removeEventListener('abort', onAbort);
        if (error) reject(error); else resolve(value as T);
      };
      const onAbort = (): void => finish(aborted());
      const timer = globalThis.setTimeout(() => finish(new Error('Chapter presentation timed out')), this.timeoutMs);
      signal.addEventListener('abort', onAbort, {once: true});
      promise.then(value => finish(undefined, value), error => finish(error));
      if (signal.aborted) onAbort();
    });
  }

  async prepare(effect: EffectView, signal: AbortSignal): Promise<void> {
    const generation = this.generation, key = identity(effect);
    this.assertCurrent(signal, generation);
    if (!isChapterEffect(effect) || this.completed.has(key) || this.presenting
      || (this.received && effect.value !== 'xiahe_recognition')) throw new Error('Chapter event is not preparable');
    const candidate: Prepared = {effect, key, generation, image: null};
    this.prepared = candidate;
    const combined = AbortSignal.any([signal, this.epoch.signal]);
    try {
      if (effect.value !== 'xiahe_recognition') {
        const image = this.document.createElement('img');
        image.src = CHAPTER_PHOTO_SOURCE; image.width = 600; image.height = 460;
        image.alt = 'MIRA 的旅行照片画面：雨后海岸与山岬上亮着暖灯的灯塔。';
        // decode() waits for load as well, without attaching or displaying the asset.
        await this.wait(image.decode(), combined);
        if (!image.complete || image.naturalWidth <= 0 || image.naturalHeight <= 0) throw new Error('Chapter photo unavailable');
        candidate.image = image;
      }
      this.assertCurrent(combined, generation);
      if (this.prepared !== candidate) throw aborted();
    } catch (error) { if (this.prepared === candidate) this.prepared = null; throw error; }
  }

  private async frame(signal: AbortSignal): Promise<void> {
    let frame: number | null = null;
    try { await this.wait(new Promise<void>(resolve => { frame = this.window.requestAnimationFrame(() => resolve()); }), signal); }
    finally { if (frame !== null) this.window.cancelAnimationFrame(frame); }
  }
  private async animate(node: HTMLElement, keyframes: Keyframe[], duration: number, signal: AbortSignal): Promise<void> {
    if (this.window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const animation = node.animate(keyframes, {duration, easing: 'cubic-bezier(.2,.65,.3,1)', fill: 'none'});
    this.animations.add(animation);
    try { await this.wait(animation.finished, signal); }
    finally { animation.cancel(); this.animations.delete(animation); }
  }

  async present(effect: EffectView, signal: AbortSignal, canCommit: () => boolean): Promise<void> {
    const prepared = this.prepared, generation = this.generation, combined = AbortSignal.any([signal, this.epoch.signal]);
    this.assertCurrent(combined, generation, canCommit);
    if (!prepared || prepared.key !== identity(effect) || prepared.generation !== generation || this.presenting
      || this.completed.has(prepared.key)) throw new Error('Chapter preparation is stale or unavailable');
    if (this.document.visibilityState === 'hidden' || !this.root.isConnected) throw new Error('Chapter surface is not visible');
    this.prepared = null; this.presenting = true; this.offer = null; this.disableChoices();
    const recognition = effect.value === 'xiahe_recognition';
    const recognitionAttempt = recognition ? {activity: effect.activity_seq, generation, signal: combined} : null;
    if (recognitionAttempt) this.pendingRecognition = recognitionAttempt;
    const target = recognition ? this.relationship : this.gift;
    try {
      // No await between the last grant check and the visible DOM change.
      this.assertCurrent(combined, generation, canCommit);
      if (recognition) {
        this.relationship.hidden = false;
        await this.animate(this.relationship, [{opacity: 0, transform: 'translateY(5px)'}, {opacity: 1, transform: 'translateY(0)'}], 360, combined);
      } else {
        if (!prepared.image?.complete || prepared.image.naturalWidth <= 0) throw new Error('Chapter photo unavailable');
        this.photo.replaceChildren(prepared.image);
        this.gift.hidden = false;
        this.actions.hidden = effect.value !== 'xiahe_gift_offer';
        this.gift.dataset['state'] = effect.value === 'xiahe_gift_offer' ? 'offering' : 'transferring';
        this.status.textContent = effect.value === 'xiahe_gift_offer' ? '这张照片，想留给你。' : 'MIRA 把照片递向你…';
        this.detail.textContent = effect.value === 'xiahe_gift_offer' ? '可以收下，也可以暂时不收。' : '雨停之前，把这一刻留住。';
        await this.animate(this.print, effect.value === 'xiahe_gift_offer'
          ? [{opacity: 0, transform: 'translateY(10px) rotate(-5deg)'}, {opacity: 1, transform: 'translateY(0) rotate(-3deg)'}]
          : [{transform: 'translateY(-12px) scale(.88) rotate(-3deg)'}, {transform: 'translateY(10px) scale(1.08) rotate(0deg)', offset: .78}, {transform: 'translateY(0) scale(1) rotate(0deg)'}],
          effect.value === 'xiahe_gift_offer' ? 420 : 900, combined);
        this.assertCurrent(combined, generation, canCommit);
        if (effect.value === 'xiahe_photo_handover') {
          this.gift.dataset['state'] = 'received';
          this.status.textContent = '照片已收下'; this.detail.textContent = 'MIRA 留给夏禾 · 雨夜的纪念';
        } else this.gift.dataset['state'] = 'offered';
      }
      // WA completion alone is not a presentation receipt: the terminal DOM state
      // must survive a browser draw boundary, with authority rechecked afterward.
      this.assertVisible(target);
      await this.frame(combined); await this.frame(combined);
      this.assertCurrent(combined, generation, canCommit); this.assertVisible(target);
      this.completed.add(prepared.key);
      if (recognition) { this.recognized = true; this.recognitionActivity = effect.activity_seq; }
      else if (effect.value === 'xiahe_photo_handover') this.received = true;
      else {
        this.savedOffer = effect;
        this.offer = {effect, generation, chosen: false};
        this.accept.disabled = !this.options.isOfferCurrent(effect); this.decline.disabled = this.accept.disabled;
      }
    } catch (error) {
      if (recognition) this.relationship.hidden = !this.recognized;
      else { this.gift.hidden = !this.received; if (!this.received) this.gift.dataset['state'] = 'cancelled'; }
      throw error;
    } finally {
      if (this.pendingRecognition === recognitionAttempt) this.pendingRecognition = null;
      this.presenting = false;
    }
  }

  /** Input, Stop and close invalidate local choices before any network work. */
  stop(): void {
    this.generation++; this.epoch.abort(); this.epoch = new AbortController(); this.prepared = null;
    this.pendingRecognition = null;
    for (const animation of this.animations) animation.cancel();
    this.offer = null; this.disableChoices(); this.actions.hidden = true;
    if (!this.recognized) this.relationship.hidden = true;
    if (!this.received) { this.gift.hidden = true; this.gift.dataset['state'] = 'cancelled'; }
  }
  prepareInput(): void { this.stop(); }
  /** Outer renderer reaction is part of recognition presentation too. */
  cancelRecognition(effect: EffectView): void {
    if (effect.value !== 'xiahe_recognition' || effect.activity_seq !== this.recognitionActivity) return;
    this.recognized = false; this.relationship.hidden = true; this.completed.delete(identity(effect));
  }
  close(): void { if (this.closed) return; this.closed = true; this.stop(); this.relationship.remove(); this.gift.remove(); }
  /** Only the application projection may clear a corrected/ended relationship. */
  resetRelationship(): void {
    this.stop(); this.recognized = false; this.received = false;
    this.savedOffer = null;
    this.relationship.hidden = true; this.gift.hidden = true; this.gift.dataset['state'] = 'cancelled';
  }
  reconcile(projection: ChapterProjection | null, activity: number): void {
    if (this.closed) return;
    if (!projection) { this.stop(); this.relationship.hidden = true; return; }
    const pending = this.pendingRecognition;
    const currentRecognition = projection.pending_transition === 'x.recognize' && !projection.suspended
      && ((pending !== null && pending.activity === activity && pending.generation === this.generation && !pending.signal.aborted)
        || (this.recognized && this.recognitionActivity === activity));
    // Recognition becomes application state only after its presentation receipt.
    // A normal poll may therefore still say role_active=false while this exact
    // recognition is visibly running or its completed cue awaits that receipt.
    if (!projection.role_active && !currentRecognition && activity >= this.recognitionActivity) {
      this.recognized = false; this.relationship.hidden = true;
    }
    const saved = this.savedOffer;
    if (!this.offer && saved && !this.received && projection.role_active && !projection.suspended
      && projection.stage === 'gift_offered' && projection.pending_transition === null
      && projection.gift_offer_effect_id === saved.id && projection.gift_offer_effect_digest === saved.digest
      && this.options.isOfferCurrent(saved)) {
      this.offer = {effect: saved, generation: this.generation, chosen: false};
      this.gift.hidden = false; this.gift.dataset['state'] = 'offered'; this.actions.hidden = false;
      this.status.textContent = '这张照片，想留给你。';
      this.detail.textContent = '可以收下，也可以暂时不收。';
    }
    const offer = this.offer;
    if (offer && !offer.chosen) {
      const authorized = projection.role_active && !projection.suspended && projection.stage === 'gift_offered'
        && projection.pending_transition === null
        && projection.gift_offer_effect_id === offer.effect.id
        && projection.gift_offer_effect_digest === offer.effect.digest
        && this.options.isOfferCurrent(offer.effect);
      this.accept.disabled = !authorized; this.decline.disabled = !authorized;
      if (!projection.role_active || projection.suspended || projection.gift_offer_effect_id !== offer.effect.id) { this.offer = null; this.actions.hidden = true; }
    }
  }
}
