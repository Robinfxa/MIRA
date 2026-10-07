import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {ContinuousListeningController}=await import(new URL('features/session/continuous-listening.js',dist));
const {BrowserAudioTransport}=await import(new URL('features/session/audio-transport.js',dist));
const lease='12345678-1234-4234-8234-123456789012', utterance='22345678-1234-4234-8234-123456789012';
const readiness=(extra={})=>({lease_id:lease,sample_rate_hz:16000,max_seconds:120,max_samples:1920000,max_utterances:12,
  max_streams_per_session:4,max_total_streams:8,session_lease_starts_used:1,total_lease_starts_used:1,
  endpoint_mode:'google_vad_offsets_natural',manual_commit_required:false,natural_grace_ms:750,drain_timeout_ms:2000,max_recognition_streams:4,...extra});
const proof=(extra={})=>{const event={type:'utterance_ready',lease_id:lease,utterance_id:utterance,revision:1,text:'Hello Mira.',
  begin_offset_samples:0,end_offset_samples:640,final_offset_samples:640,endpoint_basis:'offset_coverage',...extra};
  return {...event,source_end_sample:extra.source_end_sample??Math.max(event.end_offset_samples,event.final_offset_samples??0)};};
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function harness(extra={}) {
  let capture,observer,resolver,holdResolver,closedResolve,sequence=0,playback=false;
  const updates=[],commits=[],holds=[],submissions=[],calls=[];
  // These retained-overlap contract cases explicitly select conservative mode.
  const controller=new ContinuousListeningController({mode:'natural',bargeInMode:()=>extra.bargeInMode??'guarded',
    createId:()=>sequence++===0?lease:`${String(sequence+2).padStart(8,'0')}-1234-4234-8234-123456789012`,
    createCapture:options=>{capture=options;return {start(){calls.push('capture');options.onState('recording');return Promise.resolve(true);},stop(){calls.push('stop');},async close(){calls.push('close');}};},
    openStream:(id,signal,observers,mode)=>{observer=observers;calls.push(['mode',mode]);return {ready:Promise.resolve(readiness(extra.ready)),
      closed:new Promise(resolve=>{closedResolve=resolve;}),send(){},commit(id,revision,token){commits.push({id,revision,token});return new Promise(resolve=>{resolver=resolve;});},
      hold(token,revision){holds.push({token,revision});return new Promise(resolve=>{holdResolver=resolve;});},
      stop(){closedResolve();return Promise.resolve();},cancel(){closedResolve();}};},
    submitInput:async(text,id)=>{submissions.push({text,id});return extra.outcome??{status:'submitted'};},
    isPlaybackBusy:()=>playback,prepareInputFromGesture:()=>{calls.push('prepare');return true;},
    interruptReply:()=>{calls.push('interrupt');return true;},onUpdate:view=>updates.push(view),
  });
  return {controller,updates,commits,holds,submissions,calls,get capture(){return capture;},
    emit:event=>observer.onEvent(event),fail:()=>observer.onError(new Error('voice offline')),
    setPlayback:value=>{playback=value;},accept(extra={}){const c=commits.at(-1);resolver({type:'commit_ready',lease_id:lease,
      commit_id:c.id,revision:c.revision,utterance_id:c.token,segment_seq:commits.length,text:'Hello Mira.',...extra});},
    reject(){const c=commits.at(-1);resolver({type:'commit_rejected',lease_id:lease,commit_id:c.id,reason:'stale_revision',current_revision:c.revision+1});},
    resolveHold(extra={}){const h=holds.at(-1);holdResolver({type:'utterance_held',lease_id:lease,utterance_id:h.token,revision:h.revision,text:'Hello Mira.',...extra});}};
}
async function started(extra){const h=harness(extra);assert.equal(h.controller.start(),true);await flush();return h;}

test('natural start prepares playback in gesture and only exact utterance proof auto-submits once',async()=>{
  const h=await started();assert.ok(h.calls.indexOf('prepare')<h.calls.indexOf('capture'));
  assert.deepEqual(h.calls.find(Array.isArray),['mode','natural']);
  h.emit({type:'transcript',lease_id:lease,revision:1,text:'Hello Mira.',is_final:true});await flush();
  assert.equal(h.commits.length,0,'a final or punctuation alone does not authorize automatic dispatch');
  h.emit(proof());h.emit(proof());await flush();assert.equal(h.commits.length,1);assert.equal(h.commits[0].token,utterance);
  assert.equal(h.submissions.length,0);assert.equal(h.updates.at(-1).conversation_phase,'sending');
  h.accept();await flush();assert.deepEqual(h.submissions,[{text:'Hello Mira.',id:h.commits[0].id}]);
  assert.equal(h.updates.at(-1).sent_text[0].state,'sent');assert.equal(h.controller.active,true);
  h.emit(proof());await flush();assert.equal(h.commits.length,1);await h.controller.stop();
});

