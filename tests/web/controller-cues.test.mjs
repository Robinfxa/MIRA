import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {SessionController}=await import(new URL('features/session/controller.js',dist));
const {CancelSafePlayback}=await import(new URL('features/audio/playback.js',dist));
const {PresentationGate}=await import(new URL('features/presentation/permit-gate.js',dist));
const {parseSession}=await import(new URL('shared/protocol.js',dist));
const {safeSessionError}=await import(new URL('features/diagnostics/status.js',dist));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const effect=(id,kind,cue,speech,value=id)=>({id,kind,value,digest:'a'.repeat(64),output_epoch:1,activity_seq:1,cue_id:cue,cue_speech_id:speech});
const cue=(n)=>[effect(`s${n}`,'speech',`c${n}`,`s${n}`,`spoken ${n}`),effect(`t${n}`,'subtitle',`c${n}`,`s${n}`,`different caption ${n}`)];
function harness(grants=[...cue(1),...cue(2)]){
 let client,revision=0,current,blockedResume=null;const sources=[],streams=[],receipts=[],progress=[],shown=[],errors=[],phases=[],timers=new Set();
 const session=(patch={})=>({schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:client,revision:++revision,activity_seq:0,input_epoch:0,output_epoch:0,permit_revision:revision,phase:'stopped',request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null,...patch});
 const api={create:async c=>{client=c;return {session:session(),session_token:'synthetic'}},capabilities:async()=>({speech_enabled:true,microphone_enabled:false,speech_sample_rate_hz:24000,microphone_sample_rate_hz:16000,qualification:'injected_unverified',generation_mode:'injected'}),snapshot:()=>new Promise(()=>{}),input:async r=>(current=session({activity_seq:r.activity_seq,input_epoch:r.activity_seq,output_epoch:r.activity_seq,phase:'ready',request_id:r.request_id,active_grants:grants})),receipt:async r=>{receipts.push(r);return current},audioProgress:async p=>{progress.push(p);return current},speech:async(e,signal,push)=>{const done=deferred();streams.push({e,signal,push,done});await done.promise},stop:async r=>session({activity_seq:r.activity_seq}),close:async()=>{}};
 const context={destination:{},resume:async()=>{if(blockedResume)await blockedResume.promise},close:async()=>{},createBuffer:(_c,n)=>({getChannelData:()=>new Float32Array(n)}),createBufferSource:()=>{const source={onended:null,started:0,stopped:0,connect(){},disconnect(){},start(){this.started++},stop(){this.stopped++}};sources.push(source);return source}};
 const controller=new SessionController(api,{apply:e=>shown.push(e),prepare:async()=>{},prepareInput(){},stop(){},setPhase:p=>phases.push(p)},{connected(){},update:s=>{if(s.last_error)errors.push(safeSessionError(s.last_error))},error:e=>errors.push(e),localStop(){}},{apiBase:'/api/v1',pollIntervalMs:200},{createPlayback:o=>new CancelSafePlayback({...o,createContext:()=>context,setInterval:f=>{timers.add(f);return f},clearInterval:t=>timers.delete(t)}),createCapture:()=>({start:async()=>false,stop(){},close:async()=>{}})});
 return {controller,api,sources,streams,receipts,progress,shown,errors,phases,timers,session,get current(){return current},blockResume(){blockedResume=deferred();return blockedResume},async start(){await controller.connect();await controller.input('two bounded cues');await tick()},async close(){await controller.close();assert.equal(timers.size,0)}};
}

