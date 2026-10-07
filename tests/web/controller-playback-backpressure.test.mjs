import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist = pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST ?? 'apps/web/dist') + '/');
const {SessionController} = await import(new URL('features/session/controller.js', dist));
const {BrowserAudioTransport} = await import(new URL('features/session/audio-transport.js', dist));
const {CancelSafePlayback} = await import(new URL('features/audio/playback.js', dist));
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {let resolve; const promise = new Promise(done => {resolve = done;}); return {promise, resolve};};

function harness(sinkOptions = {}, controllerOptions = {}) {
  const sources = [], facts = [], errors = [], wires = [], requests = [], inputs = [];
  let client, revision = 0, current = {activity_seq: 0, output_epoch: 0, input_epoch: 0,
    request_id: null, active_grants: [], phase: 'stopped', sealed: false};
  const snapshot = () => ({schema_version: '0.1.0-foundation', session_id: 's', client_instance_id: client,
    revision: ++revision, permit_revision: revision, presented_effects: [], audio_progress: [], last_error: null, ...current});
  const context = {destination: {}, state: 'running', resume: async () => {}, close: async () => {},
    createBuffer(_channels, length, rate) {const samples = new Float32Array(length); return {samples, length, rate, getChannelData: () => samples};},
    createBufferSource() {const source = {buffer: null, onended: null, started: false, stopped: false, ended: false,
      connect() {}, disconnect() {}, start() {source.started = true;}, stop() {source.stopped = true;},
      end() {assert.equal(source.started, true); assert.equal(source.ended, false); source.ended = true; source.onended?.();}};
      sources.push(source); return source;},
  };
  const transport = new BrowserAudioTransport({apiBase: '/api/v1'}, () => ({sessionId: 's', token: 'synthetic'}), {
    async fetch(url, request) {
      requests.push(request);
      const effectId = /\/speech\/([^/]+)\/stream$/.exec(url)[1];
      const origin = {...JSON.parse(request.body), stream_id: effectId, effect_id: effectId};
      let bodyController, sequence = 0, samples = 0, closed = false;
      const accepted = [], delivered = [], complete = deferred();
      const wire = {effectId, accepted, delivered, settled: false, outcome: null, complete,
        send(lengths) {
          assert.equal(closed, false);
          const packets = lengths.map(length => {
            const value = ++sequence, buffer = Buffer.alloc(length * 2);
            for (let i = 0; i < length; i++) buffer.writeInt16LE(value, i * 2);
            const packet = {...origin, type: 'audio', sequence, first_sample: samples,
              sample_rate_hz: 24000, pcm_base64: buffer.toString('base64')};
            samples += length; return JSON.stringify(packet) + '\n';
          }).join('');
          bodyController.enqueue(new TextEncoder().encode(packets));
        },
        finish() {assert.equal(closed, false); closed = true;
          bodyController.enqueue(new TextEncoder().encode(JSON.stringify({...origin, type: 'complete', total_samples: samples}) + '\n'));
          bodyController.close();},
      };
      const body = new ReadableStream({start(controller) {bodyController = controller;}, cancel() {closed = true;}});
      wires.push(wire);
      return new Response(body, {headers: {'content-type': 'application/x-ndjson'}});
    },
  });
  const api = {create: async id => {client = id; return {session: snapshot(), session_token: 'synthetic'};},
    capabilities: async () => ({speech_enabled: true, microphone_enabled: false, speech_sample_rate_hz: 24000,
      microphone_sample_rate_hz: 16000, qualification: 'injected_unverified', generation_mode: 'mock'}),
    snapshot: () => new Promise(() => {}),
    async input(request) {inputs.push(request);const effect = {id: `speech-${request.activity_seq}`, kind: 'speech', value: 'one whole cue',
        digest: 'a'.repeat(64), activity_seq: request.activity_seq, output_epoch: request.activity_seq};
      current = {...current, activity_seq: request.activity_seq, output_epoch: request.activity_seq,
        input_epoch: request.activity_seq, request_id: request.request_id, phase: 'ready', sealed: true, active_grants: [effect]}; return snapshot();},
    async stop(request) {current = {...current, activity_seq: request.activity_seq, output_epoch: request.activity_seq,
      phase: 'stopped', sealed: false, request_id: null, active_grants: []}; return snapshot();},
    receipt: async () => snapshot(), audioProgress: async () => snapshot(), close: async () => transport.close(),
    async speech(effect, signal, onPcm) {
      try {
        await transport.speech(effect, signal, async pcm => {
          const wire = wires.find(item => item.effectId === effect.id); wire.delivered.push(pcm);
          await onPcm(pcm); wire.accepted.push(pcm);
        });
        const wire = wires.find(item => item.effectId === effect.id); wire.outcome = 'complete';
      } catch (error) {const wire = wires.find(item => item.effectId === effect.id); if (wire) wire.outcome = 'cancelled-or-failed'; throw error;}
      finally {const wire = wires.find(item => item.effectId === effect.id); if (wire) {wire.settled = true; wire.complete.resolve();}}
    },
  };
  const controller = new SessionController(api, {apply() {}, prepareInput() {}, stop() {}, setPhase() {}},
    {connected() {}, update() {}, error(message) {if (message) errors.push(message);}, localStop() {}},
    {apiBase: '/api/v1', pollIntervalMs: 200}, {
      ...controllerOptions,
      createPlayback: options => new CancelSafePlayback({...options, ...sinkOptions, createContext: () => context,
        setInterval: () => 1, clearInterval() {}, onFact(fact) {facts.push(fact); options.onFact(fact);}}),
      createCapture: () => ({start: async () => false, stop() {}, close: async () => {}}),
    });
  const start = async text => {await controller.input(text); await tick(); assert.ok(wires.length); return wires.at(-1);};
  const close = async () => {await controller.close(); transport.close();};
  return {controller, sources, facts, errors, wires, requests, inputs, start, close};
}