test('manual capability and endpoint hints preserve richer interim and never auto-send',async()=>{
  const h=await started({ready:{endpoint_mode:'unavailable_manual',manual_commit_required:true}});
  h.emit({type:'transcript',lease_id:lease,revision:2,text:'Stable words plus changing tail',is_final:false});
  h.emit({type:'endpoint_pending',lease_id:lease,revision:2,text:'Stable words',reason:'missing_result_offset',can_submit_manually:true});
  await flush();assert.equal(h.commits.length,0);assert.equal(h.updates.at(-1).transcript.text,'Stable words plus changing tail');
  assert.equal(h.updates.at(-1).transcript.can_send,true);assert.equal(h.updates.at(-1).conversation_phase,'manual_review');
  await h.controller.stop();
});

test('natural final and pending endpoint stay in recognizing state while manual fallback stays available',async()=>{
  const h=await started();h.emit({type:'transcript',lease_id:lease,revision:1,text:'An ordinary sentence',is_final:true});
  assert.equal(h.updates.at(-1).conversation_phase,'transcribing');assert.equal(h.updates.at(-1).transcript.can_send,true);
  h.emit({type:'endpoint_pending',lease_id:lease,revision:1,text:'An ordinary sentence',reason:'unmatched_activity_end',can_submit_manually:true});
  assert.equal(h.updates.at(-1).conversation_phase,'transcribing');assert.equal(h.commits.length,0);
  assert.doesNotMatch(h.updates.at(-1).transcript.hint,/句末对齐尚未确认/);await h.controller.stop();
});

test('stale auto rejection and newer revision fence accepted text without automatic retry',async t=>{
  for(const result of ['reject','accept'])await t.test(result,async()=>{
    const h=await started();h.emit(proof());await flush();assert.equal(h.commits.length,1);
    h.emit({type:'transcript',lease_id:lease,revision:2,text:'Hello Mira with a correction.',is_final:true});
    if(result==='reject')h.reject();else h.accept();await flush();
    assert.equal(h.submissions.length,0);h.emit(proof({revision:2,text:'Hello Mira with a correction.'}));await flush();
    assert.equal(h.commits.length,1,'the same utterance must be reviewed after its failed/stale attempt');
    assert.match(h.updates.at(-1).transcript.text,/correction/);await h.controller.stop();
  });
});

test('late amendment remains associated with submitted utterance and never starts another turn',async()=>{
  const h=await started();h.emit(proof());await flush();h.accept();await flush();const id=h.commits[0].id;
  h.emit({type:'utterance_revision',lease_id:lease,utterance_id:utterance,commit_id:id,revision:2,text:'Hello Mira, corrected.',
    reason:'late_result_after_submission',requires_review:true,submission_state:'accepted'});await flush();
  const item=h.updates.at(-1).sent_text[0];assert.equal(item.text,'Hello Mira.');assert.equal(item.utterance_id,utterance);
  assert.equal(item.correction.text,'Hello Mira, corrected.');assert.equal(item.correction.submission_state,'accepted');
  assert.equal(h.commits.length,1);assert.equal(h.submissions.length,1);await h.controller.stop();
});

test('amendment before commit acknowledgement is immediately visible and survives Stop',async()=>{
  const h=await started();h.emit(proof());await flush();const id=h.commits[0].id;
  h.emit({type:'utterance_revision',lease_id:lease,utterance_id:utterance,commit_id:id,revision:2,text:'Amended before acknowledgement.',
    reason:'late_result_after_submission',requires_review:true,submission_state:'revoked'});
  assert.equal(h.updates.at(-1).sent_text[0].text,'Hello Mira.');
  assert.equal(h.updates.at(-1).sent_text[0].correction.text,'Amended before acknowledgement.');
  await h.controller.stop();h.accept();await flush();assert.equal(h.submissions.length,0);
  assert.equal(h.updates.at(-1).sent_text[0].state,'not_sent');
  assert.equal(h.updates.at(-1).sent_text[0].correction.text,'Amended before acknowledgement.');
});

test('older utterance correction cannot replace a newer activity preview',async()=>{
  const h=await started();h.emit(proof());await flush();h.accept();await flush();
  h.emit({type:'transcript',lease_id:lease,revision:3,text:'A newer utterance still changing',is_final:false});
  h.emit({type:'utterance_revision',lease_id:lease,utterance_id:utterance,commit_id:h.commits[0].id,revision:4,text:'Correction for the first.',
    reason:'late_result_after_submission',requires_review:true,submission_state:'accepted'});
  assert.equal(h.updates.at(-1).transcript.text,'A newer utterance still changing');
  assert.equal(h.updates.at(-1).sent_text[0].correction.text,'Correction for the first.');
  assert.equal(h.submissions.length,1);await h.controller.stop();
});

