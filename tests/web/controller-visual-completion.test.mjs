import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const dist = process.env.MIRA_TEST_WEB_DIST
  ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href
  : new URL('../../apps/web/dist/', import.meta.url).href;
const { SceneEffectExecutor } = await import(new URL('features/presentation/scene-executor.js', dist));
const { createCodeNativeCharacterRenderer } = await import(new URL('features/presentation/code-native-character-renderer.js', dist));
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

function harness(grantsForInput, { prepare = true, speechEnabled = false, present = null, executor: suppliedExecutor = null } = {}) {
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
  const executor = suppliedExecutor ?? {
    apply(grant) { applied.push(grant.id); shown.push(grant.id); },
    prepareInput() {}, stop() {}, setPhase() {},
  };
  if (present) executor.present = present;
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

test('animated visual gets no receipt before the completion promise resolves', async () => {
  const completion = deferred();
  const started = [];
  const h = harness(() => [effect('raise', 'pose', 'camera_raise')], {
    present(grant, signal) { started.push({grant,signal}); return completion.promise; },
  });
  try {
    await h.start(); await h.input('raise');
    h.tasks.get('raise').resolve(); await settle();
    assert.equal(started.length, 1, 'the optional completion API must be invoked');
    assert.deepEqual(h.receipts, [], 'starting interpolation is not a final pose');
    completion.resolve(); await settle();
    assert.deepEqual(h.receipts.map(r => r.effect_id), ['raise']);
  } finally { completion.resolve(); await h.close(); }
});

test('captions and actual speech submission pass an unready optional action while visual actions remain ordered', async () => {
  const motion = deferred(), second = deferred();
  const commits = [];
  const speech = {...effect('speech', 'speech', 'spoken text'), cue_id:'cue', cue_speech_id:'speech'};
  const caption = {...effect('caption', 'subtitle', 'spoken text'), cue_id:'cue', cue_speech_id:'speech'};
  const h = harness(() => [{...effect('raise','pose','camera_raise'),cue_id:'visual-raise'},speech,caption,{...effect('scene','scene','cafe_warm'),cue_id:'visual-scene'}], {
    speechEnabled: true,
    present(grant) { commits.push(grant.id); return grant.id === 'raise' ? motion.promise : grant.id === 'scene' ? second.promise : Promise.resolve(); },
  });
  try {
    await h.start(); await h.input('speak');
    assert.deepEqual(h.started.map(x=>x.id), ['raise']);
    await h.submitSpeechSample();
    assert.deepEqual(h.started.map(x=>x.id), ['raise','caption']);
    h.tasks.get('caption').resolve(); await settle();
    assert.deepEqual(h.receipts.map(x=>x.effect_id), ['caption']);
    assert.deepEqual(commits, ['caption']);
    h.tasks.get('raise').resolve(); await settle();
    assert.deepEqual(commits, ['caption','raise']);
    assert.equal(h.tasks.has('scene'), false, 'later optional visuals cannot start before camera completion');
    for(let i=0;i<3;i++)h.install({...h.current,revision:h.current.revision+i+1});
    await settle();assert.deepEqual(commits, ['caption','raise']);
    motion.resolve();await settle();
    assert.deepEqual(h.receipts.map(x=>x.effect_id), ['caption','raise']);
    h.tasks.get('scene').resolve();await settle();second.resolve();await settle();
    assert.deepEqual(h.receipts.map(x=>x.effect_id), ['caption','raise','scene']);
  } finally {motion.resolve();second.resolve();await h.close();}
});

test('Stop, new input, revoke and close abort started motion and fence an uncooperative late completion', async t => {
  for(const reason of ['stop','new-input','revoke','close'])await t.test(reason, async()=>{
    const completion=deferred();let signal;
    const h=harness(text=>text==='old'?[effect('raise','pose','camera_raise')]:[],{
      present(_effect,receivedSignal){signal=receivedSignal;return completion.promise;},
    });
    try{
      await h.start();await h.input('old');h.tasks.get('raise').resolve();await settle();
      assert.ok(signal);assert.equal(signal.aborted,false);assert.deepEqual(h.receipts,[]);
      if(reason==='stop')await h.stop();
      else if(reason==='new-input')await h.input('new');
      else if(reason==='close')await h.close();
      else h.install({...h.current,revision:h.current.revision+1,permit_revision:h.current.permit_revision+1,active_grants:[]});
      assert.equal(signal.aborted,true);
      completion.resolve();await settle();assert.deepEqual(h.receipts,[]);
    }finally{completion.resolve();await h.close();}
  });
});

test('failed motion preserves already presented text and remains one attempt on duplicate grants',async()=>{
  const completion=deferred();let motionStarts=0;
  const h=harness(()=>[effect('prefix','subtitle','A complete prefix.'),effect('raise','pose','camera_raise')],{
    present(grant){if(grant.kind==='subtitle')return Promise.resolve();motionStarts++;return completion.promise;},
  });
  try{
    await h.start();await h.input('talk');h.tasks.get('prefix').resolve();h.tasks.get('raise').resolve();await settle();
    assert.deepEqual(h.receipts.map(x=>x.effect_id),['prefix']);
    completion.reject(new Error('Canvas copy failed'));await settle();
    h.install({...h.current,revision:h.current.revision+1});await settle();
    assert.equal(motionStarts,1);assert.deepEqual(h.receipts.map(x=>x.effect_id),['prefix']);
    assert.equal(h.errors.length,1);
  }finally{completion.resolve();await h.close();}
});

test('completion-capable media still fails closed without an explicit resource readiness gate',async()=>{
  let started=0;
  const h=harness(()=>[effect('photo','media','trip_photo')],{prepare:false,present(){started++;return Promise.resolve();}});
  try{await h.start();await h.input('photo');assert.equal(started,0);assert.deepEqual(h.receipts,[]);assert.equal(h.errors.length,1);}
  finally{await h.close();}
});

function rendererHarness({reduced=false}={}) {
  const listeners=new Map(), mediaListeners=new Map(), frames=new Map(), allFrames=[];
  let next=0, copies=0, fills=0, clips=0, failCopy=false, failFill=false;
  const contexts=[];
  const host={dataset:{},children:[],appendChild(canvas){this.children.push(canvas);canvas.host=this;}};
  const media={matches:reduced,addEventListener:(name,cb)=>mediaListeners.set(name,cb),removeEventListener:name=>mediaListeners.delete(name)};
  const document={visibilityState:'visible',addEventListener:(name,cb)=>listeners.set(name,cb),removeEventListener:name=>listeners.delete(name)};
  const createCanvas=()=>{
    const context={globalAlpha:1,save(){},restore(){},translate(){},rotate(){},scale(){},clearRect(){},fill(){if(failFill)throw new Error('path draw failed');fills++;},clip(){clips++;},drawImage(){if(failCopy)throw new Error('copy failed');copies++;}};
    contexts.push(context);
    return {width:0,height:0,setAttribute(){},getContext:()=>context,remove(){if(this.host)this.host.children=this.host.children.filter(c=>c!==this);}};
  };
  return {host,document,media,contexts,frames,allFrames,
    get copies(){return copies;},get fills(){return fills;},get clips(){return clips;},
    failCopy(value=true){failCopy=value;},failFill(value=true){failFill=value;},
    hide(){document.visibilityState='hidden';listeners.get('visibilitychange')?.();},
    show(){document.visibilityState='visible';listeners.get('visibilitychange')?.();},
    reduce(matches){media.matches=matches;mediaListeners.get('change')?.({matches});},
    options:{document,window:{matchMedia:()=>media},createCanvas,createPath:data=>({data}),
      requestAnimationFrame:cb=>{const id=++next;frames.set(id,cb);allFrames.push(cb);return id;},cancelAnimationFrame:id=>frames.delete(id)},
    tick(t){const [id,cb]=frames.entries().next().value;frames.delete(id);cb(t);},
  };
}

async function realScene(grants, {decode = async()=>{}, hidden = false} = {}) {
  const native = rendererHarness();
  const renderer = await createCodeNativeCharacterRenderer(native.host,native.options);
  if(hidden)native.hide();
  const slots = new Map(['subtitle','photo','pose','scene-label','phase-label','character-description'].map(name=>[name,{textContent:'',hidden:true}]));
  const image = Object.assign(new EventTarget(),{complete:true,naturalWidth:80,decode,getAttribute:()=>'/assets/scene/cafe-night.svg'});
  const root = {dataset:{},querySelector(selector){
    if(selector==='.character-anchor')return native.host;
    if(selector==='[data-photo] img'||selector==='[data-scene-source="classic"]')return image;
    return slots.get(selector.slice(6,-1));
  }};
  const executor = new SceneEffectExecutor(root,{characterRendererMode:'code-native-review',characterRendererFactory:async()=>renderer});
  const session = harness(grants,{prepare:false,executor});
  await session.start();await settle();
  return {native,renderer,root,slots,image,executor,session,
    advance(start=0,end=1100){for(let timestamp=start;timestamp<=end;timestamp+=100)native.tick(timestamp);},
  };
}

test('real controller/executor/animated renderer receives only terminal camera facts and preserves captions and ordered scene',async()=>{
  const h=await realScene(()=>[effect('raise','pose','camera_raise'),effect('caption','subtitle','Current words.'),effect('scene','scene','cafe_warm')]);
  try{
    await h.session.input('raise and speak');
    assert.deepEqual(h.session.receipts.map(x=>x.effect_id),['caption']);
    assert.equal(h.slots.get('subtitle').textContent,'Current words.');
    assert.equal(h.root.dataset.scene,'cafe');
    h.advance(0,500);await settle();
    assert.ok(h.renderer.getMotionState().progress>0&&h.renderer.getMotionState().progress<1);
    assert.equal(h.renderer.getMotionState().status,'running');
    assert.equal(h.root.dataset.action,'camera_partial');
    assert.match(h.slots.get('pose').textContent,/尚未完成/);
    assert.deepEqual(h.session.receipts.map(x=>x.effect_id),['caption']);
    for(let i=0;i<3;i++)h.session.install({...h.session.current,revision:h.session.current.revision+i+1});
    h.advance(600,1000);await settle();
    assert.equal(h.renderer.getMotionState().progress,1);
    assert.equal(h.root.dataset.action,'camera_raise');
    assert.equal(h.root.dataset.scene,'cafe_warm');
    assert.equal(h.slots.get('subtitle').textContent,'Current words.');
    assert.deepEqual(h.session.receipts.map(x=>x.effect_id),['caption','raise','scene']);
  }finally{await h.session.close();}
});

test('real interruption retains partial geometry and honest labels; stale frame cannot complete it',async t=>{
  for(const reason of ['stop','new-input','revoke','close'])await t.test(reason,async()=>{
    const h=await realScene(text=>text==='old'?[effect('raise','pose','camera_raise')]:[]);
    try{
      await h.session.input('old');h.advance(0,400);const progress=h.renderer.getMotionState().progress;
      assert.ok(progress>0&&progress<1);const stale=h.native.allFrames.at(-1);
      if(reason==='stop')await h.session.stop();
      else if(reason==='new-input')await h.session.input('new');
      else if(reason==='close')await h.session.close();
      else h.session.install({...h.session.current,revision:h.session.current.revision+1,permit_revision:h.session.current.permit_revision+1,active_grants:[]});
      await settle();const copies=h.native.copies;stale(5000);await settle();
      assert.equal(h.native.copies,copies);assert.equal(h.renderer.getMotionState().progress,progress);
      assert.equal(h.renderer.getMotionState().status,'cancelled');
      assert.deepEqual(h.session.receipts,[]);
      if(reason!=='close'){
        assert.equal(h.root.dataset.action,'camera_partial');
        assert.match(h.slots.get('pose').textContent,/中断.*中途/);
      }
    }finally{await h.session.close();}
  });
});

test('real camera return interpolates from raised pose; repeated current target stays still',async()=>{
  const h=await realScene(text=>[effect(text,'pose',text==='back'?'camera_ready':'camera_raise')]);
  try{
    await h.session.input('first');h.advance();await settle();assert.equal(h.renderer.getMotionState().progress,1);
    await h.session.input('again');await settle();
    assert.equal(h.renderer.getMotionState().status,'completed');assert.equal(h.renderer.getMotionState().progress,1);
    assert.deepEqual(h.session.receipts.map(x=>x.effect_id),['first','again']);
    await h.session.input('back');h.advance(0,500);await settle();
    assert.ok(h.renderer.getMotionState().progress>0&&h.renderer.getMotionState().progress<1);
    assert.deepEqual(h.session.receipts.map(x=>x.effect_id),['first','again']);
    h.advance(600,1000);await settle();assert.equal(h.renderer.getMotionState().progress,0);
    assert.equal(h.root.dataset.action,'camera_ready');
    assert.deepEqual(h.session.receipts.map(x=>x.effect_id),['first','again','back']);
  }finally{await h.session.close();}
});

test('real unready and failed camera leave a successful text prefix intact without a camera receipt',async t=>{
  for(const failure of ['hidden','copy'])await t.test(failure,async()=>{
    const h=await realScene(()=>[effect('prefix','subtitle','A completed prefix.'),effect('raise','pose','camera_raise')],{hidden:failure==='hidden'});
    try{
      await h.session.input('talk');
      if(failure==='copy'){
        h.advance(0,800);const previous=h.renderer.getMotionState().progress;
        h.native.failCopy();h.native.tick(900);await settle();
        assert.equal(h.renderer.getMotionState().progress,previous);
        assert.equal(h.native.host.children.length,1,'failed frame keeps the last successful canvas');
        assert.equal(h.root.dataset.action,'camera_partial');
      }
      assert.deepEqual(h.session.receipts.map(x=>x.effect_id),['prefix']);
      assert.equal(h.slots.get('subtitle').textContent,'A completed prefix.');
      assert.equal(h.session.errors.length,1);
    }finally{h.native.failCopy(false);await h.session.close();}
  });
});

test('real local photo waits for decode while text proceeds and revoked late decode cannot show the image',async t=>{
  for(const cancel of [false,true])await t.test(cancel?'revoked':'decoded',async()=>{
    const decoded=deferred();let decodes=0;
    const h=await realScene(()=>[effect('photo','media','trip_photo'),effect('prefix','subtitle','Here is a local travel illustration.')],{
      decode:()=>{decodes++;return decoded.promise;},
    });
    try{
      await h.session.input('show');assert.equal(decodes,1);
      assert.deepEqual(h.session.receipts.map(x=>x.effect_id),['prefix']);assert.equal(h.slots.get('photo').hidden,true);
      if(cancel)h.session.install({...h.session.current,revision:h.session.current.revision+1,permit_revision:h.session.current.permit_revision+1,active_grants:[]});
      decoded.resolve();await settle();
      assert.equal(h.slots.get('photo').hidden,cancel);
      assert.deepEqual(h.session.receipts.map(x=>x.effect_id),cancel?['prefix']:['prefix','photo']);
    }finally{decoded.resolve();await h.session.close();}
  });
});

test('independent real captions retain cue chunk order and dwell while an optional camera is pending',async()=>{
  const descriptor=Object.getOwnPropertyDescriptor(globalThis,'performance');let now=0;
  Object.defineProperty(globalThis,'performance',{configurable:true,value:{now:()=>now}});
  const values=['First. ','Second. ','Third.'];let start=0;
  const chunks=values.map((value,index)=>{const end=start+value.length;const grant={
    ...effect(`chunk-${index}`,'subtitle',value),cue_id:`chunk-cue-${index}`,
    caption_chunk:{group_id:'12345678-1234-1234-1234-123456789abc',index,start,end,total:values.join('').length,source_sha256:'b'.repeat(64)},
  };start=end;return grant;});
  const h=await realScene(()=>[{...effect('raise','pose','camera_raise'),cue_id:'visual'},...chunks]);
  try{
    await h.session.input('chunks');
    assert.deepEqual(h.session.receipts.map(x=>x.effect_id),['chunk-0']);
    h.session.install({...h.session.current,revision:h.session.current.revision+1});await settle();
    assert.deepEqual(h.session.receipts.map(x=>x.effect_id),['chunk-0']);
    now=800;h.session.install({...h.session.current,revision:h.session.current.revision+2});await settle();
    assert.deepEqual(h.session.receipts.map(x=>x.effect_id),['chunk-0','chunk-1']);
    assert.equal(h.renderer.getMotionState().status,'running');
    await h.session.stop();now=1600;
    h.session.install({...h.session.current,revision:h.session.current.revision+3});await settle();
    assert.deepEqual(h.session.receipts.map(x=>x.effect_id),['chunk-0','chunk-1']);
  }finally{await h.session.close();Object.defineProperty(globalThis,'performance',descriptor);}
});
