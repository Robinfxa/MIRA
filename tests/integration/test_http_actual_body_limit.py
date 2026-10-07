"""Actual ASGI bytes, rather than optional headers, bound untrusted JSON input."""
import asyncio
import json

import pytest

from mira.application.memory_management import MemoryManagement
from mira.application.ports.memory_management import MemoryManagementPage
from mira.entrypoints.http.local_memory_app import create_local_memory_app
from mira.entrypoints.http.operator_pairing import OperatorPairing

CODE = 'synthetic-body-limit-pairing-0123456789'
ORIGIN = 'http://127.0.0.1:8761'

class Backend:
    def __init__(self): self.opens = 0
    async def open(self): self.opens += 1
    async def scope_revision(self): return 0
    async def list_entries(self, **kwargs): return MemoryManagementPage(0, (), None)
    async def apply_operation(self, command): raise AssertionError('not required')
    async def aclose(self): pass

async def invoke(app, body, *, declared=None, chunk_bytes=10000):
    messages = []
    done = asyncio.Event()
    frames = [body[i:i+chunk_bytes] for i in range(0, len(body), chunk_bytes)] or [b'']
    index = 0
    async def receive():
        nonlocal index
        if index < len(frames):
            chunk = frames[index]; index += 1
            return {'type': 'http.request', 'body': chunk, 'more_body': index < len(frames)}
        await done.wait()
        return {'type': 'http.disconnect'}
    async def send(message):
        messages.append(message)
        if message['type'] == 'http.response.body' and not message.get('more_body', False): done.set()
    headers = [(b'host', b'127.0.0.1:8761'), (b'origin', ORIGIN.encode()),
               (b'content-type', b'application/json')]
    if declared is not None: headers.append((b'content-length', str(declared).encode()))
    await asyncio.wait_for(app({'type':'http', 'asgi':{'version':'3.0'}, 'http_version':'1.1',
        'method':'POST', 'scheme':'http', 'path':'/api/v1/operator/pair',
        'raw_path':b'/api/v1/operator/pair', 'query_string':b'', 'root_path':'',
        'headers':headers, 'client':('127.0.0.1',12345), 'server':('127.0.0.1',8761)},
        receive, send), 3)
    return next(v['status'] for v in messages if v['type']=='http.response.start'), b''.join(
        v.get('body', b'') for v in messages if v['type']=='http.response.body')

@pytest.mark.asyncio
@pytest.mark.parametrize('declared', [None, 10])
async def test_unknown_or_understated_length_never_bypasses_actual_body_cap(tmp_path, declared):
    backend = Backend()
    async def factory(): return await MemoryManagement(backend, authorized=True).open()
    app = create_local_memory_app(management_factory=factory,
        pairing=OperatorPairing(CODE, (ORIGIN,)), web_root=tmp_path)
    raw = json.dumps({'code':CODE}).encode()
    raw = raw[:-1] + b' ' * 40000 + b'}'
    async with app.router.lifespan_context(app):
        status, body = await invoke(app, raw, declared=declared)
        assert status == 413
        assert backend.opens == 0
        assert CODE.encode() not in body

@pytest.mark.asyncio
@pytest.mark.parametrize(('size','expected'), [(32768,204),(32769,413)])
async def test_actual_byte_boundary_is_inclusive_and_normal_chunking_works(tmp_path,size,expected):
    backend = Backend()
    async def factory(): return await MemoryManagement(backend, authorized=True).open()
    app = create_local_memory_app(management_factory=factory,
        pairing=OperatorPairing(CODE, (ORIGIN,)), web_root=tmp_path)
    raw = json.dumps({'code':CODE}).encode()
    raw = raw[:-1] + b' ' * (size-len(raw)) + b'}'
    async with app.router.lifespan_context(app):
        status, _ = await invoke(app, raw, chunk_bytes=1024)
        assert status == expected
        assert backend.opens == (1 if expected == 204 else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['timeout','too_many_chunks','disconnect'])
async def test_body_guard_bounds_incomplete_streams_before_downstream(mode):
    from mira.entrypoints.http.body_limit import BoundedRequestBody
    called = []
    sent = []
    async def downstream(*args): called.append(True)
    async def receive():
        if mode == 'timeout':
            await asyncio.Future()
        if mode == 'disconnect': return {'type':'http.disconnect'}
        return {'type':'http.request','body':b'', 'more_body':True}
    async def send(message): sent.append(message)
    guard = BoundedRequestBody(downstream, timeout_seconds=.01, max_chunks=3)
    await guard({'type':'http'}, receive, send)
    assert called == []
    if mode == 'disconnect': assert sent == []
    else:
        expected = 408 if mode == 'timeout' else 413
        assert next(v['status'] for v in sent if v['type']=='http.response.start') == expected


@pytest.mark.asyncio
async def test_body_guard_passes_websocket_and_does_not_consume_it():
    from mira.entrypoints.http.body_limit import BoundedRequestBody
    called = []
    async def downstream(scope, receive, send): called.append(scope['type'])
    async def forbidden(): raise AssertionError('websocket input consumed by HTTP guard')
    await BoundedRequestBody(downstream)({'type':'websocket'}, forbidden, forbidden)
    assert called == ['websocket']


def test_both_http_factories_install_the_same_actual_byte_boundary(settings, tmp_path):
    from mira.entrypoints.http.app import create_app
    from mira.entrypoints.http.body_limit import BoundedRequestBody
    normal = create_app(settings)
    local = create_local_memory_app(management_factory=lambda: None,
        pairing=OperatorPairing(CODE,(ORIGIN,)), web_root=tmp_path)
    for app in (normal,local):
        assert app.user_middleware[0].cls is BoundedRequestBody
