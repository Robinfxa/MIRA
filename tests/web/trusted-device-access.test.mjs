import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {webcrypto} from 'node:crypto';
import {readFile} from 'node:fs/promises';
const dist=resolve(process.env.MIRA_TEST_WEB_DIST??'apps/web/dist');
const {SessionController}=await import(resolve(dist,'features/session/controller.js'));

class Element {
  hidden=true; disabled=false; textContent=''; listeners=new Map();
  addEventListener(name, fn){this.listeners.set(name,fn);}
  fire(name){this.listeners.get(name)?.();}
}
function dom(){
  const panel=new Element(), status=new Element(), close=new Element(), window=new Element();
  const nodes=new Map([['[data-trusted-device-panel]',panel],['[data-trusted-device-status]',status],['[data-trusted-device-close]',close]]);
  return {panel,status,close,window,document:{querySelector:q=>nodes.get(q),defaultView:window}};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));

// Keep RED an assertion of missing behavior rather than a module collection error.
async function mount(){
  const main=await readFile(resolve(dist,'app/main-source.js'),'utf8');
  assert.match(main,/mountTrustedDeviceAccess/, 'actual main must gate trusted mode before controller startup');
  return (await import(resolve(dist,'features/session/trusted-device-access.js'))).mountTrustedDeviceAccess;
}

test('compiled trusted gate starts real controller only after bootstrap, preserves refresh and revokes only on close',async()=>{
  const mountTrustedDeviceAccess=await mount();
  const original=Object.getOwnPropertyDescriptor(globalThis,'crypto');
  Object.defineProperty(globalThis,'crypto',{configurable:true,value:webcrypto});
  let release;const pending=new Promise(resolve=>release=resolve);
  const calls=[];let controller;
  const d=dom();
  const fetcher=async(path,init)=>{calls.push(path);assert.equal(init.credentials,'include');
    if(path.endsWith('/bootstrap')){await pending;return {status:204};}
    if(path.endsWith('/revoke'))return {status:204};throw Error(path);};
  const api={create:async id=>{calls.push('create');return {session:{schema_version:'0.1.0-foundation',session_id:'one',
      client_instance_id:id,revision:1,permit_revision:1,activity_seq:0,input_epoch:0,output_epoch:0,phase:'stopped',
      request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null},session_token:'synthetic'};},
    capabilities:async()=>({speech_enabled:false,microphone_enabled:false}),snapshot:()=>new Promise(()=>{}),close:async()=>{calls.push('close');}};
  const gate=mountTrustedDeviceAccess(d.document,{fetcher,onReady:()=>{
    controller=new SessionController(api,{apply(){},stop(){},prepareInput(){}},
      {connected(){},update(){},error(){},localStop(){}},{apiBase:'/api/v1',pollIntervalMs:999999},
      {createCapture:()=>({stop(){},close:async()=>{}})});
    void controller.connect();return {stopAndClose:()=>controller.close()};}});
  try{
    await tick();assert.deepEqual(calls,['/api/v1/devices/bootstrap']);
    release();await gate.ready;await tick();assert.ok(calls.includes('create'));
    assert.match(d.status.textContent,/免配对/);
    d.window.fire('pagehide');await tick();assert.ok(calls.includes('close'));
    assert.ok(!calls.includes('/api/v1/devices/revoke'));
  }finally{await controller?.close();Object.defineProperty(globalThis,'crypto',original);}
  const next=dom();const events=[];
  const fresh=mountTrustedDeviceAccess(next.document,{fetcher:async path=>{events.push(path);return {status:204};},
    onReady:()=>({stopAndClose:async()=>events.push('local-stop')})});
  await fresh.ready;await fresh.cancelAndRevoke();await fresh.cancelAndRevoke();
  assert.deepEqual(events,['/api/v1/devices/bootstrap','local-stop','/api/v1/devices/revoke']);
});

test('cancelled or failed bootstrap never starts controller or retries silently',async()=>{
  const mountTrustedDeviceAccess=await mount();
  let release;const pending=new Promise(resolve=>release=resolve);const calls=[];const d=dom();
  const gate=mountTrustedDeviceAccess(d.document,{fetcher:async path=>{calls.push(path);if(path.endsWith('/bootstrap'))await pending;return {status:204};},
    onReady:()=>{throw Error('late controller activated');}});
  const closing=gate.cancelAndRevoke();release();await closing;await gate.ready;
  assert.deepEqual(calls,['/api/v1/devices/bootstrap','/api/v1/devices/revoke']);
  const failed=dom();let starts=0;
  const failGate=mountTrustedDeviceAccess(failed.document,{fetcher:async()=>({status:429}),onReady:()=>{starts++;}});
  await failGate.ready;assert.equal(starts,0);assert.match(failed.status.textContent,/16/);
});