async function drain(h, wire, count) {
  for (let index = 0; index < count; index++) {
    await tick(); const active = h.sources.find(source => source.started && !source.ended && !source.stopped);
    assert.ok(active, `packet ${index + 1} of ${count} is playable`);
    active.end(); await tick();
    assert.ok(wire.accepted.length - h.sources.filter(source => source.ended).length <= 50, 'default packet bound stays finite');
  }
}

test('one speech cue renders three distinct packets after a short first packet and a delayed second', async () => {
  const h = harness();
  try {
    await h.controller.connect(); const wire = await h.start('three packet cue');
    wire.send([8]); await tick(); assert.equal(h.sources.length, 1);
    h.sources[0].end(); await tick();
    assert.equal(h.facts.some(fact => fact.stage === 'completed'), false, 'underflow is not completion');
    assert.equal(wire.settled, false);
    wire.send([11, 13]); wire.finish(); await tick(); await tick();
    assert.equal(wire.outcome, 'complete', 'HTTP completion arrives before the queued PCM drains');
    assert.equal(h.facts.some(fact => fact.stage === 'completed'), false);
    await drain(h, wire, 2);
    assert.deepEqual(h.sources.map(source => source.buffer.samples[0]), [1 / 32768, 2 / 32768, 3 / 32768]);
    assert.equal(h.facts.at(-1).stage, 'completed'); assert.equal(h.facts.at(-1).renderedFrames, 32);
    assert.deepEqual(h.errors, []);
  } finally {await h.close();}
});

test('75 short packets wait at the real sink packet cap and all drain after transport completion', async () => {
  const h = harness();
  try {
    await h.controller.connect(); const wire = await h.start('short packet burst');
    wire.send(Array(75).fill(160)); wire.finish(); await tick(); await tick();
    assert.deepEqual(h.errors, [], 'packet 51 must wait, not overflow the 50-packet sink while below the 96000-frame budget');
    assert.equal(wire.accepted.length, 50); assert.equal(wire.settled, false);
    assert.equal(h.sources[0].stopped, false);
    await drain(h, wire, 75); await wire.complete.promise;
    assert.equal(wire.outcome, 'complete'); assert.equal(wire.accepted.length, 75);
    assert.deepEqual(h.sources.map(source => source.buffer.samples[0]), Array.from({length: 75}, (_, i) => (i + 1) / 32768));
    assert.equal(h.facts.at(-1).stage, 'completed'); assert.equal(h.facts.at(-1).renderedFrames, 12000);
    assert.deepEqual(h.errors, []);
  } finally {await h.close();}
});