test('natural terminal cap preserves exactly the already accepted last input without reopening the microphone',async()=>{
  const h=await started({ready:{max_utterances:1}});h.emit(proof());await flush();h.accept();
  h.emit({type:'stopped',lease_id:lease,reason:'utterance_limit'});await flush();
  assert.equal(h.submissions.length,1);assert.equal(h.updates.at(-1).state,'limit');
  assert.equal(h.updates.at(-1).sent_text[0].state,'sent');assert.equal(h.controller.active,false);
  assert.equal(h.calls.filter(call=>call==='capture').length,1);
});

test('correlated commit reset preserves accepted suffix while retaining older prefix; arbitrary newer text still fences',async t=>{
  for(const mode of ['correlated-empty','correlated-prefix','wrong-token','wrong-commit','wrong-revision','newer-text'])await t.test(mode,async()=>{
    const h=await started();h.emit(proof());await flush();const id=h.commits[0].id;h.accept();
    h.emit({type:'transcript',lease_id:lease,revision:mode==='wrong-revision'?3:2,text:mode==='correlated-empty'?'':'Older retained prefix',is_final:false,
      committed_commit_id:mode==='wrong-commit'?lease:id,committed_utterance_id:mode==='wrong-token'?lease:utterance});
    if(mode==='newer-text')h.emit({type:'transcript',lease_id:lease,revision:3,text:'Actual new input',is_final:true});
    await flush();assert.equal(h.submissions.length,mode.startsWith('correlated')?1:0);
    if(mode==='correlated-prefix')assert.equal(h.updates.at(-1).transcript.text,'Older retained prefix');
    await h.controller.stop();
  });
});

test('heuristic and finalized endpoint bases auto-send with distinct honest hints',async t=>{
  for(const basis of ['offset_coverage','vad_final_grace','stream_finalized'])await t.test(basis,async()=>{
    const h=await started();h.emit(proof({endpoint_basis:basis,final_offset_samples:basis==='offset_coverage'?640:basis==='vad_final_grace'?500:null}));
    await flush();assert.equal(h.commits.length,1);
    if(basis==='vad_final_grace')assert.match(h.updates.at(-1).transcript.hint,/停顿|启发/);
    h.accept();await flush();assert.equal(h.submissions.length,1);await h.controller.stop();
  });
});

test('recognition drain and continuation status keep microphone ownership visible with current request budget',async()=>{
  const h=await started();h.emit({type:'recognition_status',lease_id:lease,stream_index:1,state:'draining',stt_requests_used:2,stt_requests_remaining:6});
  assert.equal(h.updates.at(-1).recognition_status.state,'draining');assert.equal(h.updates.at(-1).conversation_phase,'transcribing');
  assert.equal(h.controller.microphoneActive,true);
  h.emit({type:'recognition_status',lease_id:lease,stream_index:2,state:'listening',stt_requests_used:3,stt_requests_remaining:5});
  h.emit({type:'recognition_status',lease_id:lease,stream_index:1,state:'completed',stt_requests_used:2,stt_requests_remaining:6});
  assert.equal(h.updates.at(-1).recognition_status.stream_index,2);assert.equal(h.updates.at(-1).recognition_status.stt_requests_remaining,5);
  await h.controller.stop();
});

test('Stop Close and voice failure fence pending automatic commits and preserve text',async t=>{
  for(const action of ['stop','close','failure'])await t.test(action,async()=>{
    const h=await started();h.emit(proof());await flush();assert.equal(h.commits.length,1);
    if(action==='failure')h.fail();else await h.controller[action]();h.accept();await flush();
    assert.equal(h.submissions.length,0);assert.equal(h.controller.active,false);assert.ok(h.calls.includes('stop'));
    assert.equal(h.updates.at(-1).previous_previews[0].text,'Hello Mira.');
  });
});

test('software playback overlap blocks automatic send even after playback ends',async()=>{
  const h=await started();h.setPlayback(true);
  h.capture.onChunk({pcm16le:new Uint8Array(1280).fill(20),sampleRate:16000,channels:1,sequence:0,startSample:0,endSample:640,
    captureSampleRate:48000,sourceSampleRate:null,captureStartFrame:0});
  h.setPlayback(false);h.emit(proof());await flush();assert.equal(h.commits.length,0);
  assert.equal(h.calls.includes('interrupt'),false,'captured playback energy is not barge-in evidence');
  assert.equal(h.updates.at(-1).conversation_phase,'manual_review');assert.equal(h.updates.at(-1).transcript.can_send,true);
  await h.controller.stop();
});

