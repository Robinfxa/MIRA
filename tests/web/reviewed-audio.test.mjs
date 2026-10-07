import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {ReviewedAudioPanel,parseReviewedAudioStatus}=await import(new URL('features/diagnostics/reviewed-audio.js',dist));
const {CancelSafePlayback}=await import(new URL('features/audio/playback.js',dist));
const tick=async()=>{for(let i=0;i<10;i++)await Promise.resolve();};
const pendingId='11111111-1111-4111-8111-111111111111';
const digest='a'.repeat(64),reviewId='b'.repeat(32);
const status=(patch={})=>({scope:'application',recording_active:false,has_pending_audio:false,staged_bytes:0,max_audio_bytes:512*1024,
  expires_in_seconds:0,pending_stream_id:null,pending_kind:null,input_completion_ready:false,notice:'safe notice',
  scope_notice:'范围：当前本地 MIRA 应用的全部已认证会话。',...patch});
const review=(patch={})=>({scope:'application',scope_notice:'范围：当前本地 MIRA 应用的全部已认证会话。',review_id:reviewId,
  digest,kind:'audio_input',sample_rate_hz:16000,byte_count:4,expires_in_seconds:30,
  preview_path:`/api/v1/sessions/session/reviewed-audio/reviews/${reviewId}/preview`,notice:'review exact raw bytes',...patch});
function deferred(){let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};}
class El{
  constructor(){this.listeners={};this.hidden=false;this.disabled=false;this.checked=false;this.textContent='';}
  addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
  fire(name){for(const fn of this.listeners[name]??[])fn({preventDefault(){}});}
}
function panelFixture({statusValue=status(),reviewValue=review(),previewValue={pcm16le:new Uint8Array([1,0,2,0]),sampleRateHz:16000,kind:'audio_input',digest},now=()=>1000,reviewDeferred=null}={}){
  const names=['notice','status','scope','eligibilityNotice','consent','enable','disable','review','clip','clipMetadata','preview','audition','auditionStatus','attestation','confirm','cancel','result'];
  const elements=Object.fromEntries(names.map(name=>[name,new El()]));
  const calls={mode:[],reviews:[],previews:0,confirms:[],auditions:0,stops:0};
  let currentStatus=statusValue;
  let currentTime=now();
  const api={
    reviewedAudioStatus:async()=>currentStatus,
    setReviewedAudioRecording:async(enabled,consent)=>{calls.mode.push({enabled,consent});currentStatus=status({recording_active:enabled});return {ok:true,recording_active:enabled,accepted_for_queue:false,code:'recording_state_changed',message:'safe',scope_notice:'app-wide'};},
    requestReviewedAudioReview:async streamId=>{calls.reviews.push(streamId);if(reviewDeferred)return reviewDeferred.promise;return reviewValue;},
    reviewedAudioPreview:async()=>{calls.previews++;return {pcm16le:previewValue.pcm16le.slice(),sampleRateHz:previewValue.sampleRateHz,kind:previewValue.kind,digest:previewValue.digest};},
    confirmReviewedAudio:async(_review,body)=>{calls.confirms.push(body);currentStatus=status({recording_active:true});return {ok:true,recording_active:true,accepted_for_queue:true,code:'queued_private_local',message:'queued',scope_notice:'app-wide'};},
  };
  const audition={auditionReviewedAudio:async()=>{calls.auditions++;return true;},stopReviewedAudioAudition:()=>{calls.stops++;}};
  const timers=new Map();let timerId=0;
  const instance=new ReviewedAudioPanel(api,audition,elements,{now:()=>currentTime,setTimeout:(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId;},clearTimeout:id=>timers.delete(id)});
  return {instance,elements,calls,api,timers,setStatus(value){currentStatus=value;},advance(ms){currentTime+=ms;for(const [id,timer] of [...timers])if(timer.ms<=ms){timers.delete(id);timer.fn();}else timer.ms-=ms;},close(){instance.close();}};
}

