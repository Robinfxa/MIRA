import test from 'node:test';
import assert from 'node:assert/strict';
import '../../apps/web/src/features/presentation/code-native-vendor/character.js';
import '../../apps/web/src/features/presentation/code-native-vendor/expression.js';
const face=globalThis.MiraCharacter,expressions=globalThis.MiraExpression;
const span=values=>Math.max(...values)-Math.min(...values);
test('idle has perceptible bounded independent breath, head, gaze and delayed hair performance',()=>{
 const poses=Array.from({length:241},(_,i)=>face.stateAt('idle',i/20,true));
 assert.ok(span(poses.map(p=>p.head))>=2,'head roll must be visible at native resolution');
 assert.ok(span(poses.map(p=>p.gazeX))>=2,'gaze must visibly refocus');
 assert.ok(span(poses.map(p=>p.breath))>=1.5,'breathing must reach the body channel');
 assert.ok(poses.some(p=>p.eyeOpen<.2),'idle must include complete blinks');
 assert.ok(poses.every(p=>Math.abs(p.head)<=4&&Math.abs(p.strand3)<=2),'bounded articulation');
 assert.notDeepEqual(poses.map(p=>p.strand),poses.map(p=>p.strand3),'hair channels lag');
});
test('listening attention, thinking lookaway and speaking hand-camera gesture have different physical poses',()=>{
 const idle=face.stateAt('idle',1,true),listen=face.stateAt('listen',1,true),think=face.stateAt('think',1,true);
 assert.ok(listen.head<idle.head-1);
 assert.ok(think.gazeX>listen.gazeX+2);
 assert.ok(think.gazeY<0);
 const speak=Array.from({length:121},(_,i)=>face.stateAt('speak',i/20,true));
 assert.ok(span(speak.map(p=>p.gesture))>.06,'a coherent small arm gesture is required');
 assert.ok(speak.every(p=>p.mouth>0));
});
test('phase weights continuously blend pose channels without sustaining a stale speaking mouth',()=>{
 const idle=face.stateAt('idle',1,true),think=face.stateAt('think',1,true);
 const mixed=face.stateAt('think',1,true,{phaseWeights:{idle:.5,think:.5}});
 assert.ok(Math.abs(mixed.head-(idle.head+think.head)/2)<1e-9);
 assert.ok(Math.abs(mixed.gazeX-(idle.gazeX+think.gazeX)/2)<1e-9);
 assert.equal(face.stateAt('idle',1,true,{phaseWeights:{speak:1}}).mouth,0);
});
test('suspension closes live channels and static normal preserves the adopted rest pose',()=>{
 for(const mode of ['idle','listen','think','speak']){
  const p=face.stateAt(mode,7,false);
  for(const key of ['head','headX','headY','breath','gazeX','gazeY','mouth','strand','strand2','strand3','gesture'])assert.equal(p[key],0,key);
  assert.equal(p.eyeOpen,1);
 }
});
test('guarded happy shy have distinct readable eye and brow poses in addition to lips and blush',()=>{
 const p=expressions.POSES;
 assert.ok(p.guarded.eyeLSqueeze>=.35);
 assert.ok(p.happy.browLY<=-8);
 assert.ok(p.shy.gazeY>=7&&p.shy.gazeX<=-7);
 assert.ok(p.guarded.browLTilt>=.22);
 assert.deepEqual(expressions.parameters({emotion:'normal'}),p.normal);
});

test('conversational gestures preserve rigid grip and fixed pelvis in every outfit',async()=>{
 await import('../../apps/web/src/features/presentation/code-native-vendor/camera-motion.js');
 await import('../../apps/web/src/features/presentation/code-native-vendor/body.js');
 const body=globalThis.MiraBody;
 const find=(nodes,id)=>{for(const n of nodes){if(n.id===id)return n;const found=find(n.children??[],id);if(found)return found;}};
 for(const outfit of body.OUTFITS){
  const rest=body.bodyLayers({...face.stateAt('idle',0,false),outfit,rigidGrip:true});
  for(const t of [0,.8,1.6,2.3,3.4,4.8])for(const cameraLift of [0,.5,1]){
   const moving=body.bodyLayers({...face.stateAt('speak',t,true),outfit,rigidGrip:true,cameraLift});
   const nodes=[...moving.back,...moving.underNeck,...moving.front];
   assert.equal(find(nodes,'camera-rig').transform,find(nodes,'hands-front-of-camera').transform);
   assert.deepEqual(find(nodes,'waist-and-trousers'),find(rest.back,'waist-and-trousers'));
   assert.doesNotMatch(JSON.stringify(moving),/NaN|Infinity/);
  }
 }
});

