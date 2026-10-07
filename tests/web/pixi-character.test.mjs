import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';

const dist = process.env.MIRA_TEST_WEB_DIST ? resolve(process.env.MIRA_TEST_WEB_DIST) : resolve('apps/web/dist');
const {parseCharacterManifest, fitCharacterFrame, chooseCharacterFrame} =
  await import(new URL('features/presentation/pixi-character-contract.js', `file://${dist}/`));
const {SceneEffectExecutor} = await import(new URL('features/presentation/scene-executor.js', `file://${dist}/`));

const manifest = JSON.parse(await readFile(resolve('apps/web/public/scene/mira_manifest.json'), 'utf8'));

test('manifest validates shipped frames and preserves shared bottom-centre anchors', () => {
  const valid = parseCharacterManifest(manifest);
  assert.deepEqual(valid.logicalSize, {width: 560, height: 720});
  assert.deepEqual(valid.base.pixelSize, {width: 1102, height: 1428});
  const base = fitCharacterFrame(valid.base, valid);
  const combo = fitCharacterFrame(valid.actionVariants.camera_lowered.warm, valid);
  for (const [layout, frame] of [[base, valid.base], [combo, valid.actionVariants.camera_lowered.warm]]) {
    assert.equal(layout.height, 720);
    assert.equal(layout.y, 0);
    assert.ok(Math.abs(layout.width / layout.height - frame.pixelSize.width / frame.pixelSize.height) < 1e-12);
    assert.ok(Math.abs(layout.x - (560 - layout.width) / 2) < 1e-12);
  }
});

test('manifest rejects nonlocal, malformed, mismatched, and undeclared frame entries', () => {
  for (const src of ['https://example.invalid/portrait.png', '../private.png', 'data:image/png;base64,abc']) {
    const invalid = structuredClone(manifest); invalid.base.src = src;
    assert.throws(() => parseCharacterManifest(invalid));
  }
  const badSize = structuredClone(manifest); badSize.base.pixelSize.width++;
  assert.throws(() => parseCharacterManifest(badSize));
  const badState = structuredClone(manifest); badState.expressionVariants.relaxing = {
    src: 'mira-fake.png', pixelSize: {width: 1102, height: 1428}, sourceAnchor: {x:551,y:1428}, sha256: 'a'.repeat(64),
  };
  assert.throws(() => parseCharacterManifest(badState));
  const remote = structuredClone(manifest); remote.actionVariants.look_at_rain.unknown = {
    src: 'mira-remote.png', pixelSize: {width:1101,height:1428}, sourceAnchor:{x:550.5,y:1428}, sha256:'b'.repeat(64),
  };
  assert.throws(() => parseCharacterManifest(remote));
  const duplicate = structuredClone(manifest); duplicate.expressionVariants.warm.src = duplicate.base.src;
  assert.throws(() => parseCharacterManifest(duplicate));
  const wrongAnchor = structuredClone(manifest); wrongAnchor.base.sourceAnchor.y = 0;
  assert.throws(() => parseCharacterManifest(wrongAnchor));
});

test('only exact action and expression pairs select a full-frame variant', () => {
  const valid = parseCharacterManifest(manifest);
  assert.equal(chooseCharacterFrame(valid, {phase: 'idle', expression: 'warm', action: 'camera_ready'}).src,
    manifest.expressionVariants.warm.src);
  assert.equal(chooseCharacterFrame(valid, {phase: 'speaking', expression: 'reflective', action: 'camera_ready'}).src,
    manifest.expressionVariants.reflective.src, 'phase stays orthogonal to face art');
  assert.equal(chooseCharacterFrame(valid, {phase: 'idle', expression: 'curious', action: 'camera_lowered'}).src,
    manifest.actionVariants.camera_lowered.curious.src);
  assert.equal(chooseCharacterFrame(valid, {phase: 'idle', expression: 'reflective', action: 'camera_lowered'}).src,
    manifest.actionVariants.camera_lowered.reflective.src);
  assert.equal(chooseCharacterFrame(valid, {phase: 'idle', expression: 'curious', action: 'look_at_rain'}).src,
    manifest.actionVariants.look_at_rain.curious.src);
  assert.equal(chooseCharacterFrame(valid, {phase: 'speaking', expression: 'calm', action: 'look_at_rain'}).src,
    manifest.actionVariants.look_at_rain.calm.src);
});

