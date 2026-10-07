import test from 'node:test';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const dist=pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST ?? 'apps/web/dist')+'/');
const {SessionController}=await import(new URL('features/session/controller.js',dist));
const tick=()=>new Promise(r=>setImmediate(r));
const flush=async()=>{for(let i=0;i<12;i++)await tick();};
function harness(){
 let client,revision=0,state={activity_seq:0,output_epoch:0,input_epoch:0,request_id:null,active_grants:[],phase:'stopped',sealed:false},pendingPoll;
 const errors=[],requests=[];
 const snapshot=()=>({schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:client,revision:++revision,permit_revision:revision,presented_effects:[],audio_progress:[],last_error:null,...state});
 const api={create:async id=>{client=id;return{session:snapshot(),session_token:'synthetic'};},capabilities:async()=>({speech_enabled:true,microphone_enabled:false,speech_sample_rate_hz:24000,microphone_sample_rate_hz:16000,qualification:'injected_unverified',generation_mode:'mock'}),
  snapshot:()=>new Promise(r=>pendingPoll=r),input:async request=>{requests.push(request);state={...state,activity_seq:request.activity_seq,output_epoch:request.activity_seq,input_epoch:request.activity_seq,request_id:request.request_id,sealed:true,phase:'ready',active_grants:[{id:`speech-${request.activity_seq}`,kind:'speech',value:'answer',digest:'a'.repeat(64),activity_seq:request.activity_seq,output_epoch:request.activity_seq}]};return snapshot();},
  stop:async request=>{state={...state,activity_seq:request.activity_seq,output_epoch:request.activity_seq,request_id:null,active_grants:[],phase:'stopped'};return snapshot();},
  receipt:async()=>snapshot(),audioProgress:async()=>snapshot(),speech:async()=>new Promise(()=>{}),close:async()=>{}};
 const controller=new SessionController(api,{apply(){},prepareInput(){},stop(){},setPhase(){}},{connected(){},update(){},error:e=>{if(e)errors.push(e);},localStop(){}},{apiBase:'/api/v1',pollIntervalMs:200},
  {createPlayback:()=>({quiescent:true,unlock:async()=>true,open:()=>({push:()=>true,finish:()=>true}),stop(){},reconcileAuthorization(){},close(){}}),createCapture:()=>({start:async()=>false,stop(){},close:async()=>{}})});
 return{controller,errors,requests,
  installFault:async code=>{state={...state,request_id:null,active_grants:[],phase:'error',last_error:code};
   // This is the production controller's response installer, also reached by its polling callback.
   controller.install(snapshot());await flush();},get pendingPoll(){return pendingPoll;}};
}
test('explicit local interruption treats its own terminal audio_interrupted as expected and retains continuation',async()=>{
 const h=harness();try{await h.controller.connect();await h.controller.input('original');await flush();const parent=h.requests[0];
  h.controller.interruptReply();await h.installFault('audio_interrupted');assert.deepEqual(h.errors,[]);
  await h.controller.input('supplement',undefined,'44444444-2234-4234-8234-123456789012');assert.equal(h.requests[1].relation,'continuation');assert.equal(h.requests[1].continuation_of_request_id,parent.request_id);
 }finally{await h.controller.close();}
});
for(const scenario of ['unexpected-interruption','failed-after-interruption','new-input-clears-expectation'])test(`${scenario} still exposes real audio failure`,async()=>{
 const h=harness();try{await h.controller.connect();await h.controller.input('original');await flush();
  if(scenario!=='unexpected-interruption')h.controller.interruptReply();
  if(scenario==='new-input-clears-expectation'){await h.controller.input('new independent');await flush();}
  await h.installFault(scenario==='failed-after-interruption'?'audio_failed':'audio_interrupted');assert.ok(h.errors.length>0);
 }finally{await h.controller.close();}
});
