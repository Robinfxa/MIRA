import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist = pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST ?? 'apps/web/dist') + '/');
const {createCodeNativeCharacterRenderer, composeCodeNativeScene, CODE_NATIVE_PHASES} = await import(new URL('features/presentation/code-native-character-renderer.js', dist));
const {initialSceneState} = await import(new URL('features/presentation/scene-state.js', dist));
const {SceneEffectExecutor} = await import(new URL('features/presentation/scene-executor.js', dist));
function harness({reduced=false}={}) {
  const listeners=new Map(), mediaListeners=new Map(), frames=new Map(), allFrames=[];
  let next=0, copies=0, fills=0, clips=0, failCopy=false, failFill=false;
  const contexts=[];
  const host={dataset:{},children:[],appendChild(canvas){this.children.push(canvas);canvas.host=this;}};
  const media={matches:reduced,addEventListener:(name,cb)=>mediaListeners.set(name,cb),removeEventListener:name=>mediaListeners.delete(name)};
  const document={visibilityState:'visible',addEventListener:(name,cb)=>listeners.set(name,cb),removeEventListener:name=>listeners.delete(name)};
  const createCanvas=()=>{
    const context={globalAlpha:1,save(){},restore(){},translate(){},rotate(){},scale(){},clearRect(){},fill(){if(failFill)throw new Error('path draw failed');fills++;},clip(){clips++;},drawImage(){if(failCopy)throw new Error('copy failed');copies++;}};
    contexts.push(context);
    return {width:0,height:0,setAttribute(){},getContext:()=>context,remove(){if(this.host)this.host.children=this.host.children.filter(c=>c!==this);}};
  };
  return {host,document,media,contexts,frames,allFrames,
    get copies(){return copies;},get fills(){return fills;},get clips(){return clips;},
    failCopy(value=true){failCopy=value;},failFill(value=true){failFill=value;},
    hide(){document.visibilityState='hidden';listeners.get('visibilitychange')?.();},
    show(){document.visibilityState='visible';listeners.get('visibilitychange')?.();},
    reduce(matches){media.matches=matches;mediaListeners.get('change')?.({matches});},
    options:{document,window:{matchMedia:()=>media},createCanvas,createPath:data=>({data}),
      requestAnimationFrame:cb=>{const id=++next;frames.set(id,cb);allFrames.push(cb);return id;},cancelAnimationFrame:id=>frames.delete(id)},
    tick(t){const [id,cb]=frames.entries().next().value;frames.delete(id);cb(t);},
  };
}
test('semantic source pins match exact editable vendored bytes and honest readiness',async()=>{
  const root=new URL('../../',import.meta.url);
  const catalog=JSON.parse(await readFile(new URL('apps/web/public/scene/code-native/readiness-catalog.json',root)));
  assert.equal(catalog.schemaVersion,1);assert.equal(catalog.likenessApproved,false);
  assert.equal(catalog.visualAcceptance,'pending');
  assert.deepEqual(Object.keys(catalog.sources).sort(),['body','expression','face','hair','motion']);
  for(const source of Object.values(catalog.sources))assert.equal(createHash('sha256').update(await readFile(new URL(source.path,root))).digest('hex'),source.sha256);
  for(const name of ['black_jacket','cream_inner_only','amber_raincoat'])assert.equal(catalog.assets[`mira.outfit.${name}`].status,'review_only');
  for(const name of ['guarded','happy','shy'])assert.equal(catalog.assets[`mira.emotion.${name}`].status,'review_only');
  assert.equal(catalog.assets['mira.accessory.star_clip'].status,'review_only');
});
test('actual composition draws three different wardrobes with fixed body/hair/head order and clipping',async()=>{
  const h=harness(); const renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
  assert.equal(h.host.children[0].width,288);assert.equal(h.host.children[0].height,408);assert.ok(h.fills>150);assert.ok(h.clips>0);
  const serialized=[];
  for(const outfit of ['outfit_black_jacket','outfit_cream_inner_only','outfit_amber_raincoat']){
    const state={...initialSceneState(),outfit};const scene=composeCodeNativeScene(state,1,true);
    assert.equal(scene.layers[0].id,'composition-layout');assert.equal(scene.layers[0].transform,'translate(18 0)');
    assert.deepEqual(scene.layers[0].children.map(n=>n.id),['body-back-rig','rear-hair-rig','chest-under-neck','neck-rig','body-rig','flowing-shoulder-hair-rig','body-interaction-over-hair','head-rig']);
    assert.ok(!JSON.stringify(scene).includes('shoulder-study'));serialized.push(JSON.stringify(scene));
    await renderer.prepareState(state,new AbortController().signal);renderer.render(state);
  }
  assert.equal(new Set(serialized).size,3);renderer.destroy();
});
test('long shoulder waves are registered to the corrected head and preserve foreground interaction',()=>{
  const find=(nodes,id)=>{for(const node of nodes){if(node.id===id)return node;const child=find(node.children??[],id);if(child)return child;}};
  for(const phase of Object.keys(CODE_NATIVE_PHASES))for(const running of [false,true]){
    const {layers}=composeCodeNativeScene({...initialSceneState(),phase},1,running);
    const head=find(layers,'head-rig'),shoulder=find(layers,'flowing-shoulder-hair-rig');
    assert.ok(shoulder,'long shoulder waves must be composed');
    assert.deepEqual(head.staticRegistration,{x:3,y:0});
    assert.equal(shoulder.transform,head.transform+' translate(3 0)');
    const interaction=find(layers,'body-interaction-over-hair');
    assert.equal(interaction.children[0].id,'elbows-and-forearms');
    assert.equal(interaction.transform,find(layers,'body-rig').transform);
    assert.equal(find(layers,'articulated-lock-root'),undefined,'short branch is replaced exactly once');
    assert.ok(find(layers,'flowing-right-back'));
  }
});
test('hair refinement is pure and composes before all expressions without duplicate anatomy',()=>{
  const face=globalThis.MiraCharacter,body=globalThis.MiraBody,hair=globalThis.MiraHairRefinement;
  assert.equal(typeof hair?.apply,'function');
  const pose=face.stateAt('idle',0,false),base=face.scene(pose),b=body.bodyLayers({...pose,outfit:'black_jacket',reducedMotion:true},face.palette);
  const byId=id=>base.layers.find(n=>n.id===id);
  const raw={width:b.width,height:b.height,palette:face.palette,layers:[{id:'composition-layout',type:'group',transform:'translate(18 0)',children:[...b.back,byId('rear-hair-rig'),...b.underNeck,byId('neck-rig'),...b.front,byId('head-rig')]}]};
  const before=JSON.stringify(raw),refined=hair.apply(raw,pose);
  assert.equal(JSON.stringify(raw),before,'modifier must not mutate source anatomy');
  assert.throws(()=>hair.apply(refined,pose),/exactly once/);
  for(const outfit of ['outfit_black_jacket','outfit_cream_inner_only','outfit_amber_raincoat'])
  for(const emotion of ['emotion_normal','emotion_guarded','emotion_happy','emotion_shy'])
  for(const accessory of ['accessory_camera_clip','accessory_star_clip'])
  for(const phase of Object.keys(CODE_NATIVE_PHASES))for(const running of [false,true]){
    const {layers,pose}=composeCodeNativeScene({...initialSceneState(),outfit,emotion,accessory,phase},1,running),ids=[];
    const visit=n=>{ids.push(n.id);(n.children??[]).forEach(visit);};layers.forEach(visit);
    assert.equal(new Set(ids).size,ids.length);
    assert.equal(ids.filter(id=>id==='flowing-shoulder-hair-rig').length,1);
    assert.equal(ids.includes('star-clip-silver'),accessory==='accessory_star_clip');
    if(!running)assert.equal(pose.mouth,0);
    else if(phase==='speaking')assert.ok(pose.mouth>0);
    else assert.ok(pose.mouth>=0&&pose.mouth<=4.4,'bounded brief theatrical emotional opening');
  }
});
test('four phases use actual source motion channels independently of normal emotion',()=>{
  assert.deepEqual({...CODE_NATIVE_PHASES},{idle:'idle',listening:'listen',thinking:'think',speaking:'speak'});
  for(const [phase,mode]of Object.entries(CODE_NATIVE_PHASES)){
    const scene=composeCodeNativeScene({...initialSceneState(),phase},1,true);assert.equal(scene.pose.mode,mode);
    assert.equal(scene.pose.mouth>0,phase==='speaking');
  }
});
test('unsupported state fails before visible copy, and preparation never commits',async()=>{
  const h=harness();const renderer=await createCodeNativeCharacterRenderer(h.host,h.options);const copies=h.copies;
  await renderer.prepareState({...initialSceneState(),outfit:'outfit_amber_raincoat'},new AbortController().signal);
  assert.equal(h.copies,copies);
  for(const patch of [{emotion:'emotion_unknown'},{accessory:'accessory_unknown'},{action:'camera_lowered'},{expression:'warm'}]){
    await assert.rejects(renderer.prepareState({...initialSceneState(),...patch},new AbortController().signal),/unavailable/);
    assert.throws(()=>renderer.render({...initialSceneState(),...patch}),/unavailable/);
    assert.equal(h.copies,copies);
  }
  renderer.destroy();
});
test('Stop closes mouth immediately and invalidates stale callbacks while retaining wardrobe',async()=>{
  const h=harness();const renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
  renderer.render({...initialSceneState(),phase:'speaking',outfit:'outfit_amber_raincoat'});
  h.tick(0);h.tick(60);const stale=h.allFrames.at(-1);assert.ok(renderer.getStatus().mouth>0);
  renderer.stop();const copies=h.copies;assert.equal(renderer.getStatus().mouth,0);assert.equal(renderer.getStatus().phase,'idle');assert.equal(h.frames.size,0);
  stale(5000);assert.equal(h.copies,copies);assert.equal(renderer.getStatus().seconds,0);
  renderer.render({...initialSceneState(),outfit:'outfit_amber_raincoat'});assert.equal(h.frames.size,0);renderer.destroy();
});
test('hidden, reduced motion and destruction cancel frames and late prepare results',async()=>{
  for(const interrupt of [h=>h.hide(),h=>h.reduce(true)]){
    const h=harness();const renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
    const pending=renderer.prepareState(initialSceneState(),new AbortController().signal);interrupt(h);
    await assert.rejects(pending,{name:'AbortError'});assert.equal(h.frames.size,0);assert.equal(renderer.getStatus().mouth,0);
    h.show();assert.equal(h.frames.size,h.media.matches?0:1);renderer.destroy();renderer.destroy();assert.equal(h.host.children.length,0);
  }
  const h=harness();const abort=new AbortController();const renderer=await createCodeNativeCharacterRenderer(h.host,{...h.options,signal:abort.signal});
  const pending=renderer.prepareState(initialSceneState(),new AbortController().signal);abort.abort();
  await assert.rejects(pending,{name:'AbortError'});assert.equal(h.host.children.length,0);assert.equal(h.frames.size,0);
});
for(const phase of Object.keys(CODE_NATIVE_PHASES))for(const suspension of ['visibility','reduced-motion']){
  test(`${suspension} resumes the current ${phase} phase with one fresh frame clock`,async()=>{
    const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
    try{
      renderer.render({...initialSceneState(),phase});h.tick(0);h.tick(100);
      const seconds=renderer.getStatus().seconds,stale=h.allFrames.at(-1);
      if(suspension==='visibility')h.hide();else h.reduce(true);
      assert.equal(h.frames.size,0);assert.equal(renderer.getStatus().mouth,0);
      renderer.render({...initialSceneState(),phase});assert.equal(h.frames.size,0);
      if(suspension==='visibility')h.show();else h.reduce(false);
      assert.equal(renderer.getStatus().phase,phase);assert.equal(renderer.getStatus().running,true);
      assert.equal(h.frames.size,1,'an unchanged eligible phase must resume');
      const copies=h.copies;stale(9000);assert.equal(h.copies,copies);assert.equal(h.frames.size,1);
      h.tick(10000);assert.equal(renderer.getStatus().seconds,seconds,'suspended time must not advance motion');
      h.tick(10100);assert.ok(renderer.getStatus().seconds>seconds);
      assert.equal(renderer.getStatus().mouth>0,phase==='speaking');
      renderer.render({...initialSceneState(),phase});assert.equal(h.frames.size,1);
    }finally{renderer.destroy();}
  });
}
test('overlapping temporary suspensions release independently, including reduced-motion startup',async()=>{
  const h=harness({reduced:true}),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
  try{
    renderer.render({...initialSceneState(),phase:'speaking'});assert.equal(h.frames.size,0);
    h.hide();h.reduce(false);assert.equal(h.frames.size,0);assert.equal(renderer.getStatus().mouth,0);
    h.show();assert.equal(h.frames.size,1);h.tick(0);assert.ok(renderer.getStatus().mouth>0);
    h.reduce(true);h.hide();h.show();assert.equal(h.frames.size,0);assert.equal(renderer.getStatus().mouth,0);
    h.reduce(false);assert.equal(h.frames.size,1);
    renderer.setPaused(true);h.hide();h.show();h.reduce(true);h.reduce(false);
    assert.equal(h.frames.size,0,'temporary suspension must not clear an explicit pause');
    renderer.setPaused(false);assert.equal(h.frames.size,1);
  }finally{renderer.destroy();}
});
test('Stop before or during suspension cannot be undone by visibility, preferences or stale frames',async()=>{
  for(const suspension of ['visibility','reduced-motion'])for(const stopFirst of [true,false]){
    const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
    try{
      renderer.render({...initialSceneState(),phase:'speaking'});h.tick(0);h.tick(100);
      const stale=h.allFrames.at(-1);
      if(stopFirst)renderer.stop();
      if(suspension==='visibility')h.hide();else h.reduce(true);
      if(!stopFirst)renderer.stop();
      if(suspension==='visibility')h.show();else h.reduce(false);
      renderer.render(initialSceneState());stale(9000);
      assert.equal(renderer.getStatus().phase,'idle');assert.equal(renderer.getStatus().seconds,0);
      assert.equal(renderer.getStatus().mouth,0);assert.equal(renderer.getStatus().running,false);assert.equal(h.frames.size,0);
    }finally{renderer.destroy();}
  }
});
test('a new active phase received while hidden resumes only after the page becomes visible',async()=>{
  const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
  try{
    renderer.stop();h.hide();renderer.render({...initialSceneState(),phase:'thinking'});
    renderer.render({...initialSceneState(),phase:'speaking'});assert.equal(h.frames.size,0);assert.equal(renderer.getStatus().mouth,0);
    h.show();assert.equal(h.frames.size,1);h.tick(0);assert.ok(renderer.getStatus().mouth>0);
  }finally{renderer.destroy();}
});
test('temporary suspension cancels camera completion while current ambient motion may resume',async()=>{
  for(const suspension of ['visibility','reduced-motion']){
    const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
    try{
      renderer.render({...initialSceneState(),phase:'speaking'});
      const pending=renderer.transitionState({...initialSceneState(),phase:'speaking',action:'camera_raise'},new AbortController().signal);
      const rejected=assert.rejects(pending,{name:'AbortError'});h.tick(0);h.tick(100);h.tick(200);
      const progress=renderer.getMotionState().progress,stale=h.allFrames.at(-1);assert.ok(progress>0&&progress<1);
      if(suspension==='visibility')h.hide();else h.reduce(true);
      await rejected;assert.equal(renderer.getMotionState().status,'cancelled');
      if(suspension==='visibility')h.show();else h.reduce(false);
      assert.equal(h.frames.size,1);const copies=h.copies;stale(9000);assert.equal(h.copies,copies);
      h.tick(10000);h.tick(10100);assert.ok(renderer.getStatus().mouth>0);
      assert.equal(renderer.getMotionState().progress,progress);assert.equal(renderer.getMotionState().status,'cancelled');
    }finally{renderer.destroy();}
  }
});
test('destroyed resources and late preparations stay invalid after temporary suspension ends',async()=>{
  const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
  renderer.render({...initialSceneState(),phase:'speaking'});const stale=h.allFrames.at(-1);
  const pending=renderer.prepareState({...initialSceneState(),phase:'speaking'},new AbortController().signal);
  h.hide();renderer.destroy();h.show();h.reduce(false);stale(9000);
  await assert.rejects(pending,{name:'AbortError'});assert.equal(h.host.children.length,0);assert.equal(h.frames.size,0);
});
test('repeated renders own one RAF and reduced-motion startup has none',async()=>{
  const h=harness();const renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
  for(let i=0;i<20;i++)renderer.render({...initialSceneState(),phase:'listening'});assert.equal(h.frames.size,1);renderer.destroy();
  const reduced=harness({reduced:true});const still=await createCodeNativeCharacterRenderer(reduced.host,reduced.options);
  still.render({...initialSceneState(),phase:'speaking'});assert.equal(reduced.frames.size,0);assert.equal(still.getStatus().mouth,0);still.destroy();
});
test('draw failure leaves previous scene facts and no candidate DOM commit',async()=>{
  const h=harness();const renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
  const slots=new Map(['subtitle','photo','pose','scene-label','phase-label','character-description'].map(name=>[name,{textContent:'',hidden:true}]));
  const root={dataset:{},querySelector(selector){return selector==='.character-anchor'?h.host:slots.get(selector.slice(6,-1));}};
  const executor=new SceneEffectExecutor(root,{characterRendererMode:'code-native-review',characterRendererFactory:async()=>renderer});
  await Promise.resolve();await Promise.resolve();await Promise.resolve();
  const effect={id:'wardrobe',kind:'pose',value:'outfit_amber_raincoat',digest:'a'.repeat(64),activity_seq:1,output_epoch:1};
  await executor.prepare(effect,new AbortController().signal);const previous={...root.dataset};const description=slots.get('character-description').textContent;
  h.failCopy();assert.throws(()=>executor.apply(effect),/did not commit/);
  assert.equal(root.dataset.outfit,previous.outfit);assert.equal(slots.get('character-description').textContent,description);
  assert.equal(h.host.children.length,1);h.failCopy(false);executor.stop();executor.close();
});
test('invalid times stay finite and proportion layout never animates the whole scene',()=>{
  for(const time of [NaN,Infinity,-Infinity,-1,0,1e12]){
    const scene=composeCodeNativeScene(initialSceneState(),time,true);
    assert.doesNotMatch(JSON.stringify(scene),/NaN|Infinity/);
    assert.equal(scene.layers[0].transform,'translate(18 0)');
    for(const index of [0,2,4])assert.equal(scene.layers[0].children[index].transform,'translate(-28.5 -83) scale(1.5)');
  }
});

