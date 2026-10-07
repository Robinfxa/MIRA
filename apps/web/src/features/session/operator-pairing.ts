export interface OperatorStatus {
  readonly required: boolean;
  readonly paired: boolean;
  readonly revoked: boolean;
}

export interface OperatorPairingApp {
  /** Must stop local output first and then close all private session work. */
  stopAndClose(): Promise<void>;
}

export interface OperatorPairingOptions {
  readonly fetcher?: typeof fetch;
  readonly onPaired: () => OperatorPairingApp | void;
  readonly deadlineMs?: number;
  /** Local management-only copy for pages with no conversational runtime. */
  readonly localOnly?: boolean;
}

export interface OperatorPairingGate {
  readonly ready: Promise<void>;
  cancelAndRevoke(): Promise<void>;
  close(): Promise<void>;
}

const STATUS_PATH = '/api/v1/operator/status';
const PAIR_PATH = '/api/v1/operator/pair';
const REVOKE_PATH = '/api/v1/operator/revoke';
const DEADLINE_MS = 5000;
const UNAVAILABLE = '无法确认本机配对状态。此页面不会启动记忆会话。请确认本机 MIRA 服务仍在运行，再刷新页面。';
const PAIR_FAILED = '配对未完成。页面已清除输入且不会自动重试。请重新启动本机 MIRA 服务，并亲自读取新的私有配对文件。';
const CHECKPOINT_UPGRADE = '检测到需要显式升级的旧剧情存档；存档未被改动，也不会自动升级。请先关闭本机 MIRA 服务，再运行 python tools/story_checkpoint.py dry-run，使用原来的 --db 和 --scope，并加上 --authorize-story-checkpoint。检查结果后再决定是否提交升级，然后重新启动服务并读取新的私有配对文件。';
const PAIR_ERROR_MAX_BYTES = 2048;
const PAIR_ERROR_MAX_CHUNKS = 64;
const REVOKE_FAILED = '本地回应已停止，但无法确认配对撤销。请关闭本页和本机 MIRA 服务，再重新启动并读取新的私有配对文件。';

function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function parseStatus(value: unknown): OperatorStatus | null {
  const record = object(value);
  if (!record || Object.keys(record).length !== 3
    || typeof record['required'] !== 'boolean' || typeof record['paired'] !== 'boolean'
    || typeof record['revoked'] !== 'boolean') return null;
  return Object.freeze({required: record['required'], paired: record['paired'], revoked: record['revoked']});
}

function requestOptions(method: string, signal: AbortSignal, body?: string, keepalive = false): RequestInit {
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
    ...(keepalive ? {keepalive: true} : {}),
  };
}

async function boundedFetch(fetcher: typeof fetch, path: string, init: RequestInit, deadlineMs: number): Promise<Response> {
  const deadline = new AbortController();
  const signal = init.signal ? AbortSignal.any([init.signal, deadline.signal]) : deadline.signal;
  const timeout = setTimeout(() => deadline.abort(), deadlineMs);
  try { return await fetcher(path, {...init, signal}); }
  finally { clearTimeout(timeout); }
}

async function readStatus(fetcher: typeof fetch, deadlineMs: number): Promise<OperatorStatus> {
  const abort = new AbortController();
  const timeout = setTimeout(() => abort.abort(), deadlineMs);
  try {
    const response = await fetcher(STATUS_PATH, requestOptions('GET', abort.signal));
    if (response.status !== 200) throw new Error('operator status unavailable');
    let raw: unknown;
    try { raw = await response.json(); } catch { throw new Error('operator status unavailable'); }
    const parsed = parseStatus(raw);
    if (!parsed) throw new Error('operator status unavailable');
    return parsed;
  } finally { clearTimeout(timeout); }
}

async function postWithoutBody(fetcher: typeof fetch, path: string, body: string | undefined,
    deadlineMs: number, parentSignal?: AbortSignal, keepalive = false): Promise<boolean> {
  const abort = new AbortController();
  const signal = parentSignal ? AbortSignal.any([parentSignal, abort.signal]) : abort.signal;
  const response = await boundedFetch(fetcher, path,
    requestOptions('POST', signal, body, keepalive), deadlineMs);
  return response.status === 204;
}

type PairResult = 'paired' | 'checkpoint_upgrade' | 'failed';

