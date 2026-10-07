"""Stable user-facing messages. Never inspect exception bodies or stringify providers."""
from dataclasses import dataclass

from mira.application.diagnostic_events import DiagnosticCode


@dataclass(frozen=True, slots=True)
class SafeFailure:
    code: DiagnosticCode
    message: str
    action: str


_MESSAGES = {
    DiagnosticCode.STORY_CHECKPOINT_PENDING: ("角色经历尚未确认保存。", "请保留当前页面；重试同一呈现回执可核对写入结果，切勿当作已经保存。"),
    DiagnosticCode.UNAUTHENTICATED: ("服务身份验证未通过。", "检查服务登录或凭据配置后重试。"),
    DiagnosticCode.PERMISSION_DENIED: ("服务拒绝了此操作。", "检查该服务的项目、权限与可用范围后重试。"),
    DiagnosticCode.QUOTA_EXHAUSTED: ("服务暂时达到使用限制。", "稍后重试，或检查服务配额。"),
    DiagnosticCode.TIMEOUT: ("服务响应超时。", "请重试；也可以先使用文字输入。"),
    DiagnosticCode.UNAVAILABLE: ("服务暂时不可用。", "检查连接与服务状态后重试。"),
    DiagnosticCode.TRANSPORT_CONNECT: ("审核服务连接失败。", "稍后重试；持续失败时导出脱敏诊断。"),
    DiagnosticCode.TRANSPORT_PROXY: ("审核服务代理连接失败。", "检查当前代理配置后重试。"),
    DiagnosticCode.TRANSPORT_PROTOCOL: ("审核服务通信协议失败。", "检查服务状态后重试。"),
    DiagnosticCode.TRANSPORT_READ: ("读取审核服务响应失败。", "稍后重试；持续失败时导出脱敏诊断。"),
    DiagnosticCode.TRANSPORT_WRITE: ("发送审核服务请求失败。", "稍后重试；持续失败时导出脱敏诊断。"),
    DiagnosticCode.CODEX_STARTUP_READONLY_FILESYSTEM: (
        "本地模型启动遇到只读文件系统。", "检查模型运行配置；持续失败时导出脱敏诊断。"),
    DiagnosticCode.INVALID_INPUT: ("输入无法处理。", "缩短输入或重新录音后重试。"),
    DiagnosticCode.INVALID_RESPONSE: ("服务返回的内容无法处理。", "请重试；持续失败时导出脱敏诊断。"),
    DiagnosticCode.INVALID_AUDIO: ("音频格式或内容无法处理。", "重新录音，或改用文字输入。"),
    DiagnosticCode.EMPTY_AUDIO: ("没有收到可用音频。", "检查麦克风后重新录音，或改用文字输入。"),
    DiagnosticCode.LIMIT_REACHED: ("本次操作达到资源限制。", "缩短输入或重新开始会话。"),
    DiagnosticCode.BLOCKED: ("此内容未获准呈现。", "调整内容后重试。"),
    DiagnosticCode.CANCELLED: ("本次操作已停止。", "可以继续输入或开始新一轮。"),
    DiagnosticCode.DISCONNECTED: ("连接已断开。", "重新连接后重试；旧输出不会继续播放。"),
    DiagnosticCode.MEMORY_CONTEXT_STALE: (
        "本轮记忆上下文已变化，未发出新的内容许可。", "请重试本轮，或暂时关闭记忆召回。"),
    DiagnosticCode.MEMORY_CONTEXT_OVERFLOW: (
        "必需的记忆上下文超过安全长度，未发出许可。", "整理必需的记忆边界后重试。"),
    DiagnosticCode.MEMORY_TIMEOUT: (
        "本机记忆读取超时，未发出新的内容许可。", "请重试，或暂时关闭记忆召回。"),
    DiagnosticCode.MEMORY_UNAVAILABLE: (
        "本机记忆上下文暂时不可用，未发出新的内容许可。", "检查本机记忆设置后重试。"),
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
                   "stale_chapter_choice": "cancelled", "chapter_choice_unavailable": "cancelled",
                   "media_cancelled": "cancelled", "review_not_allowed": "blocked",
                   "memory_context_stale": "memory_context_stale",
                   "memory_context_overflow": "memory_context_overflow",
                   "memory_timeout": "memory_timeout", "memory_unavailable": "memory_unavailable",
                   "review_uncertain": "unknown",
                   "review_request_too_large": "limit_reached",
                   "review_budget_exhausted": "limit_reached",
                   "generation_budget_exhausted": "limit_reached",
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
    "stale_chapter_choice", "chapter_choice_unavailable",
    "story_checkpoint_pending",
    "audio_failed", "audio_interrupted", "after_stop_fence", "audio_history_capacity", "audio_non_monotonic", "audio_receipt_required",
    "audio_terminal", "busy", "duplicate_effect", "effect_capacity", "empty_audio", "empty_generation",
    "history_pending", "incomplete_stream", "input_limit", "invalid_audio", "invalid_audio_progress", "invalid_cutoff",
    "invalid_effect", "invalid_input", "invalid_range", "invalid_response", "media_cancelled",
    "microphone_unavailable", "not_speech", "output_limit", "receipt_conflict", "receipt_mismatch",
    "receipt_sequence", "request_conflict", "review_not_allowed", "session_capacity", "session_closed",
    "session_not_found", "speech_consumed", "speech_not_granted", "speech_unavailable", "stale_activity",
    "stream_consumed", "unknown_effect", "generation_timeout", "generation_failed", "response_limit",
    "unsupported_audio", "blocked", "unauthenticated", "permission_denied", "quota_exhausted",
    "timeout", "unavailable", "review_uncertain", "codex_startup_readonly_filesystem",
    "review_request_too_large", "review_budget_exhausted", "generation_budget_exhausted",
    "memory_context_stale", "memory_context_overflow", "memory_timeout", "memory_unavailable",
})


