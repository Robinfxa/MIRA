import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const dist = pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST ?? 'apps/web/dist') + '/').href;
const {ContinuousListeningController} = await import(new URL('features/session/continuous-listening.js', dist));
const flush = async () => { for (let i = 0; i < 24; i++) await Promise.resolve(); };
const lease = '12345678-1234-4234-8234-123456789012';
const utterance = '22345678-1234-4234-8234-123456789012';

function harness(selectedMode, knownTarget = true) {
  let capture, observer, sample = 0, sequence = 0, id = 0, busy = false, canInterrupt = true;
  let stops = 0, opens = 0, interruptions = 0, rejectCommit = false;
  const target = Object.freeze({sessionId:'synthetic',requestId:'reply',outputEpoch:1,activitySeq:1});
  const endpoints = [], frames = [], inputs = [], commits = [], holds = [], views = [];
  const timers = new Map(); let timerId = 0;
  const ready = {lease_id: lease, sample_rate_hz: 16000, max_seconds: 120,
    max_samples: 1920000, max_utterances: 12, max_streams_per_session: 4,
    max_total_streams: 10, session_lease_starts_used: 1, total_lease_starts_used: 1,
    endpoint_mode: 'google_vad_offsets_natural', manual_commit_required: false,
    client_endpoint_supported: true, client_silence_ms: 700, drain_timeout_ms: 2000,
    max_recognition_streams: 4};
  const controller = new ContinuousListeningController({mode: 'natural',
    ...(selectedMode === undefined ? {} : {bargeInMode: () => selectedMode}),
    createId: () => id++ === 0 ? lease : `${String(id + 10).padStart(8, '0')}-1234-4234-8234-123456789012`,
    setTimer: fn => { const n = ++timerId; timers.set(n, fn); return n; },
    clearTimer: n => timers.delete(n),
    createCapture: options => { capture = options; return {
      start() { options.onState('recording'); return Promise.resolve(true); },
      stop() { stops++; options.onProcessing?.(null); }, async close() {},
    }; },
    openStream: (_lease, _signal, options) => { observer = options; opens++; return {
      ready: Promise.resolve(ready), closed: new Promise(() => {}),
      send: frame => frames.push(frame),
      endpoint: (endpointId, end) => endpoints.push({endpointId, end}),
      cancelEndpoint() {},
      commit: async (commitId, revision, utteranceId) => {
        commits.push({commitId, revision, utteranceId});
        if (rejectCommit) return {type:'commit_rejected',lease_id:lease,commit_id:commitId,reason:'stale_revision',current_revision:revision};
        return {type: 'commit_ready', lease_id: lease, commit_id: commitId, revision,
          utterance_id: utteranceId, segment_seq: 1, text: '补充这个细节'};
      },
      hold: async (utteranceId, revision) => { holds.push({utteranceId, revision}); return {
        type: 'utterance_held', lease_id: lease, utterance_id: utteranceId, revision,
      }; }, stop: async () => {}, cancel() {},
    }; },
    interruptReply: () => { if (busy) { interruptions++; if (canInterrupt) busy = false; } return canInterrupt; },
    isPlaybackBusy: () => busy,
    captureReplyContinuation: () => knownTarget ? target : null,
    isInterruptedReplyCurrent: value => value === target,
    submitInput: async (text, commitId) => { inputs.push({text, commitId}); return {status: 'submitted'}; },
    onUpdate: view => views.push(view),
  });
  const pcm = (level, count = 1, lag = 0) => {
    for (let i = 0; i < count; i++) {
      const data = new Int16Array(640).fill(level);
      capture.onChunk({pcm16le: new Uint8Array(data.buffer), sampleRate: 16000, channels: 1,
        sequence: sequence++, startSample: sample, endSample: sample += 640, deliveryLagMilliseconds: lag});
    }
  };
  return {controller, endpoints, frames, inputs, commits, holds, views, timers, pcm,
    setBusy(value) { busy = value; }, setCanInterrupt(value) { canInterrupt = value; }, setCommitReject(value) { rejectCommit = value; },
    setMode(value) { selectedMode = value; },
    get interruptions() { return interruptions; }, get stops() { return stops; }, get opens() { return opens; },
    processing: value => capture.onProcessing?.(value),
    emit: event => observer.onEvent(event),
    finalize(patch = {}) { const endpoint = endpoints.at(-1); assert.ok(endpoint);
      observer.onEvent({type: 'endpoint_status', lease_id: lease, endpoint_id: endpoint.endpointId,
        source_end_sample: endpoint.end, state: 'completed'});
      observer.onEvent({type: 'utterance_ready', lease_id: lease, utterance_id: utterance,
        revision: 1, text: '补充这个细节', begin_offset_samples: 0, end_offset_samples: endpoint.end,
        source_end_sample: endpoint.end, final_offset_samples: null,
        endpoint_basis: 'client_silence_finalized', client_endpoint_id: endpoint.endpointId, ...patch});
    },
  };
}
async function start(mode) { const h = harness(mode); assert.equal(h.controller.start(), true); await flush(); return h; }

