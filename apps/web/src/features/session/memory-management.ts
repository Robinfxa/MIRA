import { parseHttpRequestId } from '../diagnostics/status.js';

export interface MemoryManagementEntry {
  readonly entry_id: string;
  readonly text: string;
  readonly kind: 'episodic' | 'boundary';
  readonly source: 'user_statement';
  readonly source_version: number;
  readonly recorded_at: string;
  readonly active: boolean;
  readonly forget_event_id: string | null;
  readonly forgotten_at: string | null;
}

export interface MemoryManagementApp {
  /** Stop unsubmitted confirmation/drafts without pretending a sent write rolled back. */
  stop(): void;
  /** Abort work, clear private text and fence late responses before operator revocation. */
  close(): void;
}

export interface MemoryManagementOptions {
  readonly fetcher?: typeof fetch;
  readonly deadlineMs?: number;
  readonly newOperationId?: () => string;
  /** Use wording for a standalone local-only page with no transmission routes. */
  readonly localOnly?: boolean;
}

type OperationPayload =
  | {readonly operation: 'record'; readonly text: string; readonly kind: 'episodic' | 'boundary'}
  | {readonly operation: 'correct'; readonly entry_id: string; readonly text: string}
  | {readonly operation: 'forget'; readonly entry_id: string}
  | {readonly operation: 'restore'; readonly forget_event_id: string};

interface Confirmation {
  readonly payload: OperationPayload;
  readonly preview: string;
  readonly target?: MemoryManagementEntry;
}

interface PendingWrite {
  readonly body: string;
  readonly operationId: string;
  readonly payload: OperationPayload;
  readonly mayHaveCommitted: boolean;
}

interface Page {
  readonly revision: number;
  readonly entries: readonly MemoryManagementEntry[];
  readonly nextCursor: string | null;
}

const STATUS_PATH = '/api/v1/memory-management/status';
const ENTRIES_PATH = '/api/v1/memory-management/entries';
const OPERATIONS_PATH = '/api/v1/memory-management/operations';
const PAGE_SIZE = 20;
const MAX_PAGES = 20;
const MAX_RESPONSE_BYTES = 512 * 1024;
const MAX_PAGE_TEXT_BYTES = 128 * 1024;
const MAX_WRITE_CHARS = 4_096;
const MAX_WRITE_BYTES = 16_384;
const MAX_STORED_ENTRY_CHARS = 16_384;
const MAX_STORED_ENTRY_BYTES = 65_536;
const DEFAULT_DEADLINE_MS = 5_000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function validOpaqueId(value: unknown): value is string {
  return typeof value === 'string' && value.length >= 1 && value.length <= 128
    && !/[\s\x00-\x1f\x7f]/u.test(value);
}

function validTimestamp(value: unknown): value is string {
  return typeof value === 'string' && value.length >= 20 && value.length <= 64 && value.includes('T')
    && (value.endsWith('Z') || /[+-]/u.test(value.slice(10)));
}

function validCursor(value: unknown, expectedRevision: number): value is string {
  if (typeof value !== 'string' || value.length < 4 || value.length > 64 || !/^[a-zA-Z0-9_-]+$/.test(value)) return false;
  try {
    const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4);
    const binary = atob(padded);
    const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
    const payload = new TextDecoder('utf-8', {fatal: true}).decode(bytes);
    const match = /^(0|[1-9][0-9]*):([1-9][0-9]*)$/.exec(payload);
    if (!match) return false;
    const revisionValue = Number(match[1]);
    const sequenceValue = Number(match[2]);
    if (!Number.isSafeInteger(revisionValue) || revisionValue !== expectedRevision || !Number.isSafeInteger(sequenceValue)) return false;
    let binaryRoundTrip = '';
    for (const byte of new TextEncoder().encode(payload)) binaryRoundTrip += String.fromCharCode(byte);
    return btoa(binaryRoundTrip).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '') === value;
  } catch { return false; }
}

function validMemoryText(value: string, maxCodePoints: number, maxBytes: number): boolean {
  if (new TextEncoder().encode(value).byteLength > maxBytes) return false;
  let codePoints = 0;
  for (const _character of value) {
    codePoints++;
    if (codePoints > maxCodePoints) return false;
  }
  return true;
}

function requestDiagnosticId(response: Response): string | null {
  try {
    return parseHttpRequestId(response.headers.get('X-Request-ID'));
  } catch { return null; }
}

function diagnosticSuffix(response: Response): string {
  const id = requestDiagnosticId(response);
  return id === null ? '' : ` 诊断编号：${id}`;
}

function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function hasOnlyKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index]);
}