test('reviewed audio status strictly requires owner-scoped pending identity and the server transcript binding',()=>{
  const pending=status({recording_active:true,has_pending_audio:true,staged_bytes:4,max_audio_bytes:512*1024,expires_in_seconds:10,
    pending_stream_id:pendingId,pending_kind:'audio_input',input_completion_ready:true});
  assert.equal(parseReviewedAudioStatus(pending).input_completion_ready,true);
  for(const invalid of [null,{}, {...pending,unexpected:'private'}, {...pending,pending_stream_id:'foreign'},
    {...pending,input_completion_ready:'true'}, {...pending,has_pending_audio:false,input_completion_ready:true},
    {...pending,pending_stream_id:null}, {...pending,staged_bytes:1}, {...pending,expires_in_seconds:0}])
    assert.throws(()=>parseReviewedAudioStatus(invalid));
});

test('mode enable requires an explicit app-wide consent checkbox and can be explicitly switched off',async()=>{
  const f=panelFixture();f.instance.setCanEnable(true);f.instance.start();await tick();
  f.elements.enable.fire('click');await tick();assert.equal(f.calls.mode.length,0);assert.match(f.elements.result.textContent,/勾选明确同意/);
  f.elements.consent.checked=true;f.elements.consent.fire('change');f.elements.enable.fire('click');await tick();await tick();
  assert.deepEqual(f.calls.mode,[{enabled:true,consent:true}]);assert.match(f.elements.notice.textContent,/全部已认证会话/);
  f.elements.disable.fire('click');await tick();await tick();
  assert.deepEqual(f.calls.mode.at(-1),{enabled:false,consent:false});assert.equal(f.elements.consent.checked,false);
  f.close();
});

test('a failed status refresh clears the clip but preserves a last-known active warning and global off control',async()=>{
  const active=status({recording_active:true,has_pending_audio:true,staged_bytes:4,expires_in_seconds:30,pending_stream_id:pendingId,pending_kind:'audio_input'});
  const f=panelFixture({statusValue:active});f.instance.start();await tick();f.elements.review.fire('click');await tick();assert.equal(f.elements.clip.hidden,false);
  f.api.reviewedAudioStatus=async()=>{throw new Error('synthetic transport detail');};await f.instance.refresh();
  assert.equal(f.elements.clip.hidden,true);assert.equal(f.elements.review.hidden,true);assert.equal(f.elements.notice.hidden,false);
  assert.equal(f.elements.disable.hidden,false);assert.equal(f.elements.enable.disabled,true);
  assert.ok(!f.elements.notice.textContent.includes('synthetic transport detail'));f.close();
});

test('exact clip must be loaded and fully auditioned before matching-digest private queue confirmation',async()=>{
  const active=status({recording_active:true,has_pending_audio:true,staged_bytes:4,expires_in_seconds:30,pending_stream_id:pendingId,pending_kind:'audio_input'});
  const f=panelFixture({statusValue:active});f.instance.setCanEnable(true);f.instance.start();await tick();
  f.elements.review.fire('click');await tick();
  assert.equal(f.calls.reviews[0],pendingId);assert.equal(f.elements.clip.hidden,false);
  assert.match(f.elements.clipMetadata.textContent,/麦克风输入.*16000 Hz.*0.00 秒.*SHA-256/);
  assert.match(f.elements.result.textContent,/ASR 转写不能替代试听/);
  f.elements.confirm.fire('click');await tick();assert.equal(f.calls.confirms.length,0);
  f.elements.preview.fire('click');await tick();assert.equal(f.calls.auditions,0);assert.equal(f.elements.audition.hidden,false);
  f.elements.audition.fire('click');await tick();assert.equal(f.calls.auditions,1);
  f.instance.auditionState('playing');f.instance.auditionState('completed');
  assert.equal(f.elements.attestation.disabled,false);assert.equal(f.elements.confirm.disabled,true);
  f.elements.attestation.checked=true;f.elements.attestation.fire('change');assert.equal(f.elements.confirm.disabled,false);
  f.elements.confirm.fire('click');await tick();await tick();
  assert.deepEqual(f.calls.confirms,[{reviewed_digest:digest,review:'approved',persist_consent:true}]);
  assert.match(f.elements.result.textContent,/排入本机私有诊断队列/);assert.match(f.elements.result.textContent,/不证明已写入磁盘/);
  assert.equal(f.elements.clip.hidden,true);f.close();
});

