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

function harness(rate=48000,batch=40,mode='headphones'){
 let clock=0,timerId=0,processor,contextGlobals,trackStops=0,requests=0,frame=0,id=0,playing=false;
 const timers=new Map(),views=[],chunks=[],captureErrors=[],sent=[];
 const setTimer=(fn,ms)=>{const id=++timerId;timers.set(id,{fn,at:clock+ms});return id;};
 const clearTimer=id=>timers.delete(id);
 const socket={readyState:0,bufferedAmount:0,send(text){if(this.readyState!==1)throw new Error('closed');sent.push({at:clock,...JSON.parse(text)});this.bufferedAmount+=text.length;queueMicrotask(()=>this.bufferedAmount=0);},close(){this.readyState=3;},open(){this.readyState=1;this.onopen?.({});},message(value){this.onmessage?.({data:JSON.stringify(value)});}};
 const transport=new BrowserAudioTransport({apiBase:'/api/v1'},()=>({sessionId:'s',token:'synthetic'}),{createSocket:()=>socket,baseUrl:'https://mira.test/',now:()=>clock,setTimeout:setTimer,clearTimeout:clearTimer});
 const track={stop(){trackStops++;},getSettings:()=>({sampleRate:rate}),addEventListener(){},removeEventListener(){}};
 const stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
 const context={sampleRate:rate,destination:{},audioWorklet:{addModule:async()=>{}},resume:async()=>{},close:async()=>{},createMediaStreamSource:()=>({connect(){},disconnect(){}})};
 const controller=new ContinuousListeningController({mode:'natural',bargeInMode:()=>mode,createId:()=>id++===0?lease:`${String(id+1).padStart(8,'0')}-1234-4234-8234-123456789012`,setTimer,clearTimer,
  createCapture:options=>new MicrophoneCapture({...options,chunkMilliseconds:batch,onChunk:c=>{chunks.push(c);return options.onChunk(c);},onError:e=>{captureErrors.push(e);options.onError(e);},getUserMedia:async()=>{requests++;return stream;},createContext:()=>context,
   createWorkletNode:(_context,_name,options)=>{let node;contextGlobals={Float32Array,sampleRate:rate,currentFrame:frame,AudioWorkletProcessor:class{constructor(){this.port={onmessage:null,postMessage:data=>node.port.onmessage?.({data})};}},registerProcessor:(_name,Class)=>{processor=new Class(options);}};
    vm.runInNewContext(workletSource,contextGlobals);node={connect(){},disconnect(){},onprocessorerror:null,port:{onmessage:null,postMessage:data=>processor.port.onmessage?.({data}),close(){}}};return node;}}),
  openStream:(id,signal,observers,mode)=>transport.continuousListening(id,signal,observers,mode),submitInput:async()=>({status:'submitted'}),interruptReply:()=>true,isPlaybackBusy:()=>playing,onUpdate:v=>views.push(v)});
 const advance=async ms=>{clock+=ms;for(const[id,t]of [...timers])if(t.at<=clock){timers.delete(id);t.fn();}await flush();};
 const pcm=async(ms,amplitude=.12)=>{const end=frame+Math.round(rate*ms/1000);while(frame+128<=end){contextGlobals.currentFrame=frame;const source=Float32Array.from({length:128},(_,i)=>amplitude*Math.sin(2*Math.PI*173*(frame+i)/rate)+.003*Math.sin(2*Math.PI*43*(frame+i)/rate));processor.process([[source]],[[new Float32Array(128)]]);frame+=128;await advance(128000/rate);}};
 const ready=()=>socket.message({type:'ready',lease_id:lease,sample_rate_hz:16000,max_seconds:120,max_samples:1920000,max_utterances:12,max_streams_per_session:4,max_total_streams:8,session_lease_starts_used:1,total_lease_starts_used:1,endpoint_mode:'google_vad_offsets_natural',manual_commit_required:false,client_endpoint_supported:true,client_silence_ms:700,drain_timeout_ms:2000,max_recognition_streams:12});
 return{controller,transport,socket,sent,views,chunks,captureErrors,ready,pcm,advance,setPlaying:value=>playing=value,counts:()=>({trackStops,requests,frame}),clock:()=>clock};
}

