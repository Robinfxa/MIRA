import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {BrowserAudioTransport}=await import(new URL('features/session/audio-transport.js',dist));
const {ContinuousListeningController}=await import(new URL('features/session/continuous-listening.js',dist));
const leaseId='12345678-1234-4234-8234-123456789012';
const commitId='22345678-1234-4234-8234-123456789012';
const ready=(changes={})=>({type:'ready',lease_id:leaseId,sample_rate_hz:16000,max_seconds:2,max_samples:32000,
  max_utterances:2,max_streams_per_session:4,max_total_streams:8,session_lease_starts_used:1,
  total_lease_starts_used:1,endpoint_mode:'google_vad_offsets_manual_commit',manual_commit_required:true,...changes});
const chunk=(sequence=0,startSample=0,pcm16le=new Uint8Array([0,0,0,0]))=>({pcm16le,sampleRate:16000,channels:1,
  sequence,startSample,endSample:startSample+pcm16le.length/2,captureSampleRate:48000,sourceSampleRate:null,captureStartFrame:sequence*4800});
class Socket {readyState=0;bufferedAmount=0;onopen=null;onmessage=null;onerror=null;onclose=null;sent=[];closed=false;
  send(text){this.sent.push(JSON.parse(text));} close(){this.closed=true;this.readyState=3;} open(){this.readyState=1;this.onopen?.({});}
  message(value){this.onmessage?.({data:JSON.stringify(value)});} }
function browserTransport(extra={}){const socket=new Socket(),events=[],errors=[];let url;
  const api=new BrowserAudioTransport({apiBase:'/api/v1',pollIntervalMs:200},()=>({sessionId:'session-1',token:'session-secret'}),
    {createSocket:address=>{url=address;return socket;},baseUrl:'https://mira.test/',...extra});
  const stream=api.continuousListening(leaseId,new AbortController().signal,{onEvent:event=>events.push(event),onError:error=>errors.push(error)});
  return {api,socket,stream,events,errors,get url(){return url;}};
}
async function openReady(h,changes={}){h.socket.open();const first=h.socket.sent[0];h.socket.message(ready(changes));await h.stream.ready;return first;}

test('continuous websocket keeps token in its first frame, streams silence with contiguous samples, and manually commits exact revision',async()=>{
  const h=browserTransport();
  try {
    const first=await openReady(h);
    assert.equal(h.url,'wss://mira.test/api/v1/sessions/session-1/continuous-listening');
    assert.equal(new URL(h.url).search,'');assert.equal(first.type,'start');assert.equal(first.lease_id,leaseId);
    assert.equal(first.session_token,'session-secret');assert.equal(h.url.includes('session-secret'),false);
    h.stream.send(chunk());h.stream.send(chunk(1,2));
    const audio=h.socket.sent.filter(frame=>frame.type==='audio');
    assert.deepEqual(audio.map(frame=>[frame.sequence,frame.first_sample,frame.pcm_base64]),[[1,0,'AAAAAA=='],[2,2,'AAAAAA==']]);
    h.socket.message({type:'transcript',lease_id:leaseId,revision:7,text:'recognized suffix',is_final:true});
    const pending=h.stream.commit(commitId,7);assert.deepEqual(h.socket.sent.at(-1),{type:'commit',lease_id:leaseId,commit_id:commitId,revision:7});
    const accepted={type:'commit_ready',lease_id:leaseId,commit_id:commitId,segment_seq:1,revision:7,text:'stable confirmed suffix'};
    h.socket.message(accepted);assert.deepEqual(await pending,accepted);
    assert.equal(h.events.filter(event=>event.type==='commit_ready').length,1);
    const stopped=h.stream.stop('user_stop');assert.deepEqual(h.socket.sent.at(-1),{type:'stop',lease_id:leaseId,reason:'user_stop'});
    h.socket.message({type:'stopped',lease_id:leaseId,reason:'user_stop'});await stopped;await h.stream.closed;
    assert.equal(h.errors.length,0);
  } finally {h.api.close();}
});

