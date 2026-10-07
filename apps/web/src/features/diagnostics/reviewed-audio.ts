import type {
  ReviewedAudioActionResponse,
  ReviewedAudioConfirmRequest,
  ReviewedAudioReviewResponse,
  ReviewedAudioStatusResponse,
} from '../../shared/generated/contracts.js';

export type ReviewedAudioPreview = {
  readonly pcm16le: Uint8Array;
  readonly sampleRateHz: 16000 | 24000 | 48000;
  readonly kind: 'audio_input' | 'audio_output';
  readonly digest: string;
};

export interface ReviewedAudioApi {
  reviewedAudioStatus(signal?: AbortSignal): Promise<ReviewedAudioStatusResponse>;
  setReviewedAudioRecording(enabled: boolean, consent: boolean, signal?: AbortSignal): Promise<ReviewedAudioActionResponse>;
  requestReviewedAudioReview(streamId: string, signal?: AbortSignal): Promise<ReviewedAudioReviewResponse>;
  reviewedAudioPreview(review: ReviewedAudioReviewResponse, signal?: AbortSignal): Promise<ReviewedAudioPreview>;
  confirmReviewedAudio(review: ReviewedAudioReviewResponse, request: ReviewedAudioConfirmRequest,
    signal?: AbortSignal): Promise<ReviewedAudioActionResponse>;
}

export interface ReviewedAudioAuditionPort {
  auditionReviewedAudio(pcm16le: Uint8Array, sampleRateHz: number): Promise<boolean>;
  stopReviewedAudioAudition(): void;
}

export interface ReviewedAudioElements {
  readonly notice: HTMLElement;
  readonly status: HTMLElement;
  readonly scope: HTMLElement;
  readonly eligibilityNotice: HTMLElement;
  readonly consent: HTMLInputElement;
  readonly enable: HTMLButtonElement;
  readonly disable: HTMLButtonElement;
  readonly review: HTMLButtonElement;
  readonly clip: HTMLElement;
  readonly clipMetadata: HTMLElement;
  readonly preview: HTMLButtonElement;
  readonly audition: HTMLButtonElement;
  readonly auditionStatus: HTMLElement;
  readonly attestation: HTMLInputElement;
  readonly confirm: HTMLButtonElement;
  readonly cancel: HTMLButtonElement;
  readonly result: HTMLElement;
}

export function parseReviewedAudioStatus(raw: unknown): ReviewedAudioStatusResponse {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Reviewed audio status unavailable');
  const value = raw as Record<string, unknown>;
  const keys = ['scope', 'recording_active', 'has_pending_audio', 'staged_bytes', 'max_audio_bytes',
    'expires_in_seconds', 'pending_stream_id', 'pending_kind', 'input_completion_ready', 'notice', 'scope_notice'];
  if (Object.keys(value).some(key => !keys.includes(key)) || (value['scope'] !== undefined && value['scope'] !== 'application')
    || typeof value['recording_active'] !== 'boolean' || typeof value['has_pending_audio'] !== 'boolean'
    || typeof value['input_completion_ready'] !== 'boolean'
    || !Number.isSafeInteger(value['staged_bytes']) || (value['staged_bytes'] as number) < 0
    || !Number.isSafeInteger(value['max_audio_bytes']) || (value['max_audio_bytes'] as number) < 2
    || (value['max_audio_bytes'] as number) > 512 * 1024
    || typeof value['expires_in_seconds'] !== 'number' || !Number.isFinite(value['expires_in_seconds'])
    || value['expires_in_seconds'] < 0 || value['expires_in_seconds'] > 60
    || (value['pending_stream_id'] !== undefined && value['pending_stream_id'] !== null
      && (typeof value['pending_stream_id'] !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value['pending_stream_id'])))
    || (value['pending_kind'] !== undefined && value['pending_kind'] !== null
      && value['pending_kind'] !== 'audio_input' && value['pending_kind'] !== 'audio_output')
    || typeof value['notice'] !== 'string' || value['notice'].length > 500
    || typeof value['scope_notice'] !== 'string' || value['scope_notice'].length > 500) {
    throw new Error('Reviewed audio status unavailable');
  }
  if ((value['has_pending_audio'] === true && (typeof value['pending_stream_id'] !== 'string'
    || typeof value['pending_kind'] !== 'string' || (value['pending_kind'] !== 'audio_input' && value['pending_kind'] !== 'audio_output')
    || (value['staged_bytes'] as number) < 2 || (value['expires_in_seconds'] as number) <= 0))
    || (value['input_completion_ready'] === true && (value['recording_active'] !== true
      || value['pending_kind'] !== 'audio_input' || value['has_pending_audio'] !== true))) {
    throw new Error('Reviewed audio status unavailable');
  }
  return Object.freeze({...value}) as unknown as ReviewedAudioStatusResponse;
}

