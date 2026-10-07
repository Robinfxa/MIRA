import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { deflateSync } from 'node:zlib';

const dist = process.env.MIRA_TEST_WEB_DIST
  ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href
  : new URL('../../apps/web/dist/', import.meta.url).href;
const { initialSceneState, reduceSceneEffect } = await import(new URL('features/presentation/scene-state.js', dist));
const { PresentationGate } = await import(new URL('features/presentation/permit-gate.js', dist));
const { SessionController } = await import(new URL('features/session/controller.js', dist));
const { SceneEffectExecutor } = await import(new URL('features/presentation/scene-executor.js', dist));
const { MiraApiClient } = await import(new URL('features/session/api-client.js', dist));
const { parseSession } = await import(new URL('shared/protocol.js', dist));
const { prepareGeneratedImage, readGeneratedImageResponse, MAX_GENERATED_IMAGE_BYTES } = await import(new URL('features/presentation/generated-image-resource.js', dist));
const resourceId = '11111111-1111-4111-8111-111111111111';
const generatedPhotoIdentityForTest=value=>value.startsWith('generated_story_photo:v1:');
const photo = (activity = 1, digest = 'b'.repeat(64)) => ({id: `image-${activity}`, kind: 'media',
  value: `generated_story_photo:v1:${resourceId}:${digest}`, digest: 'a'.repeat(64), output_epoch: activity, activity_seq: activity});
const snapshot = (grants, changes = {}) => ({session_id: 'session', client_instance_id: 'client',
  activity_seq: 1, output_epoch: 1, revision: 1, permit_revision: 1, request_id: 'request',
  phase: 'idle', sealed: true, active_grants: grants, ...changes});

test('generated media changes only photo presentation, preserving character and environment', () => {
  const before = {...initialSceneState(), expression: 'reflective', action: 'camera_lowered', outfit: 'outfit_amber_raincoat'};
  const after = reduceSceneEffect(before, photo());
  assert.equal(after.photoVisible, true);
  assert.equal(after.photoKind, 'generated');
  for (const key of ['expression', 'action', 'outfit', 'emotion', 'accessory', 'environment']) assert.equal(after[key], before[key]);
});

test('dismissal fences generated grants arriving after ordinary text seals', () => {
  const gate = new PresentationGate('session', 'client');
  gate.beginInput('request');
  gate.install(snapshot([]));
  gate.dismissPhoto();
  gate.install(snapshot([photo()], {revision: 2, permit_revision: 2}));
  assert.equal(gate.allows(photo()), false);
  assert.equal(gate.consume(photo()), null);
});

test('canonical grammar rejects malformed generated media without accepting arbitrary URLs', () => {
  for (const value of [photo().value + ':extra', photo().value + '\n', photo().value.replace(':v1:', ':v2:'),
    photo().value.replace('-4111-', '-1111-'), photo().value.toUpperCase(),
    `generated_story_photo:v1:../image:${'b'.repeat(64)}`, 'https://example.invalid/a.png']) {
    assert.throws(() => reduceSceneEffect(initialSceneState(), {...photo(), value}), /Unsupported scene/);
  }
});

const tick = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 12; i++) await tick(); };
const until = async predicate => {
  const deadline = Date.now() + 2000;
  while (!predicate()) {
    if (Date.now() > deadline) assert.fail('Synthetic lifecycle milestone did not settle');
    await new Promise(resolve => setTimeout(resolve, 1));
  }
};
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => {resolve = yes; reject = no;}); return {promise, resolve, reject}; };
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) { crc ^= byte; for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1)); }
  return (crc ^ 0xffffffff) >>> 0;
}
function syntheticPng(width = 1024, height = 1024, gray = 80) {
  const chunk = (name, data) => {
    const bytes = Buffer.concat([Buffer.from(name), data]);
    const length = Buffer.alloc(4); length.writeUInt32BE(data.length);
    const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(bytes));
    return Buffer.concat([length, bytes, crc]);
  };
  const header = Buffer.alloc(13); header.writeUInt32BE(width); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = 2;
  const scanlines = Buffer.alloc((width * 3 + 1) * height, gray);
  for (let row = 0; row < height; row++) scanlines[row * (width * 3 + 1)] = 0;
  return new Uint8Array(Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]), chunk('IHDR', header), chunk('IDAT', deflateSync(scanlines)), chunk('IEND', Buffer.alloc(0))]));
}
const png = syntheticPng();
const pngDigest = hash(png);
const imageResponse = (bytes = png, headers = {}) => new Response(bytes, {headers: {'content-type': 'image/png', 'cache-control': 'no-store', ...headers}});

