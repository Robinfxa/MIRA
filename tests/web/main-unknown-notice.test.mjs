import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const backendFixture=process.env.MIRA_NOTICE_FIXTURE?JSON.parse(readFileSync(process.env.MIRA_NOTICE_FIXTURE,'utf8')):null;
const id='h_'+'a'.repeat(32);
const tick=()=>new Promise(r=>setImmediate(r));
const BODY='这部分我还不确定，先跳过。你可以补充说明，或继续聊。';
const base={schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:'c',revision:1,activity_seq:0,input_epoch:0,output_epoch:0,permit_revision:1,phase:'stopped',request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null};
let sequence=0;
async function app({noticeElements='all', codes=['review_uncertain'],prefix=null}={}){
 const globals={window:globalThis.window,document:globalThis.document,fetch:globalThis.fetch,AudioContext:globalThis.AudioContext},nodes=new Map();
 class Node{listeners={};dataset={};value='';disabled=false;hidden=true;textContent='';children=[];addEventListener(n,f){(this.listeners[n]??=[]).push(f)}setAttribute(n,v){this[n]=v}querySelector(s){return nodes.get(s)}fire(n){for(const f of this.listeners[n]??[])f({preventDefault(){},button:0,pointerId:1})}setPointerCapture(){}replaceChildren(...items){this.children=items}append(...items){this.children.push(...items)}focus(){}}
 for(const s of ['[data-connect-retry]','[data-connection-status]','[data-send-message]','[data-status]','[data-diagnostic]','[data-error]','[data-stage]','fieldset','form.composer','[name=message]','[data-stop]','[data-close]','[data-ptt]','[data-continuous-listening]','[data-continuous-panel]','[data-continuous-status]','[data-continuous-preview]','[data-continuous-interrupt]','[data-continuous-send]','[data-recovered-input-notice]','[data-recovered-input-label]','[data-recovered-new-topic]','[data-continuous-sent-text]','[data-continuous-recording-limit]','[data-continuous-review-block]','[data-microphone-preview]','[data-microphone-timing-panel]','[data-microphone-timing]','[data-voice-hint]','[data-mode-label]','[data-mode-description]','[data-recording-notice]','[data-review-audio-notice]','[data-review-audio-status]','[data-review-audio-scope]','[data-review-audio-eligibility]','[data-review-audio-consent]','[data-review-audio-enable]','[data-review-audio-disable]','[data-review-audio-review]','[data-review-audio-clip]','[data-review-audio-clip-metadata]','[data-review-audio-preview]','[data-review-audio-audition]','[data-review-audio-audition-status]','[data-review-audio-attestation]','[data-review-audio-confirm]','[data-review-audio-cancel]','[data-review-audio-result]','[data-rehearsal-banner]','[data-rehearsal-controls]','[data-rehearsal-input]','[data-rehearsal-hint]','[data-subtitle]','[data-photo]','[data-pose]','[data-scene-label]','[data-phase-label]','[data-character-description]'])nodes.set(s,new Node());
 if(noticeElements==='all'||noticeElements==='region')nodes.set('[data-system-notice]',new Node());
 if(noticeElements==='all'||noticeElements==='body')nodes.set('[data-system-notice-body]',new Node());
 globalThis.window=new Node();globalThis.document={querySelector:s=>nodes.get(s),querySelectorAll:()=>[],createElement:()=>new Node(),addEventListener(){},visibilityState:'visible'};globalThis.AudioContext=class{async resume(){}async close(){}};
 let client,revision=0,inputCount=0,lastState=null,pendingPoll=null,prefixEffect=null;const requests=[];const snapshot=patch=>({...base,client_instance_id:client,revision:++revision,permit_revision:revision,...patch});
 globalThis.fetch=async(url,options)=>{const path=String(url);if(path.endsWith('/diagnostics-status'))return Response.json({available:true,recording_active:false,notice:'',dropped_events:0,dropped_recordings:0,io_failures:0,pending_records:0});if(path.endsWith('/reviewed-audio')&&options.method==='GET')return Response.json({scope:'application',recording_active:false,has_pending_audio:false,staged_bytes:0,max_audio_bytes:512*1024,expires_in_seconds:0,pending_stream_id:null,pending_kind:null,input_completion_ready:false,notice:'off',scope_notice:'all local sessions'});if(path.endsWith('/voice-capabilities'))return Response.json({speech_enabled:false,microphone_enabled:false,speech_sample_rate_hz:24000,microphone_sample_rate_hz:16000,generation_mode:'mock',qualification:'unavailable'});if(path.endsWith('/sessions')&&options.method==='POST'){client=JSON.parse(options.body).client_instance_id;return Response.json({session:snapshot({}),session_token:'synthetic-token'})}if(path.endsWith('/inputs')){const request=JSON.parse(options.body);requests.push(request);inputCount++;const recorded=backendFixture?.sessions[inputCount-1];lastState={...(recorded??{}),activity_seq:request.activity_seq,input_epoch:inputCount,output_epoch:request.activity_seq,phase:'error',request_id:null,last_error:recorded?.last_error??codes[inputCount-1]??codes.at(-1),last_error_diagnostic_id:id};if(prefix!==null&&inputCount===1){prefixEffect={id:'prefix-'+inputCount,kind:'subtitle',value:prefix,digest:'b'.repeat(64),output_epoch:request.activity_seq,activity_seq:request.activity_seq};return Response.json(snapshot({...lastState,phase:'ready',request_id:request.request_id,last_error:null,last_error_diagnostic_id:null,active_grants:[prefixEffect]}))}return Response.json(snapshot(lastState))}if(path.endsWith('/receipts')){assert.ok(prefixEffect);lastState={...lastState,presented_effects:[prefixEffect]};return Response.json(snapshot(lastState))}if(path.endsWith('/stop'))return Response.json(snapshot({phase:'stopped',activity_seq:JSON.parse(options.body).activity_seq,active_grants:[]}));if(options.method==='GET')return await new Promise((resolve,reject)=>{pendingPoll=resolve;options.signal.addEventListener('abort',()=>reject(new Error('synthetic abort')),{once:true})});if(options.method==='DELETE')return new Response(null,{status:204});throw new Error('Unexpected synthetic fetch')};
 await import(new URL(`app/main.js?locator=${++sequence}`,dist));await tick();return{nodes,requests,async repeat(){assert.ok(pendingPoll,'initial controller poll is pending');pendingPoll(Response.json(snapshot(lastState)));pendingPoll=null;await tick();await tick()},async submit(){nodes.get('[name=message]').value='Synthetic input';nodes.get('form.composer').fire('submit');await tick();await tick()},async close(){nodes.get('[data-close]').fire('click');await tick();await tick();for(const[key,value]of Object.entries(globals)){if(value===undefined)delete globalThis[key];else globalThis[key]=value}}};
}