function validReview(review: ReviewedAudioReviewResponse): boolean {
  return /^[0-9a-f]{32}$/.test(review.review_id) && /^[0-9a-f]{64}$/.test(review.digest)
    && (review.kind === 'audio_input' || review.kind === 'audio_output')
    && (review.sample_rate_hz === 16000 || review.sample_rate_hz === 24000 || review.sample_rate_hz === 48000)
    && Number.isSafeInteger(review.byte_count) && review.byte_count >= 2 && review.byte_count <= 512 * 1024
    && Number.isFinite(review.expires_in_seconds) && review.expires_in_seconds > 0 && review.expires_in_seconds <= 60
    && typeof review.preview_path === 'string' && review.preview_path.length <= 500;
}

type Primitives = {
  readonly setTimeout?: (fn: () => void, ms: number) => number;
  readonly clearTimeout?: (id: number) => void;
  readonly now?: () => number;
};

/** UI coordinator for the per-buffer review flow. It never starts microphone capture or auto-plays. */
export class ReviewedAudioPanel {
  private closed = false;
  private started = false;
  private canEnable = false;
  private busy = false;
  private statusFresh = false;
  private readonly inputFences = new Set<symbol>();
  private modeEpoch = 0;
  private reviewEpoch = 0;
  private statusSequence = 0;
  private statusValue: ReviewedAudioStatusResponse | null = null;
  private reviewValue: ReviewedAudioReviewResponse | null = null;
  private streamValue: string | null = null;
  private pcm: Uint8Array | null = null;
  private expiryTimer: number | null = null;
  private pollTimer: number | null = null;
  private statusAbort: AbortController | null = null;
  private modeAbort: AbortController | null = null;
  private reviewAbort: AbortController | null = null;
  private expiresAt = 0;
  private auditionActive = false;
  private continuousListeningBlocked = false;
  private heardFullClip = false;
  private readonly later: (fn: () => void, ms: number) => number;
  private readonly cancelLater: (id: number) => void;
  private readonly now: () => number;

  constructor(private readonly api: ReviewedAudioApi, private readonly audition: ReviewedAudioAuditionPort,
    private readonly elements: ReviewedAudioElements, primitives: Primitives = {}) {
    this.later = primitives.setTimeout ?? ((fn, ms) => globalThis.setTimeout(fn, ms));
    this.cancelLater = primitives.clearTimeout ?? (id => globalThis.clearTimeout(id));
    this.now = primitives.now ?? (() => Date.now());
    elements.enable.addEventListener('click', () => { void this.enable(); });
    elements.disable.addEventListener('click', () => { void this.disable(); });
    elements.review.addEventListener('click', () => { void this.requestReview(); });
    elements.preview.addEventListener('click', () => { void this.loadPreview(); });
    elements.audition.addEventListener('click', () => { void this.playPreview(); });
    elements.confirm.addEventListener('click', () => { void this.confirmSave(); });
    elements.cancel.addEventListener('click', () => { void this.rejectAndClear(); });
    elements.consent.addEventListener('change', () => this.render());
    elements.attestation.addEventListener('change', () => this.render());
    this.clearReview(false);
    this.render();
  }

