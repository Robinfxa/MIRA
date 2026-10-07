import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import vm from 'node:vm';
const sourceRoot=resolve(process.env.MIRA_TEST_SOURCE_ROOT ?? process.cwd());
const html=await readFile(resolve(sourceRoot,'apps/web/index.html'),'utf8');
const dist=process.env.MIRA_TEST_WEB_DIST ? resolve(process.env.MIRA_TEST_WEB_DIST) : resolve('apps/web/dist');
const {ContinuousListeningController: ProductionContinuous}=await import(resolve(dist,'features/session/continuous-listening.js'));
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
    async stop(){calls.push('stop');this.view.localStop();}
    prepareInputFromGesture(){return true;}interruptReply(){calls.push('interrupt');return true;}
    async close(){calls.push('close');}
    startMicrophone(){calls.push('microphone');return Promise.resolve();}
    setContinuousListeningPhase(){}
  }
  class Continuous extends ProductionContinuous {constructor(options){super({...options,createCapture:()=>({start:async()=>{calls.push('unexpected-capture-start');return false;},stop(){},close(){}})});continuous=this;}}
  class Panel {recordingActive=false;start(){}close(){}setCanEnable(){}setContinuousListeningBlocked(){}invalidateForNewInput(){}invalidateForStop(){}auditionState(){}}
  vm.runInNewContext(main,{document,window,navigator:{mediaDevices:{getUserMedia(){throw new Error('automatic microphone forbidden');}}},globalThis:{AudioContext:class{},AudioWorkletNode:class{},isSecureContext:true},loadPublicConfig:()=>({}),watchDiagnosticsStatus:()=>({close(){}}),recordingNotice:()=>({visible:false,text:'',state:'off'}),safeSessionError:()=> 'safe error',MiraApiClient:class{},MiraHttpError:class extends Error{},SessionController:Controller,ContinuousListeningController:Continuous,SceneEffectExecutor:class{},ReviewedAudioPanel:Panel});
  return {document,window,calls,get controller(){return controller;},get continuous(){return continuous;},connectSuccess(){connectFail=false;},node:s=>{const n=document.querySelector(s);assert.ok(n,`selector ${s} is present in actual HTML`);return n;}};
}


test('Actual continuous controller plus compiled main enables click-start on valid late voice capabilities',async()=>{
 const h=harness();await tick();assert.equal(h.node('[data-continuous-listening]').disabled,true);
 h.controller.view.capabilities({generation_mode:'injected',qualification:'injected_unverified',microphone_enabled:true,speech_enabled:true,continuous_listening_enabled:true});
 assert.equal(h.node('[data-ptt]').disabled,false,'the independent PTT path is available');
 assert.equal(h.node('[data-continuous-listening]').hidden,false,'capability makes continuous control visible');
 assert.equal(h.node('[data-continuous-listening]').disabled,false,'the initial pre-capability disabled state must be refreshed');
 assert.equal(h.node('[data-continuous-send]').disabled,true,'manual send stays disabled without a confirmed transcript');
 assert.ok(!h.calls.includes('unexpected-capture-start'),'capability discovery must not start capture');
 await h.continuous.close();
});
const liveCapabilities={generation_mode:'injected',qualification:'injected_unverified',microphone_enabled:true,speech_enabled:true,continuous_listening_enabled:true};
test('capability refresh preserves finite-start exhaustion',async()=>{
 const h=harness();await tick();h.continuous.options.onUpdate({state:'stopped',lease_id:null,ready:{max_seconds:60,max_utterances:4,max_streams_per_session:4,max_total_streams:4,session_lease_starts_used:4,total_lease_starts_used:4},transcript:null,previous_previews:[],sent_text:[],notice:null,error:null});
 h.controller.view.capabilities(liveCapabilities);assert.equal(h.node('[data-continuous-listening]').disabled,true);await h.continuous.close();
});
test('missing continuous capability keeps click-start unavailable while PTT remains enabled',async()=>{
 const h=harness();await tick();h.controller.view.capabilities({...liveCapabilities,continuous_listening_enabled:false});assert.equal(h.node('[data-ptt]').disabled,false);assert.equal(h.node('[data-continuous-listening]').hidden,true);assert.equal(h.node('[data-continuous-listening]').disabled,true);await h.continuous.close();
});
test('Close leaves voice controls disabled after the real continuous controller publishes closed',async()=>{
 const h=harness();await tick();h.controller.view.capabilities(liveCapabilities);h.node('[data-close]').fire('click');await tick();await tick();assert.equal(h.node('[data-continuous-listening]').disabled,true);assert.equal(h.node('[data-ptt]').disabled,true);assert.equal(h.node('[data-continuous-send]').disabled,true);
});