for(const rate of [44100,48000])for(const batch of [20,40])test(`real ${rate} Hz worklet/${batch} ms startup audio drains without a WebSocket burst`,async()=>{
 const h=harness(rate,batch);try{h.controller.start();h.socket.open();await flush();await h.pcm(1600);assert.equal(h.controller.active,true);h.ready();await flush();
 assert.equal(h.controller.active,true,JSON.stringify(h.views.at(-1)));assert.deepEqual(h.captureErrors,[]);assert.equal(h.counts().trackStops,0);
 for(let i=0;i<400;i++)await h.advance(10);
 const audio=h.sent.filter(p=>p.type==='audio');assert.equal(audio.length,h.chunks.length);assert.ok(audio.every((p,i)=>p.sequence===i+1));assert.ok(audio.every((p,i)=>p.first_sample===h.chunks[i].startSample));
 assert.ok(audio.at(-1).at-audio[0].at>=1400,'a delayed ready must not burst 1.6 seconds of PCM');
 }finally{h.transport.close();await h.controller.close();}
});

for(const rate of [44100,48000])test(`real ${rate} Hz worklet preserves more than one minute of speech and short breathing pauses`,async()=>{
 const h=harness(rate,20);try{h.controller.start();h.socket.open();await flush();h.ready();await flush();
 for(let i=0;i<65;i++){await h.pcm(800);await h.pcm(200,.001);}
 assert.equal(h.controller.active,true,JSON.stringify(h.views.at(-1)));assert.deepEqual(h.captureErrors,[]);assert.equal(h.counts().requests,1);assert.equal(h.counts().trackStops,0);assert.equal(h.sent.filter(p=>p.type==='client_endpoint').length,0);
 const audio=h.sent.filter(p=>p.type==='audio');assert.ok(h.chunks.at(-1).endSample>16000*60);assert.equal(audio.length,h.chunks.length);let frontier=0;
 for(const [i,packet]of audio.entries()){assert.equal(packet.sequence,i+1);assert.equal(packet.first_sample,frontier);frontier+=Buffer.from(packet.pcm_base64,'base64').length/2;}
 assert.equal(frontier,h.chunks.at(-1).endSample);assert.equal(frontier,Math.floor(h.chunks.length*rate*.02*16000/rate));
 }finally{h.transport.close();await h.controller.close();}
});

test('resumed speech cancels an endpoint still behind startup PCM without releasing capture',async()=>{
 const h=harness();try{h.controller.start();h.socket.open();await flush();await h.pcm(400);await h.pcm(800,.001);h.ready();await flush();
 assert.equal(h.sent.filter(p=>p.type==='client_endpoint').length,0);await h.pcm(120);
 assert.equal(h.controller.active,true);assert.equal(h.counts().trackStops,0);assert.equal(h.sent.filter(p=>p.type==='cancel_endpoint').length,0);
 for(let i=0;i<150;i++)await h.advance(10);
 assert.equal(h.sent.filter(p=>p.type==='client_endpoint').length,0,'cancelled unsent endpoint never reaches the backend');
 assert.equal(h.sent.filter(p=>p.type==='audio').length,h.chunks.length);assert.deepEqual(h.captureErrors,[]);
 }finally{h.transport.close();await h.controller.close();}
});

test('server endpoint drain receives its finite window after paced startup delivery',async()=>{
 const h=harness();try{h.controller.start();h.socket.open();await flush();await h.pcm(400);await h.pcm(1200,.001);h.ready();await flush();
 for(let i=0;i<160;i++)await h.advance(10);
 const ep=h.sent.find(p=>p.type==='client_endpoint');assert.ok(ep);
 h.socket.message({type:'endpoint_status',lease_id:lease,endpoint_id:ep.endpoint_id,source_end_sample:ep.source_end_sample,state:'queued'});
 await h.advance(2000);assert.equal(h.controller.active,true,'PCM delivery lag must not consume the provider final-drain window');
 h.socket.message({type:'endpoint_status',lease_id:lease,endpoint_id:ep.endpoint_id,source_end_sample:ep.source_end_sample,state:'queued'});
 await h.advance(1001);assert.equal(h.controller.active,false,'repeated queued status never extends the finite drain');
 assert.match(h.views.at(-1).error,/转写超时/);assert.equal(h.counts().trackStops,1);
 }finally{h.transport.close();await h.controller.close();}
});

