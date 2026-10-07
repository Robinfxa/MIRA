import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=process.env.MIRA_TEST_WEB_DIST ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href : new URL('../../apps/web/dist/',import.meta.url).href;
const {SceneEffectExecutor}=await import(new URL('features/presentation/scene-executor.js',dist));
const photo={id:'photo',kind:'media',value:'trip_photo',digest:'a'.repeat(64),output_epoch:1,activity_seq:1};
function scene() {
  const slots=new Map(['subtitle','photo','pose','scene-label','phase-label','character-description','authored-photo','generated-photo','photo-label','photo-description','photo-close'].map(k=>[k,{textContent:'',hidden:k==='photo',setAttribute(){},replaceChildren(){}}]));
  const image={complete:true,naturalWidth:600,naturalHeight:400,decode:async()=>{},addEventListener(){},removeEventListener(){},getAttribute:k=>k==='src'?'/assets/scene/trip-memory.svg':null};
  const root={dataset:{},querySelector:s=>s==='[data-photo] img'?image:slots.get(s.replace(/^\[data-|\]$/g,''))??null};
  const executor=new SceneEffectExecutor(root,{characterRendererMode:'code-native-review',characterRendererFactory:null});
  return {executor,slots,root,image};
}
test('fixed SVG preparation and photo commit survive unrelated character unavailability without changing pose',async()=>{
  const h=scene();const before={...h.root.dataset};const pose=h.slots.get('pose').textContent;
  await h.executor.prepare(photo,new AbortController().signal);
  await h.executor.present(photo,new AbortController().signal,()=>true);
  assert.equal(h.slots.get('photo').hidden,false);
  assert.equal(h.slots.get('pose').textContent,pose);
  assert.equal(h.root.dataset.action,before.action);
  await assert.rejects(h.executor.prepare({...photo,kind:'pose',value:'camera_raise'},new AbortController().signal));
  h.executor.close();
});
test('fixed SVG commit still requires current authority and decoded image',async()=>{
  const h=scene();await h.executor.prepare(photo,new AbortController().signal);
  await assert.rejects(h.executor.present(photo,new AbortController().signal,()=>false));
  assert.equal(h.slots.get('photo').hidden,true);
  h.image.naturalWidth=0;
  await assert.rejects(h.executor.present(photo,new AbortController().signal,()=>true));
  assert.equal(h.slots.get('photo').hidden,true);h.executor.close();
});
const {SessionController}=await import(new URL('features/session/controller.js',dist));
const {parseSession}=await import(new URL('shared/protocol.js',dist));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const settle=async()=>{for(let i=0;i<10;i++)await tick();};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {resolve,reject,promise};};
function controllerHarness({mode='granted',prepare=async()=>{},present=async()=>{},receiptPending=false,progressPending=false}={}) {
  let clientId='',state,revision=0;
  const statuses=[],reports=[],receipts=[],errors=[],inputs=[],visuals=[];
  const build=(activity=0,fields={})=>({schema_version:'0.1.0-foundation',session_id:'session',client_instance_id:clientId,revision:++revision,activity_seq:activity,input_epoch:activity,output_epoch:activity,permit_revision:revision,phase:'ready',request_id:'request',sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null,photo_visible:false,photo_visibility_revision:0,fixed_photo:{state:'idle',reason:null,attempt_seq:0,output_epoch:0,activity_seq:0,effect_id:null},...fields});
  const api={
    async create(id){clientId=id;state=build();return {session:state,session_token:'token'};},
    async capabilities(){return {generation_mode:'injected',speech_enabled:false,microphone_enabled:false};},
    snapshot(){return new Promise(()=>{});},
    async input(req){inputs.push(req.text);const activity=req.activity_seq;const e={...photo,id:`photo-${activity}`,output_epoch:activity,activity_seq:activity};state=build(activity,{request_id:req.request_id,active_grants:mode==='granted'?[e]:[],fixed_photo:{state:mode,reason:mode==='held'?'review_unknown':null,attempt_seq:activity,output_epoch:activity,activity_seq:activity,effect_id:mode==='granted'?e.id:null}});return state;},
    async fixedPhotoProgress(body){reports.push(body);if(progressPending)return new Promise(()=>{});return state;},
    async receipt(body){receipts.push(body);if(receiptPending)return new Promise(()=>{});state={...state,fixed_photo:{...state.fixed_photo,state:'presented'},photo_visible:true,presented_effects:state.active_grants};return state;},
    async stop(req){state=build(req.activity_seq,{phase:'stopped',request_id:null});return state;},
    async dismissPhoto(){state={...state,photo_visible:false,fixed_photo:{...state.fixed_photo,state:'dismissed'}};return state;},
    async close(){},
  };
  const controller=new SessionController(api,{apply(){},prepare,present,stop(){},prepareInput(){},setPhase(){},dismissPhoto(){}},{connected(){},update(){},error(m){errors.push(m);},localStop(){},fixedPhotoStatus(m){statuses.push(m);},visualPresented(e){visuals.push(e.id);}},{apiBase:'/api/v1',pollIntervalMs:999999},{factDrainTimeoutMs:20,createPlayback:()=>({unlock:async()=>true,open:()=>null,stop(){},reconcileAuthorization(){},close:async()=>{}}),createCapture:()=>({start:async()=>false,stop(){},close:async()=>{}})});
  return {controller,api,statuses,reports,receipts,errors,inputs,visuals,get state(){return state;},async start(){await controller.connect();await controller.input('show');await settle();}};
}
test('held fixed-photo status is separate, nonfatal and cannot create an image',async()=>{
  const h=controllerHarness({mode:'held'});try{await h.start();assert(h.statuses.some(m=>m?.includes('暂未显示')));assert.equal(h.receipts.length,0);assert.equal(h.reports.length,0);await h.controller.input('keep chatting');assert.equal(h.inputs.length,2);}finally{await h.controller.close();}
});
for(const stage of ['preparation_failed','presentation_failed'])test(`exact ${stage} reaches server and keeps the session usable`,async()=>{
  const failed=async()=>{throw Error('private local message');};const h=controllerHarness(stage==='preparation_failed'?{prepare:failed}:{present:failed});
  try{await h.start();assert(h.statuses.some(m=>m?.includes('未能显示')));assert.deepEqual(h.reports.map(r=>r.outcome),['preparing',stage]);assert.equal(h.receipts.length,0);assert.equal(h.errors.some(e=>e.includes('private')),false);await h.controller.input('keep chatting');assert.equal(h.inputs.length,2);}finally{await h.controller.close();}
});
test('receipt without acknowledgement remains pending, never shown or failed',async()=>{
  const h=controllerHarness({receiptPending:true});try{await h.start();assert.equal(h.receipts.length,1);assert(h.statuses.some(m=>m?.includes('正在确认')));assert.equal(h.statuses.some(m=>m?.includes('已展示')),false);assert.equal(h.statuses.some(m=>m?.includes('未能显示')),false);}finally{await h.controller.close();}
});
test('Stop and late failed preparation cannot overwrite a newer displayed attempt',async()=>{
  const d=deferred();let calls=0;const h=controllerHarness({prepare:()=>++calls===1?d.promise:Promise.resolve()});
  try{await h.start();await h.controller.stop();await h.controller.input('new attempt');await settle();assert(h.statuses.at(-1)?.includes('已展示'));d.reject(Error('late private'));await settle();assert(h.statuses.at(-1)?.includes('已展示'));assert.equal(h.reports.some(r=>r.outcome.endsWith('_failed')),false);assert.equal(h.receipts.length,1);}finally{await h.controller.close();}
});
test('unconfirmed photo diagnostics do not prevent the next ordinary input',async()=>{
  const h=controllerHarness({prepare:async()=>{throw Error('decode');},progressPending:true});try{await h.start();await h.controller.input('continue');assert.equal(h.inputs.length,2);}finally{await h.controller.close();}
});
test('fixed status parser rejects arbitrary metadata instead of showing it',()=>{
  const h=controllerHarness();const base={schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:'c',revision:1,activity_seq:1,input_epoch:1,output_epoch:1,permit_revision:1,phase:'ready',request_id:'r',sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null};
  const status={state:'held',reason:'review_unknown',attempt_seq:1,output_epoch:1,activity_seq:1,effect_id:null};
  assert.equal(parseSession({...base,fixed_photo:status}).fixed_photo.state,'held');
  for(const patch of [{caption:'private'},{state:'secret'},{reason:'raw error'},{activity_seq:true},{effect_id:'not-an-id'}])assert.throws(()=>parseSession({...base,fixed_photo:{...status,...patch}}));
  void h.controller.close();
});
