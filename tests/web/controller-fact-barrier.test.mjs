import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve } from 'node:path';

const dist = process.env.MIRA_TEST_WEB_DIST
  ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href
  : new URL('../../apps/web/dist/', import.meta.url).href;
const { MiraApiClient } = await import(new URL('features/session/api-client.js', dist));
const { SessionController } = await import(new URL('features/session/controller.js', dist));
const { SceneEffectExecutor } = await import(new URL('features/presentation/scene-executor.js', dist));
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const tick = (milliseconds = 0) => new Promise(resolve => setTimeout(resolve, milliseconds));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

async function freePort() {
  const server = createServer();
  await new Promise((resolve, reject) => server.once('error', reject).listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  return port;
}

function scrubbedEnvironment() {
  const env = { ...process.env };
  for (const name of Object.keys(env)) {
    if (name.startsWith('MIRA_') || name === 'PYTHONPATH' || name === 'PYTHONHOME'
      || ['OPENAI_API_KEY', 'TYPESAFE_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS', 'GOOGLE_CLOUD_PROJECT',
        'GOOGLE_CLOUD_QUOTA_PROJECT', 'CODEX_ACCESS_TOKEN', 'ACCESS_TOKEN', 'AZURE_OPENAI_API_KEY',
        'ANTHROPIC_API_KEY'].includes(name)) delete env[name];
  }
  return env;
}

async function startRehearsalServer() {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const child = spawn(process.env.MIRA_TEST_PYTHON ?? process.env.PYTHON ?? 'python3',
    ['tools/dev.py', '--serve', '--profile', 'rehearsal', '--port', String(port)], {
      cwd: ROOT, env: scrubbedEnvironment(), stdio: 'ignore',
    });
  const deadline = Date.now() + 12000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error('The local rehearsal HTTP test server exited during startup.');
    try {
      const response = await fetch(`${base}/api/v1/health`, { signal: AbortSignal.timeout(400) });
      if (response.ok) return { child, base };
    } catch { /* Wait for the loopback-only service to finish starting. */ }
    await tick(20);
  }
  child.kill('SIGTERM');
  throw new Error('The local rehearsal HTTP test server did not become ready.');
}

async function stopServer(child) {
  if (child.exitCode !== null || child.killed) return;
  child.kill('SIGTERM');
  await Promise.race([
    new Promise(resolve => child.once('exit', resolve)),
    tick(1500).then(() => { if (child.exitCode === null) child.kill('SIGKILL'); }),
  ]);
}

async function waitFor(predicate, label, timeoutMs = 4000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await predicate();
    if (value) return value;
    await tick(10);
  }
  throw new Error(`Timed out waiting for ${label}.`);
}

function sceneHarness() {
  const slots = new Map(['subtitle', 'photo', 'pose', 'scene-label', 'phase-label', 'character-description']
    .map(name => [name, { textContent: '', hidden: name === 'photo' }]));
  const image = { complete: true, naturalWidth: 640, naturalHeight: 480, decode: async () => {} };
  const root = {
    dataset: {},
    querySelector(selector) {
      if (selector === '[data-photo] img') return image;
      return slots.get(selector.replace(/^\[data-|\]$/g, '')) ?? null;
    },
  };
  return { slots, image, root, effects: new SceneEffectExecutor(root, { mediaReadinessTimeoutMs: 500 }) };
}

function rehearsalPlayback() {
  return options => {
    let active = null;
    const terminal = reason => {
      const origin = active;
      active = null;
      if (origin) options.onFact({ origin, stage: 'stopped', submittedFrames: 1, renderedFrames: 0,
        sampleRate: 24000, inFlightFramesUncertain: 1, reason });
    };
    return {
      unlock: async () => true,
      open(origin) {
        active = origin;
        return {
          push(pcm) {
            options.onFact({ origin, stage: 'submitted', submittedFrames: pcm.length, renderedFrames: 0,
              sampleRate: 24000, inFlightFramesUncertain: pcm.length });
            return true;
          },
          finish: () => true,
        };
      },
      stop: terminal,
      reconcileAuthorization() { if (active && !options.isAuthorized(active)) terminal('revoked'); },
      close: async () => terminal('close'),
    };
  };
}

function viewPort() {
  return {
    connected() {}, update() {}, error() {}, localStop() {},
    capabilities() {}, rehearsalInput() {}, microphone() {},
  };
}