test('breathing connects chest, shoulder joints and delayed arms while leaving the pelvis fixed',async()=>{
 await import('../../apps/web/src/features/presentation/code-native-vendor/camera-motion.js');
 await import('../../apps/web/src/features/presentation/code-native-vendor/body.js');
 const a=face.stateAt('idle',1,true),b=face.stateAt('idle',3.6,true);
 assert.notEqual(a.armBreath,a.breath,'arms need secondary follow-through');
 assert.ok(a.breathGrip>0&&a.breathGrip<.02);
 const ra=globalThis.MiraCameraMotion.rig(0,{breath:a.breath,armBreath:a.armBreath});
 const rb=globalThis.MiraCameraMotion.rig(0,{breath:b.breath,armBreath:b.armBreath});
 assert.ok(Math.abs(ra.left.shoulder[1]-rb.left.shoulder[1])>1,'shoulders must follow the breathing thorax');
 assert.notDeepEqual(ra.left.elbow,rb.left.elbow);
});
test('emotional mouth participates through distinct lip tension and brief parting, and still closes on Stop',()=>{
 const p=expressions.POSES;
 assert.ok(p.happy.mouthCorners<=-10&&p.happy.mouthWidth>=.12);
 assert.ok(p.guarded.mouthCompress>=.55);
 const happy=Array.from({length:121},(_,i)=>face.stateAt('idle',i/15,true,{emotion:'happy'}).mouth);
 assert.ok(Math.max(...happy)>.35&&Math.min(...happy)===0,'emotion must include brief parting and relaxed closure');
 for(const emotion of expressions.EMOTIONS)assert.equal(face.stateAt('idle',1,false,{emotion}).mouth,0);
});

test('live crown stays inside the production canvas while stopped head registration remains exact',()=>{
 for(const mode of ['idle','listen','think','speak'])for(const emotion of expressions.EMOTIONS)for(let i=0;i<80;i++){
  const p=face.stateAt(mode,i/10,true,{emotion});assert.ok(p.headY>=0&&p.headY<6.5);
  const angle=p.head*Math.PI/180;
  for(let j=0;j<=50;j++){
   const t=j/50,x=(1-t)**2*77+2*(1-t)*t*87+t*t*98+3,y=(1-t)**2+2*(1-t)*t*-6+t*t*3;
   const drawnY=168.55+Math.sin(angle)*(x-135.04)+Math.cos(angle)*(y-168.55)+p.headY;
   assert.ok(drawnY>=.54,'crown crest must not clip at the top');
  }
 }
 assert.equal(face.stateAt('idle',0,false).headY,0);
});

test('theatrical happy opens a broad smile, guarded presses lips, and shy averts her gaze',()=>{
 const p=expressions.POSES;
 assert.ok(p.happy.mouthWidth>=.20&&p.happy.mouthCorners<=-16);
 assert.ok(p.happy.browLY<=-12&&p.happy.eyeLSqueeze<.1);
 assert.ok(p.guarded.mouthCompress>=.7&&p.guarded.browLTilt>=.35);
 assert.ok(p.shy.gazeX<=-15&&p.shy.mouthWidth<=-.25);
 const happy=Array.from({length:241},(_,i)=>face.stateAt('idle',i/30,true,{emotion:'happy'}));
 assert.ok(Math.max(...happy.map(p=>p.mouth))>=4);
 assert.ok(happy.some(p=>p.smileTeeth>0));
 assert.ok(happy.some(p=>p.mouth===0));
 const stopped=face.stateAt('idle',1,false,{emotion:'happy'});
 assert.equal(stopped.mouth,0);assert.equal(stopped.smileTeeth,0);
});
