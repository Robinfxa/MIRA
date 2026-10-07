import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const dist = process.env.MIRA_TEST_WEB_DIST
  ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href
  : new URL('../../apps/web/dist/', import.meta.url).href;
const { SessionController } = await import(new URL('features/session/controller.js', dist));
const { SceneEffectExecutor } = await import(new URL('features/presentation/scene-executor.js', dist));
const tick = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 5; i++) await tick(); };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const photo = (activity) => ({
  id: 'photo-effect', kind: 'media', value: 'trip_photo', digest: 'a'.repeat(64),
  output_epoch: activity, activity_seq: activity,
});

function makeImage({ complete = false, naturalWidth = 0, naturalHeight = 0, decode = null } = {}) {
  const listeners = new Map();
  return {
    complete, naturalWidth, naturalHeight, decodeCalls: 0, listeners,
    decode() { this.decodeCalls++; return decode?.promise ?? Promise.resolve(); },
    addEventListener(name, callback) {
      const callbacks = listeners.get(name) ?? new Set();
      callbacks.add(callback); listeners.set(name, callbacks);
    },
    removeEventListener(name, callback) { listeners.get(name)?.delete(callback); },
    dispatch(name) { for (const callback of [...(listeners.get(name) ?? [])]) callback({ type: name }); },
    listenerCount() { return [...listeners.values()].reduce((count, callbacks) => count + callbacks.size, 0); },
  };
}

function harness(image, { timeoutMs = 30, prepareImpl = null, mediaCount = 1 } = {}) {
  let client = '', revision = 0, current = null;
  const receipts = [], inputs = [], errors = [], applied = [];
  const slots = new Map(['subtitle', 'photo', 'pose', 'scene-label', 'phase-label', 'character-description']
    .map(name => [name, { textContent: '', hidden: name === 'photo' }]));
  const root = {
    dataset: {},
    querySelector(selector) {
      if (selector === '[data-photo] img') return image;
      return slots.get(selector.replace(/^\[data-|\]$/g, '')) ?? null;
    },
  };
  const effects = new SceneEffectExecutor(root, { mediaReadinessTimeoutMs: timeoutMs });
  const state = (activity, { phase = 'stopped', requestId = null, grants = [] } = {}) => ({
    schema_version: '0.1.0-foundation', session_id: 'media-readiness', client_instance_id: client,
    revision: ++revision, activity_seq: activity, input_epoch: activity, output_epoch: activity,
    permit_revision: revision, phase, request_id: requestId, sealed: true,
    active_grants: grants, presented_effects: [], audio_progress: [], last_error: null,
  });
  const api = {
    async create(clientId) { client = clientId; return { session: state(0), session_token: 'synthetic-only' }; },
    async capabilities() { return { generation_mode: 'rehearsal', speech_enabled: false, microphone_enabled: false, qualification: 'offline_fixture' }; },
    snapshot() { return new Promise(() => {}); },
    async input(request) {
      inputs.push(request.text);
      current = state(request.activity_seq, {
        phase: 'ready', requestId: request.request_id,
        grants: request.text === '看照片'
          ? Array.from({ length: mediaCount }, (_, index) => ({ ...photo(request.activity_seq),
            id: mediaCount === 1 ? (request.activity_seq === 1 ? 'photo-effect' : `photo-effect-${request.activity_seq}`)
              : `photo-effect-${request.activity_seq}-${index + 1}` }))
          : [],
      });
      return current;
    },
    async receipt(receipt) {
      receipts.push({ ...receipt, hidden: slots.get('photo').hidden,
        complete: image.complete, naturalWidth: image.naturalWidth });
      return current;
    },
    async audioProgress() { return current; },
    async stop(request) { current = state(request.activity_seq); return current; },
    async close() {},
  };
  const controller = new SessionController(api, {
    apply(effect) { applied.push(effect.id); effects.apply(effect); },
    prepare: prepareImpl ?? ((...args) => effects.prepare(...args)),
    prepareInput: () => effects.prepareInput(), stop: () => effects.stop(),
    setPhase: phase => effects.setPhase(phase),
  }, {
    connected() {}, update() {}, error(message) { if (message) errors.push(message); }, localStop() {},
  }, { apiBase: '/api/v1', pollIntervalMs: 999999 }, {
    createPlayback: () => ({ unlock: async () => true, open: () => null, stop() {}, reconcileAuthorization() {}, close: async () => {} }),
    createCapture: () => ({ start: async () => false, stop() {}, close: async () => {} }),
  });
  return {
    controller, api, effects, root, slots, image, receipts, inputs, errors, applied,
    async startPhoto() { await controller.connect(); await controller.input('看照片'); await settle(); },
    async stop() { await controller.stop(); await settle(); },
    async close() { await controller.close(); },
    get current() { return current; },
  };
}