test('malformed or unknown playback PCM stays conservatively held in an injected capture port',async()=>{
  for(const pcm16le of [new Uint8Array(),new Uint8Array(3),new Uint8Array(3202)]){
    const h=await started();h.setPlayback(true);
    h.capture.onChunk({pcm16le,sampleRate:16000,channels:1,sequence:0,startSample:0,endSample:640,
      captureSampleRate:48000,sourceSampleRate:null,captureStartFrame:0});
    h.setPlayback(false);h.emit(proof());await flush();
    assert.equal(h.commits.length,0);assert.equal(h.updates.at(-1).transcript.review_required,true);await h.controller.stop();
  }
});

test('an utterance observed while playback owns the sink stays manual but a fresh activity after interruption can auto-send',async()=>{
  const h=await started();h.setPlayback(true);h.emit(proof());await flush();assert.equal(h.commits.length,0);
  h.setPlayback(false);h.emit(proof());await flush();assert.equal(h.commits.length,0,'the old overlap cannot become an automatic turn later');
  const fresh='42345678-1234-4234-8234-123456789012';
  h.emit({type:'transcript',lease_id:lease,revision:2,text:'Hello Mira.',is_final:true});
  h.emit(proof({utterance_id:fresh,revision:2,begin_offset_samples:640,end_offset_samples:1280,final_offset_samples:1280}));
  await flush();assert.equal(h.commits.length,1);assert.equal(h.commits[0].token,fresh);
  h.accept();await flush();assert.equal(h.submissions.length,1);assert.equal(h.controller.active,true);await h.controller.stop();
});

test('withheld overlap stays recoverable if a newer activity sends and transport fails before prefix reset',async()=>{
  const h=await started();h.setPlayback(true);h.emit(proof({text:'Retained overlapping words.'}));await flush();
  h.setPlayback(false);h.emit({type:'transcript',lease_id:lease,revision:2,text:'Retained overlapping words.Hello Mira.',is_final:true});
  h.emit(proof({utterance_id:'42345678-1234-4234-8234-123456789012',revision:2,begin_offset_samples:640,end_offset_samples:1280,final_offset_samples:1280}));
  await flush();h.accept();await flush();h.fail();await flush();
  assert.equal(h.submissions.length,1);assert.equal(h.updates.at(-1).held_previews[0].text,'Retained overlapping words.');
  assert.equal(h.controller.restoreHeldPreview(lease,utterance),'Retained overlapping words.');
  assert.equal(h.submissions.length,1,'restore never sends');assert.equal(h.updates.at(-1).held_previews.length,0);
});

test('held previews have a visible bound, never evict, and restore frees space without sending',async()=>{
  const h=await started();h.setPlayback(true);
  for(let index=1;index<=13;index++)h.emit(proof({utterance_id:`${String(index).padStart(8,'0')}-1234-4234-8234-123456789012`,revision:index,text:`retained ${index}`}));
  await flush();assert.equal(h.controller.active,false);assert.equal(h.updates.at(-1).state,'limit');
  assert.deepEqual(h.updates.at(-1).held_previews.map(x=>x.text),Array.from({length:12},(_,i)=>`retained ${i+1}`));
  assert.equal(h.updates.at(-1).previous_previews[0].text,'retained 13');
  assert.equal(h.controller.start(),false);assert.equal(h.submissions.length,0);
  assert.equal(h.controller.restoreHeldPreview(lease,'00000001-1234-4234-8234-123456789012'),'retained 1');
  assert.equal(h.controller.start(),true);await flush();assert.equal(h.submissions.length,0);await h.controller.stop();
});

test('unknown input result is retained and never retried or replaced by automatic correction',async()=>{
  const h=await started({outcome:{status:'unknown'}});h.emit(proof());await flush();h.accept();await flush();
  assert.equal(h.updates.at(-1).sent_text[0].state,'unknown');assert.equal(h.submissions.length,1);
  h.emit(proof({revision:2,text:'Updated later.'}));await flush();assert.equal(h.commits.length,1);await h.controller.stop();
});

class Socket {readyState=0;bufferedAmount=0;sent=[];send(text){this.sent.push(JSON.parse(text));}close(){this.readyState=3;}open(){this.readyState=1;this.onopen?.({});}message(value){this.onmessage?.({data:JSON.stringify(value)});}}
test('browser natural transport validates capability and offsets and binds token to exact commit response',async()=>{
  const socket=new Socket(),events=[],errors=[];
  const api=new BrowserAudioTransport({apiBase:'/api/v1',pollIntervalMs:200},()=>({sessionId:'s',token:'private'}),
    {createSocket:()=>socket,baseUrl:'https://mira.test/'});
  const stream=api.continuousListening(lease,new AbortController().signal,{onEvent:e=>events.push(e),onError:e=>errors.push(e)},'natural');
  try {socket.open();assert.equal(socket.sent[0].mode,'natural');socket.message({type:'ready',...readiness()});await stream.ready;
    stream.send({pcm16le:new Uint8Array(1280),sampleRate:16000,channels:1,sequence:0,startSample:0,endSample:640});
    socket.message(proof());assert.equal(events.at(-1).utterance_id,utterance);
    const id='32345678-1234-4234-8234-123456789012',pending=stream.commit(id,1,utterance);
    assert.equal(socket.sent.at(-1).utterance_id,utterance);
    socket.message({type:'commit_ready',lease_id:lease,commit_id:id,segment_seq:1,revision:1,text:'Hello Mira.',utterance_id:utterance});
    assert.equal((await pending).utterance_id,utterance);assert.equal(errors.length,0);
  } finally {api.close();}
});

