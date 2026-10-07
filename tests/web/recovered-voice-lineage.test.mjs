import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {Node,parseHtml} from './helpers/recovered-lineage-dom.mjs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST ?? 'apps/web/dist')+'/');
const {ContinuousListeningController: ActualContinuous}=await import(new URL('features/session/continuous-listening.js',dist));
const {SessionController: ActualController}=await import(new URL('features/session/controller.js',dist));
const {SceneEffectExecutor: ActualScene}=await import(new URL('features/presentation/scene-executor.js',dist));
const {CancelSafePlayback}=await import(new URL('features/audio/playback.js',dist));
const {mountConversationArchive: actualArchive}=await import(new URL('features/session/conversation-archive.js',dist));
const {mountOperatorPairing: actualPairing}=await import(new URL('features/session/operator-pairing.js',dist));
const {MiraHttpError}=await import(new URL('features/session/api-client.js',dist));
const html=await readFile(new URL('../../apps/web/index.html',import.meta.url),'utf8');
const main=(await readFile(new URL('app/main-source.js',dist),'utf8')).replace(/^import .*;\n/gm,'');
const tick=()=>new Promise(r=>setImmediate(r));
const settle=async()=>{for(let i=0;i<8;i++)await tick();};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const archiveStatus=(patch={})=>({enabled:true,persistence_status:'enabled_no_committed_records',management_enabled:true,recall_session_id:null,current_session_id:null,selection_locked:false,recipients:'Synthetic selected provider + JEV',speech_enabled:true,recall_authorized:false,google_authorized:false,...patch});
const entry={entry_id:'synthetic-entry',source_version:1,stage:'accepted_input',active:true,text:'Synthetic original <img>',output_epoch:1,request_id:'old-input',input_source:'text',effect_kind:null,rendered_samples:null,sample_rate_hz:null,audio_status:null,forget_event_id:null};
function harness({paired=false,photoDecode=null,connectFailure=false,factDrainTimeoutMs=1500,speechText=null,commitBarrier=null}={}){
 const document=parseHtml(html),window=new Node('window');document.body=document.querySelector('body');document.defaultView=window;document.visibilityState='visible';document.createElement=t=>new Node(t);
 document.body.dataset.characterRenderer='code-native-review';
 if(paired){document.body.dataset.operatorPairing='required';document.body.dataset.conversationArchive='enabled';}
 const node=s=>{const n=document.querySelector(s);assert.ok(n,'actual HTML selector '+s);return n;};
 const image=node('[data-photo] img');Object.assign(image,{complete:true,naturalWidth:600,naturalHeight:460,decode:()=>photoDecode?.promise??Promise.resolve()});
 const requests=[];const calls=[],receipts=[],audioFacts=[],streams=[],sources=[],fetches=[],operations=[];let client,revision=0,current,controller,continuous,scene,archive,pairing,archiveRevision=3,failConnect=connectFailure,pairedNow=!paired,selectionLocked=false;
 const counts={captureStarts:0,captureStops:0,globalStops:0,continuousStops:0,creates:0,continuousCaptureStops:0};
 const state=(patch={})=>({schema_version:'0.1.0-foundation',session_id:'synthetic-session',client_instance_id:client,revision:++revision,permit_revision:revision,activity_seq:0,input_epoch:0,output_epoch:0,phase:'stopped',request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null,response_muted:false,response_mode:'voice',response_preference_revision:0,photo_visible:false,photo_visibility_revision:0,...patch});
 const api={
  async create(id){counts.creates++;if(failConnect)throw Error('synthetic failed connect');client=id;return {session:current=state(),session_token:'synthetic-only'};},
  async capabilities(){return {generation_mode:'injected',qualification:'unavailable',speech_enabled:true,microphone_enabled:true,continuous_listening_enabled:true};},
  snapshot(){return new Promise(()=>{});},
  async input(request){requests.push(request);calls.push(['input',request.text]);const a=request.activity_seq;const effects=[{id:'subtitle-'+a,kind:'subtitle',value:'Synthetic reply '+a,cue_id:'text-'+a,cue_speech_id:null},{id:'photo-'+a,kind:'media',value:'trip_photo',cue_id:'photo-cue-'+a,cue_speech_id:null},{id:'speech-'+a,kind:'speech',value:speechText??'Synthetic voice '+a,cue_id:'voice-'+a,cue_speech_id:'speech-'+a}].map(e=>({...e,digest:'a'.repeat(64),output_epoch:a,activity_seq:a}));
   const unmute=['可以开声音。','取消静音。','unmute'].includes(request.text);
   return current=state({activity_seq:a,input_epoch:a,output_epoch:a,phase:'ready',request_id:request.request_id,active_grants:effects,response_muted:unmute?false:current.response_muted,response_mode:unmute?'voice':current.response_mode,response_preference_revision:current.response_preference_revision+(unmute?1:0),photo_visibility_revision:current.photo_visibility_revision});},
  async receipt(value){receipts.push(value);return current;},async audioProgress(value){audioFacts.push(value);return current;},
  async speech(effect,signal,push){const done=deferred();streams.push({effect,signal,push,done});await done.promise;},
  async responsePreference(request){calls.push(['mute',request.muted]);return current=state({...current,revision:++revision,permit_revision:revision,response_muted:request.muted,response_mode:'text_only',response_preference_revision:current.response_preference_revision+1,active_grants:current.active_grants.filter(e=>e.kind!=='speech')});},
  async dismissPhoto(request){calls.push(['dismiss',request]);return {...current,photo_visible:false,photo_visibility_revision:request.expected_revision+1};},
  async stop(request){calls.push(['stop']);return current=state({activity_seq:request.activity_seq,response_muted:current.response_muted,response_mode:current.response_mode,response_preference_revision:current.response_preference_revision,photo_visibility_revision:current.photo_visibility_revision});},
  async close(){calls.push(['close']);},
 };
 let resumeGate=null;
 const context={destination:{},resume:async()=>{await resumeGate?.promise;},close:async()=>{},createBuffer:(_c,n)=>({getChannelData:()=>new Float32Array(n)}),createBufferSource:()=>{const s={onended:null,stopped:0,connect(){},disconnect(){},start(){},stop(){this.stopped++;}};sources.push(s);return s;}};
 class Controller extends ActualController{constructor(a,e,v,c,o){super(a,e,v,c,{...o,factDrainTimeoutMs,createPlayback:settings=>new CancelSafePlayback({...settings,createContext:()=>context}),createCapture:()=>({start:async()=>{counts.captureStarts++;return true;},stop(){counts.captureStops++;},close:async()=>{}}),onGlobalStop(reason){counts.globalStops++;o.onGlobalStop(reason);}});controller=this;}}
 class Scene extends ActualScene{constructor(root,options){super(root,{...options,mediaReadinessTimeoutMs:1000,characterRendererFactory:async()=>({prepareState:async()=>true,render(){},stop(){},destroy(){}})});scene=this;}}

 const continuousViews=[],commits=[],holds=[],endpoints=[],capturedFrames=[];let capture,observer,lease,asrRevision=0,sample=0,sequence=0,stableText="";
 class Continuous extends ActualContinuous {constructor(options){super({...options,
  createCapture:o=>{capture=o;return{start(){counts.captureStarts++;o.onState('recording');return Promise.resolve(true);},stop(){counts.continuousCaptureStops++;},async close(){}};},
  openStream:(id,signal,o)=>{lease=id;observer=o;return{ready:Promise.resolve({lease_id:id,sample_rate_hz:16000,max_seconds:120,max_samples:1920000,max_utterances:12,max_streams_per_session:4,max_total_streams:10,session_lease_starts_used:1,total_lease_starts_used:1,endpoint_mode:'google_vad_offsets_natural',manual_commit_required:false,client_endpoint_supported:true,client_silence_ms:700,drain_timeout_ms:2000,max_recognition_streams:4}),closed:new Promise(()=>{}),send(frame){capturedFrames.push(frame);},endpoint:(eid,end)=>endpoints.push({eid,end}),cancelEndpoint(){},
  commit:async(cid,rev,uid)=>{commits.push({cid,rev,uid});const text=uid?continuousViews.at(-1).transcript.text:stableText.trim();assert.ok(!uid||stableText.endsWith(text));await commitBarrier?.promise;stableText=uid?stableText.slice(0,-text.length):'';observer.onEvent({type:'transcript',lease_id:lease,revision:++asrRevision,text:stableText,is_final:false,...(uid?{committed_commit_id:cid,committed_utterance_id:uid}:{})});return{type:'commit_ready',lease_id:lease,commit_id:cid,revision:rev,utterance_id:uid,segment_seq:commits.length,text};},
  hold:async(uid,rev)=>{const text=continuousViews.at(-1).transcript.text;holds.push({uid,rev,text});return{type:'utterance_held',lease_id:lease,utterance_id:uid,revision:rev,text};},stop:async()=>{counts.continuousStops++;},cancel(){}};},
  onUpdate:v=>{continuousViews.push(v);options.onUpdate(v);}});continuous=this;}}
 const pcm=(level,n=1)=>{for(let i=0;i<n;i++){const data=new Int16Array(640).fill(level);capture.onChunk({pcm16le:new Uint8Array(data.buffer),sampleRate:16000,channels:1,sequence:sequence++,startSample:sample,endSample:sample+=640});}};
 const transcript=(text,final=false)=>{if(final)stableText=text;observer.onEvent({type:'transcript',lease_id:lease,revision:++asrRevision,text,is_final:final});};
 const finalize=(text,uid,begin=0)=>{const ep=endpoints.at(-1);assert.ok(ep,'captured quiet produced a real controller endpoint');observer.onEvent({type:'endpoint_status',lease_id:lease,endpoint_id:ep.eid,source_end_sample:ep.end,state:'completed'});observer.onEvent({type:'utterance_ready',lease_id:lease,utterance_id:uid,revision:asrRevision,text,begin_offset_samples:begin,end_offset_samples:ep.end,source_end_sample:ep.end,final_offset_samples:null,endpoint_basis:'client_silence_finalized',client_endpoint_id:ep.eid});};

 class Panel{recordingActive=false;start(){}close(){}setCanEnable(){}setContinuousListeningBlocked(){}invalidateForNewInput(){}invalidateForStop(){}auditionState(){}}
 const config={apiBase:'/api/v1',pollIntervalMs:999999};
 let operationHandler=async(_path,init)=>new Response(JSON.stringify({status:'committed',operation_id:JSON.parse(init.body).operation_id}),{status:200});
 const fetcher=async(path,init)=>{fetches.push({path,init});let value;
  if(path==='/api/v1/operator/status')value={required:true,paired:pairedNow,revoked:false};
  else if(path==='/api/v1/operator/pair'){pairedNow=true;return new Response(null,{status:204});}
  else if(path==='/api/v1/operator/revoke')return new Response(null,{status:204});
  else if(path.endsWith('/conversations/status'))value=archiveStatus({selection_locked:selectionLocked});
  else if(path.endsWith('/conversations/sessions'))value={revision:archiveRevision,sessions:['synthetic-old'],next_cursor:null};
  else if(path.includes('/conversations/entries?'))value={session_id:'synthetic-old',revision:archiveRevision,entries:[entry],next_cursor:null};
  else if(path.endsWith('/conversations/selection')){selectionLocked=true;value=archiveStatus({selection_locked:true,recall_session_id:JSON.parse(init.body).session_id});}
  else if(path.endsWith('/conversations/operations')){operations.push(init.body);return operationHandler(path,init);}
  else throw Error('Unexpected fixture request '+path);
  return new Response(JSON.stringify(value),{status:200});};
 vm.runInNewContext(main,{document,window,navigator:{mediaDevices:{getUserMedia(){throw Error('real capture forbidden');}}},globalThis:{AudioContext:class{},AudioWorkletNode:class{},isSecureContext:true},loadPublicConfig:()=>config,watchDiagnosticsStatus:()=>({close(){}}),recordingNotice:()=>({visible:false,text:'',state:'off'}),safeSessionError:()=> 'synthetic safe error',MiraApiClient:class{constructor(){return api;}},MiraHttpError,SessionController:Controller,ContinuousListeningController:Continuous,SceneEffectExecutor:Scene,ReviewedAudioPanel:Panel,mountConversationArchive(d,o){archive=actualArchive(d,{...o,fetcher});return archive;},mountOperatorPairing(d,o){pairing=actualPairing(d,{...o,fetcher});return pairing;}});
 return{set resumeGate(value){resumeGate=value;},node,document,window,api,calls,counts,requests,continuousViews,commits,holds,endpoints,capturedFrames,pcm,transcript,finalize,get lease(){return lease;},get sample(){return sample;},emit:e=>observer.onEvent(e),receipts,audioFacts,streams,sources,operations,fetches,image,get controller(){return controller;},get continuous(){return continuous;},get scene(){return scene;},get current(){return current;},get archive(){return archive;},get pairing(){return pairing;},set operationHandler(v){operationHandler=v;},set archiveRevision(v){archiveRevision=v;},connectSuccess(){failConnect=false;},
  send(text){const input=node('[name=message]');input.value=text;input.fire('input');input.fire('keydown',{key:'Enter'});},
  async start(){await settle();if(paired){node('[data-operator-pairing-code]').value='synthetic-code';node('[data-operator-pairing-form]').fire('submit');await settle();node('[data-archive-start]').fire('click');await settle();}},
  async close(){archive?.close();await controller?.close();await continuous?.close();scene?.close();await pairing?.close();await settle();},
 };
}