const settle = async()=>{for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve));};
async function controllerHarness({hold=false,fail=false}={}) {
  const {SessionController}=await import(new URL('features/session/controller.js',dist));
  const h=harness();const renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
  let release;const barrier=new Promise(resolve=>{release=resolve;});
  const original=renderer.prepareState.bind(renderer);
  renderer.prepareState=async(state,signal)=>{const value=await original(state,signal);if(hold)await barrier;if(fail)h.failCopy();return value;};
  const slots=new Map(['subtitle','photo','pose','scene-label','phase-label','character-description'].map(name=>[name,{textContent:'',hidden:true}]));
  const root={dataset:{},querySelector(selector){return selector==='.character-anchor'?h.host:slots.get(selector.slice(6,-1));}};
  const executor=new SceneEffectExecutor(root,{characterRendererMode:'code-native-review',characterRendererFactory:async()=>renderer});
  let client='',revision=0,current;const receipts=[],errors=[];
  const snapshot=(activity,grants=[],requestId=null)=>({schema_version:'0.1.0-foundation',session_id:'semantic-test',client_instance_id:client,
    revision:++revision,activity_seq:activity,input_epoch:activity,output_epoch:activity,permit_revision:revision,
    phase:'ready',request_id:requestId,sealed:true,active_grants:grants,presented_effects:[],audio_progress:[],last_error:null});
  const api={create:async id=>{client=id;current=snapshot(0);return{session:current,session_token:'synthetic'};},
    capabilities:async()=>({generation_mode:'injected',speech_enabled:false,microphone_enabled:false,qualification:'injected_unverified'}),
    snapshot:()=>new Promise(()=>{}),
    input:async request=>{current=snapshot(request.activity_seq,[{id:'wardrobe-'+request.activity_seq,kind:'pose',value:request.text,digest:'a'.repeat(64),activity_seq:request.activity_seq,output_epoch:request.activity_seq,cue_id:null,cue_speech_id:null}],request.request_id);return current;},
    receipt:async value=>{receipts.push(value);return current;},
    stop:async request=>{current=snapshot(request.activity_seq);return current;},close:async()=>{},
  };
  const controller=new SessionController(api,executor,{connected(){},update(){},error(message){if(message)errors.push(message);},localStop(){}},
    {apiBase:'/api/v1',pollIntervalMs:999999},{
      createPlayback:()=>({unlock:async()=>true,stop(){},reconcileAuthorization(){},close:async()=>{}}),
      createCapture:()=>({start:async()=>false,stop(){},close:async()=>{}}),
    });
  await controller.connect();await settle();return{...h,root,slots,controller,receipts,errors,release,renderer,executor};
}
test('actual controller receipts follow committed wardrobe and Stop preserves the presented outfit',async()=>{
  const h=await controllerHarness();try{
    await h.controller.input('outfit_amber_raincoat');await settle();
    assert.equal(h.root.dataset.outfit,'outfit_amber_raincoat');assert.equal(h.receipts.length,1);
    h.renderer.render({...initialSceneState(),outfit:'outfit_amber_raincoat',phase:'speaking'});
    await h.controller.stop();assert.equal(h.root.dataset.outfit,'outfit_amber_raincoat');assert.equal(h.renderer.getStatus().mouth,0);assert.equal(h.receipts.length,1);
  }finally{await h.controller.close();}
});
test('actual controller refuses unsupported or failed code-native drawing without a receipt',async()=>{
  for(const options of [{value:'face_warm'},{value:'outfit_amber_raincoat',fail:true}]){
    const h=await controllerHarness(options);try{
      await h.controller.input(options.value);await settle();assert.equal(h.receipts.length,0);assert.ok(h.errors.length>0);
      assert.equal(h.root.dataset.outfit,'outfit_black_jacket');assert.equal(h.root.dataset.emotion,'emotion_normal');
    }finally{await h.controller.close();}
  }
});
test('actual gate rejects an uncooperative late code-native preparation after Stop or Close',async()=>{
  for(const method of ['stop','close']){
    const h=await controllerHarness({hold:true});try{
      await h.controller.input('outfit_amber_raincoat');await settle();assert.equal(h.receipts.length,0);
      await h.controller[method]();h.release();await settle();assert.equal(h.receipts.length,0);assert.equal(h.root.dataset.outfit,'outfit_black_jacket');
      assert.equal(h.frames.size,0);
    }finally{await h.controller.close();}
  }
});
test('new input invalidates old pending refined geometry before any presentation receipt',async()=>{
  const h=await controllerHarness({hold:true});try{
    await h.controller.input('outfit_amber_raincoat');await settle();
    await h.controller.input('emotion_happy');await settle();
    assert.equal(h.receipts.length,0);h.release();await settle();
    for(let t=0;t<=700;t+=100)h.tick(t);await settle();
    assert.equal(h.receipts.length,1);
    assert.equal(h.root.dataset.outfit,'outfit_black_jacket');
    assert.equal(h.root.dataset.emotion,'emotion_happy');
  }finally{await h.controller.close();}
});
test('renderer initialization rejection does not block session creation or an editable draft',async()=>{
  const {SessionController}=await import(new URL('features/session/controller.js',dist));
  const slots=new Map(['subtitle','photo','pose','scene-label','phase-label','character-description'].map(name=>[name,{textContent:'',hidden:true}]));
  const root={dataset:{},querySelector(selector){return selector==='.character-anchor'?{dataset:{}}:slots.get(selector.slice(6,-1));}};
  const executor=new SceneEffectExecutor(root,{characterRendererMode:'code-native-review',characterRendererFactory:async()=>{throw new Error('synthetic Canvas unavailable');}});
  let requests=0,connected=0;
  const api={create:async client=>{requests++;return{session:{schema_version:'0.1.0-foundation',session_id:'session-without-art',client_instance_id:client,revision:1,activity_seq:0,input_epoch:0,output_epoch:0,permit_revision:1,phase:'stopped',request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null},session_token:'synthetic'};},capabilities:async()=>({speech_enabled:false,microphone_enabled:false}),snapshot:()=>new Promise(()=>{}),close:async()=>{}};
  const controller=new SessionController(api,executor,{connected(){connected++;},update(){},error(){},localStop(){}},{apiBase:'/api/v1',pollIntervalMs:999999},{
    createPlayback:()=>({unlock:async()=>true,stop(){},reconcileAuthorization(){},close:async()=>{}}),
    createCapture:()=>({start:async()=>false,stop(){},close:async()=>{}}),
  });
  try{await controller.connect();await settle();assert.equal(requests,1);assert.equal(connected,1);
    await assert.rejects(executor.prepare({id:'x',kind:'pose',value:'outfit_amber_raincoat',digest:'a'.repeat(64),activity_seq:1,output_epoch:1},new AbortController().signal),/unavailable/);
  }finally{await controller.close();}
});