  start(): void {
    if (this.closed || this.started) return;
    this.started = true;
    void this.refresh();
  }

  setCanEnable(value: boolean): void {
    this.canEnable = value;
    this.elements.eligibilityNotice.hidden = value;
    this.elements.eligibilityNotice.textContent = value ? ''
      : '当前离线 / 排练模式不开放真实音频录制；默认麦克风仍关闭。';
    this.render();
  }

  get recordingActive(): boolean { return this.statusValue?.recording_active === true; }

  /** Continuous capture is not wired to the separate raw-audio review store. */
  setContinuousListeningBlocked(value: boolean): void {
    if (this.closed || this.continuousListeningBlocked === value) return;
    this.continuousListeningBlocked = value;
    if (value) {
      this.invalidateReview(true);
      if (this.auditionActive) this.audition.stopReviewedAudioAudition();
      this.auditionActive = false;
      this.heardFullClip = false;
    }
    this.render();
  }

  /** Call synchronously before a newer user input is dispatched. */
  invalidateForNewInput(): () => void {
    const token = Symbol('review-input-fence');
    this.inputFences.add(token);
    this.statusSequence++;
    this.statusAbort?.abort(); this.statusAbort = null;
    this.invalidateReview(true);
    this.statusValue = this.statusValue ? Object.freeze({...this.statusValue,
      has_pending_audio: false, staged_bytes: 0, expires_in_seconds: 0,
      pending_stream_id: null, pending_kind: null}) : null;
    this.render();
    return () => {
      if (this.closed || !this.inputFences.delete(token)) return;
      if (this.inputFences.size === 0) void this.refresh();
      else this.render();
    };
  }

  /** Called by the central Stop action after it synchronously blocks character playback. */
  invalidateForStop(): () => void { return this.invalidateForNewInput(); }

  /** Called when the SessionController's central playback owner reports audition state. */
  auditionState(state: 'starting' | 'playing' | 'stopped' | 'completed' | 'failed'): void {
    this.auditionActive = state === 'starting' || state === 'playing';
    if (state === 'starting') this.heardFullClip = false;
    if (state === 'stopped' || state === 'failed') this.heardFullClip = false;
    if (state === 'completed') this.heardFullClip = true;
    this.elements.auditionStatus.textContent = state === 'playing' ? '正在试听原始音频…'
      : state === 'completed' ? '已从头到尾播放完成。请亲自判断原始声音是否适合私有保存。'
      : state === 'starting' ? '正在启动试听…' : state === 'stopped' ? '试听已停止；需完整试听后才能确认。'
      : state === 'failed' ? '试听未能完成；请重试或拒绝这段音频。' : '';
    this.render();
  }

  async refresh(): Promise<void> {
    if (this.closed || !this.started) return;
    const seq = ++this.statusSequence;
    this.statusAbort?.abort();
    const abort = new AbortController(); this.statusAbort = abort;
    try {
      const status = parseReviewedAudioStatus(await this.api.reviewedAudioStatus(abort.signal));
      if (this.closed || abort.signal.aborted || seq !== this.statusSequence) return;
      this.statusFresh = true;
      this.applyStatus(status);
      this.elements.status.textContent = status.recording_active
        ? `开发录制已开启 · ${this.inputFences.size > 0 ? '等待本轮输入处理结束后刷新审核状态' : status.has_pending_audio ? '有一段待审核音频' : '尚无待审核音频'}`
        : '开发录制已关闭。默认保持关闭。';
      this.elements.scope.textContent = status.scope_notice;
      if (!status.recording_active || !status.has_pending_audio || status.expires_in_seconds <= 0) {
        this.invalidateReview(true);
      } else if (this.reviewValue && (this.streamValue !== status.pending_stream_id
        || !status.pending_stream_id || this.reviewValue.kind !== status.pending_kind)) {
        this.invalidateReview(true);
      }
      this.render();
    } catch {
      if (this.closed || abort.signal.aborted || seq !== this.statusSequence) return;
      this.statusFresh = false;
      this.invalidateReview(true);
      this.elements.status.textContent = '当前会话状态暂不可用；审核与保存操作已停用。';
      this.elements.scope.textContent = this.statusValue?.scope_notice ?? '';
      this.elements.result.textContent = '无法确认审核缓冲仍属于当前会话。请刷新后重试。';
      this.render();
    } finally {
      if (this.statusAbort === abort) this.statusAbort = null;
      if (!this.closed) this.schedulePoll();
    }
  }

