import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const dist = process.env.MIRA_TEST_WEB_DIST
  ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href
  : new URL('../../apps/web/dist/', import.meta.url).href;
const { SessionController } = await import(new URL('features/session/controller.js', dist));
const tick = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await tick(); };
const deferred = () => {
  let complete, fail, settled = false;
  const promise = new Promise((yes, no) => { complete = yes; fail = no; });
  return {
    promise,
    resolve(value) { if (!settled) { settled = true; complete(value); } },
    reject(error) { if (!settled) { settled = true; fail(error); } },
    get settled() { return settled; },
  };
};
const effect = (id, kind, value = id) => ({ id, kind, value, digest: 'a'.repeat(64),
  output_epoch: 1, activity_seq: 1, cue_id: null, cue_speech_id: null });

function harness(grantsForInput, { prepare = true, speechEnabled = false } = {}) {
  let clientId = '', revision = 0, current = null;
  let submitPcm = null;
  const started = [], shown = [], receipts = [], errors = [], applied = [];
  const tasks = new Map();
  const state = (activity, { grants = [], phase = 'stopped', requestId = null } = {}) => ({
    schema_version: '0.1.0-foundation', session_id: 'ordered-visuals', client_instance_id: clientId,
    revision: ++revision, activity_seq: activity, input_epoch: activity, output_epoch: activity,
    permit_revision: revision, phase, request_id: requestId, sealed: true,
    active_grants: grants.map(grant => ({ ...grant, activity_seq: activity, output_epoch: activity })),
    presented_effects: [], audio_progress: [], last_error: null,
  });
  const api = {
    async create(id) { clientId = id; current = state(0); return { session: current, session_token: 'synthetic-only' }; },
    async capabilities() { return { generation_mode: speechEnabled ? 'injected' : 'rehearsal', speech_enabled: speechEnabled,
      microphone_enabled: false, qualification: 'offline_fixture' }; },
    snapshot() { return new Promise(() => {}); },
    async input(request) {
      current = state(request.activity_seq, { grants: grantsForInput(request.text), phase: 'ready', requestId: request.request_id });
      return current;
    },
    async receipt(value) { receipts.push(value); return current; },
    async audioProgress() { return current; },
    async speech(_grant, _signal, push) { submitPcm = push; return new Promise(() => {}); },
    async stop(request) { current = state(request.activity_seq); return current; },
    async close() {},
  };
  const executor = {
    apply(grant) { applied.push(grant.id); shown.push(grant.id); },
    prepareInput() {}, stop() {}, setPhase() {},
  };
  if (prepare) executor.prepare = (grant, signal) => {
      const task = deferred();
      started.push({ id: grant.id, kind: grant.kind, signal, task });
      tasks.set(grant.id, task);
      return task.promise;
    };
  const controller = new SessionController(api, executor, {
    connected() {}, update() {}, error(value) { if (value) errors.push(value); }, localStop() {},
  }, { apiBase: '/api/v1', pollIntervalMs: 999999 }, {
    createPlayback: options => ({ unlock: async () => true, open: grant => ({
      push(pcm) {
        options.onFact({ origin: grant, stage: 'submitted', sampleRate: 24000,
          submittedFrames: pcm.length, renderedFrames: 0, inFlightFramesUncertain: pcm.length });
        return true;
      },
      finish: () => true,
    }), stop() {},
      reconcileAuthorization() {}, close: async () => {} }),
    createCapture: () => ({ start: async () => false, stop() {}, close: async () => {} }),
  });
  return {
    controller, api, started, shown, receipts, errors, applied, tasks,
    get current() { return current; },
    async start() { await controller.connect(); },
    async input(text) { await controller.input(text); await settle(); },
    async stop() { await controller.stop(); await settle(); },
    async close() { await controller.close(); },
    install(snapshot) { revision = Math.max(revision, snapshot.revision); controller.install(snapshot); },
    async submitSpeechSample() {
      assert.equal(typeof submitPcm, 'function', 'startSpeech must remain free to begin while a visual prepares');
      await submitPcm(new Int16Array(2));
      await settle();
    },
  };
}

