import { generatedPhotoIdentity } from '../../shared/photo-value.js';
export const MAX_GENERATED_IMAGE_BYTES = 8 * 1024 * 1024;
export const GENERATED_IMAGE_LABEL = '剧情生成图 · 虚构画面';
export const GENERATED_IMAGE_DESCRIPTION = '根据已开放的虚构剧情生成的插画。';
const unavailable = () => new Error('Generated illustration unavailable');
const aborted = () => Object.assign(new Error('Generated illustration cancelled'), { name: 'AbortError' });
/** Cancel locally even if an injected transport or browser decode ignores cancellation. */
export function awaitImageOperation(operation, signal, late) {
    return new Promise((resolve, reject) => {
        let settled = false;
        const onAbort = () => {
            if (settled)
                return;
            settled = true;
            signal.removeEventListener('abort', onAbort);
            reject(aborted());
        };
        signal.addEventListener('abort', onAbort, { once: true });
        operation.then(value => {
            if (settled) {
                late?.(value);
                return;
            }
            settled = true;
            signal.removeEventListener('abort', onAbort);
            resolve(value);
        }, () => {
            if (settled)
                return;
            settled = true;
            signal.removeEventListener('abort', onAbort);
            reject(unavailable());
        });
        if (signal.aborted)
            onAbort();
    });
}
/** Reads only bounded same-origin canonical PNG responses. No error bodies enter the UI. */
export async function readGeneratedImageResponse(response, signal) {
    const cancelBody = () => { void response.body?.cancel().catch(() => { }); };
    const length = response.headers.get('content-length');
    if (signal.aborted || !response.ok || response.redirected
        || response.headers.get('content-type')?.trim().toLowerCase() !== 'image/png'
        || !response.headers.get('cache-control')?.toLowerCase().split(',').some(value => value.trim() === 'no-store')
        || (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_GENERATED_IMAGE_BYTES))) {
        cancelBody();
        throw signal.aborted ? aborted() : unavailable();
    }
    const reader = response.body?.getReader();
    if (!reader)
        throw unavailable();
    const bytes = new Uint8Array(length === null ? MAX_GENERATED_IMAGE_BYTES : Number(length));
    let total = 0;
    let chunks = 0;
    const cancel = () => { void reader.cancel().catch(() => { }); };
    signal.addEventListener('abort', cancel, { once: true });
    try {
        while (true) {
            const item = await awaitImageOperation(reader.read(), signal);
            if (item.done)
                break;
            if (!(item.value instanceof Uint8Array) || item.value.byteLength === 0 || ++chunks > 16384
                || total + item.value.byteLength > bytes.byteLength)
                throw unavailable();
            bytes.set(item.value, total);
            total += item.value.byteLength;
        }
        if (signal.aborted || total < 33 || (length !== null && Number(length) !== total))
            throw unavailable();
        return bytes.slice(0, total);
    }
    catch (error) {
        cancel();
        throw error;
    }
    finally {
        signal.removeEventListener('abort', cancel);
        reader.releaseLock();
    }
}
/** One preparation's bytes, decode and blob lifetime. Authority remains in PresentationGate. */
export async function prepareGeneratedImage(effect, signal, primitives) {
    const boundEffect = Object.freeze({ ...effect });
    const identity = boundEffect.kind === 'media' ? generatedPhotoIdentity(boundEffect.value) : null;
    if (!identity)
        throw unavailable();
    const timeoutMs = primitives.timeoutMs ?? 5000;
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 30000)
        throw new RangeError('Invalid image readiness deadline');
    const deadline = new AbortController();
    const combined = AbortSignal.any([signal, deadline.signal]);
    const timer = setTimeout(() => deadline.abort(), timeoutMs);
    let url = null;
    let image = null;
    let disposed = false;
    const revoke = primitives.revokeObjectURL ?? (value => URL.revokeObjectURL(value));
    const dispose = () => {
        if (disposed)
            return;
        disposed = true;
        signal.removeEventListener('abort', dispose);
        image?.removeAttribute('src');
        if (url !== null) {
            revoke(url);
            url = null;
        }
    };
    try {
        if (combined.aborted)
            throw aborted();
        const received = await awaitImageOperation(primitives.fetchBytes(boundEffect, combined), combined);
        if (!(received instanceof Uint8Array) || received.byteLength < 33 || received.byteLength > MAX_GENERATED_IMAGE_BYTES)
            throw unavailable();
        const bytes = received.slice();
        const header = new DataView(bytes.buffer);
        const width = header.getUint32(16), height = header.getUint32(20);
        if ([137, 80, 78, 71, 13, 10, 26, 10].some((value, index) => bytes[index] !== value)
            || header.getUint32(8) !== 13 || header.getUint32(12) !== 0x49484452
            || !((width === 1024 && (height === 1024 || height === 1536))
                || (width === 1536 && height === 1024)))
            throw unavailable();
        const digestBytes = await awaitImageOperation(crypto.subtle.digest('SHA-256', bytes.buffer), combined);
        const digest = Array.from(new Uint8Array(digestBytes), value => value.toString(16).padStart(2, '0')).join('');
        if (digest !== identity.contentDigest || combined.aborted)
            throw unavailable();
        url = (primitives.createObjectURL ?? (blob => URL.createObjectURL(blob)))(new Blob([bytes.buffer], { type: 'image/png' }));
        image = (primitives.createImage ?? (() => new Image()))();
        image.alt = `${GENERATED_IMAGE_LABEL}。${GENERATED_IMAGE_DESCRIPTION}`;
        image.width = width;
        image.height = height;
        image.src = url;
        await awaitImageOperation(image.decode(), combined);
        if (combined.aborted || !image.complete || image.naturalWidth !== width || image.naturalHeight !== height)
            throw unavailable();
        signal.addEventListener('abort', dispose, { once: true });
        if (signal.aborted) {
            dispose();
            throw aborted();
        }
        return Object.freeze({ effect: boundEffect, image,
            commit: () => { if (disposed || signal.aborted)
                throw aborted(); signal.removeEventListener('abort', dispose); }, dispose });
    }
    catch {
        dispose();
        throw signal.aborted ? aborted() : unavailable();
    }
    finally {
        clearTimeout(timer);
    }
}