function validRevision(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function parseStatus(value: unknown): {enabled: boolean; revision: number | null} | null {
  const record = object(value);
  if (!record || !hasOnlyKeys(record, ['enabled', 'revision']) || typeof record['enabled'] !== 'boolean') return null;
  if (record['enabled'] === false && record['revision'] === null) return {enabled: false, revision: null};
  if (record['enabled'] === true && validRevision(record['revision'])) {
    return {enabled: true, revision: record['revision']};
  }
  return null;
}

function parseEntry(value: unknown): MemoryManagementEntry | null {
  const record = object(value);
  if (!record || !hasOnlyKeys(record, [
    'entry_id', 'text', 'kind', 'source', 'source_version', 'recorded_at',
    'active', 'forget_event_id', 'forgotten_at',
  ])) return null;
  if (!validOpaqueId(record['entry_id'])
    || typeof record['text'] !== 'string' || !validMemoryText(record['text'], MAX_STORED_ENTRY_CHARS, MAX_STORED_ENTRY_BYTES)
    || (record['kind'] !== 'episodic' && record['kind'] !== 'boundary')
    || record['source'] !== 'user_statement'
    || !validRevision(record['source_version']) || record['source_version'] < 1
    || !validTimestamp(record['recorded_at'])
    || typeof record['active'] !== 'boolean'
    || (record['forget_event_id'] !== null
      && !validOpaqueId(record['forget_event_id']))
    || (record['forgotten_at'] !== null
      && !validTimestamp(record['forgotten_at']))) return null;
  const forgotten = record['active'] === false;
  if (forgotten ? (record['forget_event_id'] === null || record['forgotten_at'] === null)
    : (record['forget_event_id'] !== null || record['forgotten_at'] !== null)) return null;
  return Object.freeze({
    entry_id: record['entry_id'], text: record['text'], kind: record['kind'], source: 'user_statement',
    source_version: record['source_version'], recorded_at: record['recorded_at'], active: record['active'],
    forget_event_id: record['forget_event_id'], forgotten_at: record['forgotten_at'],
  });
}

function parsePage(value: unknown): Page | null {
  const record = object(value);
  if (!record || !hasOnlyKeys(record, ['revision', 'entries', 'next_cursor'])
    || !validRevision(record['revision']) || !Array.isArray(record['entries'])
    || record['entries'].length > PAGE_SIZE
    || (record['next_cursor'] !== null && !validCursor(record['next_cursor'], record['revision']))) return null;
  const entries: MemoryManagementEntry[] = [];
  const ids = new Set<string>();
  let totalTextBytes = 0;
  for (const raw of record['entries']) {
    const entry = parseEntry(raw);
    if (!entry || ids.has(entry.entry_id)) return null;
    totalTextBytes += new TextEncoder().encode(entry.text).byteLength;
    if (totalTextBytes > MAX_PAGE_TEXT_BYTES) return null;
    ids.add(entry.entry_id);
    entries.push(entry);
  }
  return Object.freeze({revision: record['revision'], entries: Object.freeze(entries), nextCursor: record['next_cursor']});
}

function parseCommitted(value: unknown, expectedOperationId: string): {revision: number; entryId: string | null; replayed: boolean} | null {
  const record = object(value);
  if (!record || !hasOnlyKeys(record, ['status', 'operation_id', 'revision', 'entry_id', 'event_id', 'replayed'])
    || record['status'] !== 'committed' || record['operation_id'] !== expectedOperationId
    || !validRevision(record['revision'])
    || (record['entry_id'] !== null && !validOpaqueId(record['entry_id']))
    || (record['event_id'] !== null && !validOpaqueId(record['event_id']))
    || typeof record['replayed'] !== 'boolean') return null;
  return {revision: record['revision'], entryId: record['entry_id'], replayed: record['replayed']};
}

function requestOptions(method: string, signal: AbortSignal, body?: string): RequestInit {
  return {
    method,
    credentials: 'include',
    cache: 'no-store',
    redirect: 'error',
    headers: body === undefined ? {'Accept': 'application/json'} : {
      'Accept': 'application/json', 'Content-Type': 'application/json',
    },
    ...(body === undefined ? {} : {body}),
    signal,
  };
}

function raceAbort<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(new Error('request aborted'));
  return new Promise<T>((resolve, reject) => {
    const onAbort = (): void => reject(new Error('request aborted'));
    signal.addEventListener('abort', onAbort, {once: true});
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', onAbort));
  });
}