def public_error_code(code) -> str:
    """Never return arbitrary provider-supplied strings through the wire error channel."""
    return code if type(code) is str and code in _PUBLIC_CODES else "unknown"


_PROVIDER_REASONS = {
    "jev_input_authentication_failed": "unauthenticated", "jev_input_forbidden": "permission_denied",
    "jev_input_request_invalid": "invalid_input", "jev_input_rate_limited": "quota_exhausted",
    "jev_input_overloaded": "unavailable", "jev_input_timeout": "timeout",
    "jev_input_transport_error": "unavailable", "jev_input_response_invalid": "invalid_response",
    "jev_input_transport_connect_error": "transport_connect",
    "jev_input_transport_proxy_error": "transport_proxy",
    "jev_input_transport_protocol_error": "transport_protocol",
    "jev_input_transport_read_error": "transport_read",
    "jev_input_transport_write_error": "transport_write",
    "jev_input_transport_timeout_error": "timeout",
    "jev_authentication_failed": "unauthenticated", "jev_forbidden": "permission_denied",
    "jev_request_invalid": "invalid_input", "jev_rate_limited": "quota_exhausted",
    "jev_overloaded": "unavailable", "jev_service_error": "unavailable",
    "jev_timeout": "timeout", "jev_transport_error": "unavailable",
    "jev_transport_connect_error": "transport_connect",
    "jev_transport_proxy_error": "transport_proxy",
    "jev_transport_protocol_error": "transport_protocol",
    "jev_transport_read_error": "transport_read",
    "jev_transport_write_error": "transport_write",
    "jev_transport_timeout_error": "timeout",
    "jev_response_contract_invalid": "invalid_response", "jev_semantic_reject": "blocked",
    "jev_request_too_large": "limit_reached", "jev_input_request_too_large": "limit_reached",
    "jev_request_budget_exhausted": "limit_reached", "jev_input_budget_exhausted": "limit_reached",
    "semantic_input_invalid_response": "invalid_response",
    "codex_timeout": "timeout", "codex_transport_failed": "unavailable",
    "codex_transport_closed": "unavailable", "codex_transport_eof": "unavailable",
    "codex_budget_exhausted": "limit_reached", "codex_output_limit": "limit_reached",
    "codex_line_limit": "limit_reached", "codex_wire_limit": "limit_reached",
    "codex_prompt_limit": "limit_reached", "codex_json_invalid": "invalid_response",
    "codex_effects_invalid": "invalid_response", "codex_not_admitted": "blocked",
    "codex_startup_readonly_filesystem": "codex_startup_readonly_filesystem",
}


_JEV_TRANSPORT_REASONS = frozenset({
    "jev_transport_error", "jev_timeout",
    "jev_input_transport_error", "jev_input_timeout",
    *(f"jev_transport_{cause}_error" for cause in
      ("connect", "proxy", "protocol", "read", "write", "timeout")),
    *(f"jev_input_transport_{cause}_error" for cause in
      ("connect", "proxy", "protocol", "read", "write", "timeout")),
})


_SEMANTIC_UNCERTAINTY_REASONS = frozenset({
    # Only genuine, well-formed semantic judgments may use the conversational skip.
    # Keep adapter/configuration/contract failures out of this list.
    "jev_semantic_unknown",
    "jev_user_development_0_6_v1_unknown",
    "jev_user_development_0_6_v2_unknown",
    "jev_input_semantic_unknown",
})


def is_semantic_uncertainty_reason(reason: object) -> bool:
    """True only for fixed JEV semantic UNKNOWN decisions, never generic UNKNOWN."""
    return type(reason) is str and reason in _SEMANTIC_UNCERTAINTY_REASONS


def is_jev_transport_reason(reason: object) -> bool:
    """True only for fixed JEV transport outcomes, including legacy generic codes."""
    return type(reason) is str and reason in _JEV_TRANSPORT_REASONS


def jev_resource_failure_code(reason: object) -> str | None:
    """Only local adapter size/count guards, never provider content or uncertainty."""
    mapping = {
        "jev_request_too_large": "review_request_too_large",
        "jev_input_request_too_large": "review_request_too_large",
        "jev_request_budget_exhausted": "review_budget_exhausted",
        "jev_input_budget_exhausted": "review_budget_exhausted",
    }
    return mapping.get(reason) if type(reason) is str else None


def classify_reason(reason) -> SafeFailure:
    """Only predeclared adapter reason codes; never a provider body or free-text guess."""
    return failure_for(_PROVIDER_REASONS.get(reason, "unknown") if type(reason) is str else "unknown")
