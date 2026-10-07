import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const dist=process.env.MIRA_TEST_WEB_DIST
  ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href
  : new URL('../../apps/web/dist/',import.meta.url).href;
const {PresentationGate}=await import(new URL('features/presentation/permit-gate.js',dist));
const {SceneEffectExecutor}=await import(new URL('features/presentation/scene-executor.js',dist));

function effect(id,kind,value,cue,speech=null){
  return {id,kind,value,digest:'a'.repeat(64),output_epoch:1,activity_seq:1,
    cue_id:cue,cue_speech_id:speech};
}
function snapshot(grants){return {schema_version:'0.1.0-foundation',session_id:'s',
  client_instance_id:'c',revision:1,activity_seq:1,input_epoch:1,output_epoch:1,
  permit_revision:1,phase:'ready',request_id:'r',sealed:true,active_grants:grants,
  presented_effects:[],audio_progress:[],last_error:null};}

test('new text and pose pass the existing renderer without any audio fact',()=>{
  const subtitle=effect('text','subtitle','我写下一句新的话。','cue');
  const pose=effect('pose','pose','face_warm','cue');
  const gate=new PresentationGate('s','c');
  gate.beginInput('r');
  gate.install(snapshot([subtitle,pose]));
  assert.equal(gate.allows(subtitle),true);
  assert.equal(gate.allows(pose),true);
  assert.equal(gate.consume(subtitle).effect_id,'text');
  assert.equal(gate.consume(pose).effect_id,'pose');

  const nodes=new Map(['subtitle','photo','pose','scene-label','phase-label',
    'character-description'].map(name=>[name,{textContent:'',hidden:true}]));
  const root={dataset:{},querySelector:selector=>nodes.get(selector.replace(/^\[data-|\]$/g,''))};
  const renderer=new SceneEffectExecutor(root);
  renderer.apply(subtitle);
  renderer.apply(pose);
  assert.equal(nodes.get('subtitle').textContent,'我写下一句新的话。');
  assert.match(nodes.get('character-description').textContent,/温暖微笑/);
});

test('speech-bound caption remains gated when voice is absent',()=>{
  const speech=effect('speech','speech','will be spoken','cue','speech');
  const caption=effect('caption','subtitle','caption for speech','cue','speech');
  const gate=new PresentationGate('s','c');
  gate.beginInput('r');
  gate.install(snapshot([speech,caption]));
  assert.equal(gate.allows(caption),false);
  assert.equal(gate.consume(caption),null);
});
