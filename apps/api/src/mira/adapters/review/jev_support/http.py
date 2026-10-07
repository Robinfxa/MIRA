"""One fixed-origin POST, no retries, redirects, proxies or response logging."""
from __future__ import annotations

import httpx
from pydantic import SecretStr

from mira.adapters.review.jev import (
    MAX_REQUEST_BYTES,
    JevHttpResponse,
    JevResponseError,
    JevTransportError,
    JevTimeoutError,
)

SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
_ABSOLUTE_MAX_REQUEST_BYTES = 128 * 1024


def _httpx_transport_cause(error: httpx.HTTPError) -> str:
    """Classify only a known httpx exception type; never inspect its text or chain."""
    if isinstance(error, httpx.ProxyError):
        return "proxy"
    if isinstance(error, httpx.ConnectError):
        return "connect"
    if isinstance(error, httpx.ProtocolError):
        return "protocol"
    if isinstance(error, httpx.ReadError):
        return "read"
    if isinstance(error, httpx.WriteError):
        return "write"
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    return "unknown"


class HttpxJevTransport:
    """Caller injects the service secret; optional HTTP transport supports offline tests.

    Owns a fresh client per call. A supplied test transport must support that lifecycle.
    The default HTTP transport has zero retries. No secret or payload is in repr/errors.
    """

    def __init__(self, api_key: SecretStr, *, transport: httpx.AsyncBaseTransport | None = None,
                 max_request_bytes: int = MAX_REQUEST_BYTES):
        if (type(max_request_bytes) is not int
                or not 1024 <= max_request_bytes <= _ABSOLUTE_MAX_REQUEST_BYTES):
            raise ValueError("jev_request_limit_invalid")
        if type(api_key) is not SecretStr:
            raise ValueError("jev_credential_invalid")
        raw = api_key.get_secret_value()
        if not raw or len(raw) > 4096 or any(char.isspace() for char in raw):
            raise ValueError("jev_credential_invalid")
        self._api_key = api_key
        self._transport = transport
        self._max_request_bytes = max_request_bytes

    def with_max_request_bytes(self, max_request_bytes: int) -> HttpxJevTransport:
        """Bind one review's resolved ceiling without changing a shared transport."""
        return HttpxJevTransport(self._api_key, transport=self._transport,
                                 max_request_bytes=max_request_bytes)

    async def __call__(
        self, payload: bytes, *, timeout_seconds: float, max_response_bytes: int
    ) -> JevHttpResponse:
        if type(payload) is not bytes or len(payload) > self._max_request_bytes:
            raise JevTransportError("jev_request_invalid")
        try:
            async with httpx.AsyncClient(
                transport=(self._transport if self._transport is not None
                           else httpx.AsyncHTTPTransport(retries=0, trust_env=False)),
                trust_env=False, follow_redirects=False,
                timeout=httpx.Timeout(timeout_seconds),
            ) as client:
                async with client.stream(
                    "POST", SYSTEMONE_URL, content=payload,
                    headers={"Authorization": "Bearer " + self._api_key.get_secret_value(),
                             "Content-Type": "application/json", "Accept": "application/json",
                             "Accept-Encoding": "identity"},
                ) as response:
                    if response.status_code != 200:
                        return JevHttpResponse(response.status_code, b"")
                    if (response.headers.get("content-encoding", "identity").lower() != "identity"
                            or response.headers.get("content-type", "").split(";")[0]
                            .strip().lower()
                            != "application/json"):
                        raise JevResponseError("jev_response_encoding_invalid")
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(body) + len(chunk) > max_response_bytes:
                            raise JevResponseError("jev_response_too_large")
                        body.extend(chunk)
                    return JevHttpResponse(200, bytes(body))
        except httpx.TimeoutException as error:
            raise JevTimeoutError(cause_code=_httpx_transport_cause(error)) from None
        except httpx.HTTPError as error:
            raise JevTransportError("jev_transport_error",
                                    cause_code=_httpx_transport_cause(error)) from None
        except ValueError:
            raise JevTransportError("jev_transport_error") from None
