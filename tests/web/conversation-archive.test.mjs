import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
const dist=process.env.MIRA_TEST_WEB_DIST?resolve(process.env.MIRA_TEST_WEB_DIST):resolve('apps/web/dist');
const {mountConversationArchive}=await import(resolve(dist,'features/session/conversation-archive.js'));
class Element {
  listeners=new Map();children=[];value='';textContent='';hidden=false;disabled=false;checked=false;type='';
  constructor(tag='div'){this.tagName=tag.toUpperCase();}
  addEventListener(name,callback){this.listeners.set(name,[...(this.listeners.get(name)??[]),callback]);}
  fire(name){for(const callback of this.listeners.get(name)??[])callback({preventDefault(){}});}
  appendChild(child){this.children.push(child);return child;}
  replaceChildren(...children){this.children=children;}
}
function dom(){const names=['panel','status','recipients','entries','sessions','refresh','next-sessions','view','next','recall-consent','google-consent','google-label','start','revoke','draft','preview','confirmed','commit','cancel','reconcile'];
 const nodes=Object.fromEntries(names.map(n=>[n,new Element()]));return {nodes,document:{querySelector(s){return nodes[s.slice(14,-1)]??null;},createElement(tag){return new Element(tag);}}};}
const tick=()=>new Promise(r=>setImmediate(r));
const status=(changes={})=>({enabled:true,persistence_status:'enabled_no_committed_records',management_enabled:true,recall_session_id:null,current_session_id:null,selection_locked:false,recipients:'OpenAI chosen route + TypeSafe/JEV',speech_enabled:false,recall_authorized:false,google_authorized:false,...changes});
const entry={entry_id:'conversation-input',source_version:1,stage:'accepted_input',active:true,text:'Synthetic <img> original',output_epoch:1,request_id:'old-input',input_source:'text',effect_kind:null,rendered_samples:null,sample_rate_hz:null,audio_status:null,forget_event_id:null};
const page={session_id:'old',revision:3,entries:[entry],next_cursor:null};
function harness({voice=false,operation,delayed,deny,pageValue}={}){const d=dom(),calls=[];let started=0,operationSequence=0;const fetcher=async(path,init)=>{calls.push({path,init});if(deny?.value)return new Response('{}',{status:401});let body;
 if(path.endsWith('/status'))body=status({speech_enabled:voice});
 else if(path.endsWith('/sessions'))body={revision:3,sessions:['old'],next_cursor:null};
 else if(path.includes('/entries?'))body=pageValue?pageValue():page;
 else if(path.endsWith('/selection')){const selected=JSON.parse(init.body);body=status({recall_session_id:selected.session_id,speech_enabled:voice});}
 else if(path.endsWith('/operations'))return operation(path,init);
 else if(path.endsWith('/revoke'))body=status({persistence_status:'revoked_existing_records_retained',selection_locked:true});
 else throw new Error('unexpected request');
 if(delayed)return delayed(path,body);
 return new Response(JSON.stringify(body),{status:200});};
 const app=mountConversationArchive(d.document,{fetcher,start(){started++;return {async stopAndClose(){}};},operationId:()=> '00000000-0000-4000-8000-'+String(++operationSequence).padStart(12,'0')});
 return {...d,app,calls,get started(){return started;}};}

test('paired preflight makes no chat or recall request until explicit start',async()=>{const h=harness();await tick();await tick();assert.equal(h.started,0);assert.deepEqual(h.calls.map(x=>x.path),['/api/v1/conversations/status','/api/v1/conversations/sessions']);h.nodes.start.fire('click');await tick();assert.equal(h.started,1);assert.deepEqual(JSON.parse(h.calls.at(-1).init.body),{session_id:null,authorize_selected_provider_and_jev:false,authorize_google_derived_speech:false});h.app.close();});

test('selected prior session requires separate recipient and Google consent',async()=>{const h=harness({voice:true});await tick();await tick();h.nodes.sessions.value='old';h.nodes.start.fire('click');await tick();assert.equal(h.started,0);h.nodes['recall-consent'].checked=true;h.nodes.start.fire('click');await tick();assert.equal(h.started,0);h.nodes['google-consent'].checked=true;h.nodes.start.fire('click');await tick();assert.equal(h.started,1);assert.equal(JSON.parse(h.calls.at(-1).init.body).session_id,'old');h.app.close();});

