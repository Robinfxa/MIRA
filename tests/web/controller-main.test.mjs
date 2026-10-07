import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import vm from 'node:vm';
const dist=process.env.MIRA_TEST_WEB_DIST?resolve(process.env.MIRA_TEST_WEB_DIST):resolve('apps/web/dist');
const source=(await readFile(resolve(dist,'app/main-source.js'),'utf8')).replace(/^import .*;\n/gm,'');
const {MiraHttpError}=await import(new URL('features/session/api-client.js','file://'+dist+'/'));
const {safeHttpError}=await import(new URL('features/diagnostics/status.js','file://'+dist+'/'));
const markup=await readFile(new URL('../../apps/web/index.html',import.meta.url),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};}
function app(connectBehavior=null, codeNative=false){const calls=[],inputs=[];let inputResult=Promise.resolve({status:'submitted'}),captureFinishResult=Promise.resolve(undefined),continuousInstance;const nodes=new Map();class Node {listeners={};disabled=false;hidden=false;checked=false;dataset={};value='';textContent='';children=[];addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}fire(name,patch={}){const e={defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},button:0,pointerId:1,...patch};for(const fn of this.listeners[name]??[])fn(e);return e;}requestSubmit(){this.fire('submit');}setAttribute(name,value){this[name]=value;}focus(){}setPointerCapture(){}releasePointerCapture(){}hasPointerCapture(){return true;}replaceChildren(...items){this.children=items;}append(...items){this.children.push(...items);}}
for(const selector of ['[data-code-mock-controls]','[data-connect-retry]','[data-connection-status]','[data-send-message]','[data-operator-pairing-form]','form[data-memory-management-record-form]','[data-status]','[data-diagnostic]','[data-error]','[data-system-notice]','[data-system-notice-body]','[data-stage]','fieldset','form.composer','[name=message]','[data-stop]','[data-close]','[data-ptt]','[data-continuous-listening]','[data-continuous-panel]','[data-continuous-status]','[data-continuous-preview]','[data-continuous-interrupt]','[data-continuous-send]','[data-recovered-input-notice]','[data-recovered-input-label]','[data-recovered-new-topic]','[data-continuous-sent-text]','[data-continuous-recording-limit]','[data-continuous-review-block]','[data-microphone-preview]','[data-microphone-timing-panel]','[data-microphone-timing]','[data-voice-hint]','[data-mode-label]','[data-mode-description]','[data-recording-notice]','[data-review-audio-notice]','[data-review-audio-status]','[data-review-audio-scope]','[data-review-audio-eligibility]','[data-review-audio-consent]','[data-review-audio-enable]','[data-review-audio-disable]','[data-review-audio-review]','[data-review-audio-clip]','[data-review-audio-clip-metadata]','[data-review-audio-preview]','[data-review-audio-audition]','[data-review-audio-audition-status]','[data-review-audio-attestation]','[data-review-audio-confirm]','[data-review-audio-cancel]','[data-review-audio-result]','[data-rehearsal-banner]','[data-rehearsal-controls]','[data-rehearsal-input]','[data-rehearsal-hint]'])nodes.set(selector,new Node());
const window=new Node();const document={body:{dataset:{characterRenderer:codeNative?'code-native-review':'static-pixi'}},querySelector:s=>s==='form'?nodes.get('[data-operator-pairing-form]'):nodes.get(s),querySelectorAll:()=>[],createElement:()=>new Node(),visibilityState:'visible',addEventListener:()=>{}};let view;
class ReviewedAudioPanel {recordingActive=false;constructor(_api,_controller,_elements){this.calls=calls;}start(){this.calls.push('review-start');}setCanEnable(_value){this.calls.push('review-enable-allowed');}setContinuousListeningBlocked(_value){this.calls.push('review-continuous-block');}invalidateForNewInput(){this.calls.push('review-new-input');}invalidateForStop(){this.calls.push('review-stop');}inputSettled(){this.calls.push('review-settled');}close(){this.calls.push('review-close');}auditionState(_state){this.calls.push('review-audition');}}
class ContinuousListeningController {active=false;constructor(options){continuousInstance=this;this.options=options;this.previousText='previous draft';this.emit({state:'idle',lease_id:null,ready:null,transcript:null,previous_previews:[],previous_preview_limit:4,sent_text:[],notice:null,error:null});}emit(view){this.view=view;this.options.onUpdate(view);}start(){calls.push('continuous-start');this.active=true;this.emit({...this.view,state:'starting',lease_id:'lease',ready:null,transcript:null});return true;}stop(){calls.push('continuous-stop');this.active=false;this.emit({...this.view,state:'stopped',lease_id:null,ready:null,transcript:null});return Promise.resolve();}close(){calls.push('continuous-close');this.active=false;return Promise.resolve();}sendCurrent(){calls.push('continuous-send');return Promise.resolve();}restorePreviousPreview(leaseId){calls.push(['restore-preview',leaseId]);this.emit({...this.view,previous_previews:this.view.previous_previews.filter(item=>item.lease_id!==leaseId)});return this.previousText;}}
class SessionController {microphoneBusy=false;constructor(_api,_effects,v,_config,options){view=v;this.options=options;}connect(){calls.push('connect');if(connectBehavior)return connectBehavior(view);view.connected();return Promise.resolve();}input(text){calls.push('input');inputs.push(text);return inputResult;}stop(){calls.push('stop');this.options.onGlobalStop?.('stop');return Promise.resolve();}close(){calls.push('close');this.options.onGlobalStop?.('close');return Promise.resolve();}prepareInputFromGesture(){return true;}interruptReply(){calls.push('interrupt-reply');return true;}setContinuousListeningPhase(_active){}startMicrophone(){calls.push('start');return Promise.resolve();}finishMicrophone(){calls.push('finish');return captureFinishResult;}startRehearsalInput(){calls.push('rehearsal-start');return Promise.resolve();}finishRehearsalInput(){calls.push('rehearsal-finish');return captureFinishResult;}}
vm.runInNewContext(source,{document,window,globalThis:{AudioContext:class{},AudioWorkletNode:class{},isSecureContext:true},navigator:{mediaDevices:{getUserMedia(){}}},isSecureContext:true,loadPublicConfig:()=>({}),watchDiagnosticsStatus:()=>({close(){}}),recordingNotice:()=>({visible:false,text:"",state:"off"}),safeSessionError:()=>"safe error",MiraApiClient:class{},MiraHttpError,SessionController,ReviewedAudioPanel,ContinuousListeningController,DomEffectExecutor:class{constructor(){calls.push('dom');}},SceneEffectExecutor:class{constructor(){calls.push('scene');}}});
return {nodes,calls,inputs,view,window,get continuous(){return continuousInstance;},setInputResult(value){inputResult=value;},setCaptureFinishResult(value){captureFinishResult=value;}};}
test('composition selects scene executor and labels actual backend capability',()=>{const h=app();assert.equal(h.calls.includes('scene'),true);assert.equal(h.calls.includes('dom'),false);h.view.capabilities({generation_mode:'replay',speech_enabled:false,microphone_enabled:false,qualification:'unavailable'});assert.match(h.nodes.get('[data-mode-label]').textContent,/Fixture/);assert.equal(h.nodes.get('[data-ptt]').disabled,true);});
test('continuous control is explicit, manual-send keeps the lease, and typed input stops it first',async()=>{
 const h=app(),button=h.nodes.get('[data-continuous-listening]'),interrupt=h.nodes.get('[data-continuous-interrupt]'),send=h.nodes.get('[data-continuous-send]'),field=h.nodes.get('[name=message]');
 h.view.capabilities({generation_mode:'injected',speech_enabled:true,microphone_enabled:true,continuous_listening_enabled:true,qualification:'injected_unverified'});
 assert.equal(button.hidden,false);button.fire('click');assert.deepEqual(h.calls.filter(call=>call.startsWith('continuous')),['continuous-start']);
 assert.match(h.nodes.get('[data-voice-hint]').textContent,/转写区发送后继续聆听.*文字框发送会先停止/);
 assert.equal(interrupt.hidden,false);interrupt.fire('click');assert.ok(h.calls.includes('interrupt-reply'),'the explicit control is reply-only');
 assert.equal(h.nodes.get('[data-ptt]').disabled,true);send.fire('click');assert.ok(h.calls.includes('continuous-send'));
 field.value='manual typed text';h.nodes.get('form.composer').fire('submit');assert.equal(field.value,'');
 await tick();await tick();assert.ok(h.calls.indexOf('continuous-stop')>=0);
 assert.ok(h.calls.indexOf('continuous-stop')<h.calls.indexOf('input'),'manual text ends listening before SessionController input');
});
test('previous lease preview stays visible, cannot be sent as current, and restores only into an empty composer',()=>{
 const h=app(),send=h.nodes.get('[data-continuous-send]'),field=h.nodes.get('[name=message]'),list=h.nodes.get('[data-continuous-sent-text]');
 h.view.capabilities({generation_mode:'injected',speech_enabled:true,microphone_enabled:true,continuous_listening_enabled:true,qualification:'injected_unverified'});
 h.nodes.get('[data-continuous-listening]').fire('click');
 const previous={lease_id:'old-lease',revision:8,text:'older provisional tail',is_final:false,endpoint_pending:false,can_send:false,truncated:false,hint:'prior pending preview'};
 h.continuous.previousText=previous.text;
 const staleCurrent={...previous,can_send:true};
 h.continuous.emit({state:'listening',lease_id:'new-lease',ready:null,transcript:staleCurrent,
   previous_previews:[previous],previous_preview_limit:4,sent_text:[],notice:null,error:null});
 assert.equal(send.disabled,true,'a transcript from an old lease cannot enable the current Send action');
 assert.equal(h.nodes.get('[data-continuous-preview]').hidden,true,'old preview appears only in its explicitly prior-history row');
 assert.match(list.getAttribute?.('aria-label')??list['aria-label'],/上次未发送预览/);
 assert.match(list.children[0].children[0].textContent,/上次聆听预览.* older provisional tail|上次聆听预览.*older provisional tail/);
 assert.match(list.children[0].children[0].textContent,/不会自动发送/);
 const restore=list.children[0].children[1];
 field.value='keep my newer draft';restore.fire('click');
 assert.equal(field.value,'keep my newer draft','restore refuses to overwrite typed text');
 assert.equal(h.calls.some(call=>Array.isArray(call)&&call[0]==='restore-preview'),false);
 field.value='';restore.fire('click');
 assert.equal(field.value,'older provisional tail');assert.deepEqual(h.inputs,[]);
 assert.equal(h.calls.some(call=>typeof call==='string'&&call.startsWith('continuous-send')),false,'restore does not send or auto-submit');
 assert.equal(list.children.length,0,'restored copy now lives in the composer and releases one bounded history slot');
 const current={...previous,lease_id:'new-lease',revision:1,text:'new lease transcript',is_final:true,can_send:true};
 h.continuous.emit({...h.continuous.view,transcript:current});
 assert.equal(send.disabled,false,'a current-lease transcript enables manual send independently of restored prior text');
 assert.match(h.nodes.get('[data-continuous-preview]').textContent,/new lease transcript/);
 const fullHistory=Array.from({length:4},(_,index)=>({...previous,lease_id:`history-${index}`,text:`pending ${index+1}`}));
 h.continuous.emit({...h.continuous.view,state:'stopped',lease_id:null,ready:null,transcript:null,
   previous_previews:fullHistory,previous_preview_limit:4});
 assert.equal(h.nodes.get('[data-continuous-listening]').disabled,true,'full history blocks another permission request');
 assert.match(h.nodes.get('[data-continuous-status]').textContent,/历史预览已满.*空文字框/);
});
test('PTT pointer and keyboard gestures start once and release once, cancellation stops',()=>{const h=app(),ptt=h.nodes.get('[data-ptt]');h.view.capabilities({generation_mode:'injected',speech_enabled:true,microphone_enabled:true,qualification:'injected_unverified'});ptt.fire('pointerdown');ptt.fire('pointerdown');ptt.fire('pointerup');assert.deepEqual(h.calls.filter(x=>['start','finish'].includes(x)),['start','finish']);ptt.fire('keydown',{key:' ',repeat:false});ptt.fire('keydown',{key:' ',repeat:true});ptt.fire('keyup',{key:' '});assert.equal(h.calls.filter(x=>x==='start').length,2);assert.equal(h.calls.filter(x=>x==='finish').length,2);ptt.fire('pointerdown');ptt.fire('pointercancel');assert.ok(h.calls.includes('stop'));});
test('empty text submission cannot orphan a held microphone gesture',()=>{const h=app(),ptt=h.nodes.get('[data-ptt]');h.view.capabilities({generation_mode:'injected',speech_enabled:true,microphone_enabled:true,qualification:'injected_unverified'});ptt.fire('pointerdown');h.nodes.get('[name=message]').value='   ';h.nodes.get('form.composer').fire('submit');ptt.fire('pointerup');assert.equal(h.calls.filter(x=>x==='input').length,0);assert.equal(h.calls.filter(x=>x==='finish').length,1);});