function syntheticImage(decode = Promise.resolve(), width = 1024, height = 1024) {
  return {src: '', complete: false, naturalWidth: 0, naturalHeight: 0, decodeCalls: 0,
    removeAttribute(name) { if (name === 'src') this.src = ''; },
    async decode() { this.decodeCalls++; await decode; this.complete = true; this.naturalWidth = width; this.naturalHeight = height; },
  };
}

function harness(options = {}) {
  const imageBytes = options.imageBytes ?? png;
  const imageDigest = hash(imageBytes);
  const receipts = [], calls = [], errors = [], statuses = [], urls = [], revoked = [], images = [];
  const activeUrls = new Map();
  const slots = new Map(['subtitle', 'photo', 'pose', 'scene-label', 'phase-label', 'character-description',
    'generated-photo', 'authored-photo', 'photo-label', 'photo-description', 'photo-close'].map(name => [name, {
    textContent: '', hidden: name === 'photo' || name === 'generated-photo', children: [],
    replaceChildren(...children) { this.children = children; },
    setAttribute(name, value) {this[name] = value;},
    set innerHTML(_value) { throw new Error('HTML parsing is forbidden'); },
  }]));
  const authoredImage = syntheticImage(Promise.resolve(), 600, 460);
  authoredImage.complete = true; authoredImage.naturalWidth = 600; authoredImage.naturalHeight = 460;
  const root = {dataset: {}, querySelector(selector) {
    if (selector === '[data-photo] img') return authoredImage;
    return slots.get(selector.replace(/^\[data-|\]$/g, '')) ?? null;
  }};
  let revision = 0, client = '', current;
  const state = (activity = 0, extra = {}) => ({schema_version: '0.1.0-foundation', session_id: 'generated-session', client_instance_id: client,
    revision: ++revision, permit_revision: revision, activity_seq: activity, input_epoch: activity, output_epoch: activity,
    request_id: null, phase: 'idle', sealed: false, active_grants: [], presented_effects: [], audio_progress: [],
    last_error: null, photo_visible: false, photo_visibility_revision: 0,
    story_image: {capability: 'bounded_fiction', state: 'idle'}, ...extra});
  const json = value => new Response(JSON.stringify(value), {headers: {'content-type': 'application/json'}});
  const api = new MiraApiClient({apiBase: '/api/v1', pollIntervalMs: 999999}, {fetch: async (url, init = {}) => {
    calls.push({url, init});
    const body = init.body ? JSON.parse(init.body) : null;
    if (url === '/api/v1/sessions' && init.method === 'POST') {
      client = body.client_instance_id; current = state(); return json({session: current, session_token: 'synthetic-token-only'});
    }
    if (url.endsWith('/voice-capabilities')) return json({generation_mode: 'mock', speech_enabled: false, microphone_enabled: false,
      qualification: 'offline_fixture', speech_sample_rate_hz: 24000, microphone_sample_rate_hz: 16000});
    if (url.endsWith('/inputs')) {
      const grant = {...photo(body.activity_seq, imageDigest), id: `22222222-2222-4222-8222-${String(body.activity_seq).padStart(12, '0')}`};
      current = state(body.activity_seq, {request_id: body.request_id, sealed: true,
        active_grants: options.grants ? options.grants(grant, body) : [grant, {...grant, id: `text-${body.activity_seq}`, kind: 'subtitle', value: '普通正文继续。'}],
        story_image: {capability: 'bounded_fiction', state: options.imageState ?? 'qualified', request_id:resourceId, resource_id: resourceId, content_digest: imageDigest, ...(options.completion ? {completion_state:'unavailable',completion_available:true}: {})}});
      return json(current);
    }
    if (url.endsWith('/story-image-completions')) {
      assert.equal(current.story_image.state,'presented');
      assert.ok(current.presented_effects.some(e=>e.id===body.presented_effect_id));
      if(options.completionError) throw new Error('synthetic completion transport failure');
      current={...current,revision:++revision,story_image:{...current.story_image,completion_state:'requested'}};
      return json(current);
    }
    if (url.includes('/story-images/')) return options.fetchResponse ? options.fetchResponse(body, init.signal) : imageResponse(imageBytes);
    if (url.endsWith('/receipts')) {
      receipts.push({...body, visible: !slots.get('photo').hidden, src: images.at(-1)?.src,
        label: slots.get('photo-label').textContent, caption: slots.get('subtitle').textContent});
      await options.receiptBarrier?.promise;
      if(options.completion){
        const effect=current.active_grants.find(e=>e.id===body.effect_id);
        current={...current,revision:++revision,presented_effects:[...current.presented_effects,effect],
          story_image:{...current.story_image,...(generatedPhotoIdentityForTest(effect.value)?{state:'presented',completion_state:'pending'}:{})}};
      }
      return json(current);
    }
    if (url.endsWith('/photo-dismissals')) {
      current = {...current, revision: ++revision, permit_revision: revision, active_grants: current.active_grants.filter(effect => effect.kind !== 'media' || body.target==='fixed_photo' && generatedPhotoIdentityForTest(effect.value)),
        photo_visible: false, photo_visibility_revision: body.expected_revision + 1};
      return json(current);
    }
    if (url.endsWith('/stop')) { current = state(body.activity_seq, {phase: 'stopped'}); return json(current); }
    if (init.method === 'DELETE') return new Response(null, {status: 204});
    if (init.method === 'GET') return new Promise(() => {});
    throw new Error('Unexpected synthetic endpoint');
  }});
  const executor = new SceneEffectExecutor(root, {characterRendererFactory: null, mediaReadinessTimeoutMs: options.timeoutMs ?? 1000,
    generatedImage: {fetchBytes: (effect, signal) => api.generatedImage(effect, signal),
      createImage: () => { const image = syntheticImage(options.decode?.promise, options.width ?? 1024, options.height ?? 1024); images.push(image); return image; },
      createObjectURL: blob => { const url = `blob:synthetic-${urls.length + 1}`; urls.push(url); activeUrls.set(url, blob); return url; },
      revokeObjectURL: url => { revoked.push(url); activeUrls.delete(url); },
    }});
  const originalPresent = executor.present.bind(executor);
  let commitReached = false;
  if (options.preCommit) executor.present = async (effect, signal, canCommit) => {
    if (effect.kind === 'media') {commitReached = true; await options.preCommit.promise;}
    return originalPresent(effect, signal, canCommit);
  };
  const controller = new SessionController(api, executor, {connected() {}, update() {}, localStop() {},
    error(message) { if (message) errors.push(message); }, storyImageStatus(message, dismissible) {statuses.push({message, dismissible});},
  }, {apiBase: '/api/v1', pollIntervalMs: 999999}, {
    createPlayback: () => ({get quiescent() {return !options.replyBusy?.();},unlock: async () => true,open: () => null,stop() {},reconcileAuthorization() {},close: async () => {}}),
    waitForReplyQuiet: options.waitForReplyQuiet,userInputPending: options.userInputPending,
    createCapture: () => ({start: async () => false, stop() {}, close: async () => {}}),
  });
  return {api, controller, executor, slots, root, receipts, calls, errors, statuses, urls, revoked, activeUrls, images,
    get current() { return current; },
    async start() {
      await controller.connect(); await controller.input('生成虚构剧情插画');
      if (options.waitAt==='quiet') {await settle();return;}
      if (current.active_grants.some(effect => effect.kind === 'media')) await until(() => !slots.get('photo').hidden
        || statuses.some(status => /未能展示/.test(status.message ?? '')) || (options.decode && images.some(image => image.decodeCalls > 0))
        || commitReached || (options.waitAt === 'fetch' && calls.some(call => call.url.includes('/story-images/'))));
      await settle();
    },
    install(changes) {current = {...current, revision: ++revision, permit_revision: revision, ...changes}; controller.install(current);},
    async close() {await controller.close();},
  };
}

