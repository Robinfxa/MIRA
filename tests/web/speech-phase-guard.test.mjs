import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const dist = process.env.MIRA_TEST_WEB_DIST
  ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href
  : new URL('../../apps/web/dist/', import.meta.url).href;
const { SessionController } = await import(new URL('features/session/controller.js', dist));
const { CancelSafePlayback } = await import(new URL('features/audio/playback.js', dist));
const tick = () => new Promise(resolve => setImmediate(resolve));
const voice = {speech_enabled: true, microphone_enabled: false, speech_sample_rate_hz: 24000,
  microphone_sample_rate_hz: 16000, qualification: 'injected_unverified', generation_mode: 'mock'};

function harness(createPlaybackImpl = null) {
  let clientId;
  let revision = 0;
  let submittedPush;
  let playbackOptions;
  let activeOrigin = null;
  const phases = [];
  const acceptedPackets = [];
  const effect = {id: 'speech-1', kind: 'speech', value: 'hello', digest: 'a'.repeat(64),
    output_epoch: 1, activity_seq: 1};
  const session = (patch = {}) => ({schema_version: '0.1.0-foundation', session_id: 's',
    client_instance_id: clientId, revision: ++revision, activity_seq: 0, input_epoch: 0,
    output_epoch: 0, permit_revision: revision, phase: 'stopped', request_id: null, sealed: true,
    active_grants: [], presented_effects: [], audio_progress: [], last_error: null, ...patch});
  const api = {
    create: async id => {clientId = id; return {session: session(), session_token: 'test-token'};},
    capabilities: async () => voice,
    snapshot: () => new Promise(() => {}),
    input: async request => session({activity_seq: 1, input_epoch: 1, output_epoch: 1,
      permit_revision: revision + 1, phase: 'ready', request_id: request.request_id,
      sealed: false, active_grants: [effect]}),
    stop: async request => session({activity_seq: request.activity_seq}),
    receipt: async () => session(),
    audioProgress: async () => session(),
    speech: async (_effect, _signal, push) => {submittedPush = push; await new Promise(() => {});},
    microphone: async () => {throw new Error('not used');},
    close: async () => {},
  };
  const playback = {
    unlock: async () => true,
    open: origin => {
      activeOrigin = origin;
      return {
        push: pcm => {
          acceptedPackets.push(pcm.length);
          playbackOptions.onFact({origin, stage: 'submitted', submittedFrames: pcm.length,
            renderedFrames: 0, sampleRate: 24000, inFlightFramesUncertain: pcm.length});
          return true;
        },
        finish: () => true,
      };
    },
    stop: () => {activeOrigin = null;},
    reconcileAuthorization: () => {},
    close: async () => {},
    get quiescent() {return activeOrigin === null;},
  };
  const effects = {apply() {}, prepareInput() {}, stop: () => phases.push('idle'),
    setPhase: phase => phases.push(phase)};
  const view = {connected() {}, update() {}, error() {}, localStop() {}, capabilities() {}};
  const controller = new SessionController(api, effects, view,
    {apiBase: '/api/v1', pollIntervalMs: 200}, {createPlayback: options => {
      playbackOptions = options;
      return createPlaybackImpl ? createPlaybackImpl(options) : playback;
    }});
  return {controller, phases, acceptedPackets, get gate() {return controller.gate;},
    get playbackOptions() {return playbackOptions;}, get submittedPush() {return submittedPush;}};
}

async function speakingRun() {
  const h = harness();
  await h.controller.connect();
  await tick();
  await h.controller.input('hello');
  await tick();
  assert.equal(typeof h.submittedPush, 'function', 'controller should have started the speech transport');
  return h;
}

