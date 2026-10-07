import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {SessionController}=await import(new URL('features/session/controller.js',dist));
const {ContinuousListeningController}=await import(new URL('features/session/continuous-listening.js',dist));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const leaseId='12345678-1234-4234-8234-123456789012';
const commitId='22345678-1234-4234-8234-123456789012';
const voice={speech_enabled:true,microphone_enabled:true,speech_sample_rate_hz:24000,microphone_sample_rate_hz:16000,
  qualification:'injected_unverified',generation_mode:'mock'};
const ready={type:'ready',lease_id:leaseId,sample_rate_hz:16000,max_seconds:120,max_samples:1920000,
  max_utterances:12,max_streams_per_session:4,max_total_streams:10,session_lease_starts_used:1,total_lease_starts_used:1,
  endpoint_mode:'google_vad_offsets_manual_commit',manual_commit_required:true};

function integration(){
  const calls=[],inputs=[],phases=[],continuousViews=[];let client,revision=0,activity=0,inputEpoch=0,captureOptions,streamObservers,resolveCommit;
  const session=(changes={})=>({schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:client,
    revision:++revision,activity_seq:activity,input_epoch:inputEpoch,output_epoch:activity,permit_revision:revision,
    phase:'stopped',request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null,...changes});
  let playbackOptions,continuousCaptureOptions;
  const sink={active:null,unlock:async()=>true,open(effect){
    const origin={id:effect.id,digest:effect.digest,activity_seq:effect.activity_seq,output_epoch:effect.output_epoch};
    sink.active=origin;
    return {push(pcm){playbackOptions.onFact({origin,stage:'submitted',submittedFrames:pcm.length,renderedFrames:0,
      sampleRate:24000,inFlightFramesUncertain:pcm.length});return true;},finish:()=>true};
  },stop(reason){
    calls.push(['audio-stop',reason]);
    const origin=sink.active;
    if(origin){sink.active=null;playbackOptions.onFact({origin,stage:'stopped',submittedFrames:2,renderedFrames:0,
      sampleRate:24000,inFlightFramesUncertain:2,reason});}
  },reconcileAuthorization(){if(sink.active&&!playbackOptions.isAuthorized(sink.active))sink.stop('revoked');},close(){sink.stop('close');}};
  const localCapture={start:async()=>true,stop(){calls.push('local-capture-stop');},close:async()=>calls.push('local-capture-close')};
  const continuousCapture={start(){calls.push('capture-start');continuousCaptureOptions.onState('recording');return Promise.resolve(true);},
    stop(){calls.push('continuous-capture-stop');continuousCaptureOptions.onState('stopped');},
    close:async()=>calls.push('continuous-capture-close')};
  const api={create:async id=>{client=id;return{session:session(),session_token:'secret'};},capabilities:async()=>voice,
    snapshot:()=>new Promise(()=>{}),input:async request=>{
      calls.push(['input',request]);inputs.push(request);activity=request.activity_seq;inputEpoch++;
      const effect={id:`speech-${activity}`,kind:'speech',value:'reply audio',digest:'a'.repeat(64),output_epoch:activity,activity_seq:activity};
      return session({phase:'ready',request_id:request.request_id,active_grants:[effect]});
    },stop:async request=>{calls.push(['network-stop',request]);activity=request.activity_seq;return session({phase:'stopped'});},
    receipt:async()=>session(),audioProgress:async request=>{calls.push(['audio-progress',request]);return session();},
    speech:async(_effect,_signal,push)=>{await push(new Int16Array([1,2]));await new Promise(()=>{});},
    microphone:()=>{throw new Error('Unexpected PTT microphone path');},close:async()=>calls.push('api-close')};
  const effects={apply(){},prepareInput(){},stop(){},setPhase:phase=>phases.push(phase)};
  const view={connected(){},update(){},error(){},localStop(){},capabilities(){},microphone(){},microphonePreview(){},microphoneTiming(){}};
  let continuous;
  const controller=new SessionController(api,effects,view,{apiBase:'/api/v1',pollIntervalMs:200},
    {createPlayback:options=>{playbackOptions=options;return sink;},createCapture:()=>localCapture,
      externalMicrophoneActive:()=>continuous?.microphoneActive===true,onGlobalStop:()=>{void continuous?.stop('user_stop');}});
  continuous=new ContinuousListeningController({createId:(()=>{let n=0;return()=>n++===0?leaseId:commitId;})(),
    createCapture:options=>{captureOptions=options;continuousCaptureOptions=options;return continuousCapture;},
    openStream:(_id,_signal,observers)=>{streamObservers=observers;return{ready:Promise.resolve(ready),closed:new Promise(()=>{}),
      send:chunk=>calls.push(['continuous-pcm',chunk]),commit:(id,revision)=>new Promise(resolve=>{calls.push(['commit',id,revision]);resolveCommit=resolve;}),
      stop:async()=>calls.push('continuous-stop'),cancel:()=>calls.push('continuous-cancel')};},
    submitInput:(text,id)=>controller.input(text,undefined,id),canStart:()=>!controller.microphoneBusy,
    onStart:()=>controller.interruptReply(),interruptReply:()=>controller.interruptReply(),
    onSpeechOnset:()=>controller.interruptReply(),onPhase:listening=>controller.setContinuousListeningPhase(listening),
    onUpdate:view=>continuousViews.push(view)});
  const reply=async text=>{await controller.input(text);await tick();assert.ok(sink.active,'synthetic reply should be in the real SessionController playback path');};
  const stop=async()=>{await continuous.stop();await controller.close();};
  return {controller,continuous,api,sink,calls,inputs,phases,continuousViews,reply,stop,
    get captureOptions(){return captureOptions;},get streamObservers(){return streamObservers;},
    resolveCommit(value){resolveCommit(value);}};
}
const captured=(sequence,amplitude=0)=>{
  const pcm16le=new Uint8Array(640),view=new DataView(pcm16le.buffer);
  for(let i=0;i<320;i++)view.setInt16(i*2,amplitude,true);
  return {pcm16le,sampleRate:16000,channels:1,sequence,startSample:sequence*320,endSample:(sequence+1)*320,
    captureSampleRate:48000,sourceSampleRate:null,captureStartFrame:sequence*960};
};