test('photo remains hidden until an already-loaded image is decoded, then receives one receipt', async () => {
  const decode = deferred();
  const h = harness(makeImage({ complete: true, naturalWidth: 600, naturalHeight: 460, decode }));
  try {
    await h.startPhoto();
    assert.equal(h.image.decodeCalls, 1);
    assert.equal(h.slots.get('photo').hidden, true);
    assert.deepEqual(h.receipts, []);
    decode.resolve();
    await settle();
    assert.equal(h.slots.get('photo').hidden, false);
    assert.deepEqual(h.receipts.map(item => [item.effect_id, item.hidden, item.complete, item.naturalWidth]),
      [['photo-effect', false, true, 600]]);
    await h.controller.install({ ...h.current, revision: h.current.revision + 1 });
    await h.controller.install({ ...h.current, revision: h.current.revision + 2 });
    await settle();
    assert.equal(h.applied.filter(id => id === 'photo-effect').length, 1);
    assert.equal(h.receipts.length, 1);
    await h.stop();
    assert.equal(h.slots.get('photo').hidden, false, 'a ready, presented photo survives Stop');
  } finally { await h.close(); }
});

test('a pending image stays hidden and Stop fences a late load without receipt', async () => {
  const image = makeImage();
  const h = harness(image);
  try {
    await h.startPhoto();
    assert.equal(h.slots.get('photo').hidden, true);
    assert.equal(h.receipts.length, 0);
    assert.ok(image.listenerCount() > 0);
    await h.stop();
    image.complete = true; image.naturalWidth = 600; image.naturalHeight = 460;
    image.dispatch('load');
    await settle();
    assert.equal(h.slots.get('photo').hidden, true);
    assert.equal(h.receipts.length, 0);
  } finally { await h.close(); }
});

test('new input fences an old pending image from filling the scene or receipt history', async () => {
  const image = makeImage();
  const h = harness(image);
  try {
    await h.startPhoto();
    await h.controller.input('照片里有什么');
    image.complete = true; image.naturalWidth = 600; image.naturalHeight = 460;
    image.dispatch('load');
    await settle();
    assert.equal(h.slots.get('photo').hidden, true);
    assert.deepEqual(h.receipts, []);
    assert.deepEqual(h.inputs, ['看照片', '照片里有什么']);
  } finally { await h.close(); }
});

test('broken, errored, or timed-out media fails closed with safe actionable feedback', async t => {
  await t.test('already complete but broken', async () => {
    const h = harness(makeImage({ complete: true, naturalWidth: 0 }));
    try {
      await h.startPhoto();
      assert.equal(h.slots.get('photo').hidden, true);
      assert.deepEqual(h.receipts, []);
      assert.match(h.errors.at(-1), /插画.*重试|重试.*插画/);
    } finally { await h.close(); }
  });
  await t.test('load error', async () => {
    const image = makeImage();
    const h = harness(image);
    try {
      await h.startPhoto();
      image.dispatch('error');
      await settle();
      assert.equal(h.slots.get('photo').hidden, true);
      assert.deepEqual(h.receipts, []);
      assert.match(h.errors.at(-1), /插画.*重试|重试.*插画/);
    } finally { await h.close(); }
  });
  await t.test('decode error', async () => {
    const decode = deferred();
    const image = makeImage({ complete: true, naturalWidth: 600, naturalHeight: 460, decode });
    const h = harness(image);
    try {
      await h.startPhoto();
      decode.reject(new Error('untrusted browser detail'));
      await settle();
      assert.equal(h.slots.get('photo').hidden, true);
      assert.deepEqual(h.receipts, []);
      assert.match(h.errors.at(-1), /插画.*重试|重试.*插画/);
      assert.equal(h.errors.some(message => message.includes('untrusted browser detail')), false);
    } finally { await h.close(); }
  });
  await t.test('bounded timeout', async () => {
    const image = makeImage();
    const h = harness(image, { timeoutMs: 5 });
    try {
      await h.startPhoto();
      await new Promise(resolve => setTimeout(resolve, 15));
      await settle();
      assert.equal(h.slots.get('photo').hidden, true);
      assert.deepEqual(h.receipts, []);
      assert.match(h.errors.at(-1), /插画.*重试|重试.*插画/);
      image.complete = true; image.naturalWidth = 600; image.naturalHeight = 460;
      image.dispatch('load');
      await settle();
      assert.equal(h.slots.get('photo').hidden, true, 'a post-timeout load cannot revive the attempt');
      assert.deepEqual(h.receipts, []);
    } finally { await h.close(); }
  });
});

test('repeated snapshots and duplicate load events reuse one bounded preparation and receipt', async () => {
  const decode = deferred();
  const image = makeImage({ decode });
  const h = harness(image);
  try {
    await h.startPhoto();
    await h.controller.install({ ...h.current, revision: h.current.revision + 1 });
    await h.controller.install({ ...h.current, revision: h.current.revision + 2 });
    assert.equal(image.listenerCount(), 2, 'one load and one error listener for the unique effect');
    image.complete = true; image.naturalWidth = 600; image.naturalHeight = 460;
    image.dispatch('load'); image.dispatch('load'); image.dispatch('error');
    await tick();
    assert.equal(image.decodeCalls, 1);
    decode.resolve();
    await settle();
    assert.equal(h.slots.get('photo').hidden, false);
    assert.equal(h.applied.filter(id => id === 'photo-effect').length, 1);
    assert.equal(h.receipts.length, 1);
    assert.equal(image.listenerCount(), 0);
  } finally { await h.close(); }
});