test('captions wait for their own actual source submission, never grant or queued PCM',async()=>{const h=harness();try{await h.start();assert.equal(h.streams.length,1);assert.deepEqual(h.shown,[]);const resume=h.blockResume();await h.streams[0].push(new Int16Array(2));await tick();assert.deepEqual(h.shown,[]);assert.deepEqual(h.receipts,[]);resume.resolve();await tick();assert.equal(h.sources[0].started,1);assert.deepEqual(h.shown.map(e=>e.id),['t1']);assert.deepEqual(h.receipts.map(e=>e.effect_id),['t1']);assert.equal(h.progress.length,0);h.streams[0].done.resolve();await tick();h.sources[0].onended();await tick();assert.equal(h.streams.length,2);assert.deepEqual(h.shown.map(e=>e.id),['t1']);await h.streams[1].push(new Int16Array(2));await tick();assert.deepEqual(h.shown.map(e=>e.id),['t1','t2']);assert.deepEqual(h.receipts.map(e=>e.effect_id),['t1','t2']);}finally{await h.close()}});

test('independent visual and standalone text cues remain immediate while authored speech controls wait',async()=>{const h=harness([...cue(1),effect('pose','pose','c1','s1','camera_lowered'),effect('photo','media','photo',null,'trip_photo_placeholder'),effect('scene','scene','visual',null,'rain_window'),effect('text','subtitle','text',null,'standalone')]);try{await h.start();assert.deepEqual(h.shown.map(e=>e.id),['photo','scene','text']);await h.streams[0].push(new Int16Array(2));await tick();assert.deepEqual(h.shown.map(e=>e.id),['photo','scene','text','t1','pose']);await h.controller.stop();assert.deepEqual(h.shown.filter(e=>e.kind==='scene'||e.kind==='media').map(e=>e.id),['photo','scene']);}finally{await h.close()}});

test('Stop before cue two source prevents its subtitle receipt and stale submissions',async()=>{const h=harness();try{await h.start();await h.streams[0].push(new Int16Array(2));h.streams[0].done.resolve();await tick();h.sources[0].onended();await tick();assert.equal(h.streams.length,2);await h.controller.stop();await assert.rejects(h.streams[1].push(new Int16Array(2)));await tick();assert.deepEqual(h.shown.map(e=>e.id),['t1']);assert.deepEqual(h.receipts.map(e=>e.effect_id),['t1']);}finally{await h.close()}});

test('Stop during pending source resume prevents even first caption and receipt',async()=>{const h=harness();try{await h.start();const resume=h.blockResume();await h.streams[0].push(new Int16Array(2));await h.controller.stop();resume.resolve();await tick();assert.equal(h.sources.length,0);assert.deepEqual(h.shown,[]);assert.deepEqual(h.receipts,[])}finally{await h.close()}});

test('backpressure and repeated snapshots never advance captions before cue completion',async()=>{const h=harness();try{await h.start();for(let i=0;i<16;i++)await h.streams[0].push(new Int16Array(6000));await tick();let accepted=false;const blocked=h.streams[0].push(new Int16Array(6000)).then(()=>accepted=true);void blocked.catch(()=>{});await tick();assert.equal(accepted,false);h.controller.install({...h.current,revision:h.current.revision+1});assert.deepEqual(h.shown.map(e=>e.id),['t1']);h.sources[0].onended();await blocked;await tick();assert.deepEqual(h.shown.map(e=>e.id),['t1']);assert.deepEqual(h.receipts.map(e=>e.effect_id),['t1']);}finally{await h.close()}});

test('revocation before source submission blocks all future cue captions',async()=>{const h=harness();try{await h.start();const resume=h.blockResume();await h.streams[0].push(new Int16Array(2));h.controller.install({...h.current,revision:h.current.revision+1,permit_revision:h.current.permit_revision+1,active_grants:[]});resume.resolve();await tick();assert.deepEqual(h.shown,[]);assert.deepEqual(h.receipts,[]);assert.equal(h.sources.length,0)}finally{await h.close()}});

for(const code of ['generation_timeout','unknown-server-private-string'])test(`session error ${code} retains safe localized copy`,async()=>{const h=harness();try{await h.start();h.controller.install({...h.current,revision:h.current.revision+1,permit_revision:h.current.permit_revision+1,phase:'error',request_id:null,active_grants:[],last_error:code});assert.equal(h.errors.at(-1),safeSessionError(code));assert.equal(h.errors.some(e=>e.includes(code)),false);assert.deepEqual(h.shown,[])}finally{await h.close()}});