const U1='22345678-1234-4234-8234-123456789012',U2='32345678-1234-4234-8234-123456789012';
test('actual default voice interruption enables same-lease continuation without starting capture on page load', async () => {
 const h=harness();await h.start();try {
  const mode=h.node('[data-continuous-barge-mode]');
  assert.equal(mode.value,'headphones');
  assert.match(mode.textContent,/语音插话开启（建议耳机）/);
  assert.match(mode.textContent,/保守模式/);
  assert.equal(h.counts.captureStarts,0,'page load cannot start microphone capture');
  h.node('[data-continuous-listening]').fire('click');await settle();h.pcm(0,18);
  await h.controller.input('Plan a trip.');await settle();await h.streams[0].push(new Int16Array(160));await settle();
  assert.equal(h.controller.replyPcmBusy,true);const stopped=h.counts.continuousCaptureStops;
  h.pcm(1400,3);assert.equal(h.controller.replyPcmBusy,true);
  h.pcm(1400);assert.equal(h.controller.replyPcmBusy,false);
  assert.equal(h.counts.continuousCaptureStops,stopped);assert.equal(h.continuous.active,true);
  assert.equal(mode.disabled,true);h.transcript('Only two days.',true);h.pcm(0,18);
  h.finalize('Only two days.',U1);await settle();
  assert.equal(h.requests.length,2);assert.equal(h.requests[1].relation,'continuation');
  assert.equal(h.requests[1].continuation_of_request_id,h.requests[0].request_id);
  assert.equal(h.requests[1].listening_utterance_id,h.commits[0].cid);
  assert.equal(h.counts.captureStarts,1);assert.equal(h.continuous.active,true);
 }finally{await h.close();}
});
test('mode change never switches an active microphone lease in place or starts another', async () => {
 const h=harness();await h.start();try {
  const mode=h.node('[data-continuous-barge-mode]');mode.value='guarded';mode.fire('change');
  h.node('[data-continuous-listening]').fire('click');await settle();
  assert.equal(h.counts.captureStarts,1);assert.equal(h.continuous.active,true);
  mode.value='headphones';mode.fire('change');await settle();
  assert.equal(h.continuous.active,false);assert.equal(h.counts.captureStarts,1);
  assert.ok(h.counts.continuousCaptureStops>=1);
 }finally{await h.close();}
});
test('definitive history_pending rejection retains reviewed parent for a fresh manual retry', async () => {
 const h=await setup();try {
  await heldAfterInterrupt(h);restoreHeld(h);
  const original=h.api.input;const attempts=[];
  h.api.input=async request=>{attempts.push(request);if(attempts.length===1)
    throw new MiraHttpError(409,'history_pending','History is not yet saved.');return original(request);};
  submit(h);await settle();assert.equal(attempts.length,1);assert.equal(h.requests.length,1);
  assert.equal(h.node('[name=message]').value,'Only two days.');
  submit(h);await settle();assert.equal(attempts.length,2);
  assert.equal(h.requests.length,2);assert.equal(h.requests[1].relation,'continuation');
  assert.equal(h.requests[1].continuation_of_request_id,h.requests[0].request_id);
  assert.notEqual(attempts[1].request_id,attempts[0].request_id);
  assert.equal(h.requests[1].listening_utterance_id,undefined);
 }finally{await h.close();}
});
async function playing(){const h=harness();await h.start();h.node('[data-continuous-listening]').fire('click');return h;}
async function setup(options={}){const h=harness(options);await h.start();h.node('[data-continuous-barge-mode]').value='guarded';h.node('[data-continuous-barge-mode]').fire('change');assert.equal(h.continuous.start(),true);await settle();h.pcm(0,18);await h.controller.input('Plan a trip.');await settle();assert.equal(h.streams.length,1);await h.streams[0].push(new Int16Array(160));await settle();assert.equal(h.controller.replyPcmBusy,true);return h;}
async function heldAfterInterrupt(h){h.pcm(1200,4);h.transcript('Only two');assert.match(h.node('[data-continuous-preview]').textContent,/Only two/);const before=h.counts.continuousCaptureStops;h.node('[data-continuous-interrupt]').fire('click');assert.equal(h.continuous.active,true);assert.equal(h.counts.continuousCaptureStops,before);assert.equal(h.controller.replyPcmBusy,false);assert.match(h.node('[data-continuous-preview]').textContent,/Only two/);h.transcript('Only two days.',true);h.pcm(0,18);h.finalize('Only two days.',U1);await settle();assert.equal(h.holds.length,1);assert.equal(h.requests.length,1);assert.equal(h.continuous.active,true);assert.equal(h.continuousViews.at(-1).held_previews[0].text,'Only two days.');assert.match(h.node('[data-continuous-sent-text]').textContent,/Only two days/);}
test('reply-only interrupt preserves recognized overlap; later clean supplement commits once as continuation; Stop fences late original stream',async()=>{const h=await setup();try{await heldAfterInterrupt(h);const begin=h.sample;h.pcm(1200,4);h.transcript('Only two days. Also avoid flights.',true);h.pcm(0,18);h.finalize('Also avoid flights.',U2,begin);await settle();assert.equal(h.requests.length,2);assert.equal(h.requests[1].text,'Also avoid flights.');assert.equal(h.requests[1].relation,'continuation');assert.equal(h.requests[1].continuation_of_request_id,h.requests[0].request_id);assert.equal(h.requests[1].listening_utterance_id,h.commits[0].cid);const cid=h.commits[0].cid;h.emit({type:'utterance_revision',lease_id:h.lease,utterance_id:U2,commit_id:cid,revision:4,text:'Also avoid long flights.',reason:'late_result_after_submission',requires_review:true,submission_state:'accepted'});await settle();assert.equal(h.requests.length,2);assert.match(h.node('[data-continuous-sent-text]').textContent,/Also avoid long flights/);h.transcript('Unfinished third supplement',false);h.node('[data-stop]').fire('click');await settle();assert.equal(h.continuous.active,false);assert.match(h.node('[data-continuous-sent-text]').textContent,/Unfinished third supplement/);h.transcript('Late tail that must not resurrect',true);await settle();assert.equal(h.requests.length,2);assert.doesNotMatch(h.node('[data-continuous-sent-text]').textContent,/Late tail that must not resurrect/);}finally{await h.close();}});
test('held-overlap restore through actual composer preserves original-request linkage without inventing an ASR commit',async()=>{const h=await setup();try{await heldAfterInterrupt(h);const composer=h.node('[name=message]');composer.value='Existing user draft';const retained=h.node('[data-continuous-sent-text]').children.find(n=>n.textContent.includes('暂缓的语音预览'));assert.ok(retained);retained.querySelector('button').fire('click');assert.equal(composer.value,'Existing user draft');assert.equal(h.continuousViews.at(-1).held_previews.length,1);composer.value='';retained.querySelector('button').fire('click');assert.equal(composer.value,'Only two days.');h.node('form.composer').fire('submit');await settle();assert.equal(h.requests.length,2);assert.equal(h.requests[1].text,'Only two days.');assert.equal(h.requests[1].relation,'continuation','recovered supplement belongs to the interrupted request');assert.equal(h.requests[1].continuation_of_request_id,h.requests[0].request_id);assert.equal(h.requests[1].continuation_of_output_epoch,h.requests[0].activity_seq);assert.equal(h.requests[1].listening_utterance_id,undefined);assert.equal(h.continuous.active,false,'the documented composer path also ends continuous listening');}finally{await h.close();}});
test('manual current stable send after explicit interrupt retains original link; later ordinary new topic stays independent',async()=>{const h=await setup();try{h.pcm(1200,4);h.transcript('Only two days.',true);h.node('[data-continuous-interrupt]').fire('click');h.node('[data-continuous-send]').fire('click');await settle();assert.equal(h.requests.length,2);assert.equal(h.requests[1].relation,'continuation');assert.equal(h.requests[1].continuation_of_request_id,h.requests[0].request_id);assert.equal(h.continuous.active,true);h.send('Different topic: tell me about the moon.');await settle();assert.equal(h.requests.length,3);assert.equal(h.requests[2].relation,undefined);assert.equal(h.requests[2].continuation_of_request_id,undefined);assert.equal(h.continuous.active,false);}finally{await h.close();}});

