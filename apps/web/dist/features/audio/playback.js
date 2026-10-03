/** One character-voice sink; no policy, wire receipts, provider selection or speech synthesis. */
export class CancelSafePlayback {
    options;
    context = null;
    current = null;
    generation = 0;
    timer = null;
    closed = false;
    closePromise = null;
    maxBufferedFrames;
    maxChunkFrames;
    maxQueuedChunks;
    constructor(options) {
        this.options = options;
        this.maxBufferedFrames = this.bound(options.maxBufferedFrames ?? 120_000, 1, 480_000);
        this.maxChunkFrames = this.bound(options.maxChunkFrames ?? 24_000, 1, 48_000);
        this.maxQueuedChunks = this.bound(options.maxQueuedChunks ?? 50, 1, 500);
    }
    bound(value, minimum, maximum) {
        if (!Number.isSafeInteger(value) || value < minimum || value > maximum)
            throw new RangeError('Invalid audio buffer bound');
        return value;
    }
    authorized(origin) {
        try {
            return this.options.isAuthorized(origin) === true;
        }
        catch {
            return false;
        }
    }
    alive(state) {
        return !this.closed && this.current === state && state.generation === this.generation;
    }
    permitted(state) {
        if (!this.alive(state))
            return false;
        if (this.authorized(state.origin))
            return true;
        this.stop('revoked');
        return false;
    }
    /** Call from a user gesture to satisfy browser autoplay policies; never requests microphone access. */
    async unlock() {
        if (this.closed)
            return false;
        try {
            await this.getContext().resume();
            return !this.closed;
        }
        catch {
            if (!this.closed)
                this.error('playback-failed', 'Audio could not start. Use text or retry audio from a user gesture.');
            return false;
        }
    }
    open(origin) {
        if (this.closed || !this.authorized(origin))
            return null;
        // Reopening the same active effect must not restart already submitted sound.
        if (this.current && JSON.stringify(this.current.origin) === JSON.stringify(this.copyOrigin(origin)))
            return null;
        this.stop('new-input');
        const state = { generation: ++this.generation, origin: this.copyOrigin(origin),
            queue: [], sealed: false, pumping: false, bufferedFrames: 0, submittedFrames: 0,
            renderedFrames: 0, source: null, activeFrames: 0 };
        this.current = state;
        this.timer = (this.options.setInterval ?? globalThis.setInterval)(() => this.reconcileAuthorization(), 20);
        return Object.freeze({
            push: (pcm16) => this.push(state, pcm16),
            finish: () => {
                if (!this.permitted(state) || state.sealed)
                    return false;
                if (state.submittedFrames === 0 && state.bufferedFrames === 0) {
                    this.fail(state, 'invalid-pcm', 'No audio was received for this response.');
                    return false;
                }
                state.sealed = true;
                this.completeIfDrained(state);
                return true;
            },
        });
    }
    copyOrigin(origin) {
        return Object.freeze({ id: origin.id, digest: origin.digest, activity_seq: origin.activity_seq, output_epoch: origin.output_epoch });
    }
    push(state, pcm16) {
        if (!this.permitted(state) || state.sealed)
            return false;
        if (!(pcm16 instanceof Int16Array) || pcm16.length === 0) {
            this.fail(state, 'invalid-pcm', 'Audio requires nonempty signed PCM16 mono at 24 kHz.');
            return false;
        }
        if (pcm16.length > this.maxChunkFrames || state.bufferedFrames + pcm16.length > this.maxBufferedFrames
            || state.queue.length + (state.source ? 1 : 0) >= this.maxQueuedChunks) {
            this.fail(state, 'queue-overflow', 'Audio buffer limit exceeded; this response was stopped.');
            return false;
        }
        state.queue.push(pcm16.slice());
        state.bufferedFrames += pcm16.length;
        void this.pump(state);
        return true;
    }
    getContext() {
        if (!this.context) {
            if (this.options.createContext)
                this.context = this.options.createContext();
            else if (typeof globalThis.AudioContext === 'function')
                this.context = new AudioContext({ latencyHint: 'interactive' });
            else
                throw new Error('Web Audio unavailable');
        }
        return this.context;
    }
    async pump(state) {
        if (!this.permitted(state) || state.pumping || state.source || state.queue.length === 0)
            return;
        state.pumping = true;
        try {
            const context = this.getContext();
            await context.resume();
            // A pending autoplay/resume promise is never authority to start an old generation.
            if (!this.permitted(state))
                return;
            const pcm16 = state.queue.shift();
            if (!pcm16)
                return;
            const buffer = context.createBuffer(1, pcm16.length, 24_000);
            const channel = buffer.getChannelData(0);
            for (let i = 0; i < pcm16.length; i++)
                channel[i] = pcm16[i] / 32768;
            const source = context.createBufferSource();
            state.source = source;
            state.activeFrames = pcm16.length;
            source.buffer = buffer;
            source.onended = () => this.ended(state, source);
            source.connect(context.destination);
            if (!this.permitted(state))
                return;
            source.start();
            state.submittedFrames += pcm16.length;
            this.fact(state, 'submitted');
        }
        catch {
            if (this.alive(state))
                this.fail(state, 'playback-failed', 'Audio playback failed. Text input is still available.');
        }
        finally {
            state.pumping = false;
        }
    }
    ended(state, source) {
        if (!this.permitted(state) || state.source !== source)
            return;
        source.onended = null;
        try {
            source.disconnect();
        }
        catch { /* Already disconnected by the browser. */ }
        state.source = null;
        state.renderedFrames += state.activeFrames;
        state.bufferedFrames -= state.activeFrames;
        state.activeFrames = 0;
        this.fact(state, 'rendered');
        if (!this.alive(state))
            return;
        this.completeIfDrained(state);
        void this.pump(state);
    }
    completeIfDrained(state) {
        if (!this.permitted(state) || !state.sealed || state.source || state.queue.length !== 0 || state.bufferedFrames !== 0)
            return;
        this.current = null;
        this.clearTimer();
        this.fact(state, 'completed');
    }
    /** Integrator calls synchronously after every installed permit update. */
    reconcileAuthorization() {
        if (this.current && !this.authorized(this.current.origin))
            this.stop('revoked');
    }
    stop(reason = 'stop') { this.terminate(reason, 'stopped'); }
    terminate(reason, stage) {
        const state = this.current;
        this.current = null;
        this.generation++;
        this.clearTimer();
        if (!state)
            return;
        state.queue.length = 0;
        state.bufferedFrames = 0;
        const source = state.source;
        state.source = null;
        if (source) {
            source.onended = null;
            // Disconnect synchronously even if stop() throws or onended is already queued.
            try {
                source.disconnect();
            }
            catch { /* Best effort resource release. */ }
            try {
                source.stop();
            }
            catch { /* An already ended source can reject stop. */ }
        }
        this.fact(state, stage, reason);
    }
    clearTimer() {
        if (this.timer !== null)
            (this.options.clearInterval ?? globalThis.clearInterval)(this.timer);
        this.timer = null;
    }
    fail(state, code, message) {
        if (!this.alive(state))
            return;
        this.terminate('error', 'failed');
        this.error(code, message);
    }
    error(code, message) {
        try {
            this.options.onError?.(Object.freeze({ code, message }));
        }
        catch { /* Error observers cannot revive the sink. */ }
    }
    fact(state, stage, reason) {
        const fact = Object.freeze({ origin: state.origin, stage, submittedFrames: state.submittedFrames,
            renderedFrames: state.renderedFrames, sampleRate: 24000,
            inFlightFramesUncertain: state.submittedFrames - state.renderedFrames,
            ...(reason === undefined ? {} : { reason }) });
        try {
            this.options.onFact?.(fact);
        }
        catch {
            if (this.alive(state))
                this.fail(state, 'consumer-failed', 'Audio progress handling failed; playback stopped.');
        }
    }
    close() {
        if (this.closePromise)
            return this.closePromise;
        this.closed = true;
        this.stop('close');
        const context = this.context;
        this.context = null;
        this.closePromise = context ? context.close().catch(() => {
            this.error('playback-failed', 'The audio device did not close cleanly.');
        }) : Promise.resolve();
        return this.closePromise;
    }
}
//# sourceMappingURL=playback.js.map