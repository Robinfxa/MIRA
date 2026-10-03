import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const dist = process.env.MIRA_TEST_WEB_DIST ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href : new URL('../../apps/web/dist/', import.meta.url).href;
const { CancelSafePlayback } = await import(new URL('features/audio/playback.js', dist));
const origin = { id: 'audio-1', digest: 'a'.repeat(64), activity_seq: 1, output_epoch: 1 };
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => { resolve=a; reject=b; }); return {promise,resolve,reject}; };
function fixture(options={}) {
  const sources=[], facts=[], errors=[], timers=new Set();
  let authorized=true, resumes=0, closes=0;
  const context={ state:'running', currentTime:0, destination:{},
    resume: () => { resumes++; return options.resume ?? Promise.resolve(); },
    close: async()=>{closes++;},
    createBuffer: (channels,length,rate) => ({ channels,length,rate,data:new Float32Array(length),getChannelData(){return this.data;} }),
    createBufferSource: () => {const source={buffer:null,onended:null,started:0,stopped:0,disconnected:0,
      connect(){},disconnect(){this.disconnected++;},start(){this.started++;},stop(){this.stopped++;}}; sources.push(source);return source;},
  };
  const sink = new CancelSafePlayback({isAuthorized:()=>authorized,onFact:f=>facts.push(f),onError:e=>errors.push(e),
    createContext:()=>context,setInterval:fn=>{timers.add(fn);return fn;},clearInterval:id=>timers.delete(id),...options});
  return {sink,sources,facts,errors,context,timers,setAuthorized:v=>{authorized=v;},counts:()=>({resumes,closes})};
}

test('audio queue submits PCM24k sequentially and completes only after finish and natural end',async()=>{
  const f=fixture();const stream=f.sink.open(origin);assert.ok(stream);
  const samples=new Int16Array([-32768,0,32767]);assert.equal(stream.push(samples),true);samples[0]=0;
  assert.equal(stream.push(new Int16Array([10,20])),true);await tick();
  assert.equal(f.sources.length,1);assert.equal(f.sources[0].buffer.rate,24000);
  assert.deepEqual([...f.sources[0].buffer.data],[-1,0,32767/32768]);
  assert.deepEqual(f.facts.map(x=>x.stage),['submitted']);
  f.sources[0].onended();await tick();assert.equal(f.sources.length,2);
  f.sources[1].onended();await tick();assert.equal(f.facts.at(-1).stage,'rendered');
  assert.equal(stream.finish(),true);assert.equal(f.facts.at(-1).stage,'completed');
  assert.equal(f.facts.at(-1).renderedFrames,5);assert.equal(stream.push(new Int16Array([1])),false);
});
test('stop before resume suppresses start, old writes, and late completion',async()=>{
  const resume=deferred(),f=fixture({resume:resume.promise}),stream=f.sink.open(origin);
  assert.equal(stream.push(new Int16Array(10)),true);f.sink.stop();f.sink.stop();
  resume.resolve();await tick();assert.equal(f.sources.filter(s=>s.started).length,0);
  assert.equal(stream.push(new Int16Array(10)),false);assert.equal(stream.finish(),false);
  assert.equal(f.facts.filter(x=>x.stage==='completed').length,0);
});
test('stop disconnects active source, clears tail and suppresses saved onended',async()=>{
  const f=fixture(),stream=f.sink.open(origin);stream.push(new Int16Array(10));stream.push(new Int16Array(20));await tick();
  const oldEnd=f.sources[0].onended;f.sink.stop('new-input');
  assert.equal(f.sources[0].stopped,1);assert.ok(f.sources[0].disconnected);assert.equal(f.timers.size,0);
  oldEnd();await tick();assert.equal(f.sources.length,1);
  assert.equal(f.facts.at(-1).stage,'stopped');assert.equal(f.facts.at(-1).inFlightFramesUncertain,10);
});
test('new origin takes over without old promise callbacks harming the new stream',async()=>{
  const f=fixture(),old=f.sink.open(origin);old.push(new Int16Array(5));await tick();const oldEnd=f.sources[0].onended;
  const next=f.sink.open({...origin,id:'next',activity_seq:2,output_epoch:2});next.push(new Int16Array(7));next.finish();await tick();
  oldEnd();await tick();assert.equal(f.sources.length,2);assert.equal(f.sources[1].stopped,0);
  f.sources[1].onended();assert.equal(f.facts.at(-1).stage,'completed');assert.equal(f.facts.at(-1).origin.id,'next');
});
test('authorization checked before queued start, during rendering and explicit revocation',async()=>{
  const pending=deferred(),f=fixture({resume:pending.promise}),s=f.sink.open(origin);s.push(new Int16Array(8));
  f.setAuthorized(false);pending.resolve();await tick();assert.equal(f.sources.filter(s=>s.started).length,0);
  const g=fixture(),t=g.sink.open(origin);t.push(new Int16Array(8));t.finish();await tick();
  g.setAuthorized(false);g.sink.reconcileAuthorization();assert.equal(g.sources[0].stopped,1);
  const h=fixture();h.sink.open(origin).push(new Int16Array(8));await tick();h.setAuthorized(false);
  for(const callback of [...h.timers]) callback();assert.equal(h.sources[0].stopped,1);
});
test('invalid and oversized PCM fails closed instead of skipping content',async()=>{
  const f=fixture({maxBufferedFrames:10,maxChunkFrames:10}),s=f.sink.open(origin);
  assert.equal(s.push(new Int16Array(6)),true);assert.equal(s.push(new Int16Array(6)),false);
  await tick();assert.equal(f.errors.at(-1).code,'queue-overflow');assert.equal(s.finish(),false);
  const g=fixture();assert.equal(g.sink.open(origin).push(new Float32Array(4)),false);assert.equal(g.errors.at(-1).code,'invalid-pcm');
});
test('close is idempotent and disables delayed start and new streams',async()=>{
  const pending=deferred(),f=fixture({resume:pending.promise});f.sink.open(origin).push(new Int16Array(10));
  await f.sink.close();await f.sink.close();pending.resolve();await tick();
  assert.equal(f.counts().closes,1);assert.equal(f.sink.open(origin),null);assert.equal(f.sources.filter(s=>s.started).length,0);
});
test('unsupported and rejected audio resume expose errors without completed facts',async()=>{
  const f=fixture({createContext:()=>{throw new Error('missing browser audio');}});f.sink.open(origin).push(new Int16Array(3));await tick();
  assert.equal(f.errors.length,1);assert.equal(f.facts.at(-1).stage,'failed');
  const g=fixture({resume:Promise.reject(new Error('gesture needed'))});g.sink.open(origin).push(new Int16Array(3));await tick();
  assert.equal(g.errors.length,1);assert.equal(g.sources.length,0);
});

