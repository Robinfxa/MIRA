import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import vm from 'node:vm';
const dist=pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST??'apps/web/dist')+'/');
const {MicrophoneCapture}=await import(new URL('features/audio/capture.js',dist));
const {ContinuousListeningController}=await import(new URL('features/session/continuous-listening.js',dist));
const {BrowserAudioTransport}=await import(new URL('features/session/audio-transport.js',dist));
const workletSource=readFileSync(new URL('../../apps/web/public/audio/capture-worklet.js',import.meta.url),'utf8');
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const lease='12345678-1234-4234-8234-123456789012';

function harness(rate=48000,batch=40){
 let clock=0,timerId=0,processor,contextGlobals,trackStops=0,requests=0,frame=0,id=0,playing=false;
 const timers=new Map(),views=[],chunks=[],captureErrors=[],sent=[];
 const setTimer=(fn,ms)=>{const id=++timerId;timers.set(id,{fn,at:clock+ms});return id;};
 const clearTimer=id=>timers.delete(id);
 const socket={readyState:0,bufferedAmount:0,send(text){if(this.readyState!==1)throw new Error('closed');sent.push({at:clock,...JSON.parse(text)});this.bufferedAmount+=text.length;queueMicrotask(()=>this.bufferedAmount=0);},close(){this.readyState=3;},open(){this.readyState=1;this.onopen?.({});},message(value){this.onmessage?.({data:JSON.stringify(value)});}};
 const track={stop(){trackStops++;},getSettings:()=>({sampleRate:rate}),addEventListener(){},removeEventListener(){}};
 const stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
 const context={sampleRate:rate,destination:{},audioWorklet:{addModule:async()=>{}},resume:async()=>{},close:async()=>{},createMediaStreamSource:()=>({connect(){},disconnect(){}})};
 const savedSet=globalThis.setTimeout,savedClear=globalThis.clearTimeout;
 globalThis.setTimeout=function(callback,ms){if(this!==undefined&&this!==globalThis)throw new TypeError('Illegal invocation');return setTimer(callback,ms);};
 globalThis.clearTimeout=function(id){if(this!==undefined&&this!==globalThis)throw new TypeError('Illegal invocation');return clearTimer(id);};
 const restoreTimers=()=>{globalThis.setTimeout=savedSet;globalThis.clearTimeout=savedClear;};
 const transport=new BrowserAudioTransport({apiBase:'/api/v1'},()=>({sessionId:'s',token:'synthetic'}),{createSocket:()=>socket,baseUrl:'https://mira.test/',now:()=>clock});
 const controller=new ContinuousListeningController({mode:'natural',createId:()=>id++===0?lease:`${String(id+1).padStart(8,'0')}-1234-4234-8234-123456789012`,
  createCapture:options=>new MicrophoneCapture({...options,chunkMilliseconds:batch,onChunk:c=>{chunks.push(c);return options.onChunk(c);},onError:e=>{captureErrors.push(e);options.onError(e);},getUserMedia:async()=>{requests++;return stream;},createContext:()=>context,
   createWorkletNode:(_context,_name,options)=>{let node;contextGlobals={Float32Array,sampleRate:rate,currentFrame:frame,AudioWorkletProcessor:class{constructor(){this.port={onmessage:null,postMessage:data=>node.port.onmessage?.({data})};}},registerProcessor:(_name,Class)=>{processor=new Class(options);}};
    vm.runInNewContext(workletSource,contextGlobals);node={connect(){},disconnect(){},onprocessorerror:null,port:{onmessage:null,postMessage:data=>processor.port.onmessage?.({data}),close(){}}};return node;}}),
  openStream:(id,signal,observers,mode)=>transport.continuousListening(id,signal,observers,mode),submitInput:async()=>({status:'submitted'}),interruptReply:()=>true,isPlaybackBusy:()=>playing,onUpdate:v=>views.push(v)});
 const advance=async ms=>{clock+=ms;for(const[id,t]of [...timers])if(t.at<=clock){timers.delete(id);t.fn();}await flush();};
 const pcm=async(ms,amplitude=.12)=>{const end=frame+Math.round(rate*ms/1000);while(frame+128<=end){contextGlobals.currentFrame=frame;const source=Float32Array.from({length:128},(_,i)=>amplitude*Math.sin(2*Math.PI*173*(frame+i)/rate)+.003*Math.sin(2*Math.PI*43*(frame+i)/rate));processor.process([[source]],[[new Float32Array(128)]]);frame+=128;await advance(128000/rate);}};
 const ready=(extra={})=>socket.message({type:'ready',lease_id:lease,sample_rate_hz:16000,max_seconds:120,max_samples:1920000,max_utterances:12,max_streams_per_session:4,max_total_streams:8,session_lease_starts_used:1,total_lease_starts_used:1,endpoint_mode:'google_vad_offsets_natural',manual_commit_required:false,client_endpoint_supported:true,client_silence_ms:700,drain_timeout_ms:2000,max_recognition_streams:12,...extra});
 return{restoreTimers,controller,transport,socket,sent,views,chunks,captureErrors,ready,pcm,advance,setPlaying:value=>playing=value,counts:()=>({trackStops,requests,frame}),clock:()=>clock};
}