test('an input blocked before dispatch restores the exact text only while the field is still empty',async()=>{const h=app(),field=h.nodes.get('[name=message]'),pending=deferred(),text='keep this exact phrasing';h.setInputResult(pending.promise);field.value=text;h.nodes.get('form.composer').fire('submit');assert.equal(field.value,'');assert.deepEqual(h.inputs,[text]);pending.resolve({status:'not-sent',text,reason:'history-timeout'});await tick();assert.equal(field.value,text);});

test('a blocked older submission never overwrites newer typing or a newer submitted input',async()=>{const h=app(),field=h.nodes.get('[name=message]'),older=deferred();h.setInputResult(older.promise);field.value='older';h.nodes.get('form.composer').fire('submit');field.value='newer draft';field.fire('input');older.resolve({status:'not-sent',text:'older',reason:'history-failed'});await tick();assert.equal(field.value,'newer draft');});

test('an older blocked outcome does not repopulate an empty field after a newer request was submitted',async()=>{const h=app(),field=h.nodes.get('[name=message]'),older=deferred();h.setInputResult(older.promise);field.value='older';h.nodes.get('form.composer').fire('submit');field.value='newer';field.fire('input');h.setInputResult(Promise.resolve({status:'submitted'}));h.nodes.get('form.composer').fire('submit');assert.equal(field.value,'');older.resolve({status:'not-sent',text:'older',reason:'history-timeout'});await tick();assert.equal(field.value,'');});