async function knownCheckpointError(response: Response, signal: AbortSignal): Promise<boolean> {
  if (response.status !== 409
      || response.headers.get('Content-Type')?.split(';', 1)[0]?.trim().toLowerCase() !== 'application/json') return false;
  const length = response.headers.get('Content-Length');
  if (length !== null && (!/^(0|[1-9]\d*)$/.test(length) || Number(length) > PAIR_ERROR_MAX_BYTES)) return false;
  const reader = response.body?.getReader();
  if (!reader) return false;
  const cancel = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener('abort', cancel, {once: true});
  try {
    const chunks: Uint8Array[] = [];
    let bytes = 0;
    let finished = false;
    for (let count = 0; count < PAIR_ERROR_MAX_CHUNKS; count++) {
      if (signal.aborted) return false;
      const next = await reader.read();
      if (signal.aborted) return false;
      if (next.done) { finished = true; break; }
      bytes += next.value.byteLength;
      if (bytes > PAIR_ERROR_MAX_BYTES) return false;
      chunks.push(next.value);
    }
    if (!finished) return false;
    const joined = new Uint8Array(bytes);
    let offset = 0;
    for (const chunk of chunks) { joined.set(chunk, offset); offset += chunk.byteLength; }
    const record = object(JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(joined)));
    return record !== null && record['code'] === 'story_checkpoint_canon_upgrade_required'
      && Object.keys(record).every(key => ['code', 'message', 'request_id'].includes(key))
      && (record['message'] === undefined || typeof record['message'] === 'string')
      && (record['request_id'] === undefined || typeof record['request_id'] === 'string');
  } catch { return false; }
  finally {
    signal.removeEventListener('abort', cancel);
    cancel();
    reader.releaseLock();
  }
}

async function postPair(fetcher: typeof fetch, body: string,
    deadlineMs: number, parentSignal: AbortSignal): Promise<PairResult> {
  const deadline = new AbortController();
  const signal = AbortSignal.any([parentSignal, deadline.signal]);
  let onAbort: (() => void) | undefined;
  const aborted = new Promise<never>((_resolve, reject) => {
    onAbort = () => reject(new Error('operator pairing interrupted'));
    signal.addEventListener('abort', onAbort, {once: true});
    if (signal.aborted) onAbort();
  });
  const timeout = setTimeout(() => deadline.abort(), deadlineMs);
  const request = (async (): Promise<PairResult> => {
    const response = await fetcher(PAIR_PATH, requestOptions('POST', signal, body));
    if (signal.aborted) return 'failed';
    if (response.status === 204) return 'paired';
    return await knownCheckpointError(response, signal) ? 'checkpoint_upgrade' : 'failed';
  })();
  try { return await Promise.race([request, aborted]); }
  finally {
    clearTimeout(timeout);
    if (onAbort) signal.removeEventListener('abort', onAbort);
  }
}

/**
 * Browser-only ephemeral pairing gate for the explicitly marked memory-mode page.
 * Pairing codes are held only in the password input until submit and are never read back
 * into page text, URLs, storage, or diagnostics.
 */
