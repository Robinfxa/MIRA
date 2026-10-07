import test from 'node:test';
import assert from 'node:assert/strict';
import '../../apps/web/src/features/presentation/code-native-vendor/character.js';
import '../../apps/web/src/features/presentation/code-native-vendor/camera-motion.js';
import '../../apps/web/src/features/presentation/code-native-vendor/body.js';
import '../../apps/web/src/features/presentation/code-native-vendor/hair.js';
import '../../apps/web/src/features/presentation/code-native-vendor/expression.js';
const F=globalThis.MiraCharacter,B=globalThis.MiraBody,H=globalThis.MiraHairRefinement,E=globalThis.MiraExpression;
const find=(nodes,id)=>{for(const n of nodes){if(n.id===id)return n;const hit=find(n.children??[],id);if(hit)return hit;}};
function compose(p,outfit='black_jacket',emotion='normal',lift=0){
 const face=F.scene(p),b=B.bodyLayers({...p,outfit,cameraLift:lift,rigidGrip:true},F.palette);
 const get=id=>face.layers.find(n=>n.id===id);
 const scene={width:288,height:408,palette:F.palette,layers:[{id:'composition-layout',type:'group',transform:'translate(18 0)',children:[...b.back,get('rear-hair-rig'),...b.underNeck,get('neck-rig'),...b.front,get('head-rig')]}]};
 return E.apply(H.apply(scene,p),p,{emotion,accessory:'camera_clip'});
}
test('yaw and shoulder attention are bounded, blended live channels that close on suspension',()=>{
 const poses=Array.from({length:181},(_,i)=>F.stateAt('idle',i/10,true));
 assert.ok(poses.every(p=>Number.isFinite(p.yaw)&&Math.abs(p.yaw)<=15),'a separate geometric yaw channel is required');
 assert.ok(Math.max(...poses.map(p=>p.yaw))-Math.min(...poses.map(p=>p.yaw))>12,'both directions must be visible');
 for(const mode of ['idle','listen','think','speak']){
  const p=F.stateAt(mode,3,false);
  for(const k of ['yaw','shoulderFollow','shoulderRaise','listeningLean'])assert.equal(p[k],0,k);
 }
 const a=F.stateAt('listen',2,true),b=F.stateAt('think',2,true),m=F.stateAt('think',2,true,{phaseWeights:{listen:.5,think:.5}});
 assert.ok(Math.abs(m.yaw-(a.yaw+b.yaw)/2)<1e-8);
 assert.ok(a.listeningLean>0&&Math.abs(a.shoulderFollow)>0);
});
test('small turns reproject facial geometry and visibility while keeping exact zero rest and rigid grip',()=>{
 const p=F.stateAt('idle',0,false),base=compose(p),serialized=JSON.stringify(base);
 assert.equal(typeof F.articulate,'function','production post-expression articulation must exist');
 assert.equal(JSON.stringify(F.articulate(base,p)),serialized);
 const left=F.articulate(base,{...p,running:true,yaw:-15,shoulderFollow:-.5,shoulderRaise:.4,listeningLean:0});
 const right=F.articulate(base,{...p,running:true,yaw:15,shoulderFollow:.5,shoulderRaise:0,listeningLean:0});
 assert.equal(JSON.stringify(base),serialized,'pure geometry modifier');
 for(const id of ['left-eye-sclera','right-eye-sclera','nose-tip-plane','upper-lip','ear-base','right-face-fringe','neck-continuity-base','collarbone-left'])assert.notEqual(find(left.layers,id).d,find(right.layers,id).d,id);
 assert.notEqual(find(left.layers,'hair-front').clip,find(right.layers,'hair-front').clip,'ear aperture changes with its solid ear surface');
 assert.equal(find(left.layers,'ear-base').opacity,find(base.layers,'ear-base').opacity,'ear exposure must use geometry, not translucent skin');
 for(const id of ['head-rig','rear-hair-rig','neck-rig'])assert.equal(find(left.layers,id).transform,find(right.layers,id).transform,'yaw cannot be a head matrix rotation');
 for(const id of ['camera-rig','hands-front-of-camera','waist-and-trousers'])assert.deepEqual(find(left.layers,id),find(base.layers,id),id);
});
test('all wardrobes, phases, expressions, blink and camera extrema keep finite unique connected geometry',()=>{
 for(const outfit of B.OUTFITS)for(const mode of ['idle','listen','think','speak'])for(const emotion of E.EMOTIONS)for(const yaw of [-15,0,15])for(const lift of [0,.5,1]){
  const p={...F.stateAt(mode,2.175,true,{emotion}),yaw};
  const raw=compose(p,outfit,emotion,lift),scene=F.articulate(raw,p),ids=[];
  const visit=n=>{ids.push(n.id);(n.children??[]).forEach(visit);};scene.layers.forEach(visit);
  assert.equal(new Set(ids).size,ids.length);assert.doesNotMatch(JSON.stringify(scene),/NaN|Infinity/);
  for(const id of ['camera-rig','hands-front-of-camera','waist-and-trousers'])assert.deepEqual(find(scene.layers,id),find(raw.layers,id));
 }
});
