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

function harness(image, { timeoutMs = 30, prepareImpl = null, mediaCount = 1, microphoneEnabled = false } = {}) {
  let client = '', revision = 0, current = null;
  const receipts = [], inputs = [], errors = [], applied = [], dismissals = [];
  const calls = {playbackStop: 0, captureStop: 0, globalStop: 0, microphoneCancel: 0};
  let microphoneSignal;
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
    active_grants: grants, photo_visible: false, photo_visibility_revision: 0, presented_effects: [], audio_progress: [], last_error: null,
  });
  const api = {
    async create(clientId) { client = clientId; return { session: state(0), session_token: 'synthetic-only' }; },
    async capabilities() { return { generation_mode: 'rehearsal', speech_enabled: false, microphone_enabled: microphoneEnabled, qualification: 'offline_fixture' }; },
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
    microphone(_origin, signal) {
      microphoneSignal = signal;
      return {ready: Promise.resolve(), completion: new Promise(() => {}),
        send() {}, finish: async () => ({text: '', had_final: false}),
        cancel() { calls.microphoneCancel++; }};
    },
    async dismissPhoto(request) {
      dismissals.push(request);
      current = {...current, revision: ++revision, permit_revision: revision,
        photo_visible: false, photo_visibility_revision: request.expected_revision + 1,
        active_grants: current.active_grants.filter(effect => effect.kind !== 'media')};
      return current;
    },
    async audioProgress() { return current; },
    async stop(request) { current = state(request.activity_seq); return current; },
    async close() {},
  };
  const controller = new SessionController(api, {
    apply(effect) { applied.push(effect.id); effects.apply(effect); },
    prepare: prepareImpl ?? ((...args) => effects.prepare(...args)),
    dismissPhoto: () => effects.dismissPhoto(),
    prepareInput: () => effects.prepareInput(), stop: () => effects.stop(),
    setPhase: phase => effects.setPhase(phase),
  }, {
    connected() {}, update() {}, error(message) { if (message) errors.push(message); }, localStop() {},
  }, { apiBase: '/api/v1', pollIntervalMs: 999999 }, {
    createPlayback: () => ({ unlock: async () => true, open: () => null, stop() { calls.playbackStop++; }, reconcileAuthorization() {}, close: async () => {} }),
    onGlobalStop: () => calls.globalStop++,
    createCapture: () => ({ start: async () => microphoneEnabled, stop() { calls.captureStop++; }, close: async () => {} }),
  });
  return {
    controller, api, effects, root, slots, image, receipts, inputs, errors, applied, dismissals, calls,
    async startPhoto() { await controller.connect(); await controller.input('看照片'); await settle(); },
    async stop() { await controller.stop(); await settle(); },
    async close() { await controller.close(); },
    get current() { return current; },
    get microphoneSignal() { return microphoneSignal; },
  };
}

test('pending decode close is immediate, fences late callbacks and preserves unrelated lifecycle', async () => {
  const decode = deferred();
  const h = harness(makeImage({complete: true, naturalWidth: 600, naturalHeight: 460, decode}), {timeoutMs: 1000});
  try {
    await h.startPhoto();
    const before = {...h.calls};
    const closing = h.controller.dismissPhoto();
    assert.equal(h.slots.get('photo').hidden, true);
    assert.deepEqual(h.calls, before, 'dismissal does not stop playback, capture or global activity');
    await closing;
    decode.resolve(); await settle();
    assert.deepEqual(h.receipts, []);
    assert.equal(h.dismissals.length, 1);
    assert.equal(h.slots.get('photo').hidden, true);
    await h.controller.install({...h.current, revision: h.current.revision + 1,
      permit_revision: h.current.permit_revision + 1, active_grants: [photo(1)]});
    await settle();
    assert.equal(h.slots.get('photo').hidden, true, 'later same-turn grant cannot resurrect');
    await h.controller.stop();
    await h.controller.input('看照片'); await settle();
    assert.equal(h.slots.get('photo').hidden, false, 'later new turn may show again');
    assert.equal(h.receipts.length, 1);
  } finally { await h.close(); }
});

test('shown close is synchronous and repeated clicks share one update; later show retains history', async () => {
  const h = harness(makeImage({complete: true, naturalWidth: 600, naturalHeight: 460}));
  try {
    await h.startPhoto();
    assert.equal(h.slots.get('photo').hidden, false);
    const historical = structuredClone(h.receipts);
    const pending = deferred();
    const actual = h.api.dismissPhoto.bind(h.api);
    h.api.dismissPhoto = request => pending.promise.then(() => actual(request));
    const before = {...h.calls};
    const first = h.controller.dismissPhoto();
    const duplicate = h.controller.dismissPhoto();
    assert.equal(h.slots.get('photo').hidden, true);
    assert.deepEqual(h.calls, before);
    const next = h.controller.input('看照片');
    await settle();
    assert.equal(h.inputs.length, 1, 'next input waits for the dismissal fact');
    pending.resolve(); await Promise.all([first, duplicate, next]); await settle();
    assert.equal(h.dismissals.length, 1);
    assert.equal(h.dismissals[0].presentation_cutoff, 1);
    assert.equal(h.slots.get('photo').hidden, false);
    assert.deepEqual(h.receipts.slice(0, 1), historical);
    assert.equal(h.receipts.length, 2);
  } finally { await h.close(); }
});


test('close with active microphone leaves capture, transport, phase, and draft owners running', async () => {
 const h=harness(makeImage({complete:true,naturalWidth:600,naturalHeight:460}),{microphoneEnabled:true});
 try {
  await h.startPhoto();await h.controller.startMicrophone();await settle();
  assert.equal(h.controller.microphoneBusy,true);assert.equal(h.microphoneSignal.aborted,false);
  const before={...h.calls};await h.controller.dismissPhoto();await settle();
  assert.equal(h.slots.get('photo').hidden,true);
  assert.equal(h.controller.microphoneBusy,true);assert.equal(h.microphoneSignal.aborted,false);
  assert.deepEqual(h.calls,before);
 } finally {await h.close();}
});

test('failed photo sync stays locally hidden without stopping speech/mic owners', async () => {
 const h=harness(makeImage({complete:true,naturalWidth:600,naturalHeight:460}));
 try {
  await h.startPhoto();const before={...h.calls};
  h.api.dismissPhoto=async()=>{throw new Error('private transport detail');};
  await h.controller.dismissPhoto();assert.deepEqual(h.calls,before);
  assert.equal(h.slots.get('photo').hidden,true);
  assert.match(h.errors.at(-1),/状态同步未确认/);
  assert.equal(h.errors.some(message=>message.includes('private transport')),false);
  const next=await h.controller.input('看照片');
  assert.equal(next.status,'not-sent');assert.equal(next.reason,'history-failed');
  assert.equal(h.inputs.length,1);
 } finally {await h.close();}
});