function restoreHeld(h) {
 const row=h.node('[data-continuous-sent-text]').children.find(n=>n.textContent.includes('暂缓的语音预览'));
 assert.ok(row);row.querySelector('button').fire('click');return h.node('[name=message]');
}
function submit(h) {h.node('form.composer').fire('submit');}
test('edited recovered supplement visibly keeps its reviewed parent and never claims ASR authority',async()=>{
 const h=await setup();try{await heldAfterInterrupt(h);const input=restoreHeld(h);
 assert.match(h.node('[data-recovered-input-label]').textContent,/补充被打断/);
 input.value='Only three days, please.';input.fire('input');
 assert.match(h.node('[data-recovered-input-label]').textContent,/已修改.*仍作为/);
 submit(h);await settle();assert.equal(h.requests.length,2);assert.equal(h.requests[1].text,'Only three days, please.');
 assert.equal(h.requests[1].relation,'continuation');assert.equal(h.requests[1].continuation_of_request_id,h.requests[0].request_id);
 assert.equal(h.requests[1].listening_utterance_id,undefined);assert.equal(h.commits.length,0);
 }finally{await h.close();}
});
test('explicit new-topic choice detaches a recovered supplement',async()=>{
 const h=await setup();try{await heldAfterInterrupt(h);restoreHeld(h);h.node('[data-recovered-new-topic]').fire('click');
 assert.equal(h.node('[data-recovered-input-notice]').hidden,true);submit(h);await settle();
 assert.equal(h.requests.length,2);assert.equal(h.requests[1].relation,undefined);assert.equal(h.requests[1].continuation_of_request_id,undefined);
 }finally{await h.close();}
});
for(const action of ['newer-input'])test(`recovered target is not relinked after ${action}; text stays editable`,async()=>{
 const h=await setup();try{await heldAfterInterrupt(h);const original=h.continuousViews.at(-1).held_previews[0].continuation_target;assert.ok(original);
 if(action==='stop'){h.node('[data-stop]').fire('click');await settle();assert.equal(h.controller.captureReplyContinuation(),null);}
 else {await h.controller.input('An unrelated later request.');await settle();await h.streams.at(-1).push(new Int16Array(160));await settle();}
 const count=h.requests.length;const input=restoreHeld(h);submit(h);await settle();
 assert.equal(h.requests.length,count,'stale recovery cannot dispatch as a silently independent or wrong-parent request');
 assert.equal(input.value,'Only two days.');assert.match(h.node('[data-error]').textContent,/原请求已失效/);
 h.node('[data-recovered-new-topic]').fire('click');submit(h);await settle();assert.equal(h.requests.length,count+1);
 assert.equal(h.requests.at(-1).relation,undefined);
 }finally{await h.close();}
});
test('restoring requires exact lease utterance and revision; repeated click consumes only once',async()=>{
 const h=await setup();try{await heldAfterInterrupt(h);const p=h.continuousViews.at(-1).held_previews[0];
 assert.equal(h.continuous.restoreHeldInput(p.lease_id,p.utterance_id,p.revision-1),null);
 assert.equal(h.continuous.restoreHeldInput('different-lease',p.utterance_id,p.revision),null);
 const input=restoreHeld(h);assert.equal(h.continuous.restoreHeldInput(p.lease_id,p.utterance_id,p.revision),null);
 submit(h);submit(h);await settle();assert.equal(h.requests.length,2);assert.equal(input.value,'');
 }finally{await h.close();}
});
test('old source ranges stay tied to the captured turn when a newer reply exists before finalization',async()=>{
 const h=await setup();try{h.pcm(1200,4);h.transcript('Only two');h.node('[data-continuous-interrupt]').fire('click');
 const parent=h.requests[0].request_id;await h.controller.input('A newer independent request.');await settle();
 h.transcript('Only two days.',true);h.pcm(0,18);h.finalize('Only two days.',U1);await settle();
 assert.equal(h.continuousViews.at(-1).held_previews[0].continuation_target.requestId,parent);
 restoreHeld(h);submit(h);await settle();assert.equal(h.requests.length,2);assert.match(h.node('[data-error]').textContent,/原请求已失效/);
 }finally{await h.close();}
});
test('mixed playback parents require an explicit new-topic decision rather than choosing the latest reply',async()=>{
 const h=await setup();try{h.pcm(1200,4);h.transcript('Only two');h.node('[data-continuous-interrupt]').fire('click');
 h.pcm(0,18);await h.controller.input('A second reply.');await settle();await h.streams.at(-1).push(new Int16Array(160));await settle();
 h.pcm(1200,4);h.node('[data-continuous-interrupt]').fire('click');h.transcript('Only two days.',true);h.pcm(0,18);h.finalize('Only two days.',U1);await settle();
 assert.equal(h.continuousViews.at(-1).held_previews[0].continuation_target,undefined);restoreHeld(h);submit(h);await settle();
 assert.equal(h.requests.length,2);assert.match(h.node('[data-recovered-input-label]').textContent,/来源无法确定/);
 h.node('[data-recovered-new-topic]').fire('click');submit(h);await settle();assert.equal(h.requests.length,3);assert.equal(h.requests[2].relation,undefined);
 }finally{await h.close();}
});
test('same-value cloned or foreign-controller target is not an issued continuation capability',async()=>{
 const h=await setup(),other=harness();try{await other.start();await heldAfterInterrupt(h);const p=h.continuousViews.at(-1).held_previews[0];
 assert.equal((await h.controller.input(p.text,undefined,undefined,{...p.continuation_target})).reason,'continuation-stale');
 assert.equal((await other.controller.input(p.text,undefined,undefined,p.continuation_target)).reason,'continuation-stale');
 assert.equal(h.requests.length,1);assert.equal(other.requests.length,0);
 }finally{await h.close();await other.close();}
});
test('reviewed recovery waits for the interrupted playback receipt before dispatch',async()=>{
 const h=await setup(),fact=deferred();try{h.api.audioProgress=async value=>{h.audioFacts.push(value);await fact.promise;return h.current;};
 await heldAfterInterrupt(h);restoreHeld(h);submit(h);await settle();assert.equal(h.requests.length,1);
 assert.ok(h.audioFacts.some(f=>f.status==='interrupted'));fact.resolve();await settle();assert.equal(h.requests.length,2);
 assert.equal(h.requests[1].presentation_cutoff,h.audioFacts.at(-1).presentation_seq);
 assert.equal(h.requests[1].relation,'continuation');
 }finally{fact.resolve();await h.close();}
});
for(const reason of ['max_duration','permission_lost'])test(`${reason} keeps held text and rejects late callback resurrection`,async()=>{
 const h=await setup();try{await heldAfterInterrupt(h);h.emit({type:'stopped',lease_id:h.lease,reason});await settle();
 assert.equal(h.continuous.active,false);assert.equal(h.requests.length,1);
 h.emit({type:'transcript',lease_id:h.lease,revision:999,text:'Late stale replacement',is_final:true});await settle();
 assert.equal(h.continuousViews.at(-1).held_previews[0].text,'Only two days.');assert.equal(h.requests.length,1);
 }finally{await h.close();}
});
test('Close rejects a retained target and cannot revive original playback or dispatch',async()=>{
 const h=await setup();try{await heldAfterInterrupt(h);const p=h.continuousViews.at(-1).held_previews[0];
 await h.controller.close();assert.equal((await h.controller.input(p.text,undefined,undefined,p.continuation_target)).status,'closed');
 await assert.rejects(h.streams[0].push(new Int16Array(160)),/Speech cancelled/);assert.equal(h.requests.length,1);assert.equal(h.sources.length,1);
 }finally{await h.close();}
});