async function readLimitedJson(response: Response, signal: AbortSignal): Promise<unknown> {
  if (!response.body) throw new Error('bounded response body is unavailable');
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const result = await raceAbort(reader.read(), signal);
      if (result.done) break;
      if (!(result.value instanceof Uint8Array)) throw new Error('bounded response chunk is invalid');
      total += result.value.byteLength;
      if (total > MAX_RESPONSE_BYTES) throw new Error('bounded response exceeded its byte limit');
      chunks.push(result.value);
    }
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    const jsonText = new TextDecoder('utf-8', {fatal: true}).decode(bytes);
    return JSON.parse(jsonText) as unknown;
  } catch {
    void reader.cancel().catch(() => undefined);
    throw new Error('bounded response could not be read');
  } finally {
    try { reader.releaseLock(); } catch { /* A cancelled stream may still be settling. */ }
  }
}

async function boundedRequest(fetcher: typeof fetch, path: string, init: RequestInit, deadlineMs: number,
    readBodyWhen: (statusCode: number) => boolean): Promise<{response: Response; body: unknown}> {
  const deadline = new AbortController();
  const signal = init.signal ? AbortSignal.any([init.signal, deadline.signal]) : deadline.signal;
  const timeout = setTimeout(() => deadline.abort(), deadlineMs);
  try {
    const fetchPromise = fetcher(path, {...init, signal});
    void fetchPromise.then(response => {
      if (signal.aborted) void response.body?.cancel().catch(() => undefined);
    }, () => undefined);
    const response = await raceAbort(fetchPromise, signal);
    if (readBodyWhen(response.status)) return {response, body: await readLimitedJson(response, signal)};
    void response.body?.cancel().catch(() => undefined);
    return {response, body: null};
  }
  finally { clearTimeout(timeout); }
}

function safeErrorCode(value: unknown, statusCode: number): string | null {
  const record = object(value);
  if (!record || typeof record['code'] !== 'string' || typeof record['message'] !== 'string'
    || record['message'].length > 256 || !validOpaqueId(record['request_id'])) return null;
  if (record['code'] === 'stale_revision') {
    const hasRevision = Object.hasOwn(record, 'current_revision');
    if (statusCode !== 409
      || !(hasOnlyKeys(record, ['code', 'message', 'request_id'])
        || hasOnlyKeys(record, ['code', 'message', 'request_id', 'current_revision']))
      || (hasRevision && !validRevision(record['current_revision']))) return null;
  } else if (!hasOnlyKeys(record, ['code', 'message', 'request_id'])) return null;
  const allowed = new Set([
    'stale_revision', 'operation_id_conflict', 'operation_conflict', 'entry_not_found',
    'memory_management_busy', 'operator_runtime_unavailable', 'invalid_request',
  ]);
  return allowed.has(record['code']) ? record['code'] : null;
}

function requestUrl(cursor: string | null): string {
  return cursor === null ? `${ENTRIES_PATH}?limit=${PAGE_SIZE}`
    : `${ENTRIES_PATH}?limit=${PAGE_SIZE}&cursor=${encodeURIComponent(cursor)}`;
}

function operationId(): string {
  if (typeof globalThis.crypto?.randomUUID !== 'function') throw new Error('secure random UUID unavailable');
  return globalThis.crypto.randomUUID();
}

function entryKindLabel(kind: 'episodic' | 'boundary'): string {
  return kind === 'boundary' ? '明确界限（每轮保留）' : '普通记忆（按需召回）';
}

/**
 * A paired-page-only controller for explicit local memory management.
 * It has no storage, URL-derived scope, transcript access, or diagnostic output.
 */
