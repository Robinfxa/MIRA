import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=process.env.MIRA_TEST_WEB_DIST?pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST)+'/').href:new URL('../../apps/web/dist/',import.meta.url).href;
const {MiraApiClient,MiraHttpError}=await import(new URL('features/session/api-client.js',dist));
const sessionId='11111111-1111-4111-8111-111111111111',clientId='22222222-2222-4222-8222-222222222222',reviewId='b'.repeat(32);
const pcm=new Uint8Array([1,0,2,0]),digest=createHash('sha256').update(pcm).digest('hex');
const json=(value,init={})=>new Response(JSON.stringify(value),{...init,headers:{'content-type':'application/json',...init.headers}});
const session=client=>({schema_version:'0.1.0-foundation',session_id:sessionId,client_instance_id:client,revision:0,activity_seq:0,input_epoch:0,output_epoch:0,
  permit_revision:0,phase:'idle',request_id:null,sealed:true,active_grants:[],presented_effects:[],audio_progress:[],last_error:null});
const status={scope:'application',recording_active:true,has_pending_audio:true,staged_bytes:4,max_audio_bytes:512*1024,expires_in_seconds:10,
  pending_stream_id:clientId,pending_kind:'audio_input',input_completion_ready:true,notice:'safe',scope_notice:'all app sessions'};
const action=(patch={})=>({scope:'application',scope_notice:'all app sessions',ok:true,code:'queued_private_local',message:'safe',recording_active:true,accepted_for_queue:true,...patch});
function server(){
  const requests=[];
  const fetch=async(url,options={})=>{
    requests.push({url:String(url),options});
    const path=new URL(url).pathname;
    if(path==='/api/v1/sessions'&&options.method==='POST')return json({session:session(JSON.parse(options.body).client_instance_id),session_token:'session-capability'});
    if(path.endsWith('/reviewed-audio')&&options.method==='GET')return json(status);
    if(path.endsWith('/reviewed-audio/recording'))return json(action({code:'recording_state_changed',accepted_for_queue:false,recording_active:JSON.parse(options.body).enabled}));
    if(path.endsWith('/streams/'+clientId+'/review'))return json({scope:'application',scope_notice:'all app sessions',review_id:digest.slice(0,32),digest,
      kind:'audio_input',sample_rate_hz:16000,byte_count:4,expires_in_seconds:10,
      preview_path:`/api/v1/sessions/${sessionId}/reviewed-audio/reviews/${digest.slice(0,32)}/preview`,notice:'safe'});
    if(path.endsWith(`/reviews/${digest.slice(0,32)}/preview`))return new Response(pcm,{headers:{'content-type':'application/octet-stream',
      'cache-control':'no-store','x-mira-audio-format':'pcm16le-mono','x-mira-sample-rate-hz':'16000',
      'x-mira-recording-kind':'audio_input','x-mira-audio-digest':digest}});
    if(path.endsWith(`/reviews/${digest.slice(0,32)}/confirm`))return json(action({recording_active:false}));
    if(path.endsWith('/sessions/'+sessionId)&&options.method==='DELETE')return new Response(null,{status:204});
    return new Response('not found',{status:404});
  };
  return {requests,fetch};
}

test('reviewed-audio API uses the in-memory session capability, strict metadata and same-origin preview path',async()=>{
  const fake=server(),client=new MiraApiClient({apiBase:'https://local.test/api/v1',pollIntervalMs:200},{fetch:fake.fetch});
  await client.create(clientId);
  const current=await client.reviewedAudioStatus();assert.equal(current.pending_stream_id,clientId);
  const on=await client.setReviewedAudioRecording(true,true);assert.equal(on.recording_active,true);
  const ticket=await client.requestReviewedAudioReview(clientId);assert.equal(ticket.digest,digest);
  const preview=await client.reviewedAudioPreview(ticket);assert.deepEqual([...preview.pcm16le],[1,0,2,0]);
  assert.equal(preview.digest,digest);assert.equal(preview.sampleRateHz,16000);
  const saved=await client.confirmReviewedAudio(ticket,{reviewed_digest:digest,review:'approved',persist_consent:true});
  assert.equal(saved.code,'queued_private_local');
  const guarded=fake.requests.filter(r=>r.url.includes('/reviewed-audio'));
  assert.ok(guarded.length>=5);
  for(const request of guarded){assert.equal(request.options.headers?.['X-Mira-Session-Token'],'session-capability');assert.equal(request.options.cache,'no-store');assert.equal(request.options.redirect,'error');}
  const confirm=guarded.find(r=>r.url.endsWith(`/reviews/${digest.slice(0,32)}/confirm`));
  assert.deepEqual(JSON.parse(confirm.options.body),{reviewed_digest:digest,review:'approved',persist_consent:true});
  assert.ok(!confirm.options.body.includes('pcm16le')&&!confirm.options.body.includes('transcript'));
  const previewRequest=guarded.find(r=>r.url.endsWith(`/reviews/${digest.slice(0,32)}/preview`));
  assert.equal(previewRequest.options.method,'GET');assert.equal(previewRequest.options.body,undefined);
  await client.close();
});