test('exact authenticated fetch and decoded visible commit precede one software receipt', async () => {
  const decode = deferred(); const h = harness({decode});
  try {
    await h.start();
    assert.equal(h.slots.get('photo').hidden, true);
    assert.equal(h.slots.get('subtitle').textContent, '普通正文继续。');
    assert.equal(h.receipts.filter(receipt => receipt.effect_id.startsWith('2222')).length, 0);
    const imageCall = h.calls.find(call => call.url.includes('/story-images/'));
    assert.equal(imageCall.url, `/api/v1/sessions/generated-session/story-images/${resourceId}`);
    assert.equal(imageCall.init.headers['X-Mira-Session-Token'], 'synthetic-token-only');
    assert.equal(imageCall.init.method, 'POST'); assert.equal(imageCall.init.cache, 'no-store'); assert.equal(imageCall.init.redirect, 'error');
    assert.deepEqual(JSON.parse(imageCall.init.body), {effect_id: h.current.active_grants[0].id,
      digest: 'a'.repeat(64), activity_seq: 1, output_epoch: 1, content_digest: pngDigest});
    for (let count = 0; count < 3; count++) h.install({});
    decode.resolve(); await until(() => h.receipts.some(receipt => receipt.effect_id.startsWith('2222')));
    assert.equal(h.slots.get('photo').hidden, false);
    assert.equal(h.slots.get('photo-label').textContent, '剧情生成图 · 虚构画面');
    assert.equal(h.slots.get('photo-description').textContent, '根据已开放的虚构剧情生成的插画。');
    assert.equal(h.slots.get('photo-close')['aria-label'], '关闭剧情生成图');
    assert.equal(h.root.dataset.expression, 'calm'); assert.equal(h.root.dataset.action, 'camera_ready');
    const receipts = h.receipts.filter(receipt => receipt.effect_id.startsWith('2222'));
    assert.equal(receipts.length, 1); assert.equal(receipts[0].visible, true); assert.match(receipts[0].src, /^blob:synthetic-/);
    assert.equal(h.calls.filter(call => call.url.includes('/story-images/')).length, 1);
    assert.equal(h.images[0].decodeCalls, 1); assert.equal(h.activeUrls.size, 1);
    assert.deepEqual(h.errors, []);
  } finally {await h.close();}
  assert.equal(h.activeUrls.size, 0); assert.equal(new Set(h.revoked).size, h.revoked.length);
});

