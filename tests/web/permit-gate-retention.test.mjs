import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const dist = process.env.MIRA_TEST_WEB_DIST
  ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href
  : new URL('../../apps/web/dist/', import.meta.url).href;
const {PresentationGate} = await import(new URL('features/presentation/permit-gate.js', dist));
const {SessionController} = await import(new URL('features/session/controller.js', dist));
const {CancelSafePlayback} = await import(new URL('features/audio/playback.js', dist));
const tick = () => new Promise(resolve => setImmediate(resolve));

function cue(activity, epoch = activity) {
  const common = {digest: 'a'.repeat(64), activity_seq: activity, output_epoch: epoch,
    cue_id: `cue-${activity}-${epoch}`, cue_speech_id: `speech-${activity}-${epoch}`};
  return [{...common, id: common.cue_speech_id, kind: 'speech', value: 'spoken words'},
    {...common, id: `caption-${activity}-${epoch}`, kind: 'subtitle', value: 'shown words'}];
}
function snapshot(activity, grants = cue(activity), patch = {}) {
  return {schema_version: '0.1.0-foundation', session_id: 's', client_instance_id: 'c',
    revision: activity * 10, permit_revision: activity * 10, activity_seq: activity,
    input_epoch: activity, output_epoch: activity, request_id: `request-${activity}`,
    phase: 'ready', sealed: true, active_grants: grants, presented_effects: [],
    audio_progress: [], last_error: null, ...patch};
}
function fact(origin, stage, renderedFrames = 240) {
  return {origin, stage, submittedFrames: 480, renderedFrames,
    sampleRate: 24000, inFlightFramesUncertain: 480 - renderedFrames};
}
function sizes(gate) {
  return [gate.knownEffects.size, gate.consumed.size, gate.audio.size];
}

test('160 successive turns keep only current activity identities and preserve every exact prefix cutoff', () => {
  const gate = new PresentationGate('s', 'c');
  let previousCutoff = 0;
  for (let activity = 1; activity <= 160; activity++) {
    assert.equal(gate.beginInput(`request-${activity}`).presentation_cutoff, previousCutoff);
    assert.deepEqual(sizes(gate), [0, 0, 0]);
    const grants = cue(activity), [speech, caption] = grants;
    gate.install(snapshot(activity, grants));
    assert.equal(gate.claimSpeech(speech), true);
    assert.equal(gate.submitSpeech(fact(speech, 'submitted', 0)), true);
    const receipt = gate.consume(caption);
    const prefix = gate.audioProgress(fact(speech, 'rendered'));
    assert.equal(receipt.presentation_seq, previousCutoff + 1);
    assert.equal(prefix.presentation_seq, previousCutoff + 2);
    assert.equal(prefix.rendered_samples, 240);
    gate.block();
    const terminal = gate.audioProgress({...fact(speech, 'stopped'), reason: 'new-input'});
    assert.deepEqual([terminal.effect_id, terminal.digest, terminal.output_epoch,
      terminal.activity_seq, terminal.rendered_samples, terminal.status],
    [speech.id, speech.digest, activity, activity, 240, 'interrupted']);
    previousCutoff = terminal.presentation_seq;
    assert.deepEqual(sizes(gate), [2, 2, 1]);
    assert.equal(gate.audioProgress(fact(speech, 'completed', 480)), null);
  }
  assert.equal(gate.stop().presentation_cutoff, 480);
  assert.deepEqual(sizes(gate), [0, 0, 0]);
});

test('current activity deduplication and audio survive compaction, revocation, regrant and local block', () => {
  const gate = new PresentationGate('s', 'c'), grants = cue(1), [speech, caption] = grants;
  gate.beginInput('request-1');
  gate.install(snapshot(1));
  gate.claimSpeech(speech);
  gate.submitSpeech(fact(speech, 'submitted', 0));
  assert.ok(gate.consume(caption));
  assert.equal(gate.audioProgress(fact(speech, 'rendered')).rendered_samples, 240);
  gate.install(snapshot(1, grants, {revision: 11, presentation_floor: 2, retired_user_inputs: 100}));
  assert.equal(gate.claimSpeech(speech), false);
  assert.equal(gate.consume(caption), null);
  gate.install(snapshot(1, [], {revision: 12, permit_revision: 11}));
  assert.equal(gate.audioProgress(fact(speech, 'rendered', 360)), null);
  gate.install(snapshot(1, grants, {revision: 13, permit_revision: 12}));
  assert.equal(gate.claimSpeech(speech), false);
  assert.equal(gate.consume(caption), null);
  assert.equal(gate.audioProgress(fact(speech, 'rendered', 360)).rendered_samples, 360);
  gate.block();
  assert.deepEqual(sizes(gate), [2, 2, 1]);
  const stopped = gate.audioProgress({...fact(speech, 'stopped', 360), reason: 'stop'});
  assert.equal(stopped.status, 'interrupted');
  assert.equal(stopped.rendered_samples, 360);
  assert.equal(gate.stop().presentation_cutoff, stopped.presentation_seq);
  assert.deepEqual(sizes(gate), [0, 0, 0]);
});

