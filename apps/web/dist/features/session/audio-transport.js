import { MiraTransportError, classifyTransportFailure } from './transport-errors.js';
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
function localLimit(value, maximum) {
    return value === null || (count(value) && value >= 1 && value <= maximum);
}
function isUuid(value) {
    return typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}
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
const LISTENING_STOP_REASONS = new Set([
    'user_stop', 'permission_lost', 'replaced', 'max_duration', 'max_samples', 'queue_limit',
    'revision_limit', 'utterance_limit', 'provider_stream_ended', 'unavailable', 'invalid_input',
    'invalid_response', 'session_closed', 'disconnect', 'output_limit', 'session_capacity',
    'microphone_unavailable', 'input_limit', 'invalid_audio', 'timeout', 'unauthenticated',
    'permission_denied', 'quota_exhausted', 'media_cancelled', 'incomplete_stream', 'blocked',
    'response_limit', 'service_budget_exhausted',
]);
const SPEECH_DECODE_WINDOW_BYTES = 16_384;
/** Bounded browser transports. The sink remains the only audio playback owner. */
export class BrowserAudioTransport {
    config;
    credentials;
    primitives;
    closed = false;
    requests = new Set();
    microphones = new Set();
    continuousStreams = new Set();
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
        const timeoutError = new MiraTransportError('request_timeout', 330000);
        const timeout = setTimeout(() => abort.abort(timeoutError), 330000);
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
                // Fetch read boundaries are arbitrary: one read may contain many valid
                // audio frames. Bound decoded/parser state, not the browser's read size.
                for (let offset = 0; offset < part.value.byteLength;) {
                    if (combined.aborted || this.closed)
                        throw cancelled();
                    const size = Math.min(SPEECH_DECODE_WINDOW_BYTES, part.value.byteLength - offset);
                    pending += decoder.decode(part.value.subarray(offset, offset + size), { stream: true });
                    offset += size;
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
            }
            pending += decoder.decode();
            if (pending.length !== 0 || !complete)
                throw new Error('Speech stream ended without verified completion');
        }
        catch (error) {
            throw classifyTransportFailure(error, combined, timeoutError, this.closed);
        }
        finally {
            clearTimeout(timeout);
            combined.removeEventListener('abort', cancelReader);
            cancelReader();
            abort.abort();
            this.requests.delete(abort);
        }
    }
    microphone(origin, signal, observers = {}) {
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
        const nowAtStart = now();
        const timingOriginMs = typeof observers.timingOriginMs === 'number'
            && Number.isFinite(observers.timingOriginMs) && observers.timingOriginMs >= 0
            ? observers.timingOriginMs : nowAtStart;
        let firstRevisionMs, firstFinalRevisionMs;
        let clientFinishMs, streamCloseMs;
        let revisionCount = 0, finalRevisionCount = 0;
        const elapsedMs = (at = now()) => Number.isFinite(at) ? Math.max(0, at - timingOriginMs) : 0;
        const timing = () => Object.freeze({
            stream_id: origin.stream_id, dispatch_ms: elapsedMs(nowAtStart),
            ...(firstRevisionMs === undefined ? {} : { first_revision_ms: firstRevisionMs }),
            ...(firstFinalRevisionMs === undefined ? {} : { first_final_revision_ms: firstFinalRevisionMs }),
            ...(clientFinishMs === undefined ? {} : { client_finish_ms: clientFinishMs }),
            ...(streamCloseMs === undefined ? {} : { stream_close_ms: streamCloseMs }),
            revision_count: revisionCount, final_revision_count: finalRevisionCount,
        });
        const notifyTiming = () => { try {
            observers.onTiming?.(timing());
        }
        catch { /* Observation cannot affect transport. */ } };
        const clearPreview = () => { try {
            observers.onRevision?.(null);
        }
        catch { /* UI observation cannot affect transport. */ } };
        notifyTiming();
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
            clearPreview();
            streamCloseMs = elapsedMs();
            notifyTiming();
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
            finish: (clientFinishAtMs) => {
                if (alive) {
                    sealed = true;
                    clientFinishMs = elapsedMs(typeof clientFinishAtMs === 'number' && Number.isFinite(clientFinishAtMs)
                        && clientFinishAtMs >= 0 ? clientFinishAtMs : now());
                    clearPreview();
                    notifyTiming();
                    drain();
                }
                return final;
            },
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
                    if (packet['type'] === 'transcript') {
                        if (packet['revision'] <= revision || typeof packet['is_final'] !== 'boolean')
                            throw new Error('Invalid transcript finality');
                        revision = packet['revision'];
                        const observedAt = elapsedMs();
                        firstRevisionMs ??= observedAt;
                        if (packet['is_final']) {
                            finalRevisionCount++;
                            firstFinalRevisionMs ??= observedAt;
                        }
                        revisionCount++;
                        notifyTiming();
                        // This callback is a bounded UI-only preview. It cannot enter the input path.
                        if (!sealed) {
                            try {
                                observers.onRevision?.({ stream_id: origin.stream_id, revision, text: packet['text'].slice(0, 2000), is_final: packet['is_final'] });
                            }
                            catch { /* Observation cannot affect transport. */ }
                        }
                    }
                    else {
                        if (!finishSent || typeof packet['had_final'] !== 'boolean' || (!packet['had_final'] && packet['text'] !== ''))
                            throw new Error('Unreliable transcript completion');
                        revision = packet['revision'];
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
    /** A continuous lease is independent of reply generations and ends only on an explicit or finite stop. */
    continuousListening(leaseId, signal, observers, mode = 'manual') {
        if (this.closed || signal.aborted)
            throw cancelled();
        if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(leaseId)) {
            throw new Error('Invalid continuous-listening lease');
        }
        const credentials = this.credentials();
        const setTimer = this.primitives.setTimeout ?? globalThis.setTimeout;
        const clearTimer = this.primitives.clearTimeout ?? globalThis.clearTimeout;
        const now = this.primitives.now ?? (() => performance.now());
        const url = new URL(`${this.config.apiBase}/sessions/${encodeURIComponent(credentials.sessionId)}/continuous-listening`, this.primitives.baseUrl ?? globalThis.location.href);
        if (url.protocol !== 'https:' && url.protocol !== 'http:')
            throw new Error('Invalid continuous-listening endpoint');
        // Credentials are exclusively in the first WebSocket frame, never in URL parameters.
        url.search = '';
        url.hash = '';
        url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
        const socket = (this.primitives.createSocket ?? (address => new WebSocket(address)))(url.href);
        let alive = true, opened = false, authenticated = false, stopping = false, readyReceived = false, finiteSignalled = false;
        let acceptedCommitLimit = false;
        let nextSequence = 1, samples = 0, expectedChunkSequence = 0;
        // Capture may start before ready. Preserve that prefix in a bounded FIFO and
        // pace it from readiness; flushing capture timestamps creates a network burst.
        const deliveryQueue = [];
        let queuedPcmBytes = 0, queuedAudioPackets = 0, sentSamples = 0, readyAt = 0;
        let deliveryTimer = null;
        let readiness = null;
        const pendingCommits = new Map();
        const completedCommits = new Map();
        let retiredCommitRevision = 0, retiredHoldRevision = 0, retiredEndpointSource = 0;
        const pendingHolds = new Map();
        const completedHolds = new Map();
        const endpoints = new Map();
        let readyTimer = null;
        let finiteTimer = null;
        let stopTimer = null;
        let resolveReady;
        let rejectReady;
        let resolveClosed;
        const ready = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
        const closed = new Promise(resolve => { resolveClosed = resolve; });
        void ready.catch(() => { });
        const clearTimers = () => {
            if (readyTimer !== null)
                clearTimer(readyTimer);
            if (finiteTimer !== null)
                clearTimer(finiteTimer);
            if (stopTimer !== null)
                clearTimer(stopTimer);
            if (deliveryTimer !== null)
                clearTimer(deliveryTimer);
            readyTimer = finiteTimer = stopTimer = null;
            deliveryTimer = null;
        };
        const cleanup = () => {
            if (!alive)
                return;
            alive = false;
            clearTimers();
            signal.removeEventListener('abort', onAbort);
            deliveryQueue.length = 0;
            queuedPcmBytes = queuedAudioPackets = 0;
            for (const pending of pendingCommits.values())
                pending.reject(cancelled());
            pendingCommits.clear();
            for (const pending of pendingHolds.values())
                pending.reject(cancelled());
            pendingHolds.clear();
            socket.onopen = null;
            socket.onmessage = null;
            socket.onerror = null;
            socket.onclose = null;
            try {
                socket.close();
            }
            catch { /* Local lease fencing is already complete. */ }
            this.continuousStreams.delete(stream);
            resolveClosed();
        };
        const rejectPendingCommits = () => {
            for (const pending of pendingCommits.values())
                pending.reject(cancelled());
            pendingCommits.clear();
            for (const pending of pendingHolds.values())
                pending.reject(cancelled());
            pendingHolds.clear();
        };
        const rememberCommit = (commitId, revision) => {
            completedCommits.set(commitId, revision);
            if (completedCommits.size > 64) {
                const [key, value] = completedCommits.entries().next().value;
                retiredCommitRevision = Math.max(retiredCommitRevision, value);
                completedCommits.delete(key);
            }
        };
        const retireEndpoints = () => {
            for (const [key, endpoint] of endpoints) {
                if (endpoints.size < 64)
                    break;
                if (endpoint.state !== 'completed' && endpoint.state !== 'cancelled')
                    continue;
                retiredEndpointSource = Math.max(retiredEndpointSource, endpoint.sourceEnd);
                endpoints.delete(key);
            }
        };
        const fail = (error) => {
            if (!alive)
                return;
            cleanup();
            if (!readyReceived)
                rejectReady(error);
            try {
                observers.onError(error);
            }
            catch { /* UI observers cannot retain the lease. */ }
        };
        const localFiniteStop = (reason = 'max_duration') => {
            if (!alive || stopping || finiteSignalled)
                return;
            finiteSignalled = true;
            const event = { type: 'stopped', lease_id: leaseId, reason };
            try {
                observers.onEvent(event);
            }
            catch { /* UI observers cannot retain the lease. */ }
            void stream.stop('user_stop');
        };
        const drainDelivery = () => {
            if (!alive || stopping || !authenticated)
                return;
            if (deliveryTimer !== null) {
                clearTimer(deliveryTimer);
                deliveryTimer = null;
            }
            if (socket.readyState !== 1) {
                fail(new Error('Continuous-listening connection is no longer open.'));
                return;
            }
            try {
                while (deliveryQueue.length) {
                    const head = deliveryQueue[0];
                    const due = readyAt + Math.max(0, (sentSamples + head.frames - 1920) / 16);
                    if (socket.bufferedAmount > 0 || (head.frames > 0 && now() < due)) {
                        deliveryTimer = setTimer(drainDelivery, socket.bufferedAmount > 0 ? 10 : Math.max(1, Math.ceil(due - now())));
                        return;
                    }
                    socket.send(head.text);
                    deliveryQueue.shift();
                    if (head.frames > 0) {
                        sentSamples += head.frames;
                        queuedPcmBytes -= head.frames * 2;
                        queuedAudioPackets--;
                    }
                }
            }
            catch {
                fail(new Error('Continuous-listening transport failed.'));
            }
        };
        readyTimer = setTimer(() => fail(new Error('Continuous listening did not become ready in time.')), 5000);
        const stream = {
            ready, closed,
            send: (chunk) => {
                if (!alive || stopping || !authenticated || !readiness)
                    throw cancelled();
                if (!(chunk.pcm16le instanceof Uint8Array) || chunk.pcm16le.length === 0 || chunk.pcm16le.length > 12000
                    || chunk.pcm16le.length % 2 !== 0 || chunk.sampleRate !== 16000 || chunk.channels !== 1
                    || chunk.sequence !== expectedChunkSequence || chunk.startSample !== samples
                    || chunk.endSample !== samples + chunk.pcm16le.length / 2) {
                    fail(new Error('Invalid or overlong continuous-listening audio.'));
                    throw new Error('Invalid or overlong continuous-listening audio.');
                }
                if (readiness.max_seconds !== null && now() >= (startedAt + readiness.max_seconds * 1000)) {
                    localFiniteStop('max_duration');
                    return;
                }
                if (readiness.max_samples !== null && samples + chunk.pcm16le.length / 2 > readiness.max_samples) {
                    localFiniteStop('max_samples');
                    return;
                }
                const audio = { type: 'audio', lease_id: leaseId, sequence: nextSequence,
                    first_sample: samples, pcm_base64: encode(chunk.pcm16le) };
                const packet = JSON.stringify(audio);
                if (queuedPcmBytes + chunk.pcm16le.length > 65536 || queuedAudioPackets >= 100
                    || socket.bufferedAmount > 65536) {
                    fail(new Error('Continuous-listening delivery fell behind and was stopped.'));
                    throw new Error('Continuous-listening delivery fell behind and was stopped.');
                }
                deliveryQueue.push({ text: packet, frames: chunk.pcm16le.length / 2 });
                queuedPcmBytes += chunk.pcm16le.length;
                queuedAudioPackets++;
                expectedChunkSequence++;
                nextSequence++;
                samples = chunk.endSample;
                drainDelivery();
                if (readiness.max_samples !== null && samples >= readiness.max_samples)
                    localFiniteStop('max_samples');
            },
            endpoint: (endpointId, sourceEndSample) => {
                if (!alive || stopping || !authenticated || !readiness)
                    throw cancelled();
                retireEndpoints();
                const previous = endpoints.get(endpointId);
                if (previous && previous.sourceEnd === sourceEndSample)
                    return;
                if (mode !== 'natural' || readiness.client_endpoint_supported !== true || !isUuid(endpointId)
                    || !count(sourceEndSample) || sourceEndSample < 1 || sourceEndSample !== samples
                    || sourceEndSample <= retiredEndpointSource || previous || endpoints.size >= 64)
                    throw new Error('Invalid client endpoint');
                endpoints.set(endpointId, { sourceEnd: sourceEndSample, state: 'queued', cancelled: false });
                const frame = { type: 'client_endpoint', lease_id: leaseId,
                    endpoint_id: endpointId, source_end_sample: sourceEndSample };
                deliveryQueue.push({ text: JSON.stringify(frame), frames: 0, endpointId });
                drainDelivery();
            },
            cancelEndpoint: (endpointId) => {
                if (!alive || stopping || !authenticated)
                    throw cancelled();
                const previous = endpoints.get(endpointId);
                if (!previous)
                    throw new Error('Unknown client endpoint');
                if (previous.cancelled)
                    return;
                previous.cancelled = true;
                const unsent = deliveryQueue.findIndex(item => item.endpointId === endpointId);
                if (unsent >= 0) {
                    deliveryQueue.splice(unsent, 1);
                    previous.state = 'cancelled';
                    try {
                        observers.onEvent({ type: 'endpoint_status', lease_id: leaseId, endpoint_id: endpointId,
                            source_end_sample: previous.sourceEnd, state: 'cancelled' });
                    }
                    catch { /* Observer cannot retain capture. */ }
                    return;
                }
                const frame = { type: 'cancel_endpoint', lease_id: leaseId, endpoint_id: endpointId };
                try {
                    socket.send(JSON.stringify(frame));
                }
                catch {
                    fail(new Error('Endpoint cancellation transport failed'));
                }
            },
            commit: (commitId, revision, utteranceId) => {
                if (!alive || stopping || !authenticated || !readiness)
                    return Promise.reject(cancelled());
                if (!isUuid(commitId) || !count(revision) || revision < 1 || pendingCommits.has(commitId)
                    || completedCommits.has(commitId) || revision <= retiredCommitRevision || pendingCommits.size >= 1 || pendingHolds.size >= 1
                    || (utteranceId !== undefined && (!isUuid(utteranceId) || mode !== 'natural'
                        || readiness.endpoint_mode !== 'google_vad_offsets_natural' || readiness.manual_commit_required !== false))) {
                    return Promise.reject(new Error('Invalid or duplicate continuous-listening commit.'));
                }
                return new Promise((resolve, reject) => {
                    pendingCommits.set(commitId, { revision, ...(utteranceId === undefined ? {} : { utteranceId }), resolve, reject });
                    const commit = { type: 'commit', lease_id: leaseId, commit_id: commitId, revision,
                        ...(utteranceId === undefined ? {} : { utterance_id: utteranceId }) };
                    try {
                        socket.send(JSON.stringify(commit));
                    }
                    catch {
                        pendingCommits.delete(commitId);
                        reject(new Error('Continuous-listening commit could not be sent.'));
                        fail(new Error('Continuous-listening transport failed.'));
                    }
                });
            },
            hold: (utteranceId, revision) => {
                if (!alive || stopping || !authenticated || !readiness)
                    return Promise.reject(cancelled());
                if (mode !== 'natural' || readiness.endpoint_mode !== 'google_vad_offsets_natural'
                    || readiness.manual_commit_required !== false || !isUuid(utteranceId) || !count(revision) || revision < 1) {
                    return Promise.reject(new Error('Invalid continuous-listening hold.'));
                }
                const key = `${utteranceId}:${revision}`, pending = pendingHolds.get(key), completed = completedHolds.get(key);
                if (pending)
                    return pending.promise;
                if (completed)
                    return Promise.resolve(completed);
                if (revision <= retiredHoldRevision || pendingHolds.size >= 1 || pendingCommits.size >= 1) {
                    return Promise.reject(new Error('Continuous-listening hold request is already pending or at its limit.'));
                }
                let resolve, reject;
                const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
                pendingHolds.set(key, { promise, resolve, reject });
                const hold = { type: 'hold', lease_id: leaseId, utterance_id: utteranceId, revision };
                try {
                    socket.send(JSON.stringify(hold));
                }
                catch {
                    fail(new Error('Continuous-listening hold could not be sent.'));
                }
                return promise;
            },
            stop: (reason = 'user_stop') => {
                if (!alive)
                    return closed;
                if (!opened || !authenticated || socket.readyState !== 1) {
                    cleanup();
                    if (!readyReceived)
                        rejectReady(cancelled());
                    return closed;
                }
                if (stopping)
                    return closed;
                stopping = true;
                rejectPendingCommits();
                const stop = { type: 'stop', lease_id: leaseId, reason };
                try {
                    socket.send(JSON.stringify(stop));
                }
                catch {
                    cleanup();
                    return closed;
                }
                // The local capture is already stopped by its owner. Bound waiting for the server ack.
                stopTimer = setTimer(() => cleanup(), 1500);
                return closed;
            },
            cancel: () => {
                if (!alive)
                    return;
                if (opened && authenticated && socket.readyState === 1 && !stopping && !acceptedCommitLimit) {
                    stopping = true;
                    const stop = { type: 'stop', lease_id: leaseId, reason: 'user_stop' };
                    try {
                        socket.send(JSON.stringify(stop));
                    }
                    catch { /* Socket close still releases the server-side lease. */ }
                }
                cleanup();
                if (!readyReceived)
                    rejectReady(cancelled());
            },
        };
        const startedAt = now();
        const onAbort = () => { stream.cancel(); };
        this.continuousStreams.add(stream);
        signal.addEventListener('abort', onAbort, { once: true });
        socket.onopen = () => {
            if (!alive || signal.aborted)
                return;
            opened = true;
            const start = { type: 'start', session_token: credentials.token, lease_id: leaseId,
                ...(mode === 'natural' ? { mode, client_endpointing: true } : {}) };
            try {
                socket.send(JSON.stringify(start));
            }
            catch {
                fail(new Error('Continuous-listening authentication transport failed.'));
            }
        };
        socket.onmessage = (event) => {
            if (!alive || signal.aborted)
                return;
            try {
                if (typeof event.data !== 'string' || event.data.length > 20000)
                    throw new Error('Invalid continuous-listening packet');
                const raw = record(JSON.parse(event.data));
                if (raw['type'] === 'error') {
                    fail(new Error(safeSessionError(raw['code'], Object.hasOwn(raw, 'diagnostic_id') ? raw['diagnostic_id'] : null)));
                    return;
                }
                if (raw['type'] === 'ready') {
                    if (!opened || readyReceived || raw['lease_id'] !== leaseId
                        || (raw['sample_rate_hz'] !== undefined && raw['sample_rate_hz'] !== 16000)
                        || !localLimit(raw['max_seconds'], 290)
                        || !localLimit(raw['max_samples'], 16000 * 290)
                        || (raw['max_samples'] !== null && raw['max_seconds'] !== null && raw['max_samples'] > raw['max_seconds'] * 16000)
                        || !localLimit(raw['max_utterances'], 32)
                        || !localLimit(raw['max_streams_per_session'], 16)
                        || !localLimit(raw['max_total_streams'], 100)
                        || !count(raw['session_lease_starts_used'])
                        || !count(raw['total_lease_starts_used'])
                        || (raw['stt_requests_used'] !== undefined && raw['stt_requests_used'] !== null
                            && !count(raw['stt_requests_used']))
                        || (raw['stt_requests_remaining'] !== undefined && raw['stt_requests_remaining'] !== null
                            && (!count(raw['stt_requests_remaining']) || raw['stt_requests_remaining'] > 100))
                        || (raw['client_endpoint_supported'] !== undefined && (typeof raw['client_endpoint_supported'] !== 'boolean'
                            || (raw['client_endpoint_supported'] === true && (mode !== 'natural' || raw['endpoint_mode'] !== 'google_vad_offsets_natural'))))
                        || (raw['client_silence_ms'] !== undefined && (!count(raw['client_silence_ms']) || raw['client_silence_ms'] < 250 || raw['client_silence_ms'] > 2000))
                        || (raw['client_endpoint_supported'] === true && raw['client_silence_ms'] === undefined)
                        || (raw['natural_grace_ms'] !== undefined && (!count(raw['natural_grace_ms']) || raw['natural_grace_ms'] > 2000))
                        || (raw['drain_timeout_ms'] !== undefined && (!count(raw['drain_timeout_ms']) || raw['drain_timeout_ms'] < 100 || raw['drain_timeout_ms'] > 5000))
                        || (raw['max_recognition_streams'] !== undefined && !localLimit(raw['max_recognition_streams'], 32))
                        || !['google_vad_offsets_manual_commit', 'google_vad_offsets_natural', 'unavailable_manual'].includes(String(raw['endpoint_mode']))
                        || (raw['endpoint_mode'] === 'google_vad_offsets_natural'
                            ? mode !== 'natural' || raw['manual_commit_required'] !== false
                            : raw['manual_commit_required'] !== true))
                        throw new Error('Invalid continuous-listening readiness');
                    readiness = Object.freeze({ lease_id: leaseId, sample_rate_hz: 16000, max_seconds: raw['max_seconds'],
                        max_samples: raw['max_samples'], max_utterances: raw['max_utterances'],
                        max_streams_per_session: raw['max_streams_per_session'], max_total_streams: raw['max_total_streams'],
                        session_lease_starts_used: raw['session_lease_starts_used'], total_lease_starts_used: raw['total_lease_starts_used'],
                        ...(raw['stt_requests_used'] === undefined ? {} : { stt_requests_used: raw['stt_requests_used'] }),
                        ...(raw['stt_requests_remaining'] === undefined ? {} : { stt_requests_remaining: raw['stt_requests_remaining'] }),
                        ...(raw['client_endpoint_supported'] === undefined ? {} : { client_endpoint_supported: raw['client_endpoint_supported'] }),
                        ...(raw['client_silence_ms'] === undefined ? {} : { client_silence_ms: raw['client_silence_ms'] }),
                        ...(raw['natural_grace_ms'] === undefined ? {} : { natural_grace_ms: raw['natural_grace_ms'] }),
                        ...(raw['drain_timeout_ms'] === undefined ? {} : { drain_timeout_ms: raw['drain_timeout_ms'] }),
                        ...(raw['max_recognition_streams'] === undefined ? {} : { max_recognition_streams: raw['max_recognition_streams'] }),
                        endpoint_mode: raw['endpoint_mode'],
                        manual_commit_required: raw['manual_commit_required'] });
                    authenticated = true;
                    readyReceived = true;
                    readyAt = now();
                    if (readyTimer !== null)
                        clearTimer(readyTimer);
                    readyTimer = null;
                    if (readiness.max_seconds !== null)
                        finiteTimer = setTimer(localFiniteStop, readiness.max_seconds * 1000);
                    resolveReady(readiness);
                    try {
                        observers.onEvent({ type: 'ready', ready: readiness });
                    }
                    catch { /* UI observers cannot retain the lease. */ }
                    return;
                }
                if (raw['lease_id'] !== leaseId || !authenticated)
                    throw new Error('Continuous-listening lease mismatch');
                if (stopping && raw['type'] !== 'stopped')
                    return;
                if (raw['type'] === 'transcript') {
                    if (!count(raw['revision']) || raw['revision'] < 1 || typeof raw['text'] !== 'string'
                        || raw['text'].length > 16000 || typeof raw['is_final'] !== 'boolean'
                        || (raw['committed_commit_id'] != null && !isUuid(raw['committed_commit_id']))
                        || (raw['committed_utterance_id'] != null && (!isUuid(raw['committed_utterance_id']) || !isUuid(raw['committed_commit_id'])))) {
                        throw new Error('Invalid transcript frame');
                    }
                    try {
                        observers.onEvent({ type: 'transcript', lease_id: leaseId, revision: raw['revision'],
                            text: raw['text'], is_final: raw['is_final'],
                            ...(raw['committed_commit_id'] == null ? {} : { committed_commit_id: raw['committed_commit_id'] }),
                            ...(raw['committed_utterance_id'] == null ? {} : { committed_utterance_id: raw['committed_utterance_id'] }) });
                    }
                    catch { /* Preview is not part of transport. */ }
                }
                else if (raw['type'] === 'endpoint_pending') {
                    if (!count(raw['revision']) || raw['revision'] < 1 || typeof raw['text'] !== 'string'
                        || raw['text'].length > 16000 || !['missing_result_offset', 'unmatched_activity_end'].includes(String(raw['reason']))
                        || (raw['can_submit_manually'] !== undefined && typeof raw['can_submit_manually'] !== 'boolean')) {
                        throw new Error('Invalid endpoint-pending frame');
                    }
                    try {
                        observers.onEvent({ type: 'endpoint_pending', lease_id: leaseId, revision: raw['revision'],
                            text: raw['text'], reason: raw['reason'],
                            ...(raw['can_submit_manually'] === undefined ? {} : { can_submit_manually: raw['can_submit_manually'] }) });
                    }
                    catch { /* Manual review remains separate from transport. */ }
                }
                else if (raw['type'] === 'endpoint_status') {
                    if (!isUuid(raw['endpoint_id']) || !count(raw['source_end_sample'])
                        || !['queued', 'draining', 'cancelled', 'completed'].includes(String(raw['state'])))
                        throw new Error('Invalid endpoint status');
                    const pending = endpoints.get(raw['endpoint_id']);
                    if (!pending || pending.sourceEnd !== raw['source_end_sample'])
                        throw new Error('Uncorrelated endpoint status');
                    const next = String(raw['state']);
                    const allowed = { queued: ['queued', 'draining', 'cancelled', 'completed'],
                        draining: ['draining', 'completed'], cancelled: ['cancelled'], completed: ['completed'] };
                    if (!allowed[pending.state]?.includes(next))
                        throw new Error('Invalid endpoint state transition');
                    pending.state = next;
                    try {
                        observers.onEvent({ type: 'endpoint_status', lease_id: leaseId, endpoint_id: raw['endpoint_id'],
                            source_end_sample: raw['source_end_sample'], state: next });
                    }
                    catch { /* Controller owns candidate cancellation. */ }
                }
                else if (raw['type'] === 'utterance_ready') {
                    const basis = raw['endpoint_basis'] ?? 'offset_coverage';
                    const final = raw['final_offset_samples'];
                    if (readiness?.endpoint_mode !== 'google_vad_offsets_natural' || readiness.manual_commit_required !== false
                        || !isUuid(raw['utterance_id']) || !count(raw['revision']) || raw['revision'] < 1
                        || typeof raw['text'] !== 'string' || raw['text'].length > 2000
                        || !['offset_coverage', 'vad_final_grace', 'stream_finalized', 'client_silence_finalized'].includes(String(basis))
                        || !count(raw['begin_offset_samples']) || !count(raw['end_offset_samples']) || !count(raw['source_end_sample'])
                        || raw['source_end_sample'] < 1 || raw['begin_offset_samples'] > raw['end_offset_samples']
                        || raw['end_offset_samples'] > raw['source_end_sample'] || raw['source_end_sample'] > samples
                        || (readiness.max_samples !== null && raw['source_end_sample'] > readiness.max_samples)
                        || (final === null ? !['stream_finalized', 'client_silence_finalized'].includes(String(basis))
                            : !count(final) || final < raw['begin_offset_samples'] || final > raw['source_end_sample'])
                        || (raw['client_endpoint_id'] != null && !isUuid(raw['client_endpoint_id']))
                        || (basis === 'client_silence_finalized' && (readiness.client_endpoint_supported !== true
                            || !isUuid(raw['client_endpoint_id']) || !endpoints.has(raw['client_endpoint_id'])
                            || endpoints.get(raw['client_endpoint_id'])?.state !== 'completed'
                            || endpoints.get(raw['client_endpoint_id'])?.sourceEnd !== raw['source_end_sample']))
                        || (basis !== 'client_silence_finalized' && raw['client_endpoint_id'] != null)
                        || (basis === 'offset_coverage' && final < raw['end_offset_samples'])
                        || (basis === 'vad_final_grace' && !(readiness.natural_grace_ms && readiness.natural_grace_ms > 0))) {
                        throw new Error('Invalid utterance-ready frame');
                    }
                    const result = { type: 'utterance_ready', lease_id: leaseId,
                        utterance_id: raw['utterance_id'], revision: raw['revision'], text: raw['text'],
                        begin_offset_samples: raw['begin_offset_samples'], end_offset_samples: raw['end_offset_samples'],
                        final_offset_samples: final,
                        endpoint_basis: basis,
                        ...(raw['client_endpoint_id'] == null ? {} : { client_endpoint_id: raw['client_endpoint_id'] }),
                        source_end_sample: raw['source_end_sample'] };
                    try {
                        observers.onEvent(result);
                    }
                    catch { /* The controller owns automatic submission. */ }
                }
                else if (raw['type'] === 'recognition_status') {
                    if (!readiness || !count(raw['stream_index']) || raw['stream_index'] < 1
                        || (readiness.max_recognition_streams !== null && raw['stream_index'] > (readiness.max_recognition_streams ?? 1))
                        || !['opening', 'listening', 'draining', 'awaiting_commit', 'completed', 'limit'].includes(String(raw['state']))
                        || (raw['stt_requests_used'] != null && !count(raw['stt_requests_used']))
                        || (raw['stt_requests_remaining'] != null && (!count(raw['stt_requests_remaining']) || raw['stt_requests_remaining'] > 100))) {
                        throw new Error('Invalid recognition-status frame');
                    }
                    const result = {
                        type: 'recognition_status', lease_id: leaseId, stream_index: raw['stream_index'],
                        state: raw['state'],
                        ...(raw['stt_requests_used'] === undefined ? {} : { stt_requests_used: raw['stt_requests_used'] }),
                        ...(raw['stt_requests_remaining'] === undefined ? {} : { stt_requests_remaining: raw['stt_requests_remaining'] })
                    };
                    try {
                        observers.onEvent(result);
                    }
                    catch { /* Capture ownership is independent of provider stream settlement. */ }
                }
                else if (raw['type'] === 'utterance_revision') {
                    if (readiness?.endpoint_mode !== 'google_vad_offsets_natural' || !isUuid(raw['utterance_id'])
                        || !isUuid(raw['commit_id']) || !count(raw['revision']) || raw['revision'] < 1
                        || typeof raw['text'] !== 'string' || raw['text'].length > 2000
                        || raw['reason'] !== 'late_result_after_submission' || raw['requires_review'] !== true
                        || !['pending', 'reserved', 'accepted', 'revoked', 'unknown'].includes(String(raw['submission_state']))) {
                        throw new Error('Invalid utterance-revision frame');
                    }
                    const result = {
                        type: 'utterance_revision', lease_id: leaseId, utterance_id: raw['utterance_id'], commit_id: raw['commit_id'],
                        revision: raw['revision'], text: raw['text'], reason: 'late_result_after_submission', requires_review: true,
                        submission_state: raw['submission_state']
                    };
                    try {
                        observers.onEvent(result);
                    }
                    catch { /* Corrections stay associated with their original turn. */ }
                }
                else if (raw['type'] === 'utterance_held' || raw['type'] === 'hold_rejected') {
                    if (!isUuid(raw['utterance_id']) || !count(raw['revision']) || raw['revision'] < 1) {
                        throw new Error('Invalid hold identity');
                    }
                    let result;
                    if (raw['type'] === 'utterance_held') {
                        if (typeof raw['text'] !== 'string' || !raw['text'].length || raw['text'].length > 2000) {
                            throw new Error('Invalid held utterance text');
                        }
                        result = { type: 'utterance_held', lease_id: leaseId, utterance_id: raw['utterance_id'], revision: raw['revision'], text: raw['text'] };
                    }
                    else {
                        if (!count(raw['current_revision'])
                            || !['stale_revision', 'lease_revoked', 'identity_conflict', 'request_limit'].includes(String(raw['reason']))) {
                            throw new Error('Invalid hold rejection');
                        }
                        result = { type: 'hold_rejected', lease_id: leaseId, utterance_id: raw['utterance_id'], revision: raw['revision'],
                            current_revision: raw['current_revision'], reason: raw['reason'] };
                    }
                    const key = `${result.utterance_id}:${result.revision}`, pending = pendingHolds.get(key);
                    if (!pending) {
                        const completed = completedHolds.get(key);
                        if (completed && JSON.stringify(completed) === JSON.stringify(result))
                            return;
                        throw new Error('Unexpected or conflicting hold response');
                    }
                    pendingHolds.delete(key);
                    completedHolds.set(key, result);
                    if (completedHolds.size > 64) {
                        const [oldKey, oldResult] = completedHolds.entries().next().value;
                        retiredHoldRevision = Math.max(retiredHoldRevision, oldResult.revision);
                        completedHolds.delete(oldKey);
                    }
                    pending.resolve(result);
                    try {
                        observers.onEvent(result);
                    }
                    catch { /* The controller retains held text independently. */ }
                }
                else if (raw['type'] === 'commit_ready') {
                    if (!isUuid(raw['commit_id']) || !count(raw['segment_seq']) || raw['segment_seq'] < 1
                        || !readiness || (readiness.max_utterances !== null && raw['segment_seq'] > readiness.max_utterances)
                        || !count(raw['revision']) || raw['revision'] < 1 || typeof raw['text'] !== 'string'
                        || raw['text'].length > 2000
                        || (raw['utterance_id'] !== undefined && raw['utterance_id'] !== null && !isUuid(raw['utterance_id']))) {
                        throw new Error('Invalid commit-ready frame');
                    }
                    const pending = pendingCommits.get(raw['commit_id']);
                    if (!pending) {
                        if (completedCommits.has(raw['commit_id']))
                            return;
                        throw new Error('Unexpected commit-ready frame');
                    }
                    if (raw['revision'] !== pending.revision || (raw['utterance_id'] ?? undefined) !== pending.utteranceId) {
                        throw new Error('Mismatched commit-ready frame');
                    }
                    const result = { type: 'commit_ready', lease_id: leaseId,
                        commit_id: raw['commit_id'], segment_seq: raw['segment_seq'], revision: raw['revision'], text: raw['text'],
                        ...(pending.utteranceId === undefined ? {} : { utterance_id: pending.utteranceId }) };
                    // The server has already closed capture at its accepted count limit.
                    // Resource cleanup must not become a new user cancellation that revokes
                    // the final delivered input while it waits at the ordinary receipt barrier.
                    acceptedCommitLimit = raw['segment_seq'] === readiness?.max_utterances;
                    pendingCommits.delete(raw['commit_id']);
                    rememberCommit(raw['commit_id'], pending.revision);
                    pending.resolve(result);
                    try {
                        observers.onEvent(result);
                    }
                    catch { /* Commit still belongs to the controller. */ }
                }
                else if (raw['type'] === 'commit_rejected') {
                    if (!isUuid(raw['commit_id']) || !count(raw['current_revision'])
                        || !['stale_revision', 'no_final_text', 'request_limit', 'lease_revoked', 'identity_conflict', 'pending_capacity'].includes(String(raw['reason']))) {
                        throw new Error('Invalid commit-rejected frame');
                    }
                    const pending = pendingCommits.get(raw['commit_id']);
                    if (!pending) {
                        if (completedCommits.has(raw['commit_id']))
                            return;
                        throw new Error('Unexpected commit-rejected frame');
                    }
                    const result = { type: 'commit_rejected', lease_id: leaseId,
                        commit_id: raw['commit_id'], reason: raw['reason'],
                        current_revision: raw['current_revision'] };
                    pendingCommits.delete(raw['commit_id']);
                    rememberCommit(raw['commit_id'], pending.revision);
                    pending.resolve(result);
                    try {
                        observers.onEvent(result);
                    }
                    catch { /* A stale click never triggers a hidden retry. */ }
                }
                else if (raw['type'] === 'stopped') {
                    if (typeof raw['reason'] !== 'string' || !LISTENING_STOP_REASONS.has(raw['reason'])) {
                        throw new Error('Invalid stopped frame');
                    }
                    const reason = raw['reason'];
                    try {
                        observers.onEvent({ type: 'stopped', lease_id: leaseId, reason });
                    }
                    catch { /* Cleanup must continue. */ }
                    cleanup();
                }
                else
                    throw new Error('Unknown continuous-listening frame');
            }
            catch {
                fail(new Error('Continuous-listening response failed validation.'));
            }
        };
        socket.onerror = () => fail(new Error('Continuous-listening connection failed.'));
        socket.onclose = () => {
            if (stopping)
                cleanup();
            else
                fail(new Error('Continuous-listening connection ended unexpectedly.'));
        };
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
        for (const stream of this.continuousStreams)
            stream.cancel();
        this.continuousStreams.clear();
    }
}