test('permit revocation and close abort a pending image before a late load can present it', async t => {
  await t.test('revocation', async () => {
    const image = makeImage();
    const h = harness(image);
    try {
      await h.startPhoto();
      h.controller.install({ ...h.current, revision: h.current.revision + 1,
        permit_revision: h.current.permit_revision + 1, active_grants: [] });
      image.complete = true; image.naturalWidth = 600; image.naturalHeight = 460;
      image.dispatch('load');
      await settle();
      assert.equal(h.slots.get('photo').hidden, true);
      assert.deepEqual(h.receipts, []);
    } finally { await h.close(); }
  });
  await t.test('close', async () => {
    const image = makeImage();
    const h = harness(image);
    await h.startPhoto();
    await h.close();
    image.complete = true; image.naturalWidth = 600; image.naturalHeight = 460;
    image.dispatch('load');
    await settle();
    assert.equal(h.slots.get('photo').hidden, true);
    assert.deepEqual(h.receipts, []);
  });
});

test('late uncooperative preparation callback cannot show or receipt after Stop', async () => {
  const preparation = deferred();
  let signal;
  const image = makeImage();
  const h = harness(image, { prepareImpl: (_effect, abortSignal) => { signal = abortSignal; return preparation.promise; } });
  try {
    await h.startPhoto();
    assert.equal(h.slots.get('photo').hidden, true);
    await h.stop();
    assert.equal(signal.aborted, true);
    preparation.resolve();
    await settle();
    assert.equal(h.slots.get('photo').hidden, true);
    assert.deepEqual(h.receipts, []);
  } finally { await h.close(); }
});

test('aborting a decode wait does not start unbounded duplicate browser decodes', async () => {
  const decode = deferred();
  const image = makeImage({ complete: true, naturalWidth: 600, naturalHeight: 460, decode });
  const h = harness(image);
  const first = new AbortController();
  try {
    const cancelled = h.effects.prepare(photo(1), first.signal);
    await tick();
    assert.equal(image.decodeCalls, 1);
    first.abort();
    await assert.rejects(cancelled, error => error.name === 'AbortError');
    const second = h.effects.prepare(photo(2), new AbortController().signal);
    await tick();
    assert.equal(image.decodeCalls, 1, 'an unabortable pending decode is shared, not duplicated');
    decode.resolve();
    await second;
    assert.equal(image.decodeCalls, 1);
  } finally { await h.close(); }
});

test('a transient decode rejection can recover on a later input without stale reveal or receipt', async () => {
  const image = makeImage({ complete: true, naturalWidth: 600, naturalHeight: 460 });
  image.decode = function () {
    this.decodeCalls++;
    return this.decodeCalls === 1
      ? Promise.reject(new Error('synthetic transient decode failure'))
      : Promise.resolve();
  };
  const h = harness(image);
  try {
    await h.startPhoto();
    assert.equal(image.decodeCalls, 1);
    assert.equal(h.slots.get('photo').hidden, true);
    assert.deepEqual(h.receipts, []);
    assert.match(h.errors.at(-1), /插画.*重试|重试.*插画/);

    await h.controller.input('看照片');
    await settle();
    assert.equal(image.decodeCalls, 2, 'a later attempt starts a fresh decode after the prior rejection settled');
    assert.equal(h.slots.get('photo').hidden, false);
    assert.deepEqual(h.applied, ['photo-effect-2']);
    assert.deepEqual(h.receipts.map(item => item.effect_id), ['photo-effect-2']);
  } finally { await h.close(); }
});

test('media preparation stays strictly serial and Stop cancels the current grant', async () => {
  const pending = [];
  const started = [];
  const image = makeImage();
  const h = harness(image, {
    mediaCount: 9,
    prepareImpl: (effect, signal) => {
      const task = deferred();
      started.push({ effect, signal }); pending.push(task);
      return task.promise;
    },
  });
  try {
    await h.startPhoto();
    assert.equal(started.length, 1, 'the earliest media grant owns the preparation lane');
    assert.equal(h.slots.get('photo').hidden, true);
    assert.deepEqual(h.receipts, []);
    await h.controller.install({ ...h.current, revision: h.current.revision + 1 });
    await settle();
    assert.equal(started.length, 1, 'repeated snapshots cannot duplicate or pass pending work');
    await h.stop();
    assert.ok(started[0].signal.aborted);
    pending.forEach(task => task.resolve());
    await settle();
    assert.equal(h.slots.get('photo').hidden, true);
    assert.deepEqual(h.receipts, []);
  } finally { await h.close(); }
});

test('failed media stays out of frontend history when the next photo question begins', async () => {
  const image = makeImage({ complete: true, naturalWidth: 0 });
  const h = harness(image);
  try {
    await h.startPhoto();
    assert.deepEqual(h.receipts, []);
    await h.controller.input('照片里有什么');
    await settle();
    assert.deepEqual(h.inputs, ['看照片', '照片里有什么']);
    assert.equal(h.slots.get('photo').hidden, true);
    assert.deepEqual(h.receipts, []);
  } finally { await h.close(); }
});
