import type {ConversationStatusView, ConversationSessionsView, ConversationPageView, ConversationEntryView} from '../../shared/generated/contracts.js';
import type {OperatorPairingApp} from './operator-pairing.js';

export interface ConversationArchiveApp extends OperatorPairingApp { stop(): void; close(): void; }
interface Options { start: () => OperatorPairingApp; fetcher?: typeof fetch; operationId?: () => string; deadlineMs?: number; }
const ROOT='/api/v1/conversations';
class PairingLost extends Error {}
class DefinitiveRejection extends Error {}
const LABELS: Record<string,string>={disabled:'未开启',enabled_no_committed_records:'已开启，尚无已提交记录',pending:'正在保存',saved:'已保存',unavailable:'本机存储不可用',write_outcome_unknown:'写入结果不确定',unavailable_or_write_outcome_unknown:'存储不可用或写入结果不确定',rejected:'本次记录被拒绝',revoked_existing_records_retained:'已撤销，原有记录仍保留'};

/** Paired-only preflight and bounded archive panel. No browser storage or HTML injection. */
export function mountConversationArchive(document:Document,options:Options):ConversationArchiveApp {
  function el<T extends HTMLElement>(name:string):T {
    const value=document.querySelector<T>(`[data-archive-${name}]`);
    if(!value)throw new Error('Missing conversation archive control');return value;
  }
  const panel=el('panel'),status=el('status'),recipients=el('recipients'),list=el('entries');
  const sessions=el<HTMLSelectElement>('sessions'),refresh=el<HTMLButtonElement>('refresh');
  const nextSessions=el<HTMLButtonElement>('next-sessions'),view=el<HTMLButtonElement>('view'),next=el<HTMLButtonElement>('next');
  const recall=el<HTMLInputElement>('recall-consent'),google=el<HTMLInputElement>('google-consent');
  const googleLabel=el('google-label'),start=el<HTMLButtonElement>('start'),revoke=el<HTMLButtonElement>('revoke');
  const draft=el<HTMLTextAreaElement>('draft'),preview=el('preview'),confirmed=el<HTMLInputElement>('confirmed');
  const commit=el<HTMLButtonElement>('commit'),cancel=el<HTMLButtonElement>('cancel'),reconcile=el<HTMLButtonElement>('reconcile');
  const fetcher=options.fetcher??globalThis.fetch,lifetime=new AbortController();
  let closed=false,busy=false,started=false,app:OperatorPairingApp|undefined,info:ConversationStatusView|null=null;
  let page:ConversationPageView|null=null,sessionCursor:string|null=null,pending:string|null=null;
  let needsRefresh=false,preserveDraft=false;
  let proposed:{operation:'correct'|'forget'|'restore';entry:ConversationEntryView}|null=null;
  panel.hidden=false;reconcile.hidden=true;googleLabel.hidden=true;
  const controls=()=>{
    const unavailable=closed||busy;
    start.disabled=unavailable||started||!info;
    sessions.disabled=unavailable;recall.disabled=unavailable||started;google.disabled=unavailable||started;
    refresh.disabled=unavailable;view.disabled=unavailable||!sessions.value;
    nextSessions.disabled=unavailable||sessionCursor===null;next.disabled=unavailable||!page?.next_cursor;
    commit.disabled=unavailable||needsRefresh||pending!==null||!proposed||!confirmed.checked||!info?.management_enabled;
    cancel.disabled=unavailable;reconcile.disabled=unavailable||pending===null;revoke.disabled=unavailable||info?.persistence_status==='revoked_existing_records_retained';
  };
  async function json(path:string,body?:unknown):Promise<unknown>{
    const deadline=new AbortController(),timer=setTimeout(()=>deadline.abort(),options.deadlineMs??5000);
    try{
      const response=await fetcher(ROOT+path,{method:body===undefined?'GET':'POST',credentials:'include',cache:'no-store',redirect:'error',
        signal:AbortSignal.any([lifetime.signal,deadline.signal]),headers:{'Accept':'application/json',...(body===undefined?{}:{'Content-Type':'application/json'})},
        ...(body===undefined?{}:{body:typeof body==='string'?body:JSON.stringify(body)})});
      if(response.status===401||response.status===403)throw new PairingLost('本机配对已失效；已清除本页档案内容。先前写入仍须重新配对后核对，不能当作已撤销。');
      if(response.status===409||response.status===422){
        void response.body?.cancel().catch(()=>{});
        throw new DefinitiveRejection(response.status===409?'档案版本或目标已变化，这项修改没有获准。':'这项修改的输入未获接受。');
      }
      if(!response.body)throw new Error('archive unavailable');
      const reader=response.body.getReader();let total=0;const pieces:Uint8Array[]=[];
      try{while(true){const {done,value}=await reader.read();if(done)break;total+=value.byteLength;if(total>131072)throw new Error('archive response too large');pieces.push(value);}}
      finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
      const bytes=new Uint8Array(total);let offset=0;for(const piece of pieces){bytes.set(piece,offset);offset+=piece.length;}
      if(response.status!==200)throw new Error('请求未完成；写入结果可能不确定。');
      return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    }finally{clearTimeout(timer);}
  }
  function showStatus(value:unknown):void{
    const parsed=value as ConversationStatusView;
    if(!parsed||typeof parsed.enabled!=='boolean'||!(parsed.persistence_status in LABELS)||typeof parsed.recipients!=='string'||typeof parsed.selection_locked!=='boolean')throw new Error('archive status invalid');
    info=parsed;status.textContent=`会话记录：${LABELS[parsed.persistence_status]}。${parsed.recall_session_id?'召回来源：'+parsed.recall_session_id:'没有选择历史召回。'}`;
    recipients.textContent=`历史召回接收方：${parsed.recipients}${parsed.speech_enabled?'；历史相关语音还会发送给 Google Cloud TTS':''}。只发送有界、不可信的来源摘录；不恢复旧权限。`;
    googleLabel.hidden=!parsed.speech_enabled;
    if(parsed.selection_locked){started=true;start.hidden=true;}
  }
  function clearDraft():void{proposed=null;preserveDraft=false;draft.value='';preview.textContent='';confirmed.checked=false;controls();}
  async function run(action:()=>Promise<void>):Promise<void>{
    if(closed||busy)return;busy=true;controls();
    try{await action();}catch(error){if(!closed){
      if(error instanceof PairingLost){closed=true;lifetime.abort();pending=null;page=null;info=null;proposed=null;draft.value='';preview.textContent='';confirmed.checked=false;recall.checked=false;google.checked=false;list.replaceChildren();sessions.replaceChildren();reconcile.hidden=true;controls();void app?.stopAndClose();}
      status.textContent=error instanceof Error?error.message:'本机档案不可用。';
    }}
    finally{busy=false;if(!closed)controls();}
  }
  async function loadSessions(cursor:string|null=null):Promise<void>{
    const value=await json('/sessions'+(cursor?'?cursor='+encodeURIComponent(cursor):'')) as ConversationSessionsView;
    if(closed)return;
    if(!value||!Array.isArray(value.sessions)||value.sessions.length>20||value.sessions.some(id=>typeof id!=='string'||id.length>128))throw new Error('archive page invalid');
    const old=sessions.value;sessions.replaceChildren();
    const empty=document.createElement('option');empty.value='';empty.textContent='不召回历史；只记录本次';sessions.appendChild(empty);
    for(const id of value.sessions){const option=document.createElement('option');option.value=id;option.textContent=id;sessions.appendChild(option);}
    sessions.value=value.sessions.includes(old)?old:info?.recall_session_id&&value.sessions.includes(info.recall_session_id)?info.recall_session_id:'';
    sessionCursor=value.next_cursor;
    recall.checked=!!sessions.value&&sessions.value===info?.recall_session_id&&!!info.recall_authorized;
    google.checked=!!sessions.value&&sessions.value===info?.recall_session_id&&!!info.google_authorized;
  }
  async function loadPage(cursor:string|null=null):Promise<void>{
    if(!sessions.value)return;
    const selected=sessions.value;
    needsRefresh=true;
    const value=await json('/entries?session_id='+encodeURIComponent(selected)+(cursor?'&cursor='+encodeURIComponent(cursor):'')) as ConversationPageView;
    if(closed)return;
    if(!value||value.session_id!==selected||!Number.isSafeInteger(value.revision)||!Array.isArray(value.entries)||value.entries.length>20)throw new Error('archive page invalid');
    page=value;list.replaceChildren();
    for(const entry of value.entries){
      if(typeof entry.text!=='string'||entry.text.length>16384||typeof entry.entry_id!=='string')throw new Error('archive entry invalid');
      const item=document.createElement('li'),label=document.createElement('p'),text=document.createElement('pre');
      label.textContent=`${entry.stage} · 版本 ${entry.source_version} · ${entry.active?'可供未来召回':'已更正或抑制'}`;
      if(entry.stage==='audio_progress')label.textContent+=` · 软件音频进度 ${entry.rendered_samples}/${entry.sample_rate_hz}；下文是关联计划，不能当作已听见的全文`;
      text.textContent=entry.text;item.appendChild(label);item.appendChild(text);
      if(info?.management_enabled){
        for(const operation of entry.forget_event_id?['restore'] as const:entry.active&&(entry.stage==='accepted_input'||entry.stage==='corrected_input')?['correct','forget'] as const:[]){
          const button=document.createElement('button');button.type='button';button.textContent={correct:'更正输入',forget:'抑制输入及其衍生记录',restore:'恢复此抑制'}[operation];
          button.addEventListener('click',()=>{if(closed||busy||pending)return;proposed={operation,entry};draft.value=operation==='correct'?(preserveDraft?draft.value:entry.text):'';preserveDraft=false;confirmed.checked=false;preview.textContent=`${button.textContent}：${entry.text}\n旧版本仍保留。本次修改不会擦除当前聊天已接受的输入、已发送给服务商的内容或已播放的声音。`;controls();});item.appendChild(button);
        }
      }list.appendChild(item);
    }
    needsRefresh=false;
    if(proposed){
      const target=value.entries.find(entry=>entry.entry_id===proposed?.entry.entry_id);
      const eligible=target&&(proposed.operation==='restore'?target.forget_event_id===proposed.entry.forget_event_id&&!!target.forget_event_id:target.active);
      if(eligible&&target)proposed={operation:proposed.operation,entry:target};
      else{proposed=null;preview.textContent='原目标已变化；更正草稿已保留，请重新选择当前目标。';}
      confirmed.checked=false;
    }
  }
  async function sendPending():Promise<void>{
    if(!pending)return;
    const body=pending;let committed=false;
    try{
      const result=await json('/operations',body) as {status?:string;operation_id?:string};
      if(closed)return;
      if(result.status!=='committed'||result.operation_id!==JSON.parse(body).operation_id)throw new Error('写入确认无法核对。');
      committed=true;pending=null;reconcile.hidden=true;clearDraft();await loadPage();showStatus(await json('/status'));
      status.textContent+=' 本机操作已确认提交；未来召回按新版本判断。';
    }catch(error){
      if(error instanceof PairingLost)throw error;
      if(closed)return;
      if(committed){page=null;needsRefresh=true;reconcile.hidden=true;status.textContent='本机操作已确认提交，但来源刷新未完成；请重新查看来源。';return;}
      if(error instanceof DefinitiveRejection){
        pending=null;reconcile.hidden=true;confirmed.checked=false;needsRefresh=true;
        preserveDraft=proposed?.operation==='correct';
        try{
          await loadPage();if(closed)return;
          status.textContent=error.message+' 已刷新来源；草稿已保留，请核对后重新确认。';
        }catch(refreshError){
          if(refreshError instanceof PairingLost)throw refreshError;
          if(closed)return;
          page=null;proposed=null;list.replaceChildren();needsRefresh=true;
          preview.textContent='草稿已保留；请先重新查看来源，再选择当前目标。';
          status.textContent=error.message+' 来源刷新尚未完成，未发送新的修改。';
        }
        return;
      }
      reconcile.hidden=false;status.textContent='写入结果未获确认。保留同一操作编号，请点“核对本次操作”。停止回应不代表撤销。';throw error;
    }
  }
  refresh.addEventListener('click',()=>{void run(async()=>{showStatus(await json('/status'));await loadSessions();});});
  nextSessions.addEventListener('click',()=>{void run(()=>loadSessions(sessionCursor));});
  view.addEventListener('click',()=>{void run(()=>loadPage());});next.addEventListener('click',()=>{void run(()=>loadPage(page?.next_cursor??null));});
  sessions.addEventListener('change',()=>{page=null;list.replaceChildren();recall.checked=false;google.checked=false;
    if(preserveDraft){proposed=null;confirmed.checked=false;preview.textContent='更正草稿已保留，请在所选来源中选择目标。';controls();}else clearDraft();});
  confirmed.addEventListener('change',controls);cancel.addEventListener('click',clearDraft);
  commit.addEventListener('click',()=>{if(closed||busy||needsRefresh||!proposed||!page||!confirmed.checked||pending||!info?.management_enabled)return;
    const {operation,entry}=proposed;
    if(operation==='correct'&&(!draft.value.trim()||Array.from(draft.value).length>4096)){status.textContent='更正内容须为 1–4096 个字符。';return;}
    pending=JSON.stringify({session_id:page.session_id,operation_id:(options.operationId??(()=>crypto.randomUUID()))(),expected_revision:page.revision,
      operation,confirmed:true,...(operation==='restore'?{forget_event_id:entry.forget_event_id}:{entry_id:entry.entry_id}),...(operation==='correct'?{text:draft.value}:{})});
    void run(sendPending);
  });
  reconcile.addEventListener('click',()=>{void run(sendPending);});
  start.addEventListener('click',()=>{void run(async()=>{
    if(sessions.value&&(!recall.checked||(info?.speech_enabled&&!google.checked))){status.textContent='请分别确认所选历史召回的接收方及适用的 Google 语音传输。';return;}
    showStatus(await json('/selection',{session_id:sessions.value||null,authorize_selected_provider_and_jev:!!sessions.value&&recall.checked,authorize_google_derived_speech:!!sessions.value&&google.checked}));
    if(closed)return;app=options.start();started=true;start.hidden=true;status.textContent+=' 聊天已启动；本次历史选择已锁定。';
  });});
  revoke.addEventListener('click',()=>{void run(async()=>{showStatus(await json('/revoke',{confirmed:true}));clearDraft();list.replaceChildren();});});
  void run(async()=>{showStatus(await json('/status'));await loadSessions();});
  const result:ConversationArchiveApp={
    stop(){clearDraft();if(pending)status.textContent='回应已停止；本机写入结果仍需核对。';},
    close(){if(closed)return;closed=true;lifetime.abort();pending=null;page=null;info=null;clearDraft();list.replaceChildren();sessions.replaceChildren();panel.hidden=true;},
    async stopAndClose(){result.close();await app?.stopAndClose();},
  };return result;
}