test('click-start cuts only the current reply before microphone capture and keeps the new lease',async()=>{
  const h=integration();
  try{await h.controller.connect();await h.reply('old reply');const starts=()=>h.calls.indexOf('capture-start');
    assert.equal(h.continuous.start(),true);assert.equal(h.sink.active,null,'start must synchronously stop old playback');
    assert.ok(starts()>=0);assert.ok(h.calls.indexOf('audio-stop')<starts(),'local interruption must precede capture start');
    await tick();assert.equal(h.continuous.active,true);assert.equal(h.calls.includes('continuous-stop'),false);
    assert.equal(h.calls.some(call=>Array.isArray(call)&&call[0]==='network-stop'),false,'reply interruption is not global Stop');
  }finally{await h.stop();}
});

test('Send interrupts locally before awaiting server commit, but keeps mic and exactly-once submission fences',async()=>{
  const h=integration();
  try{await h.controller.connect();assert.equal(h.continuous.start(),true);await tick();await h.reply('old reply');
    h.streamObservers.onEvent({type:'transcript',lease_id:leaseId,revision:1,text:'stable words',is_final:true});
    const send=h.continuous.sendCurrent();assert.equal(h.sink.active,null,'Send must cut audio before commit resolves');
    assert.equal(h.continuous.active,true);assert.equal(h.inputs.length,1,'no new model input before server confirms the exact text');
    assert.equal(h.calls.filter(call=>Array.isArray(call)&&call[0]==='commit').length,1);
    await tick();
    const terminal=h.calls.findLast(call=>Array.isArray(call)&&call[0]==='audio-progress');
    assert.equal(terminal?.[1].status,'interrupted','reply interruption keeps the terminal playback fact');
    assert.ok(h.calls.findIndex(call=>Array.isArray(call)&&call[0]==='audio-stop')
      <h.calls.findIndex(call=>Array.isArray(call)&&call[0]==='commit'),'local cut happens before the commit request begins');
    h.resolveCommit({type:'commit_ready',lease_id:leaseId,commit_id:commitId,segment_seq:1,revision:1,text:'server-confirmed words'});
    await send;await tick();assert.equal(h.inputs.length,2);assert.equal(h.inputs.at(-1).text,'server-confirmed words');
    assert.equal(h.inputs.at(-1).presentation_cutoff,terminal[1].presentation_seq,'the accepted input waits behind the causal playback receipt prefix');
    assert.equal(h.continuous.active,true);assert.equal(h.calls.includes('continuous-stop'),false);
  }finally{await h.stop();}
});