test('browser rejects unsupported natural capability and forged source or commit identity',async t=>{
  for(const kind of ['manual-enabled-natural','natural-with-manual-client','offset-before-begin','uncovered-end','fractional-offset','ahead-of-capture','wrong-token','wrong-revision']) {
    await t.test(kind,async()=>{
      const socket=new Socket(),errors=[],events=[];
      const api=new BrowserAudioTransport({apiBase:'/api/v1',pollIntervalMs:200},()=>({sessionId:'s',token:'private'}),
        {createSocket:()=>socket,baseUrl:'https://mira.test/'});
      const stream=api.continuousListening(lease,new AbortController().signal,{onEvent:e=>events.push(e),onError:e=>errors.push(e)},
        kind==='natural-with-manual-client'?'manual':'natural');
      try {
        socket.open();
        if(kind==='manual-enabled-natural'||kind==='natural-with-manual-client') {
          const rejected=assert.rejects(stream.ready);socket.message({type:'ready',...readiness(kind==='manual-enabled-natural'?{manual_commit_required:true}:{})});
          await rejected;
        } else {
          socket.message({type:'ready',...readiness()});await stream.ready;
          stream.send({pcm16le:new Uint8Array(1280),sampleRate:16000,channels:1,sequence:0,startSample:0,endSample:640});
          if(kind==='wrong-token'||kind==='wrong-revision') {
            const id='32345678-1234-4234-8234-123456789012',rejected=assert.rejects(stream.commit(id,1,utterance));
            socket.message({type:'commit_ready',lease_id:lease,commit_id:id,segment_seq:1,revision:kind==='wrong-revision'?2:1,
              text:'Hello Mira.',utterance_id:kind==='wrong-token'?lease:utterance});await rejected;
          } else {
            const changes=kind==='offset-before-begin'?{begin_offset_samples:700}:kind==='uncovered-end'?{end_offset_samples:641}
              :kind==='fractional-offset'?{end_offset_samples:2.5}:{end_offset_samples:641,final_offset_samples:641};
            socket.message(proof(changes));assert.equal(events.some(e=>e.type==='utterance_ready'),false);
          }
        }
        assert.equal(errors.length,1);assert.equal(socket.readyState,3);
      } finally {api.close();}
    });
  }
});

test('browser retains oversized previews so the UI can mark truncation instead of making a partial automatic input',async()=>{
  const socket=new Socket(),events=[];
  const api=new BrowserAudioTransport({apiBase:'/api/v1',pollIntervalMs:200},()=>({sessionId:'s',token:'private'}),
    {createSocket:()=>socket,baseUrl:'https://mira.test/'});
  const stream=api.continuousListening(lease,new AbortController().signal,{onEvent:e=>events.push(e),onError(){}},'natural');
  try {socket.open();socket.message({type:'ready',...readiness()});await stream.ready;
    socket.message({type:'transcript',lease_id:lease,revision:1,text:'x'.repeat(2001),is_final:true});
    assert.equal(events.at(-1).text.length,2001);
  } finally {api.close();}
});

test('transport cleanup after accepted count cap cannot send a revoking user Stop; explicit Stop still can',async t=>{
  for(const action of ['cleanup','explicit-stop'])await t.test(action,async()=>{
    const socket=new Socket(),abort=new AbortController();
    const api=new BrowserAudioTransport({apiBase:'/api/v1',pollIntervalMs:200},()=>({sessionId:'s',token:'private'}),
      {createSocket:()=>socket,baseUrl:'https://mira.test/'});
    const stream=api.continuousListening(lease,abort.signal,{onEvent(){},onError(){}},'natural');
    try {socket.open();socket.message({type:'ready',...readiness({max_utterances:1})});await stream.ready;
      const id='32345678-1234-4234-8234-123456789012',pending=stream.commit(id,1,utterance);
      socket.message({type:'commit_ready',lease_id:lease,commit_id:id,segment_seq:1,revision:1,text:'Hello Mira.',utterance_id:utterance});
      await pending;
      if(action==='cleanup')abort.abort();else {const stopping=stream.stop();socket.message({type:'stopped',lease_id:lease,reason:'user_stop'});await stopping;}
      assert.equal(socket.sent.filter(frame=>frame.type==='stop').length,action==='cleanup'?0:1);
    } finally {api.close();}
  });
});