test('prepared visuals serialize in grant order through apply and receipt despite repeated snapshots', async () => {
  const h = harness(() => [effect('pose', 'pose', 'camera_lowered'),
    effect('caption', 'subtitle', 'A caption'), effect('scene', 'scene', 'rain_window')]);
  try {
    await h.start();
    await h.input('visuals');
    assert.deepEqual(h.started.map(run => run.id), ['pose']);
    assert.deepEqual(h.applied, []);

    for (let i = 0; i < 3; i++) h.install({ ...h.current, revision: h.current.revision + 1 });
    await settle();
    assert.deepEqual(h.started.map(run => run.id), ['pose'], 'polling must not duplicate or bypass an unresolved preparation');
    assert.deepEqual(h.applied, []);

    h.tasks.get('pose').resolve();
    await settle();
    assert.deepEqual(h.applied, ['pose']);
    assert.deepEqual(h.started.map(run => run.id), ['pose', 'caption']);
    assert.deepEqual(h.receipts.map(receipt => receipt.effect_id), ['pose']);

    h.tasks.get('caption').resolve();
    await settle();
    assert.deepEqual(h.applied, ['pose', 'caption']);
    assert.deepEqual(h.started.map(run => run.id), ['pose', 'caption', 'scene']);
    assert.deepEqual(h.receipts.map(receipt => receipt.effect_id), ['pose', 'caption']);

    h.tasks.get('scene').resolve();
    await settle();
    assert.deepEqual(h.applied, ['pose', 'caption', 'scene']);
    assert.deepEqual(h.receipts.map(receipt => receipt.effect_id), ['pose', 'caption', 'scene']);
  } finally { await h.close(); }
});

test('a cue caption newly eligible on audio submission preempts later pending scene preparation', async () => {
  const speech = { ...effect('speech-source', 'speech', 'spoken words'), cue_id: 'cue-1', cue_speech_id: 'speech-source' };
  const caption = { ...effect('cue-caption', 'subtitle', 'submitted words'), cue_id: 'cue-1', cue_speech_id: 'speech-source' };
  const h = harness(() => [speech, caption,
    { ...effect('later-scene', 'scene', 'rain_window'), cue_id: 'visual-cue', cue_speech_id: null }], { speechEnabled: true });
  try {
    await h.start();
    await h.input('speak and set scene');
    assert.deepEqual(h.started.map(run => run.id), ['later-scene'], 'cue caption is not prepared before audio source submission');
    const laterScene = h.started[0];
    assert.equal(typeof h.submitSpeechSample, 'function');

    await h.submitSpeechSample();
    assert.equal(laterScene.signal.aborted, true, 'the newly eligible earlier caption cancels later staging');
    assert.deepEqual(h.started.map(run => run.id), ['later-scene', 'cue-caption']);
    assert.deepEqual(h.applied, []);
    assert.deepEqual(h.receipts, []);

    h.started[1].task.resolve();
    await settle();
    assert.deepEqual(h.applied, ['cue-caption']);
    assert.deepEqual(h.receipts.map(receipt => receipt.effect_id), ['cue-caption']);

    laterScene.task.resolve();
    await settle();
    assert.deepEqual(h.started.map(run => run.id), ['later-scene', 'cue-caption', 'later-scene']);
    h.started[2].task.resolve();
    await settle();
    assert.deepEqual(h.applied, ['cue-caption', 'later-scene']);
    assert.deepEqual(h.receipts.map(receipt => receipt.effect_id), ['cue-caption', 'later-scene']);
  } finally { await h.close(); }
});

test('failed preparation is reported once and does not restart on repeated snapshots', async () => {
  const h = harness(() => [effect('bad-pose', 'pose', 'unavailable_pose')]);
  try {
    await h.start();
    await h.input('visuals');
    assert.equal(h.started.length, 1);
    h.tasks.get('bad-pose').reject(new Error('private renderer detail'));
    await settle();
    for (let i = 0; i < 4; i++) h.install({ ...h.current, revision: h.current.revision + 1 });
    await settle();
    assert.equal(h.started.length, 1);
    assert.equal(h.errors.length, 1);
    assert.equal(h.errors.some(message => message.includes('private renderer detail')), false);
    assert.deepEqual(h.applied, []);
    assert.deepEqual(h.receipts, []);
  } finally { await h.close(); }
});

