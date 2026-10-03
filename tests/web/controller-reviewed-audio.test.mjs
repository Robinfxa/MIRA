import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {SessionController}=await import(new URL('features/session/controller.js',dist));
const {MiraHttpError}=await import(new URL('features/session/api-client.js',dist));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};}
const uuid='11111111-1111-4111-8111-111111111111';
const readyStatus=(patch={})=>({scope:'application',recording_active:true,has_pending_audio:true,staged_bytes:4,max_audio_bytes:512*1024,
  expires_in_seconds:10,pending_stream_id:uuid,pending_kind:'audio_input',input_completion_ready:true,notice:'safe',scope_notice:'all local sessions',...patch});

function fixture(status=readyStatus(),initialPatch={}){
  const events=[],inputs=[],progress=[],audioFacts=[],states=[],microphones=[];let clientId='client',revision=0,activity=0,inputEpoch=0,playbackBusy=false;
  const snapshot=(patch={})=>({schema_version:'0.1.0-foundation',session_id:'session',client_instance_id:clientId,revision:++revision,
    activity_seq:activity,input_epoch:inputEpoch,output_epoch:activity,permit_revision:revision,phase:'idle',request_id:null,sealed:false,
    active_grants:[],presented_effects:[],audio_progress:[],last_error:null,...patch});
  let current=snapshot();
  const api={
    create:async c=>{clientId=c;current=snapshot({client_instance_id:c,revision:0,permit_revision:0,activity_seq:0,input_epoch:0,
      output_epoch:0,...initialPatch});return {session:current,session_token:'synthetic-session-token'};},
    capabilities:async()=>({generation_mode:'injected',speech_enabled:false,microphone_enabled:true,speech_sample_rate_hz:24000,
      microphone_sample_rate_hz:16000,qualification:'injected_unverified'}),
    snapshot:()=>new Promise(()=>{}),
    stop:async request=>{events.push(['stop',request]);activity=request.activity_seq;current=snapshot({activity_seq:activity,phase:'stopped',request_id:null,sealed:false});return current;},
    input:async request=>{inputs.push({...request});activity=request.activity_seq;inputEpoch++;current=snapshot({activity_seq:activity,input_epoch:inputEpoch,
      request_id:request.request_id,phase:'ready'});return current;},
    receipt:async request=>{events.push(['receipt',request]);return current;},
    audioProgress:async request=>{progress.push(request);return current;},
    reviewedAudioStatus:async()=>status,
    microphone:origin=>{const result=deferred();const stream={ready:Promise.resolve(),completion:result.promise,finish:()=>result.promise,
      send:()=>{},cancel:()=>{},resolve:result.resolve,origin};microphones.push(stream);return stream;},
    speech:async()=>{},close:async()=>{},
  };
  const playbackOptions={};
  const playback={
    get quiescent(){return !playbackBusy;},unlock:async()=>true,open:()=>null,stop:()=>{if(playbackBusy){playbackBusy=false;playbackOptions.onAuditionState('stopped');}},
    stopAudition:()=>{if(playbackBusy){playbackBusy=false;playbackOptions.onAuditionState('stopped');}},
    audition:async(samples,rate)=>{if(playbackBusy)return false;playbackBusy=true;events.push(['audition',samples,rate]);playbackOptions.onAuditionState('starting');playbackOptions.onAuditionState('playing');return true;},
    reconcileAuthorization:()=>{},close:async()=>{playbackBusy=false;},
  };
  const capture={start:async()=>true,stop:()=>{},close:async()=>{}};
  const view={connected:()=>{},update:value=>{current=value;},error:error=>events.push(['error',error]),localStop:()=>{},
    capabilities:()=>{},microphone:()=>{},reviewAudition:state=>states.push(state)};
  const controller=new SessionController(api,{apply:()=>{},prepareInput:()=>{},stop:()=>{},setPhase:()=>{}},view,
    {apiBase:'/api/v1',pollIntervalMs:1000},{createPlayback:options=>{Object.assign(playbackOptions,options);return playback;},createCapture:()=>capture});
  return {controller,api,events,inputs,progress,audioFacts,states,microphones,get current(){return current;},
    setStatus(value){status=value;},setPlaybackBusy(value){playbackBusy=value;},get playbackBusy(){return playbackBusy;}};
}

test('successful final microphone transcript preserves only a server-bound owner-matching raw-audio stream ID',async()=>{
  const f=fixture();await f.controller.connect();await f.controller.startMicrophone();await tick();
  assert.equal(f.microphones.length,1);const streamId=f.microphones[0].origin.stream_id;
  f.setStatus(readyStatus({pending_stream_id:streamId}));
  const finish=f.controller.finishMicrophone();await tick();f.microphones[0].resolve({text:'synthetic final words',had_final:true});await finish;
  assert.equal(f.inputs.length,1);assert.equal(f.inputs[0].source_audio_stream_id,streamId);assert.equal(f.inputs[0].text,'synthetic final words');
  await f.controller.close();
});

