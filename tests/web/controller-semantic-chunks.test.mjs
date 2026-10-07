import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {SessionController}=await import(new URL('features/session/controller.js',dist));
const {PresentationGate}=await import(new URL('features/presentation/permit-gate.js',dist));
const {parseSession}=await import(new URL('shared/protocol.js',dist));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const group='12345678-1234-1234-1234-123456789abc';
function chunks(values=['你好👩🏽‍💻。 ','继续é。 ','最后。']){
 const total=values.reduce((n,s)=>n+Array.from(s).length,0);let start=0;
 return values.map((value,index)=>{const end=start+Array.from(value).length;
  const result={id:'chunk-'+index,kind:'subtitle',value,digest:'a'.repeat(64),output_epoch:1,activity_seq:1,
   cue_id:'cue-'+index,cue_speech_id:null,caption_chunk:{group_id:group,index,start,end,total,source_sha256:'b'.repeat(64)}};
  start=end;return result;});
}
function snapshot(grants,patch={}){return {schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:'c',
 revision:1,activity_seq:1,input_epoch:1,output_epoch:1,permit_revision:1,phase:'ready',request_id:'r',sealed:true,
 active_grants:grants,presented_effects:[],audio_progress:[],last_error:null,...patch};}
function harness({prepared=false,fail=false,grants=chunks()}={}){
 let client,current,revision=0;const shown=[],receipts=[],observed=[],errors=[];
 const session=patch=>snapshot([],{client_instance_id:client,revision:++revision,permit_revision:revision,
  activity_seq:0,input_epoch:0,output_epoch:0,phase:'stopped',request_id:null,...patch});
 const api={create:async c=>{client=c;return {session:session({}),session_token:'synthetic'}},
  capabilities:async()=>({speech_enabled:false,microphone_enabled:false}),snapshot:()=>new Promise(()=>{}),
  input:async r=>(current=session({activity_seq:r.activity_seq,input_epoch:r.activity_seq,output_epoch:r.activity_seq,
   phase:'ready',request_id:r.request_id,active_grants:r.activity_seq===1?grants:[]})),
  receipt:async r=>{receipts.push(r);return current},stop:async r=>session({activity_seq:r.activity_seq}),close:async()=>{}};
 const effects={apply:e=>{if(fail)throw Error('synthetic apply failure');shown.push(e)},prepareInput(){},stop(){}};
 if(prepared)effects.prepare=async()=>{};
 const controller=new SessionController(api,effects,{connected(){},update(){},error:e=>errors.push(e),localStop(){},
  visualPresented:e=>observed.push(e)},{apiBase:'/api/v1',pollIntervalMs:1000},{captionDwellMs:35,
  createPlayback:()=>({unlock:async()=>{},stop(){},reconcileAuthorization(){},close:async()=>{},quiescent:true}),
  createCapture:()=>({start:async()=>false,stop(){},close:async()=>{}})});
 return {controller,shown,receipts,observed,errors,get current(){return current},
  async start(){await controller.connect();await controller.input('分块');await tick()},
  async close(){await controller.close()}};
}
for(const prepared of [false,true])test(`caption FIFO receipts only real sequential apply; prepared=${prepared}`,async()=>{
 const h=harness({prepared});try{await h.start();assert.deepEqual(h.shown.map(e=>e.id),['chunk-0']);
 assert.deepEqual(h.receipts.map(e=>e.effect_id),['chunk-0']);assert.deepEqual(h.observed.map(e=>e.id),['chunk-0']);
 h.controller.install({...h.current,revision:h.current.revision+1});await tick();assert.equal(h.shown.length,1);
 await wait(90);assert.deepEqual(h.shown.map(e=>e.id),['chunk-0','chunk-1','chunk-2']);
 assert.equal(h.shown.map(e=>e.value).join(''),chunks().map(e=>e.value).join(''));
 assert.deepEqual(h.receipts.map(e=>e.effect_id),h.shown.map(e=>e.id));assert.deepEqual(h.observed,h.shown);
 }finally{await h.close()}});
for(const action of ['stop','new-input','close','revoke'])test(`caption FIFO cancels future chunks on ${action}`,async()=>{
 const h=harness({prepared:true});try{await h.start();assert.equal(h.shown.length,1);
 if(action==='stop')await h.controller.stop();else if(action==='new-input')await h.controller.input('新话题');
 else if(action==='close')await h.controller.close();else h.controller.install({...h.current,
  revision:h.current.revision+1,permit_revision:h.current.permit_revision+1,active_grants:[]});
 await wait(90);assert.deepEqual(h.shown.map(e=>e.id),['chunk-0']);assert.deepEqual(h.receipts.map(e=>e.effect_id),['chunk-0']);
 }finally{await h.close()}});
test('failed visual apply creates neither chunk receipt nor page-history observation',async()=>{
 const h=harness({prepared:true,fail:true});try{await h.start();await wait(50);
 assert.deepEqual(h.receipts,[]);assert.deepEqual(h.observed,[]);assert.deepEqual(h.shown,[]);
 }finally{await h.close()}});
test('chunked presentation history accepts partial groups and uses codepoint lengths',()=>{
 const parsed=parseSession(snapshot(chunks(),{presented_effects:[chunks()[1]]}));
 assert.equal(parsed.presented_effects[0].caption_chunk.index,1);
 assert.ok(Object.isFrozen(parsed.active_grants[0].caption_chunk));
 assert.notEqual(chunks()[0].value.length,Array.from(chunks()[0].value).length);
});
for(const [name,mutate] of [
 ['missing first',g=>g.slice(1)],['gap',g=>[g[0],g[2]]],
 ['overlap',g=>g.map((e,i)=>i===1?{...e,caption_chunk:{...e.caption_chunk,start:0}}:e)],
 ['different source',g=>g.map((e,i)=>i===1?{...e,caption_chunk:{...e.caption_chunk,source_sha256:'c'.repeat(64)}}:e)],
 ['invented text',g=>g.map((e,i)=>i===1?{...e,value:'extra'+e.value}:e)],
 ['speech association',g=>g.map((e,i)=>i===1?{...e,cue_speech_id:'speech'}:e)],
 ['extra metadata',g=>g.map((e,i)=>i===1?{...e,caption_chunk:{...e.caption_chunk,approval:true}}:e)],
])test(`caption metadata rejects ${name}`,()=>assert.throws(()=>parseSession(snapshot(mutate(chunks())))));
test('caller mutation and later metadata replacement cannot rewrite an issued chunk',()=>{
 const grants=chunks(),gate=new PresentationGate('s','c');gate.beginInput('r');gate.install(snapshot(grants));
 grants[0].caption_chunk.source_sha256='d'.repeat(64);
 assert.equal(gate.allows(grants[0]),false);
 assert.throws(()=>gate.install(snapshot(grants,{revision:2,permit_revision:2})));
});
test('unchunked independent subtitles retain immediate existing behavior',async()=>{
 const grants=chunks().map(e=>{const {caption_chunk,...rest}=e;return rest});const h=harness({grants});
 try{await h.start();assert.equal(h.shown.length,3);assert.equal(h.receipts.length,3)}finally{await h.close()}
});