function subtitle(state) {
  return state.active_grants.find(effect => effect.kind === 'subtitle')?.value ?? '';
}

test('actual rehearsal HTTP waits for the pre-cutoff photo receipt before generating its follow-up', { timeout: 20000 }, async () => {
  const service = await startRehearsalServer();
  const releaseReceipt = deferred(), receiptStarted = deferred();
  const inputRequests = [], timeline = [];
  let heldReceipt = true;
  const fetcher = async (request, init = {}) => {
    const url = typeof request === 'string' ? request : request.url;
    const path = new URL(url).pathname;
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : null;
    if (path.endsWith('/inputs')) {
      inputRequests.push(body.text);
      timeline.push(`input:${body.text}`);
    } else if (path.endsWith('/stop')) {
      timeline.push(`stop:${body.presentation_cutoff}`);
    } else if (path.endsWith('/receipts')) {
      timeline.push(`receipt-request:${body.presentation_seq}`);
      if (heldReceipt) {
        const stateResponse = await fetch(url.slice(0, -'/receipts'.length), { headers: init.headers });
        const state = await stateResponse.json();
        const effect = state.active_grants.find(value => value.id === body.effect_id);
        if (effect?.kind === 'media') {
          receiptStarted.resolve(body);
          await releaseReceipt.promise;
          heldReceipt = false;
        }
      }
    } else if (path.endsWith('/audio-progress')) {
      timeline.push(`progress-request:${body.presentation_seq}`);
    }
    const response = await fetch(url, init);
    if (path.endsWith('/receipts')) timeline.push(`receipt-ack:${body.presentation_seq}`);
    if (path.endsWith('/audio-progress')) timeline.push(`progress-ack:${body.presentation_seq}`);
    return response;
  };
  const api = new MiraApiClient({ apiBase: `${service.base}/api/v1` }, { fetch: fetcher });
  const scene = sceneHarness();
  const controller = new SessionController(api, scene.effects, viewPort(),
    { apiBase: `${service.base}/api/v1`, pollIntervalMs: 10 }, {
      createPlayback: rehearsalPlayback(),
      createCapture: () => ({ start: async () => false, stop() {}, close: async () => {} }),
      factDrainTimeoutMs: 1500,
    });
  let followup;
  try {
    await controller.connect();
    await controller.input('看照片');
    await waitFor(async () => {
      const state = await api.snapshot();
      return state.sealed && state.active_grants.some(effect => effect.kind === 'media') ? state : null;
    }, 'the real photo turn to seal');
    const receipt = await Promise.race([
      receiptStarted.promise,
      tick(3500).then(() => { throw new Error('The decoded photo did not issue an HTTP receipt.'); }),
    ]);
    assert.ok(receipt.presentation_seq > 0);
    assert.equal(scene.slots.get('photo').hidden, false, 'the decoded local illustration is visibly applied before receipt');

    const stopped = controller.stop();
    await Promise.race([stopped, tick(3000).then(() => { throw new Error('Stop waited on the delayed presentation receipt.'); })]);
    const stopRecord = timeline.find(item => item.startsWith('stop:'));
    assert.equal(stopRecord, `stop:${receipt.presentation_seq + 1}`,
      'photo receipt and terminal audio progress are both covered by the Stop cutoff');

    followup = controller.input('照片里有什么');
    await tick(120);
    if (inputRequests.includes('照片里有什么')) {
      const premature = await waitFor(async () => {
        const state = await api.snapshot();
        return state.activity_seq === 3 && state.sealed ? state : null;
      }, 'the raced HTTP turn to finish');
      assert.match(subtitle(premature), /画面还留在这里/, `the actual HTTP flow returned ${JSON.stringify(subtitle(premature))} before its valid photo receipt arrived`);
    }
    assert.equal(inputRequests.includes('照片里有什么'), false,
      'a new generation must remain local until the captured visual and audio facts have acknowledgements');

    releaseReceipt.resolve();
    await followup;
    const answer = await waitFor(async () => {
      const state = await api.snapshot();
      return state.activity_seq === 3 && state.sealed ? state : null;
    }, 'the follow-up based on accepted presentation history');
    assert.match(subtitle(answer), /画面还留在这里/);
    const receiptAck = timeline.indexOf(`receipt-ack:${receipt.presentation_seq}`);
    const progressRequest = timeline.indexOf(`progress-request:${receipt.presentation_seq + 1}`);
    const progressAck = timeline.indexOf(`progress-ack:${receipt.presentation_seq + 1}`);
    const followupRequest = timeline.indexOf('input:照片里有什么');
    assert.ok(receiptAck >= 0 && receiptAck < progressRequest, 'the real visual receipt is acknowledged first');
    assert.ok(progressRequest < progressAck && progressAck < followupRequest,
      'terminal audio progress stays serialized inside the same immutable cutoff prefix');
  } finally {
    releaseReceipt.resolve();
    if (followup) await Promise.race([followup.catch(() => {}), tick(1000)]);
    await controller.close();
    await stopServer(service.child);
  }
});

