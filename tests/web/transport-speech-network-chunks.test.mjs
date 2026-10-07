import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST ?? 'apps/web/dist')+'/');
const {BrowserAudioTransport}=await import(new URL('features/session/audio-transport.js',dist));
const effect={id:'synthetic-effect',kind:'speech',value:'synthetic text',digest:'a'.repeat(64),activity_seq:1,output_epoch:1};
const encoded=new TextEncoder();
const origin=e=>({effect_id:e.id,stream_id:e.id,digest:e.digest,activity_seq:e.activity_seq,output_epoch:e.output_epoch});
function frame(index,frames=6000,e=effect) {
  const bytes=Buffer.alloc(frames*2);
  for(let i=0;i<frames;i++)bytes.writeInt16LE(Math.round(Math.sin(i*0.071+index)*16000),i*2);
  return JSON.stringify({...origin(e),type:'audio',sequence:index+1,first_sample:index*frames,sample_rate_hz:24000,pcm_base64:bytes.toString('base64')})+'\n';
}
const terminal=(frames,e=effect)=>JSON.stringify({...origin(e),type:'complete',total_samples:frames})+'\n';
function client(chunks) {
  let cancelled=false;
  const iterator=chunks[Symbol.iterator]();
  const body=new ReadableStream({pull(controller){const next=iterator.next();if(next.done)controller.close();else controller.enqueue(typeof next.value==='string'?encoded.encode(next.value):next.value);},cancel(){cancelled=true;}});
  const api=new BrowserAudioTransport({apiBase:'/synthetic'},()=>({sessionId:'synthetic',token:'synthetic'}),{fetch:async()=>new Response(body,{headers:{'content-type':'application/x-ndjson'}})});
  return {api,get cancelled(){return cancelled;}};
}
function* split(bytes,width) {for(let i=0;i<bytes.length;i+=width)yield bytes.subarray(i,i+width);}

test('one valid 6.25 second response decodes identically for coalesced and fragmented reads',async()=>{
  const text=Array.from({length:25},(_,i)=>frame(i)).join('')+terminal(150000), bytes=encoded.encode(text);
  assert.ok(bytes.length>262144);
  const results=[];
  for(const chunks of [[bytes],split(bytes,7),split(bytes,16383),split(bytes,65536)]) {
    const c=client(chunks),got=[];
    await c.api.speech(effect,new AbortController().signal,pcm=>got.push(pcm));
    results.push(Buffer.concat(got.map(pcm=>Buffer.from(pcm.buffer))));
    assert.equal(got.length,25); assert.equal(got.reduce((sum,p)=>sum+p.length,0),150000);
    c.api.close();
  }
  for(const result of results)assert.deepEqual(result,results[0]);
});

test('split UTF-8 is decoded across both network and internal window boundaries',async()=>{
  const unicodeEffect={...effect,id:'synthetic-界'};
  const line=frame(0,2,unicodeEffect), point=encoded.encode(line.slice(0,line.indexOf('界'))).length;
  const prefix=' '.repeat(16383-point);
  const bytes=encoded.encode(prefix+line+terminal(2,unicodeEffect));
  assert.equal(bytes[16383],0xe7);
  for(const chunks of [[bytes],split(bytes,16384),split(bytes,1)]){
    const c=client(chunks),got=[];await c.api.speech(unicodeEffect,new AbortController().signal,pcm=>got.push(pcm));
    assert.equal(got.length,1);assert.equal(got[0].length,2);c.api.close();
  }
});

for(const kind of ['oversized-line','unterminated-line','empty-line','after-terminal','bad-utf8'])test(`${kind} remains rejected after a rendered prefix`,async()=>{
  const suffix=kind==='oversized-line'?' '.repeat(20001)+frame(1):kind==='unterminated-line'?' '.repeat(20001):kind==='empty-line'?'\n':kind==='after-terminal'?terminal(6000)+frame(1):new Uint8Array([0xff]);
  const c=client([frame(0),suffix]),got=[];
  await assert.rejects(c.api.speech(effect,new AbortController().signal,pcm=>got.push(pcm)));
  assert.equal(got.length,1);c.api.close();
});

test('cumulative 300 second transport sample ceiling still rejects the next valid PCM frame',async()=>{
  function* chunks(){for(let i=0;i<=1200;i++)yield frame(i);yield terminal(7206000);}
  const c=client(chunks());let received=0;
  await assert.rejects(c.api.speech(effect,new AbortController().signal,pcm=>{received+=pcm.length;}),/duration exceeded/);
  assert.equal(received,7200000);c.api.close();
});

test('aborting inside a coalesced read suppresses its remaining PCM and closes the reader',async()=>{
  const c=client([Array.from({length:25},(_,i)=>frame(i)).join('')+terminal(150000)]),abort=new AbortController();let received=0;
  await assert.rejects(c.api.speech(effect,abort.signal,pcm=>{received+=pcm.length;abort.abort();}),/cancelled/);
  assert.equal(received,6000);c.api.close();
});
