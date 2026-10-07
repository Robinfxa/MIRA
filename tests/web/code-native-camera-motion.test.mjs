import test from 'node:test';
import assert from 'node:assert/strict';
import '../../apps/web/src/features/presentation/code-native-vendor/camera-motion.js';
import '../../apps/web/src/features/presentation/code-native-vendor/body.js';
const body=globalThis.MiraBody;
const find=(nodes,id)=>{for(const n of nodes){if(n.id===id)return n;const v=find(n.children??[],id);if(v)return v;}};
const render=p=>body.bodyLayers({outfit:'black_jacket',running:false,cameraLift:p});
test('camera lift moves rigid camera and hands while torso stays registered',()=>{
 const a=render(0),b=render(1);
 assert.notDeepEqual(find(a.front,'camera-rig'),find(b.front,'camera-rig'));
 assert.equal(find(b.front,'camera-rig').transform,find(b.front,'hands-front-of-camera').transform);
 assert.deepEqual(find(a.front,'body-core'),find(b.front,'body-core'));
 assert.deepEqual(a.underNeck,b.underNeck);
});
test('lift articulates sleeves and both forearms continuously in all three outfits',()=>{
 for(const outfit of body.OUTFITS){
  const a=body.bodyLayers({outfit,running:false,cameraLift:0});
  const b=body.bodyLayers({outfit,running:false,cameraLift:.5});
  for(const id of ['arm-left-upper','arm-right-upper','forearm-left','forearm-right'])
   assert.notDeepEqual(find([...a.back,...a.front],id),find([...b.back,...b.front],id),id);
  assert.doesNotMatch(JSON.stringify(b),/NaN|Infinity/);
 }
});
