import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST??'apps/web/dist')+'/').href;
const {ContinuousListeningController}=await import(new URL('features/session/continuous-listening.js',dist));
const lease='12345678-1234-4234-8234-123456789012';
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function harness(){let capture,observer,id=0,sample=0,sequence=0;const endpoints=[],cancels=[],inputs=[],views=[],timers=new Map();let time=0,timerId=0;
 const ready={lease_id:lease,sample_rate_hz:16000,max_seconds:120,max_samples:1920000,max_utterances:12,max_streams_per_session:4,max_total_streams:8,session_lease_starts_used:1,total_lease_starts_used:1,endpoint_mode:'google_vad_offsets_natural',manual_commit_required:false,client_endpoint_supported:true,client_silence_ms:700,drain_timeout_ms:2000,max_recognition_streams:4};
 const controller=new ContinuousListeningController({mode:'natural',createId:()=>id++===0?lease:`${String(id+2).padStart(8,'0')}-1234-4234-8234-123456789012`,setTimer:(fn,ms)=>{const n=++timerId;timers.set(n,{fn,at:time+ms});return n;},clearTimer:n=>timers.delete(n),createCapture:o=>{capture=o;return{start(){o.onState('recording');return Promise.resolve(true);},stop(){},async close(){}};},openStream:(_l,_s,o)=>{observer=o;return{ready:Promise.resolve(ready),closed:new Promise(()=>{}),send(){},endpoint:(eid,end)=>endpoints.push({eid,end}),cancelEndpoint:eid=>{cancels.push(eid);queueMicrotask(()=>o.onEvent({type:'endpoint_status',lease_id:lease,endpoint_id:eid,source_end_sample:endpoints.at(-1).end,state:'cancelled'}));},commit:async(cid,rev,uid)=>({type:'commit_ready',lease_id:lease,commit_id:cid,revision:rev,utterance_id:uid,segment_seq:1,text:'quiet words'}),hold:async()=>{},stop:async()=>{},cancel(){}};},submitInput:async(text,id)=>{inputs.push({text,id});return{status:'submitted'};},interruptReply:()=>true,isPlaybackBusy:()=>false,onUpdate:v=>views.push(v)});
 return{controller,endpoints,cancels,inputs,views,emit:e=>observer.onEvent(e),text:(text='quiet words',revision=1)=>observer.onEvent({type:'transcript',lease_id:lease,revision,text,is_final:false}),pcm:(rms,ms=40)=>{const count=ms*16,pcm=new Int16Array(count).fill(rms);capture.onChunk({pcm16le:new Uint8Array(pcm.buffer),sampleRate:16000,channels:1,sequence:sequence++,startSample:sample,endSample:sample+=count});},tick:ms=>{time+=ms;for(const[n,t]of timers)if(t.at<=time){timers.delete(n);t.fn();}}};}
async function started(){const h=harness();h.controller.start();await flush();return h;}
test('captured quiet requests an endpoint without Google END or final and revisions do not reset silence',async()=>{const h=await started();for(let i=0;i<4;i++)h.pcm(1200);h.text();for(let i=0;i<17;i++){h.pcm(0);h.text('quiet words '+i,i+2);}assert.equal(h.endpoints.length,0);h.pcm(0);assert.equal(h.endpoints.length,1);assert.equal(h.endpoints[0].end,14080);await h.controller.stop();});
test('low voice with ASR backup ends; silence and short noise without text do not',async()=>{const h=await started();for(let i=0;i<30;i++)h.pcm(0);h.pcm(1500);for(let i=0;i<18;i++)h.pcm(0);assert.equal(h.endpoints.length,0);for(let i=0;i<5;i++)h.pcm(180);h.text();for(let i=0;i<18;i++)h.pcm(0);assert.equal(h.endpoints.length,1);await h.controller.stop();});
test('resumed voice cancels the exact pending endpoint and drain timeout preserves text',async()=>{const h=await started();for(let i=0;i<4;i++)h.pcm(1200);h.text();for(let i=0;i<18;i++)h.pcm(0);h.pcm(1200);h.pcm(1200);assert.deepEqual(h.cancels,[h.endpoints[0].eid]);await flush();for(let i=0;i<18;i++)h.pcm(0);assert.equal(h.endpoints.length,2);h.tick(3000);assert.equal(h.controller.active,false);assert.match(h.views.at(-1).notice??h.views.at(-1).error,/文字|转写/);assert.equal(h.inputs.length,0);assert.ok(h.views.at(-1).previous_previews.some(v=>v.text==='quiet words'));});
test('reply quiet wait is finite and stop fences a pending wait',async()=>{const h=await started();h.pcm(1200);h.pcm(1200);let resolved;const wait=h.controller.waitForReplyQuiet(new AbortController().signal).then(v=>resolved=v);await flush();assert.equal(resolved,undefined);for(let i=0;i<18;i++)h.pcm(0);await wait;assert.equal(resolved,true);h.pcm(1200);h.pcm(1200);const stopped=h.controller.waitForReplyQuiet(new AbortController().signal);await h.controller.stop();assert.equal(await stopped,false);});