test('mismatched, non-final, wrong-kind or disabled raw staging never prevents a valid transcript',async()=>{
  const statuses=[
    readyStatus({input_completion_ready:false}),
    readyStatus({pending_stream_id:'22222222-2222-4222-8222-222222222222'}),
    readyStatus({pending_kind:'audio_output'}),
    readyStatus({recording_active:false}),
  ];
  for(const candidate of statuses){
    const f=fixture(candidate);await f.controller.connect();await f.controller.startMicrophone();await tick();
    const finish=f.controller.finishMicrophone();await tick();f.microphones[0].resolve({text:'synthetic final words',had_final:true});await finish;
    assert.equal(f.inputs.length,1);assert.equal(Object.hasOwn(f.inputs[0],'source_audio_stream_id'),false);await f.controller.close();
  }
  const f=fixture();await f.controller.connect();await f.controller.startMicrophone();await tick();
  const finish=f.controller.finishMicrophone();await tick();f.microphones[0].resolve({text:'interim only',had_final:false});await finish;
  assert.equal(f.inputs.length,0);await f.controller.close();
});

test('a newer text input aborts a pending owner-status lookup before the old transcript can overwrite it',async()=>{
  const f=fixture(),pending=deferred();f.api.reviewedAudioStatus=()=>pending.promise;await f.controller.connect();await f.controller.startMicrophone();await tick();
  const finish=f.controller.finishMicrophone();await tick();f.microphones[0].resolve({text:'old synthetic transcript',had_final:true});await tick();
  await f.controller.input('newer typed text');pending.resolve(readyStatus({pending_stream_id:f.microphones[0].origin.stream_id}));await finish;
  assert.deepEqual(f.inputs.map(value=>value.text),['newer typed text']);
  assert.equal(f.inputs[0].source_audio_stream_id,undefined);await f.controller.close();
});

test('audition lifecycle admits only fresh idle, stopped, or fully settled idle sessions',async()=>{
  const fresh=fixture();await fresh.controller.connect();
  assert.deepEqual({phase:fresh.current.phase,sealed:fresh.current.sealed,request_id:fresh.current.request_id,
    revision:fresh.current.revision,activity_seq:fresh.current.activity_seq,input_epoch:fresh.current.input_epoch,
    output_epoch:fresh.current.output_epoch,permit_revision:fresh.current.permit_revision,
    active_grants:fresh.current.active_grants.length},
  {phase:'idle',sealed:false,request_id:null,revision:0,activity_seq:0,input_epoch:0,output_epoch:0,permit_revision:0,active_grants:0});
  assert.equal(fresh.controller.canAuditionReviewedAudio(),true);

  const stopped=fixture();await stopped.controller.connect();await stopped.controller.stop();
  assert.deepEqual({phase:stopped.current.phase,sealed:stopped.current.sealed,request_id:stopped.current.request_id},
    {phase:'stopped',sealed:false,request_id:null});
  assert.equal(stopped.controller.canAuditionReviewedAudio(),true);

  const subtitleGrant={id:'subtitle-grant',kind:'subtitle',value:'synthetic caption',digest:'d'.repeat(64),output_epoch:0,activity_seq:0};
  const completed=fixture();await completed.controller.connect();
  completed.controller.install({...completed.current,revision:completed.current.revision+1,permit_revision:completed.current.permit_revision+1,
    phase:'idle',request_id:uuid,sealed:true,active_grants:[subtitleGrant],presented_effects:[subtitleGrant]});
  assert.equal(completed.controller.canAuditionReviewedAudio(),true);
  const completedSpeechGrant={...subtitleGrant,id:'completed-speech-grant',kind:'speech',value:'synthetic speech'};
  const completedSpeech=fixture();await completedSpeech.controller.connect();
  completedSpeech.controller.install({...completedSpeech.current,revision:completedSpeech.current.revision+1,
    permit_revision:completedSpeech.current.permit_revision+1,phase:'idle',request_id:uuid,sealed:true,
    active_grants:[completedSpeechGrant],presented_effects:[completedSpeechGrant]});
  assert.equal(completedSpeech.controller.canAuditionReviewedAudio(),true,
    'server presented history marks speech terminal only after completed audio progress');
  const unfinished=fixture();await unfinished.controller.connect();
  unfinished.controller.install({...unfinished.current,revision:unfinished.current.revision+1,permit_revision:unfinished.current.permit_revision+1,
    phase:'idle',request_id:uuid,sealed:true,active_grants:[subtitleGrant],presented_effects:[]});
  assert.equal(unfinished.controller.canAuditionReviewedAudio(),false,'sealed idle is not settled while a grant is unpresented');
  const liveSpeech={...subtitleGrant,id:'speech-grant',kind:'speech',value:'synthetic speech'};
  const speech=fixture();await speech.controller.connect();
  speech.controller.install({...speech.current,revision:speech.current.revision+1,permit_revision:speech.current.permit_revision+1,
    phase:'idle',request_id:uuid,sealed:true,active_grants:[liveSpeech],presented_effects:[]});
  assert.equal(speech.controller.canAuditionReviewedAudio(),false,'a speech grant without completed presentation stays pending');
  await fresh.controller.close();await stopped.controller.close();await completed.controller.close();
  await completedSpeech.controller.close();await unfinished.controller.close();await speech.controller.close();

  const activeGrant={id:'speech-grant',kind:'speech',value:'synthetic',digest:'c'.repeat(64),output_epoch:1,activity_seq:1};
  const blocked=[
    {phase:'thinking',request_id:uuid,sealed:false,active_grants:[]},
    {phase:'ready',request_id:uuid,sealed:false,active_grants:[]},
    {phase:'ready',request_id:uuid,sealed:true,active_grants:[]},
    {phase:'ready',request_id:uuid,sealed:true,active_grants:[activeGrant]},
    {phase:'error',request_id:null,sealed:false,active_grants:[]},
    {phase:'idle',request_id:uuid,sealed:false,active_grants:[]},
    {phase:'idle',request_id:null,sealed:true,active_grants:[]},
    {phase:'stopped',request_id:null,sealed:true,active_grants:[]},
  ];
  for(const state of blocked){
    const f=fixture();await f.controller.connect();
    f.controller.install({...f.current,revision:f.current.revision+1,permit_revision:f.current.permit_revision+1,...state});
    assert.equal(f.controller.canAuditionReviewedAudio(),false,JSON.stringify(state));
    await f.controller.close();
  }
  const uncertain=fixture();await uncertain.controller.connect();await uncertain.controller.input('synthetic input starts an activity');
  uncertain.controller.install({...uncertain.current,revision:uncertain.current.revision+1,permit_revision:uncertain.current.permit_revision+1,
    phase:'idle',request_id:null,sealed:false,active_grants:[]});
  assert.equal(uncertain.controller.canAuditionReviewedAudio(),false,'an unsealed idle snapshot after activity is not a fresh session');
  await uncertain.controller.close();
});

