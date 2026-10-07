import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import vm from 'node:vm';
const sourceRoot = resolve(process.env.MIRA_TEST_SOURCE_ROOT ?? process.cwd());
const html = await readFile(resolve(sourceRoot, 'apps/web/index.html'), 'utf8');
const dist = resolve(process.env.MIRA_TEST_WEB_DIST ?? 'apps/web/dist');
const compiled = (await readFile(resolve(dist, 'app/main-source.js'), 'utf8')).replace(/^import .*;\n/gm, '');
const distUrl = pathToFileURL(dist + '/');
const {SessionController} = await import(new URL('features/session/controller.js', distUrl));
const {ContinuousListeningController} = await import(new URL('features/session/continuous-listening.js', distUrl));
const {CancelSafePlayback} = await import(new URL('features/audio/playback.js', distUrl));
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {let resolve, reject; const promise = new Promise((yes, no) => {resolve = yes; reject = no;}); return {promise, resolve, reject};};
class Node {
  constructor(tag='div',attrs={}) {this.tagName=tag.toUpperCase();this.attrs=attrs;this.children=[];this.parentElement=null;this.listeners=new Map();this.dataset={};this.value='';this._text='';this.hidden='hidden' in attrs;this.disabled='disabled' in attrs;this.scrollTop=0;this.scrollHeight=400;this.clientHeight=400;for(const [k,v] of Object.entries(attrs))if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]=v;}
  get className(){return this.attrs.class??'';} set className(v){this.attrs.class=v;}
  get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}set textContent(v){this._text=v;this.children=[];}
  get firstElementChild(){return this.children[0]??null;}
  append(...nodes){for(const n of nodes){n.parentElement=this;this.children.push(n);}}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
  setAttribute(k,v){this.attrs[k]=String(v);}
  getAttribute(k){return this.attrs[k]??null;}
  addEventListener(k,f){const list=this.listeners.get(k)??[];list.push(f);this.listeners.set(k,list);}
  fire(k,extras={}){const e={defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},...extras};for(const f of this.listeners.get(k)??[])f(e);return e;}
  requestSubmit(){this.fire('submit');}
  focus(){this.focused=true;}
  setPointerCapture(){}
  querySelectorAll(selector){const matches=[];const match=n=>{if(selector.startsWith('[')){const [,key,value]=selector.match(/^\[([^=\]]+)(?:=['"]?([^'"\]]+)['"]?)?\]$/)??[];return key in n.attrs&&(value===undefined||n.attrs[key]===value);}if(selector.startsWith('.'))return n.className.split(/\s+/).includes(selector.slice(1));const [tag,cls]=selector.split('.');return n.tagName.toLowerCase()===tag&&(!cls||n.className.split(/\s+/).includes(cls));};const visit=n=>{for(const child of n.children){if(match(child))matches.push(child);visit(child);}};visit(this);return matches;}
  querySelector(s){return this.querySelectorAll(s)[0]??null;}
}
function parseHtml(source){
  const root=new Node('document'), stack=[root];const voids=new Set(['meta','link','input','img','br','hr','source','wbr']);
  for(const token of source.matchAll(/<!--[\s\S]*?-->|<![^>]+>|<\/?[a-zA-Z][^>]*>|[^<]+/g)){
    const value=token[0];if(value.startsWith('<!'))continue;
    if(value.startsWith('</')){const tag=value.slice(2,-1).trim().toLowerCase();assert.equal(stack.at(-1).tagName.toLowerCase(),tag,`shipping HTML closes ${tag} in the proper tree`);stack.pop();continue;}
    if(value.startsWith('<')){const [,tag,raw]=value.match(/^<([\w-]+)([\s\S]*?)\/?\s*>$/);const attrs={};for(const m of raw.matchAll(/([^\s=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g))attrs[m[1]]=m[2]??m[3]??m[4]??'';const n=new Node(tag,attrs);stack.at(-1).append(n);if(!voids.has(tag)&&!value.endsWith('/>'))stack.push(n);}
    else stack.at(-1)._text+=value;
  }
  assert.equal(stack.length,1,'all shipping HTML elements close');return root;
}

// This strict first-activation model verifies call placement; it does not emulate a named browser.
function app({denyCapture = false, denyPlayback = false, delayedResume = false, natural = false, clientEndpoint = false, maxUtterances = 12, guarded = false, restoredBargeMode = null, storedBargeMode = null, unlimited = false} = {}) {
  const document = parseHtml(html), window = new Node('window');
  document.body = document.querySelector('body'); document.visibilityState = 'visible';
  document.createElement = tag => new Node(tag);
  document.querySelector('[data-continuous-barge-mode]').value = restoredBargeMode ?? 'headphones';
  const preferences = new Map(guarded ? [['mira.voice.barge-mode.v1', 'guarded']] : storedBargeMode === null ? [] : [['mira.voice.barge-mode.v1', storedBargeMode]]);
  window.localStorage = {getItem: key => preferences.get(key) ?? null, setItem: (key, value) => preferences.set(key, value)};
  const calls = [], inputs = [], sources = [], streams = [], resumes = [];
  const resumeGate = deferred(), stopGate = deferred();
  let inGesture = false, activated = false, client, revision = 0, controller, continuous;
  let captureAllowed = !denyCapture, playbackAllowed = !denyPlayback, captureSettings, sample = 0, sequence = 0;
  let current = {activity_seq: 0, input_epoch: 0, output_epoch: 0, request_id: null,
    phase: 'idle', sealed: true, active_grants: []};
  const snapshot = () => ({schema_version: '0.1.0-foundation', session_id: 'synthetic-session',
    client_instance_id: client, revision: ++revision, permit_revision: revision,
    presented_effects: [], audio_progress: [], last_error: null, ...current});
  const context = {
    state: 'suspended', destination: {},
    resume() {
      const permitted = activated || inGesture;
      resumes.push({inGesture, permitted}); calls.push('resume');
      if (!playbackAllowed || !permitted) return Promise.reject(new Error('synthetic activation denied'));
      activated = true;
      return (delayedResume ? resumeGate.promise : Promise.resolve()).then(() => {context.state = 'running';});
    },
    createBuffer(_channels, frames) {const channel = new Float32Array(frames); return {getChannelData: () => channel};},
    createBufferSource() {
      const source = {onended: null, buffer: null, started: false, stopped: false,
        connect() {}, disconnect() {}, start() {source.started = true; calls.push('pcm-start');},
        stop() {source.stopped = true; calls.push('pcm-stop');}};
      sources.push(source); return source;
    },
    close: async () => {context.state = 'closed'; calls.push('context-close');},
  };
  const api = {
    async create(id) {client = id; return {session: snapshot(), session_token: 'synthetic'};},
    async capabilities() {return {generation_mode: 'mock', qualification: 'injected_unverified',
      speech_enabled: true, microphone_enabled: true, continuous_listening_enabled: true,
      speech_sample_rate_hz: 24000, microphone_sample_rate_hz: 16000};},
    snapshot: () => new Promise(() => {}),
    async input(request) {
      calls.push('input'); inputs.push(request);
      const effect = {id: `speech-${request.activity_seq}`, kind: 'speech', value: 'synthetic reply',
        digest: 'a'.repeat(64), activity_seq: request.activity_seq, output_epoch: request.activity_seq};
      current = {...current, activity_seq: request.activity_seq, input_epoch: request.activity_seq,
        output_epoch: request.activity_seq, request_id: request.request_id, phase: 'ready', active_grants: [effect]};
      return snapshot();
    },
    async stop(request) {
      calls.push('session-stop'); current = {...current, activity_seq: request.activity_seq,
        output_epoch: request.activity_seq, request_id: null, phase: 'stopped', active_grants: []};
      return snapshot();
    },
    receipt: async () => snapshot(), audioProgress: async () => snapshot(),
    async speech(_effect, _signal, push) {calls.push('speech'); await push(new Int16Array([1, 2])); await new Promise(() => {});},
    close: async () => {calls.push('session-close');},
    continuousListening(leaseId, signal, observers, mode) {
      const ready = {type: 'ready', lease_id: leaseId, sample_rate_hz: 16000, max_seconds: 120,
        max_samples: 1920000, max_utterances: maxUtterances, max_streams_per_session: 4,
        max_total_streams: 10, session_lease_starts_used: 1, total_lease_starts_used: 1,
        endpoint_mode: natural ? 'google_vad_offsets_natural' : 'google_vad_offsets_manual_commit', manual_commit_required: !natural,
        natural_grace_ms:natural?750:0,drain_timeout_ms:2000,max_recognition_streams:4,
        ...(clientEndpoint ? {client_endpoint_supported:true,client_silence_ms:700} : {}),
        ...(unlimited ? {max_seconds:null,max_samples:null,max_utterances:null,max_streams_per_session:null,max_total_streams:null,max_recognition_streams:null,stt_requests_used:300,stt_requests_remaining:null} : {})};
      const commits = [], holds = [], endpoints = [], cancels = [];
      const stream = {leaseId, signal, observers, commits, holds, endpoints, cancels, mode, ready: Promise.resolve(ready), closed: new Promise(() => {}),
        send() {}, endpoint(id,end) {endpoints.push({id,end});}, cancelEndpoint(id) {cancels.push(id);}, commit(id, revision, utteranceId) {calls.push('commit'); const result = deferred(); commits.push({id, revision, utteranceId, ...result}); return result.promise;},
        hold(utteranceId,revision) {calls.push('hold');const result=deferred();holds.push({utteranceId,revision,...result});return result.promise;},
        stop() {calls.push('lease-stop'); return stopGate.promise;}, cancel() {calls.push('lease-cancel');}};
      streams.push(stream); return stream;
    },
  };
  class Controller extends SessionController {
    constructor(api, effects, view, config, options) {
      super(api, effects, view, config, {...options,
        createPlayback: settings => new CancelSafePlayback({...settings,
          createContext: () => {calls.push('context-create'); return context;},
          setInterval: () => 1, clearInterval() {}}),
        createCapture: () => ({start() {throw new Error('No PTT requested');}, stop() {}, async close() {}})});
      controller = this;
    }
  }
  class Continuous extends ContinuousListeningController {
    constructor(options) {
      super({...options, createCapture: settings => {captureSettings = settings; return ({
        start() {
          calls.push('capture-start'); assert.equal(inGesture, true, 'capture starts only from the click');
          if (!captureAllowed) {settings.onError({code: 'permission-denied', message: 'synthetic microphone denied'}); return Promise.resolve(false);}
          settings.onState('recording'); return Promise.resolve(true);
        }, stop() {calls.push('capture-stop');}, async close() {calls.push('capture-close');},
      });}});
      continuous = this;
    }
  }
  class Panel {recordingActive = false; start() {} close() {} setCanEnable() {} setContinuousListeningBlocked() {} invalidateForNewInput() {} invalidateForStop() {} auditionState() {}}
  vm.runInNewContext(compiled, {document, window, navigator: {mediaDevices: {getUserMedia() {throw new Error('No real microphone');}}},
    globalThis: {AudioContext: class {}, AudioWorkletNode: class {}, isSecureContext: true},
    loadPublicConfig: () => ({apiBase: '/api/v1', pollIntervalMs: 200}), watchDiagnosticsStatus: () => ({close() {}}),
    recordingNotice: () => ({visible: false, text: '', state: 'off'}), safeSessionError: () => 'synthetic safe error',
    MiraApiClient: class {constructor() {return api;}}, MiraHttpError: class extends Error {},
    SessionController: Controller, ContinuousListeningController: Continuous,
    SceneEffectExecutor: class {apply() {} prepareInput() {} stop() {} close() {} setPhase() {}}, ReviewedAudioPanel: Panel});
  const node = selector => {const value = document.querySelector(selector); assert.ok(value, selector); return value;};
  const gesture = fn => {inGesture = true; try {return fn();} finally {inGesture = false;}};
  const click = selector => gesture(() => node(selector).fire('click'));
  const submit = (text, via = 'submit') => {const input = node('[name=message]'); input.value = text; input.fire('input');
    gesture(() => via === 'Enter' ? input.fire('keydown', {key: 'Enter'}) : node('form.composer').fire('submit'));};
  const preview = (text = 'stable text', revision = 1) => {const s = streams.at(-1);
    s.observers.onEvent({type: 'transcript', lease_id: s.leaseId, revision, text, is_final: true});};
  const resolveCommit = (fields = {}) => {const s = streams.at(-1), c = s.commits.at(-1);
    c.resolve({type: 'commit_ready', lease_id: s.leaseId, commit_id: c.id, segment_seq: 1,
      revision: c.revision, text: 'confirmed text', ...(c.utteranceId ? {utterance_id:c.utteranceId} : {}), ...fields});};
  const close = async () => {stopGate.resolve(); resumeGate.resolve(); await continuous.close(); await controller.close();};
  return {node, calls, inputs, sources, streams, resumes, resumeGate, stopGate, context, gesture, click, submit, preview, resolveCommit, close,
    pcm(level, count = 1, lag = 0) {for (let i = 0; i < count; i++) {const bytes = new Int16Array(640).fill(level);
      captureSettings.onChunk({pcm16le:new Uint8Array(bytes.buffer),sampleRate:16000,channels:1,
        sequence:sequence++,startSample:sample,endSample:sample+=640,deliveryLagMilliseconds:lag});}},
    pagehide: () => window.fire('pagehide'), pageshow: () => window.fire('pageshow'), preferences,
    get controller() {return controller;}, get continuous() {return continuous;},
    allowCapture() {captureAllowed = true;}, allowPlayback() {playbackAllowed = true;}};
}

for (const via of ['submit', 'Enter', 'preset']) test(`${via} prepares the existing playback sink before pending lease teardown`, async () => {
  const h = app();
  try {
    await tick(); assert.deepEqual(h.resumes, []); assert.equal(h.calls.includes('capture-start'), false);
    h.click('[data-continuous-listening]'); await tick(); assert.equal(h.resumes.length, 1);
    assert.equal(h.resumes[0].inGesture, true, 'natural start prepares playback before any asynchronous speech');
    if (via === 'preset') h.click('[data-command]'); else h.submit('intentional text', via);
    assert.equal(h.resumes[1]?.inGesture, true, 'this send also prepares playback before the teardown await');
    assert.ok(h.calls.indexOf('resume') < h.calls.indexOf('lease-stop'));
    assert.equal(h.inputs.length, 0); assert.equal(h.sources.length, 0);
    h.stopGate.resolve(); await tick(); await tick();
    assert.equal(h.inputs.length, 1); assert.equal(h.sources.filter(source => source.started).length, 1);
    assert.equal(h.calls.filter(call => call === 'context-create').length, 1);
    assert.equal(h.calls.filter(call => call === 'capture-start').length, 1);
  } finally {await h.close();}
});

test('continuous Send prepares before commit, retains the microphone lease, and starts no unconfirmed PCM', async () => {
  const h = app();
  try {
    await tick(); h.click('[data-continuous-listening]'); await tick(); h.preview();
    h.click('[data-continuous-send]');
    assert.equal(h.resumes[0]?.inGesture, true, 'first activation precedes the commit await');
    assert.ok(h.calls.indexOf('resume') < h.calls.indexOf('commit'));
    assert.equal(h.inputs.length, 0); assert.equal(h.sources.length, 0); assert.equal(h.continuous.active, true);
    h.resolveCommit(); await tick(); await tick();
    assert.equal(h.inputs.length, 1); assert.equal(h.inputs[0].text, 'confirmed text');
    assert.equal(h.continuous.active, true); assert.equal(h.calls.includes('lease-stop'), false);
    assert.equal(h.sources.filter(source => source.started).length, 1);
  } finally {await h.close();}
});

for (const action of ['stop', 'newer-input', 'close', 'pagehide']) test(`${action} fences a send awaiting teardown and delayed resume`, async () => {
  const h = app({delayedResume: true});
  try {
    await tick(); h.click('[data-continuous-listening]'); await tick(); h.submit('queued draft');
    assert.equal(h.inputs.length, 0); assert.equal(h.sources.length, 0);
    if (action === 'stop') h.click('[data-stop]');
    if (action === 'newer-input') h.submit('newer input');
    if (action === 'close') h.click('[data-close]');
    if (action === 'pagehide') h.pagehide();
    h.stopGate.resolve(); h.resumeGate.resolve(); await tick(); await tick();
    assert.deepEqual(h.inputs.map(input => input.text), action === 'newer-input' ? ['newer input'] : []);
    assert.equal(h.sources.filter(source => source.started).length, action === 'newer-input' ? 1 : 0);
    if (action !== 'newer-input') assert.equal(h.node('[name=message]').value, 'queued draft', 'known-undispatched text remains a recoverable draft');
  } finally {await h.close();}
});

for (const action of ['stop', 'newer-input', 'close']) test(`${action} fences a pending manual commit and late resume`, async () => {
  const h = app({delayedResume: true});
  try {
    await tick(); h.click('[data-continuous-listening]'); await tick(); h.preview('retained preview');
    h.click('[data-continuous-send]');
    if (action === 'stop') h.click('[data-stop]');
    if (action === 'newer-input') h.submit('newer input');
    if (action === 'close') h.click('[data-close]');
    h.resolveCommit(); h.stopGate.resolve(); h.resumeGate.resolve(); await tick(); await tick();
    assert.deepEqual(h.inputs.map(input => input.text), action === 'newer-input' ? ['newer input'] : []);
    assert.equal(h.sources.filter(source => source.started).length, action === 'newer-input' ? 1 : 0);
    assert.match(h.node('[data-continuous-sent-text]').textContent, /retained preview/);
  } finally {await h.close();}
});

test('preparation synchronously disconnects an old source and cannot revive it during commit', async () => {
  const h = app();
  try {
    await tick(); h.click('[data-continuous-listening]'); await tick();
    await h.gesture(() => h.controller.input('old reply')); await tick(); await tick();
    const oldSource = h.sources[0], lateEnded = oldSource.onended; assert.equal(oldSource.started, true);
    h.preview();
    h.click('[data-continuous-send]');
    assert.equal(oldSource.stopped, true); assert.equal(h.sources.length, 1);
    lateEnded(); await tick(); assert.equal(h.sources.length, 1, 'retired onended cannot restart anything');
    h.resolveCommit(); await tick(); await tick(); assert.equal(h.sources.length, 2);
    assert.equal(h.calls.filter(call => call === 'context-create').length, 1);
    assert.equal(h.calls.filter(call => call === 'capture-start').length, 1);
  } finally {await h.close();}
});

test('stale commit keeps the preview and lease for an explicit gesture retry', async () => {
  const h = app();
  try {
    await tick(); h.click('[data-continuous-listening]'); await tick(); h.preview('first preview');
    h.click('[data-continuous-send]'); h.preview('updated preview', 2);
    h.resolveCommit({type: 'commit_rejected', reason: 'stale_revision', current_revision: 2}); await tick();
    assert.equal(h.continuous.active, true); assert.equal(h.inputs.length, 0);
    assert.match(h.node('[data-continuous-preview]').textContent, /updated preview/);
    assert.equal(h.node('[data-continuous-send]').disabled, false);
    assert.equal(h.streams[0].commits.length, 1, 'no automatic retry');
    h.click('[data-continuous-send]'); h.resolveCommit({text: 'updated preview'}); await tick(); await tick();
    assert.deepEqual(h.inputs.map(input => input.text), ['updated preview']); assert.equal(h.continuous.active, true);
    assert.equal(h.resumes.filter(resume => resume.inGesture).length, 3, 'start and both explicit sends prepare playback');
    assert.equal(h.calls.filter(call => call === 'context-create').length, 1);
  } finally {await h.close();}
});

test('denied playback keeps text submission and the lease; only an explicit next send retries activation', async () => {
  const h = app({denyPlayback: true});
  try {
    await tick(); h.click('[data-continuous-listening]'); await tick(); h.preview(); h.click('[data-continuous-send]');
    h.resolveCommit(); await tick(); await tick();
    assert.equal(h.inputs.length, 1); assert.equal(h.sources.length, 0); assert.equal(h.continuous.active, true);
    const attempts = h.resumes.length; await tick(); assert.equal(h.resumes.length, attempts);
    h.allowPlayback(); h.preview('next explicit turn', 2); h.click('[data-continuous-send]'); h.resolveCommit({text: 'next explicit turn'});
    await tick(); await tick(); assert.equal(h.inputs.length, 2); assert.equal(h.sources.length, 1);
    assert.equal(h.calls.filter(call => call === 'context-create').length, 1);
    assert.equal(h.calls.filter(call => call === 'capture-start').length, 1);
  } finally {await h.close();}
});

test('denied microphone preserves the editable draft and requires a fresh explicit start', async () => {
  const h = app({denyCapture: true});
  try {
    await tick(); h.node('[name=message]').value = 'unsent typed draft'; h.node('[name=message]').fire('input');
    h.click('[data-continuous-listening]'); await tick();
    assert.equal(h.continuous.active, false); assert.equal(h.node('[name=message]').value, 'unsent typed draft');
    assert.equal(h.inputs.length, 0); assert.equal(h.sources.length, 0); assert.equal(h.resumes.length, 1);
    assert.equal(h.resumes[0].inGesture, true, 'natural start prepares playback even when capture is later denied');
    assert.equal(h.streams.length, 0, 'a capture denial already reported in the click must not open a provider lease afterward');
    assert.equal(h.calls.filter(call => call === 'capture-start').length, 1);
    h.allowCapture(); h.stopGate.resolve(); await tick(); h.click('[data-continuous-listening]'); await tick();
    assert.equal(h.continuous.active, true); assert.equal(h.calls.filter(call => call === 'capture-start').length, 2);
    assert.equal(h.node('[name=message]').value, 'unsent typed draft');
  } finally {await h.close();}
});

test('actual natural UI auto-submits a proved utterance and starts the prepared reply sink without another gesture', async () => {
  const h = app({natural: true});
  try {
    await tick(); assert.equal(h.calls.includes('capture-start'), false); assert.equal(h.resumes.length, 0);
    h.click('[data-continuous-listening]'); await tick();
    const stream=h.streams[0], token='12345678-1234-4234-8234-123456789012';
    assert.equal(stream.mode,'natural'); assert.equal(h.resumes.length,1); assert.equal(h.resumes[0].inGesture,true);
    h.preview('confirmed text'); assert.equal(stream.commits.length,0);
    stream.observers.onEvent({type:'utterance_ready',lease_id:stream.leaseId,utterance_id:token,revision:1,text:'confirmed text',
      begin_offset_samples:0,end_offset_samples:640,final_offset_samples:640,source_end_sample:640,endpoint_basis:'offset_coverage'});
    assert.equal(stream.commits.length,1); assert.match(h.node('[data-continuous-status]').textContent,/正在发送/);
    assert.equal(h.inputs.length,0); h.resolveCommit(); await tick(); await tick();
    assert.equal(h.inputs.length,1); assert.equal(h.inputs[0].text,'confirmed text');
    assert.equal(h.sources.filter(source=>source.started).length,1); assert.equal(h.continuous.active,true);
    assert.match(h.node('[data-continuous-status]').textContent,/已发送.*继续聆听/);
    assert.equal(h.resumes.filter(resume=>resume.inGesture).length,1,'normal sentence requires no extra click');
    stream.observers.onEvent({type:'utterance_revision',lease_id:stream.leaseId,utterance_id:token,commit_id:stream.commits[0].id,
      revision:2,text:'corrected text',reason:'late_result_after_submission',requires_review:true,submission_state:'accepted'});
    assert.match(h.node('[data-continuous-sent-text]').textContent,/同一句.*corrected text/);
    assert.equal(h.inputs.length,1); assert.equal(h.node('[data-conversation-log]').children.length,1);
  } finally {await h.close();}
});

test('explicit reply interruption keeps capture open and a fresh natural activity auto-sends after playback overlap', async () => {
  const h=app({natural:true,guarded:true});
  try {
    await tick();h.click('[data-continuous-listening]');await tick();
    await h.gesture(()=>h.controller.input('old reply'));await tick();await tick();
    const stream=h.streams[0],oldSource=h.sources[0],overlap='12345678-1234-4234-8234-123456789012';
    const ready={type:'utterance_ready',lease_id:stream.leaseId,utterance_id:overlap,revision:1,text:'speaker overlap',
      begin_offset_samples:0,end_offset_samples:640,final_offset_samples:640,source_end_sample:640,endpoint_basis:'offset_coverage'};
    stream.observers.onEvent(ready);await tick();assert.equal(stream.commits.length,0);
    assert.equal(h.node('[data-continuous-interrupt]').disabled,false);h.click('[data-continuous-interrupt]');
    assert.equal(oldSource.stopped,true);assert.equal(h.continuous.active,true);assert.equal(h.calls.includes('capture-stop'),false);
    stream.observers.onEvent(ready);await tick();assert.equal(stream.commits.length,0,'old playback overlap never auto-sends after interruption');
    h.preview('confirmed text',2);stream.observers.onEvent({...ready,utterance_id:'22345678-1234-4234-8234-123456789012',revision:2,
      text:'confirmed text',begin_offset_samples:640,end_offset_samples:1280,final_offset_samples:1280,source_end_sample:1280});
    assert.equal(stream.commits.length,1);h.resolveCommit();await tick();await tick();
    assert.deepEqual(h.inputs.map(input=>input.text),['old reply','confirmed text']);
    assert.equal(h.calls.filter(call=>call==='capture-start').length,1);assert.equal(h.continuous.active,true);
  } finally {await h.close();}
});

test('actual page acknowledges held drained speech and resumes a fresh automatic turn after explicit reply interruption',async()=>{
  const h=app({natural:true,guarded:true});
  try {
    await tick();h.click('[data-continuous-listening]');await tick();
    await h.gesture(()=>h.controller.input('old reply'));await tick();await tick();
    const stream=h.streams[0],heldToken='12345678-1234-4234-8234-123456789012';
    stream.observers.onEvent({type:'recognition_status',lease_id:stream.leaseId,stream_index:1,state:'awaiting_commit',stt_requests_used:1,stt_requests_remaining:9});
    stream.observers.onEvent({type:'utterance_ready',lease_id:stream.leaseId,utterance_id:heldToken,revision:1,text:'speaker overlap',
      begin_offset_samples:0,end_offset_samples:640,final_offset_samples:null,source_end_sample:640,endpoint_basis:'stream_finalized'});
    assert.equal(stream.holds.length,1);assert.equal(stream.commits.length,0);assert.match(h.node('[data-continuous-sent-text]').textContent,/speaker overlap/);
    assert.equal(h.node('[data-continuous-send]').disabled,true);h.click('[data-continuous-interrupt]');
    assert.equal(h.continuous.active,true);assert.equal(h.calls.includes('capture-stop'),false);
    const ack={type:'utterance_held',lease_id:stream.leaseId,utterance_id:heldToken,revision:1,text:'speaker overlap'};
    stream.holds[0].resolve(ack);stream.observers.onEvent(ack);
    stream.observers.onEvent({type:'recognition_status',lease_id:stream.leaseId,stream_index:2,state:'listening',stt_requests_used:2,stt_requests_remaining:8});
    h.preview('speaker overlapconfirmed text',2);stream.observers.onEvent({type:'utterance_ready',lease_id:stream.leaseId,
      utterance_id:'22345678-1234-4234-8234-123456789012',revision:2,text:'confirmed text',begin_offset_samples:640,end_offset_samples:1280,
      final_offset_samples:1280,source_end_sample:1280,endpoint_basis:'offset_coverage'});
    assert.equal(stream.commits.length,1);h.resolveCommit();await tick();await tick();
    assert.deepEqual(h.inputs.map(input=>input.text),['old reply','confirmed text']);assert.equal(stream.holds.length,1);
    assert.equal(h.calls.filter(call=>call==='capture-start').length,1);assert.equal(h.continuous.active,true);
    assert.match(h.node('[data-continuous-sent-text]').textContent,/speaker overlap/);
  } finally {await h.close();}
});


async function overlapApp(options = {}) {
  const h = app({natural:true,clientEndpoint:true,...options});
  await tick(); h.click('[data-continuous-listening]'); await tick();
  h.pcm(0, 20);
  await h.gesture(() => h.controller.input('Describe the room')); await tick(); await tick();
  return h;
}
function finishOverlap(h, {text='Add the windows and finish the description', revision=1,
    utteranceId='82345678-1234-4234-8234-123456789012', begin=12800} = {}) {
  const s=h.streams[0],ep=s.endpoints.at(-1);assert.ok(ep,'quiet finalization exists');
  const event={type:'utterance_ready',lease_id:s.leaseId,utterance_id:utteranceId,revision,text,
    begin_offset_samples:begin,end_offset_samples:ep.end,source_end_sample:ep.end,final_offset_samples:null,
    endpoint_basis:'client_silence_finalized',client_endpoint_id:ep.id};
  s.observers.onEvent({type:'endpoint_status',lease_id:s.leaseId,endpoint_id:ep.id,source_end_sample:ep.end,state:'completed'});
  s.observers.onEvent(event);return event;
}

test('default overlap: actual PCM with no detector trigger finalizes at quiet and submits once with its original intent', async () => {
  const h=await overlapApp();try {
    const source=h.sources[0],s=h.streams[0],text='Add the windows and finish the description';
    assert.equal(source.started,true);assert.equal(source.stopped,false);
    h.pcm(250,5);h.preview(text);h.pcm(250,20);
    assert.equal(source.stopped,false,'soft continuous speech never fires the loud barge detector');
    assert.equal(s.endpoints.length,0,'continuous speaking is not cut into a prefix');
    h.pcm(0,18);assert.equal(s.endpoints.length,1,'quiet is tracked even while reply PCM is playing');
    finishOverlap(h,{text});assert.equal(source.stopped,true,'reply stops locally before commit resolves');
    assert.equal(s.commits.length,1);assert.equal(h.inputs.length,1);assert.equal(h.continuous.active,true);
    h.resolveCommit({text});await tick();await tick();
    assert.equal(h.inputs.length,2);assert.equal(h.inputs[1].text,text);
    assert.equal(h.inputs[1].relation,'continuation');assert.equal(h.inputs[1].continuation_of_request_id,h.inputs[0].request_id);
    assert.equal(s.holds.length,0);assert.equal(h.calls.filter(c=>c==='capture-start').length,1);
  } finally {await h.close();}
});

test('default overlap: failed early detector attempt still finalizes and retries local stop at the normal endpoint', async () => {
  const h=await overlapApp();try {
    const original=h.controller.interruptReply.bind(h.controller);let early=0;
    h.controller.interruptReply=()=>{early++;return false;};h.pcm(1400,4);
    assert.equal(early,1);assert.equal(h.sources[0].stopped,false);
    h.controller.interruptReply=original;h.preview('Continue the room description');h.pcm(0,18);
    finishOverlap(h,{text:'Continue the room description'});h.resolveCommit({text:'Continue the room description'});
    await tick();await tick();assert.equal(h.inputs.length,2);assert.equal(h.sources[0].stopped,true);
    assert.equal(h.streams[0].holds.length,0);
  } finally {await h.close();}
});

test('default overlap: silence alone never ends or resubmits a lease', async () => {
  const h=await overlapApp();try {h.pcm(0,100);assert.equal(h.streams[0].endpoints.length,0);
    assert.equal(h.streams[0].commits.length,0);assert.equal(h.inputs.length,1);
  } finally {await h.close();}
});

for (const phase of ['before-commit','after-commit']) test(`default overlap: duplicate final and later correction ${phase} cannot become a second input`, async () => {
  const h=await overlapApp();try {
    h.pcm(250,5);h.preview('Include the doorway');h.pcm(0,18);
    const event=finishOverlap(h,{text:'Include the doorway'}),s=h.streams[0];
    s.observers.onEvent(event);assert.equal(s.commits.length,1);
    if(phase==='before-commit')h.preview('Include the doorway and the hall',2);
    h.resolveCommit({text:'Include the doorway'});await tick();await tick();
    const expected=phase==='before-commit'?1:2;assert.equal(h.inputs.length,expected);
    s.observers.onEvent(event);s.observers.onEvent({...event,revision:2,text:'Include the doorway and the hall'});
    await tick();assert.equal(s.commits.length,1);assert.equal(h.inputs.length,expected);
  } finally {await h.close();}
});

for(const action of ['stop','close','new-topic']) test(`default overlap: ${action} fences the pending exact commit`,async()=>{
  const h=await overlapApp();try {
    h.pcm(250,5);h.preview('Add the ceiling');h.pcm(0,18);finishOverlap(h,{text:'Add the ceiling'});
    if(action==='stop')h.click('[data-stop]');
    else if(action==='close')h.pagehide();
    else {h.stopGate.resolve();h.submit('A separate topic');}
    h.resolveCommit({text:'Add the ceiling'});h.stopGate.resolve();await tick();await tick();
    assert.equal(h.inputs.filter(x=>x.text==='Add the ceiling').length,0);
    assert.equal(h.continuous.active,false);
    if(action==='new-topic')assert.equal(h.inputs.at(-1).text,'A separate topic');
  } finally {await h.close();}
});

test('default overlap: a resumed partial phrase cancels finalization and preserves the complete next revision',async()=>{
  const h=await overlapApp();try {
    h.pcm(250,5);h.preview('Describe the doorway');h.pcm(0,18);
    const s=h.streams[0],first=s.endpoints[0];assert.ok(first);
    h.pcm(250,3);h.preview('Describe the doorway and the shelves',2);
    assert.deepEqual(s.cancels,[first.id]);assert.equal(s.commits.length,0);
    s.observers.onEvent({type:'endpoint_status',lease_id:s.leaseId,endpoint_id:first.id,source_end_sample:first.end,state:'cancelled'});
    h.pcm(250,10);assert.equal(s.endpoints.length,1);h.pcm(0,18);
    finishOverlap(h,{text:'Describe the doorway and the shelves',revision:2});
    h.resolveCommit({text:'Describe the doorway and the shelves'});await tick();await tick();
    assert.equal(s.commits.length,1);assert.equal(h.inputs.at(-1).text,'Describe the doorway and the shelves');
  } finally {await h.close();}
});

test('default overlap: repeated echo-like finalized turns hit the original finite lease cap and ordinary text remains available',async()=>{
  const h=await overlapApp({maxUtterances:3});try {
    const s=h.streams[0];let begin=12800;
    for(let turn=1;turn<=3;turn++) {
      const text=`Repeated room phrase ${turn}`;h.pcm(250,5);h.preview(text,turn);h.pcm(0,18);
      finishOverlap(h,{text,revision:turn,utteranceId:`${String(turn+80).padStart(8,'0')}-1234-4234-8234-123456789012`,begin});
      begin=s.endpoints.at(-1).end;h.resolveCommit({text});await tick();await tick();
    }
    assert.equal(s.commits.length,3);assert.equal(s.holds.length,0);assert.equal(h.inputs.length,4);
    assert.equal(h.continuous.active,false);assert.equal(h.streams.length,1);assert.equal(h.calls.filter(c=>c==='capture-start').length,1);
    h.stopGate.resolve();h.submit('Continue with ordinary text');await tick();await tick();
    assert.equal(h.inputs.at(-1).text,'Continue with ordinary text');
  } finally {await h.close();}
});


test('fresh compiled main overrides unmarked restored conservative selection and hides unlimited counters', async () => {
  const h = app({restoredBargeMode:'guarded',natural:true,clientEndpoint:true,unlimited:true});
  try {
    await tick(); assert.equal(h.node('[data-continuous-barge-mode]').value,'headphones');
    h.pageshow(); h.click('[data-continuous-listening]'); await tick();
    assert.equal(h.continuous.run.bargeInMode,'headphones');
    assert.doesNotMatch(h.node('[data-continuous-status]').textContent,/120|12 次|本会话已启动|服务范围已启动|额度快照|本地不限|300/);
  } finally {await h.close();}
});

test('compiled main preserves only a current explicit conservative preference across reload and resume', async () => {
  const first = app();
  try {
    await tick(); const select=first.node('[data-continuous-barge-mode]'); select.value='guarded'; select.fire('change');
    assert.equal(first.preferences.get('mira.voice.barge-mode.v1'),'guarded');
    select.value='headphones'; first.pageshow(); assert.equal(select.value,'guarded');
    const second=app({storedBargeMode:first.preferences.get('mira.voice.barge-mode.v1'),natural:true});
    try {await tick();second.click('[data-continuous-listening]');await tick();assert.equal(second.continuous.run.bargeInMode,'guarded');}
    finally {await second.close();}
  } finally {await first.close();}
});

test('provider quota failure is explicit, preserves draft, and compiled controller accepts later text', async () => {
  const h=app({natural:true,unlimited:true});
  try {
    await tick();h.click('[data-continuous-listening]');await tick();h.preview('retained spoken draft');
    const s=h.streams.at(-1);s.observers.onEvent({type:'stopped',lease_id:s.leaseId,reason:'quota_exhausted'});
    await tick();assert.equal(h.continuous.active,false);assert.match(h.node('[data-continuous-status]').textContent,/Google.*配额|供应商.*配额/);
    h.submit('text after quota');await tick();await tick();assert.equal(h.inputs.at(-1).text,'text after quota');assert.equal(h.streams.length,1);
  } finally {await h.close();}
});


test('actual compiled main and controllers accept three hundred synthetic utterances on one unlimited lease', async () => {
  const h=app({natural:true,unlimited:true});
  try {
    await tick(); h.click('[data-continuous-listening]'); await tick();
    const s=h.streams[0];
    for (let n=1;n<=300;n++) {
      const text=`synthetic utterance ${n}`, utteranceId=`${String(n).padStart(8,'0')}-1234-4234-8234-123456789012`;
      s.observers.onEvent({type:'utterance_ready',lease_id:s.leaseId,utterance_id:utteranceId,revision:n,text,
        begin_offset_samples:(n-1)*640,end_offset_samples:n*640,final_offset_samples:n*640,
        source_end_sample:n*640,endpoint_basis:'offset_coverage'});
      await tick(); assert.equal(s.commits.length,n); h.resolveCommit({text,segment_seq:n}); await tick(); await tick();
    }
    assert.equal(h.inputs.length,300);assert.equal(h.streams.length,1);assert.equal(h.continuous.active,true);
    assert.ok(h.continuous.sentText.length<=64);assert.ok(h.continuous.run.automaticAttempts.size<=64);
    assert.equal(h.calls.filter(call=>call==='capture-start').length,1);
  } finally {await h.close();}
});