test('a microphone final withheld by history failure is restored only if no newer text was entered',async()=>{const h=app(),field=h.nodes.get('[name=message]'),pending=deferred(),ptt=h.nodes.get('[data-ptt]');h.view.capabilities({generation_mode:'injected',speech_enabled:true,microphone_enabled:true,qualification:'injected_unverified'});h.setCaptureFinishResult(pending.promise);ptt.fire('pointerdown');ptt.fire('pointerup');pending.resolve({status:'not-sent',text:'final recognized words',reason:'history-failed'});await tick();assert.equal(field.value,'final recognized words');});

test('explicit rehearsal shows honest banner, microphone off and synthetic hold input controls',()=>{const h=app();h.view.capabilities({generation_mode:'rehearsal',speech_enabled:true,microphone_enabled:false,qualification:'offline_fixture'});assert.equal(h.nodes.get('[data-rehearsal-banner]').hidden,false);assert.match(h.nodes.get('[data-mode-description]').textContent,/英文.*合成/);assert.equal(h.nodes.get('[data-ptt]').disabled,true);const button=h.nodes.get('[data-rehearsal-input]');button.fire('pointerdown');button.fire('pointerdown');button.fire('pointerup');assert.deepEqual(h.calls.filter(x=>x.startsWith('rehearsal')),['rehearsal-start','rehearsal-finish']);assert.equal(h.calls.includes('start'),false);button.fire('keydown',{key:' ',repeat:false});button.fire('keyup',{key:' '});assert.equal(h.calls.filter(x=>x==='rehearsal-finish').length,2);button.fire('pointerdown');h.window.fire('blur');assert.ok(h.calls.includes('stop'));assert.ok(h.calls.includes('continuous-stop'));button.fire('pointerup');assert.equal(h.calls.filter(x=>x==='rehearsal-finish').length,2);});