function snapshot(grants){return {schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:'c',revision:1,activity_seq:1,input_epoch:1,output_epoch:1,permit_revision:1,phase:'ready',request_id:'r',sealed:true,active_grants:grants,presented_effects:[],audio_progress:[],last_error:null}}
const malformed=[
 ['missing speech peer',[effect('t','subtitle','c','missing')]],
 ['wrong cue peer',[cue(1)[0],effect('t','subtitle','other','s1')]],
 ['speech points elsewhere',[{...cue(1)[0],cue_speech_id:'other'}]],
 ['cue has mixed dependency',[...cue(1),effect('pose','pose','c1',null)]],
 ['two captions',[...cue(1),effect('t-other','subtitle','c1','s1')]],
 ['two speeches',[...cue(1),effect('s-other','speech','c1','s1')]],
 ['invalid field type',[{...cue(1)[0],cue_id:7}]],
 ['duplicate effect identity',[...cue(1),cue(1)[0]]],
 ['ambiguous legacy mixture',[{...cue(1)[0],cue_id:null,cue_speech_id:null},{...cue(1)[1],cue_id:null,cue_speech_id:null}]],
];
for(const [name,grants]of malformed)test(`cue metadata fails closed: ${name}`,()=>{assert.throws(()=>parseSession(snapshot(grants)));const gate=new PresentationGate('s','c');gate.beginInput('r');assert.throws(()=>gate.install(snapshot(grants)));assert.equal(gate.allows(grants[0]),false)});

test('cue metadata is immutable across revisions and caller substitutions',()=>{const gate=new PresentationGate('s','c');gate.beginInput('r');const grants=cue(1);gate.install(snapshot(grants));assert.equal(gate.claimSpeech({...grants[0],cue_id:'forged'}),false);assert.throws(()=>gate.install({...snapshot(grants.map(e=>({...e,cue_id:'mutated'}))),revision:2,permit_revision:2}));assert.equal(gate.allows(grants[0]),false)});

test('presented subtitle history may omit speech peer and legacy visual-only is safe',()=>{const parsed=parseSession({...snapshot([]),presented_effects:[cue(1)[1]]});assert.equal(parsed.presented_effects.length,1);const legacy={...effect('legacy','subtitle',null,null)};delete legacy.cue_id;delete legacy.cue_speech_id;const gate=new PresentationGate('s','c');gate.beginInput('r');gate.install(parseSession(snapshot([legacy])));assert.ok(gate.consume(legacy));assert.equal(parseSession(snapshot([{...cue(1)[0],cue_id:null,cue_speech_id:null}])).active_grants.length,1)});

test('controller Stop preserves actual rendered scene and photo but never future cue text',async()=>{
 const {SceneEffectExecutor}=await import(new URL('features/presentation/scene-executor.js',dist));
 const slots=new Map(['subtitle','photo','pose','scene-label','phase-label','character-description'].map(name=>[name,{textContent:'',hidden:true}]));
 const image={complete:true,naturalWidth:600,naturalHeight:460,decode:async()=>{},getAttribute:()=>'/assets/scene/cafe-night.svg'};
 const stage={dataset:{},querySelector:selector=>(selector==='[data-photo] img'||selector==='[data-scene-source="classic"]')?image:slots.get(selector.replace(/^\[data-|\]$/g,''))};
 const executor=new SceneEffectExecutor(stage);
 const h=harness([effect('photo','media','photo',null,'trip_photo_placeholder'),effect('scene','scene','scene',null,'rain_window'),...cue(1),...cue(2)]);
 h.controller.effects=executor;
 try{await h.start();assert.equal(slots.get('photo').hidden,false);assert.equal(stage.dataset.scene,'rain_window');await h.streams[0].push(new Int16Array(2));await tick();assert.equal(slots.get('subtitle').textContent,'different caption 1');await h.controller.stop();assert.equal(slots.get('photo').hidden,false);assert.equal(stage.dataset.scene,'rain_window');assert.equal(slots.get('subtitle').textContent.includes('different caption 2'),false);assert.deepEqual(h.receipts.map(e=>e.effect_id),['photo','scene','t1'])}finally{await h.close()}
});