function realSinkHarness() {
  const sources = [];
  const timers = new Set();
  const facts = [];
  const context = {destination: {}, resume: async () => {}, close: async () => {},
    createBuffer: (_channels, length) => ({getChannelData: () => new Float32Array(length)}),
    createBufferSource: () => {
      const source = {onended: null, started: false, stopped: 0, connect() {}, disconnect() {},
        start() {this.started = true;}, stop() {this.stopped++;}};
      sources.push(source);
      return source;
    }};
  const h = harness(options => new CancelSafePlayback({...options,
    onFact: fact => {facts.push(fact); options.onFact?.(fact);}, createContext: () => context,
    setInterval: callback => {timers.add(callback); return callback;}, clearInterval: callback => timers.delete(callback)}));
  return {controller: h.controller, phases: h.phases, acceptedPackets: h.acceptedPackets,
    get gate() {return h.gate;}, get playbackOptions() {return h.playbackOptions;},
    get submittedPush() {return h.submittedPush;}, sources, timers, facts};
}

test('rejected first submitted fact cannot present speaking without accepted playback', async () => {
  const h = await speakingRun();
  const invalid = {origin: {id: 'speech-1', digest: 'a'.repeat(64), activity_seq: 1, output_epoch: 1},
    stage: 'submitted', submittedFrames: 0, renderedFrames: 0, sampleRate: 24000, inFlightFramesUncertain: 0};
  assert.equal(h.gate.submitSpeech(invalid), false, 'the real gate must reject this zero-frame fact');
  h.playbackOptions.onFact(invalid);
  assert.equal(h.acceptedPackets.length, 0, 'the injected sink has not accepted any PCM');
  assert.equal(h.phases.includes('speaking'), false,
    'a rejected submitted fact must not present the user-visible speaking phase');
  await h.controller.close();
});

test('native first source yields an accepted gate fact before speaking', async () => {
  const h = realSinkHarness();
  const decisions = [];
  await h.controller.connect();
  await tick();
  const gate = h.gate;
  const submitSpeech = gate.submitSpeech.bind(gate);
  gate.submitSpeech = fact => {const accepted = submitSpeech(fact); decisions.push(accepted); return accepted;};
  await h.controller.input('hello');
  await tick();
  await h.submittedPush(new Int16Array([1, 2]));
  await tick();
  assert.equal(h.sources[0].started, true, 'the real sink emitted only after starting a source');
  assert.deepEqual(decisions, [true], 'the first native source fact must pass the presentation gate');
  assert.equal(h.phases.at(-1), 'speaking');
  await h.controller.close();
  assert.equal(h.timers.size, 0);
});

test('duplicate submitted fact is rejected after the first native source', async () => {
  const h = realSinkHarness();
  const decisions = [];
  await h.controller.connect();
  await tick();
  const gate = h.gate;
  const submitSpeech = gate.submitSpeech.bind(gate);
  gate.submitSpeech = fact => {const accepted = submitSpeech(fact); decisions.push(accepted); return accepted;};
  await h.controller.input('hello');
  await tick();
  await h.submittedPush(new Int16Array([1, 2]));
  await tick();
  h.sources[0].onended();
  await h.submittedPush(new Int16Array([3, 4]));
  await tick();
  assert.equal(h.sources[1].started, true);
  assert.deepEqual(decisions, [true, false], 'the gate rejects duplicate submitted facts');
  assert.equal(h.phases.at(-1), 'speaking', 'the earlier accepted source remains the speaking basis');
  await h.controller.close();
  assert.equal(h.timers.size, 0);
});

test('Stop phase cannot be revived by a late submitted fact', async () => {
  const h = realSinkHarness();
  await h.controller.connect();
  await tick();
  await h.controller.input('hello');
  await tick();
  await h.submittedPush(new Int16Array([1, 2]));
  await tick();
  const submitted = h.facts.find(fact => fact.stage === 'submitted');
  assert.ok(submitted);
  assert.equal(h.phases.at(-1), 'speaking');
  await h.controller.stop();
  assert.equal(h.phases.at(-1), 'idle', 'the scene stop hook exits speaking');
  h.playbackOptions.onFact(submitted);
  assert.equal(h.phases.at(-1), 'idle', 'a late fact has no current SpeechRun to revive');
  await h.controller.close();
  assert.equal(h.timers.size, 0);
});