test('emitted main and actual controller render five review outcomes without silent turns',async()=>{
 const codes=['review_uncertain','review_uncertain','review_not_allowed','review_not_allowed','review_uncertain'];
 const h=await app({codes});
 try{
  for(const code of codes){
   await h.submit();
   if(code==='review_uncertain'){
    assert.equal(h.nodes.get('[data-system-notice]').hidden,false);
    assert.equal(h.nodes.get('[data-system-notice-body]').textContent,BODY);
    assert.equal(h.nodes.get('[data-error]').textContent,'');
   }else{
    assert.equal(h.nodes.get('[data-system-notice]').hidden,true);
    assert.match(h.nodes.get('[data-error]').textContent,/未获准呈现/);
   }
  }
  assert.equal(h.requests.length,5);
  await h.repeat();
  assert.equal(h.nodes.get('[data-system-notice]').hidden,false,'a repeated final snapshot keeps the notice visible');
  h.nodes.get('[data-stop]').fire('click');
  assert.equal(h.nodes.get('[data-system-notice]').hidden,true,'Stop clears the notice synchronously');
 }finally{await h.close()}
});
for(const noticeElements of ['none','region','body'])test(`emitted main retains UNKNOWN fallback when notice markup is ${noticeElements}`,async()=>{
 const h=await app({noticeElements});
 try{
  await h.submit();
  assert.equal(h.nodes.get('[data-error]').textContent,BODY,'optional markup cannot swallow the only response');
  await h.repeat();
  assert.equal(h.nodes.get('[data-error]').textContent,BODY,'ordinary snapshot refresh must not erase the fallback');
  h.nodes.get('[data-stop]').fire('click');
  assert.equal(h.nodes.get('[data-error]').textContent,'');
 }finally{await h.close()}
});
test('emitted main keeps unclassified technical UNKNOWN visible as an error',async()=>{
 const h=await app({codes:['unknown']});
 try{
  await h.submit();
  assert.match(h.nodes.get('[data-error]').textContent,/未完成.*重试/);
  assert.equal(h.nodes.get('[data-system-notice]').hidden,true);
 }finally{await h.close()}
});

test('the single system notice stays next to the composer and outside the roleplay subtitle',()=>{
 const markup=readFileSync(process.env.MIRA_NOTICE_MARKUP??new URL('../../apps/web/index.html',import.meta.url),'utf8');
 assert.equal((markup.match(/data-system-notice /g)??[]).length,1);
 assert.match(markup,/<aside class="system-notice"[^>]*data-system-notice[^>]*role="status"[^>]*aria-live="polite"[\s\S]*?<strong>系统提示<\/strong>[\s\S]*?<p data-system-notice-body><\/p>\s*<\/aside>\s*(?:<p data-recovered-input-notice\b[\s\S]*?<\/p>\s*)?<form class="composer">/);
 assert.ok(markup.indexOf('data-system-notice ')>markup.indexOf('<fieldset class="conversation-controls">'));
});

test('emitted main keeps presented prefix and clears an UNKNOWN notice on new input and Close',async()=>{
 const h=await app({prefix:'synthetic already presented prefix'});
 try{
  await h.submit();
  assert.equal(h.nodes.get('[data-subtitle]').textContent,'synthetic already presented prefix');
  await h.repeat();
  assert.equal(h.nodes.get('[data-subtitle]').textContent,'synthetic already presented prefix');
  h.nodes.get('[name=message]').value='new input';
  h.nodes.get('form.composer').fire('submit');
  assert.equal(h.nodes.get('[data-system-notice]').hidden,true,'new input clears locally before fetch settles');
  for(let attempt=0;attempt<30&&h.nodes.get('[data-system-notice]').hidden;attempt++)await new Promise(resolve=>setTimeout(resolve,5));
  assert.equal(h.nodes.get('[data-system-notice]').hidden,false,JSON.stringify({purpose:'a different activity can show its own notice',error:h.nodes.get('[data-error]').textContent,requests:h.requests}));
  h.nodes.get('[data-close]').fire('click');
  assert.equal(h.nodes.get('[data-system-notice]').hidden,true,'Close clears locally before cleanup');
 }finally{await h.close()}
});