test('same activity effect identity remains immutable after its grant temporarily disappears', () => {
  const gate = new PresentationGate('s', 'c'), grants = cue(1);
  gate.beginInput('request-1'); gate.install(snapshot(1)); gate.consume(grants[1]);
  gate.install(snapshot(1, [], {revision: 11, permit_revision: 11}));
  assert.throws(() => gate.install(snapshot(1, grants.map(effect => ({...effect, value: 'mutated'})),
    {revision: 12, permit_revision: 12})), /identity cannot change/);
  assert.equal(gate.isAuthorized(grants[0]), false);
});

test('retired old snapshots and late callbacks cannot repopulate histories or replay after Stop and new input', () => {
  const gate = new PresentationGate('s', 'c'), old = cue(1);
  gate.beginInput('request-1'); gate.install(snapshot(1)); gate.claimSpeech(old[0]);
  gate.block(); gate.audioProgress({...fact(old[0], 'stopped'), reason: 'stop'}); gate.stop();
  gate.install(snapshot(1, old, {revision: 100, permit_revision: 100}));
  assert.deepEqual(sizes(gate), [0, 0, 0]);
  assert.equal(gate.claimSpeech(old[0]), false);
  assert.equal(gate.consume(old[1]), null);
  assert.equal(gate.audioProgress(fact(old[0], 'completed', 480)), null);
  gate.beginInput('request-3');
  gate.install(snapshot(3, cue(3), {revision: 101, permit_revision: 101}));
  assert.equal(gate.claimSpeech(cue(3)[0]), true);
  assert.equal(gate.submitSpeech(fact(old[0], 'submitted', 0)), false);
  assert.equal(gate.audioProgress({...fact(old[0], 'stopped'), reason: 'stop'}), null);
  assert.deepEqual(sizes(gate), [2, 1, 1]);
});

test('epoch revocation retains pending exact interruption but a higher revision cannot roll epoch back', () => {
  const gate = new PresentationGate('s', 'c'), [speech] = cue(1);
  gate.beginInput('request-1'); gate.install(snapshot(1)); gate.claimSpeech(speech);
  gate.audioProgress(fact(speech, 'rendered'));
  gate.install(snapshot(1, [], {revision: 11, permit_revision: 11, output_epoch: 2,
    phase: 'stopped', request_id: null}));
  const interrupted = gate.audioProgress({...fact(speech, 'stopped'), reason: 'revoked'});
  assert.equal(interrupted.rendered_samples, 240);
  assert.equal(interrupted.output_epoch, 1);
  assert.equal(interrupted.status, 'interrupted');
  assert.equal(gate.install(snapshot(1, cue(1), {revision: 12, permit_revision: 12})), false);
  assert.equal(gate.isAuthorized(speech), false);
  assert.equal(gate.consume(cue(1)[1]), null);
  assert.equal(gate.audioProgress(fact(speech, 'completed', 480)), null);
});

