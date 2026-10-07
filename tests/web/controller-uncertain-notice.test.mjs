import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {SessionController}=await import(new URL('features/session/controller.js',dist));
const {safeSessionError}=await import(new URL('features/diagnostics/status.js',dist));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
const BODY='这部分我还不确定，先跳过。你可以补充说明，或继续聊。';

function harness({legacyView=false}={}){
 let client='',revision=0,permit=0,activity=0,output=0,inputHandler,stopHandler;
 const inputs=[],updates=[],errors=[],notices=[],applied=[],calls=[],receipts=[];
 let snapshots=0,speechCalls=0;
 let visiblePrefix='';
 const makeSnapshot=(patch={})=>({schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:client,
  revision:++revision,activity_seq:activity,input_epoch:activity,output_epoch:output,permit_revision:++permit,
  phase:'stopped',request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null,...patch});
 inputHandler=request=>Promise.resolve(makeSnapshot({phase:'idle',request_id:request.request_id,output_epoch:request.activity_seq}));
 stopHandler=()=>Promise.resolve(makeSnapshot({phase:'stopped',request_id:null}));
 const api={
  create:async clientId=>{client=clientId;return {session:makeSnapshot(),session_token:'synthetic'};},
  capabilities:async()=>({speech_enabled:false,microphone_enabled:false,speech_sample_rate_hz:24000,microphone_sample_rate_hz:16000,qualification:'injected_unverified',generation_mode:'injected'}),
  snapshot:()=>{snapshots++;return new Promise(()=>{});},
  input:request=>{inputs.push(request.text);activity=request.activity_seq;output=request.activity_seq;return inputHandler(request);},
  stop:request=>{activity=request.activity_seq;output=request.activity_seq;return stopHandler(request);},
  receipt:async receipt=>{receipts.push(receipt);return makeSnapshot();},audioProgress:async()=>makeSnapshot(),
  speech:async()=>{speechCalls++;},microphone:()=>{throw new Error('unexpected microphone path');},close:async()=>{},
 };
 const effects={apply:effect=>applied.push(effect),prepare:async()=>{},prepareInput(){calls.push('prepare-input');visiblePrefix='';},
  stop(){calls.push('effects-stop');visiblePrefix='stopped'},setPhase:phase=>calls.push(`phase:${phase}`)};
 const view={connected(){},update:snapshot=>updates.push(snapshot),error:message=>errors.push(message),localStop(){calls.push('local-stop');}};
 if(!legacyView)view.systemNotice=notice=>notices.push(notice);
 const playback={unlock:async()=>true,open:()=>null,stop:reason=>calls.push(`playback-stop:${reason}`),
  reconcileAuthorization(){},close:async()=>{},audition:()=>false,stopAudition(){},get quiescent(){return true;}};
 const capture={start:async()=>false,stop(){},close:async()=>{}};
 const controller=new SessionController(api,effects,view,{apiBase:'/api/v1',pollIntervalMs:10000},
  {createPlayback:()=>playback,createCapture:()=>capture});
 return {api,controller,effects,inputs,updates,errors,notices,applied,calls,receipts,makeSnapshot,
  get snapshots(){return snapshots;},get speechCalls(){return speechCalls;},
  get visiblePrefix(){return visiblePrefix;},set visiblePrefix(value){visiblePrefix=value;},
  setInputHandler(handler){inputHandler=handler;},setStopHandler(handler){stopHandler=handler;}};
}

async function connect(h){await h.controller.connect();await tick();}
const uncertain=(h,request)=>h.makeSnapshot({activity_seq:request.activity_seq,input_epoch:request.activity_seq,
 output_epoch:request.activity_seq,phase:'error',request_id:null,active_grants:[],last_error:'review_uncertain'});