test('Stop during composer teardown cancels old send but a fresh click continues the accepted parent',async()=>{
 const h=await setup(),ending=deferred();try{await heldAfterInterrupt(h);const input=restoreHeld(h);
 const realStop=h.continuous.stop.bind(h.continuous);h.continuous.stop=async reason=>{await realStop(reason);await ending.promise;};
 submit(h);await settle();h.node('[data-stop]').fire('click');ending.resolve();await settle();
 assert.equal(input.value,'Only two days.');assert.equal(h.requests.length,1);assert.equal(h.node('[data-recovered-input-notice]').hidden,false);
 submit(h);await settle();assert.equal(h.requests.length,2);assert.equal(h.requests[1].relation,'continuation');assert.equal(h.requests[1].continuation_of_request_id,h.requests[0].request_id);
 }finally{ending.resolve();await h.close();}
});

for(const stage of ['before-restore','after-restore'])test(`Stop ${stage} retains reviewed parent for a fresh manual Send`,async()=>{
 const h=await setup();try{await heldAfterInterrupt(h);const parent=h.requests[0].request_id;
 if(stage==='after-restore')restoreHeld(h);h.node('[data-stop]').fire('click');await settle();
 assert.equal(h.requests.length,1);assert.equal(h.controller.captureReplyContinuation(),null,'Stop cannot sample old playback anew');
 if(stage==='before-restore')restoreHeld(h);submit(h);await settle();
 assert.equal(h.requests.length,2);assert.equal(h.requests[1].relation,'continuation');assert.equal(h.requests[1].continuation_of_request_id,parent);
 assert.equal(h.requests[1].continuation_of_output_epoch,1);assert.equal(h.requests[1].listening_utterance_id,undefined);
 assert.ok(h.requests[1].activity_seq>2);assert.equal(h.continuous.active,false);
 }finally{await h.close();}
});
for(const finish of ['completed','muted'])test(`captured held source remains a valid reviewed parent after reply ${finish}`,async()=>{
 const h=await setup();try{h.pcm(1200,4);h.transcript('Only two');const target=h.controller.captureReplyContinuation();assert.ok(target);
 if(finish==='completed'){h.streams[0].done.resolve();await settle();h.sources[0].onended();await settle();}
 else await h.controller.setOutputMuted(true);
 assert.equal(h.controller.replyPcmBusy,false);assert.equal(h.controller.captureReplyContinuation(),null,'no live speech target can be sampled now');
 h.transcript('Only two days.',true);h.pcm(0,18);h.finalize('Only two days.',U1);await settle();
 assert.equal(h.continuousViews.at(-1).held_previews[0].continuation_target,target);
 restoreHeld(h);submit(h);await settle();assert.equal(h.requests.length,2);assert.equal(h.requests[1].relation,'continuation');
 assert.equal(h.requests[1].continuation_of_request_id,target.requestId);assert.equal(h.requests[1].listening_utterance_id,undefined);
 }finally{await h.close();}
});
test('Stop during receipt drain cancels old send and preserves the exact draft for a fresh Send',async()=>{
 const h=await setup(),fact=deferred();try{h.api.audioProgress=async value=>{h.audioFacts.push(value);await fact.promise;return h.current;};
 await heldAfterInterrupt(h);const input=restoreHeld(h);submit(h);await settle();assert.equal(h.requests.length,1);
 h.node('[data-stop]').fire('click');await settle();fact.resolve();await settle();assert.equal(h.requests.length,1);
 assert.equal(input.value,'Only two days.');assert.equal(h.node('[data-recovered-input-notice]').hidden,false);
 submit(h);await settle();assert.equal(h.requests.length,2);assert.equal(h.requests[1].relation,'continuation');
 assert.equal(h.requests[1].continuation_of_request_id,h.requests[0].request_id);
 }finally{fact.resolve();await h.close();}
});
test('receipt timeout before dispatch retains source metadata and a fresh retry waits for the same facts',async()=>{
 const h=await setup({factDrainTimeoutMs:15}),fact=deferred(),failed=deferred();try{
 h.api.audioProgress=async value=>{h.audioFacts.push(value);await fact.promise;return h.current;};
 await heldAfterInterrupt(h);const originalInput=h.controller.input.bind(h.controller);
 h.controller.input=async(...args)=>{const result=await originalInput(...args);failed.resolve(result);return result;};
 const input=restoreHeld(h);submit(h);assert.equal((await failed.promise).reason,'history-timeout');await settle();
 assert.equal(h.requests.length,1);assert.equal(input.value,'Only two days.');assert.equal(h.node('[data-recovered-input-notice]').hidden,false);
 fact.resolve();await settle();submit(h);await settle();assert.equal(h.requests.length,2);
 assert.equal(h.requests[1].relation,'continuation');assert.equal(h.requests[1].continuation_of_request_id,h.requests[0].request_id);
 assert.equal(h.requests[1].presentation_cutoff,h.audioFacts.at(-1).presentation_seq);
 }finally{fact.resolve();await h.close();}
});
test('a failed receipt still blocks retries without discarding the reviewed source',async()=>{
 const h=await setup();try{h.api.audioProgress=async()=>{throw new Error('Synthetic failed receipt');};
 await heldAfterInterrupt(h);const p=h.continuousViews.at(-1).held_previews[0];h.controller.prepareInputFromGesture();
 const first=await h.controller.input(p.text,undefined,undefined,p.continuation_target);assert.equal(first.reason,'history-failed');
 const retry=await h.controller.input(p.text,undefined,undefined,p.continuation_target);assert.equal(retry.reason,'history-failed','retry must reach the unchanged fact barrier, not lose lineage');
 assert.equal(h.requests.length,1);
 }finally{await h.close();}
});
test('dispatch of a newer input invalidates old source even before its response settles',async()=>{
 const h=await setup(),accepted=deferred(),dispatched=deferred();try{await heldAfterInterrupt(h);const p=h.continuousViews.at(-1).held_previews[0];
 h.api.input=async request=>{h.requests.push(request);dispatched.resolve();await accepted.promise;return h.current;};
 const newer=h.controller.input('New independent input');await dispatched.promise;await h.controller.stop();
 assert.equal((await h.controller.input(p.text,undefined,undefined,p.continuation_target)).reason,'continuation-stale');
 assert.equal(h.requests.length,2);accepted.resolve();await newer;
 }finally{accepted.resolve();await h.close();}
});

