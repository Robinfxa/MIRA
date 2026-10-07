import { chooseCharacterFrame, fitCharacterFrame, parseCharacterManifest } from './pixi-character-contract.js';
const DEFAULT_MANIFEST_URL = '/assets/scene/mira_manifest.json';
const ASSET_ROOT = '/assets/scene/';
const TEXTURE_TIMEOUT_MS = 7000;
const abortError = () => Object.assign(new Error('Character asset preparation cancelled'), { name: 'AbortError' });
const safeError = () => new Error('Character renderer unavailable');
function withAbort(promise, signal, timeoutMs = TEXTURE_TIMEOUT_MS) {
    if (signal.aborted)
        return Promise.reject(abortError());
    return new Promise((resolve, reject) => {
        let settled = false;
        const finish = (error, value) => {
            if (settled)
                return;
            settled = true;
            globalThis.clearTimeout(timer);
            signal.removeEventListener('abort', onAbort);
            if (error)
                reject(error);
            else
                resolve(value);
        };
        const onAbort = () => finish(abortError());
        const timer = globalThis.setTimeout(() => finish(new Error('Character asset timed out')), timeoutMs);
        signal.addEventListener('abort', onAbort, { once: true });
        promise.then(value => finish(undefined, value), () => finish(safeError()));
        if (signal.aborted)
            onAbort();
    });
}
async function fetchLocalManifest(url, signal) {
    const parsed = new URL(url, globalThis.location?.origin ?? 'http://127.0.0.1');
    if (parsed.origin !== (globalThis.location?.origin ?? parsed.origin) || parsed.pathname !== url
        || !parsed.pathname.startsWith('/assets/scene/'))
        throw safeError();
    const response = await fetch(parsed.href, {
        method: 'GET', mode: 'same-origin', credentials: 'same-origin', redirect: 'error', signal,
    });
    if (!response.ok)
        throw safeError();
    return response.json();
}
function combineSignals(signal, closing) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal.addEventListener('abort', abort, { once: true });
    closing.addEventListener('abort', abort, { once: true });
    if (signal.aborted || closing.aborted)
        controller.abort();
    return { signal: controller.signal, remove: () => {
            signal.removeEventListener('abort', abort);
            closing.removeEventListener('abort', abort);
        } };
}
function assertTexture(texture, asset) {
    if (!Number.isFinite(texture.width) || !Number.isFinite(texture.height)
        || texture.width !== asset.pixelSize.width || texture.height !== asset.pixelSize.height)
        throw safeError();
}
class PixiCharacterSurface {
    host;
    svg;
    manifest;
    runtime;
    app;
    sprite;
    closing = new AbortController();
    onContextLost = (event) => {
        event.preventDefault();
        this.destroy();
    };
    active;
    staged = null;
    canvasMounted = false;
    destroyed = false;
    previousSvgVisibility;
    unloadFence = Promise.resolve();
    constructor(host, svg, manifest, runtime, app, sprite, base) {
        this.host = host;
        this.svg = svg;
        this.manifest = manifest;
        this.runtime = runtime;
        this.app = app;
        this.sprite = sprite;
        this.active = { asset: manifest.base, texture: base };
        this.previousSvgVisibility = svg?.style.visibility ?? '';
        const canvas = app.canvas;
        canvas.className = 'mira-pixi-canvas';
        canvas.setAttribute('aria-hidden', 'true');
        canvas.setAttribute('role', 'presentation');
        canvas.tabIndex = -1;
        Object.assign(canvas.style, {
            position: 'absolute', inset: '0', display: 'block', width: '100%', height: '100%',
            pointerEvents: 'none', background: 'transparent',
        });
        canvas.addEventListener('webglcontextlost', this.onContextLost, { once: true });
    }
    async prepareState(state, signal) {
        if (this.destroyed || signal.aborted)
            throw abortError();
        const target = chooseCharacterFrame(this.manifest, state);
        if (!target)
            return false;
        if (target.src === this.active?.asset.src || target.src === this.staged?.asset.src)
            return true;
        await this.unloadFence;
        if (signal.aborted || this.destroyed)
            throw abortError();
        if (this.staged) {
            const oldStaged = this.staged;
            this.staged = null;
            await this.runtime.destroyTexture(oldStaged.texture);
        }
        const combined = combineSignals(signal, this.closing.signal);
        let loaded = null;
        try {
            loaded = await this.runtime.loadTexture(`${ASSET_ROOT}${target.src}`, combined.signal);
            assertTexture(loaded, target);
            if (combined.signal.aborted || this.destroyed) {
                await this.runtime.destroyTexture(loaded);
                loaded = null;
                throw abortError();
            }
            this.staged = { asset: target, texture: loaded };
            loaded = null;
            return true;
        }
        finally {
            combined.remove();
            if (loaded)
                await this.runtime.destroyTexture(loaded);
        }
    }
    render(state) {
        if (this.destroyed)
            return;
        const target = chooseCharacterFrame(this.manifest, state);
        const texture = this.active && target?.src === this.active.asset.src ? this.active.texture
            : target && this.staged && target.src === this.staged.asset.src ? this.staged.texture : null;
        if (!target || !texture) {
            this.showSvg();
            if (this.active) {
                const previous = this.active;
                this.active = null;
                this.scheduleTextureRelease(previous.texture);
            }
            if (this.staged) {
                const staged = this.staged;
                this.staged = null;
                this.scheduleTextureRelease(staged.texture);
            }
            return;
        }
        const previous = this.active;
        if (target.src !== this.active?.asset.src) {
            this.active = { asset: target, texture };
            if (this.staged?.asset.src === target.src)
                this.staged = null;
        }
        this.setSpriteLayout(target);
        this.sprite.texture = texture;
        this.app.renderer.render({ container: this.app.stage });
        this.showPixi();
        if (previous && previous.asset.src !== target.src) {
            this.scheduleTextureRelease(previous.texture);
        }
        if (this.staged && this.staged.asset.src !== target.src) {
            const staged = this.staged;
            this.staged = null;
            this.scheduleTextureRelease(staged.texture);
        }
    }
    setSpriteLayout(asset) {
        const layout = fitCharacterFrame(asset, this.manifest);
        this.sprite.x = layout.x;
        this.sprite.y = layout.y;
        this.sprite.width = layout.width;
        this.sprite.height = layout.height;
    }
    showPixi() {
        if (this.destroyed)
            return;
        if (!this.canvasMounted) {
            this.host.appendChild(this.app.canvas);
            this.canvasMounted = true;
        }
        this.app.canvas.style.display = 'block';
        if (this.svg)
            this.svg.style.visibility = 'hidden';
        this.host.dataset['renderer'] = 'pixi';
    }
    showSvg() {
        delete this.host.dataset['renderer'];
        if (this.canvasMounted)
            this.app.canvas.style.display = 'none';
        if (this.svg)
            this.svg.style.visibility = this.previousSvgVisibility;
    }
    scheduleTextureRelease(texture) {
        if (texture === this.active?.texture || texture === this.staged?.texture)
            return;
        this.unloadFence = this.unloadFence.then(async () => { await this.runtime.destroyTexture(texture); }).catch(() => undefined);
    }
    destroy() {
        if (this.destroyed)
            return;
        this.destroyed = true;
        this.closing.abort();
        this.app.canvas.removeEventListener('webglcontextlost', this.onContextLost);
        this.app.canvas.style.display = 'none';
        this.app.canvas.remove();
        delete this.host.dataset['renderer'];
        if (this.svg)
            this.svg.style.visibility = this.previousSvgVisibility;
        const textures = new Set();
        if (this.active)
            textures.add(this.active.texture);
        if (this.staged)
            textures.add(this.staged.texture);
        this.staged = null;
        for (const texture of textures) {
            try {
                void Promise.resolve(this.runtime.destroyTexture(texture)).catch(() => undefined);
            }
            catch { /* canvas removal and app teardown still proceed */ }
        }
        try {
            this.app.destroy();
        }
        catch { /* texture ownership was already released */ }
    }
}
export async function createPixiCharacterRenderer(host, options = {}) {
    if (options.signal?.aborted)
        return null;
    const ownAbort = new AbortController();
    const signal = options.signal ?? ownAbort.signal;
    let app = null;
    let runtime = null;
    let baseTexture = null;
    try {
        const fetchManifest = options.fetchManifest ?? fetchLocalManifest;
        const manifest = parseCharacterManifest(await withAbort(fetchManifest(options.manifestUrl ?? DEFAULT_MANIFEST_URL, signal), signal));
        if (signal.aborted)
            throw abortError();
        const loadRuntime = options.loadRuntime ?? (async () => (await import('./pixi-runtime.js')).loadPixiRuntime());
        runtime = await loadRuntime();
        if (signal.aborted)
            throw abortError();
        app = runtime.createApplication();
        const devicePixelRatio = options.devicePixelRatio?.() ?? globalThis.devicePixelRatio ?? 1;
        const resolution = Math.min(2, Math.max(1, Number.isFinite(devicePixelRatio) ? devicePixelRatio : 1));
        await app.init({ width: manifest.logicalSize.width, height: manifest.logicalSize.height, resolution,
            autoDensity: true, backgroundAlpha: 0, autoStart: false, sharedTicker: false,
            preference: 'webgl', powerPreference: 'low-power', antialias: true });
        app.ticker.stop();
        if (signal.aborted)
            throw abortError();
        baseTexture = await runtime.loadTexture(`${ASSET_ROOT}${manifest.base.src}`, signal);
        assertTexture(baseTexture, manifest.base);
        if (signal.aborted)
            throw abortError();
        const sprite = runtime.createSprite(baseTexture);
        app.stage.addChild(sprite);
        const svg = host.querySelector('svg');
        return new PixiCharacterSurface(host, svg, manifest, runtime, app, sprite, baseTexture);
    }
    catch {
        if (baseTexture && runtime) {
            try {
                await runtime.destroyTexture(baseTexture);
            }
            catch { /* fall through to the SVG */ }
        }
        if (app) {
            try {
                app.destroy();
            }
            catch { /* fallback remains mounted */ }
        }
        return null;
    }
}
