"""Stable user-facing messages. Never inspect exception bodies or stringify providers."""
from dataclasses import dataclass

from mira.application.diagnostic_events import DiagnosticCode


@dataclass(frozen=True, slots=True)
class SafeFailure:
    code: DiagnosticCode
    message: str
    action: str


_MESSAGES = {
    DiagnosticCode.UNAUTHENTICATED: ("服务身份验证未通过。", "检查服务登录或凭据配置后重试。"),
    DiagnosticCode.PERMISSION_DENIED: ("服务拒绝了此操作。", "检查该服务的项目、权限与可用范围后重试。"),
    DiagnosticCode.QUOTA_EXHAUSTED: ("服务暂时达到使用限制。", "稍后重试，或检查服务配额。"),
    DiagnosticCode.TIMEOUT: ("服务响应超时。", "请重试；也可以先使用文字输入。"),
    DiagnosticCode.UNAVAILABLE: ("服务暂时不可用。", "检查连接与服务状态后重试。"),
    DiagnosticCode.INVALID_INPUT: ("输入无法处理。", "缩短输入或重新录音后重试。"),
    DiagnosticCode.INVALID_RESPONSE: ("服务返回的内容无法处理。", "请重试；持续失败时导出脱敏诊断。"),
    DiagnosticCode.INVALID_AUDIO: ("音频格式或内容无法处理。", "重新录音，或改用文字输入。"),
    DiagnosticCode.EMPTY_AUDIO: ("没有收到可用音频。", "检查麦克风后重新录音，或改用文字输入。"),
    DiagnosticCode.LIMIT_REACHED: ("本次操作达到资源限制。", "缩短输入或重新开始会话。"),
    DiagnosticCode.BLOCKED: ("此内容未获准呈现。", "调整内容后重试。"),
    DiagnosticCode.CANCELLED: ("本次操作已停止。", "可以继续输入或开始新一轮。"),
    DiagnosticCode.DISCONNECTED: ("连接已断开。", "重新连接后重试；旧输出不会继续播放。"),
    DiagnosticCode.UNKNOWN: ("本次操作未完成，原因尚不明确。", "请重试；持续失败时导出脱敏诊断。"),
}


def failure_for(code: DiagnosticCode | str) -> SafeFailure:
    try:
        selected = DiagnosticCode(code)
    except (TypeError, ValueError):
        selected = DiagnosticCode.UNKNOWN
    message, action = _MESSAGES[selected]
    return SafeFailure(selected, message, action)


def classify_failure(error: BaseException | None = None, *,
                     http_status: int | None = None) -> SafeFailure:
    """Return observed failure class; 403 does not prove IAM vs billing vs entitlement."""
    mapping = {400: "invalid_input", 401: "unauthenticated", 403: "permission_denied",
               408: "timeout", 429: "quota_exhausted", 502: "unavailable",
               503: "unavailable", 504: "timeout"}
    if type(http_status) is int and http_status in mapping:
        return failure_for(mapping[http_status])
    if isinstance(error, TimeoutError):
        return failure_for("timeout")
    if isinstance(error, PermissionError):
        return failure_for("permission_denied")
    try:
        code = getattr(error, "code", None)
    except Exception:
        code = None
    if isinstance(code, str):
        aliases = {"generation_timeout": "timeout", "generation_failed": "unavailable",
                   "media_cancelled": "cancelled", "review_not_allowed": "blocked",
                   "response_limit": "limit_reached", "input_limit": "limit_reached",
                   "output_limit": "limit_reached", "session_capacity": "limit_reached",
                   "effect_capacity": "limit_reached", "incomplete_stream": "invalid_response",
                   "unsupported_audio": "invalid_audio", "microphone_permission_denied":
                   "permission_denied"}
        return failure_for(aliases.get(code, code))
    # Some adapters expose one fixed reason in args instead of a .code property.
    # Membership is exact; unknown args are neither rendered nor persisted.
    try:
        args = error.args if error is not None else ()
        if len(args) == 1 and type(args[0]) is str:
            return classify_reason(args[0])
    except Exception:
        pass
    return failure_for("unknown")


_PUBLIC_CODES = frozenset({
    "audio_failed", "audio_interrupted", "after_stop_fence", "audio_history_capacity", "audio_non_monotonic", "audio_receipt_required",
    "audio_terminal", "busy", "duplicate_effect", "effect_capacity", "empty_audio", "empty_generation",
    "history_pending", "incomplete_stream", "input_limit", "invalid_audio", "invalid_audio_progress", "invalid_cutoff",
    "invalid_effect", "invalid_input", "invalid_range", "invalid_response", "media_cancelled",
    "microphone_unavailable", "not_speech", "output_limit", "receipt_conflict", "receipt_mismatch",
    "receipt_sequence", "request_conflict", "review_not_allowed", "session_capacity", "session_closed",
    "session_not_found", "speech_consumed", "speech_not_granted", "speech_unavailable", "stale_activity",
    "stream_consumed", "unknown_effect", "generation_timeout", "generation_failed", "response_limit",
    "unsupported_audio", "blocked", "unauthenticated", "permission_denied", "quota_exhausted",
    "timeout", "unavailable",
})


def public_error_code(code) -> str:
    """Never return arbitrary provider-supplied strings through the wire error channel."""
    return code if type(code) is str and code in _PUBLIC_CODES else "unknown"


_PROVIDER_REASONS = {
    "jev_input_authentication_failed": "unauthenticated", "jev_input_forbidden": "permission_denied",
    "jev_input_request_invalid": "invalid_input", "jev_input_rate_limited": "quota_exhausted",
    "jev_input_overloaded": "unavailable", "jev_input_timeout": "timeout",
    "jev_input_transport_error": "unavailable", "jev_input_response_invalid": "invalid_response",
    "jev_authentication_failed": "unauthenticated", "jev_forbidden": "permission_denied",
    "jev_request_invalid": "invalid_input", "jev_rate_limited": "quota_exhausted",
    "jev_overloaded": "unavailable", "jev_service_error": "unavailable",
    "jev_timeout": "timeout", "jev_transport_error": "unavailable",
    "jev_response_contract_invalid": "invalid_response", "jev_semantic_reject": "blocked",
    "codex_timeout": "timeout", "codex_transport_failed": "unavailable",
    "codex_transport_closed": "unavailable", "codex_transport_eof": "unavailable",
    "codex_budget_exhausted": "limit_reached", "codex_output_limit": "limit_reached",
    "codex_line_limit": "limit_reached", "codex_wire_limit": "limit_reached",
    "codex_prompt_limit": "limit_reached", "codex_json_invalid": "invalid_response",
    "codex_effects_invalid": "invalid_response", "codex_not_admitted": "blocked",
}


def classify_reason(reason) -> SafeFailure:
    """Only predeclared adapter reason codes; never a provider body or free-text guess."""
    return failure_for(_PROVIDER_REASONS.get(reason, "unknown") if type(reason) is str else "unknown")
