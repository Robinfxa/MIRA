export class MiraTransportError extends Error {
    code;
    deadlineMs;
    constructor(code, deadlineMs) {
        super(code === 'request_cancelled'
            ? 'Request cancelled: session closed or operation superseded.'
            : code === 'request_timeout'
                ? `服务请求超时${deadlineMs === undefined ? '' : `（等待上限 ${deadlineMs / 1000} 秒）`}。本次操作结果未确认，请检查连接与页面状态后再决定是否重试。`
                : '连接意外中断。本次操作结果未确认，请检查连接与页面状态；持续发生时导出脱敏诊断。');
        this.code = code;
        this.deadlineMs = deadlineMs;
        this.name = 'MiraTransportError';
    }
}
export function isAbortFailure(error) {
    return typeof error === 'object' && error !== null && 'name' in error
        && (error.name === 'AbortError' || error.name === 'TimeoutError');
}
export function classifyTransportFailure(error, signal, timeout, closed = false) {
    // AbortSignal.any retains the first cause, even if another owner aborts later.
    if (signal.aborted && signal.reason === timeout)
        return timeout;
    if (signal.aborted || closed)
        return new MiraTransportError('request_cancelled');
    return classifyUnexpectedAbort(error);
}
export function classifyUnexpectedAbort(error) {
    if (isAbortFailure(error)) {
        return new MiraTransportError(error.name === 'TimeoutError'
            ? 'request_timeout' : 'request_aborted');
    }
    return error; // HTTP, malformed-body and ordinary network failures remain failures.
}
