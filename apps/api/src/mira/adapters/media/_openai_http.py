"""Small fixed-endpoint, bounded JSON transport. No credential/environment discovery."""
from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import math
import re

import httpx
from pydantic import SecretStr

from mira.application.ports.media import MediaRequest
from mira.domain.story_images import (REQUIRED_PIXEL_CHECKS, SQUARE_OUTPUT_POLICY,
    SUBSCRIPTION_OUTPUT_POLICY)

IMAGE_ENDPOINT = 'https://api.openai.com/v1/images/generations'
REVIEW_ENDPOINT = 'https://api.openai.com/v1/responses'
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
MAX_IMAGE_BYTES = 8_388_608
MAX_PROMPT_BYTES = 4096
MODEL_PATTERN = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}\Z')


class ImageProviderError(ValueError):
    """Fixed local failure code; provider bodies, prompts and credentials are never reflected."""


def strict_json(raw: bytes | str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ImageProviderError('image_json_duplicate')
            result[key] = value
        return result
    def invalid_constant(_):
        raise ImageProviderError('image_json_invalid')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, RecursionError, UnicodeError):
        raise ImageProviderError('image_json_invalid') from None


def bounded_text(value, maximum: int, *, empty: bool = False) -> bool:
    if type(value) is not str or (not value and not empty):
        return False
    try:
        return len(value.encode('utf-8')) <= maximum
    except UnicodeError:
        return False


def validate_request(request: MediaRequest, *, subscription: bool = False) -> None:
    if (not isinstance(request, MediaRequest)
            or type(request.output_dimension_policy) is not str
            or request.output_dimension_policy not in ((SQUARE_OUTPUT_POLICY, SUBSCRIPTION_OUTPUT_POLICY)
                if subscription else (SQUARE_OUTPUT_POLICY,))
            or (request.output_dimension_policy == SUBSCRIPTION_OUTPUT_POLICY
                and (type(request.policy_revision) is not str
                    or not request.policy_revision.endswith(':' + SUBSCRIPTION_OUTPUT_POLICY)))
            or not bounded_text(request.specification, MAX_PROMPT_BYTES)
            or request.allowed_resource_ids != ()
            or type(request.width) is not int or request.width != 1024
            or type(request.height) is not int or request.height != 1024
            or type(request.max_output_bytes) is not int
            or not 1 <= request.max_output_bytes <= MAX_IMAGE_BYTES
            or request.required_checks != REQUIRED_PIXEL_CHECKS
            or not bounded_text(request.request_id, 128)
            or not bounded_text(request.policy_revision, 128)
            or not bounded_text(request.admission_reference, 256)):
        raise ImageProviderError('image_request_invalid')
    if request.specification_digest != sha256(request.specification.encode('utf-8')).hexdigest():
        raise ImageProviderError('image_specification_binding')


class RequestFence:
    """Per-operation deadline/cancellation state, including uncooperative awaits.

    asyncio.timeout requests cancellation, but transport code can catch it. Check
    the owner's pending cancellation count and absolute clock after every await
    boundary and after parsing, so a late successful payload cannot become a result.
    This does not claim to forcibly terminate arbitrary code that never returns.
    """
    def __init__(self, seconds: float):
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        self.deadline = self._loop.time() + seconds
        self.timeout: asyncio.Timeout | None = None

    def check(self) -> None:
        timed_out = self.timeout is not None and self.timeout.expired()
        if self._task is not None and self._task.cancelling() and not timed_out:
            raise asyncio.CancelledError
        if timed_out or self._loop.time() >= self.deadline:
            raise ImageProviderError('image_http_timeout')
        if self._task is not None and self._task.cancelling():
            raise asyncio.CancelledError


class OpenAIJSONTransport:
    """One HTTP POST per call. A client is created only when explicitly invoked.

    Composition supplies a dedicated API key after route/data/budget admission.
    No subscription credential type or fallback route exists in this adapter.
    Injected transports are for tests or caller-managed networking and must not retry.
    """
    def __init__(self, *, api_key: SecretStr, endpoint: str,
                 transport: httpx.AsyncBaseTransport | None, timeout_seconds: float,
                 max_wire_bytes: int):
        if endpoint not in (IMAGE_ENDPOINT, REVIEW_ENDPOINT):
            raise ValueError('image_endpoint_invalid')
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 120):
            raise ValueError('image_timeout_invalid')
        if type(max_wire_bytes) is not int or not 1024 <= max_wire_bytes <= 12_000_000:
            raise ValueError('image_wire_limit_invalid')
        # Deliberately does not accept arbitrary strings/credential sources or OAuth tokens.
        if not isinstance(api_key, SecretStr):
            raise ValueError('image_api_key_invalid')
        value = api_key.get_secret_value()
        if not re.fullmatch(r'sk-[A-Za-z0-9_-]{8,512}', value):
            raise ValueError('image_api_key_invalid')
        self._api_key = api_key
        self._endpoint = endpoint
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._max_wire_bytes = max_wire_bytes

    def start(self) -> RequestFence:
        fence = RequestFence(self._timeout_seconds)
        fence.check()
        return fence

    async def post(self, body: dict, *, max_request_bytes: int, fence: RequestFence) -> dict:
        fence.check()
        encoded = json.dumps(body, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        if len(encoded) > max_request_bytes:
            raise ImageProviderError('image_request_bytes')
        try:
            async with asyncio.timeout_at(fence.deadline) as timeout:
                fence.timeout = timeout
                fence.check()
                async with httpx.AsyncClient(
                    transport=self._transport, trust_env=False, follow_redirects=False,
                    timeout=httpx.Timeout(self._timeout_seconds, connect=min(10, self._timeout_seconds)),
                ) as client:
                    fence.check()
                    async with client.stream('POST', self._endpoint, content=encoded, headers={
                        'Authorization': 'Bearer ' + self._api_key.get_secret_value(),
                        'Content-Type': 'application/json', 'Accept': 'application/json',
                        'Accept-Encoding': 'identity',
                    }) as response:
                        fence.check()
                        if response.status_code != 200:
                            raise ImageProviderError('image_http_status')
                        mime = response.headers.get('content-type', '').split(';', 1)[0].strip().lower()
                        if mime != 'application/json':
                            raise ImageProviderError('image_http_content_type')
                        if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                            raise ImageProviderError('image_http_encoding')
                        length = response.headers.get('content-length')
                        if length is not None and (not re.fullmatch(r'[0-9]{1,9}', length)
                                                   or int(length) > self._max_wire_bytes):
                            raise ImageProviderError('image_http_content_length')
                        raw = bytearray()
                        async for part in response.aiter_raw():
                            fence.check()
                            if len(raw) + len(part) > self._max_wire_bytes:
                                raise ImageProviderError('image_http_wire_limit')
                            raw.extend(part)
                        fence.check()
                        if length is not None and int(length) != len(raw):
                            raise ImageProviderError('image_http_content_length')
                    fence.check()  # Includes response/stream asynchronous cleanup.
                fence.check()  # Includes client/transport asynchronous cleanup.
            fence.check()
        except (TimeoutError, httpx.TimeoutException):
            fence.check()
            raise ImageProviderError('image_http_timeout') from None
        except httpx.HTTPError:
            fence.check()
            raise ImageProviderError('image_http_transport') from None
        except ImageProviderError:
            fence.check()
            raise
        fence.check()
        value = strict_json(bytes(raw))
        if type(value) is not dict:
            raise ImageProviderError('image_http_envelope')
        fence.check()
        return value
