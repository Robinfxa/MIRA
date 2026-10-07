import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {SessionController}=await import(new URL('features/session/controller.js',dist));
const {CancelSafePlayback}=await import(new URL('features/audio/playback.js',dist));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const settle=async()=>{for(let i=0;i<5;i++)await tick()};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
function harness({independent=true}={}){
 let client,current,revision=0;
 const shown=[],receipts=[],progress=[],errors=[],streams=[],sources=[],preparations=[];
 const effect=(id,kind,cue,speech)=>({id,kind,value:id,digest:'a'.repeat(64),output_epoch:1,activity_seq:1,cue_id:cue,cue_speech_id:speech});
 const caption=effect('text','subtitle',independent?'ordinary':'voice',independent?null:'speech');
 const speech=effect('speech','speech','voice','speech');
 const pose=effect('pose','pose','voice','speech');
 const state=(patch={})=>({schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:client,revision:++revision,permit_revision:revision,activity_seq:0,input_epoch:0,output_epoch:0,phase:'stopped',request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null,...patch});
 const api={create:async id=>{client=id;return {session:state(),session_token:'test'}},capabilities:async()=>({speech_enabled:true,microphone_enabled:false}),snapshot:()=>new Promise(()=>{}),input:async request=>(current=state({activity_seq:request.activity_seq,input_epoch:request.activity_seq,output_epoch:request.activity_seq,phase:'ready',request_id:request.request_id,active_grants:[caption,speech,pose].map(e=>({...e,activity_seq:request.activity_seq,output_epoch:request.activity_seq,id:request.activity_seq===1?e.id:e.id+'-new-'+request.activity_seq,cue_speech_id:e.cue_speech_id&&request.activity_seq!==1?'speech-new-'+request.activity_seq:e.cue_speech_id}))})),receipt:async value=>{receipts.push(value);return current},audioProgress:async value=>{progress.push(value);return current},speech:async(effect,signal,push)=>{const done=deferred();streams.push({effect,signal,push,done});await done.promise},stop:async request=>state({activity_seq:request.activity_seq}),close:async()=>{}};
 const effects={apply:e=>shown.push(e.id),prepare:(effect,signal)=>{const done=deferred();preparations.push({effect,signal,done});return done.promise},prepareInput(){},stop(){},setPhase(){}};
 const context={destination:{},resume:async()=>{},close:async()=>{},createBuffer:(_c,n)=>({getChannelData:()=>new Float32Array(n)}),createBufferSource:()=>{const source={onended:null,stopped:0,disconnected:0,connect(){},disconnect(){this.disconnected++},start(){},stop(){this.stopped++}};sources.push(source);return source}};
 const controller=new SessionController(api,effects,{connected(){},update(){},error:e=>errors.push(e),localStop(){}},{apiBase:'/api/v1',pollIntervalMs:999999},{createPlayback:o=>new CancelSafePlayback({...o,createContext:()=>context}),externalMicrophoneActive:()=>true,createCapture:()=>({stop(){},close:async()=>{}})});
 return {controller,api,shown,receipts,progress,errors,streams,sources,preparations,get current(){return current},async start(){await controller.connect();await controller.input('hello');await settle()},async close(){await controller.close()}};
}