test('browser preserves endpoint basis, correlated reset and bounded provider status on real parsed frames',async t=>{
  for(const basis of ['offset_coverage','vad_final_grace','stream_finalized'])await t.test(basis,async()=>{
    const socket=new Socket(),events=[],errors=[];
    const api=new BrowserAudioTransport({apiBase:'/api/v1',pollIntervalMs:200},()=>({sessionId:'s',token:'private'}),
      {createSocket:()=>socket,baseUrl:'https://mira.test/'});
    const stream=api.continuousListening(lease,new AbortController().signal,{onEvent:e=>events.push(e),onError:e=>errors.push(e)},'natural');
    try {socket.open();socket.message({type:'ready',...readiness()});await stream.ready;
      stream.send({pcm16le:new Uint8Array(1280),sampleRate:16000,channels:1,sequence:0,startSample:0,endSample:640});
      socket.message(proof({endpoint_basis:basis,final_offset_samples:basis==='offset_coverage'?640:basis==='vad_final_grace'?500:null}));
      assert.equal(events.at(-1).endpoint_basis,basis);assert.equal(events.at(-1).source_end_sample,640);
      socket.message({type:'recognition_status',lease_id:lease,stream_index:2,state:'draining',stt_requests_used:2,stt_requests_remaining:6});
      assert.equal(events.at(-1).stream_index,2);assert.equal(events.at(-1).stt_requests_remaining,6);
      socket.message({type:'transcript',lease_id:lease,revision:2,text:'retained prefix',is_final:false,
        committed_commit_id:'32345678-1234-4234-8234-123456789012',committed_utterance_id:utterance});
      assert.equal(events.at(-1).committed_utterance_id,utterance);assert.equal(errors.length,0);
    } finally {api.close();}
  });
});

test('browser rejects unbounded or contradictory v2 endpoint evidence and continuation status',async t=>{
  const cases=[
    ['null-offset-proof',proof({final_offset_samples:null})],
    ['null-heuristic',proof({endpoint_basis:'vad_final_grace',final_offset_samples:null})],
    ['unknown-basis',proof({endpoint_basis:'punctuation'})],
    ['source-before-end',proof({source_end_sample:639})],
    ['final-before-begin',proof({begin_offset_samples:500,final_offset_samples:400,endpoint_basis:'vad_final_grace'})],
    ['final-after-source',proof({source_end_sample:640,final_offset_samples:641})],
    ['unknown-status',{type:'recognition_status',lease_id:lease,stream_index:1,state:'retry_forever'}],
    ['too-many-streams',{type:'recognition_status',lease_id:lease,stream_index:5,state:'opening'}],
    ['negative-budget',{type:'recognition_status',lease_id:lease,stream_index:1,state:'draining',stt_requests_remaining:-1}],
    ['orphan-reset-token',{type:'transcript',lease_id:lease,revision:2,text:'',is_final:false,committed_utterance_id:utterance}],
  ];
  for(const [name,frame] of cases)await t.test(name,async()=>{
    const socket=new Socket(),errors=[];
    const api=new BrowserAudioTransport({apiBase:'/api/v1',pollIntervalMs:200},()=>({sessionId:'s',token:'private'}),
      {createSocket:()=>socket,baseUrl:'https://mira.test/'});
    const stream=api.continuousListening(lease,new AbortController().signal,{onEvent(){},onError:e=>errors.push(e)},'natural');
    try {socket.open();socket.message({type:'ready',...readiness()});await stream.ready;
      stream.send({pcm16le:new Uint8Array(1280),sampleRate:16000,channels:1,sequence:0,startSample:0,endSample:640});
      socket.message(frame);assert.equal(errors.length,1);assert.equal(socket.readyState,3);
    } finally {api.close();}
  });
});

test('held finalized candidate is acknowledged once without Input and a fresh activity then auto-submits',async()=>{
  const h=await started();h.setPlayback(true);const held=proof({endpoint_basis:'stream_finalized',final_offset_samples:null});
  h.emit(held);h.emit(held);await flush();assert.deepEqual(h.holds,[{token:utterance,revision:1}]);
  assert.equal(h.commits.length,0);assert.equal(h.submissions.length,0);assert.equal(h.updates.at(-1).held_previews[0].text,'Hello Mira.');
  assert.equal(h.updates.at(-1).transcript.can_send,false,'manual commit waits for hold acknowledgement');
  h.resolveHold();await flush();h.setPlayback(false);h.emit(held);await flush();assert.equal(h.holds.length,1);
  h.emit(proof({utterance_id:'42345678-1234-4234-8234-123456789012',revision:2,begin_offset_samples:640,end_offset_samples:1280,final_offset_samples:1280}));
  await flush();assert.equal(h.commits.length,1);h.accept();await flush();assert.equal(h.submissions.length,1);
  assert.equal(h.updates.at(-1).held_previews[0].text,'Hello Mira.');assert.equal(h.controller.active,true);await h.controller.stop();
});

