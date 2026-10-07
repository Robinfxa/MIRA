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

function harness(cueCount = 1) {
  const sources = [], facts = [], errors = [], wires = [], requests = [], inputs = [], receipts = [], progress = [], shown = [];
  let textOnlyNext = false;
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
            for (let i = 0; i < length; i++) buffer.writeInt16LE(Math.round(Math.sin(i * 0.071 + value) * 16000), i * 2);
            const packet = {...origin, type: 'audio', sequence, first_sample: samples,
              sample_rate_hz: 24000, pcm_base64: buffer.toString('base64')};
            samples += length; return JSON.stringify(packet) + '\n';
          }).join('');
          bodyController.enqueue(new TextEncoder().encode(packets));
        },
        malformed() {assert.equal(closed, false); closed = true;bodyController.enqueue(new TextEncoder().encode('invalid-json\n'));bodyController.close();},
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
    async input(request) {inputs.push(request);let grants = Array.from({length: cueCount}, (_, index) => {
      const id = `speech-${request.activity_seq}-${index + 1}`, cue_id = `cue-${request.activity_seq}-${index + 1}`;
      const common = {digest: 'a'.repeat(64), activity_seq: request.activity_seq, output_epoch: request.activity_seq, cue_id, cue_speech_id: id};
      return [{...common, id, kind: 'speech', value: `synthetic cue ${index + 1}`},
        {...common, id: `caption-${request.activity_seq}-${index + 1}`, kind: 'subtitle', value: `synthetic text ${index + 1}`}];
    }).flat();
      if(textOnlyNext) grants=grants.filter(e=>e.kind==='subtitle').map(e=>({...e,cue_speech_id:null}));
      current = {...current, activity_seq: request.activity_seq, output_epoch: request.activity_seq,
        input_epoch: request.activity_seq, request_id: request.request_id, response_mode: textOnlyNext?'text_only':'voice', phase: 'ready', sealed: true, active_grants: grants}; return snapshot();},
    async stop(request) {current = {...current, activity_seq: request.activity_seq, output_epoch: request.activity_seq,
      phase: 'stopped', sealed: false, request_id: null, active_grants: []}; return snapshot();},
    receipt: async value => {receipts.push(value); return snapshot();}, audioProgress: async value => {progress.push(value);return snapshot();}, close: async () => transport.close(),
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
  const controller = new SessionController(api, {apply(effect) {shown.push(effect);}, prepareInput() {}, stop() {}, setPhase() {}},
    {connected() {}, update() {}, error(message) {if (message) errors.push(message);}, localStop() {}},
    {apiBase: '/api/v1', pollIntervalMs: 200}, {
      createPlayback: options => new CancelSafePlayback({...options, createContext: () => context,
        setInterval: () => 1, clearInterval() {}, onFact(fact) {facts.push(fact); options.onFact(fact);}}),
      createCapture: () => ({start: async () => false, stop() {}, close: async () => {}}),
    });
  const start = async text => {await controller.input(text); await tick(); assert.ok(wires.length); return wires.at(-1);};
  const close = async () => {await controller.close(); transport.close();};
  return {controller, sources, facts, errors, wires, requests, inputs, receipts, progress, shown, start, close, textOnly() {textOnlyNext=true;}};
}

async function drain(h, wire, count) {
  for (let index = 0; index < count; index++) {
    await tick(); const active = h.sources.find(source => source.started && !source.ended && !source.stopped);
    assert.ok(active, `packet ${index + 1} of ${count} is playable`);
    active.end(); await tick();
    assert.ok(wire.accepted.length - h.sources.filter(source => source.ended).length <= 50, 'default packet bound stays finite');
  }
}


// All test audio is deterministic nonzero PCM. Network segmentation is independent
// of semantic audio frames and must not alter duration, order, or completion facts.
test('coalesced valid network tail keeps every PCM packet after an audible prefix', async () => {
  const h = harness();
  try {
    await h.controller.connect(); const wire = await h.start('synthetic long response');
    wire.send([6000]); await drain(h, wire, 1);
    assert.equal(h.facts.some(fact => fact.stage === 'completed'), false);
    wire.send(Array(80).fill(6000)); wire.finish(); await tick(); await tick();
    assert.deepEqual(h.errors, [], 'a coalesced network read is not an invalid protocol line');
    await drain(h, wire, 80); await wire.complete.promise;
    assert.equal(wire.outcome, 'complete'); assert.equal(wire.accepted.length, 81);
    assert.equal(h.facts.at(-1).renderedFrames, 486000);
    assert.equal(h.facts.at(-1).stage, 'completed');
    for (let index=0;index<81;index++) assert.equal(h.sources[index].buffer.samples[0], Math.round(Math.sin(index + 1) * 16000) / 32768);
    assert.equal(h.progress.filter(value => value.status === 'completed').length, 1);
    assert.deepEqual(h.receipts.map(value => value.effect_id), ['caption-1-1']);
  } finally {await h.close();}
});