test('stale commit is returned to the click caller, and transport never retries it',async()=>{
  const h=browserTransport();
  try {await openReady(h);const pending=h.stream.commit(commitId,2);
    const rejected={type:'commit_rejected',lease_id:leaseId,commit_id:commitId,reason:'stale_revision',current_revision:3};
    h.socket.message(rejected);assert.deepEqual(await pending,rejected);
    assert.equal(h.socket.sent.filter(frame=>frame.type==='commit').length,1);
    assert.equal(h.events.filter(event=>event.type==='commit_rejected').length,1);
    await h.stream.stop();h.socket.message({type:'stopped',lease_id:leaseId,reason:'user_stop'});
  } finally {h.api.close();}
});

test('abort fences late transcript and commit replies and settles outstanding commit',async()=>{
  const socket=new Socket(),events=[],abort=new AbortController();
  const api=new BrowserAudioTransport({apiBase:'/api/v1',pollIntervalMs:200},()=>({sessionId:'session-1',token:'secret'}),
    {createSocket:()=>socket,baseUrl:'https://mira.test/'});
  const stream=api.continuousListening(leaseId,abort.signal,{onEvent:event=>events.push(event),onError:()=>{}});
  socket.open();socket.message(ready());await stream.ready;const pending=assert.rejects(stream.commit(commitId,1));
  abort.abort();await pending;assert.equal(socket.closed,true);
  socket.message({type:'transcript',lease_id:leaseId,revision:2,text:'late',is_final:true});
  socket.message({type:'commit_ready',lease_id:leaseId,commit_id:commitId,segment_seq:1,revision:1,text:'late'});
  assert.equal(events.some(event=>event.type==='transcript'||event.type==='commit_ready'),false);api.close();
});

test('readiness rejects undeclared, oversized, or non-manual protocol limits',async()=>{
  for(const changes of [{max_seconds:291},{max_samples:32001},{manual_commit_required:false},{max_utterances:33}]){
    const h=browserTransport(),rejected=assert.rejects(h.stream.ready,/validation|readiness/i);
    try {h.socket.open();h.socket.message(ready(changes));await rejected;assert.equal(h.socket.closed,true);assert.equal(h.events.some(event=>event.type==='ready'),false);}
    finally {h.api.close();}
  }
});

for(const maximum of [8,9,10,100])test(`application readiness accepts declared lease-start ceiling ${maximum}`,async()=>{
  const h=browserTransport();
  try {
    await openReady(h,{max_total_streams:maximum,stt_requests_used:0,stt_requests_remaining:maximum});
    const value=await h.stream.ready;
    assert.equal(value.max_total_streams,maximum);
    assert.equal(value.stt_requests_remaining,maximum);
    assert.equal(h.errors.length,0);
    assert.equal(h.socket.sent.filter(frame=>frame.type==='start').length,1);
  } finally {h.api.close();}
});

for(const maximum of [0,101,1.5,'100',-1,'NaN'])test(`application readiness rejects invalid lease-start ceiling ${String(maximum)} (${typeof maximum})`,async()=>{
  const h=browserTransport(),rejected=assert.rejects(h.stream.ready,/validation|readiness/i);
  try {
    h.socket.open();h.socket.message(ready({max_total_streams:maximum}));await rejected;
    assert.equal(h.socket.closed,true);
    assert.equal(h.events.some(event=>event.type==='ready'),false);
  } finally {h.api.close();}
});

