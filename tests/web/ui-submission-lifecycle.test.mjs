import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import vm from 'node:vm';
const sourceRoot=resolve(process.env.MIRA_TEST_SOURCE_ROOT ?? process.cwd());
const html=await readFile(resolve(sourceRoot,'apps/web/index.html'),'utf8');
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
    constructor(_api,_effects,view,_config,options){this.view=view;this.options=options;controller=this;}
    async connect(){calls.push('connect');if(connectFail)throw new Error('synthetic connection failed');this.view.connected();this.view.update(ready);this.view.capabilities({generation_mode:'mock',qualification:'unavailable',microphone_enabled:false,speech_enabled:false});}
    async input(text){calls.push(['input',text]);this.view.inputAccepted(text,`input-${calls.length}`);return {status:'submitted'};}
    async dismissPhoto(){calls.push('photo-dismiss');}
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

test('Stop cancels a text submission still waiting for continuous-listening teardown',async()=>{
 const h=harness();await tick();const late=deferred(),input=h.node('[name=message]');
 h.continuous.active=true;h.continuous.stop=()=>{h.continuous.active=false;return late.promise;};
 input.value='not dispatched yet';input.fire('input');input.fire('keydown',{key:'Enter'});await tick();
 assert.equal(h.calls.filter(x=>Array.isArray(x)&&x[0]==='input').length,0);
 h.node('[data-stop]').fire('click');await tick();late.resolve();await tick();
 assert.equal(h.calls.filter(x=>Array.isArray(x)&&x[0]==='input').length,0,'Stop must not be followed by a new dispatch from an older UI continuation');
});
test('A newer text submission supersedes an older submission awaiting microphone teardown',async()=>{
 const h=harness();await tick();const late=deferred(),input=h.node('[name=message]');
 h.continuous.active=true;h.continuous.stop=()=>{h.continuous.active=false;return late.promise;};
 input.value='older queued text';input.fire('input');input.fire('keydown',{key:'Enter'});await tick();
 input.value='newer text';input.fire('input');input.fire('keydown',{key:'Enter'});await tick();
 late.resolve();await tick();
 assert.deepEqual(h.calls.filter(x=>Array.isArray(x)&&x[0]==='input').map(x=>x[1]),['newer text'],'an older UI continuation must not interrupt and replace the newer turn');
});

const inputs=h=>h.calls.filter(x=>Array.isArray(x)&&x[0]==='input').map(x=>x[1]);
async function queueText(h,text='queued text'){
 await tick();const pending=deferred(),input=h.node('[name=message]');
 h.continuous.active=true;h.continuous.stop=()=>{h.continuous.active=false;return pending.promise;};
 input.value=text;input.fire('input');input.fire('keydown',{key:'Enter'});await tick();
 assert.deepEqual(inputs(h),[]);return {pending,input};
}
test('Stop restores known-undispatched text to the unchanged empty draft',async()=>{
 const h=harness(),{pending,input}=await queueText(h);h.node('[data-stop]').fire('click');pending.resolve();await tick();assert.deepEqual(inputs(h),[]);assert.equal(input.value,'queued text');assert.equal(h.node('[data-conversation-log]').children.length,0);
});
test('Typing a newer draft does not cancel the pending intentional send or overwrite the draft',async()=>{
 const h=harness(),{pending,input}=await queueText(h);input.value='new draft only';input.fire('input');pending.resolve();await tick();assert.deepEqual(inputs(h),['queued text']);assert.equal(input.value,'new draft only');
});
for(const action of ['close','pagehide','interrupt','global-error'])test(`${action} fences pending text and preserves a newer editable draft`,async()=>{
 const h=harness(),{pending,input}=await queueText(h);input.value='new unsent draft';input.fire('input');
 if(action==='close')h.node('[data-close]').fire('click');
 if(action==='pagehide')h.window.fire('pagehide');
 if(action==='interrupt')h.node('[data-continuous-interrupt]').fire('click');
 if(action==='global-error')h.controller.options.onGlobalStop('error');
 await tick();pending.resolve();await tick();assert.deepEqual(inputs(h),[]);assert.equal(input.value,'new unsent draft');assert.equal(input.disabled,false);
});
for(const action of ['stop','close','newer-text'])test(`queued preset is fenced by ${action}`,async()=>{
 const h=harness();await tick();const pending=deferred();h.continuous.active=true;h.continuous.stop=()=>{h.continuous.active=false;return pending.promise;};
 h.node('[data-command]').fire('click');await tick();assert.deepEqual(inputs(h),[]);
 if(action==='stop')h.node('[data-stop]').fire('click');
 if(action==='close')h.node('[data-close]').fire('click');
 if(action==='newer-text'){const input=h.node('[name=message]');input.value='newer';input.fire('input');input.fire('keydown',{key:'Enter'});}
 await tick();pending.resolve();await tick();assert.deepEqual(inputs(h),action==='newer-text'?['newer']:[]);
});
test('new preset supersedes pending text before the old teardown settles',async()=>{
 const h=harness(),{pending}=await queueText(h);const button=h.node('[data-command]');button.fire('click');await tick();pending.resolve();await tick();assert.deepEqual(inputs(h),[button.dataset.command]);
});
test('continuous manual-send intent and confirmed transcript supersede queued text',async()=>{
 const h=harness(),{pending}=await queueText(h);h.node('[data-continuous-send]').fire('click');await h.continuous.options.submitInput('confirmed transcript','synthetic-utterance');pending.resolve();await tick();assert.deepEqual(inputs(h),['confirmed transcript']);
});


test('photo close is an accessible native button wired only to local photo dismissal', async () => {
 const h=harness();await tick();h.continuous.active=true;const button=h.node('[data-photo-close]');
 assert.equal(button.tagName,'BUTTON');assert.equal(button.getAttribute('type'),'button');
 assert.equal(button.getAttribute('aria-label'),'关闭旅行插画');
 const before=[...h.calls];button.fire('click');await tick();
 assert.deepEqual(h.calls.slice(before.length),['photo-dismiss']);
 assert.equal(h.continuous.active,true,'closing photo leaves ongoing listening active');
});