test('browser receiver rules: first quiet endpoint after 285 capture chunks retains the microphone and draft',async()=>{
 const h=harness();try{h.controller.start();h.socket.open();await flush();h.ready();await flush();await h.pcm(10680);
 h.socket.message({type:'transcript',lease_id:lease,revision:1,text:'synthetic recognized draft',is_final:false});
 assert.equal(h.controller.active,true);await h.pcm(720,.001);await h.advance(20);
 assert.equal(h.controller.active,true);assert.equal(h.captureErrors.length,0);assert.equal(h.counts().trackStops,0);assert.equal(h.sent.filter(p=>p.type==='client_endpoint').length,1);
 }finally{h.transport.close();await h.controller.close();h.restoreTimers();}
});

test('browser receiver rules: endpoint clear, final commit, next capture and Stop preserve one microphone',async()=>{
 const h=harness();try{h.controller.start();h.socket.open();await flush();h.ready();await flush();await h.pcm(400);await h.pcm(800,.001);await h.advance(20);
 const ep=h.sent.find(p=>p.type==='client_endpoint'),uid='52345678-1234-4234-8234-123456789012';assert.ok(ep);
 h.socket.message({type:'endpoint_status',lease_id:lease,endpoint_id:ep.endpoint_id,source_end_sample:ep.source_end_sample,state:'queued'});
 h.socket.message({type:'endpoint_status',lease_id:lease,endpoint_id:ep.endpoint_id,source_end_sample:ep.source_end_sample,state:'completed'});
 h.socket.message({type:'utterance_ready',lease_id:lease,utterance_id:uid,revision:1,text:'synthetic final',begin_offset_samples:0,end_offset_samples:ep.source_end_sample,source_end_sample:ep.source_end_sample,final_offset_samples:null,endpoint_basis:'client_silence_finalized',client_endpoint_id:ep.endpoint_id});await flush();
 const commit=h.sent.find(p=>p.type==='commit');assert.ok(commit);h.socket.message({type:'commit_ready',lease_id:lease,commit_id:commit.commit_id,utterance_id:uid,segment_seq:1,revision:1,text:'synthetic final'});await flush();
 await h.pcm(400);assert.equal(h.controller.active,true);assert.equal(h.counts().requests,1);assert.equal(h.counts().trackStops,0);assert.equal(h.views.at(-1).sent_text[0].state,'sent');assert.deepEqual(h.captureErrors,[]);
 const stop=h.controller.stop();h.socket.message({type:'stopped',lease_id:lease,reason:'user_stop'});await stop;
 assert.equal(h.counts().trackStops,1);await h.advance(10000);assert.equal(h.controller.active,false);assert.equal(h.views.at(-1).state,'stopped');
 }finally{h.transport.close();await h.controller.close();h.restoreTimers();}
});

test('browser receiver rules: reply quiet waiter clears on quiet, Abort and Stop',async()=>{
 const h=harness();try{h.controller.start();h.socket.open();await flush();h.ready();await flush();await h.pcm(400);
 const abort=new AbortController(),waiting=h.controller.waitForReplyQuiet(abort.signal);abort.abort();assert.equal(await waiting,false);
 const quiet=h.controller.waitForReplyQuiet(new AbortController().signal);await h.pcm(800,.001);assert.equal(await quiet,true);
 await h.pcm(400);const stopped=h.controller.waitForReplyQuiet(new AbortController().signal),stop=h.controller.stop();h.socket.message({type:'stopped',lease_id:lease,reason:'user_stop'});await stop;assert.equal(await stopped,false);
 assert.deepEqual(h.captureErrors,[]);
 }finally{h.transport.close();await h.controller.close();h.restoreTimers();}
});