test('explicit headphones interrupt once at 160ms and preserve one mic lease through quiet and submission', async () => {
  const h = await start('headphones');
  try {
    h.setBusy(true); h.pcm(1400, 3); assert.equal(h.interruptions, 0);
    h.pcm(1400); assert.equal(h.interruptions, 1);
    assert.equal(h.stops, 0); assert.equal(h.opens, 1); assert.equal(h.controller.active, true);
    h.pcm(1400, 3); h.pcm(0, 18); assert.equal(h.endpoints.length, 1);
    h.finalize(); await flush();
    assert.equal(h.inputs.length, 1); assert.equal(h.inputs[0].text, '补充这个细节');
    assert.equal(h.commits.length, 1); assert.equal(h.holds.length, 0);
    assert.equal(h.frames.length, 25); assert.equal(h.interruptions, 1);
    assert.equal(h.controller.active, true);
  } finally { await h.controller.close(); }
});

test('explicit guarded playback never promotes identical energetic overlap into automatic input', async () => {
  const h = await start('guarded');
  try {
    h.setBusy(true); h.pcm(1400, 10); h.pcm(0, 18);
    assert.equal(h.interruptions, 0); assert.equal(h.endpoints.length, 0);
    assert.equal(h.inputs.length, 0); assert.equal(h.opens, 1);
  } finally { await h.controller.close(); }
});

test('a short sound and delayed delivery cannot cause automatic interruption', async () => {
  for (const delayed of [false, true]) {
    const h = await start('headphones');
    try {
      h.setBusy(true);
      if (delayed) h.pcm(1400, 8, 250);
      else { h.pcm(1400, 3); h.pcm(0, 5); }
      assert.equal(h.interruptions, 0); assert.equal(h.inputs.length, 0);
    } finally { await h.controller.close(); }
  }
});

test('the same finalized utterance keeps an earlier phrase across an internal pause after confirmed Stop', async () => {
  const h = await start('headphones');
  try {
    h.setBusy(true); h.pcm(1400, 2); h.pcm(0, 5); h.pcm(1400, 4);
    assert.equal(h.interruptions, 1); h.pcm(0, 18); h.finalize(); await flush();
    assert.equal(h.inputs.length, 1); assert.equal(h.holds.length, 0);
    assert.equal(h.views.at(-1).held_previews.length, 0);
  } finally { await h.controller.close(); }
});

test('failed local reply stop leaves overlap unpromoted and the recognized draft visible', async () => {
  const h = await start('headphones');
  try {
    h.setBusy(true); h.setCanInterrupt(false); h.pcm(1400, 4);
    assert.equal(h.interruptions, 1); assert.equal(h.endpoints.length, 0);
    h.emit({type: 'transcript', lease_id: lease, revision: 1, text: '补充这个细节', is_final: true});
    assert.equal(h.views.at(-1).transcript.text, '补充这个细节');
    assert.equal(h.inputs.length, 0);
  } finally { await h.controller.close(); }
});

test('mode is fixed for the lease and AEC status grants no interruption authority', async () => {
  const h = await start('guarded');
  try {
    h.setMode('headphones'); h.processing({echoCancellationRequested: true,
      echoCancellationSupported: true, echoCancellationReported: true});
    h.setBusy(true); h.pcm(1400, 8);
    assert.equal(h.interruptions, 0);
    assert.equal(h.views.at(-1).barge_in_mode, 'guarded');
    assert.deepEqual(h.views.at(-1).capture_processing, {echoCancellationRequested: true,
      echoCancellationSupported: true, echoCancellationReported: true});
    await h.controller.stop(); assert.equal(h.views.at(-1).capture_processing, null);
    assert.equal(h.timers.size, 0);
  } finally { await h.controller.close(); }
});