test('actual explicit voice-interruption off rejects speaker overlap and keeps the same lease', async () => {
 const h=harness();await h.start();try {
  const mode=h.node('[data-continuous-barge-mode]');mode.value='guarded';mode.fire('change');
  assert.equal(h.counts.captureStarts,0);h.node('[data-continuous-listening]').fire('click');await settle();h.pcm(0,18);
  await h.controller.input('Plan a trip.');await settle();await h.streams[0].push(new Int16Array(160));await settle();
  h.pcm(1400,12);assert.equal(h.controller.replyPcmBusy,true);assert.equal(h.continuousViews.at(-1).barge_in_mode,'guarded');
  assert.equal(h.counts.captureStarts,1);assert.equal(h.continuous.active,true);assert.equal(h.commits.length,0);
  h.node('[data-continuous-interrupt]').fire('click');assert.equal(h.controller.replyPcmBusy,false);assert.equal(h.continuous.active,true);
 }finally{await h.close();}
});

test('actual rapid-burst pause keeps manual interruption usable and explicit resume cannot replay old supplements', async () => {
 const h=harness();await h.start();try {
  h.node('[data-continuous-listening]').fire('click');await settle();
  for (let i=0;i<3;i++) {
   h.pcm(0,18);await h.controller.input('Synthetic separate turn '+i);await settle();
   await h.streams.at(-1).push(new Int16Array(160));await settle();h.pcm(1400,4);
  }
  assert.equal(h.continuousViews.at(-1).barge_in_suspended,true);
  const button=h.node('[data-continuous-interrupt]');assert.equal(button.disabled,false);assert.equal(button.hidden,false);
  assert.match(button.textContent,/恢复语音插话/);assert.match(h.node('[data-continuous-status]').textContent,/短时间内连续触发/);
  h.pcm(0,18);await h.controller.input('Another response while auto paused');await settle();
  const currentStream=h.streams.at(-1);await currentStream.push(new Int16Array(160));await settle();
  assert.equal(h.controller.replyPcmBusy,true);assert.equal(h.continuousViews.at(-1).barge_in_suspended,true);
  const before=h.requests.length;button.fire('click');await settle();
  assert.equal(h.controller.replyPcmBusy,false,'resume button still manually stops the current reply');
  assert.equal(h.continuousViews.at(-1).barge_in_suspended,false);assert.equal(h.continuousViews.at(-1).barge_in_available,true);
  assert.equal(h.counts.captureStarts,1);assert.equal(h.counts.continuousCaptureStops,0);assert.equal(h.continuous.active,true);
  assert.equal(h.requests.length,before);assert.equal(h.commits.length,0,'resuming grants no submission authority');
  await assert.rejects(currentStream.push(new Int16Array(160)), /Speech cancelled/);await settle();assert.equal(h.controller.replyPcmBusy,false,'late old PCM cannot revive after manual resume');
 }finally{await h.close();}
});