test('source text is literal and uncertain writes reuse the same operation identity',async()=>{let writes=0;const bodies=[];const h=harness({operation:async(_path,init)=>{bodies.push(init.body);writes++;if(writes===1)throw new Error('connection lost after commit');return new Response(JSON.stringify({status:'committed',operation_id:JSON.parse(init.body).operation_id}),{status:200});}});await tick();await tick();h.nodes.sessions.value='old';h.nodes.view.fire('click');await tick();const row=h.nodes.entries.children[0];assert.equal(row.children[1].textContent,entry.text);row.children[2].fire('click');h.nodes.draft.value='Synthetic corrected';h.nodes.confirmed.checked=true;h.nodes.confirmed.fire('change');h.nodes.commit.fire('click');await tick();assert.equal(writes,1);assert.equal(h.nodes.reconcile.hidden,false);h.app.stop();h.nodes.reconcile.fire('click');await tick();await tick();assert.equal(writes,2);assert.equal(bodies[0],bodies[1]);assert.equal(h.nodes.reconcile.hidden,true);h.app.close();assert.equal(h.nodes.entries.children.length,0);});

test('close before late private read resolves cannot populate sources or start chat',async()=>{let release;const gate=new Promise(r=>release=r);const h=harness({delayed:async(path,body)=>{await gate;return new Response(JSON.stringify(body),{status:200});}});h.app.close();release();await tick();await tick();assert.equal(h.started,0);assert.equal(h.nodes.entries.children.length,0);assert.equal(h.nodes.sessions.children.length,0);assert.equal(h.nodes.panel.hidden,true);});


test('loss of paired authority clears private source rows and disables local writes',async()=>{const deny={value:false};const h=harness({deny});await tick();await tick();h.nodes.sessions.value='old';h.nodes.view.fire('click');await tick();assert.equal(h.nodes.entries.children.length,1);deny.value=true;h.nodes.refresh.fire('click');await tick();assert.equal(h.nodes.entries.children.length,0);assert.equal(h.nodes.sessions.children.length,0);assert.equal(h.nodes.commit.disabled,true);assert.match(h.nodes.status.textContent,/配对已失效/);h.app.close();});


for (const code of [409,422]) test(`definitive ${code} rejection preserves draft, refreshes revision, and uses a fresh confirmed operation`,async()=>{
  let writes=0,revision=3;const bodies=[];
  const h=harness({pageValue:()=>({...page,revision}),operation:async(_path,init)=>{
    bodies.push(JSON.parse(init.body));writes++;
    if(writes===1){revision=4;return new Response('{}',{status:code});}
    return new Response(JSON.stringify({status:'committed',operation_id:JSON.parse(init.body).operation_id}),{status:200});
  }});
  await tick();await tick();h.nodes.sessions.value='old';h.nodes.view.fire('click');await tick();
  h.nodes.entries.children[0].children[2].fire('click');h.nodes.draft.value='first correction';h.nodes.confirmed.checked=true;h.nodes.commit.fire('click');await tick();await tick();
  assert.equal(h.nodes.reconcile.hidden,true,'definite rejection must not leave an unresolvable uncertain operation');
  assert.equal(h.nodes.draft.value,'first correction');assert.equal(h.nodes.confirmed.checked,false);
  assert.equal(h.nodes.commit.disabled,true,'fresh source still needs renewed explicit confirmation');
  h.nodes.commit.fire('click');await tick();assert.equal(writes,1);
  h.nodes.draft.value='reviewed correction';h.nodes.confirmed.checked=true;h.nodes.confirmed.fire('change');h.nodes.commit.fire('click');await tick();await tick();
  assert.equal(writes,2);assert.notEqual(bodies[0].operation_id,bodies[1].operation_id);assert.equal(bodies[1].expected_revision,4);
  assert.equal(bodies[1].text,'reviewed correction');assert.equal(h.nodes.reconcile.hidden,true);h.app.close();
});

