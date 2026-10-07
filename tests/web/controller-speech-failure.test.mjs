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
 const api={create:async id=>{client=id;return {session:state(),session_token:'test'}},capabilities:async()=>({speech_enabled:true,microphone_enabled:false}),snapshot:()=>new Promise(()=>{}),input:async request=>(current=state({activity_seq:request.activity_seq,input_epoch:request.activity_seq,output_epoch:request.activity_seq,phase:'ready',request_id:request.request_id,active_grants:[caption,speech,pose].map(e=>({...e,activity_seq:request.activity_seq,output_epoch:request.activity_seq,id:request.activity_seq===1?e.id:e.id+'-new',cue_speech_id:e.cue_speech_id&&request.activity_seq!==1?'speech-new':e.cue_speech_id}))})),receipt:async value=>{receipts.push(value);return current},audioProgress:async value=>{progress.push(value);return current},speech:async(effect,signal,push)=>{const done=deferred();streams.push({effect,signal,push,done});await done.promise},stop:async request=>state({activity_seq:request.activity_seq}),close:async()=>{}};
 const effects={apply:e=>shown.push(e.id),prepare:(effect,signal)=>{const done=deferred();preparations.push({effect,signal,done});return done.promise},prepareInput(){},stop(){},setPhase(){}};
 const context={destination:{},resume:async()=>{},close:async()=>{},createBuffer:(_c,n)=>({getChannelData:()=>new Float32Array(n)}),createBufferSource:()=>{const source={onended:null,stopped:0,disconnected:0,connect(){},disconnect(){this.disconnected++},start(){},stop(){this.stopped++}};sources.push(source);return source}};
 const controller=new SessionController(api,effects,{connected(){},update(){},error:e=>errors.push(e),localStop(){}},{apiBase:'/api/v1',pollIntervalMs:999999},{createPlayback:o=>new CancelSafePlayback({...o,createContext:()=>context}),createCapture:()=>({stop(){},close:async()=>{}})});
 return {controller,api,shown,receipts,progress,errors,streams,sources,preparations,get current(){return current},async start(){await controller.connect();await controller.input('hello');await settle()},async close(){await controller.close()}};
}
for(const pcm of [false,true])test(`speech failure preserves prepared independent caption with partial PCM=${pcm}`,async()=>{
 const h=harness();try{await h.start();const run=h.preparations[0];assert.equal(run.effect.id,'text');
 if(pcm){await h.streams[0].push(new Int16Array(2));await settle();h.sources[0].onended();await settle();await h.streams[0].push(new Int16Array(2));await settle()}
 h.streams[0].done.reject(new Error('TTS unavailable · diagnostic-id'));await settle();
 assert.equal(run.signal.aborted,false);assert.equal(h.streams[0].signal.aborted,true);assert.equal(h.streams.length,1);
 if(pcm)assert.equal(h.sources[1].stopped,1);
 run.done.resolve();await settle();assert.deepEqual(h.shown,['text']);assert.deepEqual(h.receipts.map(r=>r.effect_id),['text']);
 assert.equal(h.progress.at(-1).status,'failed');assert.equal(h.progress.at(-1).rendered_samples,pcm?2:0);
 assert.ok(h.errors.some(e=>e.includes('diagnostic-id')));
 h.controller.install({...h.current,revision:h.current.revision+1});await settle();assert.equal(h.streams.length,1);assert.deepEqual(h.shown,['text']);
 }finally{await h.close()}
});
for(const action of ['stop','new-input','close'])test(`speech failure cannot revive pending text after ${action}`,async()=>{
 const h=harness();try{await h.start();const old=h.preparations[0],stream=h.streams[0];
 if(action==='stop')await h.controller.stop();else if(action==='new-input')await h.controller.input('next');else await h.controller.close();
 stream.done.reject(new Error('late TTS failure'));old.done.resolve();await settle();assert.equal(old.signal.aborted,true);assert.ok(!h.shown.includes('text'));assert.ok(!h.receipts.some(r=>r.effect_id==='text'));
 }finally{await h.close()}
});
test('speech-linked legacy caption remains blocked after TTS failure',async()=>{
 const h=harness({independent:false});try{await h.start();h.streams[0].done.reject(new Error('TTS failed'));await settle();assert.deepEqual(h.shown,[]);assert.deepEqual(h.receipts,[]);assert.equal(h.controller.gate.allows(h.current.active_grants[0]),false)}finally{await h.close()}
});
test('server speech failure snapshot retains prepared text and public diagnostic through late stream rejection',async()=>{
 const h=harness();try{await h.start();const pending=h.preparations[0],stream=h.streams[0];
 const text=h.current.active_grants[0];
 h.controller.install({...h.current,revision:h.current.revision+1,permit_revision:h.current.permit_revision+1,active_grants:[text],last_error:'unavailable',last_error_diagnostic_id:'h_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'});
 stream.done.reject(new Error('late transport error'));await settle();assert.equal(pending.signal.aborted,false);
 pending.done.resolve();await settle();assert.deepEqual(h.shown,['text']);assert.deepEqual(h.receipts.map(r=>r.effect_id),['text']);
 assert.ok(h.errors.at(-1).includes('h_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'));assert.equal(h.streams.length,1);
 }finally{await h.close()}
});
test('actual sink invalid-PCM failure preserves pending independent caption',async()=>{
 const h=harness();try{await h.start();const pending=h.preparations[0];await assert.rejects(h.streams[0].push(new Int16Array()));await settle();
 assert.equal(pending.signal.aborted,false);pending.done.resolve();await settle();assert.deepEqual(h.shown,['text']);
 assert.equal(h.progress.at(-1).status,'failed');assert.equal(h.progress.at(-1).rendered_samples,0);assert.equal(h.streams.length,1);
 }finally{await h.close()}
});
test('local speech failure cannot authorize newly arriving text or controls on the same branch',async()=>{
 const h=harness();try{await h.start();h.streams[0].done.reject(new Error('TTS failure'));await settle();
 const later={...h.current.active_grants[0],id:'later-text',cue_id:'later-cue'};
 h.controller.install({...h.current,revision:h.current.revision+1,permit_revision:h.current.permit_revision+1,active_grants:[...h.current.active_grants,later]});
 h.preparations[0].done.resolve();await settle();assert.deepEqual(h.shown,['text']);assert.equal(h.controller.gate.allows(later),false);assert.equal(h.streams.length,1);
 }finally{await h.close()}
});
