import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST ?? 'apps/web/dist')+'/');
const {ChapterPresentation, isChapterEffect, CHAPTER_PHOTO_SOURCE}=await import(new URL('features/presentation/chapter-presentation.js',dist));
const {SceneEffectExecutor}=await import(new URL('features/presentation/scene-executor.js',dist));
const {SessionController}=await import(new URL('features/session/controller.js',dist));
const {parseSession}=await import(new URL('shared/protocol.js',dist));
const effect=(value,id=value,epoch=1)=>({kind:'scene',value,id,digest:id+'-digest',output_epoch:epoch,activity_seq:epoch});
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};}
function harness({reduced=false,decode=Promise.resolve(),factory=null,onChoice=null,isOfferCurrent=null}={}){
 const frames=new Map(),animations=[],choices=[],listeners=new Map();let next=0,current=true;
 const window={matchMedia:()=>({matches:reduced}),requestAnimationFrame:cb=>{const id=++next;frames.set(id,cb);return id;},cancelAnimationFrame:id=>frames.delete(id)};
 const document={visibilityState:'visible',defaultView:window,createElement:tag=>new Element(tag),addEventListener:(n,c)=>listeners.set(n,c),removeEventListener:n=>listeners.delete(n)};
 class Element{
  constructor(tag='div'){this.tagName=tag;this.ownerDocument=document;this.children=[];this.dataset={};this.style={};this.hidden=false;this.disabled=false;this.isConnected=true;this.attributes={};this.listeners=new Map();this.complete=true;this.naturalWidth=600;this.naturalHeight=460;this.textContent='';}
  setAttribute(n,v){this.attributes[n]=v;} getAttribute(n){return this.attributes[n]??null;}
  append(...nodes){for(const node of nodes){this.children.push(node);node.parentElement=this;}} appendChild(node){this.append(node);return node;}
  insertBefore(node){this.append(node);return node;}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);} remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.isConnected=false;}
  addEventListener(n,c){this.listeners.set(n,c);} removeEventListener(n){this.listeners.delete(n);}
  getBoundingClientRect(){return {width:200,height:200};} getClientRects(){return this.hidden?[]:[this.getBoundingClientRect()];}
  decode(){return decode;} click(){this.listeners.get('click')?.({});}
  animate(){const wait=deferred(),anim={finished:wait.promise,cancel(){wait.reject(Object.assign(new Error('cancel'),{name:'AbortError'}));},finish:wait.resolve};animations.push(anim);return anim;}
  querySelector(selector){if(selector==='.stage-visual')return this;const name=selector.match(/^\[data-([^\]]+)\]$/)?.[1]?.replace(/-([a-z])/g,(_,c)=>c.toUpperCase());for(const c of this.children){if(name&&Object.hasOwn(c.dataset,name))return c;const found=c.querySelector(selector);if(found)return found;}return null;}
 }
 const root=new Element(), preview=new Element('figure');preview.dataset.photo='';preview.hidden=false;root.append(preview);
 for(const name of ['subtitle','pose','sceneLabel','phaseLabel','characterDescription']){const node=new Element();node.dataset[name]='';root.append(node);}
 const nativeQuery=root.querySelector.bind(root),anchor=new Element();root.querySelector=selector=>selector==='.character-anchor'?anchor:nativeQuery(selector);
 const options={onChoice:onChoice??(c=>choices.push(c)),isOfferCurrent:isOfferCurrent??(()=>current),timeoutMs:1000};
 const ui=factory?factory(root,options):new ChapterPresentation(root,options);
 return {ui,root,preview,choices,frames,animations,document,setCurrent:v=>{current=v;},find:name=>root.querySelector(`[data-${name}]`),
  tick(){const batch=[...frames];frames.clear();batch.forEach(([,cb])=>cb(16));},
  async flush(){for(let i=0;i<8;i++)await Promise.resolve();},
  async complete(){for(let i=0;i<8;i++){for(const anim of animations)anim.finish();this.tick();await this.flush();}}};
}
async function present(h,e){const signal=new AbortController().signal;await h.ui.prepare(e,signal);const pending=h.ui.present(e,signal,()=>true);await h.complete();await pending;}

