"""Safe, bounded speech failures. Never carry upstream bodies or exception strings."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from httpx import TimeoutException


class SpeechErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    INPUT_LIMIT = "input_limit"
    OUTPUT_LIMIT = "output_limit"
    INVALID_RESPONSE = "invalid_response"
    RESPONSE_LIMIT = "response_limit"
    INVALID_AUDIO = "invalid_audio"
    UNSUPPORTED_AUDIO = "unsupported_audio"
    EMPTY_AUDIO = "empty_audio"
    INCOMPLETE_STREAM = "incomplete_stream"
    BLOCKED = "blocked"
    UNAUTHENTICATED = "unauthenticated"
    PERMISSION_DENIED = "permission_denied"
    QUOTA_EXHAUSTED = "quota_exhausted"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


_SAFE_PROVIDER_STATUSES = frozenset({
    "INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
    "FAILED_PRECONDITION", "NOT_FOUND", "UNAVAILABLE", "DEADLINE_EXCEEDED",
})
_SAFE_PROVIDER_REASONS = frozenset({
    "INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
    "API_DISABLED", "SERVICE_DISABLED", "BILLING_DISABLED", "RATE_LIMIT_EXCEEDED",
    "QUOTA_EXCEEDED", "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "USER_PROJECT_DENIED",
})
_SAFE_DIAGNOSTICS = frozenset({
    "unknown_request_field", "unsupported_request_parameter", "invalid_request_value",
    "invalid_request_shape", "missing_request_field", "authentication_rejected",
    "authorization_rejected", "quota_rejected", "request_rejected", "invalid_voice",
    "unsupported_method", "unsupported_model",
})
_SAFE_FIELD_PATH = re.compile(r"[A-Za-z][A-Za-z0-9_.\[\]-]{0,127}\Z")
_SAFE_MEDIA_MIME = re.compile(r"[a-z0-9][a-z0-9.+-]{0,31}/[a-z0-9][a-z0-9.+-]{0,31}\Z")
_SAFE_PART_TYPES = frozenset({
    "inlineData", "text", "thought", "functionCall", "functionResponse", "videoMetadata",
    "executableCode", "codeExecutionResult", "fileData", "thoughtSignature",
})
_SAFE_FINISH_REASONS = frozenset({
    "STOP", "MAX_TOKENS", "SAFETY", "RECITATION", "OTHER", "BLOCKLIST",
    "PROHIBITED_CONTENT", "SPII", "IMAGE_PROHIBITED_CONTENT",
})
_SAFE_AUDIO_VALIDATION_REASONS = frozenset({
    "non_audio_part", "unsupported_mime_type", "unsupported_mime_parameter",
    "missing_audio_data", "audio_data_too_large", "invalid_base64",
    "odd_pcm_bytes", "wav_header",
})
_SAFE_MODEL_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")
_SAFE_MEDIA_PARAM_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}\Z")
_MESSAGE_FIELD_PATTERNS = (
    re.compile(r"(?:unknown|unrecognized) name\s+['\"]?([A-Za-z][A-Za-z0-9_.\[\]-]{0,127})['\"]?\s+at\s+['\"]?([A-Za-z][A-Za-z0-9_.\[\]-]{0,127})['\"]?", re.I),
    re.compile(r"(?:unknown|unrecognized|unsupported) field\s+['\"]?([A-Za-z][A-Za-z0-9_.\[\]-]{0,127})['\"]?", re.I),
    re.compile(r"unsupported (?:request )?parameter\s+['\"]?([A-Za-z][A-Za-z0-9_.\[\]-]{0,127})['\"]?", re.I),
    re.compile(r"invalid (?:value|parameter|voice)(?: for)?\s+['\"]?([A-Za-z][A-Za-z0-9_.\[\]-]{0,127})['\"]?", re.I),
)


def _normalize_provider_diagnostic(message: str | None, provider_status: str | None,
                                   field_names: tuple[str, ...]) -> str | None:
    """Reduce a provider message to a fixed category; never retain message text."""
    if provider_status == "UNAUTHENTICATED":
        return "authentication_rejected"
    if provider_status == "PERMISSION_DENIED":
        return "authorization_rejected"
    if provider_status == "RESOURCE_EXHAUSTED":
        return "quota_rejected"
    if message is None:
        return None
    if re.search(r"(?:unsupported|unknown|not found) method|method.+(?:not found|not supported)", message, re.I):
        return "unsupported_method"
    if (re.search(r"voice.+(?:invalid|unsupported|not found)|(?:invalid|unsupported) voice", message, re.I)
            or ("voice" in message.lower() and re.search(r"invalid value|not a valid", message, re.I))):
        return "invalid_voice"
    if re.search(r"model.+(?:invalid|unsupported|not found)|(?:invalid|unsupported) model", message, re.I):
        return "unsupported_model"
    if re.search(r"unknown name|unknown field|unrecognized name|cannot find field", message, re.I):
        return "unknown_request_field"
    if re.search(r"unsupported|not supported", message, re.I):
        return "unsupported_request_parameter"
    if re.search(r"missing|required field|field.+required", message, re.I):
        return "missing_request_field"
    if re.search(r"invalid json|malformed|parse error|invalid request shape", message, re.I):
        return "invalid_request_shape"
    if re.search(r"invalid value|expected .+ but got|out of range", message, re.I):
        return "invalid_request_value"
    if field_names and provider_status == "INVALID_ARGUMENT":
        return "invalid_request_value"
    return "request_rejected"


def _extract_message_field_names(message: str | None) -> tuple[str, ...]:
    if not message:
        return ()
    found: list[str] = []
    for pattern in _MESSAGE_FIELD_PATTERNS:
        for match in pattern.finditer(message):
            groups = [item for item in match.groups() if item]
            if len(groups) == 2 and groups[1] and groups[1] not in groups[0].split("."):
                name = f"{groups[1]}.{groups[0]}"
            else:
                name = groups[0]
            if _SAFE_FIELD_PATH.fullmatch(name) and name not in found:
                found.append(name)
            if len(found) >= 8:
                return tuple(found)
    return tuple(found)


def parse_provider_error_details(http_status: int, body: bytes, *, truncated: bool = False,
                                 capture_status: str = "parsed") -> ProviderErrorDetails:
    """Extract bounded codes/field paths only; raw provider text is never returned."""
    if type(http_status) is not int or not 100 <= http_status <= 599:
        raise ValueError("Invalid provider HTTP status")
    if not isinstance(body, bytes) or len(body) > 8192 or type(truncated) is not bool:
        raise ValueError("Invalid provider error body bounds")
    if capture_status not in {"parsed", "unparsed", "timeout", "unavailable"}:
        raise ValueError("Invalid provider body capture state")
    provider_status = provider_reason = None
    field_names: tuple[str, ...] = ()
    diagnostic = None
    parsed_status = capture_status
    message = None
    try:
        data = json.loads(body) if body else None
    except (ValueError, UnicodeDecodeError, RecursionError):
        data = None
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        candidate_status = error.get("status")
        if isinstance(candidate_status, str) and candidate_status in _SAFE_PROVIDER_STATUSES:
            provider_status = candidate_status
        candidate_message = error.get("message")
        if isinstance(candidate_message, str):
            message = candidate_message[:8192]
        found_fields: list[str] = []
        details = error.get("details")
        if isinstance(details, list):
            for detail in details[:32]:
                if not isinstance(detail, dict):
                    continue
                reason = detail.get("reason")
                if isinstance(reason, str) and reason in _SAFE_PROVIDER_REASONS:
                    provider_reason = provider_reason or reason
                violations = detail.get("fieldViolations")
                if isinstance(violations, list):
                    for violation in violations[:16]:
                        if not isinstance(violation, dict):
                            continue
                        field = violation.get("field")
                        if (isinstance(field, str) and _SAFE_FIELD_PATH.fullmatch(field)
                                and field not in found_fields):
                            found_fields.append(field)
        if not found_fields:
            found_fields.extend(_extract_message_field_names(message))
        field_names = tuple(found_fields[:8])
        diagnostic = _normalize_provider_diagnostic(message, provider_status, field_names)
        parsed_status = "parsed"
    elif body:
        parsed_status = "unparsed"
    return ProviderErrorDetails(
        http_status=http_status, provider_status=provider_status,
        provider_reason=provider_reason, field_names=field_names,
        diagnostic=diagnostic, body_bytes_read=len(body),
        body_truncated=truncated, body_capture_status=parsed_status,
    )


@dataclass(frozen=True, slots=True)
class ProviderErrorDetails:
    """Allowlisted facts extracted from a small Google error body; never raw JSON."""

    http_status: int
    provider_status: str | None = None
    provider_reason: str | None = None
    field_names: tuple[str, ...] = ()
    diagnostic: str | None = None
    body_bytes_read: int = 0
    body_truncated: bool = False
    body_capture_status: str = "unavailable"

    def __post_init__(self) -> None:
        if type(self.http_status) is not int or not 100 <= self.http_status <= 599:
            raise ValueError("Invalid provider HTTP status")
        if self.provider_status is not None and self.provider_status not in _SAFE_PROVIDER_STATUSES:
            raise ValueError("Invalid provider status")
        if self.provider_reason is not None and self.provider_reason not in _SAFE_PROVIDER_REASONS:
            raise ValueError("Invalid provider reason")
        if (not isinstance(self.field_names, tuple) or len(self.field_names) > 8
                or any(not isinstance(name, str) or not _SAFE_FIELD_PATH.fullmatch(name)
                       for name in self.field_names)):
            raise ValueError("Invalid provider field paths")
        if self.diagnostic is not None and self.diagnostic not in _SAFE_DIAGNOSTICS:
            raise ValueError("Invalid provider diagnostic")
        if type(self.body_bytes_read) is not int or not 0 <= self.body_bytes_read <= 8192:
            raise ValueError("Invalid provider body size")
        if type(self.body_truncated) is not bool:
            raise ValueError("Invalid provider body truncation flag")
        if self.body_capture_status not in {"parsed", "unparsed", "timeout", "unavailable"}:
            raise ValueError("Invalid provider body capture state")


@dataclass(frozen=True, slots=True)
class SafeAudioDiagnostic:
    """Non-content response metadata; never contains audio samples or transcript text."""

    part_index: int | None = None
    part_type_names: tuple[str, ...] = ()
    mime_type: str | None = None
    mime_param_names: tuple[str, ...] = ()
    sample_rate_hz: int | None = None
    channels: int | None = None
    codec: str | None = None
    audio_data_chars: int | None = None
    candidate_finish_reason: str | None = None
    validation_reason: str | None = None
    pcm_byte_count: int | None = None
    wav_header: bool | None = None
    model_version: str | None = None
    input_token_count: int | None = None
    output_token_count: int | None = None
    total_token_count: int | None = None
    response_text_excerpt: str | None = None

    def __post_init__(self) -> None:
        if self.part_index is not None and (type(self.part_index) is not int or not 0 <= self.part_index < 256):
            raise ValueError("Invalid response part index")
        if (not isinstance(self.part_type_names, tuple) or len(self.part_type_names) > 8
                or any(part not in _SAFE_PART_TYPES for part in self.part_type_names)):
            raise ValueError("Invalid response part types")
        if self.mime_type is not None and (not isinstance(self.mime_type, str)
                                           or not _SAFE_MEDIA_MIME.fullmatch(self.mime_type)):
            raise ValueError("Invalid response MIME type")
        if (not isinstance(self.mime_param_names, tuple) or len(self.mime_param_names) > 8
                or any(not isinstance(param, str) or not _SAFE_MEDIA_PARAM_NAME.fullmatch(param)
                       for param in self.mime_param_names)):
            raise ValueError("Invalid response MIME parameters")
        if self.sample_rate_hz is not None and (type(self.sample_rate_hz) is not int or not 1000 <= self.sample_rate_hz <= 384000):
            raise ValueError("Invalid response sample rate")
        if self.channels is not None and (type(self.channels) is not int or not 1 <= self.channels <= 8):
            raise ValueError("Invalid response channel count")
        if self.codec is not None and self.codec not in {"pcm", "alaw", "mulaw", "unknown"}:
            raise ValueError("Invalid response audio codec")
        if self.audio_data_chars is not None and (type(self.audio_data_chars) is not int
                                                   or not 0 <= self.audio_data_chars <= 2 * 1024 * 1024):
            raise ValueError("Invalid encoded audio size")
        if self.candidate_finish_reason is not None and self.candidate_finish_reason not in _SAFE_FINISH_REASONS:
            raise ValueError("Invalid candidate finish reason")
        if self.validation_reason is not None and self.validation_reason not in _SAFE_AUDIO_VALIDATION_REASONS:
            raise ValueError("Invalid audio validation reason")
        if self.pcm_byte_count is not None and (type(self.pcm_byte_count) is not int
                                                or not 0 <= self.pcm_byte_count <= 2 * 1024 * 1024):
            raise ValueError("Invalid PCM byte count")
        if self.wav_header is not None and type(self.wav_header) is not bool:
            raise ValueError("Invalid WAV header flag")
        if self.model_version is not None and not _SAFE_MODEL_VERSION.fullmatch(self.model_version):
            raise ValueError("Invalid provider model version")
        for token_count in (self.input_token_count, self.output_token_count, self.total_token_count):
            if token_count is not None and (type(token_count) is not int or not 0 <= token_count <= 1_000_000):
                raise ValueError("Invalid provider token count")
        if self.response_text_excerpt is not None and (
                not isinstance(self.response_text_excerpt, str) or len(self.response_text_excerpt) > 512
                or any(ord(ch) < 32 and ch not in "\t\n\r" for ch in self.response_text_excerpt)):
            raise ValueError("Invalid provider text excerpt")


class SpeechProviderError(RuntimeError):
    def __init__(self, code: SpeechErrorCode | str, *, details: ProviderErrorDetails | None = None,
                 audio_details: SafeAudioDiagnostic | None = None):
        self.code = SpeechErrorCode(code)
        self.details = details
        self.audio_details = audio_details
        super().__init__(f"Google speech: {self.code.value}")


def raise_if_cancelled() -> None:
    task = asyncio.current_task()
    if task is not None and task.cancelling():
        raise asyncio.CancelledError


def safe_error(error: Exception) -> SpeechProviderError:
    if isinstance(error, SpeechProviderError):
        return error
    if isinstance(error, (TimeoutError, TimeoutException)):
        return SpeechProviderError("timeout")
    # gRPC exposes code(), API-core exceptions can expose an enum/int property.
    # Only recognized enum names/status integers cross this boundary.
    try:
        code = getattr(error, "code", None)
        code = code() if callable(code) else code
        name = getattr(code, "name", None)
    except Exception:
        code, name = None, None
    mapping = {"UNAUTHENTICATED": "unauthenticated", "PERMISSION_DENIED": "permission_denied",
               "RESOURCE_EXHAUSTED": "quota_exhausted", "DEADLINE_EXCEEDED": "timeout",
               "INVALID_ARGUMENT": "invalid_input", "NOT_FOUND": "unavailable"}
    if isinstance(name, str) and name in mapping:
        return SpeechProviderError(mapping[name])
    if isinstance(code, int):
        return http_error(code)
    return SpeechProviderError("unavailable")


def http_error(status: int, *, details: ProviderErrorDetails | None = None) -> SpeechProviderError:
    return SpeechProviderError({400: "invalid_input", 401: "unauthenticated",
                                403: "permission_denied", 408: "timeout",
                                429: "quota_exhausted", 504: "timeout"}.get(status, "unavailable"),
                               details=details)


async def close_stream(resource, *, preserve_error: bool) -> None:
    """Close owned iterators without leaking cleanup exception text or masking cancellation."""
    close = getattr(resource, "aclose", None)
    if close is not None:
        try:
            await close()
        except Exception as error:
            if not preserve_error:
                raise safe_error(error) from None
