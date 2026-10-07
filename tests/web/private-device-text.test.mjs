import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST??'apps/web/dist')+'/');
const {SessionController}=await import(new URL('features/session/controller.js',dist));

test('private HTTP text connects and submits when secure-context randomUUID is absent',async()=>{
  const original=Object.getOwnPropertyDescriptor(globalThis,'crypto');
  Object.defineProperty(globalThis,'crypto',{configurable:true,value:{getRandomValues:array=>webcrypto.getRandomValues(array)}});
  let clientId,requestId,revision=0;
  const state=()=>({schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:clientId,
    revision:++revision,permit_revision:revision,activity_seq:0,input_epoch:0,output_epoch:0,
    phase:'stopped',request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null});
  const api={create:async id=>{clientId=id;return {session:state(),session_token:'synthetic'}},
    capabilities:async()=>({speech_enabled:false,microphone_enabled:false}),snapshot:()=>new Promise(()=>{}),
    input:async request=>{requestId=request.request_id;return {...state(),activity_seq:request.activity_seq}},
    close:async()=>{}};
  const errors=[];
  const controller=new SessionController(api,{apply(){},stop(){},prepareInput(){}},
    {connected(){},update(){},error:error=>errors.push(error),localStop(){}},
    {apiBase:'/api/v1',pollIntervalMs:999999},
    {createCapture:()=>({stop(){},close:async()=>{}})});
  try{
    await controller.connect();
    await controller.input('synthetic private text');
    const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
    assert.match(clientId,uuid);assert.match(requestId,uuid);assert.notEqual(clientId,requestId);
    assert.deepEqual(errors.filter(Boolean),[]);
  }finally{await controller.close();Object.defineProperty(globalThis,'crypto',original);}
});