test('uncooperative callbacks across Stop and new inputs remain capped and resume the current grant', async () => {
  const h = harness(text => [effect(`visual-${text}`, 'media', `photo-${text}`)]);
  try {
    await h.start();
    await h.input('turn-1');
    assert.equal(h.started.length, 1);
    await h.stop();
    assert.equal(h.started[0].signal.aborted, true, 'Stop aborts the local run immediately');
    for (let i = 2; i <= 4; i++) {
      await h.input(`turn-${i}`);
      assert.equal(h.started.length, i);
      assert.equal(h.started[i - 2].signal.aborted, true, 'each newer input aborts its predecessor');
    }
    await h.input('turn-5');
    assert.equal(h.started.length, 4, 'ignored aborts must consume the shared preparation cap');
    assert.equal(h.started.filter(run => !run.task.settled).length, 4, 'all four outstanding callbacks are still counted');
    assert.equal(h.errors.length, 1, 'capacity feedback is bounded to one report per blocked grant');
    for (let i = 0; i < 3; i++) h.install({ ...h.current, revision: h.current.revision + 1 });
    await settle();
    assert.equal(h.started.length, 4, 'polling cannot duplicate or bypass the capacity-blocked first grant');
    assert.equal(h.errors.length, 1);

    h.tasks.get('visual-turn-1').resolve();
    await settle();
    assert.equal(h.started.length, 5);
    assert.equal(h.started.at(-1).id, 'visual-turn-5');
    assert.equal(h.started.filter(run => !run.task.settled).length, 4, 'settling one stale callback opens only one slot');
    assert.equal(h.started.filter(run => !run.signal.aborted).length, 1,
      'the current turn still has only one active preparation after the stale run releases');
    assert.deepEqual(h.applied, []);
    await h.stop();
    for (const run of h.started) run.task.resolve();
    await settle();
    assert.deepEqual(h.applied, []);
    assert.deepEqual(h.receipts, []);
  } finally { await h.close(); }
});

test('media stays fail-closed without prepare while older visual ports retain direct apply', async () => {
  const h = harness(() => [effect('photo-without-gate', 'media', 'trip_photo'),
    effect('pose-direct', 'pose', 'camera_lowered'), effect('scene-direct', 'scene', 'rain_window')], { prepare: false });
  try {
    await h.start();
    await h.input('mixed visuals');
    assert.deepEqual(h.started, []);
    assert.deepEqual(h.applied, ['pose-direct', 'scene-direct']);
    assert.deepEqual(h.receipts.map(receipt => receipt.effect_id), ['pose-direct', 'scene-direct']);
    assert.equal(h.errors.length, 1);
    h.install({ ...h.current, revision: h.current.revision + 1 });
    await settle();
    assert.equal(h.errors.length, 1, 'the media failure remains quiet on unchanged polls');
    assert.deepEqual(h.applied, ['pose-direct', 'scene-direct']);
  } finally { await h.close(); }
});

test('Stop, newer input, close, and snapshot revocation fence late preparation callbacks', async t => {
  const cases = [
    ['Stop', async h => h.stop()],
    ['new input', async h => h.input('newer')],
    ['close', async h => h.close()],
    ['snapshot revocation', async h => h.install({ ...h.current,
      revision: h.current.revision + 1, permit_revision: h.current.permit_revision + 1, active_grants: [] })],
  ];
  for (const [name, interrupt] of cases) await t.test(name, async () => {
    const h = harness(text => text === 'newer'
      ? [effect('new-scene', 'scene', 'new_scene')]
      : [effect('old-pose', 'pose', 'old_pose')]);
    try {
      await h.start();
      await h.input('first');
      const old = h.started[0];
      assert.equal(old.id, 'old-pose');
      await interrupt(h);
      assert.equal(old.signal.aborted, true);
      if (name === 'new input') {
        assert.deepEqual(h.started.map(run => run.id), ['old-pose', 'new-scene']);
        h.tasks.get('old-pose').resolve();
        await settle();
        assert.deepEqual(h.applied, []);
        h.tasks.get('new-scene').resolve();
        await settle();
        assert.deepEqual(h.applied, ['new-scene']);
        assert.deepEqual(h.receipts.map(receipt => receipt.effect_id), ['new-scene']);
      } else {
        h.tasks.get('old-pose').resolve();
        await settle();
        assert.deepEqual(h.applied, []);
        assert.deepEqual(h.receipts, []);
      }
    } finally { await h.close(); }
  });
});
