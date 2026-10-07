import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {MiraApiClient}=await import(new URL('features/session/api-client.js',dist));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const session={schema_version:'0.1.0-foundation',session_id:'s',client_instance_id:'c',revision:0,activity_seq:0,input_epoch:0,output_epoch:0,permit_revision:0,phase:'idle',request_id:null,sealed:false,active_grants:[],presented_effects:[],audio_progress:[],last_error:null};
const created=()=>new Response(JSON.stringify({session,session_token:'capability-secret'}),{headers:{'content-type':'application/json'}});
test('API close aborts pending create and deletes a returned late session without reconnecting',async()=>{const pending=deferred(),calls=[];const api=new MiraApiClient({apiBase:'/api/v1',pollIntervalMs:200},{fetch:async(url,options)=>{calls.push({url,options});return options.method==='POST'?pending.promise:new Response(null,{status:204});}});const start=api.create('c');await api.close();assert.equal(calls[0].options.signal.aborted,true);pending.resolve(created());await assert.rejects(start,/closed/);await Promise.resolve();assert.equal(calls[1].options.method,'DELETE');assert.equal(calls[1].options.headers['X-Mira-Session-Token'],'capability-secret');await assert.rejects(api.create('c'),/closed/);});
test('API server cleanup failure is not reported as successful close',async()=>{const api=new MiraApiClient({apiBase:'/api/v1',pollIntervalMs:200},{fetch:async(_url,options)=>options.method==='POST'?created():new Response(null,{status:500})});await api.create('c');await assert.rejects(api.close(),/cleanup/);});

test('default browser fetch keeps its global receiver for create, snapshot and cleanup', async t => {
  const calls=[];
  t.mock.method(globalThis, 'fetch', function(url, options) {
    // Unlike Node fetch and arrow-function fakes, native browser fetch brands its receiver.
    if (this !== globalThis) throw new TypeError("Failed to execute 'fetch' on 'Window': Illegal invocation");
    calls.push({url, options});
    if (options.method === 'POST') return Promise.resolve(created());
    if (options.method === 'GET') return Promise.resolve(new Response(JSON.stringify(session), {
      headers: {'content-type':'application/json'},
    }));
    return Promise.resolve(new Response(null, {status:204}));
  });
  const api=new MiraApiClient({apiBase:'/api/v1',pollIntervalMs:200});
  await api.create('c',new AbortController().signal);
  assert.equal((await api.snapshot()).session_id,'s');
  await api.close();
  assert.deepEqual(calls.map(call=>call.options.method),['POST','GET','DELETE']);
  assert.deepEqual(calls.map(call=>call.url),['/api/v1/sessions','/api/v1/sessions/s','/api/v1/sessions/s']);
  assert.equal(calls[0].options.headers['X-Mira-Session-Token'],undefined);
  assert.equal(calls[1].options.headers['X-Mira-Session-Token'],'capability-secret');
  assert.equal(calls[2].options.headers['X-Mira-Session-Token'],'capability-secret');
});

test('default browser fetch keeps its receiver for bounded reviewed-audio preview', async t => {
  const pcm=new Uint8Array([1,0,2,0]);
  const hash=await crypto.subtle.digest('SHA-256',pcm);
  const digest=Array.from(new Uint8Array(hash),value=>value.toString(16).padStart(2,'0')).join('');
  const reviewId='a'.repeat(32),path=`/api/v1/sessions/s/reviewed-audio/reviews/${reviewId}/preview`;
  t.mock.method(globalThis,'fetch',function(url,options) {
    if(this!==globalThis)throw new TypeError("Failed to execute 'fetch' on 'Window': Illegal invocation");
    if(options.method==='POST')return Promise.resolve(created());
    if(options.method==='DELETE')return Promise.resolve(new Response(null,{status:204}));
    assert.equal(url,path);
    return Promise.resolve(new Response(pcm,{headers:{'content-type':'application/octet-stream',
      'cache-control':'no-store','x-mira-audio-format':'pcm16le-mono','x-mira-sample-rate-hz':'16000',
      'x-mira-recording-kind':'audio_input','x-mira-audio-digest':digest}}));
  });
  const api=new MiraApiClient({apiBase:'/api/v1',pollIntervalMs:200});
  await api.create('c');
  const preview=await api.reviewedAudioPreview({review_id:reviewId,digest,kind:'audio_input',
    sample_rate_hz:16000,byte_count:4,preview_path:path});
  assert.deepEqual([...preview.pcm16le],[1,0,2,0]);
  await api.close();
});

test('explicitly injected fetch is preserved and does not invoke the browser default', async t => {
  t.mock.method(globalThis,'fetch',()=>{throw new Error('Unexpected default fetch');});
  const calls=[];
  const injected=async(url,options)=>{
    calls.push({url,options});
    return options.method==='POST'?created():new Response(null,{status:204});
  };
  const api=new MiraApiClient({apiBase:'/api/v1',pollIntervalMs:200},{fetch:injected});
  await api.create('c');
  await api.close();
  assert.deepEqual(calls.map(call=>call.options.method),['POST','DELETE']);
});
