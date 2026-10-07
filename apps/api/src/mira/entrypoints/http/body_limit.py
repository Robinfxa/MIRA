"""Bound actual ASGI request bytes before routing; never trust framing headers alone."""
from __future__ import annotations

import asyncio
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BoundedRequestBody:
    """Small JSON API boundary, including unknown-length bodies and slow senders."""

    def __init__(self, app: ASGIApp, *, max_bytes: int = 32_768,
                 timeout_seconds: float = 5.0, max_chunks: int = 1_024) -> None:
        if (type(max_bytes) is not int or not 1 <= max_bytes <= 32_768
                or type(timeout_seconds) not in (int, float)
                or not 0 < timeout_seconds <= 5
                or type(max_chunks) is not int or not 1 <= max_chunks <= 1_024):
            raise ValueError('invalid_request_body_limits')
        self.app, self.max_bytes = app, max_bytes
        self.timeout_seconds, self.max_chunks = timeout_seconds, max_chunks

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        body = bytearray()
        error = None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                deadline = asyncio.get_running_loop().time() + self.timeout_seconds
                for _ in range(self.max_chunks):
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError
                    message = await receive()
                    if message.get('type') == 'http.disconnect':
                        return  # Client gone; do not open a private route or invent a result.
                    chunk = message.get('body', b'')
                    more = message.get('more_body', False)
                    if message.get('type') != 'http.request' or type(chunk) is not bytes or type(more) is not bool:
                        error = ('invalid_request', 400, 'Invalid request body.')
                        break
                    if len(body) + len(chunk) > self.max_bytes:
                        error = ('body_limit', 413, 'Request too large; shorten the input.')
                        break
                    body.extend(chunk)
                    if not more:
                        break
                else:
                    error = ('body_limit', 413, 'Request body has too many fragments.')
        except TimeoutError:
            error = ('body_timeout', 408, 'Request body did not arrive in time.')
        if error is not None:
            code, status, message = error
            request_id = str(uuid4())
            response = JSONResponse({'code': code, 'message': message, 'request_id': request_id},
                status_code=status, headers={'X-Request-ID': request_id, 'Cache-Control': 'no-store',
                                             'X-Content-Type-Options': 'nosniff'})
            await response(scope, receive, send)
            return
        complete_body = bytes(body)
        replayed = False

        async def bounded_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {'type': 'http.request', 'body': complete_body, 'more_body': False}
            return await receive()

        await self.app(scope, bounded_receive, send)