test('mute stops local PCM before response, keeps caption/mic, and never resumes old audio',async()=>{
 const h=harness();try{await h.start();const old=h.streams[0];await old.push(new Int16Array(2));await settle();
 const preference=deferred();const requests=[];h.api.responsePreference=async request=>{requests.push(request);return preference.promise};
 const change=h.controller.setOutputMuted(true);
 assert.equal(h.sources[0].stopped,1);assert.equal(old.signal.aborted,true);assert.equal(h.controller.outputMuted,true);
 assert.equal(h.controller.externalMicrophoneActive(),true);
 await settle();assert.equal(h.progress.length,0,'terminal fact waits for server mute revocation');
 const snapshot={...h.current,revision:h.current.revision+1,permit_revision:h.current.permit_revision+1,
 response_muted:true,response_mode:'text_only',response_preference_revision:1,
 active_grants:h.current.active_grants.filter(e=>e.kind!=='speech'&&e.cue_speech_id===null)};
 preference.resolve(snapshot);await change;await settle();
 assert.equal(h.progress.at(-1).status,'interrupted');
 h.preparations[0].done.resolve();await settle();assert.deepEqual(h.shown,['text']);
 await assert.rejects(old.push(new Int16Array(2)));
 h.controller.install({...h.current,revision:snapshot.revision+1});await settle();
 assert.equal(h.streams.length,1);assert.equal(h.controller.outputMuted,true);
 h.api.responsePreference=async()=>({...snapshot,revision:snapshot.revision+2,response_muted:false,response_preference_revision:2});
 await h.controller.setOutputMuted(false);await settle();assert.equal(h.streams.length,1);
 assert.equal(h.controller.outputMuted,false);
 }finally{await h.close()}
});
test('failed mute request keeps local output blocked and repeated clicks do not race unmute',async()=>{
 const h=harness();try{await h.start();const waiting=deferred();let calls=0;
 h.api.responsePreference=async()=>{calls++;return waiting.promise};
 const first=h.controller.setOutputMuted(true);await h.controller.setOutputMuted(false);
 assert.equal(calls,1);assert.equal(h.controller.outputMuted,true);
 waiting.reject(new Error('offline'));await first;await settle();
 h.controller.install({...h.current,revision:h.current.revision+1});await settle();
 assert.equal(h.controller.outputMuted,true);assert.equal(h.streams.length,1);
 }finally{await h.close()}
});

function mutedState(h, revision, preferenceRevision) { return {...h.current,
 revision,permit_revision:revision,response_muted:true,response_mode:'text_only',
 response_preference_revision:preferenceRevision,
 active_grants:h.current.active_grants.filter(e=>e.kind==='subtitle')}; }

test('newer server mute must survive delayed successful unmute response',async()=>{
 const h=harness();try{
 await h.start();
 const muted=mutedState(h,20,1);
 h.api.responsePreference=async()=>muted;
 await h.controller.setOutputMuted(true);
 const pending=deferred();h.api.responsePreference=async()=>pending.promise;
 const unmute=h.controller.setOutputMuted(false);
 // Another reliable user command is accepted while the earlier request is in flight.
 const newest={...muted,revision:22,permit_revision:22,response_preference_revision:3};
 h.controller.install(newest);
 pending.resolve({...muted,revision:21,permit_revision:21,response_muted:false,response_preference_revision:2});
 await unmute;await settle();
 assert.equal(h.controller.outputMuted,true,'stale successful response must not clear newer mute');
 assert.equal(h.streams.length,1,'old speech never restarts');
 }finally{await h.close()}
});

test('snapshot hydration latches mute and ordinary stale snapshots cannot clear it',async()=>{
 const h=harness();try{
 await h.start();const old=h.streams[0];await old.push(new Int16Array(2));
 h.controller.install(mutedState(h,20,3));await settle();
 assert.equal(h.controller.outputMuted,true);assert.equal(h.sources[0].stopped,1);
 await assert.rejects(old.push(new Int16Array(2)));
 h.controller.install({...h.current,revision:21,permit_revision:21,response_preference_revision:2,response_muted:false});
 await settle();assert.equal(h.controller.outputMuted,true);assert.equal(h.streams.length,1);
 }finally{await h.close()}
});

test('failed unmute preserves mute and never dispatches a replacement stream',async()=>{
 const h=harness();try{
 await h.start();h.api.responsePreference=async()=>mutedState(h,20,1);
 await h.controller.setOutputMuted(true);
 h.api.responsePreference=async()=>{throw Error('offline')};
 await h.controller.setOutputMuted(false);await settle();
 assert.equal(h.controller.outputMuted,true);assert.equal(h.streams.length,1);
 }finally{await h.close()}
});



test('lower preference revisions cannot reset the mute watermark',async()=>{
 const h=harness();try{
 await h.start();
 h.controller.install(mutedState(h,20,3));await settle();
 h.controller.install(mutedState(h,21,1));await settle();
 assert.equal(h.controller.preferenceRevision,3);
 h.controller.install({...mutedState(h,22,2),response_muted:false});await settle();
 assert.equal(h.controller.outputMuted,true);assert.equal(h.controller.preferenceRevision,3);
 assert.equal(h.streams.length,1);
 }finally{await h.close()}
});

