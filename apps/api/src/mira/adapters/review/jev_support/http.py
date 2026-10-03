"""One fixed-origin POST, no retries, redirects, proxies or response logging."""
from __future__ import annotations

import httpx
from pydantic import SecretStr

from mira.adapters.review.jev import (
    MAX_REQUEST_BYTES,
    JevHttpResponse,
    JevResponseError,
    JevTransportError,
)

SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"


class HttpxJevTransport:
    """Caller injects the service secret; optional HTTP transport supports offline tests.

    Owns a fresh client per call. A supplied test transport must support that lifecycle.
    The default HTTP transport has zero retries. No secret or payload is in repr/errors.
    """

    def __init__(self, api_key: SecretStr, *, transport: httpx.AsyncBaseTransport | None = None):
        if type(api_key) is not SecretStr:
            raise ValueError("jev_credential_invalid")
        raw = api_key.get_secret_value()
        if not raw or len(raw) > 4096 or any(char.isspace() for char in raw):
            raise ValueError("jev_credential_invalid")
        self._api_key = api_key
        self._transport = transport

    async def __call__(
        self, payload: bytes, *, timeout_seconds: float, max_response_bytes: int
    ) -> JevHttpResponse:
        if type(payload) is not bytes or len(payload) > MAX_REQUEST_BYTES:
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
        except httpx.TimeoutException:
            raise TimeoutError("jev_timeout") from None
        except (httpx.HTTPError, ValueError):
            raise JevTransportError("jev_transport_error") from None