test('preview rejects path substitution, content mismatch, wrong owner metadata and oversized binary before review approval',async()=>{
  const fake=server(),client=new MiraApiClient({apiBase:'https://local.test/api/v1',pollIntervalMs:200},{fetch:fake.fetch});await client.create(clientId);
  const ticket=await client.requestReviewedAudioReview(clientId);
  await assert.rejects(client.reviewedAudioPreview({...ticket,preview_path:'https://attacker.test/raw'}));
  const expected=`/api/v1/sessions/${sessionId}/reviewed-audio/reviews/${digest.slice(0,32)}/preview`;
  const hostile={...ticket,preview_path:expected};
  const bad=new MiraApiClient({apiBase:'https://local.test/api/v1',pollIntervalMs:200},{fetch:async(url,options)=>{
    if(String(url).endsWith('/sessions'))return json({session:session(clientId),session_token:'session-capability'});
    return new Response(pcm,{headers:{'content-type':'application/octet-stream','cache-control':'no-store','x-mira-audio-format':'pcm16le-mono',
      'x-mira-sample-rate-hz':'24000','x-mira-recording-kind':'audio_input','x-mira-audio-digest':digest}});
  }});
  await bad.create(clientId);await assert.rejects(bad.reviewedAudioPreview(hostile));await bad.close();await client.close();
});

test('only an exact HTTP 409 history_pending body code is retained as safe typed input-rejection metadata',async()=>{
  const createFetch=(statusCode,code,message)=>async(url,options)=>{
    const path=new URL(url).pathname;
    if(path.endsWith('/sessions')&&options.method==='POST')return json({session:session(clientId),session_token:'session-capability'});
    if(path.endsWith('/inputs'))return json({code,message,request_id:'12345678-1234-4234-8234-123456789abc'}, {status:statusCode});
    return new Response(null,{status:204});
  };
  const exact=new MiraApiClient({apiBase:'https://local.test/api/v1',pollIntervalMs:200},{fetch:createFetch(409,'history_pending','SYNTHETIC_PRIVATE_BODY')});
  await exact.create(clientId);
  await assert.rejects(exact.input({request_id:clientId,activity_seq:1,presentation_cutoff:0,text:'synthetic'},new AbortController().signal),error=>{
    assert.ok(error instanceof MiraHttpError);assert.equal(error.status,409);assert.equal(error.code,'history_pending');
    assert.ok(!error.message.includes('SYNTHETIC_PRIVATE_BODY'));return true;
  });await exact.close();
  const generic=new MiraApiClient({apiBase:'https://local.test/api/v1',pollIntervalMs:200},{fetch:createFetch(409,'some_other_conflict','SYNTHETIC_PRIVATE_BODY')});
  await generic.create(clientId);
  await assert.rejects(generic.input({request_id:clientId,activity_seq:1,presentation_cutoff:0,text:'synthetic'},new AbortController().signal),error=>{
    assert.ok(error instanceof MiraHttpError);assert.equal(error.status,409);assert.equal(error.code,null);assert.ok(!error.message.includes('SYNTHETIC_PRIVATE_BODY'));return true;
  });await generic.close();
  const serverFailure=new MiraApiClient({apiBase:'https://local.test/api/v1',pollIntervalMs:200},{fetch:createFetch(500,'history_pending','SYNTHETIC_PRIVATE_BODY')});
  await serverFailure.create(clientId);
  await assert.rejects(serverFailure.input({request_id:clientId,activity_seq:1,presentation_cutoff:0,text:'synthetic'},new AbortController().signal),error=>{
    assert.ok(error instanceof MiraHttpError);assert.equal(error.status,500);assert.equal(error.code,null);return true;
  });await serverFailure.close();
});