test('all reviewed emotional faces and silver clip commit with wardrobe and keep mouth lifecycle',async()=>{
 const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
 const faces=new Set();
 for(const emotion of ['emotion_normal','emotion_guarded','emotion_happy','emotion_shy']){
  const state={...initialSceneState(),emotion,accessory:'accessory_star_clip',outfit:'outfit_amber_raincoat',phase:'speaking'};
  const geometry=composeCodeNativeScene(state,1,true);faces.add(JSON.stringify(geometry.layers));
  assert.match(JSON.stringify(geometry.layers),/star-clip-silver/);
  await renderer.prepareState(state,new AbortController().signal);renderer.render(state);
  assert.ok(renderer.getStatus().mouth>0);renderer.stop();assert.equal(renderer.getStatus().mouth,0);
 }
 assert.equal(faces.size,4);renderer.destroy();
});
test('actual controller only receipts a fully drawn target expression and accessory',async()=>{
 const h=await controllerHarness();try{
  await h.controller.input('emotion_happy');await settle();
  for(let t=0;t<=700;t+=100)h.tick(t);await settle();assert.equal(h.root.dataset.emotion,'emotion_happy');assert.equal(h.receipts.length,1);
  await h.controller.input('accessory_star_clip');await settle();assert.equal(h.root.dataset.accessory,'accessory_star_clip');assert.equal(h.receipts.length,2);
  assert.match(h.slots.get('character-description').textContent,/神情开心.*银色星星发卡/);
  await h.controller.stop();assert.equal(h.root.dataset.emotion,'emotion_happy');assert.equal(h.root.dataset.accessory,'accessory_star_clip');
 }finally{await h.controller.close();}
});