test('IME confirmation Enter and repeated events are intercepted; legacy 229 is covered',()=>{
 const h=app(),field=h.nodes.get('[name=message]');
 field.value='合成中的消息';
 const first=field.fire('keydown',{key:'Enter',code:'Enter',keyCode:13,isComposing:true,repeat:false});
 const repeated=field.fire('keydown',{key:'Enter',code:'Enter',keyCode:13,isComposing:true,repeat:true});
 const legacy=field.fire('keydown',{key:'Enter',code:'Enter',keyCode:229,isComposing:false,repeat:false});
 assert.equal(first.defaultPrevented,true,'IME confirmation must not trigger implicit submission');
 assert.equal(repeated.defaultPrevented,true,'repeated composition Enter must also be canceled');
 assert.equal(legacy.defaultPrevented,true,'legacy IME keyCode 229 must be canceled');
 assert.deepEqual(h.inputs,[],'composition text must not reach the controller');
});

test('composition state guards Enter until compositionend, then ordinary Enter still submits exact Chinese text',()=>{
 const h=app(),field=h.nodes.get('[name=message]');
 field.value='明天去哪里？'; field.fire('compositionstart');
 const during=field.fire('keydown',{key:'Enter',code:'Enter',keyCode:13,isComposing:false,repeat:false});
 assert.equal(during.defaultPrevented,true,'composition event state protects platforms with incomplete key flags');
 assert.deepEqual(h.inputs,[]);
 field.fire('compositionend');
 const ordinary=field.fire('keydown',{key:'Enter',code:'Enter',keyCode:13,isComposing:false,repeat:false});
 assert.equal(ordinary.defaultPrevented,true,'textarea Enter prevents a newline and explicitly submits the composer');
 assert.deepEqual(h.inputs,['明天去哪里？']);
});