test('three cues advance only after natural drain across slow and coalesced network chunks', async () => {
  const h = harness(3);
  try {
    await h.controller.connect(); let wire = await h.start('three synthetic cues');
    for(let cue=1;cue<=3;cue++) {
      assert.equal(h.wires.length, cue); wire=h.wires[cue-1];
      wire.send([6000]); await drain(h, wire, 1);
      await tick(); await tick();
      assert.equal(h.wires.length, cue, 'an underflow never starts the next cue');
      wire.send(Array(24).fill(6000)); wire.finish(); await tick(); await tick();
      assert.deepEqual(h.errors, []);
      await drain(h, wire, 24); await wire.complete.promise; await tick();
      assert.equal(h.facts.filter(f=>f.stage==='completed').length,cue);
    }
    assert.deepEqual(h.wires.map(w=>w.effectId), ['speech-1-1','speech-1-2','speech-1-3']);
    assert.deepEqual(h.progress.filter(p=>p.status==='completed').map(p=>p.rendered_samples), [150000,150000,150000]);
    assert.deepEqual(h.receipts.map(value=>value.effect_id), ['caption-1-1','caption-1-2','caption-1-3']);
    assert.equal(h.sources.length,75); assert.equal(h.controller.replyPlaybackBusy,false);
  } finally {await h.close();}
});

for (const action of ['stop', 'new-turn']) test(`${action} releases a coalesced network tail at backpressure and prevents full receipt`, async () => {
  const h = harness();
  try {
    await h.controller.connect(); const old = await h.start('old synthetic response');
    old.send([6000]); await drain(h,old,1);
    old.send(Array(80).fill(6000)); old.finish(); await tick(); await tick();
    assert.deepEqual(h.errors, []); assert.equal(old.settled,false);
    const active=h.sources.find(source=>source.started&&!source.ended&&!source.stopped), saved=active.onended;
    if(action==='stop') await h.controller.stop();
    else await h.start('next synthetic response');
    await old.complete.promise; saved(); await tick();
    assert.equal(active.stopped,true); assert.equal(old.outcome,'cancelled-or-failed');
    assert.equal(h.facts.some(f=>f.origin.id===old.effectId&&f.stage==='completed'),false);
    assert.equal(h.progress.some(p=>p.effect_id===old.effectId&&p.status==='completed'),false);
    if(action==='new-turn') {const next=h.wires.at(-1);next.send([6000,6000,6000]);next.finish();await drain(h,next,3);
      assert.equal(h.facts.at(-1).stage,'completed');assert.equal(h.facts.at(-1).origin.id,next.effectId);}
  } finally {await h.close();}
});


test('late malformed speech preserves shown text and prefix facts, then accepts voice and text turns',async()=>{
  const h=harness();try{
    await h.controller.connect();const bad=await h.start('synthetic failing response');
    bad.send([6000,6000]);await drain(h,bad,1);
    assert.equal(h.sources[1].started,true);const saved=h.sources[1].onended;
    bad.malformed();await bad.complete.promise;await tick();
    assert.equal(h.errors.length,1);assert.equal(h.sources[1].stopped,true);
    assert.equal(h.shown.some(e=>e.id==='caption-1-1'),true,'rendered caption remains available');
    assert.equal(h.progress.some(p=>p.effect_id===bad.effectId&&p.rendered_samples===6000),true);
    assert.equal(h.progress.some(p=>p.effect_id===bad.effectId&&p.status==='completed'),false);
    const next=await h.start('next synthetic voice response');saved();
    next.send([6000,6000,6000]);next.finish();await drain(h,next,3);
    assert.equal(h.progress.some(p=>p.effect_id===next.effectId&&p.status==='completed'&&p.rendered_samples===18000),true);
    h.textOnly();const accepted=await h.controller.input('next synthetic text response');await tick();
    assert.equal(accepted.status,'submitted');assert.equal(h.wires.length,2);
    assert.equal(h.shown.some(e=>e.id==='caption-3-1'),true);
    assert.equal(h.errors.length,1,'earlier failure does not produce a later failure');
  }finally{await h.close();}
});