  private applyStatus(status: ReviewedAudioStatusResponse): void {
    const previous = this.statusValue;
    if (previous && previous.recording_active && status.recording_active
      && previous.pending_stream_id && status.pending_stream_id !== previous.pending_stream_id) {
      this.invalidateReview(true);
    }
    this.statusValue = status;
    if (status.recording_active && status.has_pending_audio && status.expires_in_seconds > 0) {
      const expiresAt = this.now() + status.expires_in_seconds * 1000;
      if (this.reviewValue && this.expiresAt > expiresAt + 1000) this.invalidateReview(true);
    }
  }

  private schedulePoll(): void {
    if (this.closed) return;
    if (this.pollTimer !== null) this.cancelLater(this.pollTimer);
    this.pollTimer = this.later(() => { this.pollTimer = null; void this.refresh(); }, 2000);
  }

  private async enable(): Promise<void> {
    if (this.closed || this.busy || !this.statusFresh || !this.canEnable || !this.elements.consent.checked) {
      this.elements.result.textContent = '请先阅读范围说明并勾选明确同意，再开启开发录制。';
      return;
    }
    this.invalidateReview(true);
    await this.setMode(true, true);
  }

  private async disable(): Promise<void> {
    if (this.closed || this.busy) return;
    this.invalidateReview(true);
    await this.setMode(false, false);
  }

  private async setMode(enabled: boolean, consent: boolean): Promise<void> {
    const generation = ++this.modeEpoch;
    this.busy = true; this.render();
    const abort = new AbortController(); this.modeAbort = abort;
    let refreshAfter = false;
    try {
      const result = await this.api.setReviewedAudioRecording(enabled, consent, abort.signal);
      if (this.closed || abort.signal.aborted || generation !== this.modeEpoch) return;
      if (!result.ok || result.recording_active !== enabled) {
        this.elements.result.textContent = '模式状态未能确认；请检查状态后再继续。';
      } else if (enabled) {
        this.elements.result.textContent = '已明确开启本地开发录制。原始音频仅在逐段审核并单独确认后才可排入私有存储队列。';
      } else {
        this.elements.consent.checked = false;
        this.elements.result.textContent = '已请求关闭开发录制；待审核原始缓冲已清除。';
      }
      refreshAfter = true;
    } catch {
      if (!this.closed && !abort.signal.aborted && generation === this.modeEpoch) {
        this.elements.result.textContent = '开发录制状态无法确认。请勿继续录音，并刷新查看状态。';
      }
    } finally {
      if (this.modeAbort === abort) this.modeAbort = null;
      if (!this.closed && generation === this.modeEpoch) {
        this.busy = false; this.render();
        if (refreshAfter) void this.refresh();
      }
    }
  }