test('digest mismatch, owner change, expiry, Stop and close erase the preview and revoke audition actions',async()=>{
  const active=status({recording_active:true,has_pending_audio:true,staged_bytes:4,expires_in_seconds:2,pending_stream_id:pendingId,pending_kind:'audio_input'});
  const f=panelFixture({statusValue:active,reviewValue:review({expires_in_seconds:2}),previewValue:{pcm16le:new Uint8Array([1,0,2,0]),sampleRateHz:16000,kind:'audio_input',digest:'c'.repeat(64)},now:()=>1000});
  f.instance.start();await tick();f.elements.review.fire('click');await tick();f.elements.preview.fire('click');await tick();
  assert.equal(f.elements.confirm.hidden,false);assert.equal(f.elements.audition.disabled,true);assert.match(f.elements.result.textContent,/不会进入保存确认/);
  // A refreshed owner identity revokes any displayed ticket and preview actions.
  f.setStatus(status({recording_active:true,has_pending_audio:true,staged_bytes:4,expires_in_seconds:20,
    pending_stream_id:'22222222-2222-4222-8222-222222222222',pending_kind:'audio_output'}));
  await f.instance.refresh();assert.equal(f.elements.clip.hidden,true);assert.ok(f.calls.stops>=1);
  // Return to a current ticket; expiry clears all local PCM and buttons.
  f.setStatus(active);await f.instance.refresh();f.elements.review.fire('click');await tick();
  f.api.reviewedAudioPreview=async()=>({pcm16le:new Uint8Array([1,0,2,0]),sampleRateHz:16000,kind:'audio_input',digest});
  f.elements.preview.fire('click');await tick();assert.equal(f.elements.audition.disabled,false);
  f.advance(2000);assert.equal(f.elements.clip.hidden,true);assert.equal(f.elements.confirm.hidden,true);assert.equal(f.elements.attestation.checked,false);
  f.instance.invalidateForStop();assert.equal(f.elements.review.hidden,true);
  f.close();assert.equal(f.elements.audition.disabled,true);
});

test('a stale review response after newer input is discarded and never authorizes a later save',async()=>{
  const active=status({recording_active:true,has_pending_audio:true,staged_bytes:4,expires_in_seconds:30,pending_stream_id:pendingId,pending_kind:'audio_input'});
  const pending=deferred(),f=panelFixture({statusValue:active,reviewDeferred:pending});f.instance.start();await tick();
  f.elements.review.fire('click');await tick();
  const settle=f.instance.invalidateForNewInput();
  f.setStatus(status({recording_active:true}));pending.resolve(review());await tick();
  assert.equal(f.elements.clip.hidden,true);assert.equal(f.calls.confirms.length,0);
  settle();await tick();assert.equal(f.elements.review.hidden,true);f.close();
});

