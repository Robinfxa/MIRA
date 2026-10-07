import type {OperatorPairingApp, OperatorPairingGate} from './operator-pairing.js';

interface TrustedDeviceOptions {
  readonly fetcher?: typeof fetch;
  readonly onReady: () => OperatorPairingApp | void;
  readonly deadlineMs?: number;
}

/** No pairing claim: the server issues an ephemeral browser ownership cookie. */
export function mountTrustedDeviceAccess(document: Document, options: TrustedDeviceOptions): OperatorPairingGate {
  const panel = document.querySelector<HTMLElement>('[data-trusted-device-panel]');
  const status = document.querySelector<HTMLElement>('[data-trusted-device-status]');
  const close = document.querySelector<HTMLButtonElement>('[data-trusted-device-close]');
  if (!panel || !status || !close) throw new Error('Missing trusted device interface');
  const fetcher = options.fetcher ?? globalThis.fetch;
  let stopped = false;
  let admitted = false;
  let app: OperatorPairingApp | void;
  let closing: Promise<void> | null = null;
  panel.hidden = false;
  close.disabled = false;
  status.textContent = '可信局域网免配对：正在建立此浏览器的临时会话…';

  const post = async (path: string, keepalive = false): Promise<number> => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => { abort.abort(); reject(new Error('device access timed out')); }, options.deadlineMs ?? 5000);
    });
    try {
      const response = await Promise.race([fetcher(path, {method: 'POST', credentials: 'include',
        cache: 'no-store', redirect: 'error', signal: abort.signal, keepalive}), deadline]);
      return response.status;
    } finally { if (timer !== undefined) clearTimeout(timer); }
  };

  const ready = (async () => {
    try {
      const code = await post('/api/v1/devices/bootstrap', true);
      admitted = code === 204;
      if (stopped) return;
      if (!admitted) {
        status.textContent = code === 429
          ? '已有 16 个浏览器占用临时名额。请在其中一个页面结束此设备会话，或重启服务后刷新。清除浏览器数据不会立即释放旧名额。'
          : '无法建立临时会话。请确认服务和局域网地址正确，再刷新页面；尚未启动对话。';
        return;
      }
      status.textContent = '可信局域网免配对已连接。刷新会清空此设备对话，其他设备不受影响；访问失效时请刷新页面。';
      app = options.onReady();
    } catch {
      if (!stopped) status.textContent = '临时会话未能启动。请刷新页面；若名额已满，请结束其他设备会话或重启服务。';
    }
  })();

  const cancelAndRevoke = (keepalive = false): Promise<void> => {
    if (closing) return closing;
    stopped = true;
    close.disabled = true;
    status.textContent = '正在停止回应并结束此设备会话…';
    closing = (async () => {
      if (app) {
        try { await app.stopAndClose(); } catch { /* Still retire the server identity. */ }
        app = undefined;
      }
      // An admission already in flight can set a cookie. Wait for its bounded
      // result, then retire it; a late response must never start the controller.
      await ready;
      try {
        const code = await post('/api/v1/devices/revoke', keepalive);
        if (code !== 204 && !(code === 401 && !admitted)) throw new Error('revoke unavailable');
        admitted = false;
        status.textContent = '此设备会话已结束。需要继续时刷新页面即可；其他设备不受影响。';
      } catch {
        status.textContent = '本地回应已停止，但无法确认服务端会话结束。请关闭页面，必要时重启服务。';
      }
    })();
    return closing;
  };
  close.addEventListener('click', () => { void cancelAndRevoke(); });
  document.defaultView?.addEventListener('pagehide', () => {
    if (admitted && !stopped) {
      stopped = true;
      if (app) void app.stopAndClose();
      app = undefined;
    } else { void cancelAndRevoke(true); }
  }, {once: true});
  return {ready, cancelAndRevoke: () => cancelAndRevoke(), close: () => cancelAndRevoke(true)};
}