test('finite duration cap is visible, sends one stop, and does not roll into a new stream',async()=>{
  const timers=new Map();let next=0,creates=0;const socket=new Socket(),events=[];
  const api=new BrowserAudioTransport({apiBase:'/api/v1',pollIntervalMs:200},()=>({sessionId:'session-1',token:'secret'}),
    {createSocket:()=>{creates++;return socket;},baseUrl:'https://mira.test/',
      setTimeout:(fn,ms)=>{const id=++next;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id)});
  const stream=api.continuousListening(leaseId,new AbortController().signal,{onEvent:event=>events.push(event),onError:()=>{}});
  socket.open();socket.message(ready({max_seconds:1,max_samples:16000}));await stream.ready;
  const finite=[...timers.values()].find(timer=>timer.ms===1000);assert.ok(finite);finite.fn();
  assert.equal(events.at(-1).type,'stopped');assert.equal(events.at(-1).reason,'max_duration');
  assert.deepEqual(socket.sent.at(-1),{type:'stop',lease_id:leaseId,reason:'user_stop'});assert.equal(creates,1);
  socket.message({type:'stopped',lease_id:leaseId,reason:'max_duration'});await stream.closed;
  assert.equal(creates,1);api.close();
});

function fakeContinuous(options={}){
  const calls=[],updates=[],submissions=[],events=[];let captureOptions,stream,commitResolver,resolveClosed,idIndex=0;
  const capture={start:()=>{calls.push('capture-start');captureOptions.onState('recording');return options.captureStart?.()??Promise.resolve(true);},
    stop:()=>calls.push('capture-stop'),close:async()=>calls.push('capture-close')};
  const controller=new ContinuousListeningController({createCapture:value=>{captureOptions=value;return capture;},
    openStream:(id,signal,observers)=>{calls.push(['open',id]);const closed=new Promise(resolve=>{resolveClosed=resolve;});stream={ready:options.ready??Promise.resolve(ready()),closed,
      send:value=>calls.push(['audio',value]),commit:(commitId,revision)=>{calls.push(['commit',commitId,revision]);return new Promise(resolve=>{commitResolver=resolve;});},
      stop:reason=>{calls.push(['stream-stop',reason]);resolveClosed?.();return Promise.resolve();},cancel:()=>{calls.push('stream-cancel');resolveClosed?.();}};
      events.push(observers);return stream;},
    submitInput:async(text,id)=>{calls.push(['submit',text,id]);submissions.push([text,id]);return options.outcome??{status:'submitted'};},
    canStart:options.canStart??(()=>true),createId:options.createId??(()=>[leaseId,commitId,'32345678-1234-4234-8234-123456789012'][idIndex++]??'42345678-1234-4234-8234-123456789012'),
    onPhase:value=>calls.push(['phase',value]),onUpdate:value=>updates.push(value)});
  return {controller,calls,updates,submissions,events,get stream(){return stream;},get captureOptions(){return captureOptions;},
    resolveCommit(value){commitResolver(value);}};
}
const finalReady=(commitIdValue=commitId,revision=2,text='stable final words')=>({type:'commit_ready',lease_id:leaseId,
  commit_id:commitIdValue,segment_seq:1,revision,text});

test('continuous capture sends silence and provisional text stays unsent until manual commit-ready',async()=>{
  const h=fakeContinuous();assert.equal(h.controller.start(),true);assert.deepEqual(h.calls[0],'capture-start');
  await Promise.resolve();assert.equal(h.controller.active,true);
  h.captureOptions.onChunk(chunk());assert.equal(h.calls.filter(call=>Array.isArray(call)&&call[0]==='audio').length,1);
  h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:1,text:'still changing',is_final:false});
  assert.equal(h.updates.at(-1).transcript.text,'still changing');assert.equal(h.updates.at(-1).transcript.can_send,false);assert.equal(h.submissions.length,0);
  h.events[0].onEvent({type:'endpoint_pending',lease_id:leaseId,revision:2,text:'final words',reason:'missing_result_offset',can_submit_manually:true});
  assert.equal(h.updates.at(-1).transcript.can_send,true);
  const sending=h.controller.sendCurrent();await Promise.resolve();assert.deepEqual(h.calls.find(call=>Array.isArray(call)&&call[0]==='commit'),['commit',commitId,2]);
  assert.equal(h.submissions.length,0,'a commit click must wait for the backend-approved exact text');
  h.resolveCommit(finalReady());await sending;await Promise.resolve();
  assert.deepEqual(h.submissions,[["stable final words",commitId]]);assert.equal(h.controller.active,true);
  assert.equal(h.calls.includes('capture-stop'),false,'manual send keeps the microphone lease open');
  assert.equal(h.updates.at(-1).sent_text[0].state,'sent');
  await h.controller.stop();assert.equal(h.controller.active,false);assert.ok(h.calls.includes('capture-stop'));
});

