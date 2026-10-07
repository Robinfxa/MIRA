import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST??'apps/web/dist')+'/').href;
const {MicrophoneCapture}=await import(new URL('features/audio/capture.js',dist));
const {ContinuousListeningController}=await import(new URL('features/session/continuous-listening.js',dist));
function harness(configuration={}) {
  const {permission=false,late=false,settingsThrow=false,supportThrow=false}=configuration;
  const supported=Object.hasOwn(configuration,'supported')?configuration.supported:true;
  const reported=Object.hasOwn(configuration,'reported')?configuration.reported:true;
  const reports=[],chunks=[],errors=[],reads=[],constraints=[];let stopped=0,resolveMedia;
  const settings=new Proxy({sampleRate:48000,echoCancellation:reported},{get(target,key){reads.push(key);if(!['sampleRate','echoCancellation'].includes(key))throw new Error('Unexpected identifying settings access');return target[key];}});
  const track={getSettings(){if(settingsThrow)throw new Error('Settings unavailable');return settings;},stop(){stopped++;},addEventListener(){},removeEventListener(){}};
  const stream={getAudioTracks:()=>[track],getTracks:()=>[track]};
  const node={port:{onmessage:null,postMessage(){},close(){}},connect(){},disconnect(){}};
  const context={sampleRate:48000,currentTime:0.04,audioWorklet:{addModule:async()=>{}},resume:async()=>{},close:async()=>{},
    createMediaStreamSource:()=>({connect(){},disconnect(){}}),destination:{}};
  const capture=new MicrophoneCapture({onChunk:chunk=>{chunks.push(chunk);return configuration.observers?.onChunk(chunk);},onError:error=>{errors.push(error);configuration.observers?.onError(error);},onProcessing:state=>{reports.push(state);configuration.observers?.onProcessing?.(state);},onState:state=>configuration.observers?.onState(state),
    getSupportedConstraints(){if(supportThrow)throw new Error('Support unavailable');return {echoCancellation:supported};},
    getUserMedia:async value=>{constraints.push(value);if(permission){const error=new Error('denied');error.name='NotAllowedError';throw error;}
      if(late)return await new Promise(resolve=>resolveMedia=resolve);return stream;},createContext:()=>context,createWorkletNode:()=>node,chunkMilliseconds:40});
  return {capture,reports,chunks,errors,reads,constraints,context,node,release:()=>resolveMedia(stream),stopped:()=>stopped};
}
test('capture reports only requested, supported and reported AEC booleans while preserving capture constraints',async()=>{
  const h=harness();assert.equal(await h.capture.start(),true);
  assert.deepEqual(h.reports,[{echoCancellationRequested:true,echoCancellationSupported:true,echoCancellationReported:true}]);
  assert.equal(h.constraints[0].audio.echoCancellation,true);assert.ok(h.reads.every(key=>['sampleRate','echoCancellation'].includes(key)));
  h.capture.stop();assert.equal(h.reports.at(-1),null);assert.equal(h.stopped(),1);await h.capture.close();
});
test('AEC false and unavailable/string settings stay distinct without failing microphone capture',async()=>{
  for(const configuration of [{supported:false,reported:false},{supported:undefined,reported:undefined},{reported:'all'},{settingsThrow:true},{supportThrow:true}]) {
    const h=harness(configuration);assert.equal(await h.capture.start(),true);const value=h.reports.at(-1);
    assert.equal(value.echoCancellationReported,configuration.settingsThrow||typeof configuration.reported==='string'?null:
      Object.hasOwn(configuration,'reported')?configuration.reported??null:true);
    assert.equal(value.echoCancellationSupported,configuration.supportThrow?null:Object.hasOwn(configuration,'supported')?configuration.supported??false:true);
    assert.deepEqual(h.errors,[]);await h.capture.close();
  }
});
test('capture includes same-context delivery age without clocks or identifying data on the wire',async()=>{
  const h=harness();await h.capture.start();h.context.currentTime=0.16;
  h.node.port.onmessage({data:{type:'samples',samples:new Float32Array(1920),sampleRate:48000,startFrame:0,sequence:0}});
  assert.ok(Math.abs(h.chunks[0].deliveryLagMilliseconds-120)<0.001);await h.capture.close();
});
test('denied and stopped pending permission cannot publish settings or revive capture',async()=>{
  const denied=harness({permission:true});assert.equal(await denied.capture.start(),false);assert.ok(denied.reports.every(value=>value===null));
  assert.equal(denied.errors.at(-1).code,'permission-denied');await denied.capture.close();
  const late=harness({late:true});const pending=late.capture.start();late.capture.stop();late.release();assert.equal(await pending,false);
  assert.ok(late.reports.every(value=>value===null));assert.equal(late.stopped(),1);await late.capture.close();
});

test('real capture without AEC keeps default interruption bounded and permission/Stop fences remain intact', async () => {
 const flush=async()=>{for(let i=0;i<16;i++)await Promise.resolve();};
 let h,busy=false,interruptions=0,opens=0,frame=0,sequence=0;
 const views=[],sent=[];
 const controller=new ContinuousListeningController({mode:'natural',
  createCapture:observers=>(h=harness({supported:false,reported:false,observers})).capture,
  interruptReply:()=>{if(busy){interruptions++;busy=false;}return true;},isPlaybackBusy:()=>busy,
  openStream:lease=>{opens++;return {ready:Promise.resolve({lease_id:lease,sample_rate_hz:16000,max_seconds:120,max_samples:1920000,
   max_utterances:12,max_streams_per_session:4,max_total_streams:10,session_lease_starts_used:1,total_lease_starts_used:1,
   endpoint_mode:'google_vad_offsets_natural',manual_commit_required:false,client_endpoint_supported:true,client_silence_ms:700,drain_timeout_ms:2000,max_recognition_streams:4}),
   closed:new Promise(()=>{}),send:chunk=>sent.push(chunk),stop:async()=>{},cancel(){}};},
  submitInput:async()=>{throw Error('No synthetic echo may become input without transcript commit');},onUpdate:view=>views.push(view)});
 const pcm=async(level,count)=>{for(let i=0;i<count;i++){
  h.context.currentTime=(frame+1920)/48000;
  h.node.port.onmessage({data:{type:'samples',samples:new Float32Array(1920).fill(level),sampleRate:48000,startFrame:frame,sequence:sequence++}});
  frame+=1920;await flush();
 }};
 try {
  assert.equal(h.constraints.length,0);assert.equal(opens,0);assert.equal(controller.start(),true);await flush();
  assert.deepEqual(views.at(-1).capture_processing,{echoCancellationRequested:true,echoCancellationSupported:false,echoCancellationReported:false});
  assert.equal(h.constraints.length,1);assert.equal(h.constraints[0].audio.echoCancellation,true);
  for(let cycle=0;cycle<8;cycle++){await pcm(0,5);busy=true;await pcm(0.08,4);}
  assert.equal(interruptions,3);assert.equal(views.at(-1).barge_in_suspended,true);assert.equal(opens,1);assert.equal(h.stopped(),0);
  assert.equal(sent.length,72);assert.ok(h.reads.every(key=>['sampleRate','echoCancellation'].includes(key)));
  const late=h.node.port.onmessage;await controller.stop();late({data:{type:'samples',samples:new Float32Array(1920).fill(0.08),sampleRate:48000,startFrame:frame,sequence}});await flush();
  assert.equal(sent.length,72);assert.equal(interruptions,3);assert.equal(h.stopped(),1);assert.equal(views.at(-1).capture_processing,null);
 }finally{await controller.close();}
});
