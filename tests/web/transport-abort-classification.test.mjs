import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
const dist=process.env.MIRA_TEST_WEB_DIST?resolve(process.env.MIRA_TEST_WEB_DIST):resolve('apps/web/dist');
const {MiraApiClient}=await import(resolve(dist,'features/session/api-client.js'));
const {SessionController}=await import(resolve(dist,'features/session/controller.js'));
const {BrowserAudioTransport}=await import(resolve(dist,'features/session/audio-transport.js'));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};};
const base={schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:'c',revision:0,activity_seq:0,input_epoch:0,output_epoch:0,permit_revision:0,phase:'idle',request_id:null,sealed:false,active_grants:[],presented_effects:[],audio_progress:[],last_error:null};
const created=()=>Response.json({session:base,session_token:'synthetic'});
const cancelled=signal=>new Promise((_resolve,reject)=>{if(signal.aborted)reject(signal.reason);else signal.addEventListener('abort',()=>reject(signal.reason),{once:true});});
const classify=(code,pattern)=>error=>{assert.equal(error.code,code);assert.match(error.message,pattern);assert.doesNotMatch(error.message,/signal is aborted|This operation was aborted/);return true;};
for(const stage of ['fetch','body'])test(`native default deadline at ${stage} has a safe classified timeout`,async t=>{
 t.mock.timers.enable({apis:['setTimeout']});let signal;
 const api=new MiraApiClient({apiBase:'/api/v1',pollIntervalMs:200},{fetch:async(_url,options)=>{
  if(options.method==='DELETE')return new Response(null,{status:204});signal=options.signal;
  if(stage==='fetch')return cancelled(signal);
  return {ok:true,async json(){return cancelled(signal);}};
 }});
 const pending=api.create('c');const rejected=assert.rejects(pending,classify('request_timeout',/超时/));t.mock.timers.tick(5000);await rejected;assert.equal(signal.aborted,true);await api.close();
});
test('unexpected native AbortError remains an actionable classified failure',async()=>{
 const api=new MiraApiClient({apiBase:'/api/v1',pollIntervalMs:200},{fetch:async()=>{throw new DOMException('signal is aborted without reason','AbortError');}});
 await assert.rejects(api.create('c'),classify('request_aborted',/意外中断/));await api.close();
});
test('caller default cancellation stays distinct from timeout and unexpected abort',async()=>{
 const abort=new AbortController();const api=new MiraApiClient({apiBase:'/api/v1',pollIntervalMs:200},{fetch:async(_url,o)=>cancelled(o.signal)});
 const pending=api.create('c',abort.signal);const rejected=assert.rejects(pending,classify('request_cancelled',/取消|cancelled/));abort.abort();await rejected;await api.close();
});
test('ordinary transport errors and malformed JSON do not become cancellation success',async()=>{
 const failure=new TypeError('synthetic network failure');const api=new MiraApiClient({apiBase:'/api/v1',pollIntervalMs:200},{fetch:async()=>{throw failure;}});
 await assert.rejects(api.create('c'),error=>error===failure);await api.close();
 const bad=new MiraApiClient({apiBase:'/api/v1',pollIntervalMs:200},{fetch:async()=>new Response('{bad')});await assert.rejects(bad.create('c'),/Invalid session response/);await bad.close();
});
test('late input response after its local deadline is rejected without accepting the snapshot',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const late=deferred();
 const api=new MiraApiClient({apiBase:'/api/v1',pollIntervalMs:200},{fetch:async(url,o)=>url.endsWith('/inputs')?late.promise:o.method==='DELETE'?new Response(null,{status:204}):created()});await api.create('c');
 const pending=api.input({request_id:'r',activity_seq:1,presentation_cutoff:0,text:'synthetic'});const rejected=assert.rejects(pending,classify('request_timeout',/超时/));t.mock.timers.tick(5000);late.resolve(Response.json({...base,activity_seq:1,request_id:'r'}));await rejected;await api.close();
});
test('late create after deadline is cleaned up and never installs credentials',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const late=deferred(),calls=[];
 const api=new MiraApiClient({apiBase:'/api/v1',pollIntervalMs:200},{fetch:async(url,o)=>{calls.push(o.method);return o.method==='POST'?late.promise:new Response(null,{status:204});}});
 const pending=api.create('c');const rejected=assert.rejects(pending,classify('request_timeout',/超时/));t.mock.timers.tick(5000);late.resolve(created());await rejected;await tick();assert.deepEqual(calls,['POST','DELETE']);assert.throws(()=>api.snapshot(),/not connected/);await api.close();
});
function controllerHarness(){
 let client,revision=0,activity=0,inputs=0;const errors=[],requests=[],views=[];
 const snapshot=(patch={})=>({...base,client_instance_id:client,revision:++revision,permit_revision:revision,activity_seq:activity,input_epoch:inputs,output_epoch:activity,sealed:true,...patch});
 const api={create:async c=>{client=c;return {session:snapshot(),session_token:'synthetic'};},capabilities:async()=>({generation_mode:'mock',speech_enabled:false,microphone_enabled:false}),snapshot:signal=>cancelled(signal),input:async(r,signal)=>{inputs++;activity=r.activity_seq;requests.push({r,signal});return cancelled(signal);},stop:async r=>{activity=r.activity_seq;return snapshot({phase:'stopped'});},close:async()=>{}};
 const effects={apply(){},prepareInput(){},stop(){},setPhase(){}};
 const controller=new SessionController(api,effects,{connected(){},update:view=>views.push(view),error:e=>errors.push(e),localStop(){}},{apiBase:'/api/v1',pollIntervalMs:200},{createPlayback:()=>({unlock:async()=>true,stop(){},reconcileAuthorization(){},close(){}}),createCapture:()=>({start:async()=>true,stop(){},close(){}})});
 return {controller,api,errors,requests,views,snapshot};
}
for(const action of ['stop','new-input','close'])test(`actual controller owned ${action} cancellation never surfaces native AbortError`,async()=>{
 const h=controllerHarness();await h.controller.connect();const first=h.controller.input('first');await tick();
 if(action==='stop')await h.controller.stop();else if(action==='close')await h.controller.close();else {const second=h.controller.input('newer');await tick();await h.controller.stop();await second;}
 const result=await first;assert.ok(['superseded','closed'].includes(result.status));assert.equal(h.errors.filter(Boolean).length,0);await h.controller.close();
});
test('actual controller rejects stale native abort from a superseded poll while newer input survives',async()=>{
 const h=controllerHarness(),poll=deferred();h.api.snapshot=()=>poll.promise;h.api.input=async r=>h.snapshot({activity_seq:r.activity_seq,request_id:r.request_id,phase:'thinking'});await h.controller.connect();await h.controller.input('newer');poll.reject(new DOMException('signal is aborted without reason','AbortError'));await tick();assert.equal(h.errors.filter(Boolean).length,0);await h.controller.close();
});
test('actual controller keeps current unexpected abort visible rather than swallowing by name',async()=>{
 const h=controllerHarness();h.api.input=async()=>{throw new DOMException('signal is aborted without reason','AbortError');};await h.controller.connect();assert.equal((await h.controller.input('current')).status,'unknown');assert.equal(h.errors.filter(Boolean).length,1);assert.match(h.errors.at(-1),/意外中断/);assert.doesNotMatch(h.errors.at(-1),/signal is aborted/);await h.controller.close();
});