test('stale revision requires another explicit click and current late tail remains visible',async()=>{
  const h=fakeContinuous();h.controller.start();await Promise.resolve();
  h.events[0].onEvent({type:'endpoint_pending',lease_id:leaseId,revision:3,text:'old pending',reason:'unmatched_activity_end',can_submit_manually:true});
  const click=h.controller.sendCurrent();await Promise.resolve();
  h.resolveCommit({type:'commit_rejected',lease_id:leaseId,commit_id:commitId,reason:'stale_revision',current_revision:4});
  await click;assert.equal(h.submissions.length,0);assert.match(h.updates.at(-1).notice,/转写刚更新/);
  h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:5,text:'late tail preserved',is_final:true});
  assert.equal(h.updates.at(-1).transcript.text,'late tail preserved');assert.equal(h.updates.at(-1).transcript.can_send,true);
  assert.equal(h.calls.filter(call=>Array.isArray(call)&&call[0]==='commit').length,1,'no automatic retry after a stale commit');
  await h.controller.stop();
});

test('exact server current revision is manually retryable whether it arrives before or after stale rejection',async t=>{
  for(const order of ['before','after'])await t.test(order,async()=>{
    const h=fakeContinuous();h.controller.start();await Promise.resolve();
    h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:3,text:'old stable',is_final:true});
    const staleClick=h.controller.sendCurrent();await Promise.resolve();
    if(order==='before')h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:4,text:'current stable',is_final:true});
    h.resolveCommit({type:'commit_rejected',lease_id:leaseId,commit_id:commitId,reason:'stale_revision',current_revision:4});
    await staleClick;
    if(order==='after')h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:4,text:'current stable',is_final:true});
    assert.equal(h.updates.at(-1).transcript.revision,4);
    assert.equal(h.updates.at(-1).transcript.can_send,true,'server-confirmed current revision should be eligible only after a fresh user click');
    assert.equal(h.submissions.length,0,'a stale response must never auto-submit');
    const retry=h.controller.sendCurrent();await Promise.resolve();
    const commits=h.calls.filter(call=>Array.isArray(call)&&call[0]==='commit');
    assert.equal(commits.length,2);assert.deepEqual(commits[1],['commit','32345678-1234-4234-8234-123456789012',4]);
    h.resolveCommit(finalReady('32345678-1234-4234-8234-123456789012',4,'current stable'));
    await retry;assert.deepEqual(h.submissions,[['current stable','32345678-1234-4234-8234-123456789012']]);
    await h.controller.stop();
  });
});

test('permission loss, transport error, explicit Stop and Close release capture and fence late events',async()=>{
  for(const finish of ['permission','transport','stop','close']){
    const h=fakeContinuous();h.controller.start();await Promise.resolve();
    if(finish==='permission')h.captureOptions.onError({code:'permission-denied',message:'permission denied'});
    else if(finish==='transport')h.events[0].onError(new Error('disconnect'));
    else if(finish==='stop')await h.controller.stop();
    else await h.controller.close();
    h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:99,text:'stale callback',is_final:true});
    assert.equal(h.controller.active,false);assert.equal(h.updates.at(-1).transcript,null);
    assert.ok(h.calls.includes('capture-stop'));
  }
});