test('Stop then newer text submission preserves the newer draft when an older blocked result settles',async()=>{
 const h=app(),field=h.nodes.get('[name=message]'),form=h.nodes.get('form.composer'),older=deferred();
 h.setInputResult(older.promise); field.value='旧的输入'; form.fire('submit');
 h.nodes.get('[data-stop]').fire('click');
 field.value='新的输入'; field.fire('input');
 h.setInputResult(Promise.resolve({status:'submitted'})); form.fire('submit');
 older.resolve({status:'not-sent',text:'旧的输入',reason:'history-failed'}); await tick();
 assert.deepEqual(h.calls.filter(x=>x==='input'||x==='stop'),['input','stop','input']);
 assert.deepEqual(h.inputs,['旧的输入','新的输入']); assert.equal(field.value,'');
});

test('direct form submission still sends text without depending on the Enter key path',()=>{
 const h=app(),field=h.nodes.get('[name=message]'),form=h.nodes.get('form.composer');
 field.value='按钮发送'; form.fire('submit');
 assert.deepEqual(h.inputs,['按钮发送']);
});

test('semantic uncertainty uses the dedicated status region and never the generic error alert',()=>{
 const h=app(),region=h.nodes.get('[data-system-notice]'),body=h.nodes.get('[data-system-notice-body]');
 h.view.systemNotice({label:'系统提示',body:'这部分我还不确定，先跳过。你可以补充说明，或继续聊。'});
 assert.equal(region.hidden,false); assert.equal(body.textContent,'这部分我还不确定，先跳过。你可以补充说明，或继续聊。');
 h.view.update({phase:'error',revision:2,activity_seq:1,output_epoch:1,permit_revision:2,active_grants:[],presented_effects:[],audio_progress:[],sealed:true,last_error:'review_uncertain'});
 assert.equal(h.nodes.get('[data-error]').textContent,'','The nonfatal review fallback must not populate the alert surface');
 h.view.systemNotice(null);
 assert.equal(region.hidden,true); assert.equal(body.textContent,'');
 assert.match(markup,/<aside class="system-notice" data-system-notice role="status" aria-live="polite" aria-atomic="true" hidden>/);
 assert.match(markup,/<strong>系统提示<\/strong>/);
 assert.match(markup,/<p data-system-notice-body><\/p>/);
});