test('camera transition draws intermediate articulated poses and resolves only after endpoint copy',async()=>{
 const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
 let done=false;const target={...initialSceneState(),action:'camera_raise'};
 const pending=renderer.transitionState(target,new AbortController().signal).then(()=>done=true);
 assert.equal(done,false);h.tick(0);h.tick(100);await Promise.resolve();
 const halfway=renderer.getMotionState();assert.ok(halfway.progress>0&&halfway.progress<1);assert.equal(done,false);
 const before=h.copies;for(let t=200;t<=1200;t+=100)h.tick(t);await pending;
 assert.equal(done,true);assert.ok(h.copies>before);assert.equal(renderer.getMotionState().progress,1);
 const back=renderer.transitionState(initialSceneState(),new AbortController().signal);
 for(let t=1300;t<=2600;t+=100)h.tick(t);await back;assert.equal(renderer.getMotionState().progress,0);renderer.destroy();
});
test('camera Stop and abort preserve partial geometry and stale callbacks cannot finish',async()=>{
 for(const stop of ['signal','stop','hide','destroy']){
  const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options),abort=new AbortController();
  const pending=renderer.transitionState({...initialSceneState(),action:'camera_raise'},abort.signal);
  const rejected=assert.rejects(pending,{name:'AbortError'});h.tick(0);h.tick(100);h.tick(200);
  const progress=renderer.getMotionState().progress,stale=h.allFrames.at(-1);
  if(stop==='signal')abort.abort();else if(stop==='hide')h.hide();else renderer[stop]();
  await rejected;assert.equal(renderer.getMotionState().progress,progress);
  const copies=h.copies;stale(9000);assert.equal(h.copies,copies);
  if(stop!=='destroy'){renderer.render(initialSceneState());assert.equal(renderer.getMotionState().progress,progress);renderer.destroy();}
 }
});
test('same-target camera requests do not restart and reduced motion commits a terminal drawing',async()=>{
 const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options),abort=new AbortController();
 const state={...initialSceneState(),action:'camera_raise'},first=renderer.transitionState(state,abort.signal);
 h.tick(0);h.tick(100);const progress=renderer.getMotionState().progress;
 const same=renderer.transitionState(state,abort.signal);assert.equal(renderer.getMotionState().progress,progress);
 for(let t=200;t<=1200;t+=100)h.tick(t);await Promise.all([first,same]);
 const copies=h.copies;await renderer.transitionState(state,abort.signal);assert.equal(renderer.getMotionState().progress,1);assert.equal(h.copies,copies+1);renderer.destroy();
 const r=harness({reduced:true}),still=await createCodeNativeCharacterRenderer(r.host,r.options);const before=r.copies;
 await still.transitionState(state,new AbortController().signal);assert.equal(still.getMotionState().progress,1);assert.equal(r.copies,before+1);assert.equal(r.frames.size,0);still.destroy();
});
test('failed terminal camera copy retains last visible partial pose and rejects completion',async()=>{
 const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
 const pending=renderer.transitionState({...initialSceneState(),action:'camera_raise'},new AbortController().signal);
 const rejected=assert.rejects(pending,/drawing failed/);h.tick(0);h.tick(100);
 const progress=renderer.getMotionState().progress,copies=h.copies;
 h.failCopy();h.tick(200);await rejected;
 assert.equal(h.copies,copies);assert.equal(h.host.children.length,1);assert.equal(renderer.getMotionState().progress,progress);
 assert.equal(h.frames.size,0);assert.equal(h.host.dataset.rendererError,'drawing-failed');
 renderer.stop();assert.equal(h.host.children.length,1);renderer.destroy();
});
test('camera deadline cancels a frozen frame loop and preserves last physical pose',(t)=>{
 t.mock.timers.enable({apis:['setTimeout']});
 return (async()=>{const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
  const pending=renderer.transitionState({...initialSceneState(),action:'camera_raise'},new AbortController().signal);
  const rejected=assert.rejects(pending,/deadline/);h.tick(0);h.tick(100);const progress=renderer.getMotionState().progress;
  t.mock.timers.tick(5001);await rejected;assert.equal(renderer.getMotionState().progress,progress);assert.equal(h.frames.size,0);renderer.destroy();
 })();
});
test('phase changes during camera motion remain current on terminal completion',async()=>{
 const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
 const pending=renderer.transitionState({...initialSceneState(),action:'camera_raise'},new AbortController().signal);
 h.tick(0);h.tick(100);renderer.render({...initialSceneState(),phase:'speaking',subtitle:'latest'});
 for(let t=200;t<=1300;t+=100)h.tick(t);await pending;
 assert.equal(renderer.getStatus().phase,'speaking');assert.ok(renderer.getStatus().mouth>0);renderer.destroy();
});

