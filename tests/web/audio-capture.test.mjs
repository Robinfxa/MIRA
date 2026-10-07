import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const dist = process.env.MIRA_TEST_WEB_DIST ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href : new URL('../../apps/web/dist/', import.meta.url).href;
const { MicrophoneCapture } = await import(new URL('features/audio/capture.js', dist));
const { StreamingPcm16Resampler } = await import(new URL('features/audio/pcm.js', dist));
const tick=async()=>{for(let i=0;i<10;i++)await Promise.resolve();};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
function fixture(options={}) {
  const chunks=[],errors=[],states=[],messages=[],listeners=new Map();let requests=0,trackStops=0,closes=0,disconnects=0,portCloses=0;
  const track={stop(){trackStops++;},getSettings:()=>({sampleRate:44100}),addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:(name)=>listeners.delete(name)};
  const stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
  const source={connect(){},disconnect(){disconnects++;}};
  const node={connect(){},disconnect(){disconnects++;},onprocessorerror:null,port:{onmessage:null,postMessage:x=>messages.push(x),close:()=>{portCloses++;}}};
  const context={sampleRate:48000,destination:{},audioWorklet:{addModule:async()=>{}},resume:async()=>{},close:async()=>{closes++;},createMediaStreamSource:()=>source};
  const capture=new MicrophoneCapture({onChunk:chunk=>chunks.push(chunk),onError:e=>errors.push(e),onState:s=>states.push(s),
    getUserMedia:async()=>{requests++;return options.streamPromise ? options.streamPromise : stream;},createContext:()=>context,createWorkletNode:()=>node,...options});
  return {capture,chunks,errors,states,messages,track,stream,node,context,listeners,
    emit:(samples=new Float32Array(960).fill(.5),startFrame=0,sequence=0)=>node.port.onmessage({data:{type:'samples',samples,sampleRate:context.sampleRate,startFrame,sequence}}),
    counts:()=>({requests,trackStops,closes,disconnects,portCloses})};
}

test('capture only asks for microphone on explicit start and releases every resource on stop',async()=>{
  const f=fixture();assert.equal(f.counts().requests,0);assert.equal(await f.capture.start(),true);
  assert.equal(f.counts().requests,1);assert.deepEqual(f.states,['starting','recording']);
  assert.equal(await f.capture.start(),false);f.capture.stop();f.capture.stop();await tick();
  assert.deepEqual(f.counts(),{requests:1,trackStops:1,closes:1,disconnects:2,portCloses:1});
});
test('capture reports actual context rate, source rate and contiguous 16k PCM16LE positions',async()=>{
  const f=fixture();await f.capture.start();f.emit();await tick();f.emit(new Float32Array(960).fill(-1),960,1);await tick();
  assert.equal(f.chunks.length,2);assert.equal(f.chunks[0].captureSampleRate,48000);assert.equal(f.chunks[0].sourceSampleRate,44100);
  assert.equal(f.chunks[0].sampleRate,16000);assert.equal(f.chunks[0].channels,1);assert.equal(f.chunks[0].pcm16le.byteLength,640);
  assert.equal(new DataView(f.chunks[0].pcm16le.buffer).getInt16(0,true),16384);
  assert.equal(new DataView(f.chunks[1].pcm16le.buffer).getInt16(0,true),-32768);
  assert.deepEqual(f.chunks.map(c=>[c.startSample,c.endSample,c.sequence]),[[0,320,0],[320,640,1]]);
  assert.deepEqual(f.messages.filter(m=>m.type==='ack').map(m=>m.sequence),[0,1]);
  f.capture.stop();
});
test('stop during permission request releases late tracks without constructing nodes or sending audio',async()=>{
  const permission=deferred(),f=fixture({streamPromise:permission.promise});const start=f.capture.start();f.capture.stop();permission.resolve(f.stream);
  assert.equal(await start,false);assert.equal(f.counts().trackStops,1);assert.equal(f.chunks.length,0);assert.equal(f.counts().disconnects,0);
});
test('late module load and resume cannot revive capture after close',async()=>{
  const load=deferred(),f=fixture();f.context.audioWorklet.addModule=()=>load.promise;
  const start=f.capture.start();await tick();await f.capture.close();load.resolve();assert.equal(await start,false);
  assert.equal(f.counts().trackStops,1);assert.equal(f.counts().closes,1);assert.equal(await f.capture.start(),false);
});
test('permission denial and unsupported worklet expose errors with text fallback',async()=>{
  const denied=fixture({getUserMedia:async()=>{throw Object.assign(new Error('private browser error'),{name:'NotAllowedError'});}});
  assert.equal(await denied.capture.start(),false);assert.equal(denied.errors[0].code,'permission-denied');assert.equal(denied.errors[0].message.includes('private'),false);
  const missing=fixture();missing.context.audioWorklet=undefined;assert.equal(await missing.capture.start(),false);
  assert.equal(missing.counts().requests,0);assert.equal(missing.errors[0].code,'unsupported');
});
test('consumer backpressure is bounded and stale acknowledgements after stop are suppressed',async()=>{
  const pending=deferred(),f=fixture({onChunk:()=>pending.promise,maxPendingChunks:2});await f.capture.start();
  f.emit();f.emit(new Float32Array(960),960,1);f.emit(new Float32Array(960),1920,2);
  assert.equal(f.errors.at(-1).code,'capture-overflow');assert.equal(f.counts().trackStops,1);
  pending.resolve();await tick();assert.equal(f.messages.filter(m=>m.type==='ack').length,0);
});
test('consumer rejection, processing error and unexpected track end all release capture',async()=>{
  const f=fixture({onChunk:async()=>{throw new Error('transport error');}});await f.capture.start();f.emit();await tick();
  assert.equal(f.errors.at(-1).code,'consumer-failed');assert.equal(f.counts().trackStops,1);
  const g=fixture();await g.capture.start();g.node.onprocessorerror();assert.equal(g.errors.at(-1).code,'capture-failed');
  const h=fixture();await h.capture.start();h.listeners.get('ended')();assert.equal(h.errors.at(-1).code,'device-ended');
});
test('saved worklet message callback cannot leak audio after stop or into a new capture',async()=>{
  const f=fixture();await f.capture.start();const old=f.node.port.onmessage;f.capture.stop();await f.capture.start();
  old({data:{type:'samples',samples:new Float32Array(960),sampleRate:48000,startFrame:0,sequence:0}});
  assert.equal(f.chunks.length,0);f.capture.stop();
});
test('malformed or discontinuous microphone frames fail closed',async()=>{
  const f=fixture();await f.capture.start();f.emit(new Float32Array(960),0,0);await tick();f.emit(new Float32Array(960),1920,1);
  assert.equal(f.errors.at(-1).code,'capture-failed');assert.equal(f.chunks.length,1);
});
test('resampling retains fractional state across arbitrary chunk boundaries without drift',()=>{
  const source=new Float32Array(44100).fill(.25),one=new StreamingPcm16Resampler(44100),streaming=new StreamingPcm16Resampler(44100);
  const whole=one.push(source);assert.equal(whole.length,32000);
  const pieces=[];for(let p=0;p<source.length;p+=137)pieces.push(streaming.push(source.slice(p,p+137)));
  assert.deepEqual(Buffer.concat(pieces.map(x=>Buffer.from(x))),Buffer.from(whole));
  assert.equal(new DataView(whole.buffer).getInt16(0,true),8192);
});

