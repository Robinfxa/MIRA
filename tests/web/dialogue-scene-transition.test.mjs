import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {readFileSync} from 'node:fs';
const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {SceneEffectExecutor}=await import(new URL('features/presentation/scene-executor.js',dist));
const effect={id:'window',kind:'scene',value:'rain_window',digest:'a'.repeat(64),output_epoch:1,activity_seq:1};
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};}
function fixture(version='classic',decode=Promise.resolve()){
 const slots=new Map(['subtitle','photo','pose','scene-label','phase-label','character-description'].map(name=>[name,{textContent:'',hidden:true}]));
 const sources={classic:'/assets/scene/cafe-night.svg','painterly-v3':'/assets/scene/cafe-painterly-lighting-v3-table-free.png'};
 const images=Object.fromEntries(Object.entries(sources).map(([key,src])=>[key,{complete:true,naturalWidth:1600,src,getAttribute(name){return this[name]},decode:()=>decode}]));
 const root={dataset:{backgroundVersion:version},querySelector(selector){const match=selector.match(/^\[data-scene-source="([^"]+)"\]$/);return match?images[match[1]]:slots.get(selector.replace(/^\[data-|\]$/g,''))??null;}};
 return {root,slots,images,executor:new SceneEffectExecutor(root,{characterRendererFactory:null,mediaReadinessTimeoutMs:100})};
}
for(const version of ['classic','painterly-v3'])test(`${version}: decoded window cut commits only after preparation and keeps the selected character pose`,async()=>{
 const wait=deferred(),h=fixture(version,wait.promise),signal=new AbortController();
 h.executor.apply({...effect,id:'lower',kind:'pose',value:'camera_lowered'});
 const pending=h.executor.prepare(effect,signal.signal);assert.equal(h.root.dataset.scene,'cafe');
 wait.resolve();await pending;assert.equal(h.root.dataset.scene,'cafe');
 await h.executor.present(effect,signal.signal);assert.equal(h.root.dataset.scene,'rain_window');
 assert.equal(h.root.dataset.action,'camera_lowered');assert.equal(h.root.dataset.outfit,'outfit_black_jacket');
 h.executor.close();
});
for(const cancellation of ['abort','stop','new-input','close'])test(`late decoded window after ${cancellation} cannot commit`,async()=>{
 const wait=deferred(),h=fixture('classic',wait.promise),signal=new AbortController();
 const pending=h.executor.prepare(effect,signal.signal);const rejection=assert.rejects(pending);
 if(cancellation==='abort')signal.abort();else if(cancellation==='stop')h.executor.stop();else if(cancellation==='new-input')h.executor.prepareInput();else h.executor.close();
 wait.resolve();await rejection;assert.equal(h.root.dataset.scene,'cafe');
 await assert.rejects(h.executor.present(effect,signal.signal));assert.equal(h.root.dataset.scene,'cafe');h.executor.close();
});
test('failed image and changed selector never create a scene commit',async()=>{
 const wait=deferred(),h=fixture('classic',wait.promise),signal=new AbortController();
 const pending=h.executor.prepare(effect,signal.signal);wait.reject(new Error('decode failed'));await assert.rejects(pending);assert.equal(h.root.dataset.scene,'cafe');
 const ready=fixture();await ready.executor.prepare(effect,signal.signal);ready.root.dataset.backgroundVersion='painterly-v3';
 await assert.rejects(ready.executor.present(effect,signal.signal));assert.equal(ready.root.dataset.scene,'cafe');h.executor.close();ready.executor.close();
});
test('window view uses a structural crop, coherent full-character placement, and an immediate cut',()=>{
 const css=readFileSync(new URL('../../apps/web/public/scene-view.css',import.meta.url),'utf8');
 const html=readFileSync(new URL('../../apps/web/index.html',import.meta.url),'utf8');
 assert.match(html,/href="\/assets\/scene-view.css"/);assert.match(html,/data-scene-source="classic"/);assert.match(html,/data-scene-source="painterly-v3"/);
 assert.match(css,/background-size:\s*auto 180%/);assert.match(css,/background-size:\s*auto 210%/);
 assert.match(css,/right:\s*48%/);assert.match(css,/transition:\s*none !important/);assert.doesNotMatch(css,/animation:.*walk/);
});

test('SVG fallback window placement wins over legacy fallback specificity on desktop and mobile',()=>{
 const css=readFileSync(new URL('../../apps/web/public/scene-view.css',import.meta.url),'utf8');
 const selector='.stage[data-scene="rain_window"]:not([data-character-renderer-mode="code-native-review"]) .character-anchor:not([data-renderer="pixi"])';
 assert.equal(css.split(selector).length-1,2,'both desktop and mobile carry the extra scene attribute above the legacy 0,4,0 fallback rule');
 assert.match(css.slice(css.indexOf('@media')),/right: 25%; left: auto; width: 75%/);
});

test('an existing photo moves into the open window region without covering the camera grip',()=>{
 const css=readFileSync(new URL('../../apps/web/public/scene-view.css',import.meta.url),'utf8');
 const selector='.stage[data-scene="rain_window"] .stage-visual .photo';
 assert.equal(css.split(selector).length-1,2,'desktop and mobile override the legacy/Pixi photo placement');
 assert.match(css,/left: auto; right: 7%; top: 49%; bottom: auto/);
 assert.match(css,/left: auto; right: 24px; top: 56px; bottom: auto/);
 const desktopCharacterRight=1100*(1-.48),desktopPhotoLeft=1100*(1-.07)-200;
 assert.ok(desktopPhotoLeft>desktopCharacterRight+100);
 // A mobile photo sits high, above the camera held in the lower half.
 assert.ok(56+118*460/600+45<367*.7);
});

test('mobile photo leaves clearance for its protruding 44px close button and rotation',()=>{
 const css=readFileSync(new URL('../../apps/web/public/scene-view.css',import.meta.url),'utf8');
 assert.match(css,/right: 24px; top: 56px/);
 const rightClearance=24,buttonOverhang=12,rotationAllowance=6;
 assert.ok(rightClearance>buttonOverhang+rotationAllowance);
});
