import { initialSceneState, reduceSceneEffect } from './scene-state.js';
const PHASE_LABELS = {
    idle: '陪你听雨', listening: '正在认真听', thinking: '想一想…', speaking: '正在说话',
};
const EXPRESSION_LABELS = {
    calm: '平静', warm: '温暖微笑', curious: '好奇', reflective: '若有所思',
};
const ACTION_LABELS = {
    camera_ready: '手中拿着相机', camera_lowered: '放低了相机', look_at_rain: '转头看向窗外的雨',
};
const SCENE_LABELS = {
    cafe: '雨夜 · 窗边咖啡馆', rain_window: '雨窗 · 城市慢了下来', cafe_warm: '暖灯 · 留一会儿吧',
};
const DEFAULT_MEDIA_READINESS_TIMEOUT_MS = 5000;
const MAX_MEDIA_READINESS_TIMEOUT_MS = 30000;
const abortError = () => Object.assign(new Error('Media preparation cancelled'), { name: 'AbortError' });
/**
 * Synchronous visual consumer beneath the existing presentation gate.
 * CSS supplies animation; this class schedules nothing and never starts audio.
 * Real recording/playback owners call setPhase; subtitle delivery is not speech evidence.
 */
export class SceneEffectExecutor {
    root;
    state = initialSceneState();
    decodedImages = new WeakMap();
    mediaReadinessTimeoutMs;
    constructor(root, options = {}) {
        this.root = root;
        const timeout = options.mediaReadinessTimeoutMs ?? DEFAULT_MEDIA_READINESS_TIMEOUT_MS;
        if (!Number.isSafeInteger(timeout) || timeout < 1 || timeout > MAX_MEDIA_READINESS_TIMEOUT_MS) {
            throw new RangeError('Media readiness timeout must be between 1 and 30000 milliseconds');
        }
        this.mediaReadinessTimeoutMs = timeout;
        this.render();
    }
    element(name) {
        const target = this.root.querySelector(`[data-${name}]`);
        if (!target)
            throw new Error(`Missing scene slot: ${name}`);
        return target;
    }
    apply(effect) {
        const next = reduceSceneEffect(this.state, effect);
        this.state = next;
        this.render();
    }
    /**
     * Wait for the already-mounted local illustration without changing visible DOM state.
     * This establishes decoded-resource readiness only; it cannot establish browser paint or
     * that a person looked at the image. The controller revalidates its gate before apply().
     */
    async prepare(effect, signal) {
        if (effect.kind !== 'media' || (effect.value !== 'trip_photo' && effect.value !== 'trip_photo_placeholder'))
            return;
        if (signal.aborted)
            throw abortError();
        const image = this.root.querySelector('[data-photo] img');
        if (!image)
            throw new Error('Image resource unavailable');
        const deadline = new AbortController();
        let timedOut = false;
        const abortDeadline = () => deadline.abort();
        const timer = globalThis.setTimeout(() => { timedOut = true; deadline.abort(); }, this.mediaReadinessTimeoutMs);
        signal.addEventListener('abort', abortDeadline, { once: true });
        try {
            await this.waitForImageLoad(image, deadline.signal);
            await this.decodeImage(image, deadline.signal);
            if (signal.aborted)
                throw abortError();
            if (!this.imageIsReady(image))
                throw new Error('Image resource unavailable');
        }
        catch (error) {
            if (signal.aborted)
                throw abortError();
            if (timedOut)
                throw new Error('Image readiness timed out');
            throw error instanceof Error && error.name === 'AbortError' ? error : new Error('Image resource unavailable');
        }
        finally {
            globalThis.clearTimeout(timer);
            signal.removeEventListener('abort', abortDeadline);
        }
    }
    imageIsReady(image) {
        return image.complete && image.naturalWidth > 0;
    }
    waitForImageLoad(image, signal) {
        if (signal.aborted)
            return Promise.reject(abortError());
        if (image.complete)
            return this.imageIsReady(image) ? Promise.resolve() : Promise.reject(new Error('Image resource unavailable'));
        return new Promise((resolve, reject) => {
            let settled = false;
            const finish = (error) => {
                if (settled)
                    return;
                settled = true;
                image.removeEventListener('load', onLoad);
                image.removeEventListener('error', onError);
                signal.removeEventListener('abort', onAbort);
                if (error)
                    reject(error);
                else
                    resolve();
            };
            const onLoad = () => finish(this.imageIsReady(image) ? undefined : new Error('Image resource unavailable'));
            const onError = () => finish(new Error('Image resource unavailable'));
            const onAbort = () => finish(abortError());
            image.addEventListener('load', onLoad, { once: true });
            image.addEventListener('error', onError, { once: true });
            signal.addEventListener('abort', onAbort, { once: true });
            // Close the small race between the initial complete check and listener registration.
            if (image.complete)
                onLoad();
            if (signal.aborted)
                onAbort();
        });
    }
    decodeImage(image, signal) {
        if (signal.aborted)
            return Promise.reject(abortError());
        if (!this.imageIsReady(image))
            return Promise.reject(new Error('Image resource unavailable'));
        return new Promise((resolve, reject) => {
            let settled = false;
            const finish = (error) => {
                if (settled)
                    return;
                settled = true;
                signal.removeEventListener('abort', onAbort);
                if (error)
                    reject(error);
                else
                    resolve();
            };
            const onAbort = () => finish(abortError());
            signal.addEventListener('abort', onAbort, { once: true });
            this.decodeResource(image).then(() => {
                finish(this.imageIsReady(image) ? undefined : new Error('Image resource unavailable'));
            }, () => finish(new Error('Image resource unavailable')));
            if (signal.aborted)
                onAbort();
        });
    }
    decodeResource(image) {
        const existing = this.decodedImages.get(image);
        if (existing)
            return existing;
        let decoding;
        try {
            decoding = image.decode();
        }
        catch {
            decoding = Promise.reject(new Error('Image resource unavailable'));
        }
        this.decodedImages.set(image, decoding);
        // Keep an in-flight decode single-flight even if one waiter is canceled. A settled
        // rejection is retryable, but an older rejection must never evict a newer cached attempt.
        void decoding.catch(() => {
            if (this.decodedImages.get(image) === decoding)
                this.decodedImages.delete(image);
        });
        return decoding;
    }
    prepareInput() {
        this.state = { ...this.state, phase: 'thinking', subtitle: '' };
        this.render();
    }
    stop() {
        this.state = { ...this.state, phase: 'idle', subtitle: this.state.photoVisible ? '已停下。那张旅行插画还留在这里。' : '已停下。我们可以慢慢说。' };
        this.render();
    }
    setPhase(phase) {
        this.state = { ...this.state, phase };
        this.render();
    }
    setExpression(expression) {
        this.state = { ...this.state, expression };
        this.render();
    }
    render() {
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
//# sourceMappingURL=scene-executor.js.map