test('rejected correction to a superseded target keeps draft until a fresh target is selected',async()=>{
  let changed=false,writes=0;
  const current={...entry,entry_id:'new-current-input',source_version:2,stage:'corrected_input',text:'other editor wording'};
  const h=harness({pageValue:()=>({...page,revision:changed?4:3,entries:changed?[{...entry,active:false},current]:[entry]}),operation:async(_path,init)=>{
    writes++;if(writes===1){changed=true;return new Response('{}',{status:409});}
    const body=JSON.parse(init.body);assert.equal(body.entry_id,current.entry_id);assert.equal(body.text,'my preserved correction');
    return new Response(JSON.stringify({status:'committed',operation_id:body.operation_id}),{status:200});
  }});
  await tick();await tick();h.nodes.sessions.value='old';h.nodes.view.fire('click');await tick();
  h.nodes.entries.children[0].children[2].fire('click');h.nodes.draft.value='my preserved correction';h.nodes.confirmed.checked=true;h.nodes.commit.fire('click');await tick();await tick();
  assert.equal(h.nodes.draft.value,'my preserved correction');assert.equal(h.nodes.commit.disabled,true);
  h.nodes.entries.children[1].children[2].fire('click');assert.equal(h.nodes.draft.value,'my preserved correction');
  assert.match(h.nodes.preview.textContent,/other editor wording/);h.nodes.confirmed.checked=true;h.nodes.commit.fire('click');await tick();await tick();assert.equal(writes,2);h.app.close();
});

test('HTTP503 stays uncertain and retries the identical operation instead of creating a corrected write',async()=>{
  let writes=0;const bodies=[];
  const h=harness({operation:async(_path,init)=>{bodies.push(init.body);writes++;return writes===1?new Response('{}',{status:503}):new Response(JSON.stringify({status:'committed',operation_id:JSON.parse(init.body).operation_id}),{status:200});}});
  await tick();await tick();h.nodes.sessions.value='old';h.nodes.view.fire('click');await tick();
  h.nodes.entries.children[0].children[2].fire('click');h.nodes.draft.value='uncertain correction';h.nodes.confirmed.checked=true;h.nodes.commit.fire('click');await tick();
  assert.equal(h.nodes.reconcile.hidden,false);assert.equal(h.nodes.commit.disabled,true);assert.doesNotMatch(h.nodes.status.textContent,/已保存|已确认提交/);
  h.nodes.draft.value='new draft must not change in-flight operation';h.nodes.commit.fire('click');await tick();assert.equal(writes,1);
  h.nodes.reconcile.fire('click');await tick();await tick();assert.equal(writes,2);assert.equal(bodies[0],bodies[1]);h.app.close();
});

test('failed refresh after definite rejection preserves draft and blocks writes until a fresh source is reviewed',async()=>{
  let badRead=false,writes=0;
  const h=harness({pageValue:()=>badRead?{}:{...page,revision:writes?4:3},operation:async(_path,init)=>{
    writes++;if(writes===1){badRead=true;return new Response('{}',{status:409});}
    assert.equal(JSON.parse(init.body).expected_revision,4);
    return new Response(JSON.stringify({status:'committed',operation_id:JSON.parse(init.body).operation_id}),{status:200});
  }});
  await tick();await tick();h.nodes.sessions.value='old';h.nodes.view.fire('click');await tick();
  h.nodes.entries.children[0].children[2].fire('click');h.nodes.draft.value='retain this draft';h.nodes.confirmed.checked=true;h.nodes.commit.fire('click');await tick();await tick();
  assert.equal(h.nodes.draft.value,'retain this draft');assert.equal(h.nodes.entries.children.length,0);assert.equal(h.nodes.reconcile.hidden,true);assert.equal(h.nodes.commit.disabled,true);
  h.nodes.confirmed.checked=true;h.nodes.commit.fire('click');await tick();assert.equal(writes,1);
  badRead=false;h.nodes.view.fire('click');await tick();h.nodes.entries.children[0].children[2].fire('click');assert.equal(h.nodes.draft.value,'retain this draft');
  h.nodes.confirmed.checked=true;h.nodes.commit.fire('click');await tick();await tick();assert.equal(writes,2);h.app.close();
});

test('confirmed commit followed by failed source refresh stays committed and offers no duplicate reconciliation',async()=>{
  let committed=false,writes=0;
  const h=harness({pageValue:()=>committed?{}:page,operation:async(_path,init)=>{committed=true;writes++;return new Response(JSON.stringify({status:'committed',operation_id:JSON.parse(init.body).operation_id}),{status:200});}});
  await tick();await tick();h.nodes.sessions.value='old';h.nodes.view.fire('click');await tick();
  h.nodes.entries.children[0].children[2].fire('click');h.nodes.draft.value='confirmed edit';h.nodes.confirmed.checked=true;h.nodes.commit.fire('click');await tick();await tick();
  assert.equal(writes,1);assert.equal(h.nodes.reconcile.hidden,true);assert.match(h.nodes.status.textContent,/已确认提交/);assert.match(h.nodes.status.textContent,/刷新未完成/);
  h.nodes.reconcile.fire('click');await tick();assert.equal(writes,1);h.app.close();
});
