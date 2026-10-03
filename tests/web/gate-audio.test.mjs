import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist = process.env.MIRA_TEST_WEB_DIST ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href : new URL('../../apps/web/dist/',import.meta.url).href;
const {PresentationGate} = await import(new URL('features/presentation/permit-gate.js',dist));
const e={id:'speech',kind:'speech',value:'hello',digest:'a'.repeat(64),output_epoch:1,activity_seq:1};
const s={schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:'c',revision:2,activity_seq:1,input_epoch:1,output_epoch:1,permit_revision:2,phase:'ready',request_id:'r',sealed:true,active_grants:[e],presented_effects:[],audio_progress:[],last_error:null};
function gate(){const g=new PresentationGate('s','c');g.beginInput('r');g.install(s);return g;}
function fact(stage,frames=240){return {origin:e,stage,submittedFrames:480,renderedFrames:frames,sampleRate:24000,inFlightFramesUncertain:480-frames};}
test('speech claim is one-shot but continuing authorization is independent',()=>{const g=gate();assert.equal(g.claimSpeech(e),true);assert.equal(g.claimSpeech(e),false);assert.equal(g.isAuthorized(e),true);assert.equal(g.consume(e),null);});
test('speech cannot create a visual receipt',()=>{const g=gate();assert.equal(g.consume(e),null);});
test('audio facts share cutoff sequence and reject stale and duplicate history',()=>{const g=gate();g.claimSpeech(e);assert.equal(g.audioProgress(fact('submitted')),null);assert.equal(g.audioProgress(fact('rendered')).presentation_seq,1);assert.equal(g.audioProgress(fact('rendered')),null);g.block();const terminal=g.audioProgress({...fact('stopped'),reason:'stop'});assert.equal(terminal.status,'interrupted');assert.equal(terminal.presentation_seq,2);assert.equal(g.stop().presentation_cutoff,2);assert.equal(g.audioProgress(fact('completed')),null);});
test('revocation immediately closes continuing authority without replay',()=>{const g=gate();g.claimSpeech(e);g.install({...s,revision:3,permit_revision:3,active_grants:[]});assert.equal(g.isAuthorized(e),false);assert.equal(g.audioProgress(fact('rendered')),null);});
test('caller and installed snapshot mutation cannot rewrite authority',()=>{const g=gate();assert.equal(g.isAuthorized({...e,digest:'b'.repeat(64)}),false);s.active_grants[0]={...e,value:'changed'};assert.equal(g.isAuthorized(e),true);s.active_grants[0]=e;});
