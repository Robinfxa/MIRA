import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {BrowserAudioTransport}=await import(new URL('features/session/audio-transport.js',dist));
const streamId='12345678-1234-4234-8234-123456789012';
const origin={stream_id:streamId,activity_seq:2,input_epoch:1};
class Socket {readyState=0;bufferedAmount=0;onopen=null;onmessage=null;onerror=null;onclose=null;sent=[];closed=false;send(text){this.sent.push(JSON.parse(text));}close(){this.closed=true;this.readyState=3;}open(){this.readyState=1;this.onopen?.({});}message(value){this.onmessage?.({data:JSON.stringify(value)});}}
function make(now=()=>100){const socket=new Socket(),revisions=[],timings=[];const api=new BrowserAudioTransport({apiBase:'/api/v1',pollIntervalMs:200},()=>({sessionId:'s',token:'secret'}),{createSocket:()=>socket,baseUrl:'https://mira.test/',now});const stream=api.microphone(origin,new AbortController().signal,{timingOriginMs:100,onRevision:value=>revisions.push(value),onTiming:value=>timings.push(value)});return {api,socket,stream,revisions,timings};}
function ready(h){h.socket.open();h.socket.message({type:'ready',...origin});}
const transcript=(revision,text,is_final=false)=>({type:'transcript',stream_id:streamId,revision,text,is_final});

test('valid revisions reach only the optional provisional callback and produce numeric elapsed timing',async()=>{
 let clock=100;const h=make(()=>clock);ready(h);await h.stream.ready;
 try {
  clock=102;h.socket.message(transcript(1,'临时片段'));clock=103;h.socket.message(transcript(2,'确定片段',true));
  assert.deepEqual(h.revisions.map(x=>[x.stream_id,x.revision,x.text,x.is_final]),[[streamId,1,'临时片段',false],[streamId,2,'确定片段',true]]);
  clock=104;const done=h.stream.finish();h.socket.message({type:'complete',stream_id:streamId,revision:2,text:'最终完整输入',had_final:true});
  assert.deepEqual(await done,{text:'最终完整输入',had_final:true});
  const t=h.timings.at(-1);assert.equal(t.stream_id,streamId);assert.equal(t.dispatch_ms,0);assert.equal(t.first_revision_ms,2);assert.equal(t.first_final_revision_ms,3);assert.equal(t.client_finish_ms,4);assert.equal(t.stream_close_ms,4);assert.equal(t.revision_count,2);assert.equal(t.final_revision_count,1);
  assert.deepEqual(Object.keys(t).sort(),['client_finish_ms','dispatch_ms','final_revision_count','first_final_revision_ms','first_revision_ms','revision_count','stream_close_ms','stream_id'].sort());
 } finally {h.api.close();}
});

test('finish clears preview, interim after client finish cannot repaint, final remains only in completion',async()=>{
 const h=make();ready(h);await h.stream.ready;
 try {
  h.socket.message(transcript(1,'still provisional'));const done=h.stream.finish();assert.equal(h.revisions.at(-1),null);
  h.socket.message(transcript(2,'late interim'));assert.equal(h.revisions.at(-1),null);
  h.socket.message({type:'complete',stream_id:streamId,revision:2,text:'only reliable final',had_final:true});
  assert.deepEqual(await done,{text:'only reliable final',had_final:true});assert.equal(h.revisions.at(-1),null);
 } finally {h.api.close();}
});

test('duplicate and out-of-order revisions fail closed and clear the provisional value',async()=>{
 for(const revisions of [[transcript(1,'ok'),transcript(1,'duplicate')],[transcript(2,'ok'),transcript(1,'older')]]){
  const h=make();ready(h);await h.stream.ready;const settled=h.stream.completion.catch(error=>error);
  try {
   for(const item of revisions)h.socket.message(item);
   assert.equal(h.revisions.at(-1),null);assert.equal(h.socket.closed,true);
   assert.match((await settled).message,/validation/);
  } finally {h.api.close();}
 }
});

test('final revision before user finish stays provisional and cannot authorize complete',async()=>{
 const h=make();ready(h);await h.stream.ready;const settled=h.stream.completion.catch(error=>error);
 try {
  h.socket.message(transcript(1,'segment final',true));h.socket.message({type:'complete',stream_id:streamId,revision:1,text:'unearned',had_final:true});
  assert.equal(h.socket.closed,true);assert.deepEqual(h.revisions.at(-1),null);assert.match((await settled).message,/validation/);
 } finally {h.api.close();}
});

test('transport close and late packet cannot restore an old revision',async()=>{
 const h=make();ready(h);await h.stream.ready;const settled=h.stream.completion.catch(error=>error);
 try {
  h.socket.message(transcript(1,'clear on close'));h.socket.onclose();await settled;h.socket.message(transcript(2,'stale'));
  assert.equal(h.revisions.at(-1),null);assert.equal(h.socket.closed,true);
 } finally {h.api.close();}
});

test('callers may omit revision and timing callbacks',async()=>{
 const socket=new Socket(),api=new BrowserAudioTransport({apiBase:'/api/v1',pollIntervalMs:200},()=>({sessionId:'s',token:'secret'}),{createSocket:()=>socket,baseUrl:'https://mira.test/'});
 try {const stream=api.microphone(origin,new AbortController().signal);socket.open();socket.message({type:'ready',...origin});await stream.ready;const done=stream.finish();socket.message(transcript(1,'final',true));socket.message({type:'complete',stream_id:streamId,revision:1,text:'final',had_final:true});assert.deepEqual(await done,{text:'final',had_final:true});}
 finally {api.close();}
});