test('natural listening defaults to enabled interruption without opening capture before Start', async () => {
  const h = harness();
  try {
    assert.equal(h.opens, 0); assert.equal(h.controller.active, false);
    assert.equal(h.controller.start(), true); await flush();
    assert.equal(h.views.at(-1).barge_in_mode, 'headphones');
    assert.equal(h.views.at(-1).barge_in_available, true);
    h.setBusy(true); h.pcm(1400, 4); assert.equal(h.interruptions, 1);
    assert.equal(h.opens, 1); assert.equal(h.stops, 0);
    assert.deepEqual({...h.views.at(-1).ready}, {lease_id: lease, sample_rate_hz: 16000, max_seconds: 120,
      max_samples: 1920000, max_utterances: 12, max_streams_per_session: 4, max_total_streams: 10,
      session_lease_starts_used: 1, total_lease_starts_used: 1, endpoint_mode: 'google_vad_offsets_natural',
      manual_commit_required: false, client_endpoint_supported: true, client_silence_ms: 700,
      drain_timeout_ms: 2000, max_recognition_streams: 4});
  } finally { await h.controller.close(); }
});

test('enabled lease ignores later selection changes and rearms only after 200 ms quiet', async () => {
  const h = await start('headphones');
  try {
    h.setMode('guarded'); h.setBusy(true); h.pcm(1400, 4); assert.equal(h.interruptions, 1);
    h.setBusy(true); h.pcm(1400, 20); h.pcm(0, 4); h.pcm(1400, 4); assert.equal(h.interruptions, 1);
    h.pcm(0, 5); h.pcm(1400, 4); assert.equal(h.interruptions, 2);
    assert.equal(h.views.at(-1).barge_in_mode, 'headphones'); assert.equal(h.opens, 1);
  } finally { await h.controller.close(); }
});

test('repeated synthetic echo with no or unknown AEC trips a rapid-burst guard without renewing capture or budgets', async () => {
  for (const reported of [false, null, true]) {
    const h = await start();
    try {
      h.processing({echoCancellationRequested: true, echoCancellationSupported: reported, echoCancellationReported: reported});
      for (let cycle = 0; cycle < 10; cycle++) {
        h.pcm(0, 5); h.setBusy(true); h.pcm(1400, 4);
        if (cycle === 2) {
          assert.equal(h.interruptions, 3); assert.equal(h.views.at(-1).barge_in_available, false);
          assert.match(h.views.at(-1).notice, /短时间内连续触发.*自动插话已暂停/);
          assert.equal(h.views.at(-1).barge_in_suspended, true);
          h.emit({type: 'recognition_status', lease_id: lease, stream_index: 2, state: 'listening', stt_requests_used: 2, stt_requests_remaining: 8});
        }
      }
      assert.equal(h.interruptions, 3); assert.equal(h.opens, 1); assert.equal(h.stops, 0);
      assert.equal(h.inputs.length, 0); assert.equal(h.commits.length, 0); assert.equal(h.controller.active, true);
      assert.equal(h.controller.resumeAutomaticInterruption(), true);
      h.setBusy(false); h.pcm(1400, 3); h.pcm(0, 18); h.finalize();
      await flush(); assert.equal(h.inputs.length, 1); assert.equal(h.holds.length, 0, 'ordinary finalization remains available after early interruption pauses');
      await h.controller.stop(); assert.equal(h.views.at(-1).capture_processing, null);
      assert.throws(() => h.pcm(1400, 4), /已停止/); assert.equal(h.interruptions, 3);
    } finally { await h.controller.close(); }
  }
});

test('failed local interruption attempts are bounded and cannot promote captured overlap', async () => {
  const h = await start();
  try {
    h.setCanInterrupt(false); h.setBusy(true);
    for (let cycle = 0; cycle < 10; cycle++) {h.pcm(0, 5); h.pcm(1400, 4);}
    assert.equal(h.interruptions, 3); assert.equal(h.views.at(-1).barge_in_available, false);
    assert.equal(h.inputs.length, 0); assert.equal(h.endpoints.length, 0);
  } finally { await h.controller.close(); }
});