test('resumed speech during endpoint drain is held and recognition restarts on the same microphone',async()=>{
 const h=harness();try{h.controller.start();h.socket.open();await flush();h.ready();await flush();await h.pcm(400);await h.pcm(800,.001);
 const ep=h.sent.find(p=>p.type==='client_endpoint');assert.ok(ep);
 for(const state of ['queued','draining'])h.socket.message({type:'endpoint_status',lease_id:lease,endpoint_id:ep.endpoint_id,source_end_sample:ep.source_end_sample,state});
 await h.pcm(120);assert.equal(h.sent.filter(p=>p.type==='cancel_endpoint').length,1);assert.equal(h.counts().trackStops,0);
 h.socket.message({type:'endpoint_status',lease_id:lease,endpoint_id:ep.endpoint_id,source_end_sample:ep.source_end_sample,state:'draining'});
 h.socket.message({type:'endpoint_status',lease_id:lease,endpoint_id:ep.endpoint_id,source_end_sample:ep.source_end_sample,state:'completed'});
 const uid='52345678-1234-4234-8234-123456789012';
 h.socket.message({type:'utterance_ready',lease_id:lease,utterance_id:uid,revision:1,text:'synthetic retained prefix',begin_offset_samples:0,end_offset_samples:ep.source_end_sample,source_end_sample:ep.source_end_sample,final_offset_samples:null,endpoint_basis:'client_silence_finalized',client_endpoint_id:ep.endpoint_id});
 await flush();assert.equal(h.sent.filter(p=>p.type==='commit').length,0);assert.equal(h.sent.filter(p=>p.type==='hold').length,1);
 h.socket.message({type:'utterance_held',lease_id:lease,utterance_id:uid,revision:1,text:'synthetic retained prefix'});
 h.socket.message({type:'recognition_status',lease_id:lease,stream_index:2,state:'opening'});await flush();await h.pcm(400);await h.pcm(800,.001);
 assert.equal(h.controller.active,true);assert.equal(h.counts().requests,1);assert.equal(h.counts().trackStops,0);assert.equal(h.sent.filter(p=>p.type==='client_endpoint').length,2);assert.deepEqual(h.captureErrors,[]);
 assert.equal(h.views.at(-1).held_previews.length,1);
 }finally{h.transport.close();await h.controller.close();}
});

test('bounded backlog and finite duration end visibly without a generic consumer failure',async()=>{
 const h=harness();try{h.controller.start();h.socket.open();await flush();h.ready();await flush();h.socket.bufferedAmount=65536;await h.pcm(2400);
 assert.equal(h.controller.active,false);assert.match(h.views.at(-1).error,/delivery fell behind/);assert.deepEqual(h.captureErrors,[]);assert.equal(h.counts().trackStops,1);
 }finally{h.transport.close();await h.controller.close();}
 const f=harness();try{f.controller.start();f.socket.open();await flush();f.ready();await flush();await f.advance(120000);
 assert.equal(f.controller.active,false);assert.equal(f.views.at(-1).state,'limit');assert.deepEqual(f.captureErrors,[]);assert.equal(f.counts().trackStops,1);
 }finally{f.transport.close();await f.controller.close();}
});

test('ready cannot resurrect listening after draining startup audio has already failed',async()=>{
 const h=harness();try{h.controller.start();h.socket.open();await flush();await h.pcm(400);h.socket.bufferedAmount=65537;h.ready();await flush();
 assert.equal(h.controller.active,false);assert.equal(h.views.at(-1).state,'error');assert.equal(h.views.at(-1).lease_id,null);assert.deepEqual(h.captureErrors,[]);
 }finally{h.transport.close();await h.controller.close();}
});

for(const audible of [false,true])test(`conservative playback ${audible?'audible capture requires review':'quiet room PCM does not contaminate later speech'}`,async()=>{
 const h=harness(48000,40,'guarded');try{h.controller.start();h.socket.open();await flush();h.ready();await flush();await h.pcm(800,.003);
 h.setPlaying(true);await h.pcm(400,audible?.02:.003);h.setPlaying(false);await h.pcm(400);await h.pcm(800,.001);
 const ep=h.sent.find(p=>p.type==='client_endpoint');assert.ok(ep);
 h.socket.message({type:'endpoint_status',lease_id:lease,endpoint_id:ep.endpoint_id,source_end_sample:ep.source_end_sample,state:'completed'});
 h.socket.message({type:'utterance_ready',lease_id:lease,utterance_id:'52345678-1234-4234-8234-123456789012',revision:1,text:'synthetic next phrase',begin_offset_samples:0,end_offset_samples:ep.source_end_sample,source_end_sample:ep.source_end_sample,final_offset_samples:null,endpoint_basis:'client_silence_finalized',client_endpoint_id:ep.endpoint_id});await flush();
 assert.equal(h.sent.filter(p=>p.type==='commit').length,audible?0:1);
 assert.equal(h.sent.filter(p=>p.type==='hold').length,audible?1:0);assert.equal(h.counts().trackStops,0);
 }finally{h.transport.close();await h.controller.close();}
});