test('Stop, newer input, Close, dismissal and revocation win at fetch, decode and pre-commit barriers', async t => {
  for (const [width, height] of [[1024, 1024], [1536, 1024], [1024, 1536]])
  for (const stage of ['fetch', 'decode', 'commit']) for (const action of ['stop', 'new-input', 'close', 'dismiss', 'revoke']) {
    await t.test(`${width}x${height} ${stage}: ${action}`, async () => {
      const barrier = deferred(); let fetchSignal;
      const imageBytes = syntheticPng(width, height);
      const h = harness({imageBytes, width, height, ...(stage === 'fetch' ? {waitAt: 'fetch', fetchResponse: (_body, signal) => {fetchSignal = signal; return barrier.promise;}}
        : stage === 'decode' ? {decode: barrier} : {preCommit: barrier})});
      try {
        await h.start();
        assert.equal(h.slots.get('photo').hidden, true);
        if (action === 'stop') await h.controller.stop();
        if (action === 'new-input') await h.controller.input('新一轮');
        if (action === 'close') await h.close();
        if (action === 'dismiss') await h.controller.dismissStoryImage();
        if (action === 'revoke') h.install({active_grants: []});
        if (stage === 'fetch' && action !== 'new-input') assert.equal(fetchSignal.aborted, true);
        barrier.resolve(stage === 'fetch' ? imageResponse(imageBytes) : undefined);
        await until(() => h.controller.visualPreparations.size === 0); await settle();
        assert.equal(h.receipts.some(receipt => receipt.effect_id.endsWith('000000000001')), false);
        if (action !== 'new-input') {
          assert.equal(h.slots.get('photo').hidden, true); assert.equal(h.activeUrls.size, 0);
        } else {
          assert.equal(h.receipts.filter(receipt => receipt.effect_id.startsWith('2222')).every(receipt => receipt.activity_seq === 2), true);
        }
      } finally {await h.close();}
      assert.equal(h.activeUrls.size, 0); assert.equal(new Set(h.revoked).size, h.revoked.length);
    });
  }
});

test('shown generated image survives Stop, then releases exactly once on dismissal', async () => {
  const h = harness();
  try {
    await h.start(); const before = structuredClone(h.receipts);
    assert.equal(h.slots.get('photo').hidden, false);
    await h.controller.stop(); await settle();
    assert.equal(h.slots.get('photo').hidden, false); assert.equal(h.activeUrls.size, 1);
    assert.match(h.slots.get('subtitle').textContent, /剧情生成图/); assert.doesNotMatch(h.slots.get('subtitle').textContent, /旅行/);
    await h.controller.dismissPhoto(); await settle();
    assert.equal(h.slots.get('photo').hidden, true); assert.equal(h.activeUrls.size, 0);
    assert.deepEqual(h.receipts, before);
  } finally {await h.close();}
  assert.equal(h.revoked.length, 1);
});