test('a held acknowledgement and next finalized activity in one host task cannot make the old continuation cancel the new hold',async()=>{
  const h=await started();h.setPlayback(true);h.emit(proof({endpoint_basis:'stream_finalized',final_offset_samples:null}));
  h.resolveHold();h.emit({type:'utterance_held',lease_id:lease,utterance_id:utterance,revision:1,text:'Hello Mira.'});
  h.emit(proof({utterance_id:'42345678-1234-4234-8234-123456789012',revision:2,endpoint_basis:'stream_finalized',final_offset_samples:null,
    begin_offset_samples:640,end_offset_samples:1280}));
  await flush();assert.equal(h.holds.length,2);assert.equal(h.controller.active,true);
  h.resolveHold();await flush();assert.equal(h.controller.active,true);assert.equal(h.updates.at(-1).held_previews.length,2);
  assert.equal(h.submissions.length,0);await h.controller.stop();
});

test('a finalized candidate held behind an earlier commit is acknowledged after settlement without retrying model input',async t=>{
  for(const outcome of ['stale','accepted-but-fenced','stop'])await t.test(outcome,async()=>{
    const h=await started();h.emit(proof());await flush();
    const second=proof({utterance_id:'42345678-1234-4234-8234-123456789012',revision:2,text:'second held',endpoint_basis:'stream_finalized',
      final_offset_samples:null,begin_offset_samples:640,end_offset_samples:1280});
    h.emit(second);assert.equal(h.holds.length,0);assert.equal(h.updates.at(-1).held_previews[0].text,'second held');
    if(outcome==='stop')await h.controller.stop();
    if(outcome==='accepted-but-fenced')h.accept();else h.reject();await flush();
    assert.equal(h.submissions.length,0,'no automatic model retry of the earlier commit');
    assert.equal(h.holds.length,outcome==='stop'?0:1);
    if(outcome!=='stop') {assert.deepEqual(h.holds[0],{token:second.utterance_id,revision:2});h.emit(second);
      assert.equal(h.holds.length,1);h.resolveHold({text:'second held'});await flush();assert.equal(h.controller.active,true);await h.controller.stop();}
  });
});

test('a strictly newer finalized revision of an uncommitted attempted token is retained and held after stale rejection',async()=>{
  const h=await started();h.emit(proof());await flush();assert.equal(h.commits.length,1);
  const revised=proof({revision:2,text:'Hello Mira with its late tail.',endpoint_basis:'stream_finalized',final_offset_samples:null,
    end_offset_samples:1280,source_end_sample:1280});
  h.emit(revised);assert.equal(h.holds.length,0);
  assert.equal(h.updates.at(-1).held_previews.at(-1).text,'Hello Mira with its late tail.');
  h.reject();await flush();assert.deepEqual(h.holds,[{token:utterance,revision:2}]);assert.equal(h.submissions.length,0);
  h.emit(revised);assert.equal(h.holds.length,1);h.resolveHold({text:revised.text});await flush();
  h.emit(proof({utterance_id:'52345678-1234-4234-8234-123456789012',revision:3,begin_offset_samples:1280,end_offset_samples:1920,final_offset_samples:1920}));
  await flush();assert.equal(h.commits.length,2);h.accept();await flush();assert.equal(h.submissions.length,1);
  assert.equal(h.updates.at(-1).held_previews[0].text,revised.text);await h.controller.stop();
});

test('the retained-candidate queue settles same and different tokens across commit response cancellation and supersession orders',async t=>{
  for(const sameToken of [true,false])for(const order of ['ready-then-reject','reject-then-ready','older-ack','stop','close','failure','obsolete']) {
    await t.test(`${sameToken?'same':'different'}:${order}`,async()=>{
      const h=await started();h.emit(proof());await flush();h.setPlayback(true);
      const candidate=proof({utterance_id:sameToken?utterance:'42345678-1234-4234-8234-123456789012',revision:2,text:'queued exact text',
        endpoint_basis:'stream_finalized',final_offset_samples:null,end_offset_samples:1280});
      if(order==='reject-then-ready'){h.reject();await flush();h.emit(candidate);}
      else {
        h.emit(candidate);
        if(order==='stop'||order==='close')await h.controller[order]();
        else if(order==='failure')h.fail();
        else if(order==='obsolete')h.emit({type:'transcript',lease_id:lease,revision:3,text:'newer uncertain preview',is_final:false});
        if(order==='older-ack')h.accept();else h.reject();
      }
      await flush();const canContinue=['ready-then-reject','reject-then-ready','older-ack'].includes(order);
      assert.equal(h.holds.length,canContinue?1:0);assert.equal(h.submissions.length,0);assert.equal(h.commits.length,1);
      assert.equal(h.updates.at(-1).held_previews.at(-1).text,'queued exact text');
      if(canContinue){h.emit(candidate);assert.equal(h.holds.length,1);h.resolveHold({text:candidate.text});await flush();assert.equal(h.controller.active,true);await h.controller.stop();}
      else assert.equal(h.controller.active,false,'uncertain or cancelled settlement cannot leave a falsely active listener');
    });
  }
});

