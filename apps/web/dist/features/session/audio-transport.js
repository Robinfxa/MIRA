import { safeHttpError, safeSessionError } from '../diagnostics/status.js';
function record(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw))
        throw new Error('Invalid voice packet');
    return raw;
}
function parsePacket(text) {
    try {
        return record(JSON.parse(text));
    }
    catch {
        throw new Error('Invalid voice packet. Text input is still available.');
    }
}
function count(value) { return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0; }
function pcmBytes(encoded) {
    if (typeof encoded !== 'string' || encoded.length === 0 || encoded.length > 16000
        || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded))
        throw new Error('Invalid PCM packet');
    const decoded = atob(encoded);
    if (decoded.startsWith('RIFF') && decoded.slice(8, 12) === 'WAVE')
        throw new Error('WAV containers are not raw PCM');
    if (decoded.length === 0 || decoded.length > 12000 || decoded.length % 2 !== 0 || btoa(decoded) !== encoded)
        throw new Error('Invalid PCM packet');
    return Uint8Array.from(decoded, value => value.charCodeAt(0));
}
function encode(bytes) {
    let text = '';
    for (const value of bytes)
        text += String.fromCharCode(value);
    return btoa(text);
}
function cancelled() { return new Error('Voice operation cancelled'); }
/** Bounded browser transports. The sink remains the only audio playback owner. */
export class BrowserAudioTransport {
    config;
    credentials;
    primitives;
    closed = false;
    requests = new Set();
    microphones = new Set();
    constructor(config, credentials, primitives = {}) {
        this.config = config;
        this.credentials = credentials;
        this.primitives = primitives;
    }
    async speech(effect, signal, onPcm) {
        if (this.closed || signal.aborted)
            throw cancelled();
        if (effect.kind !== 'speech')
            throw new Error('Speech requires an explicit speech grant');
        const credentials = this.credentials();
        const abort = new AbortController();
        this.requests.add(abort);
        const combined = AbortSignal.any([signal, abort.signal]);
        const timeout = setTimeout(() => abort.abort(), 330000);
        let reader;
        const cancelReader = () => { void reader?.cancel().catch(() => { }); };
        combined.addEventListener('abort', cancelReader, { once: true });
        try {
            const response = await (this.primitives.fetch ?? globalThis.fetch)(`${this.config.apiBase}/sessions/${encodeURIComponent(credentials.sessionId)}/speech/${encodeURIComponent(effect.id)}/stream`, {
                method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Mira-Session-Token': credentials.token },
                body: JSON.stringify({ digest: effect.digest, output_epoch: effect.output_epoch, activity_seq: effect.activity_seq }),
                signal: combined, cache: 'no-store', redirect: 'error',
            });
            if (combined.aborted || this.closed)
                throw cancelled();
            if (response.body)
                reader = response.body.getReader();
            if (!response.ok)
                throw new Error(safeHttpError(response.status, response.headers.get('x-request-id')));
            if (!response.headers.get('content-type')?.startsWith('application/x-ndjson') || !response.body) {
                throw new Error('Speech transport unavailable. Text input is still available.');
            }
            if (!reader)
                throw new Error('Speech response has no body');
            const decoder = new TextDecoder('utf-8', { fatal: true });
            let pending = '', sequence = 1, samples = 0, complete = false;
            while (true) {
                const part = await reader.read();
                if (combined.aborted || this.closed)
                    throw cancelled();
                if (part.done)
                    break;
                if (part.value.byteLength > 262144)
                    throw new Error('Speech transport chunk exceeded its bound');
                pending += decoder.decode(part.value, { stream: true });
                let newline;
                while ((newline = pending.indexOf('\n')) !== -1) {
                    if (newline > 20000 || complete)
                        throw new Error('Invalid speech stream terminal or line bound');
                    const line = pending.slice(0, newline);
                    pending = pending.slice(newline + 1);
                    const packet = parsePacket(line);
                    if (packet['effect_id'] !== effect.id || packet['stream_id'] !== effect.id || packet['digest'] !== effect.digest
                        || packet['activity_seq'] !== effect.activity_seq || packet['output_epoch'] !== effect.output_epoch)
                        throw new Error('Speech origin mismatch');
                    if (packet['type'] === 'audio') {
                        if (packet['sequence'] !== sequence || packet['first_sample'] !== samples || packet['sample_rate_hz'] !== 24000)
                            throw new Error('Discontinuous or unsupported speech audio');
                        const bytes = pcmBytes(packet['pcm_base64']);
                        samples += bytes.length / 2;
                        if (samples > 24000 * 300)
                            throw new Error('Speech duration exceeded its bound');
                        const pcm = new Int16Array(bytes.length / 2), data = new DataView(bytes.buffer);
                        for (let i = 0; i < pcm.length; i++)
                            pcm[i] = data.getInt16(i * 2, true);
                        await onPcm(pcm); // Backpressure is owned by the single bounded sink coordinator.
                        if (combined.aborted || this.closed)
                            throw cancelled();
                        sequence++;
                    }
                    else if (packet['type'] === 'complete') {
                        if (samples === 0 || packet['total_samples'] !== samples)
                            throw new Error('Speech completion did not match received audio');
                        complete = true;
                    }
                    else if (packet['type'] === 'error') {
                        throw new Error(safeSessionError(packet['code'], Object.hasOwn(packet, 'diagnostic_id') ? packet['diagnostic_id'] : null));
                    }
                    else
                        throw new Error('Unknown speech packet');
                }
                if (pending.length > 20000)
                    throw new Error('Speech line exceeded its bound');
            }
            pending += decoder.decode();
            if (pending.length !== 0 || !complete)
                throw new Error('Speech stream ended without verified completion');
        }
        finally {
            clearTimeout(timeout);
            combined.removeEventListener('abort', cancelReader);
            cancelReader();
            abort.abort();
            this.requests.delete(abort);
        }
    }
    microphone(origin, signal) {
        if (this.closed || signal.aborted)
            throw cancelled();
        const credentials = this.credentials();
        const setTimer = this.primitives.setTimeout ?? globalThis.setTimeout;
        const clearTimer = this.primitives.clearTimeout ?? globalThis.clearTimeout;
        const now = this.primitives.now ?? (() => performance.now());
        const url = new URL(`${this.config.apiBase}/sessions/${encodeURIComponent(credentials.sessionId)}/microphone`, this.primitives.baseUrl ?? globalThis.location.href);
        if (url.protocol !== 'https:' && url.protocol !== 'http:')
            throw new Error('Invalid microphone endpoint');
        url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
        const socket = (this.primitives.createSocket ?? (address => new WebSocket(address)))(url.href);
        let alive = true, opened = false, authenticated = false, sealed = false, finishSent = false;
        let nextSequence = 0, samples = 0, queuedBytes = 0, revision = 0;
        const queue = [];
        let readyAt = 0, nextSendAt = 0, sentSamples = 0;
        let drainTimer = null;
        let finishTimer = null;
        let resolveReady, rejectReady;
        let resolveFinal, rejectFinal;
        const ready = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
        const final = new Promise((resolve, reject) => { resolveFinal = resolve; rejectFinal = reject; });
        // Consumers may cancel before they reach their await; still expose the same rejecting promises.
        void ready.catch(() => { });
        void final.catch(() => { });
        const authTimer = setTimer(() => fail(new Error('Microphone connection timed out. Use text input.')), 10000);
        const lifetimeTimer = setTimer(() => fail(new Error('Microphone session exceeded its time limit. Use text input.')), 90000);
        const cleanup = () => {
            if (!alive)
                return;
            alive = false;
            clearTimer(authTimer);
            clearTimer(lifetimeTimer);
            if (drainTimer !== null)
                clearTimer(drainTimer);
            if (finishTimer !== null)
                clearTimer(finishTimer);
            queue.length = 0;
            queuedBytes = 0;
            signal.removeEventListener('abort', onAbort);
            socket.onopen = null;
            socket.onmessage = null;
            socket.onerror = null;
            socket.onclose = null;
            try {
                socket.close();
            }
            catch { /* All local state is already invalidated. */ }
            this.microphones.delete(stream);
        };
        const fail = (error) => {
            if (!alive)
                return;
            cleanup();
            rejectReady(error);
            rejectFinal(error);
        };
        const drain = () => {
            if (!alive || !authenticated)
                return;
            if (signal.aborted || this.closed) {
                stream.cancel();
                return;
            }
            if (drainTimer !== null) {
                clearTimer(drainTimer);
                drainTimer = null;
            }
            try {
                const clock = now();
                const head = queue[0];
                const leadReadyAt = head ? readyAt + Math.max(0, (sentSamples + head.frames - 1920) / 16) : clock;
                // Pace against send-start monotonic time, never against old capture timestamps.
                // One chunk per duration avoids turning a delayed stop/handshake into a burst.
                if (head && socket.bufferedAmount === 0 && clock >= Math.max(nextSendAt, leadReadyAt)) {
                    queue.shift();
                    queuedBytes -= head.text.length;
                    socket.send(head.text);
                    sentSamples += head.frames;
                    nextSendAt = clock + head.frames / 16;
                }
                if (sealed && queue.length === 0 && socket.bufferedAmount === 0 && !finishSent) {
                    finishSent = true;
                    socket.send(JSON.stringify({ type: 'finish' }));
                    finishTimer = setTimer(() => fail(new Error('Final transcript timed out. Use text input.')), 15000);
                }
                if (queue.length || (sealed && !finishSent)) {
                    const next = queue[0];
                    const leadAt = next ? readyAt + Math.max(0, (sentSamples + next.frames - 1920) / 16) : clock;
                    const delay = socket.bufferedAmount > 0 ? 10 : Math.max(1, Math.ceil(Math.max(nextSendAt, leadAt) - now()));
                    drainTimer = setTimer(drain, delay);
                }
            }
            catch {
                fail(new Error('Microphone transport failed. Use text input.'));
            }
        };
        const onAbort = () => stream.cancel();
        const stream = {
            ready, completion: final,
            send: (chunk) => {
                if (!alive || sealed)
                    throw cancelled();
                if (!(chunk.pcm16le instanceof Uint8Array) || chunk.pcm16le.length === 0 || chunk.pcm16le.length > 12000
                    || chunk.pcm16le.length % 2 !== 0 || chunk.sampleRate !== 16000 || chunk.channels !== 1
                    || chunk.sequence !== nextSequence || chunk.startSample !== samples
                    || chunk.endSample !== samples + chunk.pcm16le.length / 2 || chunk.endSample > 16000 * 60) {
                    const error = new Error('Invalid or overlong microphone audio');
                    fail(error);
                    throw error;
                }
                const packet = JSON.stringify({ type: 'audio', sequence: nextSequence + 1, first_sample: samples, pcm_base64: encode(chunk.pcm16le) });
                if (queuedBytes + packet.length > 65536 || queue.length >= 100) {
                    const error = new Error('Microphone queue overflow. Use text input.');
                    fail(error);
                    throw error;
                }
                queue.push({ text: packet, frames: chunk.pcm16le.length / 2 });
                queuedBytes += packet.length;
                nextSequence++;
                samples = chunk.endSample;
                drain();
            },
            finish: () => { if (alive) {
                sealed = true;
                drain();
            } return final; },
            cancel: () => {
                if (!alive)
                    return;
                if (opened && socket.readyState === 1) {
                    try {
                        socket.send(JSON.stringify({ type: 'cancel' }));
                    }
                    catch { /* Closing next. */ }
                }
                fail(cancelled());
            },
        };
        this.microphones.add(stream);
        signal.addEventListener('abort', onAbort, { once: true });
        socket.onopen = () => {
            if (!alive || signal.aborted)
                return;
            opened = true;
            try {
                socket.send(JSON.stringify({ type: 'start', session_token: credentials.token, ...origin, sample_rate_hz: 16000 }));
            }
            catch {
                fail(new Error('Microphone authentication transport failed'));
            }
        };
        socket.onmessage = event => {
            if (!alive || signal.aborted)
                return;
            try {
                if (typeof event.data !== 'string' || event.data.length > 20000)
                    throw new Error('Invalid microphone response');
                const packet = record(JSON.parse(event.data));
                if (packet['type'] === 'error') {
                    fail(new Error(safeSessionError(packet['code'], Object.hasOwn(packet, 'diagnostic_id') ? packet['diagnostic_id'] : null)));
                    return;
                }
                if (packet['stream_id'] !== origin.stream_id)
                    throw new Error('Microphone response origin mismatch');
                if (packet['type'] === 'ready') {
                    if (!opened || authenticated || packet['activity_seq'] !== origin.activity_seq || packet['input_epoch'] !== origin.input_epoch)
                        throw new Error('Invalid microphone readiness');
                    authenticated = true;
                    readyAt = now();
                    nextSendAt = readyAt;
                    clearTimer(authTimer);
                    resolveReady();
                    drain();
                }
                else if (packet['type'] === 'transcript' || packet['type'] === 'complete') {
                    if (!authenticated || !count(packet['revision']) || packet['revision'] < revision
                        || typeof packet['text'] !== 'string' || packet['text'].length > 16000)
                        throw new Error('Invalid transcript');
                    revision = packet['revision'];
                    if (packet['type'] === 'transcript') {
                        if (typeof packet['is_final'] !== 'boolean')
                            throw new Error('Invalid transcript finality');
                        // Interim text is deliberately not a causal user input.
                    }
                    else {
                        if (!finishSent || typeof packet['had_final'] !== 'boolean' || (!packet['had_final'] && packet['text'] !== ''))
                            throw new Error('Unreliable transcript completion');
                        const result = { text: packet['text'], had_final: packet['had_final'] };
                        cleanup();
                        resolveFinal(result);
                    }
                }
                else
                    throw new Error('Unknown microphone packet');
            }
            catch {
                fail(new Error('Microphone response failed validation. Use text input.'));
            }
        };
        socket.onerror = () => fail(new Error('Microphone connection failed. Use text input.'));
        socket.onclose = () => fail(new Error('Microphone disconnected before final transcript. Use text input.'));
        if (signal.aborted)
            stream.cancel();
        return stream;
    }
    close() {
        if (this.closed)
            return;
        this.closed = true;
        for (const request of this.requests)
            request.abort();
        this.requests.clear();
        for (const microphone of this.microphones)
            microphone.cancel();
        this.microphones.clear();
    }
}
//# sourceMappingURL=audio-transport.js.map