test('many spaced legitimate interruptions stay enabled and rapid-pause recovery keeps the current lease', async () => {
  const h = await start();
  try {
    for (let turn = 0; turn < 12; turn++) {
      h.pcm(0, 55); h.setBusy(true); h.pcm(1400, 4);
      assert.equal(h.interruptions, turn + 1); assert.equal(h.views.at(-1).barge_in_available, true);
    }
    for (let burst = 0; burst < 2; burst++) { h.pcm(0, 5); h.setBusy(true); h.pcm(1400, 4); }
    assert.equal(h.interruptions, 14); assert.equal(h.views.at(-1).barge_in_suspended, true);
    h.pcm(0, 100); h.setBusy(true); h.pcm(1400, 4); assert.equal(h.interruptions, 14);
    assert.equal(h.controller.resumeAutomaticInterruption(), true);
    assert.equal(h.views.at(-1).barge_in_suspended, false); assert.equal(h.views.at(-1).barge_in_available, true);
    h.pcm(0, 5); h.pcm(1400, 4); assert.equal(h.interruptions, 15);
    assert.equal(h.opens, 1); assert.equal(h.stops, 0); assert.equal(h.controller.active, true);
    h.pcm(1400, 1, 250); assert.equal(h.views.at(-1).barge_in_available, false);
    assert.equal(h.controller.resumeAutomaticInterruption(), false, 'explicit recovery cannot repair stale capture');
  } finally { await h.controller.close(); }
});

test('invalid capture while rapid-paused removes the resume promise and cannot clear old overlap', async () => {
  const h = await start();
  try {
    for(let cycle=0;cycle<3;cycle++){h.pcm(0,5);h.setBusy(true);h.pcm(1400,4);}
    assert.equal(h.views.at(-1).barge_in_suspended,true);
    h.pcm(1400,1,250);
    assert.equal(h.views.at(-1).barge_in_suspended,false);
    assert.equal(h.views.at(-1).barge_in_available,false);
    assert.equal(h.controller.resumeAutomaticInterruption(),false);
    h.pcm(0,10);h.setBusy(true);h.pcm(1400,4);assert.equal(h.interruptions,3);
    assert.equal(h.inputs.length,0);assert.equal(h.controller.active,true);
  }finally{await h.controller.close();}
});

test('successful Stop with unknown reply provenance still sends an exact final without invented continuation', async () => {
 const h=harness('headphones',false);h.controller.start();await flush();try{
  h.setBusy(true);h.pcm(1400,4);assert.equal(h.interruptions,1);
  h.pcm(0,18);h.finalize();await flush();assert.equal(h.inputs.length,1);assert.equal(h.holds.length,0);
  assert.equal(h.inputs[0].text,'补充这个细节');
 }finally{await h.controller.close();}
});

test('a newly confirmed barge cannot promote samples of an already settled utterance',async()=>{
 const h=await start('headphones');try{
  h.setBusy(true);h.pcm(1400,4);h.pcm(0,18);h.finalize();await flush();assert.equal(h.inputs.length,1);
  h.setBusy(true);h.pcm(250,3);h.pcm(0,6);h.pcm(1400,4);h.pcm(0,18);
  h.finalize({utterance_id:'32345678-1234-4234-8234-123456789012',revision:3,begin_offset_samples:0});await flush();
  assert.equal(h.inputs.length,1);assert.equal(h.holds.length,1,'old settled source cannot join a second final under a new identity');
 }finally{await h.controller.close();}
});

test('a rejected commit does not settle the source interval for a later exact finalized utterance',async()=>{
 const h=await start('headphones');try{
  h.setCommitReject(true);h.setBusy(true);h.pcm(1400,4);h.pcm(0,18);h.finalize();await flush();
  assert.equal(h.inputs.length,0);assert.equal(h.commits.length,1);
  h.setCommitReject(false);h.setBusy(true);h.pcm(250,3);h.pcm(0,6);h.pcm(1400,4);h.pcm(0,18);
  h.finalize({utterance_id:'32345678-1234-4234-8234-123456789012',revision:3,begin_offset_samples:0});await flush();
  assert.equal(h.inputs.length,1);assert.equal(h.holds.length,0,'rejection cannot manufacture a consumed source boundary');
 }finally{await h.controller.close();}
});