function controllerHarness() {
  const sources = [], audio = [], receipts = [], inputs = [], stops = [], errors = [], timers = new Set();
  let client, current, revision = 0, effectCount = 0;
  const state = (activity, grants = [], patch = {}) => snapshot(activity, grants, {
    client_instance_id: client, revision: ++revision, permit_revision: revision,
    phase: 'stopped', request_id: null, ...patch});
  const context = {destination: {}, resume: async () => {}, close: async () => {},
    createBuffer: (_channels, length) => ({getChannelData: () => new Float32Array(length)}),
    createBufferSource() {
      const source = {onended: null, stopped: 0, connect() {}, disconnect() {}, start() {},
        stop() { this.stopped++; }};
      sources.push(source); return source;
    }};
  const api = {
    create: async id => {client = id; current = state(0); return {session: current, session_token: 'synthetic'};},
    capabilities: async () => ({speech_enabled: true, microphone_enabled: false,
      speech_sample_rate_hz: 24000, microphone_sample_rate_hz: 16000,
      qualification: 'injected_unverified', generation_mode: 'mock'}),
    snapshot: () => new Promise(() => {}),
    input: async request => {inputs.push(request); return current = state(request.activity_seq,
      cue(request.activity_seq), {phase: 'ready', request_id: request.request_id});},
    stop: async request => {stops.push(request); return current = state(request.activity_seq);},
    receipt: async receipt => {receipts.push(receipt); return current;},
    audioProgress: async progress => {audio.push(progress); return current;},
    speech: async (_effect, _signal, push) => {
      await push(new Int16Array(240).fill(1000)); await push(new Int16Array(240).fill(2000));
    },
    close: async () => {},
  };
  const controller = new SessionController(api, {apply: () => {effectCount++;}, prepareInput() {}, stop() {}, setPhase() {}},
    {connected() {}, update() {}, error: value => {if (value) errors.push(value);}, localStop() {}},
    {apiBase: '/api/v1', pollIntervalMs: 200}, {
      createPlayback: options => new CancelSafePlayback({...options, createContext: () => context,
        setInterval: callback => {timers.add(callback); return callback;}, clearInterval: id => timers.delete(id)}),
      createCapture: () => ({start: async () => false, stop() {}, close: async () => {}}),
    });
  return {controller, sources, audio, receipts, inputs, stops, errors, timers,
    get effectCount() {return effectCount;}};
}

test('125 compiled controller turns retain bounded gate state with exact partial audio and real sink Stop ordering', async () => {
  const h = controllerHarness();
  const interrupted = [], completed = [];
  try {
    await h.controller.connect();
    let lateEnd = null;
    for (let turn = 1; turn <= 125; turn++) {
      const outcome = await h.controller.input(`synthetic turn ${turn}`);
      assert.equal(outcome.status, 'submitted');
      await tick();
      const gate = h.controller.gate, activity = gate.currentActivity(), speechId = cue(activity)[0].id;
      assert.deepEqual(sizes(gate), [2, 2, 1]);
      assert.equal(h.effectCount, turn);
      assert.equal(h.receipts.length, turn);
      const first = h.sources.at(-1);
      const beforeLate = h.audio.length;
      lateEnd?.(); await tick();
      assert.equal(h.audio.length, beforeLate, 'retired sink callback cannot append a fact');
      first.onended(); await tick();
      const second = h.sources.at(-1); lateEnd = second.onended;
      assert.notEqual(second, first);
      assert.equal(h.audio.at(-1).rendered_samples, 240);
      assert.equal(h.audio.some(item => item.effect_id === speechId && item.status === 'completed'), false);
      const current = h.controller.snapshot;
      h.controller.install({...current, revision: current.revision + 1, presentation_floor: turn - 1,
        retired_user_inputs: Math.max(0, turn - 80)});
      assert.deepEqual(sizes(gate), [2, 2, 1]);
      assert.equal(h.effectCount, turn, 'same active grant cannot replay after compacted history');
      if (turn % 5 === 0) {
        second.onended(); await tick(); completed.push(speechId);
        assert.equal(h.audio.at(-1).status, 'completed');
        assert.equal(h.audio.at(-1).rendered_samples, 480);
      } else interrupted.push(speechId);
      if (turn % 7 === 0) {
        await h.controller.stop(); await tick();
        assert.deepEqual(sizes(gate), [0, 0, 0]);
        assert.equal(h.stops.at(-1).presentation_cutoff, h.audio.at(-1).presentation_seq);
      }
    }
    await h.controller.stop(); await tick();
    for (const id of interrupted) {
      const facts = h.audio.filter(item => item.effect_id === id);
      assert.deepEqual(facts.map(item => [item.status, item.rendered_samples]),
        [['rendered', 240], ['interrupted', 240]]);
      assert.equal(facts[0].digest, 'a'.repeat(64));
      assert.equal(facts[1].output_epoch, facts[0].output_epoch);
      assert.equal(facts[1].activity_seq, facts[0].activity_seq);
    }
    assert.equal(completed.length, 25);
    assert.equal(interrupted.length, 100);
    const sequences = [...h.audio, ...h.receipts].map(item => item.presentation_seq).sort((a, b) => a - b);
    assert.deepEqual(sequences, Array.from({length: sequences.length}, (_, index) => index + 1));
    assert.equal(h.inputs.length, 125);
    assert.deepEqual(h.errors, []);
  } finally {await h.controller.close();}
  assert.equal(h.timers.size, 0);
});