test('central CancelSafePlayback auditions reviewed PCM without character facts and stops on normal audio, Stop and close',async()=>{
  const sources=[],facts=[],states=[];
  const context={destination:{},resume:async()=>{},close:async()=>{},createBuffer:(_channels,length,rate)=>({length,rate,samples:new Float32Array(length),getChannelData(){return this.samples;}}),
    createBufferSource:()=>{const source={buffer:null,onended:null,started:0,stopped:0,disconnected:0,connect(){},disconnect(){this.disconnected++;},start(){this.started++;},stop(){this.stopped++;}};sources.push(source);return source;}};
  const sink=new CancelSafePlayback({isAuthorized:()=>true,onFact:fact=>facts.push(fact),onAuditionState:state=>states.push(state),createContext:()=>context});
  const samples=new Int16Array([-32768,32767]);assert.equal(await sink.audition(samples,16000),true);
  assert.equal(sink.quiescent,false);assert.equal(sources[0].buffer.rate,16000);assert.deepEqual([...sources[0].buffer.samples],[-1,32767/32768]);
  assert.equal(facts.length,0);assert.deepEqual(states,['starting','playing']);
  const normal=sink.open({id:'speech',digest,activity_seq:1,output_epoch:1});assert.ok(normal);
  assert.equal(sources[0].stopped,1);assert.equal(sources[0].disconnected,1);assert.equal(facts.length,0);
  normal.push(new Int16Array([2]));await tick();assert.equal(facts.some(fact=>fact.stage==='submitted'),true);
  sink.stop('stop');assert.equal(facts.at(-1).stage,'stopped');assert.deepEqual(states,['starting','playing','stopped']);
  assert.equal(await sink.audition(new Int16Array([1]),16000),true);const last=sources.at(-1);await sink.close();
  assert.equal(last.stopped,1);assert.ok(last.disconnected);assert.equal(sink.quiescent,false);assert.equal(facts.length,2);
});

test('audition is refused while character playback owns the sink and after a stale asynchronous resume',async()=>{
  let finishResume;const resume=new Promise(resolve=>finishResume=resolve);const sources=[],states=[];
  const context={destination:{},resume:()=>resume,close:async()=>{},createBuffer:(_channels,length,rate)=>({getChannelData:()=>new Float32Array(length),rate}),
    createBufferSource:()=>{const source={onended:null,buffer:null,started:0,stopped:0,connect(){},disconnect(){},start(){this.started++;},stop(){this.stopped++;}};sources.push(source);return source;}};
  const sink=new CancelSafePlayback({isAuthorized:()=>true,onAuditionState:state=>states.push(state),createContext:()=>context});
  const stream=sink.open({id:'speech',digest,activity_seq:1,output_epoch:1});
  assert.equal(await sink.audition(new Int16Array([1]),16000),false);assert.equal(states.length,0);
  sink.stop();
  // A fresh sink makes the resume pending before Stop invalidates it.
  const pendingSink=new CancelSafePlayback({isAuthorized:()=>true,onAuditionState:state=>states.push(state),createContext:()=>context});
  const play=pendingSink.audition(new Int16Array([1]),16000);pendingSink.stop('stop');finishResume();
  assert.equal(await play,false);assert.equal(sources.length,0);assert.deepEqual(states,['starting','stopped']);
});

test('review UI stays secondary, default-off and separate from export, with exact-buffer privacy copy',async()=>{
  const html=await (await import('node:fs/promises')).readFile(new URL('../../apps/web/index.html',import.meta.url),'utf8');
  const panelStart=html.indexOf('data-review-audio-panel'),fieldset=html.indexOf('<fieldset class="conversation-controls"');
  assert.ok(panelStart>fieldset, "recording controls are secondary to the conversation");
  assert.ok(html.indexOf('<details class="settings-panel"') < panelStart, "recording controls remain in settings");
  assert.match(html,/data-review-audio-panel[^>]*>/);
  assert.match(html,/data-review-audio-notice[^>]*hidden/);assert.match(html,/data-review-audio-consent/);
  assert.match(html,/ASR 转写不是隐私审核/);assert.match(html,/试听这段原音/);assert.match(html,/排入本机私有队列/);
  assert.match(html,/未能自动做秘密检测|不会自动做秘密检测/);assert.ok(!/data-review-audio.*export/i.test(html));
});