test('only the explicit HTTP 409 history_pending rejection is returned as known not-sent',async()=>{
  const expected='上一轮可见内容尚未确认保存；本次输入未送出。请等待状态更新后重试。';
  const known=fixture();known.api.input=async()=>{throw new MiraHttpError(409,'history_pending','safe generic HTTP copy');};
  await known.controller.connect();const outcome=await known.controller.input('keep this exact text');
  assert.deepEqual(outcome,{status:'not-sent',text:'keep this exact text',reason:'history-pending'});
  assert.ok(known.events.some(event=>event[0]==='error'&&event[1]===expected));await known.controller.close();

  const unknown=fixture();unknown.api.input=async()=>{throw new MiraHttpError(409,null,'safe generic HTTP copy');};
  await unknown.controller.connect();const uncertain=await unknown.controller.input('do not restore on a generic conflict');
  assert.deepEqual(uncertain,{status:'unknown'});assert.ok(!unknown.events.some(event=>event[0]==='error'&&event[1]===expected));
  await unknown.controller.close();
});

test('central audition is blocked by active work, emits no session audio facts, and Stop revokes it synchronously',async()=>{
  const f=fixture();await f.controller.connect();assert.equal(f.controller.canAuditionReviewedAudio(),true);
  f.setPlaybackBusy(true);assert.equal(f.controller.canAuditionReviewedAudio(),false,'normal playback owns the shared sink');
  f.setPlaybackBusy(false);
  assert.equal(await f.controller.auditionReviewedAudio(new Uint8Array([1,0,2,0]),16000),true);
  assert.equal(f.controller.canAuditionReviewedAudio(),false);assert.deepEqual(f.states,['starting','playing']);
  assert.equal(f.progress.length,0);assert.equal(f.events.some(event=>event[0]==='receipt'),false);
  const capture=fixture();await capture.controller.connect();await capture.controller.startMicrophone();
  assert.equal(capture.controller.canAuditionReviewedAudio(),false,'active capture blocks review playback');
  await capture.controller.close();
  await f.controller.input('newer synthetic input');
  assert.deepEqual(f.states,['starting','playing','stopped'],'new input cancels a playing preview');
  assert.equal(f.controller.canAuditionReviewedAudio(),false);
  await f.controller.stop();assert.equal(f.controller.canAuditionReviewedAudio(),true);
  assert.deepEqual(f.states,['starting','playing','stopped']);assert.equal(f.progress.length,0);
  assert.equal(await f.controller.auditionReviewedAudio(new Uint8Array([1,0,2,0]),16000),true);
  assert.equal(f.playbackBusy,true);await f.controller.close();
  assert.equal(f.playbackBusy,false,'close cancels a playing preview');
  assert.equal(f.controller.canAuditionReviewedAudio(),false);
  const closed=fixture();await closed.controller.connect();await closed.controller.close();
  assert.equal(closed.controller.canAuditionReviewedAudio(),false);

  const activeGrant={id:'speech-grant',kind:'speech',value:'synthetic',digest:'c'.repeat(64),output_epoch:1,activity_seq:1};
  const busy=fixture();await busy.controller.connect();busy.controller.install({...busy.current,revision:busy.current.revision+1,permit_revision:busy.current.permit_revision+1,
    phase:'thinking',sealed:false,active_grants:[activeGrant]});
  assert.equal(busy.controller.canAuditionReviewedAudio(),false);await busy.controller.close();
});