test('browser receiver rules: transport failure keeps its cause and recognized draft recoverable',async()=>{
 const h=harness();try{h.controller.start();h.socket.open();await flush();h.ready();await flush();await h.pcm(400);
 h.socket.message({type:'transcript',lease_id:lease,revision:1,text:'synthetic retained draft',is_final:false});
 h.socket.readyState=3;await h.pcm(40);
 assert.equal(h.views.at(-1).state,'error');assert.match(h.views.at(-1).error,/no longer open/);assert.deepEqual(h.captureErrors,[]);
 assert.equal(h.views.at(-1).previous_previews[0].text,'synthetic retained draft');
 assert.match(h.views.at(-1).notice,/上次聆听预览.*文字框/);
 assert.equal(h.controller.restorePreviousPreview(lease),'synthetic retained draft');assert.equal(h.sent.filter(p=>p.type==='commit').length,0);
 }finally{h.transport.close();await h.controller.close();h.restoreTimers();}
});

test('browser receiver rules: playback defaults invoke native interval methods with an accepted receiver',async()=>{
 const {CancelSafePlayback}=await import(new URL('features/audio/playback.js',dist));
 const savedSet=globalThis.setInterval,savedClear=globalThis.clearInterval;let scheduled=0,cleared=0;
 globalThis.setInterval=function(){assert.ok(this===undefined||this===globalThis);scheduled++;return 1;};
 globalThis.clearInterval=function(){assert.ok(this===undefined||this===globalThis);cleared++;};
 const playback=new CancelSafePlayback({isAuthorized:()=>true});
 try{assert.ok(playback.open({id:'synthetic',digest:'a'.repeat(64),activity_seq:0,output_epoch:0}));await playback.close();assert.equal(scheduled,1);assert.equal(cleared,1);}
 finally{globalThis.setInterval=savedSet;globalThis.clearInterval=savedClear;}
});


test('real worklet capture resampler controller and wire keep null lease alive beyond 120 seconds, then quiet-submit and continue',async()=>{
 const h=harness();try{
 h.controller.start();h.socket.open();await flush();h.ready({max_seconds:null,max_samples:null,max_utterances:null,max_streams_per_session:null,max_total_streams:null,max_recognition_streams:null,stt_requests_used:300,stt_requests_remaining:null});await flush();
 await h.pcm(119600);h.socket.message({type:'transcript',lease_id:lease,revision:1,text:'first part ',is_final:true});
 h.socket.message({type:'recognition_status',lease_id:lease,stream_index:301,state:'draining',stt_requests_used:301,stt_requests_remaining:null});
 await h.pcm(800);h.socket.message({type:'recognition_status',lease_id:lease,stream_index:302,state:'listening',stt_requests_used:302,stt_requests_remaining:null});
 await h.pcm(9600);h.socket.message({type:'transcript',lease_id:lease,revision:2,text:'first part complete tail',is_final:true});
 assert.ok(h.chunks.at(-1).endSample>16000*120);assert.ok(h.sent.filter(p=>p.type==='audio').at(-1).first_sample>16000*120);
 assert.equal(h.sent.filter(p=>p.type==='client_endpoint'||p.type==='commit'||p.type==='stop').length,0,'continuous speaking does not submit at the stream boundary');
 for(let i=303;i<=620;i++)h.socket.message({type:'recognition_status',lease_id:lease,stream_index:i,state:'listening',stt_requests_used:i,stt_requests_remaining:null});
 assert.equal(h.views.at(-1).recognition_status.stt_requests_used,620);assert.equal(h.views.at(-1).recognition_status.stt_requests_remaining,null);
 await h.pcm(800,.001);await h.advance(20);const ep=h.sent.find(p=>p.type==='client_endpoint');assert.ok(ep);
 const uid='62345678-1234-4234-8234-123456789012';
 h.socket.message({type:'endpoint_status',lease_id:lease,endpoint_id:ep.endpoint_id,source_end_sample:ep.source_end_sample,state:'completed'});
 h.socket.message({type:'utterance_ready',lease_id:lease,utterance_id:uid,revision:2,text:'first part complete tail',begin_offset_samples:0,end_offset_samples:ep.source_end_sample,source_end_sample:ep.source_end_sample,final_offset_samples:null,endpoint_basis:'client_silence_finalized',client_endpoint_id:ep.endpoint_id});await flush();
 const commit=h.sent.find(p=>p.type==='commit');assert.ok(commit);
 h.socket.message({type:'commit_ready',lease_id:lease,commit_id:commit.commit_id,utterance_id:uid,segment_seq:1,revision:2,text:'first part complete tail'});await flush();
 const before=h.chunks.at(-1).endSample;await h.pcm(800);assert.ok(h.chunks.at(-1).endSample>before);assert.equal(h.controller.active,true);
 assert.equal(h.counts().requests,1);assert.equal(h.counts().trackStops,0);assert.equal(h.views.at(-1).sent_text[0].text,'first part complete tail');assert.deepEqual(h.captureErrors,[]);
 }finally{h.transport.close();await h.controller.close();h.restoreTimers();}
});