test('replacement with fixed authored photo restores its exact caption and releases generated pixels', async () => {
  const h = harness();
  try {
    await h.start();
    const authored = {...photo(), id: 'authored', value: 'trip_photo'};
    h.install({active_grants: [...h.current.active_grants, authored]}); await settle();
    assert.equal(h.slots.get('photo').hidden, false); assert.equal(h.slots.get('generated-photo').hidden, true);
    assert.equal(h.slots.get('authored-photo').hidden, false);
    assert.equal(h.slots.get('photo-label').textContent, 'TRAVEL NOTE 07 · 原创插画');
    assert.equal(h.slots.get('photo-close')['aria-label'], '关闭旅行插画');
    assert.equal(h.activeUrls.size, 0);
    assert.equal(h.receipts.filter(receipt => receipt.effect_id === 'authored').length, 1);
  } finally {await h.close();}
});

test('same-turn revocation releases visible generated resource without inventing a new receipt', async () => {
  const h = harness();
  try {
    await h.start(); const receipts = structuredClone(h.receipts);
    h.install({active_grants: []}); await settle();
    assert.equal(h.slots.get('photo').hidden, true); assert.equal(h.activeUrls.size, 0);
    assert.deepEqual(h.receipts, receipts);
  } finally {await h.close();}
});

test('a late older-activity revocation cannot erase an image already retained by local Stop', async () => {
  const h = harness();
  try {
    await h.start(); const prior = {...h.current};
    const stopping = h.controller.stop();
    h.install({activity_seq: prior.activity_seq, output_epoch: prior.output_epoch,
      request_id: prior.request_id, phase: 'idle', active_grants: []});
    assert.equal(h.slots.get('photo').hidden, false);
    assert.equal(h.activeUrls.size, 1);
    await stopping;
  } finally {await h.close();}
});

test('post-seal generated grant needs a live permit and cannot reappear after an earlier dismissal', async () => {
  const h = harness({imageState: 'generating', grants: () => []});
  try {
    await h.start(); assert.match(h.statuses.at(-1).message, /正在生成/);
    await h.controller.dismissStoryImage();
    h.install({active_grants: [photo(1, pngDigest)], story_image: {capability: 'bounded_fiction', state: 'qualified'}}); await settle();
    assert.equal(h.calls.some(call => call.url.includes('/story-images/')), false);
    assert.equal(h.slots.get('photo').hidden, true); assert.deepEqual(h.receipts, []);
    assert.equal(h.statuses.at(-1).message, null);
  } finally {await h.close();}
});

test('bad bytes, hash mismatch and decode failure leave ordinary text and bounded image failure status', async t => {
  for (const fault of ['hash', 'mime', 'cache', 'redirect', 'over-limit', 'bad-png', 'dimensions', 'decode']) await t.test(fault, async () => {
    const badDecode = deferred();
    const response = () => {
      if (fault === 'hash') return imageResponse(syntheticPng(1024, 1024, 90));
      if (fault === 'mime') return imageResponse(png, {'content-type': 'image/svg+xml'});
      if (fault === 'cache') return imageResponse(png, {'cache-control': 'max-age=999'});
      if (fault === 'over-limit') return imageResponse(png, {'content-length': String(MAX_GENERATED_IMAGE_BYTES + 1)});
      if (fault === 'bad-png') return imageResponse(new Uint8Array(100));
      if (fault === 'dimensions') return imageResponse(syntheticPng(2, 2));
      const result = imageResponse(); if (fault === 'redirect') Object.defineProperty(result, 'redirected', {value: true}); return result;
    };
    const h = harness({fetchResponse: response, ...(fault === 'decode' ? {decode: badDecode} : {})});
    try {
      await h.start();
      if (fault === 'decode') {badDecode.reject(new Error('private decoder detail')); await until(() => h.statuses.at(-1).message?.includes('未能展示'));}
      assert.equal(h.slots.get('photo').hidden, true); assert.equal(h.activeUrls.size, 0);
      assert.equal(h.slots.get('subtitle').textContent, '普通正文继续。');
      assert.equal(h.receipts.filter(receipt => receipt.effect_id.startsWith('text-')).length, 1);
      assert.equal(h.receipts.some(receipt => receipt.effect_id.startsWith('2222')), false);
      assert.match(h.statuses.at(-1).message, /未能展示.*继续聊天/); assert.deepEqual(h.errors, []);
      h.install({}); await settle(); assert.match(h.statuses.at(-1).message, /未能展示/);
      assert.equal(h.calls.filter(call => call.url.includes('/story-images/')).length, 1, 'no automatic image retry');
    } finally {await h.close();}
  });
});