test('only exact scene grants are chapter presentations; preview remains independent',()=>{
 assert.ok(isChapterEffect(effect('xiahe_gift_offer')));assert.equal(isChapterEffect({...effect('xiahe_gift_offer'),kind:'media'}),false);assert.equal(isChapterEffect(effect('trip_photo')),false);assert.equal(CHAPTER_PHOTO_SOURCE,'/assets/scene/trip-memory.svg');
});
test('chapter wire projection is bounded, immutable, and absent on legacy sessions',()=>{
 const base={schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:'c',revision:1,activity_seq:1,input_epoch:1,output_epoch:1,permit_revision:1,phase:'idle',request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null};
 const chapter={schema:'mira.xiahe-chapter.v1',source_hash:'a'.repeat(64),role_active:false,role_name:null,stage:'stranger_cafe',active_gift_offer_id:null,gift_offer_effect_id:null,gift_offer_effect_digest:null,pending_transition:null,completed:false,revision:0,suspended:false};
 assert.equal(parseSession(base).chapter_projection,undefined);assert.equal(parseSession({...base,chapter_projection:null}).chapter_projection,null);
 const parsed=parseSession({...base,chapter_projection:chapter});assert.ok(Object.isFrozen(parsed.chapter_projection));chapter.role_name='夏禾';assert.equal(parsed.chapter_projection.role_name,null);chapter.role_name=null;
 for(const mutation of [{private_log:'secret'},{role_name:'夏阖'},{stage:'claimed_without_receipt'},{completed:'yes'},{role_active:true},{source_hash:'bad'},{gift_offer_effect_id:'arbitrary'},{active_gift_offer_id:'x'.repeat(129)}])assert.throws(()=>parseSession({...base,chapter_projection:{...chapter,...mutation}}),/Invalid chapter projection/);
});
test('prepare stays invisible and offer resolves after animation and two draw frames',async()=>{
 const h=harness(),e=effect('xiahe_gift_offer');await h.ui.prepare(e,new AbortController().signal);
 assert.equal(h.find('chapter-gift')?.hidden,true);let done=false;
 const pending=h.ui.present(e,new AbortController().signal,()=>true).then(()=>done=true);await h.flush();
 assert.equal(h.find('chapter-gift').hidden,false);assert.equal(done,false);assert.equal(h.find('chapter-accept').disabled,true);
 h.animations[0].finish();await h.flush();assert.equal(done,false);h.tick();await h.flush();assert.equal(done,false);h.tick();await pending;
 assert.equal(h.find('chapter-accept').disabled,false);assert.equal(h.preview.hidden,false);h.ui.close();
});
test('offer choices emit one exact identity only; never create received state',async()=>{
 const h=harness(),e=effect('xiahe_gift_offer','offer-1');await present(h,e);
 h.find('chapter-accept').click();h.find('chapter-decline').click();assert.equal(h.choices.length,1);assert.deepEqual(h.choices[0],{effect:e,choice:'accept',text:'我收下这张照片'});
 assert.notEqual(h.find('chapter-gift').dataset.state,'received');h.ui.close();
});
test('re-offer after decline uses new identity and stale previous callback cannot submit',async()=>{
 const h=harness();await present(h,effect('xiahe_gift_offer','offer-1'));const old=h.find('chapter-decline');old.click();h.ui.prepareInput();old.click();
 await present(h,effect('xiahe_gift_offer','offer-2',2));h.find('chapter-accept').click();assert.deepEqual(h.choices.map(c=>c.effect.id),['offer-1','offer-2']);h.ui.close();
});
test('application offer predicate prevents stale clicks',async()=>{
 const h=harness();await present(h,effect('xiahe_gift_offer'));h.setCurrent(false);h.find('chapter-accept').click();assert.equal(h.choices.length,0);h.ui.close();
});
for(const action of ['stop','prepareInput','close'])test(`${action} cancels late decode and preserves preview`,async()=>{
 const wait=deferred(),h=harness({decode:wait.promise}),e=effect('xiahe_gift_offer');const pending=h.ui.prepare(e,new AbortController().signal);const failure=assert.rejects(pending);h.ui[action]();wait.resolve();await failure;
 await assert.rejects(h.ui.present(e,new AbortController().signal,()=>true));assert.equal(h.preview.hidden,false);h.ui.close();
});
for(const action of ['stop','prepareInput','close'])test(`${action} cancels transfer with no received terminal state`,async()=>{
 const h=harness(),e=effect('xiahe_photo_handover');await h.ui.prepare(e,new AbortController().signal);const pending=h.ui.present(e,new AbortController().signal,()=>true);const failure=assert.rejects(pending);await h.flush();h.ui[action]();await h.complete();await failure;
 assert.notEqual(h.find('chapter-gift')?.dataset.state,'received');assert.equal(h.preview.hidden,false);h.ui.close();
});
test('failed decode, removed grant, or hidden page cannot present',async()=>{
 const bad=harness({decode:Promise.reject(new Error('bad image'))});await assert.rejects(bad.ui.prepare(effect('xiahe_gift_offer'),new AbortController().signal));assert.equal(bad.find('chapter-gift').hidden,true);bad.ui.close();
 for(const invalid of ['grant','hidden']){const h=harness(),e=effect('xiahe_recognition');await h.ui.prepare(e,new AbortController().signal);if(invalid==='hidden')h.document.visibilityState='hidden';await assert.rejects(h.ui.present(e,new AbortController().signal,()=>invalid!=='grant'));h.ui.close();}
});
test('reduced motion still waits for draw; handover has a distinct received state',async()=>{
 const h=harness({reduced:true});await present(h,effect('xiahe_recognition'));assert.equal(h.find('chapter-relationship').hidden,false);
 await present(h,effect('xiahe_photo_handover'));assert.equal(h.animations.length,0);assert.equal(h.find('chapter-gift').dataset.state,'received');assert.match(h.find('chapter-status').textContent,/已收下/);assert.equal(h.find('chapter-actions').hidden,true);
 h.ui.stop();assert.equal(h.find('chapter-gift').hidden,false);h.ui.resetRelationship();assert.equal(h.find('chapter-relationship').hidden,true);h.ui.close();
});
test('duplicate completed event and prepared old event cannot re-present',async()=>{
 const h=harness(),e=effect('xiahe_recognition');await present(h,e);await assert.rejects(h.ui.prepare(e,new AbortController().signal));
 const old=effect('xiahe_gift_offer','old'),fresh=effect('xiahe_gift_offer','fresh',2);await h.ui.prepare(old,new AbortController().signal);await h.ui.prepare(fresh,new AbortController().signal);await assert.rejects(h.ui.present(old,new AbortController().signal,()=>true));h.ui.close();
});