test('failed mute remains locally latched when an older in-flight input brings newer voice preference',async()=>{
 const h=harness();let pendingInput;try{
 await h.start();
 const response=deferred();const dispatched=deferred();
 const originalInput=h.api.input;let earlierInputSnapshot;
 h.api.input=async request=>{earlierInputSnapshot=await originalInput(request);dispatched.resolve();return response.promise};
 pendingInput=h.controller.input('取消静音。');
 await dispatched.promise;
 // The input was accepted first on the server, but its response is still in flight.
 h.api.responsePreference=async()=>{throw Error('409 stale preference revision')};
 await h.controller.setOutputMuted(true);await settle();
 assert.equal(h.controller.outputMuted,true);
 response.resolve({...earlierInputSnapshot,revision:30,permit_revision:30,response_muted:false,
   response_mode:'voice',response_preference_revision:1});
 await pendingInput;await settle();
 assert.deepEqual({muted:h.controller.outputMuted,streams:h.streams.length},{muted:true,streams:1},
   'later failed mute must stay latched and block newly arriving speech from the earlier input');
 }finally{await h.close()}
});

test('wire response mode rejects coercible arrays rather than widening strict text mode',async()=>{
 const {parseSession}=await import(new URL('shared/protocol.js',dist));
 const h=harness();try{
 await h.start();
 for(const mode of [['text_only'],['voice']]) {
   assert.throws(()=>parseSession({...h.current,response_mode:mode,response_muted:false,response_preference_revision:0}),
     /Incompatible session contract/);
 }
 }finally{await h.close()}
});

test('preexisting mute snapshot cannot confirm a later local mute that fails',async()=>{
 const h=harness();try{
 await h.start();h.controller.install(mutedState(h,20,1));
 const pending=deferred();h.api.responsePreference=async()=>pending.promise;
 const localMute=h.controller.setOutputMuted(true);
 h.controller.install(mutedState(h,21,1));
 pending.reject(Error('409 stale preference'));await localMute;
 h.controller.install({...mutedState(h,22,2),response_muted:false,response_mode:'voice'});
 await settle();assert.equal(h.controller.outputMuted,true);assert.equal(h.streams.length,1);
 h.api.responsePreference=async()=>({...mutedState(h,23,3),response_muted:false,response_mode:'text_only'});
 await h.controller.setOutputMuted(false);assert.equal(h.controller.outputMuted,false);
 }finally{await h.close()}
});

test('failed mute survives voice snapshot during pending write and later poll',async()=>{
 const h=harness();try{
 await h.start();
 const inputResponse=deferred(),dispatched=deferred(),write=deferred();
 const originalInput=h.api.input;let earlier;
 h.api.input=async request=>{earlier=await originalInput(request);dispatched.resolve();return inputResponse.promise};
 const input=h.controller.input('取消静音。');await dispatched.promise;
 h.api.responsePreference=async()=>write.promise;
 const mute=h.controller.setOutputMuted(true);
 const voice={...earlier,revision:30,permit_revision:30,response_muted:false,response_mode:'voice',response_preference_revision:1};
 inputResponse.resolve(voice);await input;await settle();
 assert.equal(h.controller.outputMuted,true,'pending local mute wins during delivery');
 write.reject(Error('offline'));await mute;await settle();
 h.controller.install({...voice,revision:31});await settle();
 assert.deepEqual({muted:h.controller.outputMuted,streams:h.streams.length},{muted:true,streams:1});
 }finally{await h.close()}
});

test('explicit unmute after failed mute cannot replay a voice grant received while muted',async()=>{
 const h=harness();try{
 await h.start();const originalInput=h.api.input;
 h.api.responsePreference=async()=>{throw Error('offline')};
 await h.controller.setOutputMuted(true);
 let mutedTurn;
 h.api.input=async request=>{const next=await originalInput(request);mutedTurn={...next,
   revision:30,permit_revision:30,response_muted:false,response_mode:'voice',response_preference_revision:0};return mutedTurn};
 await h.controller.input('继续聊。');await settle();
 assert.equal(h.controller.outputMuted,true);assert.equal(h.streams.length,1);
 const restored={...mutedTurn,revision:31,response_preference_revision:1};
 h.api.responsePreference=async()=>restored;
 await h.controller.setOutputMuted(false);await settle();
 assert.equal(h.controller.outputMuted,false,'later explicit user unmute can clear the failed-write latch');
 h.controller.install({...restored,revision:32});await settle();
 assert.equal(h.streams.length,1,'unmute applies to a future reply, not a previously muted grant');
 h.api.input=async request=>{const next=await originalInput(request);return {...next,revision:33,permit_revision:33,
   response_muted:false,response_mode:'voice',response_preference_revision:1}};
 await h.controller.input('这是新的一轮。');await settle();
 assert.equal(h.streams.length,2,'a fresh reply after explicit unmute remains allowed');
 }finally{await h.close()}
});

