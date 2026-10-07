import { initialSceneState } from './scene-state.js';
import './code-native-vendor/character.js';
import './code-native-vendor/camera-motion.js';
import './code-native-vendor/body.js';
import './code-native-vendor/hair.js';
import './code-native-vendor/expression.js';
export const CODE_NATIVE_SIZE = Object.freeze({ width: 288, height: 408 });
export const CODE_NATIVE_PHASES = Object.freeze({
    idle: 'idle', listening: 'listen', thinking: 'think', speaking: 'speak',
});
const sources = globalThis;
const FACE = sources.MiraCharacter;
const BODY = sources.MiraBody;
const HAIR = sources.MiraHairRefinement;
const EXPRESSIONS = sources.MiraExpression;
const abortError = () => Object.assign(new Error('Code-native preparation cancelled'), { name: 'AbortError' });
export function assertCodeNativeState(state) {
    if (!Object.hasOwn(CODE_NATIVE_PHASES, state.phase))
        throw new Error('Unsupported character phase');
    if (!['outfit_black_jacket', 'outfit_cream_inner_only', 'outfit_amber_raincoat'].includes(state.outfit)) {
        throw new Error('Unsupported code-native wardrobe');
    }
    if (state.expression !== 'calm' || !['emotion_normal', 'emotion_guarded', 'emotion_happy', 'emotion_shy'].includes(state.emotion)) {
        throw new Error('Code-native facial emotion unavailable');
    }
    if (!['camera_ready', 'camera_raise'].includes(state.action))
        throw new Error('Code-native camera/turn pose unavailable');
    if (!['accessory_camera_clip', 'accessory_star_clip'].includes(state.accessory))
        throw new Error('Code-native accessory unavailable');
}
/** Pure composition: expression/blink first, then bounded semantic yaw and shoulder projection. */
export function composeCodeNativeScene(state, seconds, running, cameraLift = String(state.action) === 'camera_raise' ? 1 : 0, phaseWeights, allowGesture = true, gestureWeight = 1, lipWeights, articulation) {
    assertCodeNativeState(state);
    const pose = FACE.stateAt(CODE_NATIVE_PHASES[state.phase], Number.isFinite(seconds) ? Math.max(0, seconds) : 0, running, { phaseWeights: phaseWeights ?? { [CODE_NATIVE_PHASES[state.phase]]: 1 }, emotion: state.emotion.slice('emotion_'.length), ...(lipWeights ? { lipWeights } : {}), ...(articulation ? { yaw: articulation.yaw } : {}) });
    // Explicit/partial camera actions own the assembly. Ambient gestures must
    // never add hidden displacement that vanishes on Stop or page suspension.
    if (!allowGesture || cameraLift > 0) {
        pose['gesture'] = 0;
        pose['breathGrip'] = 0;
    }
    else
        for (const key of ['gesture', 'breathGrip'])
            pose[key] = Number(pose[key]) * Math.max(0, Math.min(1, gestureWeight));
    pose['effectiveCameraLift'] = cameraLift + (1 - cameraLift) * (Number(pose['gesture']) + Number(pose['breathGrip']));
    const face = FACE.scene(pose);
    const rear = face.layers.find(node => node.id === 'rear-hair-rig');
    const neck = face.layers.find(node => node.id === 'neck-rig');
    const head = face.layers.find(node => node.id === 'head-rig');
    if (!rear || !neck || !head)
        throw new Error('Code-native source layer contract changed');
    if (rear.transform !== head.transform || neck.transform !== head.transform)
        throw new Error('Code-native anatomy matrices changed');
    const body = BODY.bodyLayers({ ...pose, outfit: state.outfit.slice('outfit_'.length), cameraLift, rigidGrip: true, reducedMotion: !running }, FACE.palette);
    // Record the actual authored grip matrix, so lifecycle tests can inspect the
    // physical drawing rather than only a controller's nominal progress.
    pose['cameraTransform'] = body.front.flatMap(node => node.children ?? []).find(node => node.id === 'camera-rig')?.transform ?? '';
    if (body.width !== CODE_NATIVE_SIZE.width || body.height !== CODE_NATIVE_SIZE.height
        || body.layout.originX !== 18 || body.layout.originY !== 0)
        throw new Error('Code-native layout contract changed');
    const layout = { id: 'composition-layout', type: 'group', transform: 'translate(18 0)',
        children: [...body.back, rear, ...body.underNeck, neck, ...body.front, head] };
    const refined = HAIR.apply({ layers: [layout],
        palette: FACE.palette, width: body.width, height: body.height }, pose);
    const geometry = EXPRESSIONS.apply(refined, pose, { emotion: state.emotion.slice('emotion_'.length), accessory: state.accessory.slice('accessory_'.length), ...(lipWeights ? { lipWeights, weights: lipWeights } : {}) });
    // Each frame contains newly articulated paths; only the renderer's endpoint copy
    // completes transitionState. Camera motion never crossfades complete sprites.
    const articulated = FACE.articulate({ ...refined, layers: geometry.layers }, pose);
    return { layers: articulated.layers, pose };
}
function transform(context, value = '') {
    const expression = /(translate|rotate|scale)\(([^)]+)\)/g;
    let match;
    while ((match = expression.exec(value))) {
        const args = match[2].trim().split(/[ ,]+/).map(Number);
        if (!args.length || !args.every(Number.isFinite))
            throw new Error('Invalid character transform');
        if (match[1] === 'translate')
            context.translate(args[0], args[1] ?? 0);
        else if (match[1] === 'scale')
            context.scale(args[0], args[1] ?? args[0]);
        else {
            if (args.length === 3)
                context.translate(args[1], args[2]);
            context.rotate(args[0] * Math.PI / 180);
            if (args.length === 3)
                context.translate(-args[1], -args[2]);
        }
    }
}
/** Single visual clock; never owns audio, authorization or presented-history receipts. */
class CodeNativeCharacterRenderer {
    host;
    options;
    current = initialSceneState();
    seconds = 0;
    lastTimestamp = null;
    frame = null;
    epoch = 0;
    destroyed = false;
    drawingFailed = false;
    stopped = false;
    paused = false;
    reducedMotion = false;
    hidden = false;
    canvas;
    staging;
    context;
    stagingContext;
    paths = new Map();
    document;
    media;
    request;
    cancel;
    path;
    lastPose = {};
    phaseWeights = { idle: 1, listen: 0, think: 0, speak: 0 };
    lipWeights = { normal: 1, guarded: 0, happy: 0, shy: 0 };
    nextLipWeights(delta) {
        if (this.emotionMotion) {
            const motion = this.emotionMotion, t = Math.min(1, (motion.elapsed + delta * 1000) / motion.duration), ease = t * t * (3 - 2 * t);
            const target = motion.target.slice('emotion_'.length);
            return Object.fromEntries(Object.keys(motion.from).map(key => [key, motion.from[key] + ((key === target ? 1 : 0) - motion.from[key]) * ease]));
        }
        const target = (this.motion?.state ?? this.current).emotion.slice('emotion_'.length);
        const amount = 1 - Math.exp(-Math.max(0, delta) / .14);
        return Object.fromEntries(Object.keys(this.lipWeights).map(key => [key,
            this.lipWeights[key] + ((key === target ? 1 : 0) - this.lipWeights[key]) * amount]));
    }
    neutralLipWeights() {
        const target = this.current.emotion.slice('emotion_'.length);
        this.lipWeights = Object.fromEntries(Object.keys(this.lipWeights).map(key => [key, key === target ? 1 : 0]));
    }
    nextPhaseWeights(delta) {
        const target = CODE_NATIVE_PHASES[(this.motion?.state ?? this.current).phase];
        const amount = 1 - Math.exp(-Math.max(0, delta) / .16);
        return Object.fromEntries(Object.keys(this.phaseWeights).map(key => [key,
            this.phaseWeights[key] + ((key === target ? 1 : 0) - this.phaseWeights[key]) * amount]));
    }
    cameraLift = 0;
    cameraGestureLocked = false;
    gestureReturn = 1;
    releaseReadyGesture() {
        this.cameraGestureLocked = false;
        this.gestureReturn = 0;
    }
    motionTarget = 'camera_ready';
    motionStatus = 'idle';
    motion = null;
    emotionStatus = 'idle';
    emotionProgress = 0;
    emotionTarget = 'emotion_normal';
    emotionMotion = null;
    getEmotionMotionState() {
        return { target: this.emotionTarget, progress: this.emotionProgress, status: this.emotionStatus };
    }
    clearEmotion() {
        if (!this.emotionMotion)
            return;
        clearTimeout(this.emotionMotion.deadline);
        for (const [signal, listener] of this.emotionMotion.listeners)
            signal.removeEventListener('abort', listener);
        this.emotionMotion = null;
    }
    cancelEmotion(error = abortError()) {
        const motion = this.emotionMotion;
        if (!motion)
            return;
        this.clearEmotion();
        this.emotionStatus = 'cancelled';
        this.invalidate();
        motion.reject(error);
        this.schedule();
    }
    watchEmotion(signal) {
        if (!this.emotionMotion || this.emotionMotion.listeners.has(signal))
            return;
        const cancel = () => this.cancelEmotion();
        this.emotionMotion.listeners.set(signal, cancel);
        signal.addEventListener('abort', cancel, { once: true });
    }
    transitionEmotion(state, signal) {
        if (this.emotionMotion?.target === state.emotion) {
            this.watchEmotion(signal);
            return this.emotionMotion.promise;
        }
        this.cancelEmotion();
        const target = state.emotion.slice('emotion_'.length);
        const goal = Object.fromEntries(Object.keys(this.lipWeights).map(key => [key, key === target ? 1 : 0]));
        this.emotionTarget = state.emotion;
        if (this.reducedMotion || Object.keys(goal).every(key => Math.abs(goal[key] - this.lipWeights[key]) < 1e-9)) {
            this.commit(state, !this.reducedMotion && this.running(), this.cameraLift, this.phaseWeights, this.gestureReturn, goal);
            this.lipWeights = goal;
            this.current = { ...this.current, emotion: state.emotion };
            if (this.motion)
                this.motion.state = { ...this.motion.state, emotion: state.emotion };
            this.emotionStatus = 'completed';
            this.emotionProgress = 1;
            this.schedule();
            return Promise.resolve(true);
        }
        let resolve, reject;
        const promise = new Promise((accept, decline) => { resolve = accept; reject = decline; });
        this.emotionMotion = { target: state.emotion, from: { ...this.lipWeights }, elapsed: 0, duration: 550, promise, resolve, reject, listeners: new Map(),
            deadline: setTimeout(() => this.cancelEmotion(new Error('Emotion motion frame deadline exceeded')), 5000) };
        this.emotionStatus = 'running';
        this.emotionProgress = 0;
        this.watchEmotion(signal);
        this.stopped = false;
        this.paused = false;
        this.lastTimestamp = null;
        this.schedule();
        return promise;
    }
    getMotionState() {
        return { progress: this.cameraLift, target: this.motionTarget, status: this.motionStatus };
    }
    clearMotion() {
        if (!this.motion)
            return;
        clearTimeout(this.motion.deadline);
        for (const [signal, listener] of this.motion.listeners)
            signal.removeEventListener('abort', listener);
        this.motion = null;
    }
    cancelMotion(error = abortError(), stopAnimation = true) {
        const motion = this.motion;
        if (!motion)
            return;
        this.clearMotion();
        this.motionStatus = 'cancelled';
        if (stopAnimation)
            this.stopped = true;
        this.invalidate();
        motion.reject(error);
    }
    watchMotion(signal) {
        if (!this.motion || this.motion.listeners.has(signal))
            return;
        const cancel = () => this.cancelMotion();
        this.motion.listeners.set(signal, cancel);
        signal.addEventListener('abort', cancel, { once: true });
    }
    transitionState(state, signal, kind = 'camera') {
        if (this.destroyed || signal.aborted || this.options.signal?.aborted)
            return Promise.reject(abortError());
        if (this.drawingFailed)
            return Promise.reject(new Error('Code-native drawing unavailable'));
        if (this.hidden)
            return Promise.reject(new Error('Character review is hidden'));
        assertCodeNativeState(state);
        if (kind === 'emotion')
            return this.transitionEmotion(state, signal);
        const target = String(state.action) === 'camera_raise' ? 1 : 0;
        if (this.motion?.to === target) {
            this.motion.state = { ...state };
            this.watchMotion(signal);
            return this.motion.promise;
        }
        this.cancelMotion();
        // Take over the last successful drawing, including an ambient hand lift.
        // This prevents a start/cancel pop and keeps cancelled partial poses fixed.
        this.cameraLift = Number(this.lastPose['effectiveCameraLift'] ?? this.cameraLift);
        this.cameraGestureLocked = true;
        this.gestureReturn = 0;
        if (this.reducedMotion || target === this.cameraLift) {
            this.commit(state, false, target);
            this.cameraLift = target;
            this.current = { ...state };
            this.motionTarget = target ? 'camera_raise' : 'camera_ready';
            this.motionStatus = 'completed';
            if (target === 0)
                this.releaseReadyGesture();
            this.schedule();
            return Promise.resolve(true);
        }
        let resolve, reject;
        const promise = new Promise((accept, decline) => { resolve = accept; reject = decline; });
        this.motionTarget = target ? 'camera_raise' : 'camera_ready';
        this.motionStatus = 'running';
        this.motion = { state: { ...state }, from: this.cameraLift, to: target, elapsed: 0,
            duration: 1000 * Math.abs(target - this.cameraLift), promise, resolve, reject, listeners: new Map(),
            deadline: setTimeout(() => this.cancelMotion(new Error('Camera motion frame deadline exceeded')), 5000) };
        this.watchMotion(signal);
        this.stopped = false;
        this.paused = false;
        this.lastTimestamp = null;
        this.schedule();
        return promise;
    }
    constructor(host, options) {
        this.host = host;
        this.options = options;
        this.document = options.document ?? host.ownerDocument ?? globalThis.document;
        const window = options.window ?? this.document.defaultView ?? globalThis.window;
        const create = options.createCanvas ?? (() => this.document.createElement('canvas'));
        this.canvas = create();
        this.staging = create();
        for (const canvas of [this.canvas, this.staging]) {
            canvas.width = CODE_NATIVE_SIZE.width;
            canvas.height = CODE_NATIVE_SIZE.height;
        }
        this.canvas.className = 'mira-code-native-canvas';
        this.canvas.setAttribute('aria-label', 'MIRA 代码角色审阅草稿，外观未经认可');
        const context = this.canvas.getContext('2d');
        const stagingContext = this.staging.getContext('2d');
        if (!context || !stagingContext)
            throw new Error('Canvas2D unavailable');
        this.context = context;
        this.stagingContext = stagingContext;
        this.context.imageSmoothingEnabled = false;
        this.stagingContext.imageSmoothingEnabled = false;
        this.path = options.createPath ?? (data => new Path2D(data));
        this.request = options.requestAnimationFrame ?? (callback => window.requestAnimationFrame(callback));
        this.cancel = options.cancelAnimationFrame ?? (handle => window.cancelAnimationFrame(handle));
        this.hidden = this.document.visibilityState === 'hidden';
        this.media = window.matchMedia?.('(prefers-reduced-motion: reduce)');
        this.reducedMotion = this.media?.matches ?? false;
        this.document.addEventListener('visibilitychange', this.visibilityChanged);
        this.media?.addEventListener('change', this.motionChanged);
        options.signal?.addEventListener('abort', this.destroy, { once: true });
        try {
            this.commit(this.current);
            this.host.appendChild(this.canvas);
            this.host.dataset['renderer'] = 'code-native-review';
            this.host.dataset['visualAcceptance'] = 'pending';
            this.schedule();
        }
        catch (error) {
            this.destroy();
            throw error;
        }
    }
    failDrawing() {
        this.host.dataset['rendererError'] = 'drawing-failed';
        this.drawingFailed = true;
        this.cancelEmotion(new Error('Emotion motion drawing failed'));
        this.cancelMotion(new Error('Camera motion drawing failed'));
        this.stopped = true;
        this.invalidate();
    }
    running() { return !this.drawingFailed && !this.destroyed && !this.stopped && !this.paused && !this.hidden && !this.reducedMotion; }
    invalidate() {
        this.epoch++;
        if (this.frame !== null)
            this.cancel(this.frame);
        this.frame = null;
        this.lastTimestamp = null;
    }
    visibilityChanged = () => {
        this.hidden = this.document.visibilityState === 'hidden';
        if (this.hidden) {
            this.cancelEmotion();
            this.cancelMotion(abortError(), false);
        }
        this.invalidate();
        // Visibility suspends the current phase; it never releases Stop or explicit Pause.
        // Camera completion remains cancelled, even when ambient motion can resume.
        this.drawNeutral();
        this.schedule();
    };
    motionChanged = (event) => {
        this.reducedMotion = event.matches;
        this.cancelEmotion();
        this.cancelMotion(abortError(), false);
        this.invalidate();
        this.drawNeutral();
        this.schedule();
    };
    drawNeutral() {
        if (this.destroyed || this.drawingFailed)
            return;
        try {
            this.neutralLipWeights();
            this.commit(this.current, false);
        }
        catch {
            this.failDrawing();
        }
    }
    drawNode(context, node) {
        context.save();
        try {
            transform(context, node.transform);
            if (node.opacity !== undefined) {
                if (!Number.isFinite(node.opacity))
                    throw new Error('Invalid character opacity');
                context.globalAlpha *= node.opacity;
            }
            if (node.clip)
                context.clip(this.getPath(node.clip));
            if (node.type === 'group')
                for (const child of node.children ?? [])
                    this.drawNode(context, child);
            else {
                context.fillStyle = node.fill;
                context.fill(this.getPath(node.d), node.fillRule ?? 'nonzero');
            }
        }
        finally {
            context.restore();
        }
    }
    getPath(data) {
        if (typeof data !== 'string' || /NaN|Infinity/.test(data))
            throw new Error('Invalid character path');
        let path = this.paths.get(data);
        if (!path) {
            path = this.path(data);
            // Mouth paths change per frame. Keep a bounded cache rather than growing forever.
            if (this.paths.size > 768)
                this.paths.clear();
            this.paths.set(data, path);
        }
        return path;
    }
    stage(state, running = this.running(), cameraLift = this.cameraLift, phaseWeights = this.phaseWeights, gestureReturn = this.gestureReturn, lipWeights = this.lipWeights) {
        const scene = composeCodeNativeScene(state, this.seconds, running, cameraLift, phaseWeights, !this.cameraGestureLocked, gestureReturn * gestureReturn * (3 - 2 * gestureReturn), running ? lipWeights : undefined);
        this.stagingContext.clearRect(0, 0, CODE_NATIVE_SIZE.width, CODE_NATIVE_SIZE.height);
        for (const node of scene.layers)
            this.drawNode(this.stagingContext, node);
        return scene.pose;
    }
    commit(state, running = this.running(), cameraLift = this.cameraLift, phaseWeights = this.phaseWeights, gestureReturn = this.gestureReturn, lipWeights = this.lipWeights) {
        const visualState = this.emotionMotion ? { ...state, emotion: this.emotionMotion.target } : state;
        const pose = this.stage(visualState, running, cameraLift, phaseWeights, gestureReturn, lipWeights);
        this.context.save();
        try {
            // One full-frame copy replaces transparency atomically; no visible pre-clear.
            this.context.globalCompositeOperation = 'copy';
            this.context.drawImage(this.staging, 0, 0);
        }
        finally {
            this.context.restore();
        }
        this.lastPose = pose;
    }
    schedule() {
        if (!this.running() || this.frame !== null)
            return;
        const epoch = this.epoch;
        this.frame = this.request(timestamp => {
            if (this.destroyed || epoch !== this.epoch || !this.running())
                return;
            this.frame = null;
            const safeTimestamp = Number.isFinite(timestamp) ? timestamp : 0;
            const delta = this.lastTimestamp === null ? 0 : Math.min(.1, Math.max(0, (safeTimestamp - this.lastTimestamp) / 1000));
            this.seconds += delta;
            this.lastTimestamp = safeTimestamp;
            try {
                const motion = this.motion;
                const emotion = this.emotionMotion;
                const phaseWeights = this.nextPhaseWeights(delta);
                const lipWeights = this.nextLipWeights(delta);
                const gestureReturn = this.cameraGestureLocked ? 0 : Math.min(1, this.gestureReturn + delta / .45);
                if (motion) {
                    const elapsed = Math.min(motion.duration, motion.elapsed + delta * 1000);
                    const linear = elapsed / motion.duration, eased = linear * linear * (3 - 2 * linear);
                    const progress = motion.from + (motion.to - motion.from) * eased;
                    this.commit(motion.state, true, progress, phaseWeights, gestureReturn, lipWeights);
                    // Only the successful visible copy advances physical progress.
                    this.cameraLift = progress;
                    motion.elapsed = elapsed;
                    if (linear >= 1) {
                        this.current = { ...motion.state };
                        this.clearMotion();
                        this.motionStatus = 'completed';
                        if (motion.to === 0)
                            this.releaseReadyGesture();
                        motion.resolve(true);
                    }
                }
                else
                    this.commit(this.current, this.running(), this.cameraLift, phaseWeights, gestureReturn, lipWeights);
                // Advance the blend only after a successful visible copy. Retargeting
                // starts from these weights, so rapid phase changes never snap or queue.
                this.phaseWeights = phaseWeights;
                this.gestureReturn = gestureReturn;
                this.lipWeights = lipWeights;
                if (emotion && this.emotionMotion === emotion) {
                    emotion.elapsed = Math.min(emotion.duration, emotion.elapsed + delta * 1000);
                    this.emotionProgress = emotion.elapsed / emotion.duration;
                    if (emotion.elapsed >= emotion.duration) {
                        // The fully weighted target was included in the successful visible
                        // copy above. Only now may the controller record emotion completion.
                        this.current = { ...this.current, emotion: emotion.target };
                        if (this.motion)
                            this.motion.state = { ...this.motion.state, emotion: emotion.target };
                        this.clearEmotion();
                        this.emotionStatus = 'completed';
                        emotion.resolve(true);
                    }
                }
            }
            catch {
                this.failDrawing();
                return;
            }
            this.schedule();
        });
    }
    async prepareState(state, signal) {
        if (this.destroyed || signal.aborted || this.options.signal?.aborted)
            throw abortError();
        if (this.hidden)
            throw new Error('Character review is hidden');
        if (this.drawingFailed)
            throw new Error('Code-native drawing unavailable');
        const epoch = this.epoch;
        this.stage(state, this.running(), String(state.action) === 'camera_raise' ? 1 : 0);
        await Promise.resolve();
        if (this.destroyed || signal.aborted || this.options.signal?.aborted || epoch !== this.epoch)
            throw abortError();
        return true;
    }
    render(state) {
        if (this.destroyed || this.drawingFailed)
            throw new Error('Code-native renderer unavailable');
        assertCodeNativeState(state);
        const changedPhase = state.phase !== this.current.phase;
        const restart = changedPhase && state.phase !== 'idle';
        // Commit can fail; do not advance logical state or the animation clock first.
        this.commit(state, restart ? !this.hidden && !this.reducedMotion : this.running());
        this.current = { ...state };
        // Phase/subtitle changes during motion remain current at the terminal frame.
        if (this.motion)
            this.motion.state = { ...state, action: this.motion.state.action };
        if (restart) {
            this.stopped = false;
            this.paused = false;
        }
        if (changedPhase)
            this.lastTimestamp = null;
        this.schedule();
    }
    stop() {
        if (this.destroyed)
            return;
        this.cancelEmotion();
        this.cancelMotion();
        this.invalidate();
        this.stopped = true;
        this.seconds = 0;
        this.current = { ...this.current, phase: 'idle' };
        this.phaseWeights = { idle: 1, listen: 0, think: 0, speak: 0 };
        this.neutralLipWeights();
        if (this.drawingFailed)
            return;
        this.commit(this.current, false);
    }
    setPaused(paused) {
        if (this.destroyed || this.drawingFailed)
            return;
        if (paused) {
            this.cancelEmotion();
            this.cancelMotion();
        }
        this.invalidate();
        this.paused = paused;
        if (paused) {
            this.neutralLipWeights();
            this.commit(this.current, false);
        }
        else
            this.schedule();
    }
    getStatus() {
        return { mode: 'code-native-review', visualAcceptance: 'pending',
            warnings: ['局部二维动作与情绪待视觉认可；讲话口型仅为周期阶段示意，未连接PCM或音素同步。'],
            phase: this.current.phase, running: this.running(), seconds: this.seconds, mouth: Number(this.lastPose['mouth'] ?? 0),
            head: Number(this.lastPose['head'] ?? 0), yaw: Number(this.lastPose['yaw'] ?? 0), shoulderFollow: Number(this.lastPose['shoulderFollow'] ?? 0), shoulderRaise: Number(this.lastPose['shoulderRaise'] ?? 0), listeningLean: Number(this.lastPose['listeningLean'] ?? 0), gesture: Number(this.lastPose['gesture'] ?? 0), cameraTransform: String(this.lastPose['cameraTransform'] ?? ''), lipWeights: { ...this.lipWeights } };
    }
    destroy = () => {
        if (this.destroyed)
            return;
        this.cancelEmotion();
        this.cancelMotion();
        this.destroyed = true;
        this.invalidate();
        this.document.removeEventListener('visibilitychange', this.visibilityChanged);
        this.media?.removeEventListener('change', this.motionChanged);
        this.options.signal?.removeEventListener('abort', this.destroy);
        this.canvas.remove();
        this.paths.clear();
        delete this.host.dataset['renderer'];
        delete this.host.dataset['visualAcceptance'];
    };
}
export async function createCodeNativeCharacterRenderer(host, options = {}) {
    if (options.signal?.aborted)
        return null;
    return new CodeNativeCharacterRenderer(host, options);
}