// The actual page has pairing, management and conversation forms. A generic
// first-form selector would bind pairing instead of the visible chat composer.
test('actual three-form markup binds chat only to the composer',()=>{
  const forms=[...markup.matchAll(/<form\b[^>]*>/g)].map(match=>match[0]);
  assert.equal(forms.length,3);
  assert.match(forms[0],/data-operator-pairing-form/);
  assert.match(forms[1],/class="composer"/);
  assert.match(forms[2],/data-memory-management-record-form/);
  assert.match(source,/element\('form\.composer'\)\.addEventListener\('submit'/,
    'chat submission keeps its exact composer selector with multiple earlier forms');
  const h=app();
  assert.equal(h.nodes.get('[data-operator-pairing-form]').listeners.submit,undefined);
  assert.equal(h.nodes.get('form[data-memory-management-record-form]').listeners.submit,undefined,
    'the manager form is also kept separate from chat submission');
  assert.equal(h.nodes.get('form.composer').listeners.submit.length,1);
  h.nodes.get('[name=message]').value='synthetic composer input';
  h.nodes.get('form.composer').fire('submit');
  assert.deepEqual(h.inputs,['synthetic composer input']);
});


test('provisional microphone preview is accessible, text-only, and separate from the assistant and composer',()=>{
 const h=app(),preview=h.nodes.get('[data-microphone-preview]'),composer=h.nodes.get('[name=message]');
 assert.match(markup,/<p class="microphone-preview" data-microphone-preview role="status" aria-live="polite" aria-atomic="true" hidden><\/p>/);
 assert.match(markup,/data-microphone-preview[\s\S]*data-voice-hint/);
 h.view.microphonePreview({stream_id:'synthetic-stream',revision:1,text:'<img src=x onerror=alert(1)>',is_final:false});
 assert.match(preview.textContent,/用户输入临时预览/);
 assert.match(preview.textContent,/<img src=x onerror=alert\(1\)>/);
 assert.equal(preview.hidden,false);assert.equal(composer.value,'');assert.equal(preview.innerHTML,undefined);
 h.view.microphonePreview(null);assert.equal(preview.textContent,'');assert.equal(preview.hidden,true);
});


test('failed connection keeps draft editable, preserves safe capacity error, and blocks sending',async()=>{
 const problem=new MiraHttpError(429,'session_capacity',safeHttpError(429,null,'session_capacity'));
 const h=app(()=>Promise.reject(problem));const input=h.nodes.get('[name=message]');input.value='unsent draft';await tick();
 assert.equal(h.nodes.get('fieldset').disabled,false);assert.equal(input.disabled,false);
 assert.equal(h.nodes.get('[data-send-message]').disabled,true);assert.equal(h.nodes.get('[data-connect-retry]').disabled,false);
 assert.equal(h.nodes.get('[data-error]').textContent,problem.message);
 h.nodes.get('form.composer').fire('submit');assert.equal(input.value,'unsent draft');assert.equal(h.inputs.length,0);
});
test('connection retry is single-flight, preserves drafts and enables Send only after success',async()=>{
 const pending=deferred();let attempts=0;
 const h=app(view=>{attempts++;if(attempts===1)return Promise.reject(new Error('private raw detail'));return pending.promise.then(()=>view.connected());});
 const input=h.nodes.get('[name=message]');input.value='keep me';await tick();
 assert.doesNotMatch(h.nodes.get('[data-error]').textContent,/private raw detail/);
 const retry=h.nodes.get('[data-connect-retry]');retry.fire('click');retry.fire('click');
 assert.equal(attempts,2);assert.equal(retry.disabled,true);assert.equal(input.value,'keep me');
 pending.resolve();await tick();assert.equal(h.nodes.get('[data-send-message]').disabled,false);assert.equal(input.value,'keep me');
 retry.fire('click');assert.equal(attempts,2);
});
test('closing during connection does not erase drafts or enable a stale successful attempt',async()=>{
 const pending=deferred();const h=app(view=>pending.promise.then(()=>view.connected()));
 const input=h.nodes.get('[name=message]');input.value='keep after close';h.nodes.get('[data-close]').fire('click');
 pending.resolve();await tick();assert.equal(input.value,'keep after close');assert.equal(input.disabled,false);
 assert.equal(h.nodes.get('[data-send-message]').disabled,true);assert.equal(h.nodes.get('[data-connect-retry]').disabled,true);
});
test('initial origin error retains only safe wording and a verified request correlation',async()=>{
 const id='12345678-1234-4234-8234-123456789abc';const problem=new MiraHttpError(403,null,safeHttpError(403,id));
 const h=app(()=>Promise.reject(problem));await tick();assert.equal(h.nodes.get('[data-error]').textContent,problem.message);
});


test('fixed wardrobe demo controls require both mock capability and code-native selection',()=>{
 const h=app(null,true),panel=h.nodes.get('[data-code-mock-controls]');
 h.view.capabilities({generation_mode:'mock',speech_enabled:false,microphone_enabled:false,qualification:'unavailable'});
 assert.equal(panel.hidden,false);
 h.view.capabilities({generation_mode:'injected',speech_enabled:false,microphone_enabled:false,qualification:'injected_unverified'});
 assert.equal(panel.hidden,true);
 const old=app();old.view.capabilities({generation_mode:'mock',speech_enabled:false,microphone_enabled:false,qualification:'unavailable'});
 assert.equal(old.nodes.get('[data-code-mock-controls]').hidden,true);
 for(const command of ['演示：黑夹克','演示：奶油内搭','演示：琥珀雨衣'])assert.ok(markup.includes('data-command="'+command+'"'));
});

for (const listening of [false, true]) test(`known local reply interruption keeps ${listening ? 'continuous listening' : 'stopped reply'} out of the error surface`, () => {
 const h=app();h.continuous.microphoneActive=listening;
 const snapshot={phase:'error',revision:8,activity_seq:2,output_epoch:2,permit_revision:9,active_grants:[],presented_effects:[],audio_progress:[],sealed:false,last_error:'audio_interrupted'};
 h.view.update(snapshot,{expectedReplyInterruption:true});
 assert.equal(h.nodes.get('[data-error]').textContent,'');
 assert.equal(h.nodes.get('[data-status]').textContent,listening?'listening':'stopped');
 assert.equal(snapshot.phase,'error','the backend factual snapshot is not rewritten');
 assert.equal(snapshot.last_error,'audio_interrupted');
 h.view.update(snapshot,{expectedReplyInterruption:false});
 assert.equal(h.nodes.get('[data-error]').textContent,'safe error','unexpected interruption still shows its error');
});
