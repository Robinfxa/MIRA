"use strict";
/* MIRA semantic expression and hair-accessory layer.
 * All drawing geometry is editable code. No production raster inputs.
 * Attach AFTER the face/body scene has been assembled. The baseline is never mutated.
 * Normal + camera is an exact identity operation, including all baseline path strings.
 */
(function (root) {
    'use strict';
    const EMOTIONS = Object.freeze(['normal', 'guarded', 'happy', 'shy']);
    const ACCESSORIES = Object.freeze(['camera_clip', 'star_clip']);
    const clamp = (v, lo = 0, hi = 1) => Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : lo;
    const safeEmotion = v => EMOTIONS.includes(v) ? v : 'normal';
    const safeAccessory = v => ACCESSORIES.includes(v) ? v : 'camera_clip';
    const ZERO = Object.freeze({ browLY: 0, browRY: 0, browLTilt: 0, browRTilt: 0, eyeLSqueeze: 0, eyeRSqueeze: 0, eyeLY: 0, eyeRY: 0, gazeX: 0, gazeY: 0, mouthWidth: 0, mouthCompress: 0, mouthCorners: 0, mouthY: 0, blush: 0 });
    // Values are deltas from the face owner's current anatomy, in reference coordinates.
    // Brow tilt raises/lowers INNER ends oppositely; eye squeeze changes the eyelid aperture
    // and its stationary iris clip, while the gaze is translated inside that clip.
    const POSES = Object.freeze({
        normal: ZERO,
        guarded: Object.freeze({ ...ZERO, browLY: 2, browRY: 3, browLTilt: .38, browRTilt: -.37, eyeLSqueeze: .44, eyeRSqueeze: .42, eyeLY: 1.3, eyeRY: .6, gazeX: 6.5, gazeY: -.6, mouthWidth: -.05, mouthCompress: .76, mouthCorners: 5.8, mouthY: 1, blush: -.035 }),
        happy: Object.freeze({ ...ZERO, browLY: -14, browRY: -13, browLTilt: -.10, browRTilt: .09, eyeLSqueeze: -.08, eyeRSqueeze: -.06, eyeLY: -3.2, eyeRY: -2.8, gazeX: 0, gazeY: -1.5, mouthWidth: .23, mouthCompress: -.10, mouthCorners: -18, mouthY: .3, blush: .10 }),
        shy: Object.freeze({ ...ZERO, browLY: -2.2, browRY: -1.8, browLTilt: -.40, browRTilt: .38, eyeLSqueeze: .50, eyeRSqueeze: .44, eyeLY: 2.2, eyeRY: 2.0, gazeX: -16, gazeY: 14, mouthWidth: -.27, mouthCompress: .48, mouthCorners: -8.8, mouthY: 1.6, blush: .19 })
    });
    const EYES = Object.freeze({
        'left-eye': Object.freeze({ cx: 465.5, cy: 330, angle: -9, browX: 446 }),
        'right-eye': Object.freeze({ cx: 577, cy: 285, angle: -25, browX: 540 })
    });
    const REQUIRED = ['face-reference-fit', 'left-brow', 'right-brow', 'reference-lips', 'upper-lip', 'mouth-cavity', 'lower-lip', 'lower-lip-shade', 'lip-highlight', ...Object.keys(EYES).flatMap(id => ['open', 'sclera', 'iris-clip', 'gaze', 'upper-lid', 'lower-lid', 'eyelashes', 'closed-lid'].map(s => id + '-' + s))];
    const round = v => { const n = Math.round(v * 1000000) / 1000000; return Object.is(n, -0) ? 0 : n; };
    function weightsFor(controls = {}) {
        const amount = controls.intensity === undefined ? 1 : clamp(Number(controls.intensity));
        const w = { normal: 0, guarded: 0, happy: 0, shy: 0 };
        if (controls.weights) {
            for (const emotion of EMOTIONS)
                w[emotion] = clamp(Number(controls.weights[emotion]));
            const total = Object.values(w).reduce((sum, v) => sum + v, 0);
            if (total > 0)
                for (const emotion of EMOTIONS)
                    w[emotion] /= total;
            else
                w.normal = 1;
        }
        else if (controls.transition) {
            const t = clamp(Number(controls.transition.progress));
            const ease = t * t * (3 - 2 * t);
            w[safeEmotion(controls.transition.from)] += 1 - ease;
            w[safeEmotion(controls.transition.to)] += ease;
        }
        else
            w[safeEmotion(controls.emotion)] = 1;
        for (const key of EMOTIONS)
            w[key] *= amount;
        w.normal += 1 - amount;
        return w;
    }
    function parameters(controls = {}) {
        const w = weightsFor(controls), p = { ...ZERO };
        for (const emotion of EMOTIONS)
            for (const key of Object.keys(p))
                p[key] += POSES[emotion][key] * w[emotion];
        return p;
    }
    function sampleTransition(from, to, progress, intensity = 1) {
        return parameters({ intensity, transition: { from, to, progress } });
    }
    function indexNodes(scene) {
        const result = new Map();
        function visit(n) { if (result.has(n.id))
            throw new Error('Duplicate semantic node: ' + n.id); result.set(n.id, n); if (n.children)
            n.children.forEach(visit); }
        (scene.layers || []).forEach(visit);
        return result;
    }
    function assertSeam(scene, { emotion = true, accessory = true } = {}) {
        const nodes = indexNodes(scene), required = [...(emotion ? REQUIRED : []), ...(accessory ? ['camera-hair-clip'] : [])];
        const missing = required.filter(id => !nodes.has(id));
        if (missing.length)
            throw new Error('MIRA expression seam is missing: ' + missing.join(', '));
        return nodes;
    }
    // The current face contract uses absolute M/L/Q/C/S/T/Z paths. Preserve command
    // topology and deform their editable control points continuously. Unsupported paths
    // fail explicitly; this is not a raster warp or an automatic tracing operation.
    function mapPath(d, mapper) {
        if (/[a-zAHV]/.test(d))
            throw new Error('Expression paths require absolute paired-coordinate commands');
        const tokens = d.match(/[MLQCSTZ]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?/g) || [];
        let out = [], command = null, point = [];
        for (const token of tokens) {
            if (/^[MLQCSTZ]$/.test(token)) {
                if (point.length)
                    throw new Error('Unpaired expression path coordinate');
                command = token;
                out.push(token);
                continue;
            }
            if (!command || command === 'Z')
                throw new Error('Invalid expression path command');
            point.push(Number(token));
            if (point.length === 2) {
                const next = mapper(point[0], point[1]);
                out.push(String(round(next[0])), String(round(next[1])));
                point = [];
            }
        }
        if (point.length)
            throw new Error('Unpaired expression path coordinate');
        return out.join(' ');
    }
    function apertureMapper(eye, squeeze, shift) {
        const a = eye.angle * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
        return (x, y) => {
            const dx = x - eye.cx, dy = y - eye.cy, u = dx * c + dy * s, v = -dx * s + dy * c;
            const vv = v * (1 - squeeze) + shift;
            return [eye.cx + u * c - vv * s, eye.cy + u * s + vv * c];
        };
    }
    function applyEmotion(nodes, p, lip = p) {
        for (const [id, eye] of Object.entries(EYES)) {
            const left = id === 'left-eye', side = left ? 'L' : 'R';
            const brow = nodes.get(left ? 'left-brow' : 'right-brow');
            brow.d = mapPath(brow.d, (x, y) => [x, y + p['brow' + side + 'Y'] + (x - eye.browX) * p['brow' + side + 'Tilt']]);
            const mapper = apertureMapper(eye, p['eye' + side + 'Squeeze'], p['eye' + side + 'Y']);
            for (const part of ['sclera', 'upper-lid', 'lower-lid', 'eyelashes', 'closed-lid']) {
                const n = nodes.get(id + '-' + part);
                n.d = mapPath(n.d, mapper);
            }
            // The aperture and clip are deformed together. Gaze never moves the clip.
            nodes.get(id + '-iris-clip').clip = nodes.get(id + '-sclera').d;
            const gaze = nodes.get(id + '-gaze');
            gaze.transform = (gaze.transform ? gaze.transform + ' ' : '') + `translate(${round(p.gazeX)} ${round(p.gazeY)})`;
        }
        const mouthMapper = (x, y) => [x * (1 + lip.mouthWidth), y * (1 - lip.mouthCompress) + lip.mouthY + lip.mouthCorners * Math.pow(Math.min(1, Math.abs(x) / 35), 2)];
        // The source lip paths already include state.mouth. Deforming their live geometry
        // preserves speaking amplitude; no static expression mouth covers the live one.
        for (const id of ['upper-lip', 'mouth-cavity', 'lower-lip', 'lower-lip-shade', 'lip-highlight', ...(nodes.has('smile-upper-teeth') ? ['smile-upper-teeth'] : [])]) {
            const n = nodes.get(id);
            n.d = mapPath(n.d, mouthMapper);
        }
        if (nodes.has('smile-teeth-clip'))
            nodes.get('smile-teeth-clip').clip = nodes.get('mouth-cavity').d;
        for (const id of ['left-cheek-blush', 'right-cheek-blush']) {
            const n = nodes.get(id);
            if (n)
                n.opacity = round(clamp((n.opacity ?? 1) + p.blush));
        }
    }
    function starClipChildren(palette = {}) {
        const color = (key, fallback) => palette[key] || fallback;
        const path = (id, d, fill) => ({ id, type: 'path', d, fill });
        // Shared camera mount origin and scale: an actual pin/backplate, five-point star,
        // silver metal face, a bevel and a cool-white glint. Each part is editable.
        return [
            path('star-clip-pin', 'M-9 -1 L9 -1 10 1 9 3 -9 3 -10 1Z', '#68747c'),
            path('star-clip-outline', 'M0 -11 L3.7 -3.8 11.7 -2.6 5.9 3.1 7.4 11 -0 7.2 -7.4 11 -5.9 3.1 -11.7 -2.6 -3.7 -3.8Z', color('ink', '#211b22')),
            path('star-clip-silver', 'M0 -9.4 L3.1 -2.8 9.7 -1.8 4.8 3 6.0 9.0 0 5.9 -6.0 9.0 -4.8 3 -9.7 -1.8 -3.1 -2.8Z', color('silver', '#acb7bb')),
            path('star-clip-face', 'M0 -5.9 L2.0 -1.6 6.8 -.9 3.3 2.4 4.1 6.8 0 4.5 -4.1 6.8 -3.3 2.4 -6.8 -.9 -2.0 -1.6Z', '#dce5e8'),
            path('star-clip-bevel', 'M0 -9.4 L0 -5.9 -2.0 -1.6 -6.8 -.9 -3.3 2.4 -4.1 6.8 -6.0 9.0 -4.8 3 -9.7 -1.8 -3.1 -2.8Z', '#f3fafc'),
            path('star-clip-center', 'M-1.2 -.4 L.4 -.4 1.1 1.1 .1 2.3 -1.5 1.5Z', '#ffffff')
        ];
    }
    function apply(scene, state = {}, controls = {}) {
        const choice = { emotion: controls.emotion ?? state.emotion, accessory: controls.accessory ?? state.accessory, intensity: controls.intensity ?? state.emotionIntensity, transition: controls.transition ?? state.emotionTransition, weights: controls.weights ?? state.emotionWeights };
        const p = parameters(choice), lip = controls.lipWeights ? parameters({ weights: controls.lipWeights }) : p, active = [...Object.values(p), ...Object.values(lip)].some(v => v !== 0), star = safeAccessory(choice.accessory) === 'star_clip';
        if (!active && !star)
            return scene;
        assertSeam(scene, { emotion: active, accessory: star });
        const result = JSON.parse(JSON.stringify(scene)), nodes = indexNodes(result);
        if (active) {
            const shy = weightsFor(controls.lipWeights ? { weights: controls.lipWeights } : choice).shy;
            const inhibit = state.running ? Math.pow(Math.max(0, Math.sin((Number(state.time) || 0) * 1.05 - 1.0)), 2) * shy : 0;
            applyEmotion(nodes, p, { ...lip, mouthCompress: lip.mouthCompress + inhibit * .12, mouthWidth: lip.mouthWidth - inhibit * .035, mouthCorners: lip.mouthCorners + inhibit * 3.5 });
        }
        if (star)
            nodes.get('camera-hair-clip').children = starClipChildren(scene.palette);
        return result;
    }
    function xml(v) { return String(v).replace(/[&<>\"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
    // Compatible with the face-owned serializer, including clipping and even-odd holes.
    function nodeSVG(n) { const attrs = ` id="${xml(n.id)}"${n.transform ? ` transform="${xml(n.transform)}"` : ''}${n.opacity !== undefined ? ` opacity="${n.opacity}"` : ''}`; const clip = n.clip ? `<defs><clipPath id="${n.id}-clip"><path d="${n.clip}"/></clipPath></defs>` : ''; return n.type === 'group' ? `<g${attrs}>${clip}<g${n.clip ? ` clip-path="url(#${n.id}-clip)"` : ''}>${n.children.map(nodeSVG).join('')}</g></g>` : `<path${attrs} fill="${n.fill}"${n.fillRule ? ` fill-rule="${n.fillRule}"` : ''} d="${n.d}"/>`; }
    function svgScene(scene, label = 'MIRA code-native face and hair study') {
        return `<svg xmlns="http://www.w3.org/2000/svg" width="${scene.width}" height="${scene.height}" viewBox="0 0 ${scene.width} ${scene.height}" role="img" aria-label="${xml(label)}">${scene.layers.map(nodeSVG).join('')}</svg>`;
    }
    function transform(ctx, t) { const re = /(translate|rotate|scale)\(([^)]+)\)/g; let m; while ((m = re.exec(t || ''))) {
        const a = m[2].trim().split(/[ ,]+/).map(Number);
        if (m[1] === 'translate')
            ctx.translate(a[0], a[1] || 0);
        else if (m[1] === 'scale')
            ctx.scale(a[0], a[1] ?? a[0]);
        else {
            if (a.length === 3)
                ctx.translate(a[1], a[2]);
            ctx.rotate(a[0] * Math.PI / 180);
            if (a.length === 3)
                ctx.translate(-a[1], -a[2]);
        }
    } }
    function drawNode(ctx, n) { ctx.save(); transform(ctx, n.transform); if (n.clip)
        ctx.clip(new Path2D(n.clip)); if (n.opacity !== undefined)
        ctx.globalAlpha *= n.opacity; if (n.type === 'group')
        n.children.forEach(v => drawNode(ctx, v));
    else {
        ctx.fillStyle = n.fill;
        ctx.fill(new Path2D(n.d), n.fillRule || 'nonzero');
    } ctx.restore(); }
    function renderScene(ctx, scene) { ctx.clearRect(0, 0, scene.width, scene.height); scene.layers.forEach(n => drawNode(ctx, n)); }
    function create(character) {
        const api = { ...character };
        api.stateAt = (mode, time, running = true, controls = {}) => ({ ...character.stateAt(mode, time, running), emotion: safeEmotion(controls.emotion), accessory: safeAccessory(controls.accessory), emotionIntensity: controls.intensity === undefined ? 1 : clamp(Number(controls.intensity)), ...(controls.transition ? { emotionTransition: { ...controls.transition } } : {}), ...(controls.weights ? { emotionWeights: { ...controls.weights } } : {}) });
        api.scene = (state, controls = {}) => apply(character.scene(state), state, controls);
        api.svg = (state, controls = {}) => svgScene(api.scene(state, controls));
        api.render = (ctx, state, controls = {}) => renderScene(ctx, api.scene(state, controls));
        return api;
    }
    const API = { EMOTIONS, ACCESSORIES, POSES, EYES, weightsFor, parameters, sampleTransition, assertSeam, indexNodes, mapPath, starClipChildren, apply, svgScene, nodeSVG, renderScene, create };
    if (typeof module !== 'undefined' && module.exports)
        module.exports = API;
    root.MiraExpression = API;
})(typeof window !== 'undefined' ? window : globalThis);