test('old context close rejection cannot report failure into a newer capture',async()=>{
  const closing=deferred(),f=fixture();let closes=0;
  f.context.close=()=>++closes===1?closing.promise:Promise.resolve();
  await f.capture.start();f.capture.stop();await f.capture.start();
  closing.reject(new Error('old device cleanup failure'));await tick();
  assert.equal(f.errors.length,0);assert.equal(f.states.at(-1),'recording');
  f.emit();await tick();assert.equal(f.chunks.length,1);
  f.capture.stop();await f.capture.close();
});
test('current cleanup failure still reports a sanitized release warning',async()=>{
  const closing=deferred(),f=fixture();f.context.close=()=>closing.promise;
  await f.capture.start();f.capture.stop();closing.reject(new Error('private device cleanup error'));await tick();
  assert.equal(f.errors.length,1);assert.equal(f.errors[0].code,'capture-failed');
  assert.equal(f.errors[0].message.includes('private'),false);await f.capture.close();
});

test('consumer failures identify only a closed capture stage and safe counters',async()=>{
  for(const asynchronous of [false,true]){
    const problem=new Error('private transcript token path');
    const f=fixture({onChunk:()=>{if(asynchronous)return Promise.reject(problem);throw problem;}});
    await f.capture.start();f.emit();await tick();
    assert.deepEqual(f.errors[0].delivery,{stage:'chunk',emittedChunks:1,outputSamples:320});
    assert.match(f.errors[0].message,/stage=chunk; chunks=1; samples=320/);
    assert.doesNotMatch(JSON.stringify(f.errors),/private|transcript|token|path/);
    assert.equal(f.counts().trackStops,1);
  }
  const ack=fixture();await ack.capture.start();ack.node.port.postMessage=value=>{if(value.type==='ack')throw new Error('private ack error');};
  ack.emit();await tick();assert.deepEqual(ack.errors[0].delivery,{stage:'acknowledgement',emittedChunks:1,outputSamples:320});
  assert.equal(ack.counts().trackStops,1);
});