test('missing provider END and offsets still accept the exact locally finalized utterance once',async()=>{
 const h=await started();for(let i=0;i<4;i++)h.pcm(1200);h.text();for(let i=0;i<18;i++)h.pcm(0);
 const ep=h.endpoints[0],event={type:'utterance_ready',lease_id:lease,utterance_id:'22345678-1234-4234-8234-123456789012',revision:1,text:'quiet words',begin_offset_samples:0,end_offset_samples:ep.end,source_end_sample:ep.end,final_offset_samples:null,endpoint_basis:'client_silence_finalized',client_endpoint_id:ep.eid};
 h.emit({type:'endpoint_status',lease_id:lease,endpoint_id:ep.eid,source_end_sample:ep.end,state:'completed'});h.emit(event);await flush();h.emit(event);await flush();
 assert.equal(h.inputs.length,1);assert.equal(h.inputs[0].text,'quiet words');assert.equal(h.controller.active,true);
 for(let i=0;i<30;i++)h.pcm(0);assert.equal(h.endpoints.length,1,'silence alone never repeats accepted words');await h.controller.stop();
});

test('quiet waiter times out and aborts without requiring a provider event',async()=>{
 const h=await started();h.pcm(1200);h.pcm(1200);const pending=h.controller.waitForReplyQuiet(new AbortController().signal);h.tick(10000);assert.equal(await pending,false);
 const abort=new AbortController(),cancelled=h.controller.waitForReplyQuiet(abort.signal);abort.abort();assert.equal(await cancelled,false);await h.controller.close();
});