async function automaticReply(options={}) {
 const h=harness(options);await h.start();h.continuous.start();await settle();h.pcm(0,18);
 await h.controller.input('Plan a trip.');await settle();
 await h.streams[0].push(new Int16Array(160).fill(1700));await settle();return h;
}
test('qualified interruption carries a soft prefix into late final exactly once with its original parent',async()=>{
 const h=await automaticReply();try{
  const begin=h.sample,original=h.requests[0].request_id,lease=h.lease;
  h.pcm(250,2);h.transcript('等一下');h.pcm(1400,4);
  assert.equal(h.controller.replyPcmBusy,false);assert.ok(h.sources[0].stopped);
  h.transcript('等一下,等一下。只去两天。',true);h.pcm(0,18);
  h.finalize('等一下,等一下。只去两天。',U1,begin);await settle();
  assert.equal(h.requests.length,2,'the same phrase that stopped Mira must auto-submit');
  assert.equal(h.requests[1].text,'等一下,等一下。只去两天。');
  assert.equal(h.requests[1].continuation_of_request_id,original);assert.equal(h.requests[1].relation,'continuation');
  assert.equal(h.holds.length,0);assert.equal(h.counts.captureStarts,1);assert.equal(h.lease,lease);
  const commit=h.commits[0];h.emit({type:'utterance_revision',lease_id:lease,utterance_id:U1,commit_id:commit.cid,
   revision:10,text:'等一下，只去三天。',reason:'late_result_after_submission',requires_review:true,submission_state:'accepted'});
  await settle();assert.equal(h.requests.length,2);assert.equal(h.continuousViews.at(-1).sent_text[0].correction.text,'等一下，只去三天。');
 }finally{await h.close();}
});
test('identical captured sound and recognized Mira words remain source-ambiguous with automatic interruption enabled',async()=>{
 const outcomes=[];
 for(const label of ['user repeats Mira','possible self echo']) {
  const h=await automaticReply({speechText:'等一下，等一下。'});try{
   const begin=h.sample;h.pcm(1400,4);assert.equal(h.controller.replyPcmBusy,false);
   h.transcript('等一下,等一下。',true);h.pcm(0,18);h.finalize('等一下,等一下。',U1,begin);await settle();
   outcomes.push({inputs:h.requests.length,text:h.requests.at(-1).text,holds:h.holds.length});
   assert.equal(h.requests.length,2,label+' supplies identical observations, not identity proof');
  }finally{await h.close();}
 }
 assert.deepEqual(outcomes[0],outcomes[1]);
});
test('queued PCM before source start does not taint the user phrase and cannot start after interruption',async()=>{
 const h=harness(),resume=deferred();await h.start();try{
  h.continuous.start();await settle();h.pcm(0,18);await h.controller.input('Plan a trip.');await settle();
  h.resumeGate=resume;await h.streams[0].push(new Int16Array(160).fill(1700));await settle();
  assert.equal(h.sources.length,0);assert.equal(h.controller.replyPlaybackBusy,true);
  assert.equal(h.controller.replyPcmBusy,false,'accepted queue bytes are not submitted playback');
  const begin=h.sample;h.pcm(250,2);h.pcm(1400,4);h.transcript('等一下，只去两天。',true);h.pcm(0,18);
  h.resumeGate=null;resume.resolve();await settle();assert.equal(h.sources.length,0,'cancelled pending resume cannot start old sound');
  h.finalize('等一下，只去两天。',U1,begin);await settle();
  assert.equal(h.requests.length,2);assert.equal(h.requests[1].relation,'continuation');assert.equal(h.holds.length,0);
 }finally{resume.resolve();await h.close();}
});
for(const timing of ['before final','during commit'])test('new unrelated turn '+timing+' cannot inherit or be stopped by delayed interruption text',async()=>{
 const barrier=timing==='during commit'?deferred():null,h=await automaticReply({commitBarrier:barrier});
 try{
  const begin=h.sample;h.pcm(250,2);h.pcm(1400,4);h.transcript('Only two days.',true);h.pcm(0,18);
  if(timing==='during commit'){h.finalize('Only two days.',U1,begin);await settle();assert.equal(h.commits.length,1);}
  await h.controller.input('A completely different request.');await settle();
  const nextStream=h.streams.at(-1);await nextStream.push(new Int16Array(160).fill(1700));await settle();
  if(timing==='before final')h.finalize('Only two days.',U1,begin);else barrier.resolve();
  await settle();assert.equal(h.requests.length,2);assert.equal(h.controller.replyPcmBusy,true,'new reply is not interrupted by old text');
  const latest=h.continuousViews.at(-1);assert.ok(latest.held_previews.some(x=>x.text==='Only two days.')||latest.sent_text.some(x=>x.text==='Only two days.'&&x.state==='not_sent'));
 }finally{barrier?.resolve();await h.close();}
});