export function mountMemoryManagement(document: Document, options: MemoryManagementOptions = {}): MemoryManagementApp {
  const fetcher = options.fetcher ?? globalThis.fetch;
  const deadlineMs = options.deadlineMs ?? DEFAULT_DEADLINE_MS;
  const panel = document.querySelector<HTMLDetailsElement>('[data-memory-management-panel]');
  const status = document.querySelector<HTMLElement>('[data-memory-management-status]');
  const entriesList = document.querySelector<HTMLOListElement>('[data-memory-management-entries]');
  const refresh = document.querySelector<HTMLButtonElement>('[data-memory-management-refresh]');
  const previous = document.querySelector<HTMLButtonElement>('[data-memory-management-previous]');
  const next = document.querySelector<HTMLButtonElement>('[data-memory-management-next]');
  const localConsent = document.querySelector<HTMLInputElement>('[data-memory-management-local-consent]');
  const form = document.querySelector<HTMLFormElement>('form[data-memory-management-record-form]');
  const text = document.querySelector<HTMLTextAreaElement>('[data-memory-management-text]');
  const kind = document.querySelector<HTMLSelectElement>('[data-memory-management-kind]');
  const editorTitle = document.querySelector<HTMLElement>('[data-memory-management-editor-title]');
  const cancelEdit = document.querySelector<HTMLButtonElement>('[data-memory-management-cancel-edit]');
  const confirmation = document.querySelector<HTMLElement>('[data-memory-management-confirmation]');
  const preview = document.querySelector<HTMLElement>('[data-memory-management-preview]');
  const confirmed = document.querySelector<HTMLInputElement>('[data-memory-management-confirmed]');
  const commit = document.querySelector<HTMLButtonElement>('[data-memory-management-commit]');
  const cancel = document.querySelector<HTMLButtonElement>('[data-memory-management-cancel]');
  const reconcile = document.querySelector<HTMLButtonElement>('[data-memory-management-reconcile]');
  const disclosure = document.querySelector<HTMLElement>('.memory-management-disclosure');
  const retention = document.querySelector<HTMLElement>('.memory-management-retention');
  if (!panel || !status || !entriesList || !refresh || !previous || !next || !localConsent || !form
    || !text || !kind || !editorTitle || !cancelEdit || !confirmation || !preview || !confirmed
    || !commit || !cancel || !reconcile) throw new Error('Missing local memory management interface');

  let closed = false;
  let active = false;
  let loading = false;
  let writing = false;
  let needsRefresh = false;
  let revision: number | null = null;
  let entries: readonly MemoryManagementEntry[] = [];
  let correctionTarget: MemoryManagementEntry | null = null;
  let proposed: Confirmation | null = null;
  let pendingWrite: PendingWrite | null = null;
  let pageCursors: (string | null)[] = [null];
  let pageIndex = 0;
  let nextCursor: string | null = null;
  let readGeneration = 0;
  let activeRead: AbortController | null = null;
  let activeWrite: AbortController | null = null;
  const operationIdFactory = options.newOperationId ?? operationId;

  panel.hidden = false;
  if (options.localOnly === true) {
    if (disclosure) disclosure.textContent = '读取和写入只发生在此机器的固定私有范围。此工具没有模型或提供方路由，也不会向外部服务传送记忆内容。';
    if (retention) retention.textContent = '软忘记会在本机追加历史中保留原文，并可通过明确操作恢复；这不是安全删除，也不能撤回其他独立工具可能已获准传送的内容。';
  }
  confirmation.hidden = true;
  reconcile.hidden = true;
  cancelEdit.hidden = true;
  entriesList.replaceChildren();

  const setStatus = (message: string): void => { status.textContent = message; };
  const setUnknownWriteStatus = (suffix = ''): void => {
    setStatus(localConsent.checked
      ? `本机操作结果不确定；不会自动重试或显示为成功。若仍同意本机写入，可手动重发完全相同的请求与操作编号核对；若原请求尚未提交，这会执行原操作。${suffix}`
      : `本机写入同意已撤回；原操作结果仍不确定。不会再发送核对请求，除非你重新勾选同意并明确点击核对；这不代表原操作已撤销。${suffix}`);
  };
  const setReadControls = (): void => {
    const locked = closed || loading || writing || needsRefresh || pendingWrite !== null;
    refresh.disabled = closed || loading || writing || pendingWrite !== null;
    previous.disabled = locked || pageIndex <= 0;
    next.disabled = locked || nextCursor === null || pageIndex >= MAX_PAGES - 1;
    const proposeButton = form.querySelector<HTMLButtonElement>('[data-memory-management-propose]');
    form.querySelectorAll<HTMLButtonElement>('button').forEach(button => {
      button.disabled = locked || (button === proposeButton && !localConsent.checked);
    });
    localConsent.disabled = closed || loading || writing;
    for (const button of entriesList.querySelectorAll<HTMLButtonElement>('button')) button.disabled = locked;
    commit.disabled = closed || loading || writing || needsRefresh || pendingWrite !== null
      || !proposed || !confirmed.checked || !localConsent.checked || revision === null;
    confirmed.disabled = closed || writing || pendingWrite !== null;
    cancel.disabled = closed || writing || pendingWrite !== null;
    reconcile.disabled = closed || writing || pendingWrite === null || !localConsent.checked;
  };
  const clearProposed = (): void => {
    proposed = null;
    confirmation.hidden = true;
    preview.textContent = '';
    confirmed.checked = false;
    commit.disabled = true;
    text.value = '';
    correctionTarget = null;
    kind.disabled = false;
    editorTitle.textContent = '添加一条陈述';
    cancelEdit.hidden = true;
  };
  const clearPrivateState = (): void => {
    entries = [];
    revision = null;
    nextCursor = null;
    pageCursors = [null];
    pageIndex = 0;
    correctionTarget = null;
    entriesList.replaceChildren();
    text.value = '';
    localConsent.checked = false;
    clearProposed();
  };
  const findEntry = (entryId: string): MemoryManagementEntry | undefined => entries.find(entry => entry.entry_id === entryId);
  const renderEntries = (): void => {
    entriesList.replaceChildren();
    for (const entry of entries) {
      const row = document.createElement('li');
      row.className = 'memory-management-entry';
      const body = document.createElement('p');
      body.className = 'memory-management-entry-text';
      body.textContent = entry.text;
      const meta = document.createElement('span');
      meta.className = 'memory-management-entry-meta';
      meta.textContent = `${entryKindLabel(entry.kind)} · 版本 ${entry.source_version} · ${entry.active ? '当前' : '已忘记，可恢复'}`;
      const actions = document.createElement('div');
      actions.className = 'memory-management-entry-actions';
      const addAction = (action: 'correct' | 'forget' | 'restore', label: string): void => {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset['memoryManagementAction'] = action;
        button.dataset['entryId'] = entry.entry_id;
        button.textContent = label;
        button.addEventListener('click', () => {
          if (closed || loading || writing || needsRefresh) return;
          if (action === 'correct') {
            correctionTarget = findEntry(entry.entry_id) ?? null;
            if (!correctionTarget || !correctionTarget.active) return;
            kind.value = correctionTarget.kind;
            kind.disabled = true;
            text.value = '';
            editorTitle.textContent = '更正这条陈述';
            cancelEdit.hidden = false;
            setStatus('请输入新的准确措辞；更正会追加一个版本，不会覆盖历史。');
            setReadControls();
            return;
          }
          if (!localConsent.checked) {
            setStatus('请先勾选本页的本机写入同意，再准备这次操作。');
            return;
          }
          if (action === 'forget') {
            const target = findEntry(entry.entry_id);
            if (!target || !target.active) return;
            const externalCopy = options.localOnly === true
              ? '此工具不会执行任何外部内容传输。'
              : '这也无法撤回此前已经发送给模型的内容。';
            propose({payload: {operation: 'forget', entry_id: target.entry_id}, target,
              preview: `软忘记这条本机陈述：\n\n${target.text}\n\n这不会从追加历史中删除文字；它可由一次明确的恢复操作恢复。${externalCopy}`});
          } else {
            const target = findEntry(entry.entry_id);
            if (!target || target.active || !target.forget_event_id) return;
            const externalCopy = options.localOnly === true
              ? '此工具不会执行任何外部内容传输。'
              : '这不会撤回此前已经发送给模型的内容。';
            propose({payload: {operation: 'restore', forget_event_id: target.forget_event_id}, target,
              preview: `恢复这条陈述对应的一项软忘记事件：\n\n${target.text}\n\n若仍有其他有效软忘记事件，文字可能继续不参与召回。请在刷新后核对实际状态。${externalCopy}`});
          }
        });
        actions.appendChild(button);
      };
      if (entry.active) {
        addAction('correct', '更正');
        addAction('forget', '软忘记');
      } else if (entry.forget_event_id !== null) {
        addAction('restore', '明确恢复');
      }
      row.appendChild(body);
      row.appendChild(meta);
      row.appendChild(actions);
      entriesList.appendChild(row);
    }
  };
  const propose = (confirmationValue: Confirmation): void => {
    if (closed || loading || writing || needsRefresh) return;
    if (!localConsent.checked) {
      setStatus('请先勾选本页的本机写入同意，再准备这次操作。');
      return;
    }
    proposed = confirmationValue;
    preview.textContent = confirmationValue.preview;
    confirmation.hidden = false;
    confirmed.checked = false;
    commit.disabled = true;
    setStatus('请逐字核对上面的内容，并再次勾选后才会发送本机操作。');
    setReadControls();
  };
  const setReadFailure = (response: Response): void => {
    const suffix = diagnosticSuffix(response);
    if (response.status === 401) {
      clearPrivateState();
      setStatus(`本机配对已失效或不匹配。本机记忆面板已清除；请结束本页，并重新启动本机服务后亲自配对。${suffix}`);
    } else if (response.status === 403) {
      clearPrivateState();
      setStatus(`本机服务拒绝了此来源的访问。本机记忆面板已清除；没有新的读取或写入。${suffix}`);
    } else if (response.status === 404) {
      clearPrivateState();
      setStatus(`本机记忆管理当前不可用。本机记忆面板已清除；请确认本次启动显式启用了管理。${suffix}`);
    }
    else if (response.status === 503) setStatus(`本机管理服务暂时无法提供记忆页。没有自动重试；可稍后手动刷新。${suffix}`);
    else setStatus(`无法安全读取本机记忆页。未显示响应内容，也没有自动重试。${suffix}`);
  };

  const loadPage = async (cursor: string | null, reason: 'open' | 'refresh' | 'next' | 'previous'): Promise<void> => {
    if (closed || loading || writing) return;
    loading = true;
    const requestGeneration = ++readGeneration;
    const abort = new AbortController();
    activeRead?.abort();
    activeRead = abort;
    setStatus('正在读取这一页本机记忆…');
    setReadControls();
    try {
      const statusResult = await boundedRequest(fetcher, STATUS_PATH, requestOptions('GET', abort.signal),
        deadlineMs, statusCode => statusCode === 200);
      const statusResponse = statusResult.response;
      if (closed || requestGeneration !== readGeneration) return;
      if (statusResponse.status !== 200) { needsRefresh = true; setReadFailure(statusResponse); return; }
      const statusValue = parseStatus(statusResult.body);
      if (closed || requestGeneration !== readGeneration) return;
      if (!statusValue) { needsRefresh = true; setStatus('本机状态回复格式无效。没有显示或写入任何内容。请手动刷新。'); return; }
      if (!statusValue.enabled || statusValue.revision === null) {
        needsRefresh = true;
        revision = null;
        clearProposed();
        setStatus('本机记忆管理默认关闭。只有本机操作方显式启用本地写入并完成配对时才能使用。');
        entries = [];
        renderEntries();
        return;
      }
      const entriesResult = await boundedRequest(fetcher, requestUrl(cursor), requestOptions('GET', abort.signal),
        deadlineMs, statusCode => statusCode === 200);
      const entriesResponse = entriesResult.response;
      if (closed || requestGeneration !== readGeneration) return;
      if (entriesResponse.status !== 200) { needsRefresh = true; setReadFailure(entriesResponse); return; }
      const page = parsePage(entriesResult.body);
      if (closed || requestGeneration !== readGeneration) return;
      if (!page) { needsRefresh = true; setStatus('本机记忆页回复格式无效。没有显示或写入任何内容。请手动刷新。'); return; }
      if (page.revision !== statusValue.revision) {
        entries = [];
        renderEntries();
        needsRefresh = true;
        clearProposed();
        setStatus('读取期间本机记忆版本已变化。请手动刷新后再核对或操作。');
        return;
      }
      const previousRevision = revision;
      if (previousRevision !== null && previousRevision !== page.revision && (proposed || correctionTarget)) clearProposed();
      revision = page.revision;
      entries = page.entries;
      nextCursor = page.nextCursor;
      needsRefresh = false;
      if (reason === 'open' || reason === 'refresh') { pageCursors = [null]; pageIndex = 0; }
      else if (reason === 'next') {
        if (pageIndex < MAX_PAGES - 1) { pageCursors = pageCursors.slice(0, pageIndex + 1); pageCursors.push(cursor); pageIndex++; }
      } else if (reason === 'previous') pageIndex = Math.max(0, pageIndex - 1);
      renderEntries();
      const pageSummary = `本机记忆第 ${pageIndex + 1} 页 · 版本 ${revision} · ${entries.length} 条。内容只显示当前有界页面。`;
      setStatus(nextCursor !== null && pageIndex >= MAX_PAGES - 1
        ? `${pageSummary} 已达到最多 ${MAX_PAGES} 页的浏览范围；仍有后续页未显示。`
        : pageSummary);
    } catch {
      if (!closed && requestGeneration === readGeneration) {
        needsRefresh = true;
        setStatus('读取结果未确认。没有自动重试；请手动刷新本机记忆页。');
      }
    } finally {
      if (requestGeneration === readGeneration) {
        loading = false;
        activeRead = null;
        setReadControls();
      }
    }
  };

  const finishRejected = (message: string): void => {
    pendingWrite = null;
    needsRefresh = true;
    reconcile.hidden = true;
    clearProposed();
    setStatus(message);
    setReadControls();
  };

  const sendPendingWrite = async (): Promise<void> => {
    const pending = pendingWrite;
    if (closed || writing || !pending) return;
    if (!localConsent.checked) { setUnknownWriteStatus(); return; }
    writing = true;
    reconcile.hidden = true;
    const abort = new AbortController();
    activeWrite = abort;
    setStatus('正在提交已确认的本机操作…停止回应不会撤销已提交或不确定的本机写入。');
    setReadControls();
    try {
      const resultEnvelope = await boundedRequest(fetcher, OPERATIONS_PATH,
        requestOptions('POST', abort.signal, pending.body), deadlineMs,
        statusCode => statusCode === 200 || statusCode === 409 || statusCode === 503);
      const response = resultEnvelope.response;
      if (closed || pendingWrite !== pending) return;
      if (response.status === 200) {
        const result = parseCommitted(resultEnvelope.body, pending.operationId);
        if (!result) {
          pendingWrite = {...pending, mayHaveCommitted: true};
          writing = false;
          activeWrite = null;
          reconcile.hidden = false;
          setUnknownWriteStatus(' 本机服务的确认回复无法核对，不要新建重复记录。');
          setReadControls();
          return;
        }
        pendingWrite = null;
        writing = false;
        activeWrite = null;
        revision = result.revision;
        needsRefresh = false;
        clearProposed();
        if (correctionTarget) correctionTarget = null;
        const operationOutcome = result.replayed ? '本机已确认这项操作先前成功提交，没有重复添加。'
          : '本机已确认这项操作已提交。';
        setStatus(`${operationOutcome}正在刷新当前页…`);
        setReadControls();
        // Cursors bind the old revision. A committed write starts a fresh first page.
        await loadPage(null, 'refresh');
        if (closed) return;
        if (revision === null || revision < result.revision || needsRefresh) {
          needsRefresh = true;
          setStatus(`${operationOutcome}但刷新页未能匹配该版本；请手动刷新并核对当前状态。`);
          setReadControls();
        } else {
          setStatus(`${operationOutcome} ${status.textContent}`);
        }
        return;
      }
      const errorValue = response.status === 409 || response.status === 503 ? resultEnvelope.body : null;
      if (closed || pendingWrite !== pending) return;
      const code = safeErrorCode(errorValue, response.status);
      if (response.status === 503 || code === 'memory_management_busy' || code === 'operator_runtime_unavailable') {
        pendingWrite = {...pending, mayHaveCommitted: true};
        writing = false;
        activeWrite = null;
        reconcile.hidden = false;
        setUnknownWriteStatus(` ${diagnosticSuffix(response)}`);
        setReadControls();
        return;
      }
      writing = false;
      activeWrite = null;
      if (response.status === 409) {
        const message = code === 'stale_revision' ? '本机记忆版本已变化，这次操作没有按旧版本继续。请手动刷新并重新核对。'
          : code === 'entry_not_found' ? '目标记录已不存在或不再可操作。请手动刷新当前页。'
          : code === 'operation_id_conflict' ? '本次操作编号与本机现有操作冲突；未显示为成功。请刷新后重新核对，再发起一项新的确认。'
          : '本机记忆操作发生冲突；未显示为成功。请手动刷新并重新核对。';
        finishRejected(`${message}${diagnosticSuffix(response)}`);
        return;
      }
      if (response.status === 401 || response.status === 403) {
        const uncertain = pending.mayHaveCommitted;
        pendingWrite = null;
        writing = false;
        activeWrite = null;
        reconcile.hidden = true;
        needsRefresh = true;
        clearPrivateState();
        setStatus(uncertain
          ? `本机配对或来源访问已失效，先前操作结果无法通过当前配对核实。本机记忆面板已清除；不要假设它已撤销。${diagnosticSuffix(response)}`
          : `本机配对或来源访问已失效。本机记忆面板已清除；这次操作没有显示为成功。${diagnosticSuffix(response)}`);
        setReadControls();
        return;
      }
      if (response.status === 413 || response.status === 422) { finishRejected(`本机服务拒绝了这项输入；没有显示为已保存。请刷新后检查内容和长度。${diagnosticSuffix(response)}`); return; }
      pendingWrite = {...pending, mayHaveCommitted: true};
      writing = false;
      activeWrite = null;
      reconcile.hidden = false;
      setUnknownWriteStatus(` ${diagnosticSuffix(response)}`);
      setReadControls();
    } catch {
      if (closed || pendingWrite !== pending) return;
      pendingWrite = {...pending, mayHaveCommitted: true};
      writing = false;
      activeWrite = null;
      reconcile.hidden = false;
      setUnknownWriteStatus();
      setReadControls();
    } finally {
      if (!closed && pendingWrite === pending && writing) {
        writing = false;
        activeWrite = null;
        setReadControls();
      }
    }
  };

  form.addEventListener('submit', event => {
    event.preventDefault();
    if (closed || loading || writing || needsRefresh) return;
    if (!localConsent.checked) { setStatus('请先勾选本页的本机写入同意。'); return; }
    const value = text.value;
    if (!value.trim() || !validMemoryText(value, MAX_WRITE_CHARS, MAX_WRITE_BYTES)) {
      setStatus(`请手动输入不超过 ${MAX_WRITE_CHARS} 个 Unicode 字符且不超过 ${MAX_WRITE_BYTES / 1024} KiB UTF-8 的非空陈述。`);
      return;
    }
    if (correctionTarget) {
      const current = findEntry(correctionTarget.entry_id);
      if (!current || !current.active) { needsRefresh = true; setStatus('要更正的记录已变化；请手动刷新当前页。'); setReadControls(); return; }
      propose({payload: {operation: 'correct', entry_id: current.entry_id, text: value}, target: current,
        preview: `更正这条本机陈述：\n\n原文：\n${current.text}\n\n新措辞：\n${value}\n\n更正会保留旧版本于本机追加历史。`});
    } else {
      propose({payload: {operation: 'record', text: value, kind: kind.value === 'boundary' ? 'boundary' : 'episodic'},
        preview: `添加一条本机陈述（${entryKindLabel(kind.value === 'boundary' ? 'boundary' : 'episodic')}）：\n\n${value}\n\n它由你手动输入；没有从聊天中自动提取。`});
    }
  });

  confirmed.addEventListener('change', setReadControls);
  commit.addEventListener('click', () => {
    if (closed || loading || writing || needsRefresh || pendingWrite !== null
      || !proposed || !confirmed.checked || !localConsent.checked || revision === null) return;
    let operationIdValue: string;
    try { operationIdValue = operationIdFactory(); } catch {
      setStatus('无法安全生成本次操作编号；没有发送任何记忆内容。');
      return;
    }
    if (!UUID.test(operationIdValue)) { setStatus('操作编号不可用；没有发送任何记忆内容。'); return; }
    const payload = proposed.payload;
    const request = Object.freeze({operation_id: operationIdValue, expected_revision: revision, ...payload, confirmed: true});
    pendingWrite = {operationId: operationIdValue, payload, body: JSON.stringify(request), mayHaveCommitted: false};
    void sendPendingWrite();
  });
  cancel.addEventListener('click', () => {
    if (closed || writing) return;
    clearProposed();
    setStatus('本次确认已取消；未发送本机写入。');
    setReadControls();
  });
  cancelEdit.addEventListener('click', () => {
    if (closed || writing) return;
    clearProposed();
    setStatus('已取消更正草稿。');
    setReadControls();
  });
  localConsent.addEventListener('change', () => {
    if (!localConsent.checked && (proposed || correctionTarget)) clearProposed();
    if (pendingWrite) {
      if (!localConsent.checked && writing) {
        setStatus('本机写入同意已撤回，但已发送的本机请求仍在处理中；撤回不能确认它已取消。');
      } else setUnknownWriteStatus();
    }
    setReadControls();
  });
  refresh.addEventListener('click', () => {
    if (!closed && !loading && !writing && pendingWrite === null) {
      if (proposed || correctionTarget) clearProposed();
      needsRefresh = false;
      reconcile.hidden = true;
      pendingWrite = null;
      loadPage(null, 'refresh');
    }
  });
  next.addEventListener('click', () => {
    if (!closed && !loading && !writing && !needsRefresh && nextCursor !== null && pageIndex < MAX_PAGES - 1) {
      const cursor = nextCursor;
      void loadPage(cursor, 'next');
    }
  });
  previous.addEventListener('click', () => {
    if (!closed && !loading && !writing && !needsRefresh && pageIndex > 0) {
      void loadPage(pageCursors[pageIndex - 1] ?? null, 'previous');
    }
  });
  reconcile.addEventListener('click', () => { void sendPendingWrite(); });
  panel.addEventListener('toggle', () => {
    if (panel.open && !active && !closed) {
      active = true;
      void loadPage(null, 'open');
    }
  });
  setReadControls();

  return {
    stop() {
      if (closed) return;
      clearProposed();
      confirmed.checked = false;
      if (pendingWrite && writing) setStatus('角色回应已停止。本机写入仍在等待确认回复；停止回应不会撤销已提交或不确定的操作。');
      else if (pendingWrite) setUnknownWriteStatus('角色回应已停止；不能把它当作撤销。');
      else setStatus('角色回应已停止。尚未确认的本机记忆草稿已清除。');
      setReadControls();
    },
    close() {
      if (closed) return;
      closed = true;
      readGeneration++;
      activeRead?.abort();
      activeWrite?.abort();
      activeRead = null;
      activeWrite = null;
      pendingWrite = null;
      entries = [];
      revision = null;
      nextCursor = null;
      pageCursors = [null];
      pageIndex = 0;
      correctionTarget = null;
      proposed = null;
      text.value = '';
      preview.textContent = '';
      confirmed.checked = false;
      localConsent.checked = false;
      entriesList.replaceChildren();
      confirmation.hidden = true;
      reconcile.hidden = true;
      panel.hidden = true;
      setStatus('本机记忆面板已清除；配对撤销由本机服务处理。');
      setReadControls();
    },
  };
}