  private async requestReview(): Promise<void> {
    const status = this.statusValue;
    if (this.closed || this.busy || !status?.recording_active || !status.has_pending_audio
      || !status.pending_stream_id || status.expires_in_seconds <= 0) return;
    this.invalidateReview(true);
    const generation = ++this.reviewEpoch, streamId = status.pending_stream_id;
    this.busy = true; this.render();
    const abort = new AbortController(); this.reviewAbort = abort;
    try {
      const review = await this.api.requestReviewedAudioReview(streamId, abort.signal);
      if (this.closed || abort.signal.aborted || generation !== this.reviewEpoch) return;
      if (!validReview(review) || review.kind !== status.pending_kind) throw new Error('Invalid reviewed audio ticket');
      if (this.statusValue?.pending_stream_id !== streamId) throw new Error('Reviewed audio owner changed');
      this.reviewValue = Object.freeze({...review}); this.streamValue = streamId;
      this.expiresAt = this.now() + review.expires_in_seconds * 1000;
      this.armExpiry(generation, review.expires_in_seconds);
      this.elements.clip.hidden = false;
      const seconds = review.byte_count / (review.sample_rate_hz * 2);
      const duration = seconds.toFixed(2);
      const kind = review.kind === 'audio_input' ? '麦克风输入' : '角色输出音频';
      this.elements.clipMetadata.textContent = `精确缓冲：${kind} · PCM16LE 单声道 · ${review.sample_rate_hz} Hz · ${duration} 秒 · ${review.byte_count} 字节 · SHA-256 ${review.digest}`;
      this.elements.result.textContent = '审核票据已建立。请加载并完整试听实际原始音频，再决定拒绝或私有保存。ASR 转写不能替代试听。';
    } catch {
      if (!this.closed && !abort.signal.aborted && generation === this.reviewEpoch) {
        this.clearReview(true);
        this.elements.result.textContent = '这段音频不存在、已过期或不属于当前会话；已清除本地审核操作。';
      }
    } finally {
      if (this.reviewAbort === abort) this.reviewAbort = null;
      if (!this.closed && generation === this.reviewEpoch) { this.busy = false; this.render(); }
    }
  }

  private async loadPreview(): Promise<void> {
    const review = this.reviewValue;
    if (this.closed || this.busy || !review || this.now() >= this.expiresAt) { this.expire(); return; }
    const generation = this.reviewEpoch;
    this.busy = true; this.render();
    const abort = new AbortController(); this.reviewAbort = abort;
    try {
      const preview = await this.api.reviewedAudioPreview(review, abort.signal);
      if (this.closed || abort.signal.aborted || generation !== this.reviewEpoch) { preview.pcm16le.fill(0); return; }
      if (preview.pcm16le.byteLength !== review.byte_count || preview.pcm16le.byteLength % 2 !== 0
        || preview.digest !== review.digest || preview.sampleRateHz !== review.sample_rate_hz
        || preview.kind !== review.kind || this.now() >= this.expiresAt) {
        preview.pcm16le.fill(0); throw new Error('Preview did not match reviewed buffer');
      }
      this.zeroPcm(); this.pcm = preview.pcm16le;
      this.heardFullClip = false;
      this.elements.auditionStatus.textContent = '原始音频已装入临时内存；点击“试听这段原音”开始，系统不会自动播放。';
      this.elements.result.textContent = '原始 PCM 与审核摘要匹配。请完整试听实际声音；自动语音转写无法发现所有口述秘密。';
    } catch {
      if (!this.closed && !abort.signal.aborted && generation === this.reviewEpoch) {
        this.clearPreview(true);
        this.elements.result.textContent = '无法读取与摘要一致的原始音频；这段缓冲不会进入保存确认。';
      }
    } finally {
      if (this.reviewAbort === abort) this.reviewAbort = null;
      if (!this.closed && generation === this.reviewEpoch) { this.busy = false; this.render(); }
    }
  }

  private async playPreview(): Promise<void> {
    const review = this.reviewValue, pcm = this.pcm;
    if (this.closed || this.busy || !review || !pcm || this.now() >= this.expiresAt) { this.expire(); return; }
    this.heardFullClip = false;
    const started = await this.audition.auditionReviewedAudio(pcm, review.sample_rate_hz);
    if (!started && !this.closed) {
      this.auditionState('failed');
      this.elements.result.textContent = '角色回应、麦克风或演示状态尚未静止。请等它们结束后，再试听这段原音。';
    }
  }