test('bounded deadline cancels an uncooperative image decode and late completion remains hidden', async () => {
  const decode = deferred(); const h = harness({decode, timeoutMs: 5});
  try {
    await h.start(); await new Promise(resolve => setTimeout(resolve, 15)); await settle();
    assert.equal(h.activeUrls.size, 0); assert.equal(h.slots.get('photo').hidden, true);
    decode.resolve(); await settle();
    assert.equal(h.receipts.some(receipt => receipt.effect_id.startsWith('2222')), false);
  } finally {await h.close();}
});

test('stream bound and cancellation do not wait on a hung network reader', async () => {
  const abort = new AbortController(); let cancelled = 0;
  const response = new Response(new ReadableStream({pull() {return new Promise(() => {});}, cancel() {cancelled++;}}),
    {headers: {'content-type': 'image/png', 'cache-control': 'no-store'}});
  const reading = readGeneratedImageResponse(response, abort.signal); abort.abort();
  await assert.rejects(reading); assert.ok(cancelled >= 1);
  const tooLarge = new Response(new ReadableStream({start(controller) {controller.enqueue(new Uint8Array(MAX_GENERATED_IMAGE_BYTES + 1));}}),
    {headers: {'content-type': 'image/png', 'cache-control': 'no-store'}});
  await assert.rejects(readGeneratedImageResponse(tooLarge, new AbortController().signal));
});

test('prepared image clones transport bytes and owns one abort listener until commit', async () => {
  const abort = new AbortController(); let listeners = 0, revoked = 0;
  const add = abort.signal.addEventListener.bind(abort.signal), remove = abort.signal.removeEventListener.bind(abort.signal);
  abort.signal.addEventListener = (...args) => {if (args[0] === 'abort') listeners++; return add(...args);};
  abort.signal.removeEventListener = (...args) => {if (args[0] === 'abort') listeners--; return remove(...args);};
  let storedBlob;
  const bytes = png.slice();
  const resource = await prepareGeneratedImage(photo(1, pngDigest), abort.signal, {fetchBytes: async () => bytes,
    createImage: () => syntheticImage(), createObjectURL: blob => {storedBlob = blob; bytes.fill(0); return 'blob:owned';}, revokeObjectURL: () => revoked++});
  assert.equal(hash(new Uint8Array(await storedBlob.arrayBuffer())), pngDigest);
  assert.equal(listeners, 1); resource.commit(); assert.equal(listeners, 0);
  abort.abort(); assert.equal(revoked, 0);
  resource.dispose(); resource.dispose(); assert.equal(revoked, 1);
});

test('session projection is bounded, immutable and never grants image presentation by itself', async () => {
  const h = harness({imageState: 'qualified', grants: () => []});
  try {
    await h.start(); assert.equal(h.calls.some(call => call.url.includes('/story-images/')), false);
    for (const extra of [{state: '<img onerror=attack>'}, {resource_id: '../private'}, {content_digest: 'bad'}, {url: 'https://untrusted.invalid'}]) {
      assert.throws(() => parseSession({...h.current, story_image: {capability: 'bounded_fiction', state: 'idle', ...extra}}));
    }
    const parsed = parseSession(h.current); assert.equal(Object.isFrozen(parsed.story_image), true);
  } finally {await h.close();}
});

test('a later post-seal image grant displays through the existing controller without reopening text', async () => {
  const h = harness({imageState: 'generating', grants: grant => [{...grant, id: 'text-only', kind: 'subtitle', value: '正文已经结束。'}]});
  try {
    await h.start(); assert.equal(h.current.sealed, true);
    assert.equal(h.slots.get('subtitle').textContent, '正文已经结束。');
    assert.equal(h.calls.some(call => call.url.includes('/story-images/')), false);
    h.install({active_grants: [...h.current.active_grants, photo(1, pngDigest)],
      story_image: {capability: 'bounded_fiction', state: 'qualified'}});
    await until(() => h.receipts.some(receipt => receipt.effect_id === 'image-1'));
    assert.equal(h.slots.get('photo').hidden, false);
    assert.equal(h.slots.get('subtitle').textContent, '正文已经结束。');
    assert.deepEqual(h.receipts.map(receipt => receipt.effect_id), ['text-only', 'image-1']);
  } finally {await h.close();}
});