test('first abort cause stays caller cancellation even when the deadline also fires later',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const late=deferred(),abort=new AbortController();
 const api=new MiraApiClient({apiBase:'/api/v1',pollIntervalMs:200},{fetch:async(_url,o)=>o.method==='DELETE'?new Response(null,{status:204}):late.promise});
 const pending=api.create('c',abort.signal);const rejected=assert.rejects(pending,classify('request_cancelled',/cancelled/));abort.abort();t.mock.timers.tick(5000);late.resolve(created());await rejected;await api.close();
});
test('speech fetch deadline is a timeout, while an unexpected native abort is not suppressed',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const effect={id:'speech',kind:'speech',value:'synthetic',digest:'a'.repeat(64),activity_seq:1,output_epoch:1};
 const transport=new BrowserAudioTransport({apiBase:'/api/v1'},()=>({sessionId:'s',token:'synthetic'}),{fetch:async(_u,o)=>cancelled(o.signal)});
 const pending=transport.speech(effect,new AbortController().signal,()=>{});const rejected=assert.rejects(pending,classify('request_timeout',/330 秒/));t.mock.timers.tick(330000);await rejected;transport.close();
 const unexpected=new BrowserAudioTransport({apiBase:'/api/v1'},()=>({sessionId:'s',token:'synthetic'}),{fetch:async()=>{throw new DOMException('signal is aborted without reason','AbortError');}});
 await assert.rejects(unexpected.speech(effect,new AbortController().signal,()=>{}),classify('request_aborted',/意外中断/));unexpected.close();
});
for(const phase of ['setup','final'])test(`actual microphone ${phase} owned Stop cancellation stays quiet`,async()=>{
 const h=controllerHarness();h.api.capabilities=async()=>({generation_mode:'injected',speech_enabled:false,microphone_enabled:true});let stops=0;
 h.api.stop=async(r,signal)=>{stops++;return phase==='setup'&&stops===1?cancelled(signal):h.snapshot({activity_seq:r.activity_seq,phase:'stopped'});};
 h.api.microphone=(_origin,signal)=>({ready:Promise.resolve(),completion:cancelled(signal),send(){},finish:()=>cancelled(signal),cancel(){}});
 await h.controller.connect();await tick();await h.controller.startMicrophone();await tick();const finishing=phase==='final'?h.controller.finishMicrophone():null;await tick();await h.controller.stop();if(finishing)await finishing;await tick();assert.equal(h.errors.filter(Boolean).length,0);await h.controller.close();
});