test('recognition child rotation preserves confirmed interruption and contiguous PCM without renewing budgets',async()=>{
 const h=await automaticReply();try{
  const begin=h.sample,initial={...h.continuousViews.at(-1).ready};h.pcm(250,3);h.pcm(1400,4);
  h.emit({type:'recognition_status',lease_id:h.lease,stream_index:2,state:'listening',stt_requests_used:2,stt_requests_remaining:2});
  h.pcm(1100,5);h.transcript('等一下，等一下，还有一个要求。',true);h.pcm(0,18);
  h.finalize('等一下，等一下，还有一个要求。',U1,0);await settle();
  assert.equal(h.requests.length,2);assert.equal(h.counts.captureStarts,1);assert.equal(h.counts.continuousCaptureStops,0);
  assert.deepEqual({...h.continuousViews.at(-1).ready},initial);
  let offset=0;for(const [sequence,frame] of h.capturedFrames.entries()){
   assert.equal(frame.sequence,sequence);assert.equal(frame.startSample,offset);offset=frame.endSample;
   assert.equal(frame.endSample-frame.startSample,frame.pcm16le.length/2);
  }
  assert.equal(offset,h.sample);assert.ok(begin>0);
 }finally{await h.close();}
});
for(const action of ['stop','close','permission_lost'])test('confirmed interruption late final cannot survive '+action,async()=>{
 const h=await automaticReply();try{
  const begin=h.sample;h.pcm(250,2);h.pcm(1400,4);h.transcript('等一下，还有要求。',true);h.pcm(0,18);
  if(action==='stop')await h.controller.stop();else if(action==='close')await h.controller.close();
  else h.emit({type:'stopped',lease_id:h.lease,reason:'permission_lost'});
  h.finalize('等一下，还有要求。',U1,begin);await settle();
  assert.equal(h.requests.length,1);assert.equal(h.commits.length,0);assert.equal(h.continuous.active,false);
  assert.ok(h.continuousViews.at(-1).previous_previews.some(p=>p.text==='等一下，还有要求。'));
 }finally{await h.close();}
});