export function mountOperatorPairing(document: Document, options: OperatorPairingOptions): OperatorPairingGate {
  const fetcher = options.fetcher ?? globalThis.fetch;
  const deadlineMs = options.deadlineMs ?? DEADLINE_MS;
  const localOnly = options.localOnly === true;
  const privateDevice = document.body?.dataset['deviceAccess'] === 'private';
  const panel = document.querySelector<HTMLElement>('[data-operator-pairing-panel]');
  const form = document.querySelector<HTMLFormElement>('[data-operator-pairing-form]');
  const input = document.querySelector<HTMLInputElement>('[data-operator-pairing-code]');
  const submit = document.querySelector<HTMLButtonElement>('[data-operator-pairing-submit]');
  const message = document.querySelector<HTMLElement>('[data-operator-pairing-status]');
  const cancel = document.querySelector<HTMLButtonElement>('[data-operator-pairing-cancel]');
  if (!panel || !form || !input || !submit || !message || !cancel) {
    throw new Error('Missing operator pairing interface');
  }

  let stopped = false;
  let busy = false;
  let paired = false;
  let pairInFlight = false;
  let activated = false;
  let generation = 0;
  let app: OperatorPairingApp | void;
  let activePair: Promise<void> | null = null;
  let closePromise: Promise<void> | null = null;
  const lifetime = new AbortController();
  panel.hidden = false;
  cancel.hidden = true;
  submit.disabled = true;
  message.textContent = '正在确认本机配对状态…';

  const activate = () => {
    if (stopped || activated) return;
    activated = true;
    paired = true;
    form.hidden = true;
    cancel.hidden = false;
    message.textContent = privateDevice
      ? '此设备已配对。刷新会重新开始此设备的临时会话；另一台设备不受影响。结束配对后，需重启服务获取新代码。'
      : localOnly
      ? '本次本机管理配对已确认。撤销配对或关闭工具后，需重新启动本机工具获取新配对文件。'
      : '本次本机配对已确认。停止回应并结束本次配对后，需重新启动本机应用获取新配对文件。';
    try { app = options.onPaired(); }
    catch {
      stopped = true;
      cancel.disabled = true;
      message.textContent = localOnly
        ? '配对已确认，但本机管理界面无法启动。请关闭页面和本机工具，再重新启动并读取新的私有配对文件。'
        : '配对已确认，但本地界面无法启动。请关闭本页和本机 MIRA 服务，再重新启动并读取新的私有配对文件。';
    }
  };

  const ready = (async () => {
    try {
      const status = await readStatus(fetcher, deadlineMs);
      if (stopped) return;
      if (!status.required) { message.textContent = UNAVAILABLE; return; }
      if (status.revoked) {
        form.hidden = true;
        message.textContent = '本次配对已撤销，不能再次使用。请重新启动本机 MIRA 服务，并亲自读取新的私有配对文件。';
        return;
      }
      if (status.paired) { activate(); return; }
      submit.disabled = false;
      message.textContent = '每次启动都请亲自打开本机私有配对文件，读取一次性代码并在下方密码框输入。不要把代码放进网址、聊天或其他应用。此步骤不能防止同一操作系统账户下的恶意软件读取页面或控制浏览器。';
    } catch {
      if (!stopped) { form.hidden = true; message.textContent = UNAVAILABLE; }
    }
  })();

  form.addEventListener('submit', event => {
    event.preventDefault();
    if (stopped || busy || submit.disabled) return;
    const code = input.value;
    input.value = '';
    if (!code.trim()) {
      message.textContent = '请从本机私有配对文件手动输入一次性代码。';
      return;
    }
    busy = true;
    pairInFlight = true;
    submit.disabled = true;
    cancel.hidden = false;
    cancel.disabled = false;
    message.textContent = '正在提交本次配对…';
    const requestGeneration = generation;
    const requestBody = JSON.stringify({code});
    const request = (async () => {
      try {
        const result = await postPair(fetcher, requestBody, deadlineMs, lifetime.signal);
        if (!stopped && requestGeneration === generation) {
          if (result === 'paired') activate();
          else message.textContent = result === 'checkpoint_upgrade' ? CHECKPOINT_UPGRADE : PAIR_FAILED;
        }
      } catch {
        if (!stopped && requestGeneration === generation) message.textContent = PAIR_FAILED;
      } finally {
        pairInFlight = false;
        busy = false;
        activePair = null;
        if (!activated) cancel.hidden = true;
      }
    })();
    activePair = request;
  });

  const cancelAndRevoke = (keepalive = false): Promise<void> => {
    if (closePromise) return closePromise;
    stopped = true;
    generation++;
    lifetime.abort();
    input.value = '';
    form.hidden = true;
    submit.disabled = true;
    cancel.disabled = true;
    message.textContent = '正在本地停止并结束本次配对…';
    closePromise = (async () => {
      const pendingPair = activePair;
      if (app) {
        try { await app.stopAndClose(); } catch { /* Local stop has been requested; still attempt server revocation. */ }
        app = undefined;
      }
      if (paired || pairInFlight) {
        if (pendingPair) await pendingPair;
        try {
          const revoked = await postWithoutBody(fetcher, REVOKE_PATH, undefined, deadlineMs, undefined, keepalive);
          if (!revoked) throw new Error('operator revoke was not confirmed');
          paired = false;
        message.textContent = localOnly
          ? '本机管理访问已撤销。需要继续时，请重新启动本机工具并读取新的私有配对文件。'
          : '本次回应已停止，配对已撤销。需要继续时，请重新启动本机 MIRA 服务并读取新的私有配对文件。';
        } catch { message.textContent = REVOKE_FAILED; }
      } else {
        message.textContent = '本次配对已取消。要重新开始，请刷新页面并亲自读取本机私有配对文件。';
      }
    })();
    return closePromise;
  };
  cancel.addEventListener('click', () => { void cancelAndRevoke(); });
  const onPageHide = () => {
    if (privateDevice && paired && !pairInFlight) {
      // Preserve only the existing bounded browser grant. A subsequent create
      // atomically retires this owner's old session if unload cleanup is lost.
      stopped = true; generation++; lifetime.abort(); input.value = '';
      if (app) void app.stopAndClose();
      app = undefined;
      return;
    }
    void cancelAndRevoke(true);
  };
  document.defaultView?.addEventListener('pagehide', onPageHide, {once: true});

  return {
    ready,
    cancelAndRevoke: () => cancelAndRevoke(),
    close: () => cancelAndRevoke(true),
  };
}
