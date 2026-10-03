"""Safe, bounded speech failures. Never carry upstream bodies or exception strings."""
import asyncio
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


class SpeechProviderError(RuntimeError):
    def __init__(self, code: SpeechErrorCode | str):
        self.code = SpeechErrorCode(code)
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


def http_error(status: int) -> SpeechProviderError:
    return SpeechProviderError({400: "invalid_input", 401: "unauthenticated",
                                403: "permission_denied", 408: "timeout",
                                429: "quota_exhausted", 504: "timeout"}.get(status, "unavailable"))


async def close_stream(resource, *, preserve_error: bool) -> None:
    """Close owned iterators without leaking cleanup exception text or masking cancellation."""
    close = getattr(resource, "aclose", None)
    if close is not None:
        try:
            await close()
        except Exception as error:
            if not preserve_error:
                raise safe_error(error) from None
