import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {SessionController}=await import(new URL('features/session/controller.js',dist));
function harness({stopThrows=false,closeThrows=false,legacy=false}={}) {
 const calls=[],errors=[];
 const effects={apply(){},prepareInput(){},stop(){calls.push('visual-stop');if(stopThrows)throw Error('synthetic renderer stop');}};
 if(!legacy)effects.close=()=>{calls.push('visual-close');if(closeThrows)throw Error('synthetic renderer close');};
 let client='',revision=0,activity=0;
 const state=()=>({schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:client,
  revision:++revision,activity_seq:activity,input_epoch:activity,output_epoch:activity,permit_revision:revision,
  phase:'stopped',request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null});
 const api={create:async id=>{client=id;return {session:state(),session_token:'synthetic'};},
  capabilities:async()=>({speech_enabled:false,microphone_enabled:false,speech_sample_rate_hz:24000,
   microphone_sample_rate_hz:16000,qualification:'offline_fixture',generation_mode:'mock'}),
  snapshot:()=>new Promise(()=>{}),stop:async request=>{activity=request.activity_seq;return state();},
  close:async()=>{calls.push('api-close');}};
 const playback={stop:()=>calls.push('audio-stop'),close:async()=>calls.push('audio-close'),stopAudition(){},reconcileAuthorization(){},get quiescent(){return true;}};
 const capture={stop:()=>calls.push('capture-stop'),close:async()=>calls.push('capture-close')};
 const view={connected(){},update(){},error:message=>errors.push(message),localStop(){}};
 const controller=new SessionController(api,effects,view,{apiBase:'/api/v1',pollIntervalMs:10000},{createPlayback:()=>playback,createCapture:()=>capture});
 return {controller,calls,errors};
}
test('Close destroys optional renderer exactly once and releases every other owner',async()=>{
 const h=harness();const first=h.controller.close();assert.equal(h.controller.close(),first);await first;
 for(const name of ['visual-close','audio-close','capture-close','api-close'])assert.equal(h.calls.filter(x=>x===name).length,1);
 assert.deepEqual(h.errors,[]);
});
test('renderer Stop or destruction failure cannot prevent remaining resource cleanup',async()=>{
 for(const settings of [{stopThrows:true},{closeThrows:true}]){
  const h=harness(settings);await h.controller.close();await h.controller.close();
  for(const name of ['visual-close','audio-close','capture-close','api-close'])assert.equal(h.calls.filter(x=>x===name).length,1);
  assert.equal(h.errors.length,1);assert.doesNotMatch(h.errors[0],/synthetic renderer/);
 }
});
test('legacy effects without a close hook keep the previous cleanup contract',async()=>{
 const h=harness({legacy:true});await h.controller.close();assert.equal(h.calls.includes('visual-close'),false);
 for(const name of ['audio-close','capture-close','api-close'])assert.equal(h.calls.filter(x=>x===name).length,1);
 assert.deepEqual(h.errors,[]);
});

test('local Stop does not destroy the renderer; subsequent Close does',async()=>{
 const h=harness();await h.controller.connect();await h.controller.stop();
 assert.equal(h.calls.includes('visual-close'),false);
 assert.equal(h.calls.includes('visual-stop'),true);
 await h.controller.close();assert.equal(h.calls.filter(x=>x==='visual-close').length,1);
});
