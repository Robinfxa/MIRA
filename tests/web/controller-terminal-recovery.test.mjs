import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {CancelSafePlayback}=await import(new URL('features/audio/playback.js',dist));
const {SessionController}=await import(new URL('features/session/controller.js',dist));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const voice={speech_enabled:true,microphone_enabled:true,speech_sample_rate_hz:24000,microphone_sample_rate_hz:16000,qualification:'injected_unverified',generation_mode:'mock'};
function harness(options={}){
 const calls=[],received=[],progress=[],errors=[],phases=[],microphones=[],previews=[],timings=[];let client,rev=0,activity=0,inputEpoch=0;
 const session=(overrides={})=>({schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:client,revision:++rev,activity_seq:activity,input_epoch:inputEpoch,output_epoch:activity,permit_revision:rev,phase:'stopped',request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null,...overrides});
 const api={create:async c=>{client=c;return {session:session(),session_token:'secret'};},capabilities:async()=>options.capabilities??voice,snapshot:()=>new Promise(()=>{}),input:async r=>{calls.push(['input',r]);activity=r.activity_seq;inputEpoch++;const effect={id:`speech-${activity}`,kind:'speech',value:'hello',digest:'a'.repeat(64),output_epoch:activity,activity_seq:activity};return session({phase:'ready',request_id:r.request_id,active_grants:[effect]});},stop:async r=>{calls.push(['network-stop',r]);activity=r.activity_seq;return session();},receipt:async r=>{received.push(r);return session();},audioProgress:async r=>{progress.push(r);return session();},speech:async (e,s,push)=>{calls.push(['speech',e]);await push(new Int16Array([1,2]));},microphone:(origin,signal,observers)=>{calls.push(['microphone',origin]);const d=deferred();const stream={ready:Promise.resolve(),completion:d.promise,send:c=>calls.push(['pcm',c]),finish:()=>{calls.push(['finish']);return d.promise;},cancel:()=>calls.push(['mic-cancel']),resolve:d.resolve,signal,observers};microphones.push(stream);return stream;},close:async()=>calls.push(['api-close'])};
 let playbackOptions,captureOptions;
 const sink={active:null,unlock:async()=>{calls.push(['unlock']);return true;},open:e=>{calls.push(['open',e]);sink.active=e;return {push:pcm=>{calls.push(['push',pcm]);playbackOptions.onFact({origin:e,stage:'submitted',submittedFrames:pcm.length,renderedFrames:0,sampleRate:24000,inFlightFramesUncertain:pcm.length});return true;},finish:()=>{calls.push(['sealed']);return true;}};},stop:reason=>{calls.push(['local-audio-stop',reason]);if(sink.active){const e=sink.active;sink.active=null;playbackOptions.onFact({origin:e,stage:'stopped',submittedFrames:2,renderedFrames:0,sampleRate:24000,inFlightFramesUncertain:2,reason});}},reconcileAuthorization:()=>{if(sink.active&&!playbackOptions.isAuthorized(sink.active))sink.stop('revoked');},close:async()=>{sink.stop('close');calls.push(['sink-close']);}};
 const capture={start:async()=>{calls.push(['capture-start']);captureOptions.onState('recording');return true;},stop:()=>{calls.push(['capture-stop']);captureOptions.onState('stopped');},close:async()=>calls.push(['capture-close'])};
 const effects={apply:e=>calls.push(['visual',e]),prepareInput:()=>calls.push(['prepare']),stop:()=>calls.push(['scene-stop']),setPhase:p=>phases.push(p)};
 const view={connected:()=>calls.push(['connected']),update:s=>calls.push(['view',s]),error:e=>errors.push(e),localStop:()=>calls.push(['view-stop']),capabilities:v=>calls.push(['capabilities',v]),microphone:s=>calls.push(['mic-state',s]),microphonePreview:value=>previews.push(value),microphoneTiming:value=>timings.push(value)};
 const controller=new SessionController(api,effects,view,{apiBase:'/api/v1',pollIntervalMs:200},{createPlayback:o=>{playbackOptions=o;return options.createPlayback?options.createPlayback(o):sink;},createCapture:o=>{captureOptions=o;return capture;},
  externalMicrophoneActive:options.externalMicrophoneActive,onGlobalStop:options.onGlobalStop});
 return {controller,api,sink,capture,calls,received,progress,errors,phases,microphones,previews,timings,session,get playback(){return playbackOptions;},get captureEvents(){return captureOptions;}};
}

test('terminal identity releases capture once and preserves explicit voice restart until a new error',async()=>{
 let active=false;const stops=[];
 const h=harness({externalMicrophoneActive:()=>active,onGlobalStop:r=>{stops.push(r);active=false}});
 try {
  await h.controller.connect();await h.controller.input('first');await tick();
  const failedState=(state,code)=>{const {revision,permit_revision,...same}=state;return h.session({...same,phase:'error',request_id:null,active_grants:[],sealed:true,last_error:code})};
  const prior=h.controller.snapshot;
  const failed=failedState(prior,'generation_budget_exhausted');
  active=true;h.controller.install(failed);
  assert.equal(active,false);assert.equal(stops.filter(x=>x==='error').length,1);
  const sends=h.calls.filter(c=>c[0]==='input').length;
  active=true;h.controller.install(failed);h.controller.install(failedState(failed,'generation_budget_exhausted'));
  assert.equal(active,true,'a repeated terminal failure must not close newly restarted continuous capture');
  assert.equal(stops.filter(x=>x==='error').length,1);
  assert.match(h.errors.at(-1),/模型请求次数已用完/);
  assert.equal(h.calls.filter(c=>c[0]==='input').length,sends,'polling does not retry input');
  const second=failedState(failed,'quota_exhausted');
  h.controller.install(second);assert.equal(active,false);assert.equal(stops.filter(x=>x==='error').length,2);
  active=true;await h.controller.input('new explicit text');await tick();
  assert.equal(active,true);assert.equal(h.controller.snapshot.last_error,null);
  const next=h.controller.snapshot;
  h.controller.install(failed);assert.equal(active,true);assert.equal(h.controller.snapshot,next,'an old poll cannot replace a new turn');
  h.controller.install(failedState(next,'generation_budget_exhausted'));
  assert.equal(active,false);assert.equal(stops.filter(x=>x==='error').length,3,'same error in a new turn stops once again');
  active=true;await h.controller.stop();assert.equal(active,false);assert.equal(stops.at(-1),'stop');
  await h.controller.startMicrophone();await tick();assert.equal(h.controller.microphoneBusy,true);
 }finally{await h.controller.close()}
});