test('user-approved local neck root remains in front of rear hair with its approved surface and registration',()=>{
 // Scoped approval: Sentinel_0b8188c8c67881918c563c414cc19e2a, the 1631 root image.
 // This guards that local surface/depth relation. It does not approve the rest of the art.
 const find=(nodes,id)=>{for(const node of nodes){if(node.id===id)return node;const v=find(node.children??[],id);if(v)return v;}};
 const normalize=n=>[n.id,n.d??null,n.fill??null,n.opacity??1,n.clip??null,n.transform??null,(n.children??[]).map(normalize)];
 for(const outfit of ['outfit_black_jacket','outfit_cream_inner_only','outfit_amber_raincoat']){
  const scene=composeCodeNativeScene({...initialSceneState(),outfit},0,false),layout=scene.layers[0],ids=layout.children.map(n=>n.id);
  assert.equal(layout.transform,'translate(18 0)');
  assert.ok(ids.indexOf('rear-hair-rig')<ids.indexOf('chest-under-neck'));
  assert.ok(ids.indexOf('chest-under-neck')<ids.indexOf('head-rig'));
  const chest=find(scene.layers,'chest-under-neck'),root=find(chest.children,'left-shoulder-bridge-behind-hair-root-visible');
  assert.ok(root,'the approved medial trapezius must not fall behind the rear-hair layer');
  assert.equal(chest.transform,'translate(-28.5 -83) scale(1.5)');
  assert.equal(createHash('sha256').update(JSON.stringify(normalize(root))).digest('hex'),'8da3e4fbd59ec9f66e3434b10192406e0ecdcfc0c834061940c00a9190629e98');
  assert.deepEqual(find(scene.layers,'head-rig').staticRegistration,{x:3,y:0});
 }
});

