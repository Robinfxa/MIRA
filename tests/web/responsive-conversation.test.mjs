import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
const root = new URL('../../', import.meta.url);
const html = await readFile(new URL('apps/web/index.html', root), 'utf8');
const css = await readFile(new URL('apps/web/public/app.css', root), 'utf8');
const dist = process.env.MIRA_TEST_WEB_DIST ? resolve(process.env.MIRA_TEST_WEB_DIST) : resolve('apps/web/dist');
const {SessionController} = await import(resolve(dist, 'features/session/controller.js'));
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {let resolve;const promise = new Promise(r=>resolve=r);return {promise,resolve};};
function harness() {
  let client, revision=0, activity=0, inputEpoch=0;
  const accepted=[], shown=[], receipts=[];
  const snapshot=(o={})=>({schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:client,revision:++revision,activity_seq:activity,input_epoch:inputEpoch,output_epoch:activity,permit_revision:revision,phase:'stopped',request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null,...o});
  const api={create:async c=>{client=c;return {session:snapshot(),session_token:'synthetic'};},capabilities:async()=>({generation_mode:'mock',qualification:'unavailable',microphone_enabled:false,speech_enabled:false}),snapshot:()=>new Promise(()=>{}),input:async request=>{activity=request.activity_seq;inputEpoch++;return snapshot({request_id:request.request_id,phase:'ready',active_grants:[{id:`subtitle-${activity}`,kind:'subtitle',value:'真正显示的回复',digest:'a'.repeat(64),output_epoch:activity,activity_seq:activity,cue_id:null,cue_speech_id:null}]});},receipt:async r=>{receipts.push(r);return snapshot();},stop:async r=>{activity=r.activity_seq;return snapshot();},close:async()=>{}};
  const effects={apply:e=>shown.push(['applied',e.value]),prepareInput(){},stop(){},setPhase(){}};
  const view={connected(){},update(){},error(){},localStop(){},inputAccepted:text=>accepted.push(text),visualPresented:e=>shown.push(['observed',e.value])};
  const controller=new SessionController(api,effects,view,{apiBase:'/api/v1',pollIntervalMs:200},{createPlayback:()=>({unlock:async()=>false,stop(){},reconcileAuthorization(){},close(){}}),createCapture:()=>({start:async()=>false,stop(){},close(){}})});
  return {controller,api,effects,view,snapshot,accepted,shown,receipts};
}
test('responsive conversation has native editable input, page-only log and secondary settings',()=>{
  assert.match(html,/class="experience-grid"/);
  assert.match(html,/<ol[^>]+data-conversation-log[^>]+role="log"/);
  assert.match(html,/<textarea[^>]+name="message"[^>]+rows="2"/);
  assert.match(html,/<details class="settings-panel" id="settings">/);
  assert.ok(html.indexOf('data-conversation-log') < html.indexOf('data-review-audio-consent'));
  assert.match(html,/data-turn-status[^>]+role="status"/);
  assert.match(css,/grid-template-columns:\s*minmax\(0,\s*1\.55fr\)\s+minmax\(340px,\s*1fr\)/);
  assert.match(css,/\.composer textarea[\s\S]*font-size:\s*16px/);
});
test('accepted user text and consumed subtitle are observed once in actual controller order',async()=>{
  const h=harness();await h.controller.connect();
  assert.equal((await h.controller.input('我的输入')).status,'submitted');await tick();
  assert.deepEqual(h.accepted,['我的输入']);
  assert.deepEqual(h.shown,[['applied','真正显示的回复'],['observed','真正显示的回复']]);
  assert.equal(h.receipts.length,1);
  await h.controller.stop();assert.equal(h.accepted.length,1);assert.equal(h.shown.length,2);
  await h.controller.close();
});
test('Stop fences a late accepted input from entering the page log',async()=>{
  const h=harness(),late=deferred();await h.controller.connect();
  const original=h.api.input;h.api.input=async r=>{const result=await original(r);await late.promise;return result;};
  const input=h.controller.input('迟到输入');await tick();await h.controller.stop();late.resolve();
  assert.equal((await input).status,'superseded');assert.deepEqual(h.accepted,[]);assert.deepEqual(h.shown,[]);
  await h.controller.close();
});
test('failed rendering never emits a presented chat message',async()=>{
  const h=harness();h.effects.apply=()=>{throw new Error('synthetic renderer failure');};
  await h.controller.connect();await h.controller.input('用户输入');await tick();
  assert.deepEqual(h.accepted,['用户输入']);assert.deepEqual(h.shown,[]);assert.deepEqual(h.receipts,[]);
  await h.controller.close();
});