test('review_uncertain is one nonfatal notice per activity/epoch and a later input still works',async()=>{
 const h=harness();h.setInputHandler(request=>Promise.resolve(uncertain(h,request)));
 try{
  await connect(h);assert.equal((await h.controller.input('uncertain')).status,'submitted');
  assert.deepEqual(h.notices.filter(notice=>notice!==null),[{label:'系统提示',body:BODY}]);assert.deepEqual(h.errors.filter(Boolean),[]);
  const first=h.controller.snapshot;
  h.controller.install(first);
  assert.equal(h.notices.filter(notice=>notice!==null).length,1,'repeated polls/revisions must not repeat this activity notice');
  assert.equal(h.calls.includes('effects-stop'),false,'UNKNOWN must not enter terminal failure handling');
  assert.equal(h.calls.includes('phase:idle'),true,'the local thinking indicator settles without replacing text');
  assert.equal(h.snapshots,1,'the uncertainty branch must not launch a second status fetch');
  assert.equal(h.speechCalls,0);assert.deepEqual(h.applied,[]);
  h.setInputHandler(request=>Promise.resolve(h.makeSnapshot({activity_seq:request.activity_seq,input_epoch:request.activity_seq,
   output_epoch:request.activity_seq,phase:'idle',request_id:request.request_id,active_grants:[]})));
  assert.equal((await h.controller.input('补充说明')).status,'submitted');
  assert.equal(h.notices.at(-1),null,'new input clears the old status immediately');
  const shown=h.notices.filter(notice=>notice!==null).length;
  const lateOld={...first,revision:h.controller.snapshot.revision+2,permit_revision:h.controller.snapshot.permit_revision+1};
  h.controller.install(lateOld);
  assert.equal(h.notices.filter(notice=>notice!==null).length,shown,'a late prior-activity snapshot cannot revive it');
  assert.deepEqual(h.inputs,['uncertain','补充说明']);assert.deepEqual(h.errors.filter(Boolean),[]);
  assert.deepEqual(h.receipts,[],'a notice does not create a presentation receipt');
 }finally{await h.controller.close();}
});

test('Stop and Close clear an uncertainty notice before asynchronous cleanup settles',async()=>{
 const stopped=harness();stopped.setInputHandler(request=>Promise.resolve(uncertain(stopped,request)));
 try{
  await connect(stopped);await stopped.controller.input('uncertain');
  const pendingStop=deferred();stopped.setStopHandler(()=>pendingStop.promise);
  const stop=stopped.controller.stop();
  assert.equal(stopped.notices.at(-1),null,'local Stop clears the notice synchronously');
  pendingStop.resolve(stopped.makeSnapshot({phase:'stopped',request_id:null,active_grants:[]}));await stop;
 }finally{await stopped.controller.close();}
 const closed=harness();closed.setInputHandler(request=>Promise.resolve(uncertain(closed,request)));
 await connect(closed);await closed.controller.input('uncertain');
 const close=closed.controller.close();
 assert.equal(closed.notices.at(-1),null,'Close clears the notice synchronously');
 await close;
});

test('a semantic uncertainty notice leaves an already rendered partial prefix untouched',async()=>{
 const h=harness(),requestStarted=deferred(),pending=deferred();
 h.setInputHandler(request=>{requestStarted.resolve(request);return pending.promise;});
 try{
  await connect(h);const input=h.controller.input('uncertain');const request=await requestStarted.promise;
  // Synthetic controller-port state only; this does not claim actual browser paint or user visibility.
  h.visiblePrefix='部分已呈现的内容';
  pending.resolve(uncertain(h,request));await input;
  assert.equal(h.visiblePrefix,'部分已呈现的内容');
  assert.equal(h.calls.includes('effects-stop'),false);
  assert.deepEqual(h.receipts,[]);
 }finally{await h.controller.close();}
});

test('legacy views receive at most one fallback and it clears on the next input',async()=>{
 const h=harness({legacyView:true});h.setInputHandler(request=>Promise.resolve(uncertain(h,request)));
 try{
  await connect(h);await h.controller.input('uncertain');
  const current=h.controller.snapshot;h.controller.install(current);
  assert.equal(h.errors.filter(message=>message===BODY).length,1);
  h.setInputHandler(request=>Promise.resolve(h.makeSnapshot({activity_seq:request.activity_seq,output_epoch:request.activity_seq,
   phase:'idle',request_id:request.request_id,active_grants:[]})));
  await h.controller.input('continue');assert.equal(h.errors.at(-1),'');
 }finally{await h.controller.close();}
});

test('explicit rejection and technical/format errors keep the existing error path',async()=>{
 for(const code of ['review_not_allowed','invalid_response','generation_failed']){
  const h=harness();h.setInputHandler(request=>Promise.resolve(h.makeSnapshot({activity_seq:request.activity_seq,
   output_epoch:request.activity_seq,phase:'error',request_id:null,active_grants:[],last_error:code})));
  try{
   await connect(h);await h.controller.input('error');
   assert.equal(h.notices.some(notice=>notice!==null),false,`${code} must not become a normal fallback notice`);
   assert.equal(h.errors.at(-1),safeSessionError(code));
   assert.equal(h.calls.includes('effects-stop'),true);
  }finally{await h.controller.close();}
 }
});
