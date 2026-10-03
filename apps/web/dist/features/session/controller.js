import { CancelSafePlayback, MicrophoneCapture } from '../audio/index.js';
import { safeSessionError } from '../diagnostics/status.js';
import { PresentationGate } from '../presentation/permit-gate.js';
const MEDIA_PREPARATION_LIMIT = 4;
const MEDIA_PREPARATION_ERROR = '旅行插画暂时无法显示，请稍后重试或继续聊天。';
/** One gate, one playback sink and one microphone. Every continuation carries local causality. */
export class SessionController {
    api;
    effects;
    view;
    config;
    reportedError = null;
    gate = null;
    snapshot = null;
    capabilities = null;
    running = false;
    connecting = false;
    closed = false;
    generation = 0;
    lifetime = new AbortController();
    activityRequest = null;
    pollRequest = null;
    pollTimer = null;
    playback;
    capture;
    visualPreparations = new Map();
    speech = null;
    microphone = null;
    rehearsalInput = null;
    unlocked = false;
    facts = Promise.resolve();
    pendingFacts = 0;
    closePromise = null;
    constructor(api, effects, view, config, options = {}) {
        this.api = api;
        this.effects = effects;
        this.view = view;
        this.config = config;
        this.playback = (options.createPlayback ?? (settings => new CancelSafePlayback(settings)))({
            isAuthorized: origin => !this.closed && this.gate?.isAuthorized(origin) === true,
            onFact: fact => this.playbackFact(fact),
            onError: error => { if (!this.closed)
                this.view.error(error.message); },
        });
        this.capture = (options.createCapture ?? (settings => new MicrophoneCapture(settings)))({
            onChunk: chunk => this.captureChunk(chunk),
            onState: state => {
                const current = this.microphone;
                if (!current || !this.current(current.generation) || current.released)
                    return;
                if (state === 'recording') {
                    this.effects.setPhase?.('listening');
                    this.view.microphone?.('recording');
                }
                else if (state === 'starting')
                    this.view.microphone?.('starting');
            },
            onError: error => { if (this.microphone && !this.closed)
                this.fail(new Error(error.message)); },
        });
    }
    current(generation) { return !this.closed && this.running && generation === this.generation; }
    async connect() {
        if (this.closed || this.running || this.connecting)
            return;
        this.connecting = true;
        const clientId = crypto.randomUUID();
        try {
            const created = await this.api.create(clientId, this.lifetime.signal);
            if (this.closed) {
                await this.api.close();
                return;
            }
            this.gate = new PresentationGate(created.session.session_id, clientId);
            this.running = true;
            this.view.connected();
            this.install(created.session);
            void this.api.capabilities(this.lifetime.signal).then(value => {
                if (this.closed)
                    return;
                this.capabilities = value;
                this.view.capabilities?.(value);
                this.startSpeech();
            }).catch(error => { if (!this.closed)
                this.report(error); });
            void this.poll();
        }
        catch (error) {
            if (!this.closed) {
                this.fail(error);
                throw error;
            }
        }
        finally {
            this.connecting = false;
        }
    }
    install(snapshot) {
        const gate = this.gate;
        if (this.closed || !gate)
            return;
        if (this.snapshot && (snapshot.session_id !== this.snapshot.session_id
            || snapshot.client_instance_id !== this.snapshot.client_instance_id)) {
            this.fail(new Error('Session response identity mismatch. Local output was stopped.'));
            return;
        }
        try {
            if (!gate.install(snapshot))
                return;
        }
        catch (error) {
            this.fail(error);
            return;
        }
        // Revocation is reconciled synchronously even when this snapshot belongs to an old activity.
        this.playback.reconcileAuthorization();
        this.cancelRevokedVisualPreparations();
        if (snapshot.activity_seq !== gate.currentActivity())
            return;
        this.snapshot = snapshot;
        this.view.update(snapshot);
        if (snapshot.phase === 'error') {
            this.fail(new Error(safeSessionError(snapshot.last_error ?? 'generation_failed', snapshot.last_error_diagnostic_id)));
            return;
        }
        this.presentVisuals();
        this.startSpeech();
        if (!this.speech && !this.microphone && !this.rehearsalInput && snapshot.sealed && snapshot.phase === 'idle')
            this.effects.setPhase?.('idle');
    }
    presentVisuals() {
        const gate = this.gate;
        if (!gate || !this.snapshot || this.closed)
            return;
        for (const effect of this.snapshot.active_grants) {
            if (effect.kind === 'speech' || !gate.allows(effect))
                continue;
            if (effect.kind === 'media')
                this.prepareMediaEffect(effect, this.generation, gate);
            else
                this.applyVisualEffect(effect, this.generation, gate);
        }
    }
    applyVisualEffect(effect, generation, gate) {
        if (!this.current(generation) || this.gate !== gate || !gate.allows(effect))
            return;
        try {
            this.effects.apply(effect);
        }
        catch (error) {
            this.fail(error);
            return;
        }
        // apply() is synchronous, but may re-enter application code. Revalidate before history.
        if (!this.current(generation) || this.gate !== gate || !gate.allows(effect))
            return;
        const receipt = gate.consume(effect);
        if (receipt)
            this.enqueueFact(receipt, false, generation);
    }
    prepareMediaEffect(effect, generation, gate) {
        if (!this.current(generation) || this.gate !== gate || !gate.allows(effect))
            return;
        if (this.visualPreparations.has(effect.id))
            return;
        if (!this.effects.prepare || this.visualPreparations.size >= MEDIA_PREPARATION_LIMIT) {
            this.view.error(MEDIA_PREPARATION_ERROR);
            return;
        }
        const run = { effect, generation, gate, abort: new AbortController() };
        this.visualPreparations.set(effect.id, run);
        void this.finishMediaPreparation(run);
    }
    async finishMediaPreparation(run) {
        const stillAuthorized = () => this.visualPreparations.get(run.effect.id) === run
            && !run.abort.signal.aborted && this.current(run.generation)
            && this.gate === run.gate && run.gate.allows(run.effect);
        try {
            await this.effects.prepare(run.effect, run.abort.signal);
        }
        catch {
            if (stillAuthorized())
                this.view.error(MEDIA_PREPARATION_ERROR);
            this.releaseVisualPreparation(run);
            return;
        }
        // Resource callbacks can be slow or ignore AbortSignal. Never let them revive old authority.
        if (!stillAuthorized()) {
            this.releaseVisualPreparation(run);
            return;
        }
        try {
            if (!stillAuthorized())
                return;
            this.effects.apply(run.effect);
            if (!stillAuthorized())
                return;
            const receipt = run.gate.consume(run.effect);
            if (receipt)
                this.enqueueFact(receipt, false, run.generation);
        }
        catch (error) {
            if (stillAuthorized())
                this.fail(error);
        }
        finally {
            this.releaseVisualPreparation(run);
        }
    }
    releaseVisualPreparation(run) {
        if (this.visualPreparations.get(run.effect.id) === run)
            this.visualPreparations.delete(run.effect.id);
    }
    cancelRevokedVisualPreparations() {
        for (const run of this.visualPreparations.values()) {
            if (run.generation !== this.generation || this.gate !== run.gate || !run.gate.allows(run.effect))
                run.abort.abort();
        }
    }
    cancelVisualPreparations() {
        // Keep uncooperative callbacks counted against the small cap until they actually settle.
        for (const run of this.visualPreparations.values())
            run.abort.abort();
    }
    /** Block and physically disconnect before any network cancellation or new request. */
    interrupt(reason) {
        const generation = ++this.generation;
        this.cancelVisualPreparations();
        this.rehearsalInput = null;
        this.view.rehearsalInput?.('stopped');
        this.gate?.block();
        const speech = this.speech;
        this.playback.stop(reason); // terminal fact is allocated before beginInput/stop captures cutoff
        speech?.abort.abort();
        speech?.wake?.();
        this.speech = null;
        const microphone = this.microphone;
        this.microphone = null;
        this.capture.stop();
        microphone?.abort.abort();
        microphone?.transport?.cancel();
        if (microphone) {
            microphone.queue.length = 0;
            microphone.queuedBytes = 0;
        }
        this.activityRequest?.abort();
        this.activityRequest = null;
        this.view.microphone?.('stopped');
        return generation;
    }
    unlock(generation) {
        this.unlocked = false;
        void this.playback.unlock().then(ok => {
            if (!this.current(generation))
                return;
            this.unlocked = ok;
            if (ok)
                this.startSpeech();
            else
                this.view.error('Audio could not start. Text input is still available; try again from a user gesture.');
        }).catch(error => { if (this.current(generation))
            this.report(error); });
    }
    async input(text) {
        if (!this.gate || this.closed || !text.trim())
            return;
        const generation = this.interrupt('new-input');
        this.reportedError = null;
        this.view.error('');
        const id = crypto.randomUUID(), basis = this.gate.beginInput(id);
        this.effects.prepareInput();
        if (this.capabilities?.speech_enabled !== false)
            this.unlock(generation); // invoked in the gesture, never after a fetch/permission await
        const abort = new AbortController();
        this.activityRequest = abort;
        try {
            const snapshot = await this.api.input({ ...basis, request_id: id, text }, abort.signal);
            if (this.current(generation))
                this.install(snapshot);
        }
        catch (error) {
            if (this.current(generation))
                this.fail(error);
        }
    }
    async stop() {
        if (!this.gate || this.closed)
            return;
        const generation = this.interrupt('stop');
        this.reportedError = null;
        this.view.error('');
        const basis = this.gate.stop();
        this.effects.stop();
        this.view.localStop();
        const abort = new AbortController();
        this.activityRequest = abort;
        try {
            const snapshot = await this.api.stop(basis, abort.signal);
            if (this.current(generation))
                this.install(snapshot);
        }
        catch (error) {
            if (this.current(generation))
                this.fail(error);
        }
    }
    startSpeech() {
        const gate = this.gate;
        if (this.closed || !this.running || !this.unlocked || !this.capabilities?.speech_enabled
            || !gate || this.speech || this.microphone || this.rehearsalInput || !this.snapshot)
            return;
        const effect = this.snapshot.active_grants.find(value => value.kind === 'speech' && gate.allows(value));
        if (!effect || !gate.claimSpeech(effect))
            return;
        const run = { effect, generation: this.generation, abort: new AbortController(), handle: null, accepted: 0, rendered: 0, wake: null };
        this.speech = run;
        run.handle = this.playback.open(effect);
        if (!run.handle) {
            this.fail(new Error('Audio grant could not start. Use text input.'));
            return;
        }
        void this.api.speech(effect, run.abort.signal, async (pcm) => {
            // Read one packet at a time and pace it against naturally ended software samples.
            while (run.accepted - run.rendered + pcm.length > 96000) {
                if (!this.activeSpeech(run))
                    throw new Error('Speech cancelled');
                await new Promise(resolve => { run.wake = resolve; });
            }
            if (!this.activeSpeech(run) || !run.handle.push(pcm))
                throw new Error('Speech playback stopped');
            run.accepted += pcm.length;
        }).then(() => {
            if (this.activeSpeech(run) && !run.handle.finish())
                this.fail(new Error('Speech did not complete. Use text input.'));
        }).catch(error => { if (this.activeSpeech(run))
            this.fail(error); });
    }
    activeSpeech(run) {
        return this.speech === run && this.current(run.generation) && !run.abort.signal.aborted && this.gate?.isAuthorized(run.effect) === true;
    }
    playbackFact(fact) {
        const run = this.speech;
        const progress = this.gate?.audioProgress(fact);
        if (progress && !this.closed)
            this.enqueueFact(progress, true, run?.generation ?? this.generation);
        if (!run || run.effect.id !== fact.origin.id || run.effect.digest !== fact.origin.digest)
            return;
        if (fact.stage === 'rendered') {
            run.rendered = fact.renderedFrames;
            run.wake?.();
            run.wake = null;
        }
        if (fact.stage === 'submitted' && this.activeSpeech(run)) {
            if (this.gate?.submitSpeech(fact))
                this.presentVisuals();
            this.effects.setPhase?.('speaking');
        }
        if (fact.stage === 'completed' || fact.stage === 'stopped' || fact.stage === 'failed') {
            this.speech = null;
            run.abort.abort();
            run.wake?.();
            run.wake = null;
            if (!this.current(run.generation))
                return;
            this.effects.setPhase?.(this.microphone ? 'listening' : 'idle');
            if (fact.stage === 'failed' || fact.reason === 'error')
                this.fail(new Error('Audio failed. Text input is still available.'));
            else if (fact.stage === 'completed')
                queueMicrotask(() => { if (this.current(run.generation))
                    this.startSpeech(); });
        }
    }
    enqueueFact(fact, audio, generation = this.generation) {
        if (++this.pendingFacts > 4096) {
            this.pendingFacts--;
            this.fail(new Error('Presentation history delivery is full. Close and create a new session.'));
            return;
        }
        // Serialize facts so terminal audio cannot overtake a prior rendered counter.
        // New input/stop does not cancel established facts; its cutoff fences late delivery.
        this.facts = this.facts.then(async () => {
            if (this.closed)
                return;
            if (audio)
                await this.api.audioProgress(fact);
            else
                await this.api.receipt(fact);
        }).catch(error => {
            if (this.current(generation))
                this.fail(error);
            // Preserve the new activity's actionable failure/locator, if it has one.
            else if (!this.closed && this.reportedError === null)
                this.view.error('An earlier presentation fact could not be saved. History may be incomplete.');
        }).finally(() => { this.pendingFacts--; });
    }
    /** User-controlled fixed input rehearsal. No capture, STT, PCM input or speech-recognition claim. */
    async startRehearsalInput() {
        if (!this.gate || this.closed || this.rehearsalInput
            || this.capabilities?.generation_mode !== 'rehearsal'
            || this.capabilities.qualification !== 'offline_fixture')
            return;
        const generation = this.interrupt('new-input');
        this.reportedError = null;
        this.view.error('');
        const basis = this.gate.stop();
        this.effects.stop();
        this.effects.setPhase?.('listening');
        this.unlock(generation);
        const run = { generation, ready: Promise.resolve(), released: false };
        this.rehearsalInput = run;
        this.view.rehearsalInput?.('listening');
        const abort = new AbortController();
        this.activityRequest = abort;
        run.ready = this.api.stop(basis, abort.signal).then(snapshot => {
            if (!this.current(generation) || this.rehearsalInput !== run)
                return;
            if (snapshot.activity_seq !== basis.activity_seq)
                throw new Error('Rehearsal input was superseded');
            this.install(snapshot);
        }).catch(error => { if (this.current(generation) && this.rehearsalInput === run)
            this.fail(error); });
        await run.ready;
    }
    async finishRehearsalInput() {
        const run = this.rehearsalInput;
        if (!run || run.released || !this.current(run.generation))
            return;
        run.released = true;
        this.effects.setPhase?.('thinking');
        await run.ready;
        if (this.rehearsalInput !== run || !this.current(run.generation))
            return;
        this.rehearsalInput = null;
        this.view.rehearsalInput?.('stopped');
        await this.input('照片里有什么');
    }
    async startMicrophone() {
        if (!this.gate || this.closed || this.microphone)
            return;
        if (!this.capabilities?.microphone_enabled) {
            this.view.error('Microphone recognition is not configured. Use text input.');
            return;
        }
        const generation = this.interrupt('new-input');
        this.reportedError = null;
        this.view.error('');
        const basis = this.gate.stop();
        this.effects.prepareInput();
        this.unlock(generation);
        const run = { generation, abort: new AbortController(), queue: [], queuedBytes: 0,
            released: false, transport: null, setup: Promise.resolve(), finishing: null };
        this.microphone = run;
        this.activityRequest = run.abort;
        // Start capture synchronously under the user's gesture, before awaiting the stop acknowledgement.
        const starting = this.capture.start();
        run.setup = this.api.stop(basis, run.abort.signal).then(snapshot => {
            if (!this.activeMicrophone(run))
                return;
            if (snapshot.activity_seq !== basis.activity_seq)
                throw new Error('Microphone stop acknowledgement was superseded');
            this.install(snapshot);
            if (!this.activeMicrophone(run))
                return;
            const transport = this.api.microphone({ stream_id: crypto.randomUUID(), activity_seq: snapshot.activity_seq, input_epoch: snapshot.input_epoch }, run.abort.signal);
            run.transport = transport;
            void transport.completion.catch(error => { if (this.activeMicrophone(run))
                this.fail(error); });
            for (const chunk of run.queue)
                transport.send(chunk);
            run.queue.length = 0;
            run.queuedBytes = 0;
            return transport.ready;
        }).catch(error => { if (this.activeMicrophone(run))
            this.fail(error); });
        const started = await starting;
        if (!started && this.activeMicrophone(run) && !run.released)
            this.fail(new Error('Microphone did not start. Use text input.'));
    }
    activeMicrophone(run) {
        return this.microphone === run && this.current(run.generation) && !run.abort.signal.aborted;
    }
    captureChunk(chunk) {
        const run = this.microphone;
        if (!run || !this.activeMicrophone(run) || run.released)
            throw new Error('Microphone cancelled');
        if (run.transport) {
            run.transport.send(chunk);
            return;
        }
        if (run.queue.length >= 100 || run.queuedBytes + chunk.pcm16le.length > 65536)
            throw new Error('Microphone startup queue exceeded its bound');
        run.queue.push({ ...chunk, pcm16le: chunk.pcm16le.slice() });
        run.queuedBytes += chunk.pcm16le.length;
    }
    async finishMicrophone() {
        const run = this.microphone;
        if (!run || !this.activeMicrophone(run))
            return;
        if (run.finishing)
            return run.finishing;
        run.released = true;
        this.capture.stop();
        this.view.microphone?.('finishing');
        this.effects.setPhase?.('thinking');
        run.finishing = (async () => {
            await run.setup;
            if (!this.activeMicrophone(run) || !run.transport)
                return;
            const result = await run.transport.finish();
            if (!this.activeMicrophone(run))
                return;
            this.microphone = null;
            run.abort.abort();
            this.view.microphone?.('stopped');
            const text = result.text.trim();
            const noise = /^\[(?:noise|silence|inaudible|music|静音|噪音)\]$/i.test(text);
            if (!result.had_final || !text || noise || !/[\p{L}\p{N}]/u.test(text)) {
                this.effects.setPhase?.('idle');
                this.view.error('No reliable speech was recognized. Try again or use text input.');
                return;
            }
            await this.input(text);
        })().catch(error => { if (this.activeMicrophone(run))
            this.fail(error); });
        return run.finishing;
    }
    async poll() {
        if (!this.running || this.closed)
            return;
        const generation = this.generation, abort = new AbortController();
        this.pollRequest = abort;
        try {
            const snapshot = await this.api.snapshot(abort.signal);
            if (this.current(generation))
                this.install(snapshot);
        }
        catch (error) {
            if (this.current(generation))
                this.fail(error);
        }
        finally {
            if (this.pollRequest === abort)
                this.pollRequest = null;
            if (this.running && !this.closed)
                this.pollTimer = setTimeout(() => { this.pollTimer = null; void this.poll(); }, this.config.pollIntervalMs);
        }
    }
    report(error) {
        this.reportedError = error instanceof Error ? error.message : 'Transport unavailable. Use text input.';
        this.view.error(this.reportedError);
    }
    fail(error) {
        if (this.closed)
            return;
        this.interrupt('error');
        this.effects.stop();
        this.report(error);
    }
    close() {
        if (this.closePromise)
            return this.closePromise;
        this.closed = true;
        this.running = false;
        this.interrupt('close');
        this.effects.stop();
        this.lifetime.abort();
        this.pollRequest?.abort();
        this.pollRequest = null;
        if (this.pollTimer !== null) {
            clearTimeout(this.pollTimer);
            this.pollTimer = null;
        }
        this.closePromise = Promise.allSettled([this.capture.close(), this.playback.close(), this.api.close()]).then(results => {
            if (results.some(result => result.status === 'rejected'))
                this.view.error('Local resources closed; server cleanup could not be confirmed.');
        });
        return this.closePromise;
    }
}
//# sourceMappingURL=controller.js.map