  private async confirmSave(): Promise<void> {
    const review = this.reviewValue;
    if (this.closed || this.busy || !review || !this.pcm || !this.heardFullClip
      || !this.elements.attestation.checked || this.now() >= this.expiresAt) {
      if (this.now() >= this.expiresAt) this.expire();
      else this.elements.result.textContent = '先加载并从头到尾试听原始音频，再勾选确认已实际听过且适合私有保存。';
      return;
    }
    this.clearAuditionOnly();
    const generation = ++this.reviewEpoch;
    this.busy = true; this.render();
    const abort = new AbortController(); this.reviewAbort = abort;
    let refreshAfter = false;
    try {
      const result = await this.api.confirmReviewedAudio(review, {
        reviewed_digest: review.digest, review: 'approved', persist_consent: true,
      }, abort.signal);
      if (this.closed || abort.signal.aborted || generation !== this.reviewEpoch) return;
      const queued = result.ok && result.accepted_for_queue === true && result.code === 'queued_private_local';
      this.clearReview(true);
      this.elements.result.textContent = queued
        ? '已排入本机私有诊断队列；这只确认队列接收，不证明已写入磁盘。原始导出仍需另一项独立同意。'
        : '私有保存未获队列接收；音频审核数据已清除。';
      refreshAfter = true;
    } catch {
      if (!this.closed && !abort.signal.aborted && generation === this.reviewEpoch) {
        this.clearReview(true);
        this.elements.result.textContent = '私有保存状态无法确认；本地审核数据已清除。请稍后检查诊断状态。';
      }
    } finally {
      if (this.reviewAbort === abort) this.reviewAbort = null;
      if (!this.closed && generation === this.reviewEpoch) {
        this.busy = false; this.render();
        if (refreshAfter) void this.refresh();
      }
    }
  }

  private async rejectAndClear(): Promise<void> {
    const review = this.reviewValue;
    if (!review || this.busy || this.closed) { this.clearReview(true); return; }
    const generation = ++this.reviewEpoch;
    this.clearAuditionOnly(); this.busy = true; this.render();
    const abort = new AbortController(); this.reviewAbort = abort;
    let refreshAfter = false;
    try {
      await this.api.confirmReviewedAudio(review, {
        reviewed_digest: review.digest, review: 'rejected', persist_consent: false,
      }, abort.signal);
      if (this.closed || abort.signal.aborted || generation !== this.reviewEpoch) return;
      this.clearReview(true);
      this.elements.result.textContent = '已拒绝并清除这段待审音频。';
      refreshAfter = true;
    } catch {
      if (!this.closed && !abort.signal.aborted && generation === this.reviewEpoch) {
        this.clearReview(true);
        this.elements.result.textContent = '拒绝确认未能送达；本地审核内容已清除，服务端缓冲会按短时有效期失效。';
      }
    } finally {
      if (this.reviewAbort === abort) this.reviewAbort = null;
      if (!this.closed && generation === this.reviewEpoch) {
        this.busy = false; this.render();
        if (refreshAfter) void this.refresh();
      }
    }
  }

  private armExpiry(generation: number, seconds: number): void {
    if (this.expiryTimer !== null) this.cancelLater(this.expiryTimer);
    this.expiryTimer = this.later(() => {
      this.expiryTimer = null;
      if (!this.closed && generation === this.reviewEpoch && this.now() >= this.expiresAt) this.expire();
    }, Math.max(0, seconds * 1000));
  }

  private expire(): void {
    if (this.closed) return;
    this.invalidateReview(true);
    if (this.statusValue) this.statusValue = Object.freeze({...this.statusValue,
      has_pending_audio: false, staged_bytes: 0, expires_in_seconds: 0, pending_stream_id: null, pending_kind: null});
    this.elements.result.textContent = '这段审核已过期；音频、摘要确认和操作按钮已清除。';
    this.render();
  }

  private clearAuditionOnly(): void {
    this.audition.stopReviewedAudioAudition();
    this.auditionActive = false; this.heardFullClip = false;
  }