const pendingRecognitionProjection={schema:'mira.xiahe-chapter.v1',source_hash:'a'.repeat(64),role_active:false,role_name:null,stage:'stranger_cafe',active_gift_offer_id:null,gift_offer_effect_id:null,gift_offer_effect_digest:null,pending_transition:'x.recognize',completed:false,revision:1,suspended:false};
test('pending recognition polls keep the current cue visible during animation, draw frames, and receipt wait',async()=>{
 const h=harness(),e=effect('xiahe_recognition');await h.ui.prepare(e,new AbortController().signal);
 const pending=h.ui.present(e,new AbortController().signal,()=>true);const settled=pending.then(()=>({ok:true}),error=>({ok:false,error}));
 await h.flush();h.ui.reconcile(pendingRecognitionProjection,1);assert.equal(h.find('chapter-relationship').hidden,false,'pending current recognition is not an exit');
 h.animations[0].finish();await h.flush();h.ui.reconcile({...pendingRecognitionProjection,revision:2},1);h.tick();await h.flush();
 h.ui.reconcile({...pendingRecognitionProjection,revision:3},1);assert.equal(h.find('chapter-relationship').hidden,false);h.tick();await h.flush();assert.equal((await settled).ok,true);
 h.ui.reconcile({...pendingRecognitionProjection,revision:4},1);assert.equal(h.find('chapter-relationship').hidden,false,'local presentation may await its application receipt');
 h.ui.reconcile({...pendingRecognitionProjection,role_active:true,role_name:'夏禾',stage:'recognized',pending_transition:null,revision:5},1);assert.equal(h.find('chapter-relationship').hidden,false);
 h.ui.reconcile({...pendingRecognitionProjection,pending_transition:'x.exit',revision:6},2);assert.equal(h.find('chapter-relationship').hidden,true);h.ui.close();
});
for(const invalid of ['newer-activity','suspended','exited'])test(`pending recognition poll cannot hide an actual ${invalid} revocation`,async()=>{
 const h=harness(),e=effect('xiahe_recognition');await h.ui.prepare(e,new AbortController().signal);
 const pending=h.ui.present(e,new AbortController().signal,()=>true);const failed=assert.rejects(pending);await h.flush();
 h.ui.reconcile({...pendingRecognitionProjection,...(invalid==='suspended'?{suspended:true}:{}),...(invalid==='exited'?{pending_transition:'x.exit'}:{})},invalid==='newer-activity'?2:1);
 assert.equal(h.find('chapter-relationship').hidden,true);await h.complete();await failed;h.ui.close();
});