test('later accepted explicit user unmute can release a failed local mute for its new reply',async()=>{
 const h=harness();try{
 await h.start();h.api.responsePreference=async()=>{throw Error('offline')};
 await h.controller.setOutputMuted(true);
 assert.equal(h.controller.outputMuted,true);
 const originalInput=h.api.input;
 h.api.input=async request=>{const next=await originalInput(request);return {...next,
   revision:30,permit_revision:30,response_muted:false,response_mode:'voice',response_preference_revision:1}};
 await h.controller.input('可以开声音。');await settle();
 assert.deepEqual({muted:h.controller.outputMuted,streams:h.streams.length},{muted:false,streams:2},
   'a genuinely later explicit user unmute applies to the newly accepted reply');
 }finally{await h.close()}
});

for(const text of ['他说“可以开声音”。','不要取消静音。','"unmute"','可以开声音吗？']) {
 test(`ambiguous later input cannot release failed mute: ${text}`,async()=>{
  const h=harness();try{
  await h.start();h.api.responsePreference=async()=>{throw Error('offline')};
  await h.controller.setOutputMuted(true);
  const originalInput=h.api.input;
  h.api.input=async request=>{const next=await originalInput(request);return {...next,
    revision:30,permit_revision:30,response_muted:false,response_mode:'voice',response_preference_revision:1}};
  await h.controller.input(text);await settle();
  assert.deepEqual({muted:h.controller.outputMuted,streams:h.streams.length},{muted:true,streams:1});
  }finally{await h.close()}
 });
}

test('poll acceptance of the exact later unmute input releases its new reply once',async()=>{
 const h=harness();try{
 await h.start();h.api.responsePreference=async()=>{throw Error('offline')};
 await h.controller.setOutputMuted(true);
 const response=deferred(),dispatched=deferred(),original=h.api.input;let accepted;
 h.api.input=async request=>{accepted={...await original(request),revision:30,permit_revision:30,
   response_muted:false,response_mode:'voice',response_preference_revision:1};dispatched.resolve();return response.promise};
 const sending=h.controller.input('可以开声音。');await dispatched.promise;
 h.controller.install(accepted);await settle();
 assert.equal(h.controller.outputMuted,false);assert.equal(h.streams.length,2);
 response.resolve(accepted);await sending;await settle();assert.equal(h.streams.length,2);
 }finally{await h.close()}
});

test('UI unmute also fences an earlier in-flight muted reply but permits a future input',async()=>{
 const h=harness();try{
 await h.start();h.api.responsePreference=async()=>{throw Error('offline')};
 await h.controller.setOutputMuted(true);
 const response=deferred(),dispatched=deferred(),original=h.api.input;let accepted;
 h.api.input=async request=>{accepted={...await original(request),revision:30,permit_revision:30,
   response_muted:false,response_mode:'voice',response_preference_revision:0};dispatched.resolve();return response.promise};
 const sending=h.controller.input('继续说天气。');await dispatched.promise;
 h.api.responsePreference=async()=>({...accepted,revision:31,response_preference_revision:1});
 await h.controller.setOutputMuted(false);await settle();assert.equal(h.streams.length,1);
 response.resolve(accepted);await sending;await settle();assert.equal(h.streams.length,1);
 h.api.input=async request=>({...await original(request),revision:32,permit_revision:32,
   response_muted:false,response_mode:'voice',response_preference_revision:1});
 await h.controller.input('下一轮。');await settle();assert.equal(h.streams.length,2);
 }finally{await h.close()}
});
