import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist = process.env.MIRA_TEST_WEB_DIST
  ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href
  : new URL('../../apps/web/dist/', import.meta.url).href;
const {MiraApiClient} = await import(new URL('features/session/api-client.js', dist));
for(const character of ['\t','\n','\r'])test(`reject normalized cross-origin apiBase containing ${JSON.stringify(character)}`,async()=>{
 const config={apiBase:'/api/v1',pollIntervalMs:200};const resourceCalls=[];
 const api=new MiraApiClient(config,{fetch:async(url,init)=>{
  if(url.endsWith('/sessions')&&init.method==='POST')return new Response(JSON.stringify({session_token:'synthetic-session-token',session:{schema_version:'0.1.0-foundation',session_id:'synthetic-session',client_instance_id:'synthetic-client',revision:0,permit_revision:0,activity_seq:0,input_epoch:0,output_epoch:0,request_id:null,phase:'idle',sealed:false,active_grants:[],presented_effects:[],audio_progress:[],last_error:null}}),{headers:{'content-type':'application/json'}});
  if(url.includes('/story-images/')){resourceCalls.push({url,resolvedOrigin:new URL(url,'https://same-origin.invalid').origin,tokenHeaderPresent:init.headers['X-Mira-Session-Token']==='synthetic-session-token'});return new Response(new Uint8Array(33),{headers:{'content-type':'image/png','cache-control':'no-store'}});}
  if(init.method==='DELETE')return new Response(null,{status:204});
  throw Error('Unexpected request');
 }});
 try{
  await api.create('synthetic-client');config.apiBase=`/${character}/external.invalid`;
  await api.generatedImage({id:'synthetic-effect',kind:'media',value:`generated_story_photo:v1:99d8be13-36b2-43cd-a7bb-3f2cf19806fe:${'a'.repeat(64)}`,digest:'b'.repeat(64),activity_seq:1,output_epoch:1},new AbortController().signal).catch(()=>{});
  assert.equal(resourceCalls.length,0,JSON.stringify(resourceCalls));
 }finally{await api.close();}
});
