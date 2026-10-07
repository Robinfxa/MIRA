from __future__ import annotations

import contextlib
import json
import socket
import ssl

import httpcore
import httpx
import pytest
from tools import provider_login
from mira.adapters.auth import openai_codex as m

SECRET = 'secret-body-header-proxy-password-user-devicecode-token'


def test_first_post_connect_failure_is_distinct_and_safe(tmp_path):
    seen = []
    inner = ssl.SSLCertVerificationError(1, SECRET)
    inner.verify_code = 20
    def handler(request):
        seen.append(request)
        error = httpx.ConnectError(SECRET, request=request)
        error.__cause__ = inner
        raise error
    store = m.CodexSessionStore(tmp_path / 'unopened' / 'session.json', transport=httpx.MockTransport(handler))
    with pytest.raises(m.CodexAuthError) as caught:
        store.begin_device_login(on_user_code=lambda *_: pytest.fail('code must not display'))
    fields = caught.value.safe_diagnostic()
    assert fields['operation'] == 'device_code_request'
    assert fields['phase'] == 'request_headers'
    assert fields['category'] == 'exception'
    assert 'tls_certificate' in fields['categories']
    assert fields['exception_chain'][-1]['ssl_verify_code'] == 20
    assert SECRET not in json.dumps(fields)
    assert str(caught.value) == 'oauth_network_error'
    assert len(seen) == 1 and seen[0].method == 'POST'
    assert json.loads(seen[0].content) == {'client_id': m.CODEX_OAUTH_CLIENT_ID}
    assert not store.path.parent.exists()


def test_response_body_failure_retains_phase_status_not_body(tmp_path):
    class BrokenBody(httpx.SyncByteStream):
        def __iter__(self):
            yield SECRET.encode()
            raise httpx.ReadError(SECRET)
    def handler(request):
        return httpx.Response(200, stream=BrokenBody(), headers={'x-secret': SECRET}, request=request)
    store = m.CodexSessionStore(tmp_path / 'session.json', transport=httpx.MockTransport(handler))
    with pytest.raises(m.CodexAuthError) as caught:
        store.begin_device_login()
    fields = caught.value.safe_diagnostic()
    assert fields['phase'] == 'response_body'
    assert fields['http_status'] == 200
    assert fields['categories'] == ['read']
    assert SECRET not in json.dumps(fields)


@pytest.mark.parametrize('inner, category', [
    (ssl.SSLError(1, SECRET), 'tls'), (socket.gaierror(-2, SECRET), 'dns'),
    (httpcore.ProxyError(SECRET), 'proxy'), (httpcore.ConnectTimeout(SECRET), 'connect_timeout'),
    (httpcore.ReadTimeout(SECRET), 'read_timeout'), (httpx.WriteTimeout(SECRET), 'write_timeout'),
    (httpx.PoolTimeout(SECRET), 'pool_timeout'), (ConnectionRefusedError(61, SECRET), 'connection_refused'),
    (ConnectionResetError(54, SECRET), 'connection_reset'),
])
def test_cause_labels_are_fixed_and_cycle_bounded(inner, category):
    error = httpx.ConnectError(SECRET)
    error.__cause__ = inner
    inner.__context__ = error
    fields = m._safe_exception_fields(error)
    assert category in fields['categories']
    assert len(fields['exception_chain']) == 2
    assert SECRET not in json.dumps(fields)


def test_unknown_exception_name_messages_and_invalid_numbers_never_printed():
    cls = type(SECRET, (Exception,), {})
    error = cls(SECRET)
    assert SECRET not in json.dumps(m._safe_exception_fields(error))
    inner = ssl.SSLCertVerificationError(1, SECRET)
    inner.verify_code = SECRET
    assert 'ssl_verify_code' not in m._safe_exception_fields(inner)['exception_chain'][0]


def test_chain_is_bounded():
    error = httpx.ConnectError(SECRET)
    root = error
    for _ in range(30):
        error.__cause__ = httpx.ConnectError(SECRET)
        error = error.__cause__
    fields = m._safe_exception_fields(root)
    assert len(fields['exception_chain']) == 16
    assert fields['chain_truncated'] is True


def test_cli_prints_filtered_diagnostic_only(monkeypatch, capsys):
    payload = {'operation': SECRET, 'phase': SECRET, 'category': SECRET,
               'exception_chain': [{'type': SECRET, 'errno': SECRET}],
               'categories': [SECRET], 'http_status': SECRET, 'body': SECRET}
    error = m.CodexAuthError('oauth_network_error', diagnostic=payload)
    class Store:
        path = 'synthetic-local-store'
        def __init__(self, *_): pass
        def begin_device_login(self, **_): raise error
    monkeypatch.setattr(provider_login, 'CodexSessionStore', Store)
    monkeypatch.setattr('builtins.input', lambda _: 'LOGIN')
    assert provider_login.main(['login']) == 2
    output = capsys.readouterr()
    assert SECRET not in output.err + output.out
    data = json.loads(output.err.split('MIRA OAuth diagnostic: ', 1)[1])
    assert data['diagnostic'] == 'mira_oauth_failure_v1'
    assert data['operation'] == 'unknown' and data['phase'] == 'unknown'


def test_cancel_still_sends_nothing(monkeypatch, capsys):
    monkeypatch.setattr('builtins.input', lambda _: 'NO')
    monkeypatch.setattr(m.CodexSessionStore, 'begin_device_login', lambda **_: pytest.fail('unexpected login'))
    assert provider_login.main(['login']) == 0
    assert 'MIRA OAuth diagnostic' not in capsys.readouterr().err


@pytest.mark.parametrize('where', ['client_initialization', 'response_close', 'client_close'])
def test_other_request_phases_are_preserved(monkeypatch, tmp_path, where):
    class Response:
        status_code = 200
        headers = {}
        request = httpx.Request('POST', m.CODEX_DEVICE_CODE_URL)
        def iter_bytes(self): yield b'{}'
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args):
            if where == 'client_close': raise httpx.CloseError(SECRET)
        @contextlib.contextmanager
        def stream(self, *args, **kwargs):
            yield Response()
            if where == 'response_close': raise httpx.CloseError(SECRET)
    store = m.CodexSessionStore(tmp_path / 'unopened' / 'session.json')
    def client():
        if where == 'client_initialization': raise OSError(2, SECRET)
        return Client()
    monkeypatch.setattr(store, '_client', client)
    with pytest.raises(m.CodexAuthError) as caught:
        store.begin_device_login()
    assert caught.value.safe_diagnostic()['phase'] == where
    assert SECRET not in json.dumps(caught.value.safe_diagnostic())