test('captured PCM onset cuts a reply once; silence and late ASR revisions never trigger it',async()=>{
  const h=integration();
  try{await h.controller.connect();assert.equal(h.continuous.start(),true);await tick();await h.reply('reply after lease start');
    h.captureOptions.onChunk(captured(0,0));assert.ok(h.sink.active,'silence cannot interrupt');
    h.captureOptions.onChunk(captured(1,2800));assert.ok(h.sink.active,'one energetic frame is below the onset qualification');
    h.captureOptions.onChunk(captured(2,2800));assert.equal(h.sink.active,null,'new captured speech-like PCM crosses local onset threshold');
    assert.equal(h.continuous.active,true);assert.equal(h.calls.includes('continuous-stop'),false);
    assert.equal(h.inputs.length,1,'audio onset is local and cannot create another model input');
    assert.equal(h.calls.filter(call=>Array.isArray(call)&&call[0]==='commit').length,0,'audio onset never commits text');
    for(let i=3;i<14;i++)h.captureOptions.onChunk(captured(i,0));
    h.streamObservers.onEvent({type:'transcript',lease_id:leaseId,revision:1,text:'stable words',is_final:true});
    const send=h.continuous.sendCurrent();await tick();
    h.resolveCommit({type:'commit_ready',lease_id:leaseId,commit_id:commitId,segment_seq:1,revision:1,text:'committed words'});
    await send;await tick();assert.ok(h.sink.active,'the committed next reply starts while the lease survives');
    h.streamObservers.onEvent({type:'transcript',lease_id:leaseId,revision:2,text:'late final tail after prior commit',is_final:true});
    assert.ok(h.sink.active,'a late ASR tail after a prior commit cannot interrupt the newer reply');
    h.captureOptions.onChunk(captured(14,2800));h.captureOptions.onChunk(captured(15,2800));
    assert.equal(h.sink.active,null,'the quiet reset rearms the detector for a later PCM onset');
    const stops=h.calls.filter(call=>Array.isArray(call)&&call[0]==='audio-stop').length;
    h.captureOptions.onChunk(captured(16,2800));h.captureOptions.onChunk(captured(17,2800));
    assert.equal(h.calls.filter(call=>Array.isArray(call)&&call[0]==='audio-stop').length,stops,'the same onset is latched once');
    assert.equal(h.inputs.length,2,'neither PCM onset nor the ASR tail adds a model request');
  }finally{await h.stop();}
});

test('global Stop and Close remain the paths that release continuous capture',async()=>{
  for(const action of ['stop','close']){const h=integration();await h.controller.connect();h.continuous.start();await tick();
    await h.reply('reply to stop or close');assert.equal(h.continuous.active,true);
    if(action==='stop')await h.controller.stop();else await h.controller.close();
    assert.equal(h.sink.active,null,`${action} also fences reply playback`);
    assert.equal(h.continuous.active,false,`${action} must release continuous mic`);
    assert.ok(h.calls.includes('continuous-capture-stop'));
    if(action==='stop')assert.ok(h.calls.indexOf('continuous-capture-stop')<h.calls.findIndex(call=>Array.isArray(call)&&call[0]==='network-stop'),
      'Stop releases local capture before the server Stop request');
    if(action!=='close')await h.controller.close();
  }
});

test('permission loss releases only the continuous lease and fences late transcript callbacks',async()=>{
  const h=integration();try{await h.controller.connect();h.continuous.start();await tick();
    h.streamObservers.onEvent({type:'transcript',lease_id:leaseId,revision:1,text:'preview to keep',is_final:false});
    h.captureOptions.onError({code:'permission-denied',message:'permission denied'});
    assert.equal(h.continuous.active,false);assert.ok(h.calls.includes('continuous-capture-stop'));
    h.streamObservers.onEvent({type:'transcript',lease_id:leaseId,revision:2,text:'late stale result',is_final:true});
    assert.equal(h.continuous.active,false);assert.equal(h.inputs.length,0);
    assert.equal(h.continuousViews.at(-1).previous_previews[0]?.text,'preview to keep','a late event cannot overwrite the retained pre-revoke preview');
    assert.equal(h.calls.includes('continuous-stop'),true,'permission loss sends a bounded lease stop');
  }finally{await h.stop();}
});