test('phase pose blends on the renderer clock and rapid retarget starts from the visible pose',async()=>{
 const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
 try{
  h.tick(0);h.tick(100);const idle=renderer.getStatus();
  renderer.render({...initialSceneState(),phase:'thinking'});
  assert.equal(renderer.getStatus().head,idle.head,'phase entry must not snap the head');
  h.tick(200);h.tick(300);const midway=renderer.getStatus();
  assert.ok(midway.head>idle.head&&midway.head<2.9);
  renderer.render({...initialSceneState(),phase:'listening'});
  assert.equal(renderer.getStatus().head,midway.head,'rapid retarget must use current blended pose');
  for(let t=400;t<=1100;t+=100)h.tick(t);
  assert.ok(renderer.getStatus().head<0);
  renderer.render({...initialSceneState(),phase:'speaking'});h.tick(1200);h.tick(1300);
  const stale=h.allFrames.at(-1);renderer.stop();const copies=h.copies;
  assert.equal(renderer.getStatus().head,0);assert.equal(renderer.getStatus().gesture,0);stale(9000);assert.equal(h.copies,copies);
 }finally{renderer.destroy();}
});

test('explicit camera action takes the visible grip pose and cancellation preserves its actual matrix',async()=>{
 for(const suspension of ['stop','hide','reduce','pause','abort']){
  const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options),abort=new AbortController();
  try{
   const speaking={...initialSceneState(),phase:'speaking'};renderer.render(speaking);
   for(let t=0;t<=1800;t+=100)h.tick(t);
   const initial=renderer.getStatus().cameraTransform;assert.notEqual(initial,'translate(0 8)');
   const pending=renderer.transitionState({...speaking,action:'camera_raise'},abort.signal);
   const rejected=assert.rejects(pending,{name:'AbortError'});
   h.tick(1900);assert.equal(renderer.getStatus().cameraTransform,initial,'taking ownership must not snap the visible grip');
   h.tick(2000);const physical=renderer.getStatus().cameraTransform;
   if(suspension==='stop')renderer.stop();else if(suspension==='hide')h.hide();else if(suspension==='reduce')h.reduce(true);else if(suspension==='pause')renderer.setPaused(true);else abort.abort();
   await rejected;assert.equal(renderer.getStatus().cameraTransform,physical,'cancellation must preserve the actual drawn matrix');
   if(suspension==='hide')h.show();else if(suspension==='reduce')h.reduce(false);
   if(h.frames.size){h.tick(2100);h.tick(2200);assert.equal(renderer.getStatus().cameraTransform,physical,'ambient resumption cannot move a cancelled partial grip');}
  }finally{renderer.destroy();}
 }
});

