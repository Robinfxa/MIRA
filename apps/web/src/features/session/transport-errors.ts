/** Transport-owned cancellation is classified by its signal, never by a browser message. */
export type MiraTransportFailureCode = 'request_timeout' | 'request_cancelled' | 'request_aborted';
export class MiraTransportError extends Error {
  constructor(readonly code: MiraTransportFailureCode, readonly deadlineMs?: number) {
    super(code === 'request_cancelled'
      ? 'Request cancelled: session closed or operation superseded.'
      : code === 'request_timeout'
      ? `服务请求超时${deadlineMs === undefined ? '' : `（等待上限 ${deadlineMs / 1000} 秒）`}。本次操作结果未确认，请检查连接与页面状态后再决定是否重试。`
      : '连接意外中断。本次操作结果未确认，请检查连接与页面状态；持续发生时导出脱敏诊断。');
    this.name = 'MiraTransportError';
  }
}
export function isAbortFailure(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'name' in error
    && (error.name === 'AbortError' || error.name === 'TimeoutError');
}
export function classifyTransportFailure(error: unknown, signal: AbortSignal,
    timeout: MiraTransportError, closed = false): unknown {
  // AbortSignal.any retains the first cause, even if another owner aborts later.
  if (signal.aborted && signal.reason === timeout) return timeout;
  if (signal.aborted || closed) return new MiraTransportError('request_cancelled');
  return classifyUnexpectedAbort(error);
}
export function classifyUnexpectedAbort(error: unknown): unknown {
  if (isAbortFailure(error)) {
    return new MiraTransportError((error as {name: string}).name === 'TimeoutError'
      ? 'request_timeout' : 'request_aborted');
  }
  return error; // HTTP, malformed-body and ordinary network failures remain failures.
}
