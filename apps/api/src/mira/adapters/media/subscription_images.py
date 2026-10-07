"""Offline-tested internal Codex image wire; not a public subscription API.

This adapter does not establish account entitlement. Explicit bootstrap admission
owns route/data/budget choice. API generation is a separate adapter, never fallback.
"""
import asyncio
import base64
import binascii
import json
import math
import re
from uuid import uuid4
import zlib

import httpx

from mira.adapters.generation.direct_codex_responses import CodexCredentialSource
from mira.application.ports.media import GeneratedImage, MediaRequest
from ._openai_http import (
    PNG_SIGNATURE, ImageProviderError, RequestFence, strict_json, validate_request,
)
from ._subscription_auth import subscription_headers

SUBSCRIPTION_IMAGE_ENDPOINT = 'https://chatgpt.com/backend-api/codex/images/generations'
SUBSCRIPTION_IMAGE_MODEL = 'gpt-image-2'


class SubscriptionImageBackend:
    def __init__(self, *, credential_source: CodexCredentialSource,
                 transport: httpx.AsyncBaseTransport | None = None,
                 timeout_seconds: float = 90.0, max_wire_bytes: int = 12_000_000):
        if not callable(getattr(credential_source, 'get_credentials', None)):
            raise ValueError('image_subscription_credentials_required')
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 120):
            raise ValueError('image_timeout_invalid')
        if type(max_wire_bytes) is not int or not 1024 <= max_wire_bytes <= 12_000_000:
            raise ValueError('image_wire_limit_invalid')
        if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
            raise ValueError('image_transport_invalid')
        self._credential_source = credential_source
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._max_wire_bytes = max_wire_bytes

    async def generate(self, request: MediaRequest) -> GeneratedImage:
        validate_request(request, subscription=True)
        fence = RequestFence(self._timeout_seconds)
        fence.check()
        # Pinned Codex DTO supports these fields. Its tool uses size=auto/n=None;
        # these constrained values preserve MIRA's contract but remain live-unverified.
        encoded = json.dumps({
            'model': SUBSCRIPTION_IMAGE_MODEL, 'prompt': request.specification,
            'background': 'opaque', 'quality': 'auto', 'size': '1024x1024', 'n': 1,
        }, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(encoded) > 32_768:
            raise ImageProviderError('image_request_bytes')
        try:
            async with asyncio.timeout_at(fence.deadline) as timeout:
                fence.timeout = timeout
                headers = await subscription_headers(self._credential_source, fence=fence)
                fence.check()
                headers.update({'Content-Type': 'application/json', 'Accept': 'application/json',
                                'Accept-Encoding': 'identity, gzip',
                                'x-codex-image-turn-id': str(uuid4())})
                async with httpx.AsyncClient(
                    transport=self._transport, trust_env=False, follow_redirects=False,
                    timeout=httpx.Timeout(self._timeout_seconds,
                                          connect=min(10, self._timeout_seconds)),
                ) as client:
                    fence.check()
                    async with client.stream('POST', SUBSCRIPTION_IMAGE_ENDPOINT,
                                             content=encoded, headers=headers) as response:
                        fence.check()
                        raw = await self._read_response(response, fence)
                        fence.check()
                    fence.check()
                fence.check()
            fence.check()
        except (TimeoutError, httpx.TimeoutException):
            fence.check()
            raise ImageProviderError('image_http_timeout') from None
        except ImageProviderError:
            fence.check()
            raise
        except Exception:
            fence.check()
            raise ImageProviderError('image_http_transport') from None
        fence.check()
        result = self._parse_image(raw, request)
        fence.check()
        return result

    async def _read_response(self, response: httpx.Response, fence: RequestFence) -> bytes:
        if response.status_code != 200:
            raise ImageProviderError('image_http_status')
        mime = response.headers.get('content-type')
        # The native client parses JSON without requiring MIME. Missing MIME is
        # compatible; a contradictory explicit MIME is a local fail-closed guard.
        if mime is not None and mime.split(';', 1)[0].strip().lower() != 'application/json':
            raise ImageProviderError('image_http_content_type')
        encoding = response.headers.get('content-encoding', 'identity').strip().lower()
        if encoding not in ('identity', 'gzip'):
            raise ImageProviderError('image_http_encoding')
        length = response.headers.get('content-length')
        if length is not None and (not re.fullmatch(r'[0-9]{1,9}', length)
                                   or int(length) > self._max_wire_bytes):
            raise ImageProviderError('image_http_content_length')
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == 'gzip' else None
        raw = bytearray()
        wire_bytes = 0
        async for part in response.aiter_raw():
            fence.check()
            wire_bytes += len(part)
            if wire_bytes > self._max_wire_bytes:
                raise ImageProviderError('image_http_wire_limit')
            if decoder is None:
                raw.extend(part)
            else:
                pending = part
                while pending:
                    fence.check()
                    try:
                        decoded = decoder.decompress(
                            pending, min(65_536, self._max_wire_bytes - len(raw) + 1))
                    except zlib.error:
                        raise ImageProviderError('image_http_encoding') from None
                    if len(raw) + len(decoded) > self._max_wire_bytes:
                        raise ImageProviderError('image_http_decoded_limit')
                    raw.extend(decoded)
                    if decoder.unused_data:
                        raise ImageProviderError('image_http_encoding')
                    pending = decoder.unconsumed_tail
            fence.check()
        if decoder is not None and (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail):
            raise ImageProviderError('image_http_encoding')
        if length is not None and int(length) != wire_bytes:
            raise ImageProviderError('image_http_content_length')
        fence.check()
        return bytes(raw)

    def _parse_image(self, raw: bytes, request: MediaRequest) -> GeneratedImage:
        body = strict_json(raw)
        if type(body) is not dict:
            raise ImageProviderError('image_generation_envelope')
        self._check_completion(body)
        if type(body.get('created')) is not int or not 0 <= body['created'] < 2**64:
            raise ImageProviderError('image_generation_created')
        if (body.get('background') not in (None, 'opaque', 'transparent', 'auto')
                or body.get('quality') not in (None, 'auto', 'low', 'medium', 'high')
                or (body.get('size') is not None and type(body['size']) is not str)):
            raise ImageProviderError('image_generation_incomplete')
        items = body.get('data')
        if type(items) is not list or len(items) != 1 or type(items[0]) is not dict:
            raise ImageProviderError('image_generation_count')
        item = items[0]
        self._check_completion(item)
        generation_id = item.get('generation_id')
        if generation_id is not None and type(generation_id) is not str:
            raise ImageProviderError('image_generation_resource')
        encoded = item.get('b64_json')
        limit = 4 * ((request.max_output_bytes + 2) // 3)
        if type(encoded) is not str or not encoded or len(encoded) > limit:
            raise ImageProviderError('image_base64_limit')
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ImageProviderError('image_base64_invalid') from None
        if base64.b64encode(data).decode('ascii') != encoded:
            raise ImageProviderError('image_base64_invalid')
        if not data or len(data) > request.max_output_bytes or not data.startswith(PNG_SIGNATURE):
            raise ImageProviderError('image_generation_bytes')
        # Bytes remain untrusted until the existing downstream PillowPngDecoder.
        # This DTO supplies no quota/price/usage proof or provider resource identity.
        return GeneratedImage(data, 'image/png', 'chatgpt_subscription',
                              SUBSCRIPTION_IMAGE_MODEL, None)

    @staticmethod
    def _check_completion(value: dict) -> None:
        # Rust serde ignores additional metadata. Preserve that compatibility
        # inside the decoded-body cap, while never ignoring explicit failure,
        # partial-image semantics. A passive URL is never followed or trusted;
        # missing b64_json still fails. Actual dimensions/alpha belong to Pillow.
        if (value.get('error') is not None or value.get('refusal') is not None
                or value.get('incomplete_details') is not None
                or value.get('partial_image_b64') is not None
                or value.get('status') not in (None, 'completed')
                or value.get('output_format') not in (None, 'png')):
            raise ImageProviderError('image_generation_incomplete')