test('successful camera return restores ambient hand gestures gradually, without unlocking partial cancellations',async()=>{
 const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
 try{
  const speaking={...initialSceneState(),phase:'speaking'};renderer.render(speaking);
  const up=renderer.transitionState({...speaking,action:'camera_raise'},new AbortController().signal);
  for(let t=0;t<=1100;t+=100)h.tick(t);await up;
  const down=renderer.transitionState(speaking,new AbortController().signal);
  for(let t=1200;t<=2200;t+=100)h.tick(t);await down;
  assert.equal(renderer.getMotionState().status,'completed');assert.equal(renderer.getMotionState().progress,0);
  assert.equal(renderer.getStatus().cameraTransform,'translate(0 8)','the ready endpoint itself must be exact');
  h.tick(2300);const first=renderer.getStatus();
  assert.ok(first.gesture>0,'a successfully returned camera must allow future speaking gestures');
  const full=globalThis.MiraCharacter.stateAt('speak',first.seconds,true).gesture;
  assert.ok(first.gesture<full*.3,'restoring the gesture must fade in rather than snap');
  for(let t=2400;t<=2800;t+=100)h.tick(t);
  assert.ok(renderer.getStatus().gesture>0);assert.equal(renderer.getMotionState().progress,0);
 }finally{renderer.destroy();}
});