  private clearPreview(stop = true): void {
    if (stop) this.clearAuditionOnly();
    this.zeroPcm();
    this.heardFullClip = false;
    this.elements.auditionStatus.textContent = '';
  }

  private clearReview(stop = true): void {
    if (this.expiryTimer !== null) this.cancelLater(this.expiryTimer);
    this.expiryTimer = null; this.expiresAt = 0;
    this.reviewValue = null; this.streamValue = null;
    this.clearPreview(stop);
    this.elements.clip.hidden = true;
    this.elements.clipMetadata.textContent = '';
    this.elements.attestation.checked = false;
  }

  private invalidateReview(stop = true): void {
    this.reviewEpoch++;
    this.reviewAbort?.abort(); this.reviewAbort = null;
    this.clearReview(stop);
  }

  private zeroPcm(): void {
    if (this.pcm) this.pcm.fill(0);
    this.pcm = null;
  }

  private render(): void {
    const status = this.statusValue;
    const active = status?.recording_active === true;
    const pending = this.statusFresh && this.inputFences.size === 0 && active && status?.has_pending_audio === true && status.expires_in_seconds > 0
      && Boolean(status.pending_stream_id && status.pending_kind);
    const ticket = this.statusFresh && this.reviewValue !== null && this.now() < this.expiresAt;
    const loaded = this.pcm !== null;
    this.elements.notice.hidden = !active;
    this.elements.notice.textContent = active
      ? `开发录制已开启。${status?.scope_notice ?? '范围暂无法确认，请勿继续录音。'} 原始音频需要对精确缓冲试听和审核；不会自动发现或抹除口述秘密。`
      : '';
    this.elements.disable.hidden = !active;
    this.elements.consent.disabled = this.continuousListeningBlocked || this.busy || active || !this.statusFresh || !this.canEnable;
    this.elements.enable.disabled = this.continuousListeningBlocked || this.busy || active || !this.statusFresh || !this.canEnable || !this.elements.consent.checked;
    this.elements.review.disabled = this.continuousListeningBlocked || this.busy || !pending || ticket;
    this.elements.review.hidden = !pending || ticket;
    this.elements.preview.disabled = this.continuousListeningBlocked || this.busy || !ticket || loaded;
    this.elements.preview.hidden = !ticket || loaded;
    this.elements.audition.disabled = this.continuousListeningBlocked || this.busy || !ticket || !loaded || this.auditionActive;
    this.elements.audition.hidden = !ticket || !loaded;
    this.elements.attestation.disabled = this.continuousListeningBlocked || this.busy || !ticket || !this.heardFullClip;
    this.elements.confirm.disabled = this.continuousListeningBlocked || this.busy || !ticket || !loaded || !this.heardFullClip || !this.elements.attestation.checked;
    this.elements.confirm.hidden = !ticket;
    this.elements.cancel.disabled = this.busy || !ticket;
    this.elements.cancel.hidden = !ticket;
  }

  close(): void {
    if (this.closed) return;
    const recordingActive = this.statusValue?.recording_active === true;
    this.closed = true; this.modeEpoch++; this.reviewEpoch++; this.statusSequence++;
    if (this.pollTimer !== null) this.cancelLater(this.pollTimer);
    this.pollTimer = null;
    this.statusAbort?.abort(); this.statusAbort = null;
    this.modeAbort?.abort(); this.modeAbort = null;
    this.reviewAbort?.abort(); this.reviewAbort = null;
    this.statusValue = null;
    this.inputFences.clear();
    this.clearReview(true);
    this.elements.notice.hidden = !recordingActive;
    this.elements.notice.textContent = recordingActive
      ? '本会话审核已关闭，待审音频和本地操作已清除；应用范围内的开发录制模式仍然开启。请在仍连接的会话中明确关闭。'
      : '';
    this.elements.review.hidden = true;
    this.elements.enable.disabled = true;
    this.elements.disable.hidden = true;
    this.elements.result.textContent = '';
  }
}
