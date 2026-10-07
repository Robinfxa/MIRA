import { Application, Sprite, Texture } from 'pixi.js';
const imageAbortError = () => Object.assign(new Error('Image decoding cancelled'), { name: 'AbortError' });
function decodeImage(src, signal) {
    if (signal.aborted)
        return Promise.reject(imageAbortError());
    return new Promise((resolve, reject) => {
        const image = new Image();
        let settled = false;
        const timer = globalThis.setTimeout(() => finish(new Error('Image decoding timed out')), 7000);
        const finish = (error) => {
            if (settled)
                return;
            settled = true;
            globalThis.clearTimeout(timer);
            signal.removeEventListener('abort', onAbort);
            if (error) {
                image.src = '';
                reject(error);
            }
            else
                resolve(image);
        };
        const onAbort = () => finish(imageAbortError());
        signal.addEventListener('abort', onAbort, { once: true });
        image.decoding = 'async';
        image.onload = () => finish(image.naturalWidth > 0 && image.naturalHeight > 0 ? undefined : new Error('Image is invalid'));
        image.onerror = () => finish(new Error('Image is unavailable'));
        image.src = src;
        if (typeof image.decode === 'function') {
            void image.decode().then(() => finish(image.naturalWidth > 0 && image.naturalHeight > 0 ? undefined : new Error('Image is invalid')), () => finish(new Error('Image is unavailable')));
        }
        if (signal.aborted)
            onAbort();
    });
}
export function loadPixiRuntime() {
    return {
        createApplication: () => new Application(),
        async loadTexture(src, signal) {
            const image = await decodeImage(src, signal);
            if (signal.aborted)
                throw imageAbortError();
            return Texture.from(image);
        },
        createSprite(texture) { return new Sprite(texture); },
        destroyTexture(texture) { texture.destroy(true); },
    };
}