test('a source start failure cannot claim any submitted or uncertain rendered frames',async()=>{
  const f=fixture();const create=f.context.createBufferSource;
  f.context.createBufferSource=()=>{const source=create();source.start=()=>{throw new Error('device lost');};return source;};
  f.sink.open(origin).push(new Int16Array(12));await tick();const failed=f.facts.at(-1);
  assert.equal(failed.stage,'failed');assert.equal(failed.submittedFrames,0);assert.equal(failed.inFlightFramesUncertain,0);
});
test('observer-triggered local stop cannot start the queued tail or report completion',async()=>{
  let sink;const f=fixture({onFact:fact=>{if(fact.stage==='submitted')sink.stop();}});sink=f.sink;
  const stream=sink.open(origin);stream.push(new Int16Array(10));stream.push(new Int16Array(10));stream.finish();await tick();
  assert.equal(f.sources.length,1);assert.equal(f.sources[0].stopped,1);assert.equal(stream.push(new Int16Array(2)),false);
});
test('denied origins do not allocate browser resources and origin identities are immutable',async()=>{
  const f=fixture();f.setAuthorized(false);assert.equal(f.sink.open(origin),null);assert.equal(f.counts().resumes,0);
  f.setAuthorized(true);const mutable={...origin};const s=f.sink.open(mutable);mutable.id='mutated';s.push(new Int16Array(1));await tick();
  assert.equal(f.facts[0].origin.id,origin.id);assert.ok(Object.isFrozen(f.facts[0].origin));f.sink.stop();
});
test('an empty finished stream fails explicitly instead of reporting silent completion',()=>{
  const f=fixture();assert.equal(f.sink.open(origin).finish(),false);
  assert.equal(f.errors.at(-1).code,'invalid-pcm');assert.equal(f.facts.at(-1).stage,'failed');
});
