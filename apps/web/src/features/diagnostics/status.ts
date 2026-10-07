import type { PublicConfig } from '../../shared/config.js';
import { parseDiagnosticId } from '../../shared/protocol.js';
import type { DiagnosticsStatusResponse } from '../../shared/generated/contracts.js';

export function parseDiagnosticsStatus(raw: unknown): DiagnosticsStatusResponse {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Diagnostics status unavailable');
  const value = raw as Record<string, unknown>;
  const keys = ['available', 'recording_active', 'notice', 'dropped_events', 'dropped_recordings', 'io_failures', 'pending_records'];
  if (Object.keys(value).some(key => !keys.includes(key)) || typeof value['available'] !== 'boolean'
    || typeof value['recording_active'] !== 'boolean' || typeof value['notice'] !== 'string' || value['notice'].length > 500
    || ['dropped_events', 'dropped_recordings', 'io_failures', 'pending_records'].some(key =>
      typeof value[key] !== 'number' || !Number.isSafeInteger(value[key]) || (value[key] as number) < 0)) {
    throw new Error('Diagnostics status unavailable');
  }
  return Object.freeze({...value}) as unknown as DiagnosticsStatusResponse;
}

export function recordingNotice(status: DiagnosticsStatusResponse | null): {visible: boolean; text: string; state: string} {
  if (!status) return {visible: true, state: 'unknown', text: '开发录制状态尚未确认，请勿输入秘密。互动仍可继续。'};
  if (status.recording_active) return {visible: true, state: 'active', text: '开发录制中：通过隐私过滤的对话和模型内容可能保存在本机。音频仅在单独隐私审核后保存。请勿输入秘密。'};
  if (!status.available || status.io_failures > 0 || status.dropped_events > 0) {
    return {visible: true, state: 'degraded', text: '原始录制已关闭；部分诊断日志暂不可用或已丢弃。互动仍可继续。'};
  }
  return {visible: false, text: '', state: 'off'};
}

export function watchDiagnosticsStatus(config: PublicConfig,
  render: (status: DiagnosticsStatusResponse | null) => void,
  primitives: {fetch?: typeof fetch; setTimeout?: (fn: () => void, ms: number) => number;
    clearTimeout?: (id: number) => void} = {}): {close: () => void} {
  const fetcher = primitives.fetch ?? globalThis.fetch;
  const later = primitives.setTimeout ?? ((fn, ms) => globalThis.setTimeout(fn, ms));
  const cancelTimer = primitives.clearTimeout ?? (id => globalThis.clearTimeout(id));
  let closed = false, timer: number | undefined, pending: AbortController | null = null;
  render(null);
  async function read(): Promise<void> {
    if (closed) return;
    pending = new AbortController();
    const abort = pending;
    const deadline = later(() => abort.abort(), 5000);
    try {
      const response = await fetcher(config.apiBase + '/diagnostics-status', {
        method: 'GET', signal: abort.signal, cache: 'no-store', redirect: 'error',
      });
      if (!response.ok) throw new Error('Diagnostics status unavailable');
      const value = parseDiagnosticsStatus(await response.json());
      if (!closed && !abort.signal.aborted) render(value);
    } catch {
      if (!closed) render(null);
    } finally {
      cancelTimer(deadline);
      if (pending === abort) pending = null;
      if (!closed) timer = later(() => { void read(); }, 2000);
    }
  }
  void read();
  return {close() {
    if (closed) return;
    closed = true;
    if (timer !== undefined) cancelTimer(timer);
    pending?.abort();
    pending = null;
  }};
}

export function parseHttpRequestId(value: unknown): string | null {
  return typeof value === 'string' && value.length === 36
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value) ? value : null;
}

export function safeHttpError(status: number, requestId: string | null, code: string | null = null): string {
  const messages: Record<number, string> = {
    400: '输入无法处理，请检查后重试。', 401: '服务身份验证未通过，请检查登录或凭据配置。',
    403: '此操作未获允许，请检查来源与服务权限。', 404: '会话已不可用，请刷新重建。',
    408: '请求超时，请重试。', 409: '操作与当前会话状态冲突，请停止后重试。',
    413: '输入超过大小限制，请缩短后重试。', 422: '输入不符合要求，请检查后重试。',
    429: '暂时达到使用限制，请稍后重试或检查配额。',
    503: '服务暂不可用，可以先使用文字输入。', 504: '服务响应超时，请重试。',
  };
  const message = status === 429 && code === 'session_capacity'
    ? '本地会话达到容量限制。请结束当前或不用的会话，再刷新重建；重复提交本轮不会解除限制。'
    : messages[status] ?? '请求未完成，请重试；持续失败时导出脱敏诊断。';
  const locator = parseHttpRequestId(requestId);
  return message + (locator ? ` 诊断编号：${locator}` : '');
}

export function safeSessionError(code: unknown, diagnosticId?: unknown): string {
  const messages: Record<string, string> = {
    timeout: '服务响应超时，请重试。', generation_timeout: '生成超时，请重试。',
    generation_failed: '生成未完成，请重试；持续失败时导出脱敏诊断。',
    generation_budget_exhausted: '本次运行设置的模型请求次数已用完，未继续调用。重复发送或刷新页面不会恢复额度；请先核对启动时设置的请求上限。',
    memory_context_stale: '本地记忆在这一轮中发生变化，剩余响应已停止。请确认更正或忘记操作后重新提交。',
    memory_context_overflow: '本地记忆与当前输入超过上下文上限，不会静默丢弃必需信息。请缩短输入或整理已保存的边界后重试。',
    memory_timeout: '读取本地记忆超时，剩余响应已停止。请稍后重试；持续失败时导出脱敏诊断。',
    memory_unavailable: '本地记忆暂不可用，请检查所选数据库、作用域和私有配置后重试。',
    codex_startup_readonly_filesystem: '本地模型启动遇到只读文件系统，请检查模型运行配置；持续失败时导出脱敏诊断。',
    unauthenticated: '服务身份验证未通过，请检查服务登录或凭据配置。',
    permission_denied: '服务拒绝了此操作，请检查权限与可用范围。',
    quota_exhausted: '服务达到使用限制，请稍后重试或检查配额。',
    unavailable: '服务暂不可用，请稍后重试。',
    review_not_allowed: '此内容未获准呈现，请调整输入后重试。',
    review_uncertain: '未能确认此响应适合呈现，本轮未呈现。可以调整请求后重试。',
    review_request_too_large: '本轮审核内容超过大小上限，未发送给服务。请缩短输入或新建会话。',
    review_budget_exhausted: '本次运行的审核请求额度已用完，未继续调用。请先核对启动时的请求和费用上限。',
    invalid_response: '服务返回格式无法处理，剩余输出已停止。查看诊断编号；持续失败时导出脱敏诊断。',
    media_cancelled: '本次语音已停止，可以继续输入。', invalid_audio: '音频无法处理，请重新录音或使用文字。',
    empty_audio: '没有收到可用音频，请检查麦克风或使用文字。',
    audio_failed: '音频播放失败，请重试或继续使用文字。',
    audio_interrupted: '音频已停止，可以继续使用文字。',
    microphone_unavailable: '语音识别未配置，可以继续使用文字。',
    speech_unavailable: '角色语音未配置，可以继续阅读文字。',
  };
  const message = typeof code === 'string' && Object.hasOwn(messages, code) ? messages[code]!
    : '本次操作未完成，请重试；持续失败时导出脱敏诊断。';
  const locator = parseDiagnosticId(diagnosticId);
  return message + (locator ? ` 诊断编号：${locator}` : '');
}