test('malformed cue replacement synchronously disconnects current source before callbacks',async()=>{const h=harness();try{await h.start();await h.streams[0].push(new Int16Array(2));await tick();const end=h.sources[0].onended;h.controller.install({...h.current,revision:h.current.revision+1,permit_revision:h.current.permit_revision+1,active_grants:h.current.active_grants.map(e=>e.id==='t2'?{...e,cue_id:'wrong'}:e)});assert.equal(h.sources[0].stopped,1);end();await tick();assert.deepEqual(h.shown.map(e=>e.id),['t1']);assert.equal(h.streams.length,1)}finally{await h.close()}});

test('new input while future cue PCM waits cannot present the old cue',async()=>{const h=harness();try{await h.start();await h.streams[0].push(new Int16Array(2));h.streams[0].done.resolve();await tick();h.sources[0].onended();await tick();const old=h.streams[1],resume=h.blockResume();await old.push(new Int16Array(2));h.api.input=async r=>h.session({activity_seq:r.activity_seq,input_epoch:r.activity_seq,output_epoch:r.activity_seq,phase:'ready',request_id:r.request_id,active_grants:[]});await h.controller.input('new question');resume.resolve();await tick();assert.equal(h.sources.length,1);assert.deepEqual(h.shown.map(e=>e.id),['t1']);assert.deepEqual(h.receipts.map(e=>e.effect_id),['t1'])}finally{await h.close()}});

test('submitted cue opening rejects mismatched origins, empty counters and terminal speech',()=>{const grants=cue(1);const gate=new PresentationGate('s','c');gate.beginInput('r');gate.install(snapshot(grants));gate.claimSpeech(grants[0]);const fact={origin:grants[0],stage:'submitted',sampleRate:24000,submittedFrames:2,renderedFrames:0,inFlightFramesUncertain:2};for(const patch of [{origin:{...grants[0],output_epoch:2}},{origin:{...grants[0],activity_seq:2}},{origin:{...grants[0],digest:'b'.repeat(64)}},{sampleRate:16000},{submittedFrames:0},{submittedFrames:NaN}])assert.equal(gate.submitSpeech({...fact,...patch}),false);assert.equal(gate.consume(grants[1]),null);assert.equal(gate.submitSpeech(fact),true);assert.equal(gate.submitSpeech(fact),false);assert.ok(gate.consume(grants[1]));assert.equal(gate.consume(grants[1]),null);gate.audioProgress({...fact,stage:'stopped',reason:'error'});assert.equal(gate.submitSpeech(fact),false)});

test('HTTP safe error request ID survives controller error handling',async()=>{const {safeHttpError}=await import(new URL('features/diagnostics/status.js',dist));const h=harness();try{await h.controller.connect();const id='12345678-1234-1234-1234-123456789abc',safe=safeHttpError(503,id);h.api.input=async()=>{throw new Error(safe)};await h.controller.input('hello');assert.equal(h.errors.at(-1),safe);assert.ok(h.errors.at(-1).includes(id))}finally{await h.close()}});

for(const code of ['constructor','toString','__proto__'])test(`prototype-like unknown session code ${code} uses actionable fallback`,async()=>{const h=harness();try{const fallback=safeSessionError('unknown-server-private-string');assert.equal(safeSessionError(code),fallback);await h.start();h.controller.install({...h.current,revision:h.current.revision+1,permit_revision:h.current.permit_revision+1,phase:'error',request_id:null,active_grants:[],last_error:code});assert.equal(h.errors.at(-1),fallback);assert.equal(typeof h.errors.at(-1),'string')}finally{await h.close()}});
