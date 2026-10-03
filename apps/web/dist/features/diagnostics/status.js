import { parseDiagnosticId } from '../../shared/protocol.js';
export function parseDiagnosticsStatus(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw))
        throw new Error('Diagnostics status unavailable');
    const value = raw;
    const keys = ['available', 'recording_active', 'notice', 'dropped_events', 'dropped_recordings', 'io_failures', 'pending_records'];
    if (Object.keys(value).some(key => !keys.includes(key)) || typeof value['available'] !== 'boolean'
        || typeof value['recording_active'] !== 'boolean' || typeof value['notice'] !== 'string' || value['notice'].length > 500
        || ['dropped_events', 'dropped_recordings', 'io_failures', 'pending_records'].some(key => typeof value[key] !== 'number' || !Number.isSafeInteger(value[key]) || value[key] < 0)) {
        throw new Error('Diagnostics status unavailable');
    }
    return Object.freeze({ ...value });
}
export function recordingNotice(status) {
    if (!status)
        return { visible: true, state: 'unknown', text: '开发录制状态尚未确认，请勿输入秘密。互动仍可继续。' };
    if (status.recording_active)
        return { visible: true, state: 'active', text: '开发录制中：通过隐私过滤的对话和模型内容可能保存在本机。音频仅在单独隐私审核后保存。请勿输入秘密。' };
    if (!status.available || status.io_failures > 0 || status.dropped_events > 0) {
        return { visible: true, state: 'degraded', text: '原始录制已关闭；部分诊断日志暂不可用或已丢弃。互动仍可继续。' };
    }
    return { visible: false, text: '', state: 'off' };
}
export function watchDiagnosticsStatus(config, render, primitives = {}) {
    const fetcher = primitives.fetch ?? globalThis.fetch;
    const later = primitives.setTimeout ?? ((fn, ms) => globalThis.setTimeout(fn, ms));
    const cancelTimer = primitives.clearTimeout ?? (id => globalThis.clearTimeout(id));
    let closed = false, timer, pending = null;
    render(null);
    async function read() {
        if (closed)
            return;
        pending = new AbortController();
        const abort = pending;
        const deadline = later(() => abort.abort(), 5000);
        try {
            const response = await fetcher(config.apiBase + '/diagnostics-status', {
                method: 'GET', signal: abort.signal, cache: 'no-store', redirect: 'error',
            });
            if (!response.ok)
                throw new Error('Diagnostics status unavailable');
            const value = parseDiagnosticsStatus(await response.json());
            if (!closed && !abort.signal.aborted)
                render(value);
        }
        catch {
            if (!closed)
                render(null);
        }
        finally {
            cancelTimer(deadline);
            if (pending === abort)
                pending = null;
            if (!closed)
                timer = later(() => { void read(); }, 2000);
        }
    }
    void read();
    return { close() {
            if (closed)
                return;
            closed = true;
            if (timer !== undefined)
                cancelTimer(timer);
            pending?.abort();
            pending = null;
        } };
}
export function safeHttpError(status, requestId) {
    const messages = {
        400: '输入无法处理，请检查后重试。', 401: '服务身份验证未通过，请检查登录或凭据配置。',
        403: '此操作未获允许，请检查来源与服务权限。', 404: '会话已不可用，请刷新重建。',
        408: '请求超时，请重试。', 409: '操作与当前会话状态冲突，请停止后重试。',
        413: '输入超过大小限制，请缩短后重试。', 422: '输入不符合要求，请检查后重试。',
        429: '暂时达到使用限制，请稍后重试或检查配额。',
        503: '服务暂不可用，可以先使用文字输入。', 504: '服务响应超时，请重试。',
    };
    const message = messages[status] ?? '请求未完成，请重试；持续失败时导出脱敏诊断。';
    return message + (requestId && requestId.length === 36 && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(requestId)
        ? ` 诊断编号：${requestId}` : '');
}
export function safeSessionError(code, diagnosticId) {
    const messages = {
        timeout: '服务响应超时，请重试。', generation_timeout: '生成超时，请重试。',
        generation_failed: '生成未完成，请重试；持续失败时导出脱敏诊断。',
        unauthenticated: '服务身份验证未通过，请检查服务登录或凭据配置。',
        permission_denied: '服务拒绝了此操作，请检查权限与可用范围。',
        quota_exhausted: '服务达到使用限制，请稍后重试或检查配额。',
        unavailable: '服务暂不可用，请稍后重试。', review_not_allowed: '此内容未获准呈现，请调整输入后重试。',
        media_cancelled: '本次语音已停止，可以继续输入。', invalid_audio: '音频无法处理，请重新录音或使用文字。',
        empty_audio: '没有收到可用音频，请检查麦克风或使用文字。',
        audio_failed: '音频播放失败，请重试或继续使用文字。',
        audio_interrupted: '音频已停止，可以继续使用文字。',
        microphone_unavailable: '语音识别未配置，可以继续使用文字。',
        speech_unavailable: '角色语音未配置，可以继续阅读文字。',
    };
    const message = typeof code === 'string' && Object.hasOwn(messages, code) ? messages[code]
        : '本次操作未完成，请重试；持续失败时导出脱敏诊断。';
    const locator = parseDiagnosticId(diagnosticId);
    return message + (locator ? ` 诊断编号：${locator}` : '');
}
//# sourceMappingURL=status.js.map