test('close while permission is pending stops a late capture result and never reopens the mic',async()=>{
  let resolvePermission;const permission=new Promise(resolve=>{resolvePermission=resolve;});
  const h=fakeContinuous({captureStart:()=>permission,ready:new Promise(()=>{})});h.controller.start();
  await h.controller.close();resolvePermission(true);await Promise.resolve();
  assert.equal(h.controller.active,false);assert.equal(h.calls.includes('capture-stop'),true);assert.equal(h.updates.at(-1).state,'closed');
});

test('manual send cap ends visibly without rollover',async()=>{
  const h=fakeContinuous();h.controller.start();await Promise.resolve();
  h.events[0].onEvent({type:'endpoint_pending',lease_id:leaseId,revision:1,text:'one',reason:'missing_result_offset',can_submit_manually:true});
  const one=h.controller.sendCurrent();await Promise.resolve();h.resolveCommit(finalReady(commitId,1,'one'));await one;await Promise.resolve();
  h.events[0].onEvent({type:'endpoint_pending',lease_id:leaseId,revision:2,text:'two',reason:'missing_result_offset',can_submit_manually:true});
  const two=h.controller.sendCurrent();await Promise.resolve();
  h.resolveCommit(finalReady('32345678-1234-4234-8234-123456789012',2,'two'));
  // The fake ready permits two accepted commits; the second finishes the lease.
  await two;await Promise.resolve();
  assert.equal(h.controller.active,false);assert.equal(h.updates.at(-1).state,'limit');
  assert.equal(h.calls.filter(call=>Array.isArray(call)&&call[0]==='open').length,1);
});

test('last accepted commit survives delayed input-barrier submission and natural terminal ordering',async()=>{
  let releaseInput;
  const inputBarrier=new Promise(resolve=>{releaseInput=resolve;});
  const h=fakeContinuous({ready:Promise.resolve(ready({max_utterances:1})),outcome:inputBarrier});
  h.controller.start();await Promise.resolve();
  h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:1,text:'last stable words',is_final:true});
  const send=h.controller.sendCurrent();await Promise.resolve();
  h.resolveCommit(finalReady(commitId,1,'server accepted last stable words'));
  // The API input may remain behind SessionController's receipt-prefix barrier.
  await Promise.resolve();await Promise.resolve();
  assert.deepEqual(h.submissions,[['server accepted last stable words',commitId]]);
  assert.equal(h.controller.active,false,'the physical mic stops immediately at the declared count cap');
  assert.equal(h.updates.at(-1).state,'limit');
  assert.equal(h.calls.includes('capture-stop'),true);
  assert.equal(h.calls.some(call=>Array.isArray(call)&&call[0]==='stream-stop'),false,
    'natural exhaustion must not send a second user_stop that can revoke the accepted ID');
  // Real backend ordering is commit_ready followed by stopped(utterance_limit).
  h.events[0].onEvent({type:'stopped',lease_id:leaseId,reason:'utterance_limit'});
  assert.equal(h.calls.some(call=>Array.isArray(call)&&call[0]==='stream-stop'),false);
  releaseInput({status:'submitted'});await send;
  assert.equal(h.updates.at(-1).sent_text[0].state,'sent','late receipt completion must update the preserved snapshot');
});

test('terminal utterance_limit immediately after commit-ready cannot drop the accepted manual send',async()=>{
  const h=fakeContinuous({ready:Promise.resolve(ready({max_utterances:1}))});
  h.controller.start();await Promise.resolve();
  h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:1,text:'accepted before cap',is_final:true});
  const send=h.controller.sendCurrent();await Promise.resolve();
  // Model commit_ready resolving its waiter followed by stopped delivered before
  // the controller's async continuation is scheduled.
  h.resolveCommit(finalReady(commitId,1,'accepted before cap'));
  h.events[0].onEvent({type:'stopped',lease_id:leaseId,reason:'utterance_limit'});
  await send;
  assert.deepEqual(h.submissions,[['accepted before cap',commitId]],
    'a natural backend terminal after commit_ready must preserve the one accepted click');
  assert.equal(h.controller.active,false);assert.equal(h.updates.at(-1).state,'limit');
  assert.equal(h.calls.some(call=>Array.isArray(call)&&call[0]==='stream-stop'),false);
});