function pendingFactHarness({ timeoutMs = 100, rejectReceipt = false, microphone = false } = {}) {
  let clientId = '', revision = 0;
  const inputs = [], receipts = [], stops = [], errors = [];
  const receiptAck = deferred(), lateReceiptAck = deferred(), receiptStarted = deferred(), transcript = deferred();
  const state = (activity, patch = {}) => ({
    schema_version: '0.1.0-foundation', session_id: 'fact-barrier', client_instance_id: clientId,
    revision: ++revision, activity_seq: activity, input_epoch: activity, output_epoch: activity,
    permit_revision: revision, phase: 'stopped', request_id: null, sealed: true,
    active_grants: [], presented_effects: [], audio_progress: [], last_error: null, ...patch,
  });
  const api = {
    async create(value) { clientId = value; return { session: state(0), session_token: 'synthetic-only' }; },
    async capabilities() { return { generation_mode: 'rehearsal', speech_enabled: false,
      microphone_enabled: microphone, speech_sample_rate_hz: 24000, microphone_sample_rate_hz: 16000,
      qualification: 'offline_fixture' }; },
    snapshot() { return new Promise(() => {}); },
    async input(request) {
      inputs.push(request.text);
      const grants = request.text === 'first' ? [{ id: 'first-visual', kind: 'subtitle', value: 'first visual',
        digest: 'a'.repeat(64), output_epoch: request.activity_seq, activity_seq: request.activity_seq }] : [];
      return state(request.activity_seq, { phase: 'ready', request_id: request.request_id, active_grants: grants });
    },
    async stop(request) { stops.push(request); return state(request.activity_seq); },
    async receipt(request) {
      receipts.push(request);
      receiptStarted.resolve(request);
      if (rejectReceipt) throw new Error('synthetic receipt transport failure');
      return request.presentation_seq === 1 ? receiptAck.promise : lateReceiptAck.promise;
    },
    async audioProgress() { return state(0); },
    async close() {},
    async speech() {},
    microphone() {
      if (!microphone) throw new Error('microphone is not part of this test');
      return { ready: Promise.resolve(), completion: transcript.promise, send() {},
        finish: () => transcript.promise, cancel() {} };
    },
  };
  const controller = new SessionController(api, { apply() {}, prepareInput() {}, stop() {}, setPhase() {} }, {
    connected() {}, update() {}, error(message) { if (message) errors.push(message); }, localStop() {},
  }, { apiBase: '/api/v1', pollIntervalMs: 999999 }, {
    factDrainTimeoutMs: timeoutMs,
    createPlayback: () => ({ unlock: async () => true, open: () => null, stop() {},
      reconcileAuthorization() {}, close: async () => {} }),
    createCapture: () => ({ start: async () => microphone, stop() {}, close: async () => {} }),
  });
  return { api, controller, inputs, receipts, stops, errors, receiptAck, lateReceiptAck, receiptStarted, transcript,
    async start() { await controller.connect(); await controller.input('first'); await receiptStarted.promise; },
    async close() { await controller.close(); }, };
}

test('Stop stays immediate while a pre-cutoff fact is pending; new input waits for its ack', async () => {
  const h = pendingFactHarness();
  try {
    await h.start();
    const stopStarted = Date.now();
    await h.controller.stop();
    assert.ok(Date.now() - stopStarted < 250, 'local Stop and its request do not await the receipt');
    assert.equal(h.stops[0].presentation_cutoff, h.receipts[0].presentation_seq);
    const next = h.controller.input('second');
    await tick(20);
    assert.deepEqual(h.inputs, ['first']);
    h.receiptAck.resolve();
    await next;
    assert.deepEqual(h.inputs, ['first', 'second']);
  } finally { h.receiptAck.resolve(); await h.close(); }
});