test('scene executor recognition visibly smiles then restores latest emotion without changing room or persistent appearance',async()=>{
 const transitions=[],draws=[];
 const renderer={prepareState:async()=>true,render:s=>draws.push({...s}),transitionState(s,signal,kind){const pending=deferred();transitions.push({s,signal,kind,pending});return pending.promise;},destroy(){}};
 const h=harness({factory:(root,chapter)=>new SceneEffectExecutor(root,{chapter,characterRendererMode:'code-native-review',characterRendererFactory:async()=>renderer})});
 const e=effect('xiahe_recognition'),signal=new AbortController();await h.ui.prepare(e,signal.signal);const pending=h.ui.present(e,signal.signal,()=>true);await h.flush();
 assert.equal(transitions[0].s.emotion,'emotion_happy');assert.equal(h.root.dataset.scene,'cafe');assert.equal(h.root.dataset.emotion,'emotion_normal');
 h.ui.apply({...effect('caption'),kind:'subtitle',value:'夏禾，真的是你。'});h.ui.setPhase('speaking');
 transitions[0].pending.resolve(true);await h.complete();assert.equal(transitions.length,2);assert.equal(transitions[1].s.emotion,'emotion_normal');assert.equal(transitions[1].s.phase,'speaking');
 let done=false;pending.then(()=>done=true);await h.flush();assert.equal(done,false);transitions[1].pending.resolve(true);await pending;
 assert.equal(h.root.dataset.scene,'cafe');assert.equal(h.root.dataset.emotion,'emotion_normal');assert.equal(draws.at(-1).emotion,'emotion_normal');assert.equal(h.find('subtitle').textContent,'夏禾，真的是你。');h.ui.close();
});
test('Stop during recognition restoration removes the unreceipted cue',async()=>{
 const transitions=[];const renderer={prepareState:async()=>true,render(){},transitionState(s,signal){const pending=deferred();transitions.push({s,signal,pending});return pending.promise;},stop(){},destroy(){}};
 const h=harness({factory:(root,chapter)=>new SceneEffectExecutor(root,{chapter,characterRendererMode:'code-native-review',characterRendererFactory:async()=>renderer})});
 const e=effect('xiahe_recognition'),abort=new AbortController();await h.ui.prepare(e,abort.signal);const pending=h.ui.present(e,abort.signal,()=>true);const failed=assert.rejects(pending);
 transitions[0].pending.resolve(true);await h.complete();assert.equal(transitions.length,2);abort.abort();h.ui.stop();transitions[1].pending.resolve(true);await failed;assert.equal(h.find('chapter-relationship').hidden,true);h.ui.close();
});
test('real controller retains current offer across chat, blocks Stop, and sends one typed choice before handover receipt',async()=>{
 let controller,client='',revision=0,snapshot,activity=0;const requests=[],receipts=[],failures=[],offerSaved=deferred(),chatReady=deferred(),history=[];
 const projection={schema:'mira.xiahe-chapter.v1',source_hash:'a'.repeat(64),role_active:true,role_name:'夏禾',stage:'photo_promise',active_gift_offer_id:null,gift_offer_effect_id:null,gift_offer_effect_digest:null,completed:false,pending_transition:'x.gift_offer',revision:1,suspended:false};
 const create=(grants=[],requestId=null)=>({session_id:'chapter-fixture',client_instance_id:client,revision:++revision,activity_seq:activity,input_epoch:activity,output_epoch:activity,permit_revision:revision,phase:grants.length?'ready':'idle',request_id:requestId,sealed:true,active_grants:grants,presented_effects:[...history],audio_progress:[],last_error:null,chapter_projection:{...projection}});
 const h=harness({isOfferCurrent:e=>controller.isChapterOfferCurrent(e),onChoice:c=>{void controller.chooseChapterGift(c.effect,c.choice);},factory:(root,chapter)=>new SceneEffectExecutor(root,{chapter,characterRendererFactory:null})});
 const api={async create(id){client=id;snapshot=create();return {session:snapshot,session_token:'synthetic'};},async capabilities(){return {generation_mode:'mock',speech_enabled:false,microphone_enabled:false};},snapshot(){return new Promise(()=>{});},
  async input(request){requests.push(request);if(request.text==='chat')await chatReady.promise;activity=request.activity_seq;projection.suspended=false;const grants=request.text==='offer'?[effect('xiahe_gift_offer','offer-current',activity)]:request.chapter_choice?[effect('xiahe_photo_handover','handover',activity)]:[];if(request.chapter_choice)projection.pending_transition='x.gift_accept';snapshot=create(grants,request.request_id);return snapshot;},
  async receipt(receipt){receipts.push(receipt);await offerSaved.promise;const shown=snapshot.active_grants.find(e=>e.id===receipt.effect_id);history.push(shown);if(shown.value==='xiahe_gift_offer')Object.assign(projection,{stage:'gift_offered',pending_transition:null,active_gift_offer_id:'offer.bound',gift_offer_effect_id:shown.id,gift_offer_effect_digest:shown.digest});else Object.assign(projection,{stage:'completed',completed:true,pending_transition:null,active_gift_offer_id:null});snapshot={...snapshot,revision:++revision,presented_effects:[...history],chapter_projection:{...projection}};return snapshot;},
  async stop(request){activity=request.activity_seq;projection.suspended=true;snapshot=create();return snapshot;},async close(){}};
 controller=new SessionController(api,h.ui,{connected(){},update(){},error:e=>{if(e)failures.push(e);},localStop(){}},{apiBase:'/api/v1',pollIntervalMs:999999},{createPlayback:()=>({unlock:async()=>true,stop(){},close:async()=>{},reconcileAuthorization(){}}),createCapture:()=>({start:async()=>false,stop(){},close:async()=>{}})});
 try {
  await controller.connect();await controller.input('offer');await h.complete();await h.flush();assert.equal(receipts.length,1);assert.equal(h.find('chapter-accept').disabled,true);h.find('chapter-accept').click();assert.equal(requests.length,1);
  offerSaved.resolve();await h.flush();assert.equal(h.find('chapter-accept').disabled,false);const offered=snapshot.active_grants[0],animationCount=h.animations.length,originalImage=h.find('chapter-photo').children[0];
  const chat=controller.input('chat');assert.equal(h.find('chapter-accept').disabled,true);h.find('chapter-accept').click();await h.flush();assert.equal(controller.isChapterOfferCurrent(offered),false);chatReady.resolve();await chat;await h.flush();
  assert.equal(snapshot.active_grants.length,0);assert.equal(controller.isChapterOfferCurrent(offered),true);assert.equal(h.find('chapter-accept').disabled,false);assert.equal(h.animations.length,animationCount);assert.equal(h.find('chapter-photo').children[0],originalImage);assert.equal(receipts.length,1,'chat restores an existing offer without replay or new receipt');
  await controller.stop();assert.equal(h.find('chapter-accept').disabled,true);assert.equal(controller.isChapterOfferCurrent(offered),false);
  controller.install({...snapshot,revision:++revision,chapter_projection:{...projection,suspended:false}});assert.equal(controller.isChapterOfferCurrent(offered),false,'late projection cannot release local Stop');
  await controller.input('continue');await h.flush();assert.equal(h.find('chapter-accept').disabled,false);const beforeChoice=requests.length;
  h.find('chapter-accept').click();h.find('chapter-accept').click();await h.flush();assert.equal(requests.length,beforeChoice+1);const request=requests.at(-1);assert.deepEqual(request.chapter_choice,{choice:'accept',offer_id:'offer.bound',offer_effect_id:offered.id,offer_effect_digest:offered.digest});assert.equal(request.text,'我收下这张照片');
  assert.equal(h.root.dataset.scene,'cafe');assert.equal(receipts.length,1,'choice is not a handover receipt');assert.equal((await controller.chooseChapterGift(offered,'decline')).status,'ignored');await h.complete();await h.flush();
  assert.equal(receipts.length,2);assert.equal(h.find('chapter-gift').dataset.state,'received');assert.equal(snapshot.chapter_projection.completed,true);assert.deepEqual(failures,[]);
 }finally{offerSaved.resolve();chatReady.resolve();await controller.close();}
});