test('explicit Stop and Close while commit approval is pending fence the later accepted frame',async t=>{
  for(const action of ['stop','close'])await t.test(action,async()=>{
    const h=fakeContinuous();h.controller.start();await Promise.resolve();
    h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:1,text:`do not send after ${action}`,is_final:true});
    const send=h.controller.sendCurrent();await Promise.resolve();
    const closing=action==='stop'?h.controller.stop():h.controller.close();
    h.resolveCommit(finalReady(commitId,1,`stale after explicit ${action}`));
    await Promise.all([send,closing]);
    assert.equal(h.submissions.length,0);
    if(action==='stop')assert.deepEqual(h.calls.find(call=>Array.isArray(call)&&call[0]==='stream-stop'),['stream-stop','user_stop']);
    else assert.equal(h.updates.at(-1).state,'closed');
  });
});

test('Stop then Start retains prior provisional preview while the new lease waits for its own transcript',async()=>{
  const h=fakeContinuous();h.controller.start();await Promise.resolve();
  h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:3,text:'prior still-unsubmitted tail',is_final:false});
  await h.controller.stop();
  assert.equal(h.updates.at(-1).transcript,null);
  assert.equal(h.updates.at(-1).previous_previews[0].text,'prior still-unsubmitted tail');
  assert.match(h.updates.at(-1).previous_previews[0].hint,/上次聆听.*不会自动发送/);

  h.controller.start();await Promise.resolve();
  const lease2=h.calls.filter(call=>Array.isArray(call)&&call[0]==='open').at(-1)[1];
  assert.notEqual(lease2,leaseId);
  assert.equal(h.controller.active,true);
  assert.equal(h.updates.at(-1).transcript,null,'no old lease transcript is treated as current');
  assert.equal(h.updates.at(-1).previous_previews[0].text,'prior still-unsubmitted tail');
  await h.controller.sendCurrent();
  assert.equal(h.submissions.length,0,'a previous lease preview is never submitted by the active Send button');
  h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:99,text:'late old event',is_final:true});
  assert.equal(h.updates.at(-1).transcript,null,'late old-lease callbacks stay fenced');
  h.events[1].onEvent({type:'transcript',lease_id:lease2,revision:1,text:'new lease words',is_final:true});
  assert.equal(h.updates.at(-1).transcript.text,'new lease words');
  const send=h.controller.sendCurrent();await Promise.resolve();
  h.resolveCommit({type:'commit_ready',lease_id:lease2,commit_id:'32345678-1234-4234-8234-123456789012',
    segment_seq:1,revision:1,text:'new lease words'});
  await send;
  assert.deepEqual(h.submissions,[['new lease words','32345678-1234-4234-8234-123456789012']]);
  assert.equal(h.updates.at(-1).previous_previews[0].lease_id,leaseId);
  assert.equal(h.controller.restorePreviousPreview(leaseId),'prior still-unsubmitted tail');
  assert.equal(h.submissions.length,1,'restoring a previous preview never submits it');
  assert.deepEqual(h.updates.at(-1).previous_previews,[]);
  await h.controller.stop();
});