test('new input waits for generated presentation history, while Stop remains immediate', async () => {
  const receiptBarrier = deferred(); const h = harness({receiptBarrier});
  try {
    await h.start(); assert.equal(h.slots.get('photo').hidden, false);
    const next = h.controller.input('接着聊'); await settle();
    assert.equal(h.calls.filter(call => call.url.endsWith('/inputs')).length, 1);
    const stopping = h.controller.stop();
    assert.equal(h.root.dataset.phase, 'idle');
    await stopping;
    const outcome = await next; assert.equal(outcome.status, 'superseded');
    receiptBarrier.resolve(); await settle();
    assert.equal(h.calls.filter(call => call.url.endsWith('/inputs')).length, 1);
  } finally {receiptBarrier.resolve(); await h.close();}
});

test('decoded dimension mismatch disposes the blob without creating presentation authority', async () => {
  let revoked = 0;
  await assert.rejects(prepareGeneratedImage(photo(1, pngDigest), new AbortController().signal,
    {fetchBytes: async () => png, createImage: () => syntheticImage(Promise.resolve(), 1023, 1024),
      createObjectURL: () => 'blob:dimensions', revokeObjectURL: () => revoked++}));
  assert.equal(revoked, 1);
});

test('held budget explains exhausted local allowance and keeps ordinary text available', async () => {
  const h = harness({imageState: 'held', grants: (grant, body) => [{...grant, id: `text-${body.activity_seq}`, kind: 'subtitle', value: '普通正文继续。'}]});
  try {
    await h.start();
    h.install({story_image: {capability: 'bounded_fiction', state: 'held', failure_code: 'budget'}});
    await settle();
    assert.match(h.statuses.at(-1).message, /调用额度已用尽.*继续聊天/);
    assert.doesNotMatch(h.statuses.at(-1).message, /账单|硬上限|美元|未能完成/);
    assert.equal(h.statuses.at(-1).dismissible, false);
    assert.equal(h.slots.get('subtitle').textContent, '普通正文继续。');
    assert.equal(h.receipts.filter(receipt => receipt.effect_id.startsWith('text-')).length, 1);
    assert.equal(h.calls.some(call => call.url.includes('/story-images/')), false);
    for (const failure_code of ['ineligible', 'review', null]) {
      h.install({story_image: {capability: 'bounded_fiction', state: 'held', failure_code}});
      assert.match(h.statuses.at(-1).message, /暂未获准.*继续聊天/);
      assert.doesNotMatch(h.statuses.at(-1).message, /额度已用尽/);
    }
    await h.controller.input('继续聊'); await settle();
    assert.equal(h.receipts.filter(receipt => receipt.effect_id.startsWith('text-')).length, 2);
    assert.deepEqual(h.errors, []);
  } finally {await h.close();}
});

for (const [width, height] of [[1024, 1024], [1536, 1024], [1024, 1536]]) {
  test(`actual ${width}x${height} raster reaches visible commit and exact digest receipt`, async () => {
    const bytes = syntheticPng(width, height);
    const h = harness({imageBytes: bytes, width, height});
    try {
      await h.start();
      const receipts = h.receipts.filter(receipt => receipt.effect_id.startsWith('2222'));
      assert.equal(receipts.length, 1);
      assert.equal(receipts[0].visible, true);
      assert.equal(h.images[0].width, width); assert.equal(h.images[0].height, height);
      assert.equal(h.images[0].naturalWidth, width); assert.equal(h.images[0].naturalHeight, height);
      const request = JSON.parse(h.calls.find(call => call.url.includes('/story-images/')).init.body);
      assert.equal(request.content_digest, hash(bytes));
      const served = new Uint8Array(await h.activeUrls.values().next().value.arrayBuffer());
      assert.deepEqual(served, bytes);
    } finally { await h.close(); }
  });
}

test('generated image CSS preserves actual aspect ratio without crop or square forcing', async () => {
  const {readFile} = await import('node:fs/promises');
  const css = await readFile(new URL('../../apps/web/public/app.css', import.meta.url), 'utf8');
  const rule = css.match(/\.photo \[data-generated-photo\] img \{([^}]+)\}/)[1];
  assert.match(rule, /aspect-ratio:\s*auto/);
  assert.match(rule, /object-fit:\s*contain/);
});

for (const [width, height, naturalWidth, naturalHeight] of [
  [1024, 2048, 1024, 2048], [1536, 1536, 1536, 1536], [1536, 1024, 1024, 1024],
]) {
  test(`unsupported or mismatched raster ${width}x${height}/${naturalWidth}x${naturalHeight} cannot get receipt`, async () => {
    const h = harness({imageBytes: syntheticPng(width, height), width: naturalWidth, height: naturalHeight});
    try { await h.start(); assert.equal(h.receipts.filter(r => r.effect_id.startsWith('2222')).length, 0);
      assert.equal(h.slots.get('photo').hidden, true); }
    finally { await h.close(); }
  });
}