test('the coordinator respects a smaller injected sink capacity instead of assuming 50 packets or 96000 frames', async () => {
  const h = harness({maxQueuedChunks: 2, maxBufferedFrames: 20, maxChunkFrames: 10});
  try {
    await h.controller.connect(); const wire = await h.start('bounded capacity');
    wire.send(Array(6).fill(8)); wire.finish(); await tick(); await tick();
    assert.deepEqual(h.errors, []); assert.equal(wire.accepted.length, 2);
    for (let index = 0; index < 6; index++) {
      const active = h.sources.find(source => source.started && !source.ended && !source.stopped); assert.ok(active);
      active.end(); await tick(); assert.ok(wire.accepted.length - h.sources.filter(source => source.ended).length <= 2);
    }
    assert.equal(h.facts.at(-1).stage, 'completed'); assert.equal(h.facts.at(-1).renderedFrames, 48);
  } finally {await h.close();}
});

for (const action of ['stop', 'new-turn', 'close']) test(`${action} cancels a transport waiting at sink capacity without playing the old tail`, async () => {
  const h = harness();
  try {
    await h.controller.connect(); const old = await h.start('old burst');
    old.send(Array(75).fill(160)); old.finish(); await tick(); await tick();
    assert.deepEqual(h.errors, []); assert.equal(old.accepted.length, 50); assert.equal(old.settled, false);
    const oldSource = h.sources[0], staleEnded = oldSource.onended;
    if (action === 'stop') await h.controller.stop();
    if (action === 'close') await h.controller.close();
    if (action === 'new-turn') {const next = await h.start('new cue'); next.send([3, 5, 7]); next.finish();}
    await tick(); assert.equal(old.settled, true); assert.equal(old.outcome, 'cancelled-or-failed');
    assert.equal(oldSource.stopped, true); staleEnded(); await tick();
    assert.equal(h.facts.filter(fact => fact.origin.id === old.effectId && fact.stage === 'completed').length, 0);
    assert.equal(h.sources.filter(source => source.started).length, action === 'new-turn' ? 2 : 1);
    if (action === 'new-turn') {
      const next = h.wires.at(-1); await drain(h, next, 3);
      assert.equal(h.facts.at(-1).stage, 'completed'); assert.equal(h.facts.at(-1).origin.id, next.effectId);
      assert.equal(h.facts.at(-1).renderedFrames, 15);
    }
  } finally {await h.close();}
});

test('a frame-limited sink pauses even when its packet slots remain available', async () => {
  const h = harness({maxQueuedChunks: 50, maxBufferedFrames: 12, maxChunkFrames: 10});
  try {
    await h.controller.connect(); const wire = await h.start('frame bounded'); wire.send([8, 8, 8]); wire.finish();
    await tick(); await tick(); assert.deepEqual(h.errors, []); assert.equal(wire.accepted.length, 1);
    for (let index = 0; index < 3; index++) {
      h.sources[index].end(); await tick();
      assert.ok(wire.accepted.length - h.sources.filter(source => source.ended).length <= 1);
    }
    assert.equal(h.facts.at(-1).stage, 'completed'); assert.equal(h.facts.at(-1).renderedFrames, 24);
  } finally {await h.close();}
});

test('a packet that can never fit fails and settles instead of waiting for capacity forever', async () => {
  const h = harness({maxBufferedFrames: 8, maxChunkFrames: 8});
  try {
    await h.controller.connect(); const wire = await h.start('impossible packet'); wire.send([9]); wire.finish();
    await tick(); await tick(); assert.equal(wire.settled, true); assert.equal(wire.accepted.length, 0);
    assert.equal(h.sources.length, 0); assert.ok(h.errors.length > 0);
    assert.equal(h.facts.some(fact => fact.stage === 'completed'), false);
  } finally {await h.close();}
});