test('every declared frame is local, hash-pinned RGBA PNG below the texture limits', async () => {
  const valid = parseCharacterManifest(manifest);
  const frames = [valid.base, ...Object.values(valid.expressionVariants),
    ...Object.values(valid.actionVariants).flatMap(Object.values)];
  let totalBytes = 0;
  for (const frame of frames) {
    const file = resolve('apps/web/public/scene', frame.src);
    const bytes = await readFile(file);
    totalBytes += bytes.byteLength;
    assert.equal(bytes.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    assert.equal(bytes.readUInt32BE(16), frame.pixelSize.width);
    assert.equal(bytes.readUInt32BE(20), frame.pixelSize.height);
    assert.equal(bytes[25], 6, 'full-frame assets preserve RGBA alpha');
    assert.equal(createHash('sha256').update(bytes).digest('hex'), frame.sha256);
    assert.ok(frame.pixelSize.width < 2048 && frame.pixelSize.height < 2048);
    assert.ok(bytes.byteLength <= 3 * 1024 * 1024);
  }
  assert.ok(totalBytes < 32 * 1024 * 1024, 'static artwork package has an explicit compressed-size budget');
});

class Slot {
  constructor() { this.dataset = {}; this.hidden = false; this.textContent = ''; this.style = {}; }
  setAttribute(name, value) { this[name] = value; }
}
function fakeStage(withCharacter = true) {
  const names = ['subtitle', 'photo', 'pose', 'scene-label', 'phase-label', 'character-description'];
  const elements = Object.fromEntries(names.map(name => [name, new Slot()]));
  const anchor = withCharacter ? new Slot() : null;
  const svg = anchor ? new Slot() : null;
  if (anchor) {
    anchor.children = [];
    anchor.appendChild = child => { anchor.children.push(child); child.parentNode = anchor; };
    anchor.querySelector = selector => selector === 'svg' ? svg : null;
  }
  if (svg) svg.style.visibility = '';
  const root = new Slot();
  root.querySelector = selector => selector.startsWith('[data-')
    ? elements[selector.slice(6, -1)] ?? null
    : selector === '.character-anchor' ? anchor
      : selector === '.character-anchor svg' ? svg : null;
  return {root, anchor, svg, elements};
}
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test('renderer readiness applies only the latest executor state', async () => {
  const stage = fakeStage(), pending = deferred(), applied = [];
  const executor = new SceneEffectExecutor(stage.root, {
    characterRendererFactory: () => pending.promise,
  });
  executor.apply({kind: 'pose', value: 'camera_lowered'});
  executor.setPhase('speaking');
  executor.stop();
  pending.resolve({render: state => applied.push(state), destroy() { applied.push('destroy'); }});
  await tick();
  assert.equal(applied.length, 1);
  assert.equal(applied[0].phase, 'idle');
  assert.equal(applied[0].expression, 'warm');
  assert.equal(applied[0].action, 'camera_lowered');
  assert.equal(stage.root.dataset.phase, 'idle');
  assert.equal(stage.root.dataset.expression, 'warm');
  assert.equal(stage.root.dataset.action, 'camera_lowered');
});

test('prepare stages the exact next frame but does not render it before apply', async () => {
  const stage = fakeStage(), applied = [], prepared = [];
  const renderer = {
    async prepareState(state) { prepared.push({...state}); return true; },
    render(state) { applied.push({...state}); },
    destroy() {},
  };
  const executor = new SceneEffectExecutor(stage.root, {characterRendererFactory: async () => renderer});
  const effect = {kind: 'pose', value: 'camera_lowered'};
  const signal = new AbortController().signal;
  await executor.prepare(effect, signal);
  assert.equal(prepared.at(-1).action, 'camera_lowered');
  assert.equal(prepared.at(-1).expression, 'warm');
  assert.equal(applied.at(-1).action, 'camera_ready', 'prepare stages resources only');
  executor.apply(effect);
  assert.equal(applied.at(-1).action, 'camera_lowered');
  assert.equal(applied.at(-1).expression, 'warm');
});

test('close aborts pending renderer setup and safely disposes late completion once', async () => {
  const stage = fakeStage(), pending = deferred(); let destroys = 0;
  const executor = new SceneEffectExecutor(stage.root, {characterRendererFactory: () => pending.promise});
  executor.close(); executor.close();
  pending.resolve({prepareState: async () => true, render() {}, destroy() { destroys++; }});
  await tick();
  assert.equal(destroys, 1);
  assert.equal(stage.anchor.dataset.renderer, undefined);
  assert.equal(stage.svg.style.visibility, '');
});

test('renderer failures leave the static SVG path usable', async () => {
  const stage = fakeStage();
  stage.svg.style.visibility = '';
  new SceneEffectExecutor(stage.root, {characterRendererFactory: async () => { throw new Error('local asset unavailable'); }});
  await tick();
  assert.equal(stage.svg.style.visibility, '');
  assert.equal(stage.anchor.dataset.characterRenderer, undefined);
});

test('Pixi runtime initializes transparent, capped, non-looping canvas', async () => {
  const {createPixiCharacterRenderer} = await import(new URL('features/presentation/pixi-character-renderer.js', `file://${dist}/`));
  const calls = [], listeners = new Map(), canvas = {
    style: {}, setAttribute(name, value) { this[name] = value; },
    addEventListener(name, listener) { listeners.set(name, listener); },
    removeEventListener(name) { listeners.delete(name); }, remove() { calls.push('remove'); },
  };
  const sprite = {texture: null, x: 0, y: 0, width: 0, height: 0};
  const app = {
    canvas, stage: {addChild(child) { calls.push(['addChild', child]); }},
    ticker: {stop() { calls.push('ticker.stop'); }},
    async init(options) { calls.push(['init', options]); this.renderer = {render(options) { calls.push(['render', options]); }}; },
    destroy() { calls.push('destroy'); },
  };
  const runtime = {
    createApplication() { return app; },
    async loadTexture(src) {
      calls.push(['loadTexture', src]);
      const record = [manifest.base, ...Object.values(manifest.expressionVariants),
        ...Object.values(manifest.actionVariants).flatMap(Object.values)].find(value => src.endsWith(value.src));
      return {width: record.pixelSize.width, height: record.pixelSize.height, src};
    },
    async unloadTexture(texture) { calls.push(['unloadTexture', texture.src]); },
    createSprite(texture) { sprite.texture = texture; return sprite; },
    destroyTexture(texture) { calls.push(['destroyTexture', texture.src]); },
  };
  const localFetch = async () => manifest;
  const stage = fakeStage();
  const portrait = await createPixiCharacterRenderer(stage.anchor, {
    fetchManifest: localFetch, loadRuntime: async () => runtime, devicePixelRatio: () => 4,
  });
  const initialLoads = calls.filter(entry => Array.isArray(entry) && entry[0] === 'loadTexture').length;
  assert.equal(initialLoads, 1, 'only the neutral base is loaded at startup');
  portrait.render({phase: 'idle', expression: 'calm', action: 'camera_ready'});
  assert.equal(stage.svg.style.visibility, 'hidden');
  assert.equal(stage.anchor.dataset.renderer, 'pixi');
  assert.equal(canvas.className, 'mira-pixi-canvas');
  assert.equal(canvas['aria-hidden'], 'true');
  const baseLayout = fitCharacterFrame(manifest.base, parseCharacterManifest(manifest));
  assert.deepEqual(sprite && {x: sprite.x, y: sprite.y, width: sprite.width, height: sprite.height}, {
    x: baseLayout.x, y: baseLayout.y, width: baseLayout.width, height: baseLayout.height,
  });
  const init = calls.find(entry => Array.isArray(entry) && entry[0] === 'init')[1];
  assert.equal(init.backgroundAlpha, 0);
  assert.equal(init.autoStart, false);
  assert.equal(init.resolution, 2);
  assert.equal(init.preference, 'webgl');
  assert.equal(init.sharedTicker, false);
  assert.equal(calls.some(entry => Array.isArray(entry) && entry[0] === 'render'), true);
  assert.equal(await portrait.prepareState({phase:'idle', expression:'warm', action:'camera_ready'}, new AbortController().signal), true);
  portrait.render({phase: 'idle', expression: 'warm', action: 'camera_ready'});
  assert.equal(sprite.texture.src.endsWith(manifest.expressionVariants.warm.src), true);
  assert.equal(stage.svg.style.visibility, 'hidden');
  assert.equal(await portrait.prepareState({phase:'idle', expression:'curious', action:'look_at_rain'}, new AbortController().signal), true,
    'a declared exact combo can be staged when authorized');
  portrait.render({phase:'idle', expression:'curious', action:'look_at_rain'});
  assert.equal(stage.anchor.dataset.renderer, 'pixi');
  assert.equal(stage.svg.style.visibility, 'hidden');
  portrait.destroy();
  assert.equal(stage.svg.style.visibility, '');
  assert.equal(stage.anchor.dataset.renderer, undefined);
});

test('WebGL context loss tears down Pixi and restores SVG', async () => {
  const {createPixiCharacterRenderer} = await import(new URL('features/presentation/pixi-character-renderer.js', `file://${dist}/`));
  const listeners = new Map(); let appDestroyed = 0, canvasRemoved = 0;
  const canvas = {
    style: {}, setAttribute(name, value) { this[name] = value; },
    addEventListener(name, listener) { listeners.set(name, listener); },
    removeEventListener(name) { listeners.delete(name); }, remove() { canvasRemoved++; },
  };
  const app = {
    canvas, ticker: {stop() {}}, stage: {addChild() {}},
    async init() { this.renderer = {render() {}}; },
    destroy() { appDestroyed++; },
  };
  const runtime = {
    createApplication() { return app; },
    async loadTexture() { return {width: manifest.base.pixelSize.width, height: manifest.base.pixelSize.height}; },
    createSprite(texture) { return {texture, x:0, y:0, width:0, height:0}; },
    destroyTexture() {},
  };
  const stage = fakeStage();
  const portrait = await createPixiCharacterRenderer(stage.anchor, {
    fetchManifest: async () => manifest, loadRuntime: async () => runtime,
  });
  portrait.render({phase:'idle', expression:'calm', action:'camera_ready'});
  assert.equal(stage.anchor.dataset.renderer, 'pixi');
  let prevented = false;
  listeners.get('webglcontextlost')?.({preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(stage.anchor.dataset.renderer, undefined);
  assert.equal(stage.svg.style.visibility, '');
  assert.equal(canvasRemoved, 1);
  assert.equal(appDestroyed, 1);
  assert.equal(listeners.has('webglcontextlost'), false);
  portrait.destroy();
  assert.equal(appDestroyed, 1, 'close remains idempotent after context loss');
});
