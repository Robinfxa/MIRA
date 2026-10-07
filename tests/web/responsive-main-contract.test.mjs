import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import vm from 'node:vm';
const html=await readFile(new URL('../../apps/web/index.html',import.meta.url),'utf8');
const dist=process.env.MIRA_TEST_WEB_DIST ? resolve(process.env.MIRA_TEST_WEB_DIST) : resolve('apps/web/dist');
const main=(await readFile(resolve(dist,'app/main-source.js'),'utf8')).replace(/^import .*;\n/gm,'');
const tick=()=>new Promise(r=>setImmediate(r));
const deferred=()=>{let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};};
class Node {
  constructor(tag='div',attrs={}) {this.tagName=tag.toUpperCase();this.attrs=attrs;this.children=[];this.parentElement=null;this.listeners=new Map();this.dataset={};this.value='';this._text='';this.hidden='hidden' in attrs;this.disabled='disabled' in attrs;this.scrollTop=0;this.scrollHeight=400;this.clientHeight=400;for(const [k,v] of Object.entries(attrs))if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]=v;}
  get className(){return this.attrs.class??'';} set className(v){this.attrs.class=v;}
  get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}set textContent(v){this._text=v;this.children=[];}
  get firstElementChild(){return this.children[0]??null;}
  append(...nodes){for(const n of nodes){n.parentElement=this;this.children.push(n);}}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
  setAttribute(k,v){this.attrs[k]=String(v);}
  getAttribute(k){return this.attrs[k]??null;}
  addEventListener(k,f){const list=this.listeners.get(k)??[];list.push(f);this.listeners.set(k,list);}
  fire(k,extras={}){const e={defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},...extras};for(const f of this.listeners.get(k)??[])f(e);return e;}
  requestSubmit(){this.fire('submit');}
  focus(){this.focused=true;}
  setPointerCapture(){}
  querySelectorAll(selector){const matches=[];const match=n=>{if(selector.startsWith('[')){const [,key,value]=selector.match(/^\[([^=\]]+)(?:=['"]?([^'"\]]+)['"]?)?\]$/)??[];return key in n.attrs&&(value===undefined||n.attrs[key]===value);}if(selector.startsWith('.'))return n.className.split(/\s+/).includes(selector.slice(1));const [tag,cls]=selector.split('.');return n.tagName.toLowerCase()===tag&&(!cls||n.className.split(/\s+/).includes(cls));};const visit=n=>{for(const child of n.children){if(match(child))matches.push(child);visit(child);}};visit(this);return matches;}
  querySelector(s){return this.querySelectorAll(s)[0]??null;}
}
function parseHtml(source){
  const root=new Node('document'), stack=[root];const voids=new Set(['meta','link','input','img','br','hr','source','wbr']);
  for(const token of source.matchAll(/<!--[\s\S]*?-->|<![^>]+>|<\/?[a-zA-Z][^>]*>|[^<]+/g)){
    const value=token[0];if(value.startsWith('<!'))continue;
    if(value.startsWith('</')){const tag=value.slice(2,-1).trim().toLowerCase();assert.equal(stack.at(-1).tagName.toLowerCase(),tag,`shipping HTML closes ${tag} in the proper tree`);stack.pop();continue;}
    if(value.startsWith('<')){const [,tag,raw]=value.match(/^<([\w-]+)([\s\S]*?)\/?\s*>$/);const attrs={};for(const m of raw.matchAll(/([^\s=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g))attrs[m[1]]=m[2]??m[3]??m[4]??'';const n=new Node(tag,attrs);stack.at(-1).append(n);if(!voids.has(tag)&&!value.endsWith('/>'))stack.push(n);}
    else stack.at(-1)._text+=value;
  }
  assert.equal(stack.length,1,'all shipping HTML elements close');return root;
}
function harness({connectFailure=false}={}){
  const document=parseHtml(html),window=new Node('window'),calls=[];document.body=document.querySelector('body');document.visibilityState='visible';document.createElement=t=>new Node(t);
  let controller,continuous;let connectFail=connectFailure;
  const ready={revision:1,activity_seq:0,output_epoch:0,permit_revision:1,active_grants:[],presented_effects:[],audio_progress:[],sealed:true,phase:'idle',last_error:null};
  class Controller {
    microphoneBusy=false;
    constructor(_api,_effects,view){this.view=view;controller=this;}
    async connect(){calls.push('connect');if(connectFail)throw new Error('synthetic connection failed');this.view.connected();this.view.update(ready);this.view.capabilities({generation_mode:'mock',qualification:'unavailable',microphone_enabled:false,speech_enabled:false});}
    async input(text){calls.push(['input',text]);this.view.inputAccepted(text,`input-${calls.length}`);return {status:'submitted'};}
    async stop(){calls.push('stop');this.view.localStop();}
    prepareInputFromGesture(){return true;}interruptReply(){calls.push('interrupt');return true;}
    async close(){calls.push('close');}
    startMicrophone(){calls.push('microphone');return Promise.resolve();}
    setContinuousListeningPhase(){}
  }
  class Continuous {active=false;microphoneActive=false;constructor(options){continuous=this;this.options=options;}start(){calls.push('continuous-start');}async stop(){calls.push('continuous-stop');this.active=false;}async close(){calls.push('continuous-close');}async sendCurrent(){calls.push('continuous-send');}}
  class Panel {recordingActive=false;start(){}close(){}setCanEnable(){}setContinuousListeningBlocked(){}invalidateForNewInput(){}invalidateForStop(){}auditionState(){}}
  vm.runInNewContext(main,{document,window,navigator:{mediaDevices:{getUserMedia(){throw new Error('automatic microphone forbidden');}}},globalThis:{AudioContext:class{},AudioWorkletNode:class{},isSecureContext:true},loadPublicConfig:()=>({}),watchDiagnosticsStatus:()=>({close(){}}),recordingNotice:()=>({visible:false,text:'',state:'off'}),safeSessionError:()=> 'safe error',MiraApiClient:class{},MiraHttpError:class extends Error{},SessionController:Controller,ContinuousListeningController:Continuous,SceneEffectExecutor:class{},ReviewedAudioPanel:Panel});
  return {document,window,calls,get controller(){return controller;},get continuous(){return continuous;},connectSuccess(){connectFail=false;},node:s=>{const n=document.querySelector(s);assert.ok(n,`selector ${s} is present in actual HTML`);return n;}};
}
test('compiled main boots against actual HTML; offline capability starts no microphone',async()=>{
  const h=harness();await tick();assert.equal(h.node('[data-continuous-listening]').hidden,true);assert.equal(h.node('[data-continuous-panel]').hidden,true);
  assert.deepEqual(h.calls,['connect']);assert.equal(h.node('[name=message]').disabled,false);assert.equal(h.node('[data-send-message]').disabled,false);
  assert.equal(h.document.querySelectorAll('[data-stop]').length,1);
});
test('textarea Enter submits, while IME and Shift+Enter preserve the draft',async()=>{
  const h=harness();await tick();const input=h.node('[name=message]');input.value='一个草稿';
  input.fire('compositionstart');assert.equal(input.fire('keydown',{key:'Enter'}).defaultPrevented,true);assert.equal(h.calls.length,1);
  input.fire('compositionend');assert.equal(input.fire('keydown',{key:'Enter',shiftKey:true}).defaultPrevented,false);assert.equal(input.value,'一个草稿');
  input.fire('keydown',{key:'Enter',shiftKey:false});await tick();assert.deepEqual(h.calls[1],['input','一个草稿']);assert.equal(input.value,'');
  assert.equal(h.node('[data-conversation-log]').children.length,1);assert.match(h.node('[data-conversation-log]').textContent,/一个草稿/);
});
test('failed connection leaves input editable and retry sends only after actual readiness',async()=>{
  const h=harness({connectFailure:true});await tick();const input=h.node('[name=message]');input.value='离线草稿';input.fire('keydown',{key:'Enter'});await tick();assert.equal(input.value,'离线草稿');assert.equal(h.node('[data-send-message]').disabled,true);assert.equal(input.disabled,false);
  h.connectSuccess();h.node('[data-connect-retry]').fire('click');await tick();assert.equal(input.value,'离线草稿');assert.equal(h.node('[data-send-message]').disabled,false);
});
test('known unsent text restores only the unchanged empty draft',async()=>{
  const h=harness();await tick();const pending=deferred(),input=h.node('[name=message]');h.controller.input=()=>pending.promise;input.value='第一稿';input.fire('input');input.fire('keydown',{key:'Enter'});await tick();
  input.value='后写的草稿';input.fire('input');pending.resolve({status:'not-sent',text:'第一稿'});await tick();assert.equal(input.value,'后写的草稿');assert.equal(h.node('[data-conversation-log]').children.length,0);
  h.controller.input=async text=>({status:'not-sent',text});input.value='可恢复草稿';input.fire('input');input.fire('keydown',{key:'Enter'});await tick();assert.equal(input.value,'可恢复草稿');
});
test('Stop preserves shown text and current draft; distinct voice controls keep distinct callbacks',async()=>{
  const h=harness();await tick();h.controller.view.inputAccepted('确实送出','r');h.controller.view.visualPresented({kind:'subtitle',id:'e',value:'确实显示'});const input=h.node('[name=message]');input.value='还没发送';
  h.node('[data-stop]').fire('click');await tick();assert.equal(input.value,'还没发送');assert.equal(h.node('[data-conversation-log]').children.length,2);assert.match(h.node('[data-turn-status]').textContent,/停止/);
  h.node('[data-continuous-interrupt]').fire('click');h.node('[data-continuous-send]').fire('click');assert.ok(h.calls.includes('interrupt'));assert.ok(h.calls.includes('continuous-send'));
});
test('page log is bounded, text-only, duplicate-safe, and respects a reader scrolled upward',async()=>{
  const h=harness();await tick();const log=h.node('[data-conversation-log]');log.scrollHeight=1000;log.clientHeight=200;log.scrollTop=50;
  h.controller.view.visualPresented({kind:'subtitle',id:'e',value:'<img src=x onerror=bad()>\n长回复'});h.controller.view.visualPresented({kind:'subtitle',id:'e',value:'duplicate'});
  assert.equal(log.children.length,1);assert.equal(log.scrollTop,50);assert.equal(log.querySelectorAll('img').length,0);assert.match(log.textContent,/<img src=x/);
  h.controller.view.visualPresented({kind:'pose',id:'p',value:'face_warm'});assert.equal(log.children.length,1);
  for(let i=0;i<85;i++)h.controller.view.inputAccepted(`text ${i}`,`r${i}`);
  assert.equal(log.children.length,80);assert.match(h.node('[data-conversation-history-note]').textContent,/80/);assert.equal(h.node('[data-conversation-empty]').hidden,true);
});
test('continuous state shows real finite cap and manual-send readiness without auto-start',async()=>{
  const h=harness();await tick();h.controller.view.capabilities({generation_mode:'injected',qualification:'injected',microphone_enabled:true,speech_enabled:true,continuous_listening_enabled:true});
  h.continuous.options.onUpdate({state:'listening',lease_id:'l',ready:{max_seconds:180,max_utterances:8,session_lease_starts_used:1,max_streams_per_session:3,total_lease_starts_used:2,max_total_streams:6,endpoint_mode:'unavailable_manual'},transcript:{lease_id:'l',revision:2,is_final:true,can_send:true,text:'待核对',endpoint_pending:false},previous_previews:[],sent_text:[],notice:null,error:null});
  assert.match(h.node('[data-continuous-status]').textContent,/本次聆听上限 180 秒，本次最多发送 8 条/);assert.match(h.node('[data-continuous-status]').textContent,/手动发送备用模式/);assert.equal(h.node('[data-continuous-send]').disabled,false);assert.equal(h.node('[data-continuous-interrupt]').hidden,false);assert.ok(!h.calls.includes('continuous-start'));
  assert.equal(h.node('[data-conversation-log]').children.length,0,'transcript is never a sent chat fact');
});
test('actual HTML retains every consent control in settings, while notices and input stay outside',()=>{
  const h=harness(),settings=h.node('.settings-panel');assert.ok(settings.querySelector('[data-review-audio-consent]'));assert.ok(settings.querySelector('[data-memory-management-local-consent]'));assert.equal(settings.querySelector('[data-recording-notice]'),null);assert.equal(settings.querySelector('[data-stop]'),null);assert.equal(settings.querySelector('[name=message]'),null);
  for(const details of h.document.querySelectorAll('details'))assert.equal('open' in details.attrs,false);
});

test('presented disjoint Unicode caption chunks form one exact message without duplicating prefixes',async()=>{
  const h=harness();await tick();const group='11111111-1111-4111-8111-111111111111';
  const effect=(id,value,index,start,end,activity=1)=>({kind:'subtitle',id,value,activity_seq:activity,output_epoch:activity,caption_chunk:{group_id:group,index,start,end,total:9,source_sha256:'a'.repeat(64)}});
  const first=effect('a','你好🌧️',0,0,4);const second=effect('b','，慢慢聊。',1,4,9);
  h.controller.view.visualPresented(first);h.controller.view.visualPresented(second);h.controller.view.visualPresented(second);
  const log=h.node('[data-conversation-log]');assert.equal(log.children.length,1);assert.equal(log.children[0].querySelector('p').textContent,'你好🌧️，慢慢聊。');
  h.node('[data-stop]').fire('click');assert.equal(log.children.length,1);
  h.controller.view.visualPresented(effect('c','你好🌧️',0,0,4,2));assert.equal(log.children.length,2,'new activity never merges into the old reply');
});
test('an invalid or noncontiguous chunk never fabricates a missing prefix or overwrites shown text',async()=>{
  const h=harness();await tick();const base={kind:'subtitle',activity_seq:1,output_epoch:1,caption_chunk:{group_id:'11111111-1111-4111-8111-111111111111',index:0,start:0,end:2,total:6,source_sha256:'a'.repeat(64)}};
  h.controller.view.visualPresented({...base,id:'first',value:'前段'});
  h.controller.view.visualPresented({...base,id:'gap',value:'尾段',caption_chunk:{...base.caption_chunk,index:2,start:4,end:6}});
  const log=h.node('[data-conversation-log]');assert.equal(log.children.length,2);assert.equal(log.children[0].querySelector('p').textContent,'前段');assert.equal(log.children[1].querySelector('p').textContent,'尾段');
});
test('compiled main distinguishes unlimited local limits from exhausted finite service budget and preserves text entry',async()=>{
 const h=harness();await tick();h.controller.view.capabilities({generation_mode:'injected',qualification:'injected',microphone_enabled:true,speech_enabled:true,continuous_listening_enabled:true});
 const view={state:'stopped',lease_id:null,ready:{max_seconds:null,max_samples:null,max_utterances:null,max_streams_per_session:null,max_total_streams:null,max_recognition_streams:null,session_lease_starts_used:140,total_lease_starts_used:140,stt_requests_used:10,stt_requests_remaining:0,endpoint_mode:'google_vad_offsets_natural'},natural_enabled:true,service_budget_exhausted:false,transcript:null,previous_previews:[],sent_text:[],notice:null,error:null};
 h.continuous.options.onUpdate(view);assert.equal(h.node('[data-continuous-listening]').disabled,false);assert.doesNotMatch(h.node('[data-continuous-status]').textContent,/本地不限|本会话已启动|服务范围已启动/);assert.match(h.node('[data-continuous-status]').textContent,/剩余 0 次/);assert.doesNotMatch(h.node('[data-continuous-status]').textContent,/null/);
 h.node('[name=message]').value='保留草稿';h.continuous.options.onUpdate({...view,service_budget_exhausted:true});assert.equal(h.node('[data-continuous-listening]').disabled,true);assert.equal(h.node('[name=message]').disabled,false);assert.equal(h.node('[name=message]').value,'保留草稿');assert.ok(!h.calls.includes('continuous-start'));
});
test('compiled main does not resurrect old source after its display history has retired',async()=>{
 const h=harness();await tick();for(let n=1;n<=100;n++)h.controller.view.visualPresented({id:`effect-${n}`,kind:'subtitle',value:`reply ${n}`,activity_seq:n,output_epoch:n});
 assert.equal(h.node('[data-conversation-log]').children.length,80);h.controller.view.visualPresented({id:'effect-1',kind:'subtitle',value:'old reply',activity_seq:1,output_epoch:1});assert.equal(h.node('[data-conversation-log]').children.length,80);assert.doesNotMatch(h.node('[data-conversation-log]').textContent,/old reply/);
 h.controller.view.update({phase:'idle',last_error:null,active_grants:[],presented_effects:[],audio_progress:[],retired_user_inputs:96,presentation_floor:100});assert.match(h.node('[data-conversation-history-note]').textContent,/96.*不是完整/);
});