for(const prefixFrames of [5,6,10,25])test('confirmed uninterrupted soft prefix of '+prefixFrames*40+' ms keeps the entire phrase',async()=>{
 const h=await automaticReply();try{
  const begin=h.sample;h.pcm(250,prefixFrames);h.transcript('等一下');h.pcm(1400,4);h.pcm(1100,5);
  h.transcript('等一下，等一下，还有一个要求。',true);h.pcm(0,18);h.finalize('等一下，等一下，还有一个要求。',U1,begin);await settle();
  assert.equal(h.requests.length,2);assert.equal(h.requests[1].text,'等一下，等一下，还有一个要求。');
  assert.equal(h.holds.length,0);assert.equal(h.counts.captureStarts,1);
 }finally{await h.close();}
});

test('one finalized interruption preserves a soft first phrase and its 240ms internal pause',async()=>{
 const h=await automaticReply();try{
  const begin=h.sample;h.pcm(250,3);h.transcript('等一下');h.pcm(0,6);h.pcm(1400,4);
  assert.equal(h.controller.replyPcmBusy,false);h.transcript('等一下，等一下。',true);h.pcm(0,18);
  h.finalize('等一下，等一下。',U1,begin);await settle();
  assert.equal(h.requests.length,2);assert.equal(h.requests[1].text,'等一下，等一下。');
  assert.equal(h.requests[1].continuation_of_request_id,h.requests[0].request_id);assert.equal(h.holds.length,0);
 }finally{await h.close();}
});