test('hold conflict failure Stop and Close retain the exact preview and cannot resurrect capture',async t=>{
  for(const action of ['rejected','wrong-text','stop','close','failure'])await t.test(action,async()=>{
    const h=await started();h.setPlayback(true);h.emit(proof({endpoint_basis:'stream_finalized',final_offset_samples:null}));await flush();
    assert.equal(h.holds.length,1);
    if(action==='stop'||action==='close')await h.controller[action]();
    else if(action==='failure')h.fail();
    h.resolveHold(action==='rejected'?{type:'hold_rejected',reason:'stale_revision',current_revision:2}
      :action==='wrong-text'?{text:'Different text'}:{});await flush();
    assert.equal(h.controller.active,false);assert.equal(h.submissions.length,0);assert.equal(h.commits.length,0);
    assert.equal(h.updates.at(-1).held_previews[0].text,'Hello Mira.');
    assert.equal(h.calls.filter(x=>x==='capture').length,1);
  });
});

test('browser hold is exact tuple correlated and successful replay does not send another frame',async()=>{
  const socket=new Socket(),events=[],errors=[];
  const api=new BrowserAudioTransport({apiBase:'/api/v1',pollIntervalMs:200},()=>({sessionId:'s',token:'private'}),
    {createSocket:()=>socket,baseUrl:'https://mira.test/'});
  const stream=api.continuousListening(lease,new AbortController().signal,{onEvent:e=>events.push(e),onError:e=>errors.push(e)},'natural');
  try {socket.open();socket.message({type:'ready',...readiness()});await stream.ready;
    const pending=stream.hold(utterance,1),duplicate=stream.hold(utterance,1);
    assert.deepEqual(socket.sent.at(-1),{type:'hold',lease_id:lease,utterance_id:utterance,revision:1});
    assert.equal(socket.sent.filter(frame=>frame.type==='hold').length,1);
    const ack={type:'utterance_held',lease_id:lease,utterance_id:utterance,revision:1,text:'Hello Mira.'};socket.message(ack);
    assert.deepEqual(await pending,ack);assert.deepEqual(await duplicate,ack);assert.deepEqual(await stream.hold(utterance,1),ack);
    socket.message(ack);
    assert.equal(socket.sent.filter(frame=>frame.type==='hold').length,1);assert.equal(errors.length,0);
    assert.equal(events.filter(event=>event.type==='utterance_held').length,1);
  } finally {api.close();}
});

test('browser hold response conflicts and cancellation fence pending holds and late acknowledgements',async t=>{
  for(const kind of ['wrong-token','wrong-revision','conflicting-replay','stop','abort','close','rejected'])await t.test(kind,async()=>{
    const socket=new Socket(),abort=new AbortController(),events=[],errors=[];
    const api=new BrowserAudioTransport({apiBase:'/api/v1',pollIntervalMs:200},()=>({sessionId:'s',token:'private'}),
      {createSocket:()=>socket,baseUrl:'https://mira.test/'});
    const stream=api.continuousListening(lease,abort.signal,{onEvent:e=>events.push(e),onError:e=>errors.push(e)},'natural');
    try {socket.open();socket.message({type:'ready',...readiness()});await stream.ready;
      const pending=stream.hold(utterance,1),ack={type:'utterance_held',lease_id:lease,utterance_id:utterance,revision:1,text:'Hello Mira.'};
      if(kind==='conflicting-replay') {socket.message(ack);await pending;socket.message({...ack,text:'Conflicting text'});assert.equal(errors.length,1);}
      else if(kind==='rejected') {socket.message({type:'hold_rejected',lease_id:lease,utterance_id:utterance,revision:1,reason:'stale_revision',current_revision:2});
        assert.equal((await pending).type,'hold_rejected');assert.equal(errors.length,0);}
      else {
        const rejected=assert.rejects(pending);
        if(kind==='wrong-token')socket.message({...ack,utterance_id:lease});
        else if(kind==='wrong-revision')socket.message({...ack,revision:2});
        else if(kind==='abort')abort.abort();
        else if(kind==='close')api.close();
        else {const stopped=stream.stop();socket.message({type:'stopped',lease_id:lease,reason:'user_stop'});await stopped;}
        await rejected;socket.message(ack);assert.equal(events.some(e=>e.type==='utterance_held'),false);
      }
      assert.equal(socket.sent.filter(frame=>frame.type==='hold').length,1);
    } finally {api.close();}
  });
});
