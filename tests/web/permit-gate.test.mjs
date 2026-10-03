import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
// Per-run build when orchestrated; npm test still supports its ordinary local build.
const dist = process.env.MIRA_TEST_WEB_DIST
  ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href
  : new URL('../../apps/web/dist/', import.meta.url).href;
const { PresentationGate } = await import(new URL('features/presentation/permit-gate.js', dist));
const { parseSession } = await import(new URL('shared/protocol.js', dist));

const effect={id:'e1',kind:'subtitle',value:'hello',digest:'a'.repeat(64),output_epoch:1,activity_seq:1};
function snapshot(patch={}) { return {schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:'c',
 revision:2,activity_seq:1,input_epoch:1,output_epoch:1,permit_revision:2,phase:'ready',
 request_id:'r1',sealed:false,active_grants:[effect],presented_effects:[],last_error:null,...patch}; }
function started(){ const g=new PresentationGate('s','c');g.beginInput('r1');g.install(snapshot());return g; }

test('accepts exact current request and emits one receipt',()=>{const g=started();assert.equal(g.consume(effect).presentation_seq,1);assert.equal(g.consume(effect),null);});
test('local stop immediately blocks stale grant',()=>{const g=started();g.stop();assert.equal(g.consume(effect),null);});
test('larger permit number cannot clear explicit local stop',()=>{const g=started();g.stop();g.install(snapshot({revision:20,permit_revision:20,activity_seq:2}));assert.equal(g.consume(effect),null);});
test('old activity never admits even newer server control',()=>{const g=started();g.beginInput('r2');g.install(snapshot({revision:30,permit_revision:30}));assert.equal(g.consume(effect),null);});
test('same input can stop old and establish a new request',()=>{const g=started();g.stop();g.beginInput('r3');const next={...effect,id:'e3',activity_seq:3,output_epoch:3};g.install(snapshot({revision:8,permit_revision:8,activity_seq:3,output_epoch:3,request_id:'r3',active_grants:[next]}));assert.ok(g.consume(next));});
test('second stop dominates an earlier restart',()=>{const g=started();g.stop();g.beginInput('r3');g.stop();const next={...effect,id:'e3',activity_seq:3,output_epoch:3};g.install(snapshot({revision:30,permit_revision:30,activity_seq:3,output_epoch:3,request_id:'r3',active_grants:[next]}));assert.equal(g.consume(next),null);});
test('complete grant set extension does not replay old effect',()=>{const g=started();g.consume(effect);const second={...effect,id:'e2'};g.install(snapshot({revision:3,permit_revision:3,active_grants:[effect,second]}));assert.equal(g.consume(effect),null);assert.ok(g.consume(second));});
test('foreign session does not advance watermark',()=>{const g=started();assert.equal(g.install(snapshot({session_id:'foreign',revision:99,permit_revision:99})),false);assert.ok(g.consume(effect));});
test('foreign client does not install',()=>{const g=started();assert.equal(g.install(snapshot({client_instance_id:'foreign'})),false);});
test('lower revision ignored',()=>{const g=started();assert.equal(g.install(snapshot({revision:1})),false);});
test('revoked grant not available',()=>{const g=started();g.install(snapshot({revision:3,permit_revision:3,active_grants:[]}));assert.equal(g.consume(effect),null);});
test('digest mismatch rejected',()=>{const g=started();assert.equal(g.consume({...effect,digest:'b'.repeat(64)}),null);});
test('stop reports consumption cutoff',()=>{const g=started();g.consume(effect);assert.equal(g.stop().presentation_cutoff,1);});
test('wire parser rejects wrong protocol',()=>assert.throws(()=>parseSession(snapshot({schema_version:'0.2'}))));
test('wire parser rejects invalid enum',()=>assert.throws(()=>parseSession(snapshot({phase:'speaking-maybe'}))));
test('wire parser rejects invalid effect digest',()=>assert.throws(()=>parseSession(snapshot({active_grants:[{...effect,digest:'bad'}]}))));
test('wire parser accepts exported shape',()=>assert.equal(parseSession(snapshot()).session_id,'s'));

test('same control version with conflicting grants fails closed',()=>{const g=started();assert.throws(()=>g.install(snapshot({revision:3,active_grants:[]})));assert.equal(g.consume(effect),null);});
test('newer snapshot cannot change an existing effect identity',()=>{const g=started();assert.throws(()=>g.install(snapshot({revision:3,permit_revision:3,active_grants:[{...effect,value:'changed'}]})));assert.equal(g.consume(effect),null);});
test('caller cannot swap effect value while keeping digest',()=>{const g=started();assert.equal(g.consume({...effect,value:'changed'}),null);});