test('the fact snapshot does not wait for a fact issued after the input cutoff', async () => {
  const h = pendingFactHarness({ timeoutMs: 1000 });
  try {
    await h.start();
    await h.controller.stop();
    const next = h.controller.input('second');
    await tick(5);
    h.controller.enqueueFact({ effect_id: 'post-cutoff', digest: 'b'.repeat(64), output_epoch: 3,
      activity_seq: 3, presentation_seq: 2 }, false, 3);
    await tick(5);
    h.receiptAck.resolve();
    await Promise.race([next, tick(100).then(() => { throw new Error('A post-cutoff fact blocked the captured prefix.'); })]);
    assert.deepEqual(h.inputs, ['first', 'second']);
    assert.deepEqual(h.receipts.map(fact => fact.presentation_seq), [1, 2]);
  } finally { h.receiptAck.resolve(); h.lateReceiptAck.resolve(); await h.close(); }
});

test('a final microphone transcript waits for the same pre-cutoff history before input dispatch', async () => {
  const h = pendingFactHarness({ microphone: true, timeoutMs: 1000 });
  try {
    await h.start();
    await h.controller.startMicrophone();
    const finishing = h.controller.finishMicrophone();
    h.transcript.resolve({ text: 'recognized question', had_final: true });
    await tick(10);
    assert.deepEqual(h.inputs, ['first']);
    h.receiptAck.resolve();
    const outcome = await finishing;
    assert.equal(outcome.status, 'submitted');
    assert.deepEqual(h.inputs, ['first', 'recognized question']);
  } finally { h.receiptAck.resolve(); h.lateReceiptAck.resolve(); await h.close(); }
});

test('a failed pre-cutoff receipt fails closed and never starts the next generation', async () => {
  const h = pendingFactHarness({ rejectReceipt: true });
  try {
    await h.start();
    await h.controller.stop();
    await h.controller.input('second');
    assert.deepEqual(h.inputs, ['first']);
    assert.match(h.errors.at(-1), /could not be confirmed.*fresh session/i);
  } finally { h.receiptAck.resolve(); await h.close(); }
});

test('fact drain timeout is bounded, reports a retryable error, and does not poison a later ack', async () => {
  const h = pendingFactHarness({ timeoutMs: 20 });
  try {
    await h.start();
    await h.controller.stop();
    const started = Date.now();
    await h.controller.input('second');
    assert.ok(Date.now() - started < 250);
    assert.deepEqual(h.inputs, ['first']);
    assert.match(h.errors.at(-1), /still waiting to be saved/i);
    h.receiptAck.resolve();
    await tick(5);
    await h.controller.input('third');
    assert.deepEqual(h.inputs, ['first', 'third']);
  } finally { h.receiptAck.resolve(); await h.close(); }
});

test('a newer rapid input releases a superseded waiter and only the newest request starts after ack', async () => {
  const h = pendingFactHarness({ timeoutMs: 1000 });
  try {
    await h.start();
    const older = h.controller.input('second');
    await tick(10);
    const newest = h.controller.input('third');
    await Promise.race([older, tick(100).then(() => { throw new Error('Superseded input did not release its waiter.'); })]);
    await tick(20);
    assert.deepEqual(h.inputs, ['first']);
    h.receiptAck.resolve();
    await newest;
    assert.deepEqual(h.inputs, ['first', 'third']);
  } finally { h.receiptAck.resolve(); await h.close(); }
});

test('closing while a fact barrier waits cancels the waiter without late input revival', async () => {
  const h = pendingFactHarness({ timeoutMs: 1000 });
  try {
    await h.start();
    const waiting = h.controller.input('second');
    await tick(10);
    await h.close();
    await Promise.race([waiting, tick(100).then(() => { throw new Error('Close did not release the fact waiter.'); })]);
    assert.deepEqual(h.inputs, ['first']);
    h.receiptAck.resolve();
    await tick(10);
    assert.deepEqual(h.inputs, ['first']);
  } finally { h.receiptAck.resolve(); await h.close(); }
});