test('emotion completion waits for its fully drawn target while phase and subtitle updates continue',async()=>{
 const h=await controllerHarness();try{
  await h.controller.input('emotion_happy');await settle();
  assert.equal(h.receipts.length,0);assert.equal(h.root.dataset.emotion,'emotion_normal');
  h.executor.setPhase('speaking');
  h.executor.apply({id:'text-live',kind:'subtitle',value:'text continues',digest:'a'.repeat(64),activity_seq:1,output_epoch:1});
  assert.equal(h.slots.get('subtitle').textContent,'text continues');
  h.tick(0);h.tick(100);await settle();assert.equal(h.receipts.length,0);assert.ok(h.renderer.getStatus().mouth>0);
  for(let t=200;t<=700;t+=100)h.tick(t);await settle();
  assert.equal(h.receipts.length,1);assert.equal(h.root.dataset.emotion,'emotion_happy');
  assert.equal(h.renderer.getStatus().lipWeights.happy,1);
  assert.equal(h.renderer.getStatus().phase,'speaking');assert.equal(h.slots.get('subtitle').textContent,'text continues');
 }finally{await h.controller.close();}
});

test('retargeted emotion receipts exclude the cancelled predecessor',async()=>{
 const h=await controllerHarness();try{
  await h.controller.input('emotion_happy');await settle();h.tick(0);h.tick(100);assert.equal(h.receipts.length,0);
  await h.controller.input('emotion_shy');await settle();
  for(let t=200;t<=1000;t+=100)h.tick(t);await settle();
  assert.equal(h.receipts.length,1);assert.equal(h.root.dataset.emotion,'emotion_shy');
  assert.equal(h.renderer.getStatus().lipWeights.shy,1);
 }finally{await h.controller.close();}
});

test('emotion Stop, suspension, abort and close never finish through stale frames',async()=>{
 for(const reason of ['stop','hide','reduce','pause','abort','destroy']){
  const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options),signal=new AbortController();
  try{
   const pending=renderer.transitionState({...initialSceneState(),emotion:'emotion_happy'},signal.signal,'emotion');
   const rejected=assert.rejects(pending,{name:'AbortError'});h.tick(0);h.tick(100);
   const stale=h.allFrames.at(-1);
   if(reason==='hide')h.hide();else if(reason==='reduce')h.reduce(true);else if(reason==='pause')renderer.setPaused(true);else if(reason==='abort')signal.abort();else renderer[reason]();
   await rejected;const copies=h.copies;stale(5000);assert.equal(h.copies,copies);
   if(reason!=='destroy')assert.notEqual(renderer.getEmotionMotionState().status,'completed');
  }finally{renderer.destroy();}
 }
});

test('reduced-motion emotion may complete only after an immediate full target copy',async()=>{
 const h=harness({reduced:true}),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
 try{const before=h.copies;
  await renderer.transitionState({...initialSceneState(),emotion:'emotion_happy'},new AbortController().signal,'emotion');
  assert.equal(h.copies,before+1);assert.equal(h.frames.size,0);assert.equal(renderer.getStatus().lipWeights.happy,1);
  assert.equal(renderer.getEmotionMotionState().status,'completed');assert.equal(renderer.getStatus().mouth,0);
 }finally{renderer.destroy();}
});

test('emotion drawing failure and frozen-clock deadline cannot claim the target endpoint',(t)=>{
 t.mock.timers.enable({apis:['setTimeout']});
 return (async()=>{
  for(const fail of ['copy','deadline']){
   const h=harness(),renderer=await createCodeNativeCharacterRenderer(h.host,h.options);
   try{
    const pending=renderer.transitionState({...initialSceneState(),emotion:'emotion_happy'},new AbortController().signal,'emotion');
    const rejected=assert.rejects(pending,/drawing failed|deadline/);h.tick(0);h.tick(100);
    const progress=renderer.getEmotionMotionState().progress;
    if(fail==='copy'){h.failCopy();h.tick(200);}else t.mock.timers.tick(5001);
    await rejected;assert.equal(renderer.getEmotionMotionState().status,'cancelled');
    assert.equal(renderer.getEmotionMotionState().progress,progress);assert.ok(renderer.getStatus().lipWeights.happy<1);
   }finally{renderer.destroy();}
  }
 })();
});

test('limited yaw and shoulder channels reset on Stop, hidden and reduced motion without completing a camera cue',async()=>{
 for(const suspend of ['stop','hide','reduce']){
  const h=harness(),r=await createCodeNativeCharacterRenderer(h.host,h.options);
  r.render({...initialSceneState(),phase:'listening'});h.tick(0);h.tick(100);
  assert.ok(Math.abs(r.getStatus().yaw)>3);assert.ok(r.getStatus().listeningLean>0);
  const pending=r.transitionState({...initialSceneState(),phase:'listening',action:'camera_raise'},new AbortController().signal);
  const outcome=pending.then(()=> 'completed',()=> 'cancelled');h.tick(200);h.tick(300);
  if(suspend==='stop')r.stop();else if(suspend==='hide')h.hide();else h.reduce(true);
  assert.equal(await outcome,'cancelled',suspend);
  assert.notEqual(r.getMotionState().status,'completed');
  for(const key of ['yaw','shoulderFollow','shoulderRaise','listeningLean'])assert.equal(r.getStatus()[key],0,suspend+':'+key);
  assert.equal(h.frames.size,0);r.destroy();
 }
});