test('R2 generated picture waits for user quiet and exact display receipt',async()=>{
  const quiet=deferred();const h=harness({waitAt:'quiet',waitForReplyQuiet:()=>quiet.promise});
  try {await h.start();assert.equal(h.receipts.filter(r=>r.effect_id.startsWith('2222')).length,0);
    assert.equal(h.calls.filter(c=>c.url.includes('/story-images/')).length,0);
    quiet.resolve(true);await until(()=>!h.slots.get('photo').hidden);
    assert.equal(h.receipts.filter(r=>r.effect_id.startsWith('2222')).length,1);
  } finally {quiet.resolve(false);await h.close();}
});

test('R2 generated picture waits for reply audio and typed draft',async()=>{
  let busy=true,draft=true;const h=harness({waitAt:'quiet',replyBusy:()=>busy,userInputPending:()=>draft});
  try {await h.start();assert.equal(h.receipts.filter(r=>r.effect_id.startsWith('2222')).length,0);
    busy=false;h.install({});await settle();assert.equal(h.receipts.filter(r=>r.effect_id.startsWith('2222')).length,0);
    draft=false;h.install({});await until(()=>!h.slots.get('photo').hidden);
  } finally {await h.close();}
});

test('R2 reply-only interrupt preserves background display even without next input',async()=>{
  const quiet=deferred();const h=harness({waitAt:'quiet',waitForReplyQuiet:()=>quiet.promise});
  try {await h.start();h.controller.interruptReply();
    assert.equal(h.statuses.at(-1).dismissible,true);
    quiet.resolve(true);h.install({});await until(()=>!h.slots.get('photo').hidden);
    assert.equal(h.calls.filter(c=>c.url.endsWith('/stop')).length,0);
    assert.equal(h.receipts.filter(r=>r.effect_id.startsWith('2222')).length,1);
  } finally {quiet.resolve(false);await h.close();}
});

test('R2 fixed close fences only fixed photo while current generated grant stays permitted',()=>{
  const gate=new PresentationGate('session','client');gate.beginInput('request');
  const generated=photo();const fixed={...generated,id:'fixed',value:'trip_photo'};
  gate.install(snapshot([fixed,generated]));gate.dismissPhoto('fixed_photo');
  assert.equal(gate.allows(fixed),false);assert.equal(gate.allows(generated),true);
});


for(const outcome of ['accepted','transport_failure']) test(`R2 completion waits for saved display and gap once: ${outcome}`,async()=>{
  const saved=deferred();let draft=false;
  const h=harness({completion:true,receiptBarrier:saved,completionError:outcome==='transport_failure',userInputPending:()=>draft});
  try {await h.start();assert.equal(h.calls.filter(c=>c.url.endsWith('/story-image-completions')).length,0);
    draft=true;saved.resolve();await settle();assert.equal(h.calls.filter(c=>c.url.endsWith('/story-image-completions')).length,0);
    draft=false;h.install({});await settle();assert.equal(h.calls.filter(c=>c.url.endsWith('/story-image-completions')).length,1);
    h.install({});h.install({});await settle();assert.equal(h.calls.filter(c=>c.url.endsWith('/story-image-completions')).length,1);
    assert.equal(h.slots.get('photo').hidden,false);
  }finally{saved.resolve();await h.close();}
});

test('R2 closing fixed display does not abort already preparing generated resource',async()=>{
  const bytes=deferred();
  const h=harness({waitAt:'fetch',fetchResponse:()=>bytes.promise,grants:grant=>[
    {...grant,id:'33333333-3333-4333-8333-333333333333',value:'trip_photo'},grant]});
  try {await h.start();assert.equal(h.slots.get('photo').hidden,false);
    await h.controller.dismissPhoto('fixed_photo');assert.equal(h.slots.get('photo').hidden,true);
    bytes.resolve(imageResponse());await until(()=>h.receipts.some(r=>r.effect_id.startsWith('2222')));
    assert.equal(h.slots.get('photo').hidden,false);
    const body=JSON.parse(h.calls.find(c=>c.url.endsWith('/photo-dismissals')).init.body);
    assert.equal(body.target,'fixed_photo');assert.equal(body.expected_image_request_id,null);
  }finally{bytes.resolve(imageResponse());await h.close();}
});