const {BrowserAudioTransport}=await import(new URL('features/session/audio-transport.js',dist));
class Socket{readyState=0;bufferedAmount=0;sent=[];send(text){this.sent.push(JSON.parse(text));}close(){this.readyState=3;}open(){this.readyState=1;this.onopen?.({});}message(frame){this.onmessage?.({data:JSON.stringify(frame)});}}
function wire(){const socket=new Socket(),events=[],errors=[];const transport=new BrowserAudioTransport({apiBase:'/api/v1'},()=>({sessionId:'s',token:'synthetic'}),{createSocket:()=>socket,baseUrl:'https://mira.test/'});const stream=transport.continuousListening(lease,new AbortController().signal,{onEvent:e=>events.push(e),onError:e=>errors.push(e)},'natural');socket.open();socket.message({type:'ready',lease_id:lease,sample_rate_hz:16000,max_seconds:120,max_samples:1920000,max_utterances:12,max_streams_per_session:4,max_total_streams:8,session_lease_starts_used:1,total_lease_starts_used:1,endpoint_mode:'google_vad_offsets_natural',manual_commit_required:false,client_endpoint_supported:true,client_silence_ms:700,drain_timeout_ms:2000});return{socket,events,errors,transport,stream};}
test('real transport sends ordered exact capture endpoint and accepts no-offset correlated final',async()=>{
 const h=wire(),ep='32345678-1234-4234-8234-123456789012';try{await h.stream.ready;
 assert.equal(h.socket.sent[0].client_endpointing,true);
 h.stream.send({pcm16le:new Uint8Array(1280),sampleRate:16000,channels:1,sequence:0,startSample:0,endSample:640});h.stream.endpoint(ep,640);h.stream.endpoint(ep,640);
 assert.deepEqual(h.socket.sent.at(-1),{type:'client_endpoint',lease_id:lease,endpoint_id:ep,source_end_sample:640});assert.equal(h.socket.sent.filter(e=>e.type==='client_endpoint').length,1);
 h.socket.message({type:'endpoint_status',lease_id:lease,endpoint_id:ep,source_end_sample:640,state:'draining'});h.stream.cancelEndpoint(ep);h.stream.cancelEndpoint(ep);
 assert.equal(h.socket.sent.filter(e=>e.type==='cancel_endpoint').length,1);
 h.socket.message({type:'endpoint_status',lease_id:lease,endpoint_id:ep,source_end_sample:640,state:'completed'});
 h.socket.message({type:'utterance_ready',lease_id:lease,utterance_id:'22345678-1234-4234-8234-123456789012',revision:1,text:'quiet words',begin_offset_samples:0,end_offset_samples:640,source_end_sample:640,final_offset_samples:null,endpoint_basis:'client_silence_finalized',client_endpoint_id:ep});
 assert.equal(h.events.at(-1).client_endpoint_id,ep);assert.deepEqual(h.errors,[]);
 }finally{h.transport.close();}
});
test('real transport rejects wrong frontier, uncorrelated endpoint readiness and invalid silence defaults',async t=>{
 for(const kind of ['frontier','unknown-endpoint','wrong-status-frontier','invalid-silence'])await t.test(kind,async()=>{const h=wire();try{await h.stream.ready;
 h.stream.send({pcm16le:new Uint8Array(1280),sampleRate:16000,channels:1,sequence:0,startSample:0,endSample:640});const ep='32345678-1234-4234-8234-123456789012';
 if(kind==='frontier'){assert.throws(()=>h.stream.endpoint(ep,641));assert.equal(h.socket.sent.filter(x=>x.type==='client_endpoint').length,0);}
 else if(kind==='wrong-status-frontier'){h.stream.endpoint(ep,640);h.socket.message({type:'endpoint_status',lease_id:lease,endpoint_id:ep,source_end_sample:639,state:'completed'});assert.equal(h.errors.length,1);}
 else if(kind==='unknown-endpoint'){h.socket.message({type:'utterance_ready',lease_id:lease,utterance_id:'22345678-1234-4234-8234-123456789012',revision:1,text:'quiet words',begin_offset_samples:0,end_offset_samples:640,source_end_sample:640,final_offset_samples:null,endpoint_basis:'client_silence_finalized',client_endpoint_id:ep});assert.equal(h.errors.length,1);}
 else {assert.throws(()=>new ContinuousListeningController({silenceMilliseconds:249,onUpdate(){}}),RangeError);assert.throws(()=>new ContinuousListeningController({silenceMilliseconds:2001,onUpdate(){}}),RangeError);}
 }finally{h.transport.close();}});
});


test('steady low background before and after speech reaches captured quiet without waiting for lease expiry',async()=>{
 const h=await started();for(let i=0;i<20;i++)h.pcm(120);for(let i=0;i<5;i++)h.pcm(1200);h.text();
 for(let i=0;i<18;i++)h.pcm(120);assert.equal(h.endpoints.length,1);await h.controller.stop();
});

test('new low background after a strong voice uses hysteresis and bounded floor adaptation',async()=>{
 const h=await started();for(let i=0;i<5;i++)h.pcm(1200);h.text();for(let i=0;i<18;i++)h.pcm(120);
 assert.equal(h.endpoints.length,1);await h.controller.stop();
});