test('previous preview retention is bounded without eviction and blocks restart until a manual restore',async()=>{
  const h=fakeContinuous();
  for(let index=1;index<=4;index++){
    assert.equal(h.controller.start(),true);await Promise.resolve();
    const lease=h.calls.filter(call=>Array.isArray(call)&&call[0]==='open').at(-1)[1];
    h.events.at(-1).onEvent({type:'transcript',lease_id:lease,revision:1,text:`retained ${index}`,is_final:false});
    await h.controller.stop();
  }
  const retained=h.updates.at(-1).previous_previews;
  assert.equal(retained.length,4);assert.deepEqual(retained.map(item=>item.text),['retained 1','retained 2','retained 3','retained 4']);
  const captures=h.calls.filter(call=>call==='capture-start').length;
  assert.equal(h.controller.start(),false,'full preview history blocks another permission request');
  assert.match(h.updates.at(-1).notice,/预览已满 4 段.*空文字框/);
  assert.equal(h.updates.at(-1).previous_previews.length,4,'no historical preview is silently evicted');
  assert.equal(h.calls.filter(call=>call==='capture-start').length,captures);
  assert.equal(h.controller.restorePreviousPreview(retained[0].lease_id),'retained 1');
  assert.equal(h.controller.start(),true,'user-controlled restoration frees one history slot');
  await h.controller.stop();
});

test('definitively not-sent committed text remains visibly recoverable; unknown result never retries',async()=>{
  const missed=fakeContinuous({outcome:{status:'not-sent',text:'stable words',reason:'history-timeout'}});
  missed.controller.start();await Promise.resolve();
  missed.events[0].onEvent({type:'endpoint_pending',lease_id:leaseId,revision:1,text:'pending text',reason:'missing_result_offset',can_submit_manually:true});
  const pendingSend=missed.controller.sendCurrent();await Promise.resolve();
  missed.resolveCommit(finalReady(commitId,1,'stable words'));await pendingSend;
  assert.equal(missed.updates.at(-1).sent_text[0].state,'not_sent');assert.match(missed.updates.at(-1).sent_text[0].notice,/手动发送/);
  assert.equal(missed.updates.at(-1).sent_text[0].text,'stable words');await missed.controller.stop();

  const unknown=fakeContinuous({outcome:{status:'unknown'}});unknown.controller.start();await Promise.resolve();
  unknown.events[0].onEvent({type:'endpoint_pending',lease_id:leaseId,revision:1,text:'maybe accepted',reason:'missing_result_offset',can_submit_manually:true});
  const uncertainSend=unknown.controller.sendCurrent();await Promise.resolve();
  unknown.resolveCommit(finalReady(commitId,1,'maybe accepted'));await uncertainSend;
  assert.equal(unknown.updates.at(-1).sent_text[0].state,'unknown');assert.match(unknown.updates.at(-1).sent_text[0].notice,/不会自动重发/);
  assert.equal(unknown.calls.filter(call=>Array.isArray(call)&&call[0]==='submit').length,1);await unknown.controller.stop();
});

test('a new lease clears current preview, preserves old tail separately, and submits only its own transcript',async()=>{
  const h=fakeContinuous();h.controller.start();await Promise.resolve();
  h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:3,text:'older provisional tail',is_final:false});
  await h.controller.stop();
  assert.equal(h.updates.at(-1).transcript,null);
  assert.equal(h.updates.at(-1).previous_previews.length,1);
  assert.equal(h.updates.at(-1).previous_previews[0].can_send,false);
  assert.match(h.updates.at(-1).previous_previews[0].hint,/不会自动发送/);

  h.controller.start();await Promise.resolve();
  const lease2=h.calls.filter(call=>Array.isArray(call)&&call[0]==='open').at(-1)[1];
  assert.notEqual(lease2,leaseId);assert.equal(h.updates.at(-1).transcript,null);
  await h.controller.sendCurrent();
  assert.equal(h.calls.filter(call=>Array.isArray(call)&&call[0]==='commit').length,0,
    'the old lease preview cannot be committed from the new lease');
  h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:99,text:'late old callback',is_final:true});
  assert.equal(h.updates.at(-1).transcript,null,'old lease callbacks cannot update the new preview');
  h.events[1].onEvent({type:'transcript',lease_id:lease2,revision:1,text:'new lease words',is_final:true});
  assert.equal(h.updates.at(-1).transcript.text,'new lease words');
  const send=h.controller.sendCurrent();await Promise.resolve();
  h.resolveCommit({type:'commit_ready',lease_id:lease2,commit_id:'32345678-1234-4234-8234-123456789012',
    segment_seq:1,revision:1,text:'new lease words'});
  await send;
  assert.deepEqual(h.submissions,[['new lease words','32345678-1234-4234-8234-123456789012']]);
  assert.equal(h.controller.restorePreviousPreview(leaseId),'older provisional tail');
  assert.equal(h.submissions.length,1,'restore is only a copy operation, never a submission');
  assert.deepEqual(h.updates.at(-1).previous_previews,[]);
  await h.controller.stop();
});