test('replyPlaybackBusy conservatively covers pending transport, queued tail, completion, and close', async () => {
  const h = harness();
  try {
    assert.equal(h.controller.replyPlaybackBusy, true, 'not connected is not confirmed idle');
    await h.controller.connect(); await tick(); assert.equal(h.controller.replyPlaybackBusy, false);
    const wire = await h.start('busy cue'); assert.equal(h.controller.replyPlaybackBusy, true, 'waiting for first PCM is busy');
    wire.send([3, 5, 7]); wire.finish(); await tick(); await tick();
    assert.equal(wire.outcome, 'complete'); assert.equal(h.controller.replyPlaybackBusy, true, 'HTTP completion is not playback completion');
    h.sources[0].end(); await tick(); assert.equal(h.controller.replyPlaybackBusy, true);
    await drain(h, wire, 2); assert.equal(h.controller.replyPlaybackBusy, false);
    await h.controller.close(); assert.equal(h.controller.replyPlaybackBusy, true, 'closed owner is not confirmed idle');
  } finally {await h.close();}
});

test('replyPlaybackBusy also includes the shared review audition without claiming physical sound', async () => {
  const h = harness();
  try {
    await h.controller.connect(); await tick(); assert.equal(h.controller.replyPlaybackBusy, false);
    assert.equal(await h.controller.auditionReviewedAudio(new Uint8Array([1, 0, 2, 0]), 16000), true);
    assert.equal(h.controller.replyPlaybackBusy, true);
    h.sources[0].end(); await tick(); assert.equal(h.controller.replyPlaybackBusy, false);
    assert.equal(h.facts.length, 0, 'review audition never fabricates character playback facts');
  } finally {await h.close();}
});


test('quiet gates one initial dispatch and keeps all reply packets on the same existing PCM queue', async () => {
  const quiet = deferred(); let calls = 0;
  const h = harness({}, {waitForReplyQuiet: () => {calls++; return quiet.promise;}});
  try {
    await h.controller.connect(); await h.controller.input('wait for quiet'); await tick();
    assert.equal(h.wires.length, 0); assert.equal(h.sources.length, 0); assert.equal(h.controller.replyPcmBusy, false);
    quiet.resolve(true); await tick(); assert.equal(h.wires.length, 1); assert.equal(h.controller.replyPcmBusy, false);
    const wire = h.wires[0]; wire.send([8]); await tick(); assert.equal(h.controller.replyPcmBusy, true);
    h.sources[0].end(); await tick(); wire.send([11,13]); wire.finish(); await tick(); await drain(h, wire, 2);
    assert.equal(calls, 1); assert.equal(h.requests.length, 1); assert.equal(h.facts.at(-1).renderedFrames, 32);
    assert.equal(h.controller.replyPcmBusy, false); assert.deepEqual(h.errors, []);
  } finally {await h.close();}
});

for (const action of ['stop', 'new-turn', 'close']) test(`${action} fences delayed quiet before transport dispatch`, async () => {
  const gates=[]; const h=harness({}, {waitForReplyQuiet: signal=>{const gate=deferred(); gates.push({...gate,signal});return gate.promise;}});
  try {
    await h.controller.connect();await h.controller.input('old pending reply');await tick();assert.equal(gates.length,1);
    if(action==='stop')await h.controller.stop();
    if(action==='new-turn')await h.controller.input('new pending reply');
    if(action==='close')await h.controller.close();
    assert.equal(gates[0].signal.aborted,true);gates[0].resolve(true);await tick();assert.equal(h.wires.length,0);
    if(action==='new-turn'){gates[1].resolve(true);await tick();assert.equal(h.wires.length,1);h.wires[0].send([3]);h.wires[0].finish();await drain(h,h.wires[0],1);}
  }finally{await h.close();}
});

test('voice supplement names the interrupted request and a later ordinary text request remains independent',async()=>{
  const h=harness();try{
    await h.controller.connect();await h.start('original task');const original=h.inputs[0];
    assert.equal(h.controller.interruptReply(),true);
    await h.controller.input('one more detail',undefined,'22345678-1234-4234-8234-123456789012');await tick();
    assert.equal(h.inputs[1].relation,'continuation');assert.equal(h.inputs[1].continuation_of_request_id,original.request_id);
    assert.equal(h.inputs[1].continuation_of_output_epoch,original.activity_seq);
    await h.controller.input('ordinary independent text');assert.equal(h.inputs[2].relation,undefined);
    assert.equal(h.inputs[2].continuation_of_request_id,undefined);
  }finally{await h.close();}
});