test('retained preview list is bounded, never evicts silently, and blocks restart when full',async()=>{
  const h=fakeContinuous();
  for(let index=1;index<=4;index++){
    assert.equal(h.controller.start(),true);await Promise.resolve();
    const lease=h.calls.filter(call=>Array.isArray(call)&&call[0]==='open').at(-1)[1];
    h.events.at(-1).onEvent({type:'transcript',lease_id:lease,revision:1,text:`pending ${index}`,is_final:false});
    await h.controller.stop();
  }
  const previous=h.updates.at(-1).previous_previews;
  assert.equal(previous.length,4);assert.deepEqual(previous.map(item=>item.text),['pending 1','pending 2','pending 3','pending 4']);
  const captureStarts=h.calls.filter(call=>call==='capture-start').length;
  assert.equal(h.controller.start(),false);
  assert.match(h.updates.at(-1).notice,/预览已满 4 段.*空文字框/);
  assert.deepEqual(h.updates.at(-1).previous_previews.map(item=>item.text),['pending 1','pending 2','pending 3','pending 4']);
  assert.equal(h.calls.filter(call=>call==='capture-start').length,captureStarts);
  assert.equal(h.controller.restorePreviousPreview(previous[0].lease_id),'pending 1');
  assert.equal(h.controller.start(),true,'a manual restore frees a history slot');
  await h.controller.stop();
});

test('same-revision endpoint hint cannot replace an observed interim tail before terminal settlement',async()=>{
  const h=fakeContinuous();h.controller.start();await Promise.resolve();
  h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:2,text:'稳定前缀临时尾巴',is_final:false});
  h.events[0].onEvent({type:'endpoint_pending',lease_id:leaseId,revision:2,text:'稳定前缀',reason:'unmatched_activity_end',can_submit_manually:true});
  assert.equal(h.updates.at(-1).transcript.text,'稳定前缀临时尾巴');
  assert.equal(h.updates.at(-1).transcript.is_final,false);
  assert.equal(h.submissions.length,0);
  h.events[0].onEvent({type:'stopped',lease_id:leaseId,reason:'provider_stream_ended'});
  assert.equal(h.updates.at(-1).transcript,null);
  assert.equal(h.updates.at(-1).previous_previews.at(-1).text,'稳定前缀临时尾巴');
  assert.equal(h.submissions.length,0);
  await h.controller.close();
});

test('endpoint hint does not downgrade same-revision finality or untruncate a richer preview',async()=>{
  for(const isFinal of [false,true]){
    const h=fakeContinuous();h.controller.start();await Promise.resolve();
    h.events[0].onEvent({type:'transcript',lease_id:leaseId,revision:3,text:'长'.repeat(2001),is_final:isFinal});
    h.events[0].onEvent({type:'endpoint_pending',lease_id:leaseId,revision:3,text:'长',reason:'missing_result_offset',can_submit_manually:true});
    const view=h.updates.at(-1).transcript;
    assert.equal(view.text,'长'.repeat(2000));assert.equal(view.truncated,true);
    assert.equal(view.is_final,isFinal);assert.equal(view.can_send,false);
    assert.equal(h.submissions.length,0);await h.controller.close();
  }
});
